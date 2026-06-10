"""The /alert route: graded alerts, narration orchestration, broadcasts."""
import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

import api.core as core
from api.core import TESTING
from api.config import BASINS, basin_municipalities
from api.stores import get_incidents_list
from api.narration import (
    CACHED_ALERT_RESPONSES, CACHED_RISK_DATA_JSONS, GENERATING_NARRATIONS,
    get_cached_narration, get_fallback_narration, get_alert_state_repr,
    generate_narration_in_background,
)
from api.risk_routes import get_risk
from api.incident_routes import log_alert_or_outage
from api.push_routes import check_and_trigger_push_sync
from rapid_agent.centinela_agent import run_narration_turn
from api.i18n import lang_for_cc, translate_text_cached, get_bundle

router = APIRouter()

def _basin_lang(basin: str) -> str:
    cfg = next((b for b in BASINS if b["id"] == basin), None)
    return lang_for_cc(cfg.get("cc")) if cfg else "en"

def _localize_alert(basin: str, resp: dict) -> dict:
    """Adds the resident language + translated broadcast to any alert payload."""
    lang = _basin_lang(basin)
    resp["lang"] = lang
    broadcast = resp.get("resident_broadcast") or ""
    resp["broadcast_translated"] = (
        translate_text_cached(broadcast, lang) if lang != "en" else broadcast)
    return resp

@router.get("/ui-strings")
def get_ui_strings(lang: str = "en"):
    """The resident-facing copy bundle in the requested language (canonical
    English source, translated once per language and cached; English fallback
    on any failure so the card never breaks)."""
    return {"lang": lang, "bundle": get_bundle(lang)}


@router.get("/alert")
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
            return _localize_alert(basin, {
                "graded_alert": graded,
                "agency_incident": {
                    "title": f"REOPENED HISTORICAL INCIDENT: {matching['id']}",
                    "summary": matching["details"],
                    "affected_municipalities": affected
                },
                "resident_broadcast": f"HISTORICAL INCIDENT DATA: {matching['details']}"
            })

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
            return _localize_alert(basin, {
                "graded_alert": graded_alert,
                "agency_incident": {
                    "title": title,
                    "summary": cached["summary"],
                    "affected_municipalities": affected_municipalities
                },
                "resident_broadcast": cached["broadcast"]
            })
            
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
                
        return _localize_alert(basin, alert_response)
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

