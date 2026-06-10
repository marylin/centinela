"""Registry routes: resolved groups/places + the resolve escape hatch."""
import threading

from fastapi import APIRouter, HTTPException

from api.core import TESTING
from api.config import BASINS, basin_municipalities
from api.places_resolver import resolve_place
from api.resolution import (
    RESOLUTION_CACHE, RESOLUTION_LOCK, testing_resolution, read_resolution_doc,
    write_resolution_doc, registry_resolution_entries,
    refresh_resolution_in_background, resolved_places, group_seismic_bbox,
)

router = APIRouter()

@router.get("/basins")
def get_basins():
    """The configured groups with RESOLVED places (anchor + hydro point per
    place, derived, never hardcoded). Unresolved places carry resolved=false
    and no coordinates until the background resolution lands."""
    return [
        {
            "id": b["id"],
            "name": b["name"],
            "country": b["country"],
            "kind": b.get("kind", "flood-watch"),
            "places": resolved_places(b),
            "municipalities": basin_municipalities(b),
            "seismic_bbox": group_seismic_bbox(b)
        }
        for b in BASINS
    ]

@router.get("/places")
def get_places():
    """The monitored-places registry: groups with coordinates and kind.
    Same payload as /basins (kept as an alias for the frontend migration)."""
    return get_basins()

@router.post("/places/resolve")
def resolve_places_endpoint(place: str = None, force: bool = False):
    """Operator escape hatch. With `place`: synchronously re-resolve that one
    place id and write through. Without: kick a background re-resolution of
    missing places (or everything with force=true)."""
    if TESTING:
        doc = testing_resolution()
        if place:
            entry = doc["registry"].get(place)
            if entry is None:
                raise HTTPException(status_code=404, detail=f"Unknown place: {place}")
            return {"status": "ok", "place": place, "resolution": entry}
        return {"status": "started"}

    if place:
        target = next((e for e in registry_resolution_entries() if e["key"] == place), None)
        if target is None:
            raise HTTPException(status_code=404, detail=f"Unknown place: {place}")
        resolution = resolve_place(target["name"], target.get("cc"))
        if resolution is None:
            raise HTTPException(status_code=502, detail=f"Could not resolve {target['name']}")
        with RESOLUTION_LOCK:
            doc = read_resolution_doc() or {"registry": {}, "candidates": {}}
            doc.setdefault("registry", {})[place] = resolution
            write_resolution_doc(doc)
            RESOLUTION_CACHE["doc"] = doc
        return {"status": "ok", "place": place, "resolution": resolution}

    threading.Thread(target=refresh_resolution_in_background,
                     args=(force,), daemon=True).start()
    return {"status": "started"}

