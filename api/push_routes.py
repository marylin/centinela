"""Push notifications: token registry routes, state-keyed sends, cooldowns."""
import asyncio
import time
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, BackgroundTasks
from firebase_admin import messaging
from pydantic import BaseModel

from api.core import TESTING
from api.stores import get_fcm_tokens, add_fcm_token, discard_fcm_token
from api.narration import (
    get_alert_state_repr, get_cached_narration, set_cached_narration,
    get_fallback_narration, update_last_good_narration,
    generate_narration_in_background, GENERATING_NARRATIONS,
)
from rapid_agent.centinela_agent import run_narration_turn
from api.risk_routes import get_risk
from api.incident_routes import log_alert_or_outage
from api.config import BASINS
from api.core import db
from api.i18n import lang_for_cc, get_bundle, translate_text_cached

router = APIRouter()

# State and cooldown tracking for push notifications
TOKEN_LAST_SENT_STATES = {}  # token -> state_repr
TOKEN_COOLDOWNS = {}  # token -> {state_repr: datetime}
SENT_PUSH_HISTORY = []  # list of dicts for testing


class TokenRegistration(BaseModel):
    token: str


def check_and_trigger_push_sync(risk_data, basin="rio_cauca"):
    publish_place_transition(basin, risk_data)
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


def run_alerts_and_narration_check(basin: str):
    try:
        risk_data = get_risk(basin=basin)
        check_and_trigger_push_sync(risk_data, basin)
    except Exception as e:
        print(f"Error running alerts check for {basin}: {e}", flush=True)


@router.post("/register-token")
def register_token(data: TokenRegistration, background_tasks: BackgroundTasks, basin: str = "rio_cauca"):
    """Registers an FCM token for push notifications."""
    token = data.token.strip()
    if token:
        add_fcm_token(token)
        risk_data = get_risk(basin=basin)
        background_tasks.add_task(check_and_trigger_push_sync, risk_data, basin)
        return {"status": "Success", "message": f"Token registered. Total tokens: {len(get_fcm_tokens())}"}
    return {"status": "Error", "message": "Invalid token"}


@router.get("/test/sent-pushes")
def get_sent_pushes():
    """Returns the history of sent push notification attempts for testing."""
    return SENT_PUSH_HISTORY

@router.post("/test/clear-sent-pushes")
def clear_sent_pushes():
    """Clears the history of sent push notification attempts for testing."""
    global SENT_PUSH_HISTORY
    SENT_PUSH_HISTORY = []
    return {"status": "Success"}



# --- Per-place FCM topics (subscribe to YOUR place; one publish fans out) ---
# Topic per group: place_<basin>. Per-basin last-sent state + cooldown persist
# in Firestore (in-memory dies across Cloud Run instances); TESTING uses the
# in-memory mock and records publishes in a separate history so the legacy
# per-token assertions stay untouched.

TOPIC_COOLDOWN_S = 600
TOPIC_PUSH_HISTORY = []          # TESTING-visible record of topic publishes
TOPIC_STATE_MOCK = {}            # basin -> {state, sent_ms} (TESTING fallback)

def _read_topic_state(basin):
    if db is not None:
        try:
            snap = db.collection("topic_push").document(basin).get()
            return snap.to_dict() or {} if snap.exists else {}
        except Exception as e:
            print(f"Topic state read failed ({basin}): {e}", flush=True)
            return {}
    return TOPIC_STATE_MOCK.get(basin, {})

def _write_topic_state(basin, state_repr, now_ms):
    payload = {"state": state_repr, "sent_ms": now_ms}
    if db is not None:
        try:
            db.collection("topic_push").document(basin).set(payload)
            return
        except Exception as e:
            print(f"Topic state write failed ({basin}): {e}", flush=True)
    TOPIC_STATE_MOCK[basin] = payload

def publish_place_transition(basin, risk_data):
    """One topic publish per severity-state transition per group, in the
    place's language, with a deep link to the place page. Steady state and
    cooldown windows publish nothing."""
    try:
        state_repr = get_alert_state_repr(risk_data)
        now_ms = int(time.time() * 1000)
        prev = _read_topic_state(basin)
        if prev.get("state", "") == state_repr:
            return
        if now_ms - int(prev.get("sent_ms") or 0) < TOPIC_COOLDOWN_S * 1000:
            return
        if not state_repr:
            # Transition back to calm: remember it, send nothing.
            _write_topic_state(basin, state_repr, now_ms)
            return

        worst = max(risk_data, key=lambda r: float(r.get("risk_score") or 0.0))
        cfg = next((b for b in BASINS if b["id"] == basin), {})
        lang = lang_for_cc(cfg.get("cc"))
        bundle = get_bundle(lang)
        sev_key = "CRITICAL" if worst["risk_score"] >= 0.8 else "DANGER" if worst["risk_score"] >= 0.6 else "WARNING"
        sev_label = bundle["status_labels"].get(sev_key, sev_key)
        dominant = (worst.get("dominant_hazard") or "FLOOD").upper()
        action = bundle["hazard_actions"].get(dominant, bundle["hazard_actions"]["FLOOD"])
        simulated = any(r.get("simulated") for r in risk_data)
        title = f"{'[SIMULATED] ' if simulated else ''}{worst['municipality']}: {sev_label}"
        body = action
        data = {"basin": basin, "route": f"#/place/{worst.get('place_id', basin)}"}

        if TESTING:
            TOPIC_PUSH_HISTORY.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "topic": f"place_{basin}", "title": title, "body": body, "data": data,
            })
        else:
            messaging.send(messaging.Message(
                topic=f"place_{basin}",
                notification=messaging.Notification(title=title, body=body),
                data=data,
            ))
            print(f"Topic publish: place_{basin} -> {title}", flush=True)
        _write_topic_state(basin, state_repr, now_ms)
    except Exception as e:
        print(f"Topic publish failed ({basin}): {e}", flush=True)

class PlaceSubscription(BaseModel):
    token: str
    basin: str

@router.post("/subscribe-place")
def subscribe_place(data: PlaceSubscription):
    """Subscribe a device token to one place's alert topic."""
    if not any(b["id"] == data.basin for b in BASINS):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Unknown place: {data.basin}")
    token = (data.token or "").strip()
    if not token:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Missing token")
    topic = f"place_{data.basin}"
    if not TESTING:
        messaging.subscribe_to_topic([token], topic)
    return {"status": "subscribed", "topic": topic}

@router.post("/unsubscribe-place")
def unsubscribe_place(data: PlaceSubscription):
    topic = f"place_{data.basin}"
    token = (data.token or "").strip()
    if token and not TESTING:
        messaging.unsubscribe_from_topic([token], topic)
    return {"status": "unsubscribed", "topic": topic}

@router.get("/test/sent-topic-pushes")
def get_sent_topic_pushes():
    return TOPIC_PUSH_HISTORY

@router.post("/test/clear-sent-topic-pushes")
def clear_sent_topic_pushes():
    TOPIC_PUSH_HISTORY.clear()
    TOPIC_STATE_MOCK.clear()
    return {"status": "Success"}
