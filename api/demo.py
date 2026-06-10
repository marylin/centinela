"""Read-time merge of simulated demo events into index rows (never the cache)."""
from api.hazard import blend_index
from api.stores import get_demo_event

def merge_demo_event_into_risk(basin: str, results):
    """Read-time merge of an active simulated demo event into the index rows.
    The injected quake replaces the seismic component (magnitude/7 so a strong
    demo event lands visibly above the live-feed scaling) and the index is
    re-blended with the standard component weights. The merged row is tagged
    simulated so it is never presented as a real USGS detection."""
    if not isinstance(results, list):
        return results
    event = get_demo_event(basin)
    if not event:
        return results
    muni = event.get("municipality")
    try:
        magnitude = float(event.get("magnitude") or 0.0)
    except (TypeError, ValueError):
        return results
    for row in results:
        if not isinstance(row, dict) or row.get("municipality") != muni:
            continue
        comps = {}
        available = row.get("components_available") or []
        if "flood" in available:
            comps["flood"] = float(row.get("flood_score") or 0.0)
        if "landslide" in available:
            comps["landslide"] = float(row.get("landslide_score") or 0.0)
        if "rain" in available:
            comps["rain"] = float(row.get("rain_score") or 0.0)
        comps["seismic"] = round(min(1.0, max(0.0, (magnitude - 4.0) / 3.5)), 2)
        index, dominant = blend_index(comps)
        row["earthquake_magnitude"] = magnitude
        row["seismic_score"] = comps["seismic"]
        row["risk_score"] = index
        row["dominant_hazard"] = dominant
        row["components_available"] = sorted(comps.keys())
        row["simulated"] = True
    return results

