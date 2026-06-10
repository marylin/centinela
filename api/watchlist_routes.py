"""Watchlist glue: caches, Firestore doc, candidate resolution, the route.
The pure pool + scoring live in api/watchlist.py."""
import threading
import time
from datetime import datetime

from fastapi import APIRouter

from api.core import TESTING, db
from api.watchlist import (
    CANDIDATES as WATCHLIST_CANDIDATES,
    ATTRIBUTION as WATCHLIST_ATTRIBUTION,
    RADIUS_KM as WATCHLIST_RADIUS_KM,
    MIN_MAG as WATCHLIST_MIN_MAG,
    compute_watchlist, season_months,
)
from api.places_resolver import cell_scale_for, resolve_entries
from api.resolution import RESOLUTION_CACHE, RESOLUTION_LOCK, read_resolution_doc, write_resolution_doc

router = APIRouter()

# --- Candidate watchlist: backend-scored, Firestore-cached, read-only -------
# Scores the candidate pool (api/watchlist.py) from the USGS catalog and the
# GloFAS reanalysis. Promotion into the registry stays a manual config step.

WATCHLIST_TTL_S = 6 * 3600
WATCHLIST_CACHE = {"doc": None, "fetched_at": 0.0}
WATCHLIST_REFRESH_LOCK = threading.Lock()

def read_watchlist_doc():
    if db is None:
        return None
    try:
        snap = db.collection("watchlist").document("latest").get()
        return snap.to_dict() if snap.exists else None
    except Exception as e:
        print(f"Watchlist Firestore read failed: {e}", flush=True)
        return None

def write_watchlist_doc(doc):
    if db is None:
        return
    try:
        db.collection("watchlist").document("latest").set(doc)
    except Exception as e:
        print(f"Watchlist Firestore write failed: {e}", flush=True)

def watchlist_doc_fresh(doc, now_ms):
    return bool(doc and doc.get("computed_at")
                and now_ms - doc["computed_at"] < WATCHLIST_TTL_S * 1000)

def resolved_watchlist_candidates():
    """Candidate pool merged with DERIVED coordinates (the candidates section
    of the resolution doc). Missing candidates are resolved inline: this only
    runs inside the watchlist background refresh, which is already a long
    job. Unresolvable candidates are skipped with a log line."""
    with RESOLUTION_LOCK:
        doc = read_resolution_doc() or {"registry": {}, "candidates": {}}
        doc.setdefault("registry", {})
        doc.setdefault("candidates", {})
        missing = [{"key": c["name"], "name": c["name"], "cc": c.get("cc")}
                   for c in WATCHLIST_CANDIDATES
                   if c["name"] not in doc["candidates"]]
        if missing:
            doc["candidates"].update(resolve_entries(missing))
            write_resolution_doc(doc)
            RESOLUTION_CACHE["doc"] = doc
    rows = []
    for c in WATCHLIST_CANDIDATES:
        entry = doc["candidates"].get(c["name"])
        if not entry:
            print(f"Watchlist: skipping unresolved candidate {c['name']}", flush=True)
            continue
        anchor = entry["anchor"]
        hydro = entry.get("hydro_point") or {}
        rows.append({
            **c,
            "lat": anchor["lat"], "lng": anchor["lng"],
            "hydro_lat": hydro.get("lat", anchor["lat"]),
            "hydro_lng": hydro.get("lng", anchor["lng"]),
            "cell_p50_m3s": hydro.get("cell_p50_m3s"),
            "cell_scale": hydro.get("cell_scale"),
        })
    return rows

def refresh_watchlist_in_background():
    """Recompute the watchlist (30-60s of external calls). Lock-guarded per
    instance; re-reads Firestore inside the lock so concurrent Cloud Run
    instances never stampede the public APIs."""
    if not WATCHLIST_REFRESH_LOCK.acquire(blocking=False):
        return
    try:
        now_ms = int(time.time() * 1000)
        remote = read_watchlist_doc()
        if watchlist_doc_fresh(remote, now_ms):
            WATCHLIST_CACHE["doc"] = remote
            WATCHLIST_CACHE["fetched_at"] = time.time()
            return
        doc = compute_watchlist(resolved_watchlist_candidates())
        write_watchlist_doc(doc)
        WATCHLIST_CACHE["doc"] = doc
        WATCHLIST_CACHE["fetched_at"] = time.time()
        print(f"Watchlist refreshed: {len(doc['results'])} candidates.", flush=True)
    except Exception as e:
        print(f"Watchlist refresh failed: {e}", flush=True)
    finally:
        WATCHLIST_REFRESH_LOCK.release()

# Deterministic candidate resolution fixture (TESTING only): anchors are
# fixed city coordinates so the suite never resolves over the network.
TESTING_CANDIDATE_FIXTURE = {
    "Medellín":      {"lat": 6.2442, "lng": -75.5812, "p50": 1.8},
    "Quito":         {"lat": -0.1807, "lng": -78.4678, "p50": 46.6},
    "Guayaquil":     {"lat": -2.1700, "lng": -79.9224, "p50": 3071.6},
    "La Paz":        {"lat": -16.4897, "lng": -68.1193, "p50": 1.0},
    "San Salvador":  {"lat": 13.6929, "lng": -89.2182, "p50": 7.0},
    "Tegucigalpa":   {"lat": 14.0723, "lng": -87.1921, "p50": 0.1},
    "Santo Domingo": {"lat": 18.4861, "lng": -69.9312, "p50": 64.3},
    "Kingston":      {"lat": 17.9712, "lng": -76.7936, "p50": 0.5},
    "Buenos Aires":  {"lat": -34.6037, "lng": -58.3816, "p50": 20.0},
    "Jakarta":       {"lat": -6.2146, "lng": 106.8451, "p50": 250.0},
    "Manila":        {"lat": 14.5995, "lng": 120.9842, "p50": 80.0},
    "Dhaka":         {"lat": 23.8103, "lng": 90.4125, "p50": 35000.0},
    "Kathmandu":     {"lat": 27.7172, "lng": 85.3240, "p50": 120.0},
    "Istanbul":      {"lat": 41.0082, "lng": 28.9784, "p50": 5.0},
    "Tokyo":         {"lat": 35.6762, "lng": 139.6503, "p50": 60.0},
}

def testing_watchlist_rows():
    """Deterministic TESTING payload shaped exactly like production: the real
    pool metadata with fixture resolution and index-derived scores, no
    network, no Firestore."""
    months = season_months(datetime.now().date())
    results = []
    for i, candidate in enumerate(WATCHLIST_CANDIDATES):
        fx = TESTING_CANDIDATE_FIXTURE[candidate["name"]]
        row = dict(candidate)
        row.update({
            "lat": fx["lat"], "lng": fx["lng"],
            "hydro_lat": fx["lat"], "hydro_lng": fx["lng"],
            "cell_p50_m3s": fx["p50"],
            "cell_scale": cell_scale_for(fx["p50"]),
        })
        row.update({
            "quake_90d_count": (3 * i) % 17,
            "quake_90d_maxmag": round(4.5 + (i % 5) * 0.4, 1),
            "days_above_seasonal_p90_last60": (2 * i) % 23,
            "last60_max_vs_p90": round(0.6 + (i % 7) * 0.35, 2),
            "seismic_score": round(max(0.0, 0.85 - i * 0.07), 2),
            "flood_score": round(max(0.0, 0.55 - i * 0.04), 2),
            "activity_score": round(max(0.0, 0.9 - i * 0.07), 2),
        })
        results.append(row)
    results.sort(key=lambda r: r["activity_score"], reverse=True)
    return {
        "computed_at": int(time.time() * 1000),
        "season_months": list(months),
        "radius_km": WATCHLIST_RADIUS_KM,
        "min_mag": WATCHLIST_MIN_MAG,
        "attribution": WATCHLIST_ATTRIBUTION,
        "results": results,
    }

@router.get("/watchlist")
def get_watchlist():
    """Ranked candidate watchlist (MODEL data: activity scored from the USGS
    catalog + GloFAS reanalysis). Serves cached data immediately; a stale or
    missing cache triggers a background refresh. Read-only: promoting a
    candidate into the registry stays a manual config change + resync."""
    if TESTING:
        return {"status": "ok", **testing_watchlist_rows()}

    now_ms = int(time.time() * 1000)
    doc = WATCHLIST_CACHE["doc"]
    if not watchlist_doc_fresh(doc, now_ms):
        remote = read_watchlist_doc()
        if remote:
            doc = remote
            WATCHLIST_CACHE["doc"] = remote
            WATCHLIST_CACHE["fetched_at"] = time.time()
    if watchlist_doc_fresh(doc, now_ms):
        return {"status": "ok", **doc}

    threading.Thread(target=refresh_watchlist_in_background, daemon=True).start()
    if doc:
        return {"status": "refreshing", **doc}
    return {"status": "warming", "computed_at": None,
            "season_months": list(season_months(datetime.now().date())),
            "radius_km": WATCHLIST_RADIUS_KM, "min_mag": WATCHLIST_MIN_MAG,
            "attribution": WATCHLIST_ATTRIBUTION, "results": []}

