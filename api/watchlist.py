"""Candidate watchlist scoring.

Pure module: candidate pool config + activity scoring from two public sources
(USGS FDSN catalog, Open-Meteo flood API / GloFAS reanalysis). No network,
Firestore, or FastAPI work at import time; the caller (api.main) owns caching,
the background refresh, and the endpoint. Ported from the validated one-off
run in scripts/activity_scoring.py (results: docs/02-Requirements/
centinela-activity-scoring.md); composite weights kept identical.
"""
import time
from datetime import date, timedelta

import requests

RADIUS_KM = 300
MIN_MAG = 4.5
FLOOD_START = "2015-01-01"
HISTORY_YEARS = 10
USER_AGENT = "centinela-watchlist/1.0"
ATTRIBUTION = "USGS FDSN catalog + GloFAS reanalysis (Open-Meteo)"

# The candidate pool: names only, NOTHING coordinate-shaped. Coordinates and
# cell metadata are DERIVED at refresh time through the shared resolver
# (geocoded anchor + strongest-discharge GloFAS cell). aqi_covered marks
# VERIFIED Google AQI availability (probed 2026-06-10; unprobed = False, the
# badge simply does not show). Bogotá / Managua / Manaus were promoted into
# the monitored registry 2026-06-10; the pool is global, not LatAm-only. The six global candidates were promoted same-day.
CANDIDATES = [
    {"name": "Medellín", "country": "Colombia", "cc": "CO", "aqi_covered": True},
    {"name": "Quito", "country": "Ecuador", "cc": "EC", "aqi_covered": True},
    {"name": "Guayaquil", "country": "Ecuador", "cc": "EC", "aqi_covered": True},
    {"name": "La Paz", "country": "Bolivia", "cc": "BO", "aqi_covered": False},
    {"name": "San Salvador", "country": "El Salvador", "cc": "SV", "aqi_covered": False},
    {"name": "Tegucigalpa", "country": "Honduras", "cc": "HN", "aqi_covered": False},
    {"name": "Santo Domingo", "country": "Dominican Republic", "cc": "DO", "aqi_covered": False},
    {"name": "Kingston", "country": "Jamaica", "cc": "JM", "aqi_covered": False},
    {"name": "Buenos Aires", "country": "Argentina", "cc": "AR", "aqi_covered": True},
]


def season_months(today):
    """The dynamic seasonal window: current month +/-1, wrapping the year
    (December gives (11, 12, 1)). Replaces the one-off script's hardcoded
    May-July so the watchlist stays honest year-round. A December-centered
    window spans calendar years; the season-rank groups by the year each
    sample falls in, which is acceptable at this granularity."""
    m = today.month
    return (((m - 2) % 12) + 1, m, (m % 12) + 1)


def _fetch_json(url, params, timeout=10, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout,
                                headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt == retries - 1:
                print(f"Watchlist fetch failed ({url}): {e}", flush=True)
                return None
            time.sleep(2 * (attempt + 1))


def usgs_events(lat, lng, start, end):
    """All M4.5+ events within RADIUS_KM between two ISO dates, as
    (date, magnitude) tuples; None when the catalog is unreachable."""
    data = _fetch_json("https://earthquake.usgs.gov/fdsnws/event/1/query", {
        "format": "geojson", "latitude": lat, "longitude": lng,
        "maxradiuskm": RADIUS_KM, "minmagnitude": MIN_MAG,
        "starttime": start, "endtime": end, "limit": 20000,
    })
    if data is None:
        return None
    out = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        if p.get("mag") is None or p.get("time") is None:
            continue
        out.append((date.fromtimestamp(p["time"] / 1000.0), float(p["mag"])))
    return out


def flood_series(lat, lng, end):
    """Daily GloFAS discharge since FLOOD_START as (date, value) tuples."""
    data = _fetch_json("https://flood-api.open-meteo.com/v1/flood", {
        "latitude": lat, "longitude": lng, "daily": "river_discharge",
        "start_date": FLOOD_START, "end_date": end.isoformat(),
    }, timeout=30)
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


def score_place(candidate, today, months):
    """One RESOLVED candidate's metric row (the caller merges anchor/hydro
    coordinates in). Seismic samples the city anchor; flood samples the
    derived river cell. Metadata passes through; missing sources leave their
    metrics absent and their subscore at zero."""
    lat, lng = candidate["lat"], candidate["lng"]
    flood_lat = candidate.get("hydro_lat", lat)
    flood_lng = candidate.get("hydro_lng", lng)
    rec = dict(candidate)

    recent = usgs_events(lat, lng, (today - timedelta(days=90)).isoformat(),
                         today.isoformat())
    if recent is not None:
        rec["quake_90d_count"] = len(recent)
        rec["quake_90d_maxmag"] = max((m for _, m in recent), default=None)

    first_year = today.year - HISTORY_YEARS
    hist = usgs_events(lat, lng, f"{first_year}-01-01", f"{today.year - 1}-12-31")
    if hist is not None:
        season = [(d, m) for d, m in hist if d.month in months]
        rec["quake_season_avg_per_year"] = round(len(season) / HISTORY_YEARS, 1)
        rec["quake_season_maxmag"] = max((m for _, m in season), default=None)

    series = flood_series(flood_lat, flood_lng, today)
    if series:
        season_hist = sorted(v for d, v in series
                             if d.month in months and d.year < today.year)
        p50 = percentile(season_hist, 50)
        p90 = percentile(season_hist, 90)
        last60 = [v for d, v in series if d >= today - timedelta(days=60)]
        rec["discharge_seasonal_p50"] = round(p50, 1) if p50 is not None else None
        rec["discharge_seasonal_p90"] = round(p90, 1) if p90 is not None else None
        if p90 and last60:
            rec["days_above_seasonal_p90_last60"] = sum(1 for v in last60 if v > p90)
            rec["last60_max_vs_p90"] = round(max(last60) / p90, 2) if p90 > 0 else None
        year_maxes = {}
        for d, v in series:
            if d.month in months:
                year_maxes[d.year] = max(year_maxes.get(d.year, 0.0), v)
        cur = year_maxes.get(today.year)
        if cur is not None and len(year_maxes) > 1:
            prior = [v for y, v in year_maxes.items() if y < today.year]
            rec["season_max_rank"] = 1 + sum(1 for v in prior if v > cur)
            rec["season_years_compared"] = len(prior) + 1

    # Same normalization as the validated one-off run (strongest-hazard blend).
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
    return rec


def compute_watchlist(resolved_candidates, today=None):
    """Score pre-resolved candidate rows (each already carrying lat/lng =
    anchor, hydro_lat/hydro_lng, cell_p50_m3s, cell_scale). One candidate
    failing never kills the refresh; it keeps its metadata with zero scores."""
    today = today or date.today()
    months = season_months(today)
    results = []
    for candidate in resolved_candidates:
        try:
            results.append(score_place(candidate, today, months))
        except Exception as e:
            print(f"Watchlist scoring failed for {candidate['name']}: {e}", flush=True)
            row = dict(candidate)
            row.update({"seismic_score": 0.0, "flood_score": 0.0, "activity_score": 0.0})
            results.append(row)
        time.sleep(0.5)
    results.sort(key=lambda r: r["activity_score"], reverse=True)
    return {
        "computed_at": int(time.time() * 1000),
        "season_months": list(months),
        "radius_km": RADIUS_KM,
        "min_mag": MIN_MAG,
        "attribution": ATTRIBUTION,
        "results": results,
    }
