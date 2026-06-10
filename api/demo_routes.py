"""Demo inject/clear routes (operator simulation, honestly labeled)."""
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from api.config import BASINS, basin_municipalities
from api.stores import (
    set_demo_event, delete_demo_event, add_incident, remove_simulated_incidents,
)
from api.resolution import live_seismic_coordinates
from api.risk_routes import get_risk
from api.push_routes import check_and_trigger_push_sync, run_alerts_and_narration_check

router = APIRouter()

class DemoEventRequest(BaseModel):
    basin: str
    municipality: str
    magnitude: float

class DemoClearRequest(BaseModel):
    basin: str

@router.post("/demo/inject-event")
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

@router.post("/demo/clear-event")
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



