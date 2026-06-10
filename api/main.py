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
from api.static_routes import router as static_router
from api.places_routes import router as places_router
from api.watchlist_routes import router as watchlist_router
from api.demo_routes import router as demo_router

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
app.include_router(static_router)
app.include_router(places_router)
app.include_router(watchlist_router)
app.include_router(demo_router)

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

