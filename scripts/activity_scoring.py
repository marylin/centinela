# One-off activity scoring for monitored places + candidates.
# Sources: USGS FDSN event catalog (public) and Open-Meteo flood API (GloFAS
# reanalysis, public). No keys, no warehouse. Writes JSON next to this script.
import json
import time
import urllib.request
import urllib.parse
from datetime import date, timedelta

TODAY = date(2026, 6, 10)
SEASON_MONTHS = (5, 6, 7)          # window around "this time of year"
SEASON_YEARS = range(2016, 2026)   # 10 prior years
FLOOD_START = "2015-01-01"
RADIUS_KM = 300
MIN_MAG = 4.5

PLACES = [
    # current registry (group kind noted)
    ("Cali", 3.4516, -76.5320, "current", "flood"),
    ("Yumbo", 3.5855, -76.4952, "current", "flood"),
    ("Jamundi", 3.2610, -76.5394, "current", "flood"),
    ("Neiva", 2.9273, -75.2819, "current", "flood"),
    ("Girardot", 4.3009, -74.8061, "current", "flood"),
    ("Honda", 5.2045, -74.7411, "current", "flood"),
    ("Lima", -12.046, -77.043, "current", "seismic"),
    ("Guatemala City", 14.6349, -90.5069, "current", "seismic"),
    ("Santiago", -33.4489, -70.6693, "current", "seismic"),
    ("Mexico City", 19.4326, -99.1332, "current", "seismic"),
    ("Port-au-Prince", 18.5944, -72.3074, "current", "seismic"),
    # candidates (city centers, as probed)
    ("Bogota", 4.7110, -74.0721, "candidate", "?"),
    ("Medellin", 6.2442, -75.5812, "candidate", "?"),
    ("Quito", -0.1807, -78.4678, "candidate", "?"),
    ("Guayaquil", -2.1700, -79.9224, "candidate", "?"),
    ("La Paz", -16.4897, -68.1193, "candidate", "?"),
    ("San Salvador", 13.6929, -89.2182, "candidate", "?"),
    ("Managua", 12.1150, -86.2362, "candidate", "?"),
    ("Tegucigalpa", 14.0723, -87.1921, "candidate", "?"),
    ("Santo Domingo", 18.4861, -69.9312, "candidate", "?"),
    ("Kingston", 17.9712, -76.7936, "candidate", "?"),
    ("Buenos Aires", -34.6037, -58.3816, "candidate", "?"),
    ("Manaus", -3.1300, -60.0200, "candidate", "?"),
    # coordinate-tuning probe: mid-channel Rio Negro south of the Manaus port
    ("Manaus (river cell)", -3.1800, -60.0300, "probe", "?"),
]


def fetch_json(url, retries=3):
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "centinela-scoring/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if attempt == retries - 1:
                print(f"  FAILED {url[:90]}... -> {e}", flush=True)
                return None
            time.sleep(2 * (attempt + 1))


def usgs_events(lat, lng, start, end):
    """All M4.5+ events within RADIUS_KM between start and end (ISO dates)."""
    params = urllib.parse.urlencode({
        "format": "geojson", "latitude": lat, "longitude": lng,
        "maxradiuskm": RADIUS_KM, "minmagnitude": MIN_MAG,
        "starttime": start, "endtime": end, "limit": 20000,
    })
    data = fetch_json(f"https://earthquake.usgs.gov/fdsnws/event/1/query?{params}")
    if not data:
        return None
    out = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        if p.get("mag") is None or p.get("time") is None:
            continue
        d = date.fromtimestamp(p["time"] / 1000.0)
        out.append((d, float(p["mag"])))
    return out


def flood_series(lat, lng):
    params = urllib.parse.urlencode({
        "latitude": lat, "longitude": lng, "daily": "river_discharge",
        "start_date": FLOOD_START, "end_date": TODAY.isoformat(),
    })
    data = fetch_json(f"https://flood-api.open-meteo.com/v1/flood?{params}")
    if not data or "daily" not in data:
        return None
    days = data["daily"].get("time") or []
    vals = data["daily"].get("river_discharge") or []
    return [(date.fromisoformat(d), v) for d, v in zip(days, vals) if v is not None]


def percentile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def score_place(name, lat, lng, status, kind):
    print(f"== {name}", flush=True)
    rec = {"name": name, "lat": lat, "lng": lng, "status": status, "kind": kind}

    # --- seismic: recent 90 days ---
    recent_start = (TODAY - timedelta(days=90)).isoformat()
    recent = usgs_events(lat, lng, recent_start, TODAY.isoformat())
    if recent is not None:
        rec["quake_90d_count"] = len(recent)
        rec["quake_90d_maxmag"] = max((m for _, m in recent), default=None)

    # --- seismic: May-Jul across prior years, one bulk query then filter ---
    hist = usgs_events(lat, lng, f"{SEASON_YEARS.start}-01-01", f"{SEASON_YEARS.stop - 1}-12-31")
    if hist is not None:
        season = [(d, m) for d, m in hist if d.month in SEASON_MONTHS]
        rec["quake_season_total_10y"] = len(season)
        rec["quake_season_avg_per_year"] = round(len(season) / len(SEASON_YEARS), 1)
        rec["quake_season_maxmag"] = max((m for _, m in season), default=None)
        rec["quake_10y_total"] = len(hist)
        rec["quake_10y_maxmag"] = max((m for _, m in hist), default=None)

    # --- flood: GloFAS reanalysis since 2015 ---
    series = flood_series(lat, lng)
    if series:
        season_hist = sorted(v for d, v in series
                             if d.month in SEASON_MONTHS and d.year < TODAY.year)
        p50 = percentile(season_hist, 50)
        p90 = percentile(season_hist, 90)
        last60 = [v for d, v in series if d >= TODAY - timedelta(days=60)]
        rec["discharge_seasonal_p50"] = round(p50, 1) if p50 is not None else None
        rec["discharge_seasonal_p90"] = round(p90, 1) if p90 is not None else None
        rec["discharge_last60_max"] = round(max(last60), 1) if last60 else None
        if p90 and last60:
            rec["days_above_seasonal_p90_last60"] = sum(1 for v in last60 if v > p90)
            rec["last60_max_vs_p90"] = round(max(last60) / p90, 2) if p90 > 0 else None
        # rank this season's max against each prior year's May-Jul max
        year_maxes = {}
        for d, v in series:
            if d.month in SEASON_MONTHS:
                year_maxes[d.year] = max(year_maxes.get(d.year, 0.0), v)
        cur = year_maxes.get(TODAY.year)
        if cur is not None and len(year_maxes) > 1:
            prior = [v for y, v in year_maxes.items() if y < TODAY.year]
            rec["season_max_rank"] = 1 + sum(1 for v in prior if v > cur)
            rec["season_years_compared"] = len(prior) + 1
        rec["discharge_abs_scale"] = round(p50, 1) if p50 is not None else None

    # --- normalized scores (strongest-hazard style, like the app index) ---
    q_count = rec.get("quake_90d_count") or 0
    q_mag = rec.get("quake_90d_maxmag") or 0
    seismic = 0.0
    if q_count:
        seismic = min(1.0, 0.55 * min(1.0, q_count / 15.0)
                      + 0.45 * min(1.0, max(0.0, q_mag - 4.5) / 2.5))
    flood = 0.0
    days_ex = rec.get("days_above_seasonal_p90_last60") or 0
    ratio = rec.get("last60_max_vs_p90") or 0
    if days_ex or ratio:
        flood = min(1.0, 0.6 * min(1.0, days_ex / 15.0)
                    + 0.4 * min(1.0, max(0.0, ratio - 0.8) / 0.6))
    rec["seismic_score"] = round(seismic, 2)
    rec["flood_score"] = round(flood, 2)
    rec["activity_score"] = round(max(seismic, flood), 2)
    time.sleep(0.5)  # be polite to both APIs
    return rec


def main():
    results = [score_place(*p) for p in PLACES]
    results.sort(key=lambda r: r["activity_score"], reverse=True)
    out = {"computed": TODAY.isoformat(), "radius_km": RADIUS_KM, "min_mag": MIN_MAG,
           "season_months": list(SEASON_MONTHS), "results": results}
    with open("scripts/activity_scoring_results.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    hdr = (f"{'place':22} {'st':9} {'act':>4} {'seis':>4} {'fld':>4} "
           f"{'q90d':>4} {'mx90':>4} {'q/yr':>5} {'mxSe':>4} "
           f"{'exc60':>5} {'mxRt':>5} {'rank':>6}")
    print("\n" + hdr)
    print("-" * len(hdr))
    for r in results:
        rank = (f"{r['season_max_rank']}/{r['season_years_compared']}"
                if r.get("season_max_rank") else "-")
        print(f"{r['name']:22} {r['status']:9} {r['activity_score']:>4} "
              f"{r['seismic_score']:>4} {r['flood_score']:>4} "
              f"{r.get('quake_90d_count', '-'):>4} {r.get('quake_90d_maxmag') or '-':>4} "
              f"{r.get('quake_season_avg_per_year', '-'):>5} {r.get('quake_season_maxmag') or '-':>4} "
              f"{r.get('days_above_seasonal_p90_last60', '-'):>5} "
              f"{r.get('last60_max_vs_p90', '-'):>5} {rank:>6}")


if __name__ == "__main__":
    main()
