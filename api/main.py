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

# State and cooldown tracking for push notifications
TOKEN_LAST_SENT_STATES = {}  # token -> state_repr
TOKEN_COOLDOWNS = {}  # token -> {state_repr: datetime}
SENT_PUSH_HISTORY = []  # list of dicts for testing

# Cache for alert data response to avoid redundant Gemini calls during polling
# Local simulation state in case Fivetran API is rate-limited (429)
LOCAL_PAUSED_STATES = {}  # connector_id -> bool
# MOCK_DB_STATE lives in api.core (from-imported above; mutated in place only).

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

class AlertNarratives(BaseModel):
    summary: str
    broadcast: str

class TokenRegistration(BaseModel):
    token: str

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

def fetch_location_rainfall_history(lat: float, lng: float, api_key: str):
    url = "https://weather.googleapis.com/v1/history/hours:lookup"
    params = {
        "location.latitude": lat,
        "location.longitude": lng,
        "hours": 24,
        "pageSize": 24,
        "unitsSystem": "METRIC"
    }
    resp = requests.get(url, params=params, headers={"X-Goog-Api-Key": api_key}, timeout=6.0)
    if resp.status_code != 200:
        raise RuntimeError(f"weather history status {resp.status_code}")
    hours = resp.json().get("historyHours", [])
    series = []
    for h in hours:
        qpf = ((h.get("precipitation") or {}).get("qpf") or {})
        t = ((h.get("interval") or {}).get("startTime")) or ""
        series.append({"time": t, "mm": round(float(qpf.get("quantity") or 0.0), 2)})
    series.reverse()  # API returns newest first; serve oldest-first for charts
    return {"total_24h_mm": round(sum(s["mm"] for s in series), 1), "hourly": series}

def fetch_location_discharge(lat: float, lng: float):
    url = "https://flood-api.open-meteo.com/v1/flood"
    params = {"latitude": lat, "longitude": lng, "daily": "river_discharge",
              "past_days": 7, "forecast_days": 1}
    resp = requests.get(url, params=params, timeout=6.0)
    if resp.status_code != 200:
        raise RuntimeError(f"flood api status {resp.status_code}")
    d = resp.json().get("daily") or {}
    series = [{"date": t, "m3s": round(float(v), 1)}
              for t, v in zip(d.get("time") or [], d.get("river_discharge") or [])
              if v is not None]
    if not series:
        return None
    latest, week_ago = series[-1]["m3s"], series[0]["m3s"]
    direction = "rising" if latest > week_ago * 1.05 else ("falling" if latest < week_ago * 0.95 else "steady")
    return {"latest_m3s": latest, "direction": direction, "daily": series}

def fetch_location_soil(lat: float, lng: float):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {"latitude": lat, "longitude": lng, "hourly": "soil_moisture_0_to_7cm",
              "past_days": 2, "forecast_days": 1}
    resp = requests.get(url, params=params, timeout=6.0)
    if resp.status_code != 200:
        raise RuntimeError(f"soil api status {resp.status_code}")
    h = resp.json().get("hourly") or {}
    values = [float(v) for v in (h.get("soil_moisture_0_to_7cm") or []) if v is not None]
    if not values:
        return None
    return {"latest_m3m3": round(values[-1], 3),
            "min_48h": round(min(values), 3), "max_48h": round(max(values), 3)}

def fetch_location_aqi(lat: float, lng: float, api_key: str):
    url = "https://airquality.googleapis.com/v1/currentConditions:lookup"
    resp = requests.post(url, json={"location": {"latitude": lat, "longitude": lng}},
                         headers={"X-Goog-Api-Key": api_key}, timeout=6.0)
    if resp.status_code != 200:
        raise RuntimeError(f"air quality status {resp.status_code}")
    indexes = resp.json().get("indexes") or []
    uaqi = next((i for i in indexes if i.get("code") == "uaqi"), indexes[0] if indexes else None)
    if not uaqi:
        return None
    return {"aqi": int(uaqi.get("aqi") or 0), "category": uaqi.get("category") or ""}


@app.get("/location-conditions")
def get_location_conditions(lat: float, lng: float):
    """Real conditions for any coordinate: observed 24h rainfall plus modeled
    river discharge and soil moisture, each labeled with its provenance."""
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lng out of range")

    if TESTING:
        hourly = [{"time": "", "mm": round(max(0.0, 1.4 * math.sin(i / 4.0)), 2)} for i in range(24)]
        return {
            "latitude": lat, "longitude": lng,
            "rainfall": {"total_24h_mm": round(sum(x["mm"] for x in hourly), 1), "hourly": hourly},
            "river_discharge": {"latest_m3s": 1234.5, "direction": "rising",
                                 "daily": [{"date": f"2026-06-0{d}", "m3s": 1000.0 + d * 30} for d in range(1, 9)]},
            "soil_moisture": {"latest_m3m3": 0.312, "min_48h": 0.298, "max_48h": 0.33},
            "air_quality": {"aqi": 82, "category": "Good air quality"},
            "provenance": LOCATION_CONDITIONS_PROVENANCE
        }

    cache_key = (round(lat, 2), round(lng, 2))
    now_s = time.time()
    cached = LOCATION_CONDITIONS_CACHE.get(cache_key)
    if cached and cached[0] > now_s:
        return cached[1]

    payload = {"latitude": lat, "longitude": lng, "rainfall": None,
               "river_discharge": None, "soil_moisture": None, "air_quality": None,
               "provenance": LOCATION_CONDITIONS_PROVENANCE}
    api_key = os.environ.get("GOOGLE_WEATHER_API_KEY")
    if api_key:
        try:
            payload["rainfall"] = fetch_location_rainfall_history(lat, lng, api_key)
        except Exception as e:
            print(f"location-conditions rainfall failed: {e}", flush=True)
        try:
            payload["air_quality"] = fetch_location_aqi(lat, lng, api_key)
        except Exception as e:
            print(f"location-conditions air quality failed: {e}", flush=True)
    try:
        payload["river_discharge"] = fetch_location_discharge(lat, lng)
    except Exception as e:
        print(f"location-conditions discharge failed: {e}", flush=True)
    try:
        payload["soil_moisture"] = fetch_location_soil(lat, lng)
    except Exception as e:
        print(f"location-conditions soil failed: {e}", flush=True)

    LOCATION_CONDITIONS_CACHE[cache_key] = (now_s + LOCATION_CONDITIONS_TTL_S, payload)
    return payload

def check_and_trigger_push_sync(risk_data, basin="rio_cauca"):
    print("DEBUG: check_and_trigger_push_sync started", flush=True)
    try:
        # 1. Get current risk data state repr
        current_state = get_alert_state_repr(risk_data)
        print(f"DEBUG: current_state={current_state}", flush=True)
        
        # If no active alert state, update all tokens' last sent state to empty, and return
        if not current_state:
            print("DEBUG: current_state is empty, resetting token states", flush=True)
            for token in list(get_fcm_tokens()):
                TOKEN_LAST_SENT_STATES[token] = ""
                TOKEN_COOLDOWNS[token] = {}
            return
            
        # 2. Since there is an active alert (risk is HIGH), get/compute the narration and cache it
        affected_municipalities = []
        for muni_risk in risk_data:
            score = muni_risk["risk_score"]
            if score >= 0.6:
                affected_municipalities.append(muni_risk["municipality"])
                
        if not affected_municipalities:
            return
            
        title = f"{basin.replace('_', ' ').title()} Basin Compound Flood Risk Alert"
        # Check if we have cached narratives matching this risk data in Firestore
        cached = get_cached_narration(basin, risk_data)
        if cached:
            summary = cached.get("summary", "")
            resident_broadcast_text = cached.get("broadcast", "")
        else:
            if TESTING:
                narratives = {
                    "summary": f"Mock technical summary describing {basin} basin compound flood risk.",
                    "broadcast": f"Mock resident warning broadcast message mentioning affected municipalities in {basin}."
                }
            else:
                # Phase 6: narration produced via ADK LlmAgent Runner
                narratives = run_narration_turn(basin, risk_data)
            summary = narratives.get("summary", "")
            resident_broadcast_text = narratives.get("broadcast", "")
            
            if summary and resident_broadcast_text:
                set_cached_narration(basin, risk_data, summary, resident_broadcast_text)
                update_last_good_narration(basin, summary, resident_broadcast_text)
                
        if not resident_broadcast_text:
            print("DEBUG: No resident_broadcast_text generated, skipping pushes and logs", flush=True)
            return
            
        # Log active alert incident to Firestore
        log_alert_or_outage("alert", basin, f"Compound multi-hazard alert active for basin: {summary[:120]}", risk_data)

        # 3. Check which tokens need to be notified
        tokens_to_notify = []
        now = datetime.now(timezone.utc)
        print(f"DEBUG: FCM_TOKENS={list(get_fcm_tokens())}", flush=True)
        
        for token in list(get_fcm_tokens()):
            last_sent_state = TOKEN_LAST_SENT_STATES.get(token, "")
            print(f"DEBUG: token={token[:8]}... last_sent_state={last_sent_state}", flush=True)
            if current_state == last_sent_state:
                print(f"DEBUG: token={token[:8]}... state matches last sent, skipping", flush=True)
                continue
                
            # Check cooldown
            state_cooldowns = TOKEN_COOLDOWNS.setdefault(token, {})
            last_sent_time = state_cooldowns.get(current_state)
            if last_sent_time:
                if last_sent_time.tzinfo is None:
                    last_sent_time = last_sent_time.replace(tzinfo=timezone.utc)
                if now - last_sent_time < timedelta(minutes=10):
                    print(f"Skipping token {token[:8]}... due to 10-minute cooldown", flush=True)
                    continue
                    
            tokens_to_notify.append(token)
            
        print(f"DEBUG: tokens_to_notify={tokens_to_notify}", flush=True)
        if not tokens_to_notify:
            return

        # 4. Send pushes
        failed_tokens = []
        for token in tokens_to_notify:
            # Record the attempt in SENT_PUSH_HISTORY
            SENT_PUSH_HISTORY.append({
                "timestamp": now.isoformat(),
                "token": token,
                "title": title,
                "body": resident_broadcast_text
            })
            
            # If TESTING is True, stub/short-circuit the actual FCM send call
            if TESTING:
                TOKEN_LAST_SENT_STATES[token] = current_state
                TOKEN_COOLDOWNS.setdefault(token, {})[current_state] = now
                print(f"Stubbed push warning to token {token[:8]}... for state {current_state}", flush=True)
                continue
                
            try:
                message = messaging.Message(
                    notification=messaging.Notification(
                        title=title,
                        body=resident_broadcast_text[:1000]
                    ),
                    token=token
                )
                messaging.send(message)
                
                # Update last sent state and cooldown
                TOKEN_LAST_SENT_STATES[token] = current_state
                TOKEN_COOLDOWNS.setdefault(token, {})[current_state] = now
                print(f"Sent push warning to token {token[:8]}... for state {current_state}")
            except Exception as ex:
                print(f"Error sending push notification to token {token}: {ex}")
                if "not-registered" in str(ex).lower() or "invalid" in str(ex).lower():
                     failed_tokens.append(token)
                     
        for ft in failed_tokens:
            discard_fcm_token(ft)
            if ft in TOKEN_COOLDOWNS:
                del TOKEN_COOLDOWNS[ft]
            if ft in TOKEN_LAST_SENT_STATES:
                del TOKEN_LAST_SENT_STATES[ft]
                
    except Exception as e:
        print(f"Error checking/triggering push: {e}")

@app.get("/alert")
def get_alert(basin: str = "rio_cauca", background_tasks: BackgroundTasks = None):
    """Turns the current risk scores into graded alerts, incident report, and resident warning."""

    if core.REOPENED_INCIDENT_ID:
        incidents = get_incidents_list()
        matching = next((inc for inc in incidents if inc["id"] == core.REOPENED_INCIDENT_ID), None)
        if matching:
            risk_data = matching.get("risk_data", [])
            graded = []
            affected = []
            for r in risk_data:
                score = r["risk_score"]
                sev = "HIGH" if score >= 0.6 else "LOW"
                if score >= 0.8:
                    sev = "EXTREME"
                elif score >= 0.4:
                    sev = "MODERATE"
                graded.append({
                    "municipality": r["municipality"],
                    "risk_score": score,
                    "severity": sev,
                    "dominant_hazard": r.get("dominant_hazard", "FLOOD")
                })
                if sev in ["HIGH", "EXTREME"]:
                    affected.append(r["municipality"])
            return {
                "graded_alert": graded,
                "agency_incident": {
                    "title": f"REOPENED HISTORICAL INCIDENT: {matching['id']}",
                    "summary": matching["details"],
                    "affected_municipalities": affected
                },
                "resident_broadcast": f"HISTORICAL INCIDENT DATA: {matching['details']}"
            }

    try:
        # Re-use the risk computation logic
        risk_data = get_risk(basin=basin)
        
        graded_alert = []
        affected_municipalities = []
        
        for muni_risk in risk_data:
            muni = muni_risk["municipality"]
            score = muni_risk["risk_score"]
            
            # Map score to severity
            if score >= 0.8:
                severity = "EXTREME"
            elif score >= 0.6:
                severity = "HIGH"
            elif score >= 0.4:
                severity = "MODERATE"
            else:
                severity = "LOW"
                
            graded_alert.append({
                "municipality": muni,
                "risk_score": score,
                "severity": severity,
                "dominant_hazard": muni_risk.get("dominant_hazard", "FLOOD")
            })
            
            if severity in ["HIGH", "EXTREME"]:
                affected_municipalities.append(muni)
                
        title = f"{basin.replace('_', ' ').title()} Basin Compound Multi-Hazard Alert"

        # Check Firestore cache first
        cached = get_cached_narration(basin, risk_data)
        if cached:
            return {
                "graded_alert": graded_alert,
                "agency_incident": {
                    "title": title,
                    "summary": cached["summary"],
                    "affected_municipalities": affected_municipalities
                },
                "resident_broadcast": cached["broadcast"]
            }
            
        # Cache miss: return last good narration or generating placeholder instantly and trigger background generation
        fallback = get_fallback_narration(basin, risk_data)
        alert_response = {
            "graded_alert": graded_alert,
            "agency_incident": {
                "title": title,
                "summary": fallback["summary"],
                "affected_municipalities": affected_municipalities
            },
            "resident_broadcast": fallback["broadcast"]
        }
        
        # Trigger background generation task if not already generating
        if basin not in GENERATING_NARRATIONS:
            GENERATING_NARRATIONS.add(basin)
            if background_tasks:
                background_tasks.add_task(generate_narration_in_background, basin, risk_data)
            else:
                import asyncio
                asyncio.create_task(asyncio.to_thread(generate_narration_in_background, basin, risk_data))
                
        return alert_response
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/register-token")
def register_token(data: TokenRegistration, background_tasks: BackgroundTasks, basin: str = "rio_cauca"):
    """Registers an FCM token for push notifications."""
    token = data.token.strip()
    if token:
        add_fcm_token(token)
        risk_data = get_risk(basin=basin)
        background_tasks.add_task(check_and_trigger_push_sync, risk_data, basin)
        return {"status": "Success", "message": f"Token registered. Total tokens: {len(get_fcm_tokens())}"}
    return {"status": "Error", "message": "Invalid token"}

@app.get("/connector-status")
async def get_connector_status(basin: str = "rio_cauca"):
    """Reads status of all configured Fivetran connectors, returning the primary at root and full list in 'connectors'."""
    basin_config = next((b for b in BASINS if b["id"] == basin), BASINS[0])
    basin_connectors = basin_config["connectors"]

    if TESTING:
        connector_results = []
        for conn in basin_connectors:
            conn_id = conn["id"]
            is_paused = LOCAL_PAUSED_STATES.get(conn_id, False)
            connector_results.append({
                "connector_id": conn_id,
                "name": conn["name"],
                "status": "paused" if is_paused else "active",
                "last_sync_time": datetime.now(timezone.utc).isoformat(),
                "freshness": "FRESH"
            })
        primary = connector_results[0] if connector_results else {"status": "active", "last_sync_time": "never", "freshness": "FRESH"}
        return {
            "status": primary["status"],
            "last_sync_time": primary["last_sync_time"],
            "freshness": primary["freshness"],
            "connectors": connector_results
        }
        
    try:
        connector_results = []
        for conn in basin_connectors:
            conn_id = conn["id"]

            toolset = get_mcp_toolset()
            try:
                async def call_details(session):
                    return await session.call_tool(
                        name="get_connection_details",
                        arguments={
                            "schema_file": "open-api-definitions/connections/connection_details.json",
                            "connection_id": conn_id
                        }
                    )
                result = await toolset._execute_with_session(call_details, f"Failed to get connection details for {conn_id}")
                raw_text = result.content[0].text
                if "Error" in raw_text or "Fivetran API error" in raw_text:
                    if "429" in raw_text:
                        is_paused = LOCAL_PAUSED_STATES.get(conn_id, False)
                        connector_results.append({
                            "connector_id": conn_id,
                            "name": conn["name"],
                            "status": "paused" if is_paused else "active",
                            "last_sync_time": datetime.now(timezone.utc).isoformat(),
                            "freshness": "FRESH"
                        })
                        continue
                        
                    connector_results.append({
                        "connector_id": conn_id,
                        "name": conn["name"],
                        "status": "error",
                        "last_sync_time": "never",
                        "freshness": "UNKNOWN"
                    })
                    continue
                    
                data = json.loads(raw_text).get("data", {})
                paused = data.get("paused", False)
                succeeded_at_str = data.get("succeeded_at")
                
                status_val = "paused" if paused else "active"
                
                # If we know it was modified locally, we can override/fallback
                is_paused = LOCAL_PAUSED_STATES.get(conn_id, paused)
                if is_paused != paused:
                    status_val = "paused" if is_paused else "active"
                
                # Calculate freshness
                freshness = "UNKNOWN"
                if succeeded_at_str:
                    if succeeded_at_str.endswith("Z"):
                        succeeded_at_str = succeeded_at_str[:-1]
                    succeeded_at = datetime.fromisoformat(succeeded_at_str).replace(tzinfo=timezone.utc)
                    current_time = datetime.now(timezone.utc)
                    diff_minutes = (current_time - succeeded_at).total_seconds() / 60.0
                    freshness = "FRESH" if diff_minutes < 60.0 else "STALE"
                    
                connector_results.append({
                    "connector_id": conn_id,
                    "name": conn["name"],
                    "status": status_val,
                    "last_sync_time": data.get("succeeded_at") or "never",
                    "freshness": freshness
                })
            finally:
                await toolset.close()
            
        primary = connector_results[0] if connector_results else {"status": "active", "last_sync_time": "never", "freshness": "FRESH"}
        return {
            "status": primary["status"],
            "last_sync_time": primary["last_sync_time"],
            "freshness": primary["freshness"],
            "connectors": connector_results
        }
    except Exception as e:
        if "429" in str(e):
            # Fallback entirely to local mock
            connector_results = []
            for conn in basin_connectors:
                conn_id = conn["id"]
                is_paused = LOCAL_PAUSED_STATES.get(conn_id, False)
                connector_results.append({
                    "connector_id": conn_id,
                    "name": conn["name"],
                    "status": "paused" if is_paused else "active",
                    "last_sync_time": datetime.now(timezone.utc).isoformat(),
                    "freshness": "FRESH"
                })
            primary = connector_results[0] if connector_results else {"status": "active", "last_sync_time": "never", "freshness": "FRESH"}
            return {
                "status": primary["status"],
                "last_sync_time": primary["last_sync_time"],
                "freshness": primary["freshness"],
                "connectors": connector_results
            }
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/heal")
async def heal(background_tasks: BackgroundTasks, connector_id: str = CONNECTOR_ID, basin: str = "rio_cauca"):
    """Runs the existing detect-to-heal flow for a specific connector."""
    LOCAL_PAUSED_STATES[connector_id] = False
    
    # Log heal to Firestore
    log_alert_or_outage("heal", basin, f"Connector {connector_id} healed (manually or via scheduler).")
    
    risk_data = get_risk(basin=basin)
    if TESTING:
        background_tasks.add_task(check_and_trigger_push_sync, risk_data, basin)
        return {
            "status": "Success",
            "connector_id": connector_id,
            "freshness": "FRESH",
            "pipeline_state": "healthy",
            "error": None
        }
    try:
        # Run heal with 5 minute threshold
        res = await check_and_heal_connector(connector_id, 5.0)
        if res.get("status") == "Error" and "429" in str(res.get("error")):
            print("Warning: Fivetran API rate limit (429) hit on heal. Mocking heal success.")
            res = {
                "status": "Success",
                "connector_id": connector_id,
                "freshness": "FRESH",
                "pipeline_state": "healthy",
                "error": None
            }
        background_tasks.add_task(check_and_trigger_push_sync, risk_data)
        return res
    except Exception as e:
        if "429" in str(e):
            print("Warning: Fivetran API rate limit (429) hit in outer heal try. Mocking heal success.")
            background_tasks.add_task(check_and_trigger_push_sync, risk_data)
            return {
                "status": "Success",
                "connector_id": connector_id,
                "freshness": "FRESH",
                "pipeline_state": "healthy",
                "error": None
            }
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/break")
async def break_conn(background_tasks: BackgroundTasks, connector_id: str = CONNECTOR_ID, basin: str = "rio_cauca"):
    """Pauses a specific connector to simulate an outage."""
    LOCAL_PAUSED_STATES[connector_id] = True
    
    # Log outage in Firestore
    log_alert_or_outage("outage", basin, f"Connector {connector_id} broke/outage simulated.")
    
    risk_data = get_risk(basin=basin)
    if TESTING:
        background_tasks.add_task(check_and_trigger_push_sync, risk_data, basin)
        return {"status": "Success", "message": f"Connector {connector_id} paused successfully"}
    toolset = get_mcp_toolset()
    pipeline_state = {"degraded": False, "error": None}
    try:
        modify_args = {
            "schema_file": "open-api-definitions/connections/modify_connection.json",
            "connection_id": connector_id,
            "request_body": json.dumps({"paused": True})
        }
        res_text = await call_with_retry(toolset, "modify_connection", modify_args, pipeline_state)
        if pipeline_state["degraded"]:
            if "429" in str(pipeline_state["error"]):
                print("Warning: Fivetran API rate limit (429) hit. Mocking break success.")
                pipeline_state["degraded"] = False
                pipeline_state["error"] = None
            else:
                raise HTTPException(status_code=500, detail=pipeline_state["error"])
        background_tasks.add_task(check_and_trigger_push_sync, risk_data, basin)
        return {"status": "Success", "message": f"Connector {connector_id} paused successfully"}
    except Exception as e:
        if "429" in str(e):
            print("Warning: Fivetran API rate limit (429) hit in outer try. Mocking break success.")
            background_tasks.add_task(check_and_trigger_push_sync, risk_data, basin)
            return {"status": "Success", "message": f"Connector {connector_id} paused successfully (mocked 429)"}
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        await toolset.close()

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

def run_alerts_and_narration_check(basin: str):
    try:
        risk_data = get_risk(basin=basin)
        check_and_trigger_push_sync(risk_data, basin)
    except Exception as e:
        print(f"Error running alerts check for {basin}: {e}", flush=True)

async def run_autonomous_check_and_heal(basin: str = "rio_cauca"):
    print(f"DEBUG: Starting autonomous check-and-heal run for {basin}", flush=True)
    try:
        status_data = await get_connector_status(basin=basin)
        for conn in status_data.get("connectors", []):
            conn_id = conn["connector_id"]
            name = conn["name"]
            is_paused = conn["status"] == "paused"
            is_stale = conn["freshness"] == "STALE"
            
            if is_paused or is_stale:
                print(f"DEBUG: Connector {conn_id} ({name}) is paused={is_paused} or stale={is_stale}. Triggering autonomous heal.", flush=True)
                # Perform heal
                LOCAL_PAUSED_STATES[conn_id] = False
                if not TESTING:
                    try:
                        res = await check_and_heal_connector(conn_id, 5.0)
                        print(f"DEBUG: Heal connector {conn_id} returned {res}", flush=True)
                    except Exception as ex:
                        print(f"ERROR: Failed to heal connector {conn_id} autonomously: {ex}", flush=True)
                
                # Record the autonomous heal
                add_autonomous_heal({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "connector_id": conn_id,
                    "name": name,
                    "message": "autonomous, no human action"
                })
                # Log incident
                log_alert_or_outage("heal", basin, f"Connector {conn_id} healed autonomously.")
    except Exception as e:
        print(f"ERROR in run_autonomous_check_and_heal: {e}", flush=True)
    
    # Finally, trigger the alert & push notification check via background executor thread
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, run_alerts_and_narration_check, basin)
    except Exception as ex:
        print(f"ERROR: Failed to run check_and_trigger_push_sync in executor: {ex}", flush=True)

@app.post("/check-alerts")
def check_alerts(background_tasks: BackgroundTasks, basin: str = "rio_cauca"):
    """Manually/scheduled triggers the alert state check and push notification flow with autonomous self-heal."""
    background_tasks.add_task(run_autonomous_check_and_heal, basin)
    return {"status": "Success", "message": f"Alert state check and autonomous self-heal triggered for {basin}"}

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

@app.get("/test/sent-pushes")
def get_sent_pushes():
    """Returns the history of sent push notification attempts for testing."""
    return SENT_PUSH_HISTORY

@app.post("/test/clear-sent-pushes")
def clear_sent_pushes():
    """Clears the history of sent push notification attempts for testing."""
    global SENT_PUSH_HISTORY
    SENT_PUSH_HISTORY = []
    return {"status": "Success"}

USGS_LIVE_FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
USGS_LIVE_CACHE = {"data": None, "fetched_at": 0.0}
USGS_LIVE_CACHE_TTL_SECONDS = 60.0

def fetch_usgs_live_feed():
    now = time.time()
    cached = USGS_LIVE_CACHE["data"]
    if cached is not None and (now - USGS_LIVE_CACHE["fetched_at"]) < USGS_LIVE_CACHE_TTL_SECONDS:
        return cached
    try:
        resp = requests.get(USGS_LIVE_FEED_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        USGS_LIVE_CACHE["data"] = data
        USGS_LIVE_CACHE["fetched_at"] = now
        return data
    except Exception as e:
        print(f"Error fetching USGS live feed: {e}", flush=True)
        if cached is not None:
            return cached
        raise HTTPException(status_code=502, detail="USGS live feed unavailable")

@app.get("/live-seismic")
def get_live_seismic(basin: str = "rio_cauca"):
    """Returns real USGS events from the live feed attributed to the basin's
    municipalities (nearest within 150 km), newest first. Stateless and always
    real data: simulated demo events never appear here."""
    basin_config = next((b for b in BASINS if b["id"] == basin), None)
    if basin_config is None:
        raise HTTPException(status_code=404, detail=f"Unknown basin: {basin}")
    live_coords = live_seismic_coordinates()
    munis = {
        m: live_coords[m]
        for m in basin_municipalities(basin_config)
        if m in live_coords
    }
    feed = fetch_usgs_live_feed()
    events = []
    for feature in feed.get("features", []):
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 3:
            continue
        lon, lat, depth = coords[:3]
        closest_muni = None
        min_dist = float("inf")
        for name, (mlat, mlon) in munis.items():
            dist = math.sqrt((lat - mlat) ** 2 + (lon - mlon) ** 2) * 111.0
            if dist < min_dist:
                min_dist = dist
                closest_muni = name
        if not closest_muni or min_dist >= 150.0:
            continue
        prop = feature.get("properties") or {}
        t_ms = prop.get("time") or 0
        dt = datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc)
        events.append({
            "municipality": closest_muni,
            "magnitude": float(prop.get("mag") or 0.0),
            "place": prop.get("place", "Unknown"),
            "time": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "depth_km": float(depth),
            "latitude": float(lat),
            "longitude": float(lon),
            "simulated": False
        })
    events.sort(key=lambda e: e["time"], reverse=True)
    return events

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



def parse_region(place: str) -> str:
    """Region = text after the last comma of the USGS place string, or the
    whole string when there is no comma (matches sql/seismic_active_regions.sql)."""
    if not place:
        return "Unknown"
    return place.split(",")[-1].strip() or "Unknown"


def compute_event_risk(magnitude: float, depth_km: float) -> float:
    """0-1 risk derived from magnitude and depth: magnitude scaled against M8,
    discounted for deeper (less surface-damaging) hypocenters."""
    mag_component = min(1.0, max(0.0, float(magnitude or 0.0) / 8.0))
    depth = float(depth_km or 0.0)
    if depth < 70.0:
        depth_factor = 1.0
    elif depth < 300.0:
        depth_factor = 0.85
    else:
        depth_factor = 0.7
    return round(mag_component * depth_factor, 2)


def severity_for_risk(risk_score: float) -> str:
    if risk_score >= 0.8:
        return "Critical"
    if risk_score >= 0.6:
        return "Danger"
    if risk_score >= 0.4:
        return "Warning"
    return "Low"


def template_event_narration(event: dict, risk_score: float, severity: str) -> str:
    prefix = "SIMULATED drill event (not a real USGS detection): " if event.get("simulated") else ""
    return (
        f"{prefix}M{float(event.get('magnitude') or 0.0):.1f} earthquake {event.get('place', 'Unknown')} "
        f"at {event.get('time', 'unknown time')}, depth {float(event.get('depth_km') or 0.0):.1f} km. "
        f"Derived risk score {risk_score:.2f} grades this event as {severity}."
    )


def seismic_seed_events():
    """Deterministic local stand-in for the BigQuery raw-events table, with
    timestamps relative to now so the 48h/30d windows always have data."""
    now = datetime.now(timezone.utc)

    def seed(event_id, hours_ago, magnitude, place, lat, lon, depth_km):
        return {
            "id": event_id,
            "magnitude": magnitude,
            "place": place,
            "time": (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latitude": lat,
            "longitude": lon,
            "depth_km": depth_km
        }

    return [
        seed("usseed0001", 2, 6.8, "78 km W of San Antonio de los Cobres, Argentina", -24.18, -66.99, 180.0),
        seed("usseed0002", 5, 5.4, "112 km SSE of Lima, Peru", -12.95, -76.62, 42.0),
        seed("usseed0003", 9, 4.7, "23 km NE of Coquimbo, Chile", -29.79, -71.13, 51.0),
        seed("usseed0004", 16, 5.9, "Kermadec Islands, New Zealand", -29.65, -177.84, 35.0),
        seed("usseed0005", 27, 4.6, "41 km SW of Puerto Madero, Mexico", 14.46, -92.69, 28.0),
        seed("usseed0006", 39, 5.1, "South Sandwich Islands region", -56.32, -27.41, 95.0),
        seed("usseed0007", 45, 4.9, "147 km E of Hachinohe, Japan", 40.49, 143.20, 19.0),
        # Older than 48h: only counts toward the 30-day active-regions window.
        seed("usseed0008", 90, 6.1, "62 km SSW of Lima, Peru", -12.51, -77.30, 38.0),
        seed("usseed0009", 200, 5.6, "Off the coast of Aisen, Chile", -45.40, -76.10, 12.0),
        seed("usseed0010", 320, 4.8, "9 km NNW of Mexico City, Mexico", 19.51, -99.18, 60.0),
        seed("usseed0011", 480, 5.2, "Tonga region", -19.92, -174.36, 110.0),
        seed("usseed0012", 650, 4.5, "33 km WSW of Port-au-Prince, Haiti", 18.48, -72.62, 14.0)
    ]


def recent_events_from_rows(rows):
    """Apply the recent-events contract to dict rows: M4.5+, last 48h,
    newest first, max 20 (mirrors sql/seismic_recent_events.sql)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent = [r for r in rows if float(r.get("magnitude") or 0.0) >= 4.5 and r.get("time", "") >= cutoff]
    recent.sort(key=lambda r: r["time"], reverse=True)
    return recent[:20]


def active_regions_from_rows(rows):
    """Group last-30-day rows by parsed region, ranked by event count
    (mirrors sql/seismic_active_regions.sql)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    regions = {}
    for r in rows:
        if r.get("time", "") < cutoff:
            continue
        region = parse_region(r.get("place", ""))
        entry = regions.setdefault(region, {"region": region, "count": 0, "max_magnitude": 0.0})
        entry["count"] += 1
        entry["max_magnitude"] = max(entry["max_magnitude"], float(r.get("magnitude") or 0.0))
    ranked = sorted(regions.values(), key=lambda e: (-e["count"], -e["max_magnitude"]))
    return ranked[:15]


def load_sql(filename: str) -> str:
    with open(f"sql/{filename}", "r", encoding="utf-8") as f:
        return f.read()


def load_raw_events_sql(filename: str) -> str:
    return load_sql(filename).replace("usgs_raw_events.events", RAW_EVENTS_TABLE)


def format_raw_event_row(row_dict: dict) -> dict:
    t = row_dict.get("time")
    if isinstance(t, datetime):
        t = t.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": row_dict.get("id"),
        # BigQuery stores float32; round to USGS's 0.1 precision so prose and
        # UI never show artifacts like 5.199999809265137.
        "magnitude": round(float(row_dict.get("magnitude") or 0.0), 1),
        "place": row_dict.get("place") or "Unknown",
        "time": t,
        "latitude": float(row_dict.get("latitude") or 0.0),
        "longitude": float(row_dict.get("longitude") or 0.0),
        "depth_km": float(row_dict.get("depth_km") or 0.0)
    }


def get_simulated_feed_events():
    """Active simulated demo events shaped as feed events, newest first.
    Older injected events (pre feed-fields) without an id are skipped."""
    events = []
    for demo in get_all_demo_events():
        if not isinstance(demo, dict) or not demo.get("id"):
            continue
        event = format_raw_event_row(demo)
        event["simulated"] = True
        events.append(event)
    events.sort(key=lambda e: e.get("time") or "", reverse=True)
    return events


@app.get("/seismic-events")
def get_seismic_events():
    """Live event feed read from the BigQuery raw-events table (synced by the
    usgs_raw_events Fivetran connector), plus active regions over 30 days.
    Simulated injected events appear at the top, tagged simulated."""
    simulated = get_simulated_feed_events()

    if TESTING:
        rows = seismic_seed_events()
        real_events = recent_events_from_rows(rows)
        active_regions = active_regions_from_rows(rows)
    else:
        real_events = []
        active_regions = []
        try:
            client = bigquery.Client(project='centinela-498622')
            recent_rows = client.query(load_raw_events_sql("seismic_recent_events.sql")).result()
            real_events = [format_raw_event_row(dict(row)) for row in recent_rows]
            region_rows = client.query(load_raw_events_sql("seismic_active_regions.sql")).result()
            active_regions = [
                {
                    "region": row_dict.get("region") or "Unknown",
                    "count": int(row_dict.get("count") or 0),
                    "max_magnitude": round(float(row_dict.get("max_magnitude") or 0.0), 1)
                }
                for row_dict in (dict(row) for row in region_rows)
            ]
        except Exception as e:
            # The raw table only exists once the connector is deployed and has
            # synced; degrade to an empty (but well-formed) feed until then.
            print(f"Error querying raw seismic events from BigQuery: {e}", flush=True)

    for event in real_events:
        event["simulated"] = False
    return {"events": simulated + real_events, "active_regions": active_regions}


def find_raw_event_by_id(event_id: str):
    """Looks up one event: simulated demo events first, then the seeded table
    (TESTING) or the BigQuery raw-events table."""
    for event in get_simulated_feed_events():
        if event.get("id") == event_id:
            return event

    if TESTING:
        for row in seismic_seed_events():
            if row["id"] == event_id:
                event = dict(row)
                event["simulated"] = False
                return event
        return None

    try:
        client = bigquery.Client(project='centinela-498622')
        query = (
            f"SELECT {', '.join(RAW_EVENT_FIELDS)} FROM {RAW_EVENTS_TABLE} "
            "WHERE id = @event_id LIMIT 1"
        )
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("event_id", "STRING", event_id)]
        )
        for row in client.query(query, job_config=job_config).result():
            event = format_raw_event_row(dict(row))
            event["simulated"] = False
            return event
    except Exception as e:
        print(f"Error querying raw seismic event {event_id} from BigQuery: {e}", flush=True)
    return None


@app.get("/seismic-focus")
def get_seismic_focus(id: str):
    """Click-to-focus analysis of one event from the raw feed: derived risk
    score, severity grade, and a narration (real Gemini in production, a
    template string in TESTING)."""
    event = find_raw_event_by_id(id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Unknown seismic event id: {id}")

    risk_score = compute_event_risk(event.get("magnitude"), event.get("depth_km"))
    severity = severity_for_risk(risk_score)

    narration = ""
    if not TESTING:
        narration = run_event_narration_turn({
            **event,
            "risk_score": risk_score,
            "severity": severity
        })
    if not narration:
        narration = template_event_narration(event, risk_score, severity)

    return {
        "event": event,
        "risk_score": risk_score,
        "severity": severity,
        "narration": narration
    }
