import os
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

# State and cooldown tracking for push notifications
TOKEN_LAST_SENT_STATES = {}  # token -> state_repr
TOKEN_COOLDOWNS = {}  # token -> {state_repr: datetime}
SENT_PUSH_HISTORY = []  # list of dicts for testing

# Cache for alert data response to avoid redundant Gemini calls during polling
CACHED_ALERT_RESPONSE = None
CACHED_RISK_DATA_JSON = None

# Local simulation state in case Fivetran API is rate-limited (429)
LOCAL_PAUSED_STATES = {}  # connector_id -> bool
MOCK_DB_STATE = {"populated": True}

# Import the existing agent logic
from rapid_agent.agent import check_and_heal_connector, get_mcp_toolset, call_with_retry

# Import ADK narration agent (Phase 6: all prose runs through the ADK LlmAgent Runner)
from rapid_agent.centinela_agent import run_narration_turn

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
    }
]

CONNECTOR_ID = "plausibly_illustrate"

@app.get("/risk")
def get_risk(basin: str = "rio_cauca"):
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
        # Read the query from the tracked SQL file
        with open("sql/risk_score.sql", "r", encoding="utf-8") as f:
            query = f.read()

        # Dynamically target the requested basin
        query = query.replace("'Rio Cauca'", f"'{basin_name}'")

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
        # 1. Get current risk data
        current_state = get_alert_state_repr(risk_data)
        print(f"DEBUG: current_state={current_state}", flush=True)
        
        # If no active alert state, update all tokens' last sent state to empty, and return
        if not current_state:
            print("DEBUG: current_state is empty, resetting token states", flush=True)
            for token in list(get_fcm_tokens()):
                TOKEN_LAST_SENT_STATES[token] = ""
                TOKEN_COOLDOWNS[token] = {}
            return
            
        # 2. Check which tokens need to be notified
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
            
        # 3. Generate narrative using Gemini
        affected_municipalities = []
        for muni_risk in risk_data:
            score = muni_risk["risk_score"]
            if score >= 0.6:
                affected_municipalities.append(muni_risk["municipality"])
                
        if not affected_municipalities:
            return
            
        # Check if we have cached narratives matching this risk data
        global CACHED_ALERT_RESPONSE, CACHED_RISK_DATA_JSON
        risk_json = json.dumps(risk_data, sort_keys=True)
        
        resident_broadcast_text = ""
        title = "Rio Cauca Basin Compound Flood Risk Alert"
        
        if CACHED_ALERT_RESPONSE and CACHED_RISK_DATA_JSON == risk_json:
            resident_broadcast_text = CACHED_ALERT_RESPONSE.get("resident_broadcast", "")
            
        if not resident_broadcast_text:
            if TESTING:
                narratives = {
                    "summary": f"Mock technical summary describing {basin} basin compound flood risk.",
                    "broadcast": f"Mock resident warning broadcast message mentioning affected municipalities in {basin}."
                }
            else:
                # Phase 6: narration produced via ADK LlmAgent Runner
                narratives = run_narration_turn(basin, risk_data)
            resident_broadcast_text = narratives.get("broadcast", "")
            
            # Cache the response for GET /alert
            graded_alert = []
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
                graded_alert.append({
                    "municipality": muni,
                    "risk_score": score,
                    "severity": severity
                })
                
            CACHED_ALERT_RESPONSE = {
                "graded_alert": graded_alert,
                "agency_incident": {
                    "title": title,
                    "summary": narratives.get("summary", ""),
                    "affected_municipalities": affected_municipalities
                },
                "resident_broadcast": resident_broadcast_text
            }
            CACHED_RISK_DATA_JSON = risk_json
            
        if not resident_broadcast_text:
            return
            
        # Log active alert incident to Firestore
        log_alert_or_outage("alert", basin, f"Compound multi-hazard alert active for basin: {CACHED_ALERT_RESPONSE['agency_incident']['summary'][:120]}", risk_data)

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
def get_alert(basin: str = "rio_cauca"):
    """Turns the current risk scores into graded alerts, incident report, and resident warning."""
    global CACHED_ALERT_RESPONSE, CACHED_RISK_DATA_JSON, REOPENED_INCIDENT_ID
    
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
        
        # Check cache
        risk_json = json.dumps(risk_data, sort_keys=True)
        if CACHED_ALERT_RESPONSE and CACHED_RISK_DATA_JSON == risk_json:
            return CACHED_ALERT_RESPONSE
            
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
                
        # Phase 6: narration produced via ADK LlmAgent Runner (not raw genai.generate_content)
        if TESTING:
            narratives = {
                "summary": f"Mock technical summary describing {basin} basin compound multi-hazard risk.",
                "broadcast": f"Mock resident warning broadcast message mentioning affected municipalities in {basin}."
            }
        else:
            narratives = run_narration_turn(basin, risk_data)
        
        title = f"{basin.replace('_', ' ').title()} Basin Compound Multi-Hazard Alert"
        resident_broadcast_text = narratives.get("broadcast", "")
        
        alert_response = {
            "graded_alert": graded_alert,
            "agency_incident": {
                "title": title,
                "summary": narratives.get("summary", ""),
                "affected_municipalities": affected_municipalities
            },
            "resident_broadcast": resident_broadcast_text
        }
        
        # Cache the result
        CACHED_ALERT_RESPONSE = alert_response
        CACHED_RISK_DATA_JSON = risk_json
        
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
        
    toolset = get_mcp_toolset()
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
    finally:
        await toolset.close()

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
    
    # Finally, trigger the alert & push notification check
    risk_data = get_risk(basin=basin)
    check_and_trigger_push_sync(risk_data, basin)

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

@app.get("/incidents")
def get_incidents():
    """Returns the history of incidents logged in Firestore."""
    return get_incidents_list()

@app.post("/incidents/{incident_id}/reopen")
def reopen_incident(incident_id: str):
    """Reopens a past incident override to display on the dashboard."""
    global REOPENED_INCIDENT_ID, CACHED_ALERT_RESPONSE, CACHED_RISK_DATA_JSON
    incidents = get_incidents_list()
    matching = next((inc for inc in incidents if inc["id"] == incident_id), None)
    if not matching:
        raise HTTPException(status_code=404, detail="Incident not found")
    REOPENED_INCIDENT_ID = incident_id
    CACHED_ALERT_RESPONSE = None
    CACHED_RISK_DATA_JSON = None
    return {"status": "Success", "reopened_incident_id": REOPENED_INCIDENT_ID}

@app.post("/incidents/clear-reopen")
def clear_reopen():
    """Clears reopened incident override and resumes live data view."""
    global REOPENED_INCIDENT_ID, CACHED_ALERT_RESPONSE, CACHED_RISK_DATA_JSON
    REOPENED_INCIDENT_ID = None
    CACHED_ALERT_RESPONSE = None
    CACHED_RISK_DATA_JSON = None
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
