"""Incident + autonomous-heal routes and the incident logger."""
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

import api.core as core
from api.stores import (
    get_incidents_list, add_incident, clear_incidents_store,
    get_autonomous_heals_list, clear_autonomous_heals_store,
)
from api.narration import CACHED_ALERT_RESPONSES, CACHED_RISK_DATA_JSONS
from api.risk_routes import get_risk

router = APIRouter()

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



@router.get("/autonomous-heals")
def get_autonomous_heals():
    """Returns the history of autonomous self-heal events."""
    return get_autonomous_heals_list()

@router.post("/test/clear-autonomous-heals")
def clear_autonomous_heals():
    """Clears the history of autonomous self-heal events for testing."""
    clear_autonomous_heals_store()
    return {"status": "Success"}


@router.get("/incidents")
def get_incidents():
    """Returns the history of incidents logged in Firestore."""
    return get_incidents_list()

@router.post("/incidents/{incident_id}/reopen")
def reopen_incident(incident_id: str):
    """Reopens a past incident override to display on the dashboard."""
    incidents = get_incidents_list()
    matching = next((inc for inc in incidents if inc["id"] == incident_id), None)
    if not matching:
        raise HTTPException(status_code=404, detail="Incident not found")
    core.REOPENED_INCIDENT_ID = incident_id
    CACHED_ALERT_RESPONSES.clear()
    CACHED_RISK_DATA_JSONS.clear()
    return {"status": "Success", "reopened_incident_id": core.REOPENED_INCIDENT_ID}

@router.post("/incidents/clear-reopen")
def clear_reopen():
    """Clears reopened incident override and resumes live data view."""
    core.REOPENED_INCIDENT_ID = None
    CACHED_ALERT_RESPONSES.clear()
    CACHED_RISK_DATA_JSONS.clear()
    return {"status": "Success"}

@router.post("/test/clear-incidents")
def clear_incidents():
    """Clears the incidents list for testing."""
    clear_incidents_store()
    return {"status": "Success"}

