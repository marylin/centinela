"""Gemini narration: state-keyed caches, last-good fallbacks, background
generation. All mutable containers here are mutated in place only (safe to
from-import); the actual LLM call lives in rapid_agent.centinela_agent.
"""
import hashlib
from datetime import datetime, timezone

from api.core import TESTING, db
from rapid_agent.centinela_agent import run_narration_turn

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

def default_narration(basin: str):
    """Generic safe fallback for ANY basin: the curated dictionary only covers
    the original groups, and the registry grows by config row."""
    pretty = basin.replace("_", " ").title()
    return {
        "summary": f"Monitoring {pretty} for natural hazards (flood, landslide, seismic).",
        "broadcast": f"System active. No alerts active for {pretty}."
    }

def get_last_good_narration(basin: str):
    if db is not None:
        try:
            doc_ref = db.collection("basin_narrations").document(f"last_good_{basin}")
            doc = doc_ref.get()
            if doc.exists:
                return doc.to_dict()
        except Exception as e:
            print(f"Error reading last good from Firestore: {e}", flush=True)
    return LAST_GOOD_NARRATIVES.get(basin) or default_narration(basin)

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
        return LAST_GOOD_NARRATIVES.get(basin) or default_narration(basin)

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

