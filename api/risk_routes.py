"""Risk + history + summaries routes (the model-index read paths)."""
import math
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException
from google.cloud import bigquery
from pydantic import BaseModel

import api.core as core
from api.core import TESTING, MOCK_DB_STATE
from api.config import BASINS, TELEMETRY_PROVENANCE, basin_municipalities
from api.stores import get_incidents_list, record_risk_sample_tick, get_risk_sample_ticks
from api.hazard import compute_base_risk, ensure_all_index_fresh, testing_index_rows
from api.demo import merge_demo_event_into_risk
from api.resolution import resolved_places

router = APIRouter()

@router.get("/risk")
def get_risk(basin: str = "rio_cauca"):
    """Returns graded index rows per place, merging any active simulated demo
    event at read time. Rows are copied first: the production index cache must
    never be polluted by a demo merge."""
    base = [dict(r) for r in compute_base_risk(basin=basin)]
    results = merge_demo_event_into_risk(basin, base)
    # Record what users actually see (demo spikes included) so the timeline
    # history matches the lived dashboard.
    record_risk_sample_tick(basin, results)
    return results

@router.get("/risk-all")
def get_risk_all():
    """Index rows for EVERY group in one call (one bulk warehouse pass server
    side). This is the index page's data source; per-group /risk stays for the
    detail poll. Demo events merge per group on copies; ticks record for all
    groups under the standard once-a-minute throttle."""
    if TESTING:
        per_group = {b["id"]: testing_index_rows(b) for b in BASINS}
    else:
        per_group = ensure_all_index_fresh()
    groups = []
    for b in BASINS:
        rows = [dict(r) for r in per_group.get(b["id"], [])]
        rows = merge_demo_event_into_risk(b["id"], rows)
        record_risk_sample_tick(b["id"], rows)
        groups.append({
            "id": b["id"], "name": b["name"], "kind": b.get("kind", "flood-watch"),
            "country": b["country"], "rows": rows,
        })
    return {"groups": groups}

@router.get("/risk-history")
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

@router.get("/telemetry-history")
def get_telemetry_history(basin: str = "rio_cauca", place: str = None):
    """Real telemetry series for the trend panel: observed rainfall (48h,
    hourly), GloFAS discharge (31d, daily) and model soil moisture (72h,
    hourly). Scoped to one place id when `place` is given, otherwise averaged
    across the group. No seeded series exist anymore."""
    basin_config = next((b for b in BASINS if b["id"] == basin), None)
    if basin_config is None:
        raise HTTPException(status_code=404, detail=f"Unknown basin: {basin}")
    scoped_places = basin_config["places"]
    if place:
        scoped_places = [p for p in basin_config["places"] if p["id"] == place]
        if not scoped_places:
            raise HTTPException(status_code=404, detail=f"Unknown place {place} in {basin}")

    if TESTING:
        now = datetime.now(timezone.utc)
        rainfall = [
            {"time": (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "precipitation_mm": round(max(0.0, 2.2 * math.sin((48 - h) / 5.0)), 2)}
            for h in range(48, -1, -2)
        ]
        discharge = [
            {"date": (now - timedelta(days=d)).strftime("%Y-%m-%d"),
             "discharge_m3s": round(1100.0 + 180.0 * math.sin((31 - d) / 6.0), 1)}
            for d in range(31, -1, -1)
        ]
        soil = [
            {"time": (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ"),
             "moisture_m3m3": round(0.32 + 0.05 * math.sin((72 - h) / 9.0), 3)}
            for h in range(72, -1, -3)
        ]
        return {"basin": basin, "place": place, "rainfall": rainfall, "discharge": discharge,
                "soil": soil, "provenance": TELEMETRY_PROVENANCE}

    place_ids = [p["id"] for p in scoped_places]
    place_names = [p["name"] for p in scoped_places]
    rainfall, discharge, soil = [], [], []
    client = bigquery.Client(project='centinela-498622')

    def q_param_list(values):
        return bigquery.ArrayQueryParameter("vals", "STRING", values)

    try:
        job = client.query(
            """SELECT TIMESTAMP_TRUNC(timestamp, HOUR) AS hour,
                      ROUND(AVG(precipitation_mm), 2) AS precipitation_mm
               FROM unified_feeds.rainfall
               WHERE municipality IN UNNEST(@vals)
                 AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
               GROUP BY hour ORDER BY hour LIMIT 60""",
            job_config=bigquery.QueryJobConfig(query_parameters=[q_param_list(place_names)]))
        for row in job.result():
            rd = dict(row)
            t = rd.get("hour")
            rainfall.append({
                "time": t.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(t, datetime) else str(t),
                "precipitation_mm": float(rd.get("precipitation_mm") or 0.0)})
    except Exception as e:
        print(f"Telemetry rainfall query failed for {basin}/{place}: {e}", flush=True)

    try:
        job = client.query(
            """SELECT date, ROUND(AVG(discharge_m_3_s), 1) AS discharge_m3s
               FROM global_hydro.river_discharge
               WHERE place_id IN UNNEST(@vals)
                 AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL 31 DAY)
               GROUP BY date ORDER BY date LIMIT 60""",
            job_config=bigquery.QueryJobConfig(query_parameters=[q_param_list(place_ids)]))
        for row in job.result():
            rd = dict(row)
            d = rd.get("date")
            discharge.append({
                "date": d.isoformat() if hasattr(d, "isoformat") else str(d),
                "discharge_m3s": float(rd.get("discharge_m3s") or 0.0)})
    except Exception as e:
        print(f"Telemetry discharge query failed for {basin}/{place}: {e}", flush=True)

    try:
        job = client.query(
            """SELECT TIMESTAMP_TRUNC(ts, HOUR) AS hour,
                      ROUND(AVG(moisture_m_3_m_3), 3) AS moisture_m3m3
               FROM global_hydro.soil_moisture
               WHERE place_id IN UNNEST(@vals)
                 AND ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 72 HOUR)
               GROUP BY hour ORDER BY hour LIMIT 96""",
            job_config=bigquery.QueryJobConfig(query_parameters=[q_param_list(place_ids)]))
        for row in job.result():
            rd = dict(row)
            t = rd.get("hour")
            soil.append({
                "time": t.strftime("%Y-%m-%dT%H:%M:%SZ") if isinstance(t, datetime) else str(t),
                "moisture_m3m3": float(rd.get("moisture_m3m3") or 0.0)})
    except Exception as e:
        print(f"Telemetry soil query failed for {basin}/{place}: {e}", flush=True)

    return {"basin": basin, "place": place, "rainfall": rainfall, "discharge": discharge,
            "soil": soil, "provenance": TELEMETRY_PROVENANCE}

# --- Conditions at ANY location (real, multi-source, honestly labeled) -------
# Sources: Google Weather hourly history (observed rainfall, 24h), Open-Meteo
# flood API (GloFAS river discharge, model), Open-Meteo forecast API (soil
# moisture, model). Per-source failures degrade to null, never a 500.
# NOTE: when the Google Flood Forecasting API approval arrives, swap/augment
# the discharge source behind these same response fields.


@router.get("/group-summaries")
def get_group_summaries():
    """Worst model-index per group, for ordering the scope strip by current
    criticality. Rides the per-group 60s index cache; rows are COPIED before
    the demo merge (the index cache must never be polluted), so a simulated
    spike reorders the strip honestly. No tick recording here: /risk owns
    the timeline."""
    if not TESTING:
        ensure_all_index_fresh()  # one bulk pass instead of N serial computes
    groups = []
    for b in BASINS:
        rows = merge_demo_event_into_risk(
            b["id"], [dict(r) for r in compute_base_risk(basin=b["id"])])
        worst = None
        for r in rows:
            score = float(r.get("risk_score") or 0.0)
            if worst is None or score > worst["score"]:
                worst = {"score": score,
                         "place": r.get("municipality"),
                         "hazard": r.get("dominant_hazard")}
        groups.append({
            "id": b["id"],
            "name": b["name"],
            "kind": b.get("kind", "flood-watch"),
            "country": b["country"],
            "worst_score": round(worst["score"], 4) if worst else 0.0,
            "worst_place": worst["place"] if worst else None,
            "dominant_hazard": worst["hazard"] if worst else None,
        })
    groups.sort(key=lambda g: g["worst_score"], reverse=True)
    return {"groups": groups}


class DbStateUpdate(BaseModel):
    populated: bool

@router.post("/test/set-db-state")
def set_db_state(data: DbStateUpdate):
    """Sets the mock database state for testing."""
    MOCK_DB_STATE["populated"] = data.populated
    return {"status": "Success", "populated": MOCK_DB_STATE["populated"]}

# ---------------------------------------------------------------------------
# Portfolio demo: live USGS seismic feed + simulated event injection
# ---------------------------------------------------------------------------


