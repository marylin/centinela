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
from api.push_routes import check_and_trigger_push_sync, publish_place_transition
from rapid_agent.centinela_agent import run_narration_turn
from api.i18n import lang_for_cc, translate_text_cached, get_bundle
from api.tts import synthesize_alert
from fastapi import Response
from xml.sax.saxutils import escape as xml_escape

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

        # Per-place topic publish on severity transitions (state-keyed +
        # cooldown inside; steady state publishes nothing).
        if background_tasks:
            background_tasks.add_task(publish_place_transition, basin, risk_data)
        else:
            publish_place_transition(basin, risk_data)
        
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



@router.get("/alert-audio")
def get_alert_audio(basin: str = "rio_cauca", background_tasks: BackgroundTasks = None):
    """The resident alert spoken aloud (MP3) in the place's language when the
    voice exists, English otherwise. Built from the same payload residents
    read: status meaning + protective action + live broadcast."""
    payload = get_alert(basin=basin, background_tasks=background_tasks)
    lang = payload.get("lang", "en")
    bundle = get_bundle(lang)
    bundle_en = get_bundle("en")
    graded = payload.get("graded_alert") or []
    worst = max(graded, key=lambda g: g.get("risk_score", 0), default=None)
    dominant = (worst or {}).get("dominant_hazard", "FLOOD")

    def compose(b, broadcast):
        action = b["hazard_actions"].get(dominant, b["hazard_actions"]["FLOOD"])
        return f"{action} {broadcast or ''}".strip()

    text_local = compose(bundle, payload.get("broadcast_translated"))
    text_en = compose(bundle_en, payload.get("resident_broadcast"))
    audio, spoken = synthesize_alert(text_local, text_en, lang)
    return Response(content=audio, media_type="audio/mpeg",
                    headers={"X-Spoken-Lang": spoken, "Cache-Control": "no-store"})


# --- CAP feed (OASIS CAP v1.2) ----------------------------------------------
# The standards-compliant artifact a real civil-protection agency could
# consume. We are NOT an alerting authority: senderName says so, and
# simulated rows publish as Exercise, never Actual.

CAP_SENDER = "centinela-demo@centinela-498622.iam.gserviceaccount.com"
CAP_SENDER_NAME = "Centinela multi-hazard monitor (demonstration system, not an alerting authority)"

def _cap_maps(score):
    if score >= 0.8:
        return "Immediate", "Extreme"
    if score >= 0.6:
        return "Expected", "Severe"
    return "Future", "Moderate"

@router.get("/cap.xml")
def get_cap_feed():
    """Active alerts (WARNING and above) for every monitored place as OASIS
    CAP v1.2, with English + resident-language info blocks."""
    from api.hazard import ensure_all_index_fresh, testing_index_rows
    from api.demo import merge_demo_event_into_risk
    from api.resolution import resolved_places
    from datetime import datetime, timezone

    if TESTING:
        per_group = {b["id"]: testing_index_rows(b) for b in BASINS}
    else:
        per_group = ensure_all_index_fresh()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    alerts = []
    for b in BASINS:
        rows = merge_demo_event_into_risk(b["id"], [dict(r) for r in per_group.get(b["id"], [])])
        lang = _basin_lang(b["id"])
        bundle = get_bundle(lang)
        bundle_en = get_bundle("en")
        anchors = {p["name"]: p.get("anchor") for p in resolved_places(b)}
        for r in rows:
            score = float(r.get("risk_score") or 0.0)
            if score < 0.4:
                continue
            simulated = bool(r.get("simulated"))
            urgency, severity = _cap_maps(score)
            dominant = (r.get("dominant_hazard") or "FLOOD").upper()
            category = "Geo" if dominant in ("SEISMIC", "LANDSLIDE") else "Met"
            anchor = anchors.get(r["municipality"]) or {}
            area_xml = f"<areaDesc>{xml_escape(r['municipality'])}, {xml_escape(b['country'])}</areaDesc>"
            if anchor.get("lat") is not None:
                area_xml += f"<circle>{anchor['lat']:.4f},{anchor['lng']:.4f} 5.0</circle>"

            def info_block(bd, code):
                event = bd["hazard_labels"].get(dominant, bd["hazard_labels"]["FLOOD"])
                action = bd["hazard_actions"].get(dominant, bd["hazard_actions"]["FLOOD"])
                return (
                    f"<info><language>{code}</language>"
                    f"<category>{category}</category>"
                    f"<event>{xml_escape(event)}</event>"
                    f"<urgency>{urgency}</urgency><severity>{severity}</severity>"
                    f"<certainty>Observed</certainty>"
                    f"<headline>{xml_escape(r['municipality'])}: {xml_escape(event)}</headline>"
                    f"<description>{xml_escape(event)} risk index {score:.2f} (Centinela model index).</description>"
                    f"<instruction>{xml_escape(action)}</instruction>"
                    f"<area>{area_xml}</area></info>"
                )

            infos = info_block(bundle_en, "en-US")
            if lang != "en":
                infos += info_block(bundle, lang)
            alerts.append(
                f'<alert xmlns="urn:oasis:names:tc:emergency:cap:1.2">'
                f"<identifier>centinela-{b['id']}-{r.get('place_id', r['municipality'])}-{today}</identifier>"
                f"<sender>{CAP_SENDER}</sender><sent>{now}</sent>"
                f"<status>{'Exercise' if simulated else 'Actual'}</status>"
                f"<msgType>Alert</msgType><scope>Public</scope>"
                f"<note>{xml_escape(CAP_SENDER_NAME)}</note>"
                f"{infos}</alert>"
            )

    # A feed of multiple <alert> entries wrapped for transport.
    feed = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<feed xmlns="http://www.w3.org/2005/Atom"><title>Centinela CAP feed</title>'
            + "".join(f"<entry><content type=\"text/xml\">{a}</content></entry>" for a in alerts)
            + "</feed>")
    return Response(content=feed, media_type="application/xml",
                    headers={"Cache-Control": "no-cache"})
