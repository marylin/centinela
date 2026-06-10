import os
import asyncio
import time
import json
import subprocess
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.cloud import bigquery
from pydantic import BaseModel
import firebase_admin
from firebase_admin import credentials, messaging

# Load environment variables
load_dotenv()

import requests
import concurrent.futures
import math

MUNICIPALITY_COORDINATES = {
    "Cali": {"lat": 3.4516, "lng": -76.5320, "basin": "Rio Cauca"},
    "Yumbo": {"lat": 3.5855, "lng": -76.4952, "basin": "Rio Cauca"},
    "Jamundí": {"lat": 3.2610, "lng": -76.5394, "basin": "Rio Cauca"},
    "Neiva": {"lat": 2.9273, "lng": -75.2819, "basin": "Rio Magdalena"},
    "Girardot": {"lat": 4.3009, "lng": -74.8061, "basin": "Rio Magdalena"},
    "Honda": {"lat": 5.2045, "lng": -74.7411, "basin": "Rio Magdalena"}
}

WEATHER_CACHE = {}
WEATHER_CACHE_EXPIRY = None

def fetch_precipitation_for_muni(muni: str, lat: float, lng: float, api_key: str):
    url = "https://weather.googleapis.com/v1/currentConditions:lookup"
    params = {
        "location.latitude": lat,
        "location.longitude": lng,
        "unitsSystem": "METRIC"
    }
    headers = {
        "X-Goog-Api-Key": api_key
    }
    attempts = 3
    backoff = 1.0
    for attempt in range(attempts):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                precip = data.get("precipitation", {}).get("amount", {}).get("millimeters", 0.0)
                return float(precip)
            else:
                print(f"Weather API error for {muni}: {resp.status_code} (attempt {attempt + 1}/{attempts})", flush=True)
        except Exception as e:
            err_msg = str(e)
            if api_key in err_msg:
                err_msg = err_msg.replace(api_key, "REDACTED_KEY")
            print(f"Error fetching weather for {muni}: {err_msg} (attempt {attempt + 1}/{attempts})", flush=True)
        
        if attempt < attempts - 1:
            time.sleep(backoff)
            backoff *= 2.0
            
    return None

TESTING = os.environ.get("TESTING", "false").lower() == "true"

# Initialize Firebase Admin SDK using Application Default Credentials (ADC)
try:
    firebase_admin.initialize_app()
    print("Firebase Admin SDK initialized successfully using ADC.")
except ValueError:
    pass
except Exception as e:
    print(f"Warning: Firebase Admin SDK failed to initialize: {e}")

# Initialize Firestore client with a fallback for local testing
db = None
try:
    if not TESTING:
        from firebase_admin import firestore
        db = firestore.client()
        print("Firestore client initialized successfully.")
except Exception as e:
    print(f"Warning: Failed to initialize Firestore client: {e}")

# In-memory fallbacks/stores
FCM_TOKENS = set()
AUTONOMOUS_HEALS = []
INCIDENTS = []
REOPENED_INCIDENT_ID = None

def get_fcm_tokens():
    if db is not None:
        try:
            return set(doc.id for doc in db.collection("fcm_tokens").stream())
        except Exception as e:
            print(f"Error fetching FCM tokens from Firestore: {e}")
    return FCM_TOKENS

def add_fcm_token(token):
    if db is not None:
        try:
            db.collection("fcm_tokens").document(token).set({
                "token": token,
                "registered_at": firestore.SERVER_TIMESTAMP
            })
            return
        except Exception as e:
            print(f"Error adding FCM token to Firestore: {e}")
    FCM_TOKENS.add(token)

def discard_fcm_token(token):
    if db is not None:
        try:
            db.collection("fcm_tokens").document(token).delete()
            return
        except Exception as e:
            print(f"Error deleting FCM token from Firestore: {e}")
    FCM_TOKENS.discard(token)

def get_autonomous_heals_list():
    if db is not None:
        try:
            docs = db.collection("autonomous_heals").stream()
            results = []
            for doc in docs:
                data = doc.to_dict()
                if "timestamp" in data and not isinstance(data["timestamp"], str):
                    data["timestamp"] = data["timestamp"].isoformat()
                results.append(data)
            return results
        except Exception as e:
            print(f"Error fetching autonomous heals from Firestore: {e}")
    return AUTONOMOUS_HEALS

def add_autonomous_heal(heal_entry):
    if db is not None:
        try:
            db.collection("autonomous_heals").add(heal_entry)
            return
        except Exception as e:
            print(f"Error adding autonomous heal to Firestore: {e}")
    AUTONOMOUS_HEALS.append(heal_entry)

def clear_autonomous_heals_store():
    global AUTONOMOUS_HEALS
    if db is not None:
        try:
            docs = db.collection("autonomous_heals").stream()
            for doc in docs:
                doc.reference.delete()
        except Exception as e:
            print(f"Error clearing autonomous heals in Firestore: {e}")
    AUTONOMOUS_HEALS = []

def get_incidents_list():
    if db is not None:
        try:
            docs = db.collection("incidents").stream()
            results = []
            for doc in docs:
                data = doc.to_dict()
                if "timestamp" in data and not isinstance(data["timestamp"], str):
                    data["timestamp"] = data["timestamp"].isoformat()
                results.append(data)
            return results
        except Exception as e:
            print(f"Error fetching incidents from Firestore: {e}")
    return INCIDENTS

def add_incident(incident_entry):
    if db is not None:
        try:
            db.collection("incidents").document(incident_entry["id"]).set(incident_entry)
            return
        except Exception as e:
            print(f"Error adding incident to Firestore: {e}")
    INCIDENTS.append(incident_entry)

def clear_incidents_store():
    global INCIDENTS
    if db is not None:
        try:
            docs = db.collection("incidents").stream()
            for doc in docs:
                doc.reference.delete()
        except Exception as e:
            print(f"Error clearing incidents in Firestore: {e}")
    INCIDENTS = []

def log_alert_or_outage(event_type: str, basin: str, details: str, risk_data=None):
    if risk_data is None:
        risk_data = get_risk(basin=basin)
    incident_id = f"inc_{int(time.time())}"
    incident_entry = {
        "id": incident_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "basin": basin,
        "type": event_type, # "alert", "outage", "heal"
        "details": details,
        "risk_data": risk_data or []
    }
    add_incident(incident_entry)
    print(f"DEBUG: Incident logged: {incident_entry}", flush=True)

# --- Composite-risk sample history (one Firestore doc per basin) -------------
# The live risk timeline used to be session-only; recording throttled ticks
# server-side lets every page load seed the sparkline with real history.
RISK_SAMPLE_MIN_INTERVAL_S = 60
RISK_SAMPLE_WINDOW_S = 24 * 3600
RISK_SAMPLE_MAX_TICKS = 300
RISK_SAMPLE_LAST_WRITE = {}   # basin -> epoch seconds of last persisted tick
RISK_SAMPLES_MOCK = {}        # basin -> ticks (TESTING / no-Firestore fallback)

def record_risk_sample_tick(basin: str, risk_data):
    """Persist one composite-risk tick per basin, at most once per minute.
    Read-trim-append on a single per-basin doc: no indexes needed, and the
    24h/300-tick cap bounds the doc size. Last write wins across instances,
    which is fine for a once-a-minute dashboard series."""
    try:
        now_s = time.time()
        if now_s - RISK_SAMPLE_LAST_WRITE.get(basin, 0) < RISK_SAMPLE_MIN_INTERVAL_S:
            return
        RISK_SAMPLE_LAST_WRITE[basin] = now_s
        tick = {
            "t": int(now_s * 1000),
            "samples": {
                m["municipality"]: round(float(m.get("risk_score", 0.0) or 0.0), 4)
                for m in (risk_data or [])
                if isinstance(m, dict) and m.get("municipality")
            }
        }
        if not tick["samples"]:
            return
        cutoff_ms = int((now_s - RISK_SAMPLE_WINDOW_S) * 1000)
        if db is not None:
            doc_ref = db.collection("risk_samples").document(basin)
            snap = doc_ref.get()
            ticks = (snap.to_dict() or {}).get("ticks", []) if snap.exists else []
            ticks = [x for x in ticks if isinstance(x, dict) and x.get("t", 0) >= cutoff_ms]
            ticks.append(tick)
            doc_ref.set({"basin": basin, "updated": tick["t"], "ticks": ticks[-RISK_SAMPLE_MAX_TICKS:]})
        else:
            ticks = [x for x in RISK_SAMPLES_MOCK.get(basin, []) if x.get("t", 0) >= cutoff_ms]
            ticks.append(tick)
            RISK_SAMPLES_MOCK[basin] = ticks[-RISK_SAMPLE_MAX_TICKS:]
    except Exception as e:
        print(f"Error recording risk sample for {basin}: {e}", flush=True)

def get_risk_sample_ticks(basin: str):
    if db is not None:
        try:
            snap = db.collection("risk_samples").document(basin).get()
            if snap.exists:
                ticks = (snap.to_dict() or {}).get("ticks", [])
                return ticks[-RISK_SAMPLE_MAX_TICKS:]
        except Exception as e:
            print(f"Error reading risk history for {basin}: {e}", flush=True)
    return RISK_SAMPLES_MOCK.get(basin, [])

# State and cooldown tracking for push notifications
TOKEN_LAST_SENT_STATES = {}  # token -> state_repr
TOKEN_COOLDOWNS = {}  # token -> {state_repr: datetime}
SENT_PUSH_HISTORY = []  # list of dicts for testing

# Cache for alert data response to avoid redundant Gemini calls during polling
CACHED_ALERT_RESPONSES = {}  # basin -> response_dict
CACHED_RISK_DATA_JSONS = {}  # basin -> risk_json
GENERATING_NARRATIONS = set()  # set of basins currently generating
FIRESTORE_MOCK_CACHE = {}

LAST_GOOD_NARRATIVES = {
    "rio_cauca": {
        "summary": "Monitoring Rio Cauca basin for compound flood and multi-hazard risks.",
        "broadcast": "System active. No extreme weather alerts currently active for Rio Cauca."
    },
    "rio_magdalena": {
        "summary": "Monitoring Rio Magdalena basin for compound flood and multi-hazard risks.",
        "broadcast": "System active. No extreme weather alerts currently active for Rio Magdalena."
    },
    "lima_peru": {
        "summary": "Monitoring Lima (Peru) for seismic hazard along the Pacific subduction margin.",
        "broadcast": "System active. No major seismic alerts currently active for Lima."
    },
    "guatemala_city": {
        "summary": "Monitoring Guatemala City for seismic hazard along the Central America (Cocos plate) margin.",
        "broadcast": "System active. No major seismic alerts currently active for Guatemala City."
    },
    "santiago_chile": {
        "summary": "Monitoring Santiago (Chile) for seismic hazard along the Nazca plate subduction margin.",
        "broadcast": "System active. No major seismic alerts currently active for Santiago."
    },
    "mexico_city": {
        "summary": "Monitoring Mexico City for seismic hazard along the Cocos plate subduction margin.",
        "broadcast": "System active. No major seismic alerts currently active for Mexico City."
    },
    "port_au_prince": {
        "summary": "Monitoring Port-au-Prince for seismic hazard along the Enriquillo-Plantain Garden fault zone.",
        "broadcast": "System active. No major seismic alerts currently active for Port-au-Prince."
    }
}

import hashlib

def get_state_hash(basin: str, risk_data: list):
    state_repr = get_alert_state_repr(risk_data)
    full_string = f"{basin}:{state_repr}"
    return hashlib.sha256(full_string.encode("utf-8")).hexdigest()

def get_cached_narration(basin: str, risk_data: list):
    state_hash = get_state_hash(basin, risk_data)
    if db is not None:
        try:
            doc_ref = db.collection("basin_narrations").document(state_hash)
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"Error reading from Firestore: {e}", flush=True)
    return FIRESTORE_MOCK_CACHE.get(state_hash)

def set_cached_narration(basin: str, risk_data: list, summary: str, broadcast: str):
    state_hash = get_state_hash(basin, risk_data)
    data = {
        "summary": summary,
        "broadcast": broadcast,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if db is not None:
        try:
            db.collection("basin_narrations").document(state_hash).set(data)
            print(f"Successfully wrote narration to Firestore for state_hash: {state_hash}", flush=True)
        except Exception as e:
            print(f"Error writing to Firestore: {e}", flush=True)
    FIRESTORE_MOCK_CACHE[state_hash] = data

def get_last_good_narration(basin: str):
    if db is not None:
        try:
            doc_ref = db.collection("basin_narrations").document(f"last_good_{basin}")
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"Error reading last good from Firestore: {e}", flush=True)
    return LAST_GOOD_NARRATIVES.get(basin)

def update_last_good_narration(basin: str, summary: str, broadcast: str):
    data = {
        "summary": summary,
        "broadcast": broadcast,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    if db is not None:
        try:
            db.collection("basin_narrations").document(f"last_good_{basin}").set(data)
            print(f"Successfully updated last good narration in Firestore for {basin}", flush=True)
        except Exception as e:
            print(f"Error writing last good to Firestore: {e}", flush=True)
    LAST_GOOD_NARRATIVES[basin] = data

def get_fallback_narration(basin: str, risk_data: list):
    is_high_risk = bool(get_alert_state_repr(risk_data))
    last_good = get_last_good_narration(basin)
    
    is_default_placeholder = False
    if last_good:
        broadcast_text = last_good.get("broadcast", "")
        if "no extreme weather alerts" in broadcast_text.lower() or "no alerts active" in broadcast_text.lower():
            is_default_placeholder = True
            
    if is_high_risk:
        if not last_good or is_default_placeholder:
            return {
                "summary": f"A compound multi-hazard alert is currently active for the {basin.replace('_', ' ').title()} basin. Narrative details are being generated.",
                "broadcast": "Urgent: Elevated risk detected. Detailed warning message is currently being generated. Please monitor local safety updates."
            }
        return last_good
    else:
        if last_good:
            return last_good
        return LAST_GOOD_NARRATIVES.get(basin)

def generate_narration_in_background(basin: str, risk_data: list):
    global GENERATING_NARRATIONS
    try:
        print(f"Background narration generation started for {basin}...", flush=True)
        if TESTING:
            narratives = {
                "summary": f"Mock technical summary describing {basin} basin compound multi-hazard risk.",
                "broadcast": f"Mock resident warning broadcast message mentioning affected municipalities in {basin}."
            }
        else:
            narratives = run_narration_turn(basin, risk_data)
            
        summary = narratives.get("summary", "")
        broadcast = narratives.get("broadcast", "")
        
        if summary and broadcast:
            set_cached_narration(basin, risk_data, summary, broadcast)
            update_last_good_narration(basin, summary, broadcast)
            print(f"Background narration generation completed and saved to Firestore for {basin}!", flush=True)
    except Exception as e:
        print(f"Error in background narration generation: {e}", flush=True)
    finally:
        GENERATING_NARRATIONS.discard(basin)

# Local simulation state in case Fivetran API is rate-limited (429)
LOCAL_PAUSED_STATES = {}  # connector_id -> bool
MOCK_DB_STATE = {"populated": True}

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

class AlertNarratives(BaseModel):
    summary: str
    broadcast: str

class TokenRegistration(BaseModel):
    token: str

BASINS = [
    {
        "id": "rio_cauca",
        "name": "Rio Cauca",
        "country": "Colombia",
        "kind": "compound",
        "municipalities": ["Cali", "Yumbo", "Jamundí"],
        "connectors": [
            {
                "id": "plausibly_illustrate",
                "name": "Cauca River Gauge (Sheets)",
                "type": "sheets"
            },
            {
                "id": "garment_dealer",
                "name": "Cauca Soil Saturation (GCS)",
                "type": "gcs"
            },
            {
                "id": "whole_glorify",
                "name": "USGS Seismic Feed (Connector SDK)",
                "type": "connector_sdk"
            }
        ]
    },
    {
        "id": "rio_magdalena",
        "name": "Rio Magdalena",
        "country": "Colombia",
        "kind": "compound",
        # Seeded/demo basin: river and soil values are modeled, not measured.
        # Surfaced in the UI as a SIMULATED tag so modeled data is never
        # presented as live (the Cauca pipeline is the real one).
        "simulated": True,
        "municipalities": ["Neiva", "Girardot", "Honda"],
        "connectors": [
            {
                "id": "magdalena_gauge",
                "name": "Magdalena River Gauge (Mock Sheets)",
                "type": "sheets"
            },
            {
                "id": "magdalena_sat",
                "name": "Magdalena Soil Saturation (Mock GCS)",
                "type": "gcs"
            }
        ]
    },
    {
        "id": "lima_peru",
        "name": "Lima",
        "country": "Peru",
        "kind": "seismic",
        "municipalities": ["Lima", "Callao", "Chorrillos"],
        # Peru bounding box so real coastal-Peru quakes from the global USGS feed
        # attribute to Lima's municipalities. Existing basins keep the default box.
        "seismic_bbox": (
            "    AND latitude BETWEEN -13.0 AND -11.0\n"
            "    AND longitude BETWEEN -78.0 AND -76.0"
        ),
        "connectors": [
            {
                "id": "whole_glorify",
                "name": "USGS Seismic Feed (Connector SDK)",
                "type": "connector_sdk"
            }
        ]
    },
    {
        "id": "guatemala_city",
        "name": "Guatemala City",
        "country": "Guatemala",
        "kind": "seismic",
        "municipalities": ["Guatemala City", "Mixco", "Villa Nueva"],
        # Central America bounding box so real quakes from the global USGS feed
        # attribute to Guatemala City's municipalities. Existing basins keep the default box.
        "seismic_bbox": (
            "    AND latitude BETWEEN 13.0 AND 16.0\n"
            "    AND longitude BETWEEN -92.0 AND -89.0"
        ),
        "connectors": [
            {
                "id": "whole_glorify",
                "name": "USGS Seismic Feed (Connector SDK)",
                "type": "connector_sdk"
            }
        ]
    },
    {
        "id": "santiago_chile",
        "name": "Santiago",
        "country": "Chile",
        "kind": "seismic",
        "municipalities": ["Santiago", "Puente Alto", "Maipu"],
        # Central Chile bounding box so real Nazca-margin quakes from the global USGS
        # feed attribute to Santiago's municipalities. Existing basins keep the default box.
        "seismic_bbox": (
            "    AND latitude BETWEEN -34.5 AND -32.0\n"
            "    AND longitude BETWEEN -72.5 AND -69.5"
        ),
        "connectors": [
            {
                "id": "whole_glorify",
                "name": "USGS Seismic Feed (Connector SDK)",
                "type": "connector_sdk"
            }
        ]
    },
    {
        "id": "mexico_city",
        "name": "Mexico City",
        "country": "Mexico",
        "kind": "seismic",
        "municipalities": ["Mexico City", "Ecatepec", "Nezahualcoyotl"],
        # Central Mexico bounding box so real Cocos-margin quakes from the global USGS
        # feed attribute to Mexico City's municipalities. Existing basins keep the default box.
        "seismic_bbox": (
            "    AND latitude BETWEEN 17.5 AND 20.5\n"
            "    AND longitude BETWEEN -100.5 AND -97.5"
        ),
        "connectors": [
            {
                "id": "whole_glorify",
                "name": "USGS Seismic Feed (Connector SDK)",
                "type": "connector_sdk"
            }
        ]
    },
    {
        "id": "port_au_prince",
        "name": "Port-au-Prince",
        "country": "Haiti",
        "kind": "seismic",
        "municipalities": ["Port-au-Prince", "Carrefour", "Delmas"],
        # Caribbean bounding box so real quakes along the Enriquillo fault zone from the
        # global USGS feed attribute to Port-au-Prince's municipalities. Existing basins
        # keep the default box.
        "seismic_bbox": (
            "    AND latitude BETWEEN 17.5 AND 19.5\n"
            "    AND longitude BETWEEN -74.0 AND -71.0"
        ),
        "connectors": [
            {
                "id": "whole_glorify",
                "name": "USGS Seismic Feed (Connector SDK)",
                "type": "connector_sdk"
            }
        ]
    }
]

CONNECTOR_ID = "plausibly_illustrate"

def compute_base_risk(basin: str = "rio_cauca"):
    """Runs the tracked risk-score SQL, returns graded risk per municipality."""
    global REOPENED_INCIDENT_ID
    if REOPENED_INCIDENT_ID:
        incidents = get_incidents_list()
        matching = next((inc for inc in incidents if inc["id"] == REOPENED_INCIDENT_ID), None)
        if matching and "risk_data" in matching:
            return matching["risk_data"]

    basin_config = next((b for b in BASINS if b["id"] == basin), BASINS[0])
    basin_name = basin_config["name"]

    if TESTING:
        if MOCK_DB_STATE.get("populated", True):
            if basin == "rio_magdalena":
                return [
                    {
                        "municipality": "Neiva",
                        "risk_score": 0.48,
                        "rainfall_mm": 5.2,
                        "river_level_m": 3.8,
                        "soil_saturation": 0.88,
                        "threshold": 4.5,
                        "slope_angle_deg": 15.0,
                        "susceptibility_index": 0.35,
                        "earthquake_magnitude": None,
                        "flood_score": 0.62,
                        "landslide_score": 0.51,
                        "seismic_score": 0.0,
                        "dominant_hazard": "FLOOD"
                    },
                    {
                        "municipality": "Girardot",
                        "risk_score": 0.65,
                        "rainfall_mm": 6.8,
                        "river_level_m": 4.1,
                        "soil_saturation": 0.90,
                        "threshold": 4.5,
                        "slope_angle_deg": 22.0,
                        "susceptibility_index": 0.55,
                        "earthquake_magnitude": 3.4,
                        "flood_score": 0.75,
                        "landslide_score": 0.65,
                        "seismic_score": 0.48,
                        "dominant_hazard": "FLOOD"
                    },
                    {
                        "municipality": "Honda",
                        "risk_score": 0.82,
                        "rainfall_mm": 8.0,
                        "river_level_m": 5.2,
                        "soil_saturation": 0.95,
                        "threshold": 5.0,
                        "slope_angle_deg": 32.0,
                        "susceptibility_index": 0.78,
                        "earthquake_magnitude": None,
                        "flood_score": 0.92,
                        "landslide_score": 0.83,
                        "seismic_score": 0.0,
                        "dominant_hazard": "FLOOD"
                    }
                ]
            elif basin == "lima_peru":
                # Seismic-only basin: flood and landslide read as no-data (0), never
                # fabricated. risk_score is driven entirely by the seismic_score.
                return [
                    {
                        "municipality": "Lima",
                        "risk_score": 0.24,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 5.6,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.8,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Callao",
                        "risk_score": 0.21,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 4.9,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.7,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Chorrillos",
                        "risk_score": 0.18,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 4.2,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.6,
                        "dominant_hazard": "SEISMIC"
                    }
                ]
            elif basin == "guatemala_city":
                # Seismic-only basin: flood and landslide read as no-data (0), never
                # fabricated. risk_score is driven entirely by the seismic_score.
                return [
                    {
                        "municipality": "Guatemala City",
                        "risk_score": 0.25,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 5.8,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.83,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Mixco",
                        "risk_score": 0.22,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 5.1,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.73,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Villa Nueva",
                        "risk_score": 0.19,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 4.4,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.63,
                        "dominant_hazard": "SEISMIC"
                    }
                ]
            elif basin == "santiago_chile":
                # Seismic-only basin: flood and landslide read as no-data (0), never
                # fabricated. risk_score is driven entirely by the seismic_score.
                return [
                    {
                        "municipality": "Santiago",
                        "risk_score": 0.24,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 5.7,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.81,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Puente Alto",
                        "risk_score": 0.21,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 5.0,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.71,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Maipu",
                        "risk_score": 0.18,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 4.3,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.61,
                        "dominant_hazard": "SEISMIC"
                    }
                ]
            elif basin == "mexico_city":
                # Seismic-only basin: flood and landslide read as no-data (0), never
                # fabricated. risk_score is driven entirely by the seismic_score.
                return [
                    {
                        "municipality": "Mexico City",
                        "risk_score": 0.25,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 5.9,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.84,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Ecatepec",
                        "risk_score": 0.22,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 5.2,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.74,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Nezahualcoyotl",
                        "risk_score": 0.19,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 4.5,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.64,
                        "dominant_hazard": "SEISMIC"
                    }
                ]
            elif basin == "port_au_prince":
                # Seismic-only basin: flood and landslide read as no-data (0), never
                # fabricated. risk_score is driven entirely by the seismic_score.
                return [
                    {
                        "municipality": "Port-au-Prince",
                        "risk_score": 0.24,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 5.5,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.79,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Carrefour",
                        "risk_score": 0.21,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 4.8,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.69,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Delmas",
                        "risk_score": 0.18,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 4.1,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.59,
                        "dominant_hazard": "SEISMIC"
                    }
                ]
            else:
                return [
                    {
                        "municipality": "Cali",
                        "risk_score": 0.42,
                        "rainfall_mm": 4.5,
                        "river_level_m": 4.34,
                        "soil_saturation": 0.92,
                        "threshold": 3.5,
                        "slope_angle_deg": 12.0,
                        "susceptibility_index": 0.25,
                        "earthquake_magnitude": None,
                        "flood_score": 0.72,
                        "landslide_score": 0.45,
                        "seismic_score": 0.0,
                        "dominant_hazard": "FLOOD"
                    },
                    {
                        "municipality": "Yumbo",
                        "risk_score": 0.58,
                        "rainfall_mm": 3.0,
                        "river_level_m": 4.34,
                        "soil_saturation": 0.85,
                        "threshold": 3.5,
                        "slope_angle_deg": 28.0,
                        "susceptibility_index": 0.65,
                        "earthquake_magnitude": 2.1,
                        "flood_score": 0.68,
                        "landslide_score": 0.71,
                        "seismic_score": 0.3,
                        "dominant_hazard": "LANDSLIDE"
                    },
                    {
                        "municipality": "Jamundí",
                        "risk_score": 0.76,
                        "rainfall_mm": 5.0,
                        "river_level_m": 4.34,
                        "soil_saturation": 0.95,
                        "threshold": 4.0,
                        "slope_angle_deg": 38.0,
                        "susceptibility_index": 0.88,
                        "earthquake_magnitude": 4.5,
                        "flood_score": 0.73,
                        "landslide_score": 0.9,
                        "seismic_score": 0.64,
                        "dominant_hazard": "LANDSLIDE"
                    }
                ]
        else:
            if basin == "rio_magdalena":
                return [
                    {
                        "municipality": "Neiva",
                        "risk_score": 0.05,
                        "rainfall_mm": 0.0,
                        "river_level_m": 1.2,
                        "soil_saturation": 0.1,
                        "threshold": 4.5,
                        "slope_angle_deg": 15.0,
                        "susceptibility_index": 0.35,
                        "earthquake_magnitude": None,
                        "flood_score": 0.05,
                        "landslide_score": 0.05,
                        "seismic_score": 0.0,
                        "dominant_hazard": "FLOOD"
                    },
                    {
                        "municipality": "Girardot",
                        "risk_score": 0.02,
                        "rainfall_mm": 0.0,
                        "river_level_m": 1.0,
                        "soil_saturation": 0.1,
                        "threshold": 4.5,
                        "slope_angle_deg": 22.0,
                        "susceptibility_index": 0.55,
                        "earthquake_magnitude": None,
                        "flood_score": 0.02,
                        "landslide_score": 0.02,
                        "seismic_score": 0.0,
                        "dominant_hazard": "FLOOD"
                    },
                    {
                        "municipality": "Honda",
                        "risk_score": 0.08,
                        "rainfall_mm": 0.0,
                        "river_level_m": 1.5,
                        "soil_saturation": 0.12,
                        "threshold": 5.0,
                        "slope_angle_deg": 32.0,
                        "susceptibility_index": 0.78,
                        "earthquake_magnitude": None,
                        "flood_score": 0.08,
                        "landslide_score": 0.08,
                        "seismic_score": 0.0,
                        "dominant_hazard": "FLOOD"
                    }
                ]
            elif basin == "lima_peru":
                # Quiet-state seismic-only basin: low real/baseline seismic values,
                # flood and landslide as no-data (0), never fabricated.
                return [
                    {
                        "municipality": "Lima",
                        "risk_score": 0.15,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 3.5,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.5,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Callao",
                        "risk_score": 0.13,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 3.0,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.43,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Chorrillos",
                        "risk_score": 0.1,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 2.3,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.33,
                        "dominant_hazard": "SEISMIC"
                    }
                ]
            elif basin == "guatemala_city":
                # Quiet-state seismic-only basin: low real/baseline seismic values,
                # flood and landslide as no-data (0), never fabricated.
                return [
                    {
                        "municipality": "Guatemala City",
                        "risk_score": 0.15,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 3.5,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.5,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Mixco",
                        "risk_score": 0.13,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 3.0,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.43,
                        "dominant_hazard": "SEISMIC"
                    },
                    {
                        "municipality": "Villa Nueva",
                        "risk_score": 0.1,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": 2.3,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": 0.33,
                        "dominant_hazard": "SEISMIC"
                    }
                ]
            elif basin in ("santiago_chile", "mexico_city", "port_au_prince"):
                # Quiet-state seismic-only basins: low real/baseline seismic values,
                # flood and landslide as no-data (0), never fabricated.
                quiet_munis = next(b for b in BASINS if b["id"] == basin)["municipalities"]
                quiet_values = [(0.15, 3.5, 0.5), (0.13, 3.0, 0.43), (0.1, 2.3, 0.33)]
                return [
                    {
                        "municipality": muni,
                        "risk_score": risk,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.0,
                        "soil_saturation": 0.0,
                        "threshold": 0.0,
                        "slope_angle_deg": 0.0,
                        "susceptibility_index": 0.0,
                        "earthquake_magnitude": mag,
                        "flood_score": 0.0,
                        "landslide_score": 0.0,
                        "seismic_score": seismic,
                        "dominant_hazard": "SEISMIC"
                    }
                    for muni, (risk, mag, seismic) in zip(quiet_munis, quiet_values)
                ]
            else:
                return [
                    {
                        "municipality": "Cali",
                        "risk_score": 0.05,
                        "rainfall_mm": 0.0,
                        "river_level_m": 1.0,
                        "soil_saturation": 0.1,
                        "threshold": 3.5,
                        "slope_angle_deg": 12.0,
                        "susceptibility_index": 0.25,
                        "earthquake_magnitude": None,
                        "flood_score": 0.05,
                        "landslide_score": 0.05,
                        "seismic_score": 0.0,
                        "dominant_hazard": "FLOOD"
                    },
                    {
                        "municipality": "Yumbo",
                        "risk_score": 0.02,
                        "rainfall_mm": 0.0,
                        "river_level_m": 0.8,
                        "soil_saturation": 0.1,
                        "threshold": 3.5,
                        "slope_angle_deg": 28.0,
                        "susceptibility_index": 0.65,
                        "earthquake_magnitude": None,
                        "flood_score": 0.02,
                        "landslide_score": 0.02,
                        "seismic_score": 0.0,
                        "dominant_hazard": "FLOOD"
                    },
                    {
                        "municipality": "Jamundí",
                        "risk_score": 0.08,
                        "rainfall_mm": 0.0,
                        "river_level_m": 1.2,
                        "soil_saturation": 0.12,
                        "threshold": 4.0,
                        "slope_angle_deg": 38.0,
                        "susceptibility_index": 0.88,
                        "earthquake_magnitude": None,
                        "flood_score": 0.08,
                        "landslide_score": 0.08,
                        "seismic_score": 0.0,
                        "dominant_hazard": "FLOOD"
                    }
                ]
    try:
        # Fetch real weather data from Google Weather API if not testing
        api_key = os.environ.get("GOOGLE_WEATHER_API_KEY")
        if api_key:
            now_utc = datetime.now(timezone.utc)
            global WEATHER_CACHE_EXPIRY, WEATHER_CACHE
            if not WEATHER_CACHE_EXPIRY or now_utc >= WEATHER_CACHE_EXPIRY:
                print("Weather cache expired or empty. Fetching new data from Google Weather API...", flush=True)
                new_precip = {}
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                    futures = {
                        executor.submit(fetch_precipitation_for_muni, muni, coord["lat"], coord["lng"], api_key): muni
                        for muni, coord in MUNICIPALITY_COORDINATES.items()
                    }
                    for future in concurrent.futures.as_completed(futures):
                        muni = futures[future]
                        try:
                            val = future.result()
                            if val is not None:
                                new_precip[muni] = val
                        except Exception as e:
                            print(f"Error in future result for {muni}: {e}", flush=True)
                
                if new_precip:
                    WEATHER_CACHE.update(new_precip)
                    WEATHER_CACHE_EXPIRY = now_utc + timedelta(minutes=5)
                    
                    # Write to BigQuery
                    try:
                        bq_client = bigquery.Client(project='centinela-498622')
                        timestamp_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
                        rows_to_insert = []
                        for muni, precip_val in new_precip.items():
                            coord = MUNICIPALITY_COORDINATES[muni]
                            rows_to_insert.append(f"('{timestamp_str}', 'GMP-01', {precip_val}, '{coord['basin']}', '{muni}')")
                        
                        if rows_to_insert:
                            insert_query = f"""
                            INSERT INTO unified_feeds.rainfall (timestamp, station_id, precipitation_mm, basin, municipality)
                            VALUES {', '.join(rows_to_insert)}
                            """
                            query_job = bq_client.query(insert_query)
                            query_job.result()
                            print(f"Successfully inserted {len(rows_to_insert)} weather API records to BigQuery.", flush=True)
                    except Exception as bq_err:
                        print(f"Error writing Weather API data to BigQuery: {bq_err}", flush=True)
        else:
            print("Warning: GOOGLE_WEATHER_API_KEY environment variable is not set.", flush=True)
    except Exception as weather_err:
        print(f"Error in Weather API integration flow: {weather_err}", flush=True)

    try:
        # Read the query from the tracked SQL file
        with open("sql/risk_score.sql", "r", encoding="utf-8") as f:
            query = f.read()

        # Dynamically target the requested basin
        query = query.replace("'Rio Cauca'", f"'{basin_name}'")

        # Swap the seismic bounding box per basin. The default is the Rio Cauca/Colombia
        # box, so existing basins are unchanged (replaced with themselves). Lima supplies
        # its own Peru box so real coastal-Peru quakes attribute to its municipalities.
        default_seismic_bbox = (
            "    AND latitude BETWEEN 2.0 AND 5.0\n"
            "    AND longitude BETWEEN -78.0 AND -75.0"
        )
        query = query.replace(default_seismic_bbox, basin_config.get("seismic_bbox", default_seismic_bbox))

        client = bigquery.Client(project='centinela-498622')
        query_job = client.query(query)
        rows = query_job.result()

        # Map fields to the frontend UI contract
        results = []
        for row in rows:
            row_dict = dict(row)
            muni = row_dict.get("municipality", "")
            if muni.startswith("Jamund"):
                muni = "Jamundí"
            results.append({
                "municipality": muni,
                "risk_score": float(row_dict.get("compound_score", 0.0) or 0.0),
                "rainfall_mm": float(row_dict.get("precipitation_mm", 0.0) or 0.0),
                "river_level_m": float(row_dict.get("river_level_m", 0.0) or 0.0),
                "soil_saturation": float(row_dict.get("saturation_index", 0.0) or 0.0),
                "threshold": float(row_dict.get("alert_threshold_m", 0.0) or 0.0),
                "slope_angle_deg": float(row_dict.get("slope_angle_deg", 0.0) or 0.0),
                "susceptibility_index": float(row_dict.get("susceptibility_index", 0.0) or 0.0),
                "earthquake_magnitude": float(row_dict.get("earthquake_magnitude", 0.0)) if row_dict.get("earthquake_magnitude") is not None else None,
                "flood_score": float(row_dict.get("flood_score", 0.0) or 0.0),
                "landslide_score": float(row_dict.get("landslide_score", 0.0) or 0.0),
                "seismic_score": float(row_dict.get("seismic_score", 0.0) or 0.0),
                "dominant_hazard": row_dict.get("dominant_hazard", "FLOOD")
            })
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/risk")
def get_risk(basin: str = "rio_cauca"):
    """Returns graded risk per municipality, merging any active simulated demo event at read time."""
    results = merge_demo_event_into_risk(basin, compute_base_risk(basin=basin))
    # Record what users actually see (demo spikes included) so the timeline
    # history matches the lived dashboard.
    record_risk_sample_tick(basin, results)
    return results

@app.get("/risk-history")
def get_risk_history(basin: str = "rio_cauca"):
    """Recent composite-risk ticks for the basin (recorded server-side, one
    tick per minute while the dashboard is polled) so the live risk timeline
    is pre-seeded across page loads. Shape:
    {basin, ticks: [{t: epoch_ms, samples: {municipality: score}}]}."""
    if TESTING:
        # Deterministic seeded series: 30 one-minute ticks ending now, gently
        # varying around the current seeded risk values.
        risk = merge_demo_event_into_risk(basin, compute_base_risk(basin=basin))
        now_ms = int(time.time() * 1000)
        ticks = []
        for i in range(30, 0, -1):
            samples = {}
            for m in risk:
                base = float(m.get("risk_score", 0.0) or 0.0)
                wiggle = 0.015 * math.sin(i / 3.0)
                samples[m["municipality"]] = round(min(1.0, max(0.0, base + wiggle)), 4)
            ticks.append({"t": now_ms - i * 60_000, "samples": samples})
        return {"basin": basin, "ticks": ticks}
    return {"basin": basin, "ticks": get_risk_sample_ticks(basin)}

@app.get("/telemetry-history")
def get_telemetry_history(basin: str = "rio_cauca"):
    """River-level (7d) and hourly rainfall (48h) series for the trend chart.
    Honesty contract: rainfall rows are genuinely real (live Google Weather
    readings recorded on each refresh); river-level rows come through the real
    sheet -> Fivetran -> BigQuery pipeline but carry seeded values."""
    basin_config = next((b for b in BASINS if b["id"] == basin), None)
    if basin_config is None:
        raise HTTPException(status_code=404, detail=f"Unknown basin: {basin}")
    basin_name = basin_config["name"]

    if TESTING:
        now = datetime.now(timezone.utc)
        river = [
            {
                "time": (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "river_level_m": round(4.1 + 0.65 * math.sin((48 - h) / 7.0) + (48 - h) * 0.012, 2),
                "threshold_m": 4.0
            }
            for h in range(48, -1, -6)
        ]
        rainfall = [
            {
                "time": (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "precipitation_mm": round(max(0.0, 2.2 * math.sin((48 - h) / 5.0)) , 2)
            }
            for h in range(48, -1, -2)
        ]
        discharge = [
            {
                "date": (now - timedelta(days=d)).strftime("%Y-%m-%d"),
                "discharge_m3s": round(1100.0 + 180.0 * math.sin((31 - d) / 6.0), 1)
            }
            for d in range(31, -1, -1)
        ]
        return {"basin": basin, "river": river, "rainfall": rainfall, "discharge": discharge,
                "provenance": {"rainfall": "live", "river": "pipeline-seeded", "discharge": "model-glofas"}}

    river, rainfall, discharge = [], [], []
    try:
        client = bigquery.Client(project='centinela-498622')
        river_sql = load_sql("telemetry_river_history.sql").replace("'Rio Cauca'", f"'{basin_name}'")
        for row in client.query(river_sql).result():
            rd = dict(row)
            t = rd.get("reading_time")
            river.append({
                "time": t.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(t, datetime) else str(t),
                "river_level_m": float(rd.get("river_level_m") or 0.0),
                "threshold_m": float(rd.get("alert_threshold_m") or 0.0)
            })
        rain_sql = load_sql("telemetry_rainfall_history.sql").replace("'Rio Cauca'", f"'{basin_name}'")
        for row in client.query(rain_sql).result():
            rd = dict(row)
            t = rd.get("hour")
            rainfall.append({
                "time": t.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(t, datetime) else str(t),
                "precipitation_mm": float(rd.get("precipitation_mm") or 0.0)
            })
    except Exception as e:
        # Degrade to empty (well-formed) series; the chart shows its empty state.
        print(f"Error querying telemetry history for {basin}: {e}", flush=True)
    try:
        # Separate try: the global_hydro dataset only exists once the second
        # connector has synced; rainfall/river must not degrade with it.
        client = bigquery.Client(project='centinela-498622')
        discharge_sql = load_sql("telemetry_discharge_history.sql").replace("'rio_cauca'", f"'{basin}'")
        for row in client.query(discharge_sql).result():
            rd = dict(row)
            d = rd.get("date")
            discharge.append({
                "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
                "discharge_m3s": float(rd.get("discharge_m3s") or 0.0)
            })
    except Exception as e:
        print(f"Error querying discharge history for {basin}: {e}", flush=True)
    return {"basin": basin, "river": river, "rainfall": rainfall, "discharge": discharge,
            "provenance": {"rainfall": "live", "river": "pipeline-seeded", "discharge": "model-glofas"}}

# --- Conditions at ANY location (real, multi-source, honestly labeled) -------
# Sources: Google Weather hourly history (observed rainfall, 24h), Open-Meteo
# flood API (GloFAS river discharge, model), Open-Meteo forecast API (soil
# moisture, model). Per-source failures degrade to null, never a 500.
# NOTE: when the Google Flood Forecasting API approval arrives, swap/augment
# the discharge source behind these same response fields.
LOCATION_CONDITIONS_CACHE = {}  # (lat, lng rounded) -> (expiry_epoch_s, payload)
LOCATION_CONDITIONS_TTL_S = 30 * 60

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

LOCATION_CONDITIONS_PROVENANCE = {
    "rainfall": "observed · Google Weather",
    "river_discharge": "model · GloFAS via Open-Meteo",
    "soil_moisture": "model · ECMWF via Open-Meteo"
}

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
            "provenance": LOCATION_CONDITIONS_PROVENANCE
        }

    cache_key = (round(lat, 2), round(lng, 2))
    now_s = time.time()
    cached = LOCATION_CONDITIONS_CACHE.get(cache_key)
    if cached and cached[0] > now_s:
        return cached[1]

    payload = {"latitude": lat, "longitude": lng, "rainfall": None,
               "river_discharge": None, "soil_moisture": None,
               "provenance": LOCATION_CONDITIONS_PROVENANCE}
    api_key = os.environ.get("GOOGLE_WEATHER_API_KEY")
    if api_key:
        try:
            payload["rainfall"] = fetch_location_rainfall_history(lat, lng, api_key)
        except Exception as e:
            print(f"location-conditions rainfall failed: {e}", flush=True)
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

def get_alert_state_repr(risk_data):
    active_alerts = []
    for muni_risk in risk_data:
        muni = muni_risk["municipality"]
        score = muni_risk["risk_score"]
        if score >= 0.8:
            severity = "EXTREME"
        elif score >= 0.6:
            severity = "HIGH"
        elif score >= 0.4:
            severity = "MODERATE"
        else:
            severity = "LOW"
        if severity in ["HIGH", "EXTREME"]:
            active_alerts.append((muni, severity))
    active_alerts.sort()
    return ",".join(f"{m}:{s}" for m, s in active_alerts)

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
    global CACHED_ALERT_RESPONSES, CACHED_RISK_DATA_JSONS, LAST_GOOD_NARRATIVES, GENERATING_NARRATIONS, REOPENED_INCIDENT_ID
    
    if REOPENED_INCIDENT_ID:
        incidents = get_incidents_list()
        matching = next((inc for inc in incidents if inc["id"] == REOPENED_INCIDENT_ID), None)
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
            
            # For mock connectors (Magdalena basin), return simulated status
            if conn_id in ["magdalena_gauge", "magdalena_sat"]:
                is_paused = LOCAL_PAUSED_STATES.get(conn_id, False)
                connector_results.append({
                    "connector_id": conn_id,
                    "name": conn["name"],
                    "status": "paused" if is_paused else "active",
                    "last_sync_time": datetime.now(timezone.utc).isoformat(),
                    "freshness": "FRESH"
                })
                continue

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
async def heal(background_tasks: BackgroundTasks, connector_id: str = "plausibly_illustrate", basin: str = "rio_cauca"):
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
async def break_conn(background_tasks: BackgroundTasks, connector_id: str = "plausibly_illustrate", basin: str = "rio_cauca"):
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

@app.get("/autonomous-heals")
def get_autonomous_heals():
    """Returns the history of autonomous self-heal events."""
    return get_autonomous_heals_list()

@app.post("/test/clear-autonomous-heals")
def clear_autonomous_heals():
    """Clears the history of autonomous self-heal events for testing."""
    clear_autonomous_heals_store()
    return {"status": "Success"}

@app.get("/basins")
def get_basins():
    """Returns the configured basins so the selector can be populated from config."""
    return [
        {
            "id": b["id"],
            "name": b["name"],
            "country": b["country"],
            "kind": b.get("kind", "compound"),
            "simulated": b.get("simulated", False),
            "municipalities": b["municipalities"]
        }
        for b in BASINS
    ]

@app.get("/incidents")
def get_incidents():
    """Returns the history of incidents logged in Firestore."""
    return get_incidents_list()

@app.post("/incidents/{incident_id}/reopen")
def reopen_incident(incident_id: str):
    """Reopens a past incident override to display on the dashboard."""
    global REOPENED_INCIDENT_ID, CACHED_ALERT_RESPONSES, CACHED_RISK_DATA_JSONS
    incidents = get_incidents_list()
    matching = next((inc for inc in incidents if inc["id"] == incident_id), None)
    if not matching:
        raise HTTPException(status_code=404, detail="Incident not found")
    REOPENED_INCIDENT_ID = incident_id
    CACHED_ALERT_RESPONSES.clear()
    CACHED_RISK_DATA_JSONS.clear()
    return {"status": "Success", "reopened_incident_id": REOPENED_INCIDENT_ID}

@app.post("/incidents/clear-reopen")
def clear_reopen():
    """Clears reopened incident override and resumes live data view."""
    global REOPENED_INCIDENT_ID, CACHED_ALERT_RESPONSES, CACHED_RISK_DATA_JSONS
    REOPENED_INCIDENT_ID = None
    CACHED_ALERT_RESPONSES.clear()
    CACHED_RISK_DATA_JSONS.clear()
    return {"status": "Success"}

@app.post("/test/clear-incidents")
def clear_incidents():
    """Clears the incidents list for testing."""
    clear_incidents_store()
    return {"status": "Success"}

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

class DbStateUpdate(BaseModel):
    populated: bool

@app.post("/test/set-db-state")
def set_db_state(data: DbStateUpdate):
    """Sets the mock database state for testing."""
    MOCK_DB_STATE["populated"] = data.populated
    return {"status": "Success", "populated": MOCK_DB_STATE["populated"]}

# ---------------------------------------------------------------------------
# Portfolio demo: live USGS seismic feed + simulated event injection
# ---------------------------------------------------------------------------

# Same coordinates the USGS connector uses for nearest-municipality attribution,
# extended with the Rio Magdalena municipalities from MUNICIPALITY_COORDINATES.
LIVE_SEISMIC_COORDINATES = {
    "Cali": (3.4516, -76.5320),
    "Yumbo": (3.5833, -76.4917),
    "Jamundí": (3.2667, -76.5333),
    "Neiva": (2.9273, -75.2819),
    "Girardot": (4.3009, -74.8061),
    "Honda": (5.2045, -74.7411),
    "Lima": (-12.046, -77.043),
    "Callao": (-12.056, -77.118),
    "Chorrillos": (-12.168, -77.022),
    "Guatemala City": (14.6349, -90.5069),
    "Mixco": (14.6333, -90.6064),
    "Villa Nueva": (14.5269, -90.5969),
    "Santiago": (-33.4489, -70.6693),
    "Puente Alto": (-33.6117, -70.5756),
    "Maipu": (-33.5110, -70.7580),
    "Mexico City": (19.4326, -99.1332),
    "Ecatepec": (19.6010, -99.0500),
    "Nezahualcoyotl": (19.4003, -98.9870),
    "Port-au-Prince": (18.5944, -72.3074),
    "Carrefour": (18.5410, -72.3990),
    "Delmas": (18.5500, -72.3000)
}

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
    munis = {
        m: LIVE_SEISMIC_COORDINATES[m]
        for m in basin_config["municipalities"]
        if m in LIVE_SEISMIC_COORDINATES
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

# Simulated demo events live in Firestore (Cloud Run runs multiple instances,
# so in-memory state would not be seen by the next request). The in-memory
# dict is only the local/TESTING fallback when no Firestore client exists.
DEMO_EVENTS_MOCK = {}

def get_demo_event(basin: str):
    if db is not None:
        try:
            doc = db.collection("demo_events").document(basin).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            print(f"Error reading demo event from Firestore: {e}", flush=True)
    return DEMO_EVENTS_MOCK.get(basin)

def set_demo_event(basin: str, event: dict):
    if db is not None:
        try:
            db.collection("demo_events").document(basin).set(event)
            return
        except Exception as e:
            print(f"Error writing demo event to Firestore: {e}", flush=True)
    DEMO_EVENTS_MOCK[basin] = event

def delete_demo_event(basin: str):
    if db is not None:
        try:
            db.collection("demo_events").document(basin).delete()
        except Exception as e:
            print(f"Error deleting demo event from Firestore: {e}", flush=True)
    DEMO_EVENTS_MOCK.pop(basin, None)

def merge_demo_event_into_risk(basin: str, results):
    """Read-time merge of an active simulated demo event into the risk rows.
    Uses the same weights as sql/risk_score.sql (seismic = magnitude/7.0,
    compound = 0.40 flood + 0.30 landslide + 0.30 seismic). For seismic-only
    basins (flood and landslide read as no-data), the seismic score carries
    the full compound weight so the injected event is visible. The merged row
    is tagged simulated so it is never presented as a real USGS detection."""
    if not isinstance(results, list):
        return results
    event = get_demo_event(basin)
    if not event:
        return results
    muni = event.get("municipality")
    try:
        magnitude = float(event.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        return results
    for row in results:
        if not isinstance(row, dict) or row.get("municipality") != muni:
            continue
        seismic_score = round(min(1.0, max(0.0, magnitude / 7.0)), 2)
        flood = float(row.get("flood_score") or 0.0)
        landslide = float(row.get("landslide_score") or 0.0)
        if flood == 0.0 and landslide == 0.0:
            risk_score = seismic_score
        else:
            risk_score = round((0.40 * flood) + (0.30 * landslide) + (0.30 * seismic_score), 2)
        if flood >= landslide and flood >= seismic_score:
            dominant = "FLOOD"
        elif landslide >= flood and landslide >= seismic_score:
            dominant = "LANDSLIDE"
        else:
            dominant = "SEISMIC"
        row["earthquake_magnitude"] = magnitude
        row["seismic_score"] = seismic_score
        row["risk_score"] = risk_score
        row["dominant_hazard"] = dominant
        row["simulated"] = True
    return results

def remove_simulated_incidents(basin: str):
    """Removes incidents created by a simulated demo event for the basin."""
    global INCIDENTS

    def is_simulated_incident(inc):
        if not isinstance(inc, dict) or inc.get("basin") != basin:
            return False
        if inc.get("simulated"):
            return True
        return any(
            isinstance(r, dict) and r.get("simulated")
            for r in inc.get("risk_data", [])
        )

    if db is not None:
        try:
            for doc in db.collection("incidents").stream():
                if is_simulated_incident(doc.to_dict() or {}):
                    doc.reference.delete()
        except Exception as e:
            print(f"Error removing simulated incidents from Firestore: {e}", flush=True)
    INCIDENTS = [inc for inc in INCIDENTS if not is_simulated_incident(inc)]

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
    if data.municipality not in basin_config["municipalities"]:
        raise HTTPException(
            status_code=400,
            detail=f"Municipality {data.municipality} is not part of basin {data.basin}"
        )
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    muni_lat, muni_lon = LIVE_SEISMIC_COORDINATES.get(data.municipality, (0.0, 0.0))
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

RAW_EVENTS_TABLE = os.environ.get("SEISMIC_RAW_EVENTS_TABLE", "usgs_raw_events.events")
RAW_EVENT_FIELDS = ["id", "magnitude", "place", "time", "latitude", "longitude", "depth_km"]


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


def get_all_demo_events():
    """All active simulated demo events across basins (Firestore, or the
    in-memory mock when no client exists)."""
    if db is not None:
        try:
            return [doc.to_dict() for doc in db.collection("demo_events").stream()]
        except Exception as e:
            print(f"Error listing demo events from Firestore: {e}", flush=True)
    return list(DEMO_EVENTS_MOCK.values())


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
