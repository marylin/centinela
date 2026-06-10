"""Coordinate resolution for monitored places and watchlist candidates.

Nothing coordinate-shaped is hardcoded in the app: given a place NAME and an
ISO2 country code, this module derives
  - the city anchor (Open-Meteo geocoding, highest-population match), used for
    map pins, observed-rain recording, AQI, and route origins; and
  - the hydro sampling point (the GloFAS grid cell with the strongest median
    discharge within ~15 km of the anchor), used for river discharge. City
    centroids frequently sit on creek-scale cells; the probe finds the actual
    river (verified: it finds the Magdalena one cell west of Honda's center).

Pure module: no Firestore, no FastAPI, nothing at import time. The caller
(api.main) owns caching and persistence.
"""
import time
from math import hypot

import requests

PROBE_GRID = 7          # 7x7 cells around the anchor
PROBE_STEP_DEG = 0.05   # GloFAS cell size; grid spans ~+/-15 km
PROBE_PAST_DAYS = 92    # same window the hazard index uses
RIVER_P50_M3S = 500.0   # cell_scale thresholds (coarse, documented)
MID_P50_M3S = 10.0
USER_AGENT = "centinela-places-resolver/1.0"


def _fetch_json(url, params, timeout=20, retries=3):
    for attempt in range(retries):
        try:
            resp = requests.get(url, params=params, timeout=timeout,
                                headers={"User-Agent": USER_AGENT})
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt == retries - 1:
                print(f"Resolver fetch failed ({url}): {e}", flush=True)
                return None
            time.sleep(1.5 * (attempt + 1))


def cell_scale_for(p50):
    if p50 is None:
        return None
    if p50 >= RIVER_P50_M3S:
        return "river"
    if p50 >= MID_P50_M3S:
        return "mid"
    return "creek"


def geocode_place(name, cc=None):
    """City anchor for a place name: highest-population geocoder match,
    filtered to the ISO2 country code when given. None when unresolvable."""
    params = {"name": name, "count": 5, "language": "en", "format": "json"}
    if cc:
        params["countryCode"] = cc
    data = _fetch_json("https://geocoding-api.open-meteo.com/v1/search", params)
    results = (data or {}).get("results") or []
    if cc:
        results = [r for r in results
                   if (r.get("country_code") or "").upper() == cc.upper()]
    # Prefer populated places (PPL*): without this, "Santo Domingo" matches
    # the Dominican Republic COUNTRY entity (PCLI) on raw population.
    ppl = [r for r in results if (r.get("feature_code") or "").startswith("PPL")]
    if ppl:
        results = ppl
    if not results:
        return None
    best = max(results, key=lambda r: r.get("population") or 0)
    return {
        "lat": round(float(best["latitude"]), 5),
        "lng": round(float(best["longitude"]), 5),
        "country": best.get("country"),
        "admin1": best.get("admin1"),
        "population": best.get("population"),
    }


def probe_river_cell(lat, lng, grid=PROBE_GRID, step=PROBE_STEP_DEG):
    """The GloFAS cell with the strongest median discharge near the anchor:
    ONE multi-coordinate request for the whole grid. Cells without data
    (ocean, no river) are skipped. None when nothing in range has data."""
    half = grid // 2
    lats, lngs = [], []
    for di in range(-half, half + 1):
        for dj in range(-half, half + 1):
            lats.append(f"{lat + di * step:.4f}")
            lngs.append(f"{lng + dj * step:.4f}")
    data = _fetch_json("https://flood-api.open-meteo.com/v1/flood", {
        "latitude": ",".join(lats), "longitude": ",".join(lngs),
        "daily": "river_discharge", "past_days": PROBE_PAST_DAYS,
    }, timeout=30)
    if data is None:
        return None
    items = data if isinstance(data, list) else [data]
    cells = {}
    for it in items:
        vals = sorted(v for v in ((it.get("daily") or {}).get("river_discharge") or [])
                      if v is not None)
        if len(vals) < 30:
            continue
        clat, clng = float(it.get("latitude")), float(it.get("longitude"))
        key = (round(clat, 4), round(clng, 4))
        if key in cells:
            continue
        median = vals[len(vals) // 2]
        cells[key] = {"lat": clat, "lng": clng, "p50": median,
                      "dist": hypot(clat - lat, clng - lng)}
    if not cells:
        return None
    best = sorted(cells.values(), key=lambda c: (-c["p50"], c["dist"]))[0]
    return {
        "lat": round(best["lat"], 5),
        "lng": round(best["lng"], 5),
        "cell_p50_m3s": round(best["p50"], 1),
        "cell_scale": cell_scale_for(best["p50"]),
    }


def resolve_place(name, cc=None):
    """Full resolution for one place. None when geocoding fails; a place can
    resolve with hydro_point=None (no river data in range, e.g. open coast)."""
    geo = geocode_place(name, cc)
    if geo is None:
        return None
    hydro = probe_river_cell(geo["lat"], geo["lng"])
    return {
        "anchor": {"lat": geo["lat"], "lng": geo["lng"]},
        "hydro_point": hydro,
        "geocode": {"country": geo.get("country"), "admin1": geo.get("admin1"),
                    "population": geo.get("population")},
        "resolved_at": int(time.time() * 1000),
    }


def resolve_entries(entries):
    """Resolve [{key, name, cc}] sequentially (polite to both free APIs).
    Per-entry failures are tolerated: the returned map only holds successes."""
    out = {}
    for e in entries:
        try:
            resolution = resolve_place(e["name"], e.get("cc"))
            if resolution is not None:
                out[e["key"]] = resolution
            else:
                print(f"Resolver: no geocode match for {e['name']} ({e.get('cc')})", flush=True)
        except Exception as ex:
            print(f"Resolver: failed for {e['name']}: {ex}", flush=True)
        time.sleep(0.4)
    return out
