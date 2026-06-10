# core must be imported FIRST: it runs load_dotenv() before any module-level
# os.environ reads here or in any other api module.
import api.core as core
from api.core import TESTING, db, MOCK_DB_STATE
from api.config import (
    BASINS, REAL_CONNECTORS, CONNECTOR_ID, SEISMIC_BBOX_PAD_DEG,
    TELEMETRY_PROVENANCE, LOCATION_CONDITIONS_PROVENANCE,
    RAW_EVENTS_TABLE, RAW_EVENT_FIELDS, basin_municipalities,
)
from api.stores import (
    get_fcm_tokens, add_fcm_token, discard_fcm_token,
    get_autonomous_heals_list, add_autonomous_heal, clear_autonomous_heals_store,
    get_incidents_list, add_incident, clear_incidents_store,
    record_risk_sample_tick, get_risk_sample_ticks,
    get_demo_event, set_demo_event, delete_demo_event, get_all_demo_events,
    remove_simulated_incidents,
)
from api.resolution import (
    RESOLUTION_CACHE, RESOLUTION_LOCK, testing_resolution,
    read_resolution_doc, write_resolution_doc, registry_resolution_entries,
    get_resolution, refresh_resolution_in_background, resolved_places,
    group_seismic_bbox, municipality_coordinates, live_seismic_coordinates,
)
from api.hazard import (
    refresh_weather_records, component_scores, blend_index, index_row,
    compute_hazard_index, testing_index_rows, compute_base_risk,
    WEATHER_CACHE, INDEX_CACHE, INDEX_CACHE_TTL_S, DOMINANT_BY_COMPONENT,
)
from api.demo import merge_demo_event_into_risk
from api.narration import (
    CACHED_ALERT_RESPONSES, CACHED_RISK_DATA_JSONS, GENERATING_NARRATIONS,
    FIRESTORE_MOCK_CACHE, LAST_GOOD_NARRATIVES, get_state_hash,
    get_cached_narration, set_cached_narration, get_last_good_narration,
    update_last_good_narration, get_fallback_narration,
    generate_narration_in_background, get_alert_state_repr,
)
from api.risk_routes import router as risk_router, get_risk
from api.incident_routes import router as incident_router, log_alert_or_outage
from api.push_routes import router as push_router, check_and_trigger_push_sync, run_alerts_and_narration_check
from api.alert_routes import router as alert_router
from api.connector_routes import router as connector_router
from api.conditions_routes import router as conditions_router
from api.seismic_routes import router as seismic_router

import os
import asyncio
import time
import json
import subprocess
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Response, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import bigquery
from pydantic import BaseModel
from firebase_admin import messaging

import requests
import concurrent.futures
import math
import threading

from api.watchlist import (
    CANDIDATES as WATCHLIST_CANDIDATES,
    ATTRIBUTION as WATCHLIST_ATTRIBUTION,
    RADIUS_KM as WATCHLIST_RADIUS_KM,
    MIN_MAG as WATCHLIST_MIN_MAG,
    compute_watchlist,
    season_months,
)
from api.places_resolver import cell_scale_for, resolve_entries, resolve_place

# Place coordinates are DERIVED at runtime (geocode + GloFAS river-cell probe
# via api/places_resolver.py); the registry below holds names only.

# Cache for alert data response to avoid redundant Gemini calls during polling
# Import the existing agent logic
from rapid_agent.agent import check_and_heal_connector, get_mcp_toolset, call_with_retry

# Import ADK narration agent (Phase 6: all prose runs through the ADK LlmAgent Runner)
from rapid_agent.centinela_agent import run_narration_turn, run_event_narration_turn

app = FastAPI(title="Centinela Backend API")

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(risk_router)
app.include_router(incident_router)
app.include_router(push_router)
app.include_router(alert_router)
app.include_router(connector_router)
app.include_router(conditions_router)
app.include_router(seismic_router)

# ---------------------------------------------------------------------------
# PLACES REGISTRY (real-data unification)
# ---------------------------------------------------------------------------
# Every monitored place is one registry row with coordinates; adding a place is
# a config change, nothing else. All data behind the registry is REAL:
#   - GloFAS river discharge + model soil moisture (global_hydro connector),
#   - observed rainfall history (live Google Weather, recorded per place),
#   - the global USGS raw-events feed (usgs_raw_events connector).
# No seeded sheets/CSVs anywhere; the hazard index is computed from these
# feeds and is always labeled as a Centinela MODEL INDEX.
# kind: "flood-watch" (river basin framing) | "seismic-watch" (quake framing).
#
# NOTHING COORDINATE-SHAPED IS HARDCODED. The registry holds structure and
# names only; coordinates are DERIVED per place by api/places_resolver.py:
#   anchor      geocoded city center (map pin, rain recorder, AQI, routes)
#   hydro_point strongest-discharge GloFAS cell within ~15 km (river sampling)
# Resolutions persist in Firestore (places_resolution/latest, no TTL) and are
# lazily filled by a lock-guarded background thread. Seismic bboxes derive
# from the resolved anchors (+/- SEISMIC_BBOX_PAD_DEG).

@app.get("/", response_class=HTMLResponse)
def read_index():
    """Serves the dashboard home page."""
    try:
        with open("web/index.html", "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/app.js")
def read_js():
    """Serves the client-side JavaScript engine."""
    try:
        with open("web/app.js", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="application/javascript")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/style.css")
def read_css():
    """Serves the dashboard stylesheet."""
    try:
        with open("web/style.css", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="text/css")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/firebase-messaging-sw.js")
def read_sw():
    """Serves the Firebase Messaging Service Worker."""
    try:
        with open("web/firebase-messaging-sw.js", "r", encoding="utf-8") as f:
            return Response(content=f.read(), media_type="application/javascript")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/basins")
def get_basins():
    """The configured groups with RESOLVED places (anchor + hydro point per
    place, derived, never hardcoded). Unresolved places carry resolved=false
    and no coordinates until the background resolution lands."""
    return [
        {
            "id": b["id"],
            "name": b["name"],
            "country": b["country"],
            "kind": b.get("kind", "flood-watch"),
            "places": resolved_places(b),
            "municipalities": basin_municipalities(b),
            "seismic_bbox": group_seismic_bbox(b)
        }
        for b in BASINS
    ]

@app.get("/places")
def get_places():
    """The monitored-places registry: groups with coordinates and kind.
    Same payload as /basins (kept as an alias for the frontend migration)."""
    return get_basins()

@app.post("/places/resolve")
def resolve_places_endpoint(place: str = None, force: bool = False):
    """Operator escape hatch. With `place`: synchronously re-resolve that one
    place id and write through. Without: kick a background re-resolution of
    missing places (or everything with force=true)."""
    if TESTING:
        doc = testing_resolution()
        if place:
            entry = doc["registry"].get(place)
            if entry is None:
                raise HTTPException(status_code=404, detail=f"Unknown place: {place}")
            return {"status": "ok", "place": place, "resolution": entry}
        return {"status": "started"}

    if place:
        target = next((e for e in registry_resolution_entries() if e["key"] == place), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Unknown place: {place}")
        resolution = resolve_place(target["name"], target.get("cc"))
        if resolution is None:
            raise HTTPException(status_code=502, detail=f"Could not resolve {target['name']}")
        with RESOLUTION_LOCK:
            doc = read_resolution_doc() or {"registry": {}, "candidates": {}}
            doc.setdefault("registry", {})[place] = resolution
            write_resolution_doc(doc)
            RESOLUTION_CACHE["doc"] = doc
        return {"status": "ok", "place": place, "resolution": resolution}

    threading.Thread(target=refresh_resolution_in_background,
                     args=(force,), daemon=True).start()
    return {"status": "started"}

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

# Deterministic candidate resolution fixture (TESTING only): anchors are the
# pre-derivation city coordinates; Manaus carries the Rio Negro river cell.
TESTING_CANDIDATE_FIXTURE = {
    "Bogotá":        {"lat": 4.7110, "lng": -74.0721, "p50": 0.7},
    "Medellín":      {"lat": 6.2442, "lng": -75.5812, "p50": 1.8},
    "Quito":         {"lat": -0.1807, "lng": -78.4678, "p50": 46.6},
    "Guayaquil":     {"lat": -2.1700, "lng": -79.9224, "p50": 3071.6},
    "La Paz":        {"lat": -16.4897, "lng": -68.1193, "p50": 1.0},
    "San Salvador":  {"lat": 13.6929, "lng": -89.2182, "p50": 7.0},
    "Managua":       {"lat": 12.1150, "lng": -86.2362, "p50": 12.3},
    "Tegucigalpa":   {"lat": 14.0723, "lng": -87.1921, "p50": 0.1},
    "Santo Domingo": {"lat": 18.4861, "lng": -69.9312, "p50": 64.3},
    "Kingston":      {"lat": 17.9712, "lng": -76.7936, "p50": 0.5},
    "Buenos Aires":  {"lat": -34.6037, "lng": -58.3816, "p50": 20.0},
    "Manaus":        {"lat": -3.1800, "lng": -60.0300, "p50": 54826.7},
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

@app.get("/watchlist")
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

class DemoEventRequest(BaseModel):
    basin: str
    municipality: str
    magnitude: float

class DemoClearRequest(BaseModel):
    basin: str

@app.post("/demo/inject-event")
def demo_inject_event(data: DemoEventRequest, background_tasks: BackgroundTasks):
    """Stores a simulated seismic event for the basin, merged into /risk at read
    time and tagged simulated everywhere. Triggers the narration recompute so
    /alert reflects it, and logs a clearly simulated incident."""
    basin_config = next((b for b in BASINS if b["id"] == data.basin), None)
    if basin_config is None:
        raise HTTPException(status_code=404, detail=f"Unknown basin: {data.basin}")
    if data.municipality not in basin_municipalities(basin_config):
        raise HTTPException(
            status_code=400,
            detail=f"Municipality {data.municipality} is not part of basin {data.basin}"
        )
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    muni_lat, muni_lon = live_seismic_coordinates().get(data.municipality, (0.0, 0.0))
    event = {
        "basin": data.basin,
        "municipality": data.municipality,
        "magnitude": float(data.magnitude),
        "simulated": True,
        "injected_at": now_iso,
        # Feed fields so the simulated event also appears in /seismic-events
        # and is focusable via /seismic-focus, tagged simulated everywhere.
        "id": f"sim-{data.basin}-{int(time.time())}",
        "place": f"near {data.municipality}, {basin_config['country']}",
        "time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latitude": float(muni_lat),
        "longitude": float(muni_lon),
        "depth_km": 10.0
    }
    set_demo_event(data.basin, event)

    risk_data = get_risk(basin=data.basin)
    incident_entry = {
        "id": f"inc_sim_{int(time.time())}",
        "timestamp": now_iso,
        "basin": data.basin,
        "type": "alert",
        "simulated": True,
        "details": (
            f"SIMULATED demo event: M{event['magnitude']:.1f} earthquake injected near "
            f"{data.municipality}. Not a real USGS detection."
        ),
        "risk_data": risk_data or []
    }
    add_incident(incident_entry)

    # Reuse the existing check-alerts narration path so /alert reflects the event
    background_tasks.add_task(run_alerts_and_narration_check, data.basin)
    return {"status": "Success", "event": event, "risk_data": risk_data}

@app.post("/demo/clear-event")
def demo_clear_event(data: DemoClearRequest, background_tasks: BackgroundTasks):
    """Removes the simulated demo event for the basin so /risk, /alert and
    /incidents return to normal."""
    basin_config = next((b for b in BASINS if b["id"] == data.basin), None)
    if basin_config is None:
        raise HTTPException(status_code=404, detail=f"Unknown basin: {data.basin}")
    delete_demo_event(data.basin)
    remove_simulated_incidents(data.basin)
    background_tasks.add_task(run_alerts_and_narration_check, data.basin)
    return {"status": "Success", "basin": data.basin}

# ---------------------------------------------------------------------------
# Portfolio: raw USGS pipeline (Fivetran -> BigQuery -> these endpoints)
#
# The usgs_raw_events Fivetran connector syncs the global M4.5+ monthly feed
# into the raw-events table verbatim (no municipality attribution, no baseline
# events). BigQuery organizes it via the tracked SQL files, and these
# endpoints read BigQuery only -- never USGS directly -- so Fivetran stays
# the orchestrator. In TESTING, a seeded sample table stands in for BigQuery
# (the real rows appear only after the connector is deployed and synced).
# ---------------------------------------------------------------------------



