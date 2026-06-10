"""Resident-language layer: the canonical English resident copy, the
country->language map, and Firestore-cached Cloud Translation.

Honesty rules: only RESIDENT-facing copy is translated (alert card content and
push payloads), never model internals. Fixed copy translates once per language
and caches forever (a human reviewer can correct any cached entry in Firestore
without code changes). TESTING: deterministic "[lang] " prefix, zero network.
"""
import hashlib
import threading

from api.core import TESTING, db

# Group country code -> resident language (Cloud Translation codes).
LANG_BY_CC = {
    "CO": "es", "PE": "es", "GT": "es", "CL": "es", "MX": "es", "NI": "es",
    "SV": "es", "HN": "es", "DO": "es", "AR": "es", "BO": "es", "EC": "es",
    "BR": "pt", "HT": "ht", "ID": "id", "PH": "fil", "BD": "bn", "NP": "ne",
    "TR": "tr", "JP": "ja", "TW": "zh-TW", "IR": "fa", "PK": "ur", "TH": "th",
    "VN": "vi", "GR": "el", "IT": "it", "KE": "sw", "NZ": "en",
}

def lang_for_cc(cc):
    return LANG_BY_CC.get((cc or "").upper(), "en")

# Canonical resident copy (single source of truth; the frontend renders this
# bundle, translated server-side). Keys are stable identifiers.
RESIDENT_COPY = {
    "hazard_labels": {
        "FLOOD": "Flood",
        "LANDSLIDE": "Landslide",
        "SEISMIC": "Earthquake / seismic activity",
    },
    "hazard_actions": {
        "FLOOD": "Move to higher ground, away from the river channel and low-lying areas. Do not cross moving water.",
        "LANDSLIDE": "Move away from steep slopes and the base of hillsides; avoid narrow valleys and drainage paths.",
        "SEISMIC": "Drop, cover, and hold on. After shaking stops, move away from damaged structures to open ground.",
    },
    "status_labels": {
        "LOW": "Low", "WARNING": "Warning", "DANGER": "Danger", "CRITICAL": "Critical",
    },
    "guidance": {
        "quake_high": {
            "meaning": "Strong seismic activity has been detected nearby. Expect aftershocks.",
            "items": [
                "Drop, cover, and hold on. After shaking stops, move away from damaged structures to open ground.",
                "Move to open ground away from buildings and power lines.",
                "Expect aftershocks; do not re-enter damaged structures.",
                "Follow instructions from civil protection authorities.",
            ],
        },
        "quake_warning": {
            "meaning": "Elevated hazard signals for this area. Stay alert.",
            "items": [
                "Review your earthquake plan and identify the nearest open assembly area.",
                "Keep emergency supplies and documents reachable.",
                "Follow official channels for updates.",
            ],
        },
        "quake_low": {
            "meaning": "No elevated hazard signals right now. This area is monitored for earthquake activity.",
            "items": [
                "Know your nearest open assembly area (park, plaza, stadium).",
                "Secure heavy furniture and keep an emergency kit reachable.",
                "Stay informed via local safety advisories and public announcements.",
            ],
        },
        "critical": {
            "meaning": "Severe risk of flood, landslide, or seismic activity. Immediate threat to life and property.",
            "items": [
                "EVACUATE IMMEDIATELY to higher ground.",
                "Avoid low-lying areas, river catchments, and steep slopes.",
                "Follow instructions from civil protection authorities without delay.",
                "Check on neighbors and vulnerable family members if safe to do so.",
            ],
        },
        "danger": {
            "meaning": "High hazard probability detected. Conditions are deteriorating rapidly.",
            "items": [
                "PREPARE TO EVACUATE. Secure emergency supply kits.",
                "Move valuable items, electronics, and documents to upper floors.",
                "Stand by and monitor official radio or messaging channels for evacuation orders.",
                "Avoid crossing flooded roads or flowing water.",
            ],
        },
        "warning": {
            "meaning": "Moderate risk. Precautionary measures and vigilance are advised.",
            "items": [
                "STAY VIGILANT. Monitor water levels in local streams and catchments.",
                "Review your family emergency plans and supply kits.",
                "Avoid steep terrains and non-essential travel in affected zones.",
                "Keep safety devices charged and notification options active.",
            ],
        },
        "low": {
            "meaning": "Hydrological conditions are safe and stable.",
            "items": [
                "No immediate actions are required.",
                "Stay informed via local safety advisories and public announcements.",
            ],
        },
    },
    "ui": {
        "hazard": "Hazard", "where": "Where", "action": "Action",
        "when": "When", "source": "Source", "as_of": "as of",
        "no_warnings": "No active warnings for this area.",
        "risk_is_currently": "risk is currently",
        "original_english": "Show original (English)",
        "subscribe": "Get alerts for this place",
        "unsubscribe": "Stop alerts for this place",
        "simulated": "SIMULATED (demo)",
    },
}

_BUNDLE_CACHE = {}  # lang -> bundle
_LOCK = threading.Lock()
_CLIENT = None


def _walk(obj, visit):
    """Apply visit() to every string leaf, preserving structure."""
    if isinstance(obj, str):
        return visit(obj)
    if isinstance(obj, list):
        return [_walk(v, visit) for v in obj]
    if isinstance(obj, dict):
        return {k: _walk(v, visit) for k, v in obj.items()}
    return obj


def _string_leaves(obj, out):
    if isinstance(obj, str):
        out.append(obj)
    elif isinstance(obj, list):
        for v in obj:
            _string_leaves(v, out)
    elif isinstance(obj, dict):
        for v in obj.values():
            _string_leaves(v, out)


def _hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def _read_lang_doc(lang):
    if db is None:
        return {}
    try:
        snap = db.collection("translations").document(lang).get()
        return snap.to_dict() or {} if snap.exists else {}
    except Exception as e:
        print(f"Translation cache read failed ({lang}): {e}", flush=True)
        return {}


def _write_lang_doc(lang, mapping):
    if db is None:
        return
    try:
        db.collection("translations").document(lang).set(mapping, merge=True)
    except Exception as e:
        print(f"Translation cache write failed ({lang}): {e}", flush=True)


def _translate_batch(texts, lang):
    """Cloud Translation v3 via ADC. Raises on failure (caller falls back)."""
    global _CLIENT
    from google.cloud import translate_v3 as translate
    if _CLIENT is None:
        _CLIENT = translate.TranslationServiceClient()
    parent = "projects/centinela-498622/locations/global"
    resp = _CLIENT.translate_text(
        parent=parent, contents=texts, target_language_code=lang,
        source_language_code="en", mime_type="text/plain")
    return [t.translated_text for t in resp.translations]


def translate_text_cached(text, lang):
    """One dynamic string (e.g. the narration broadcast), cached by hash."""
    if not text or lang == "en":
        return text
    if TESTING:
        return f"[{lang}] {text}"
    key = _hash(text)
    cached = _read_lang_doc(lang).get(key)
    if cached:
        return cached
    try:
        out = _translate_batch([text], lang)[0]
        _write_lang_doc(lang, {key: out})
        return out
    except Exception as e:
        print(f"Translation failed ({lang}): {e}", flush=True)
        return text  # honest fallback: English rather than nothing


def get_bundle(lang):
    """The full resident copy bundle in `lang`. Translated once, cached in
    Firestore (per-string, hash-keyed) and in memory per process."""
    lang = (lang or "en").strip() or "en"
    if lang == "en":
        return RESIDENT_COPY
    if TESTING:
        return _walk(RESIDENT_COPY, lambda s: f"[{lang}] {s}")
    with _LOCK:
        if lang in _BUNDLE_CACHE:
            return _BUNDLE_CACHE[lang]
        stored = _read_lang_doc(lang)
        leaves = []
        _string_leaves(RESIDENT_COPY, leaves)
        missing = [t for t in dict.fromkeys(leaves) if _hash(t) not in stored]
        if missing:
            try:
                translated = _translate_batch(missing, lang)
                new_entries = {_hash(src): out for src, out in zip(missing, translated)}
                stored.update(new_entries)
                _write_lang_doc(lang, new_entries)
            except Exception as e:
                print(f"Bundle translation failed ({lang}): {e}", flush=True)
                return RESIDENT_COPY  # English fallback, never a broken bundle
        bundle = _walk(RESIDENT_COPY, lambda s: stored.get(_hash(s), s))
        _BUNDLE_CACHE[lang] = bundle
        return bundle
