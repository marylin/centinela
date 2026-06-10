"""Coordinate-resolution glue: caches, Firestore persistence, and the
resolved views of the registry (anchors, hydro points, derived bboxes).
The pure geocode/probe logic lives in api/places_resolver.py.
"""
import threading
import time

import api.core as core
from api.core import TESTING, db
from api.config import BASINS, SEISMIC_BBOX_PAD_DEG
from api.places_resolver import cell_scale_for, resolve_entries

# --- Coordinate resolution (anchor + hydro point per place, nothing hardcoded)

SEISMIC_BBOX_PAD_DEG = 1.5
RESOLUTION_CACHE = {"doc": None, "fetched_at": 0.0}
RESOLUTION_LOCK = threading.Lock()

# Deterministic TESTING resolution: the pre-derivation coordinates as anchors
# plus fixed hydro metadata mirroring the verified 2026-06-10 probe run. Kept
# ONLY for fixtures; production never reads these.
TESTING_RESOLUTION = {
    "cali":            {"anchor": {"lat": 3.4516, "lng": -76.5320},  "p50": 1078.0},
    "yumbo":           {"anchor": {"lat": 3.5855, "lng": -76.4952},  "p50": 2.8},
    "jamundi":         {"anchor": {"lat": 3.2610, "lng": -76.5394},  "p50": 848.2},
    "neiva":           {"anchor": {"lat": 2.9273, "lng": -75.2819},  "p50": 0.6},
    "girardot":        {"anchor": {"lat": 4.3009, "lng": -74.8061},  "p50": 471.6},
    "honda":           {"anchor": {"lat": 5.2045, "lng": -74.7411},  "p50": 1900.0},
    "lima":            {"anchor": {"lat": -12.046, "lng": -77.043},  "p50": 53.7},
    "guatemala_city":  {"anchor": {"lat": 14.6349, "lng": -90.5069}, "p50": 0.2},
    "santiago":        {"anchor": {"lat": -33.4489, "lng": -70.6693}, "p50": 2.5},
    "mexico_city":     {"anchor": {"lat": 19.4326, "lng": -99.1332}, "p50": 13.0},
    "port_au_prince":  {"anchor": {"lat": 18.5944, "lng": -72.3074}, "p50": 9.7},
    # Promoted candidates (fixture values = the verified 2026-06-10 resolutions).
    "manaus":          {"anchor": {"lat": -3.10194, "lng": -60.025},  "p50": 177010.0},
    "bogota":          {"anchor": {"lat": 4.60971, "lng": -74.08175}, "p50": 55.6},
    "managua":         {"anchor": {"lat": 12.13282, "lng": -86.2504}, "p50": 26.2},
    # Global expansion fixtures (fixed coords, fixture medians).
    "jakarta":        {"anchor": {"lat": -6.2146, "lng": 106.8451}, "p50": 250.0},
    "manila":         {"anchor": {"lat": 14.5995, "lng": 120.9842}, "p50": 80.0},
    "dhaka":          {"anchor": {"lat": 23.8103, "lng": 90.4125}, "p50": 35000.0},
    "kathmandu":      {"anchor": {"lat": 27.7172, "lng": 85.324}, "p50": 120.0},
    "istanbul":       {"anchor": {"lat": 41.0082, "lng": 28.9784}, "p50": 5.0},
    "tokyo":          {"anchor": {"lat": 35.6762, "lng": 139.6503}, "p50": 60.0},
    "taipei":         {"anchor": {"lat": 25.033, "lng": 121.5654}, "p50": 90.0},
    "wellington":     {"anchor": {"lat": -41.2866, "lng": 174.7756}, "p50": 15.0},
    "tehran":         {"anchor": {"lat": 35.6892, "lng": 51.389}, "p50": 8.0},
    "karachi":        {"anchor": {"lat": 24.8607, "lng": 67.0011}, "p50": 600.0},
    "bangkok":        {"anchor": {"lat": 13.7563, "lng": 100.5018}, "p50": 700.0},
    "hanoi":          {"anchor": {"lat": 21.0278, "lng": 105.8342}, "p50": 2500.0},
    "athens":         {"anchor": {"lat": 37.9838, "lng": 23.7275}, "p50": 3.0},
    "naples":         {"anchor": {"lat": 40.8518, "lng": 14.2681}, "p50": 12.0},
    "nairobi":        {"anchor": {"lat": -1.2921, "lng": 36.8219}, "p50": 25.0},
}

def testing_resolution():
    registry = {}
    for pid, fx in TESTING_RESOLUTION.items():
        registry[pid] = {
            "anchor": dict(fx["anchor"]),
            "hydro_point": {
                "lat": fx["anchor"]["lat"],
                "lng": round(fx["anchor"]["lng"] - 0.05, 5),
                "cell_p50_m3s": fx["p50"],
                "cell_scale": cell_scale_for(fx["p50"]),
            },
            "geocode": {"country": None, "admin1": None, "population": None},
            "resolved_at": 0,
        }
    return {"registry": registry, "candidates": {}}

def read_resolution_doc():
    if db is None:
        return None
    try:
        snap = db.collection("places_resolution").document("latest").get()
        return snap.to_dict() if snap.exists else None
    except Exception as e:
        print(f"Resolution Firestore read failed: {e}", flush=True)
        return None

def write_resolution_doc(doc):
    if db is None:
        return
    try:
        db.collection("places_resolution").document("latest").set(doc)
    except Exception as e:
        print(f"Resolution Firestore write failed: {e}", flush=True)

def registry_resolution_entries():
    return [{"key": p["id"], "name": p["name"], "cc": b.get("cc")}
            for b in BASINS for p in b["places"]]

def get_resolution():
    """The resolution doc: {registry: {place_id: ...}, candidates: {name: ...}}.
    Never blocks: serves L1/Firestore and fills gaps in the background.
    Geography is stable, so entries have no TTL (force via the endpoint)."""
    if TESTING:
        return testing_resolution()
    doc = RESOLUTION_CACHE["doc"]
    if doc is None:
        remote = read_resolution_doc()
        doc = remote or {"registry": {}, "candidates": {}}
        RESOLUTION_CACHE["doc"] = doc
        RESOLUTION_CACHE["fetched_at"] = time.time()
    missing = [e for e in registry_resolution_entries()
               if e["key"] not in (doc.get("registry") or {})]
    if missing:
        threading.Thread(target=refresh_resolution_in_background,
                         args=(False,), daemon=True).start()
    return doc

def refresh_resolution_in_background(force=False):
    """Resolve missing (or all, when forced) registry places. Lock-guarded;
    re-reads Firestore inside the lock so concurrent instances cooperate."""
    if not RESOLUTION_LOCK.acquire(blocking=False):
        return
    try:
        doc = read_resolution_doc() or {"registry": {}, "candidates": {}}
        doc.setdefault("registry", {})
        doc.setdefault("candidates", {})
        entries = registry_resolution_entries()
        if not force:
            entries = [e for e in entries if e["key"] not in doc["registry"]]
        if not entries:
            RESOLUTION_CACHE["doc"] = doc
            return
        resolved = resolve_entries(entries)
        doc["registry"].update(resolved)
        write_resolution_doc(doc)
        RESOLUTION_CACHE["doc"] = doc
        print(f"Resolution refreshed: {len(resolved)}/{len(entries)} places.", flush=True)
    except Exception as e:
        print(f"Resolution refresh failed: {e}", flush=True)
    finally:
        RESOLUTION_LOCK.release()

def resolved_places(basin_config):
    """Registry places merged with their resolution. Unresolved places carry
    resolved=False and no coordinates (the UI renders them without markers)."""
    registry = (get_resolution().get("registry") or {})
    out = []
    for p in basin_config["places"]:
        entry = registry.get(p["id"])
        row = {"id": p["id"], "name": p["name"], "resolved": entry is not None}
        if entry:
            row["anchor"] = entry["anchor"]
            row["hydro_point"] = entry.get("hydro_point")
            # Legacy lat/lng = anchor so existing consumers keep working.
            row["lat"] = entry["anchor"]["lat"]
            row["lng"] = entry["anchor"]["lng"]
        out.append(row)
    return out

def group_seismic_bbox(basin_config):
    """Attribution bbox derived from resolved anchors (+/- pad). None until
    at least one place in the group is resolved."""
    anchors = [p["anchor"] for p in resolved_places(basin_config) if p.get("anchor")]
    if not anchors:
        return None
    return {
        "lat_min": min(a["lat"] for a in anchors) - SEISMIC_BBOX_PAD_DEG,
        "lat_max": max(a["lat"] for a in anchors) + SEISMIC_BBOX_PAD_DEG,
        "lng_min": min(a["lng"] for a in anchors) - SEISMIC_BBOX_PAD_DEG,
        "lng_max": max(a["lng"] for a in anchors) + SEISMIC_BBOX_PAD_DEG,
    }

def municipality_coordinates():
    """{name: {lat, lng, basin}} from resolved anchors (recorder, attribution,
    demo epicenters). Unresolved places are simply absent."""
    out = {}
    for b in BASINS:
        for p in resolved_places(b):
            if p.get("anchor"):
                out[p["name"]] = {"lat": p["anchor"]["lat"],
                                  "lng": p["anchor"]["lng"],
                                  "basin": b["name"]}
    return out

# Event attribution + demo epicenters use the RESOLVED anchors (derived, not
# hardcoded). Only registry names ever flow through these call sites.
def live_seismic_coordinates():
    return {name: (c["lat"], c["lng"])
            for name, c in municipality_coordinates().items()}

