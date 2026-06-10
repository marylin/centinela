"""Persistence helpers: Firestore-backed with in-memory fallbacks.

Every helper guards on `db is None` (local/TESTING runs have no Firestore).
The module-level fallback collections (FCM_TOKENS, AUTONOMOUS_HEALS,
INCIDENTS, RISK_SAMPLES_MOCK, DEMO_EVENTS_MOCK) are owned here; the two that
get REBOUND (AUTONOMOUS_HEALS, INCIDENTS) are only rebound inside this module,
so other modules must call these functions rather than importing the lists.
"""
import time

import api.core as core
from api.core import db

FCM_TOKENS = set()
AUTONOMOUS_HEALS = []
INCIDENTS = []

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
                "registered_at": core.firestore.SERVER_TIMESTAMP
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

def get_all_demo_events():
    """All active simulated demo events across basins (Firestore, or the
    in-memory mock when no client exists)."""
    if db is not None:
        try:
            return [doc.to_dict() for doc in db.collection("demo_events").stream()]
        except Exception as e:
            print(f"Error listing demo events from Firestore: {e}", flush=True)
    return list(DEMO_EVENTS_MOCK.values())

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
