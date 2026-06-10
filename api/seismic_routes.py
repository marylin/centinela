"""Seismic feeds: USGS live feed, warehouse-backed events + focus routes."""
import json
import math
import os
import time
from datetime import datetime, timezone, timedelta

import requests
from fastapi import APIRouter, HTTPException
from google.cloud import bigquery

from api.core import TESTING
from api.config import BASINS, RAW_EVENTS_TABLE, RAW_EVENT_FIELDS, basin_municipalities
from api.resolution import live_seismic_coordinates, group_seismic_bbox
from api.stores import get_all_demo_events
from rapid_agent.centinela_agent import run_event_narration_turn

router = APIRouter()

USGS_LIVE_FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
USGS_LIVE_CACHE = {"data": None, "fetched_at": 0.0}
USGS_LIVE_CACHE_TTL_SECONDS = 60.0

def fetch_usgs_live_feed():
    now = time.time()
    cached = USGS_LIVE_CACHE["data"]
    if cached is not None and (now - USGS_LIVE_CACHE["fetched_at"]) < USGS_LIVE_CACHE_TTL_SECONDS:
        return cached
    try:
        resp = requests.get(USGS_LIVE_FEED_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        USGS_LIVE_CACHE["data"] = data
        USGS_LIVE_CACHE["fetched_at"] = now
        return data
    except Exception as e:
        print(f"Error fetching USGS live feed: {e}", flush=True)
        if cached is not None:
            return cached
        raise HTTPException(status_code=502, detail="USGS live feed unavailable")

@router.get("/live-seismic")
def get_live_seismic(basin: str = "rio_cauca"):
    """Returns real USGS events from the live feed attributed to the basin's
    municipalities (nearest within 150 km), newest first. Stateless and always
    real data: simulated demo events never appear here."""
    basin_config = next((b for b in BASINS if b["id"] == basin), None)
    if basin_config is None:
        raise HTTPException(status_code=404, detail=f"Unknown basin: {basin}")
    live_coords = live_seismic_coordinates()
    munis = {
        m: live_coords[m]
        for m in basin_municipalities(basin_config)
        if m in live_coords
    }
    feed = fetch_usgs_live_feed()
    events = []
    for feature in feed.get("features", []):
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 3:
            continue
        lon, lat, depth = coords[:3]
        closest_muni = None
        min_dist = float("inf")
        for name, (mlat, mlon) in munis.items():
            dist = math.sqrt((lat - mlat) ** 2 + (lon - mlon) ** 2) * 111.0
            if dist < min_dist:
                min_dist = dist
                closest_muni = name
        if not closest_muni or min_dist >= 150.0:
            continue
        prop = feature.get("properties") or {}
        t_ms = prop.get("time") or 0
        dt = datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc)
        events.append({
            "municipality": closest_muni,
            "magnitude": float(prop.get("mag") or 0.0),
            "place": prop.get("place", "Unknown"),
            "time": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "depth_km": float(depth),
            "latitude": float(lat),
            "longitude": float(lon),
            "simulated": False
        })
    events.sort(key=lambda e: e["time"], reverse=True)
    return events


def parse_region(place: str) -> str:
    """Region = text after the last comma of the USGS place string, or the
    whole string when there is no comma (matches sql/seismic_active_regions.sql)."""
    if not place:
        return "Unknown"
    return place.split(",")[-1].strip() or "Unknown"


def compute_event_risk(magnitude: float, depth_km: float) -> float:
    """0-1 risk derived from magnitude and depth: magnitude scaled against M8,
    discounted for deeper (less surface-damaging) hypocenters."""
    mag_component = min(1.0, max(0.0, float(magnitude or 0.0) / 8.0))
    depth = float(depth_km or 0.0)
    if depth < 70.0:
        depth_factor = 1.0
    elif depth < 300.0:
        depth_factor = 0.85
    else:
        depth_factor = 0.7
    return round(mag_component * depth_factor, 2)


def severity_for_risk(risk_score: float) -> str:
    if risk_score >= 0.8:
        return "Critical"
    if risk_score >= 0.6:
        return "Danger"
    if risk_score >= 0.4:
        return "Warning"
    return "Low"


def template_event_narration(event: dict, risk_score: float, severity: str) -> str:
    prefix = "SIMULATED drill event (not a real USGS detection): " if event.get("simulated") else ""
    return (
        f"{prefix}M{float(event.get('magnitude') or 0.0):.1f} earthquake {event.get('place', 'Unknown')} "
        f"at {event.get('time', 'unknown time')}, depth {float(event.get('depth_km') or 0.0):.1f} km. "
        f"Derived risk score {risk_score:.2f} grades this event as {severity}."
    )


def seismic_seed_events():
    """Deterministic local stand-in for the BigQuery raw-events table, with
    timestamps relative to now so the 48h/30d windows always have data."""
    now = datetime.now(timezone.utc)

    def seed(event_id, hours_ago, magnitude, place, lat, lon, depth_km):
        return {
            "id": event_id,
            "magnitude": magnitude,
            "place": place,
            "time": (now - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latitude": lat,
            "longitude": lon,
            "depth_km": depth_km
        }

    return [
        seed("usseed0001", 2, 6.8, "78 km W of San Antonio de los Cobres, Argentina", -24.18, -66.99, 180.0),
        seed("usseed0002", 5, 5.4, "112 km SSE of Lima, Peru", -12.95, -76.62, 42.0),
        seed("usseed0003", 9, 4.7, "23 km NE of Coquimbo, Chile", -29.79, -71.13, 51.0),
        seed("usseed0004", 16, 5.9, "Kermadec Islands, New Zealand", -29.65, -177.84, 35.0),
        seed("usseed0005", 27, 4.6, "41 km SW of Puerto Madero, Mexico", 14.46, -92.69, 28.0),
        seed("usseed0006", 39, 5.1, "South Sandwich Islands region", -56.32, -27.41, 95.0),
        seed("usseed0007", 45, 4.9, "147 km E of Hachinohe, Japan", 40.49, 143.20, 19.0),
        # Older than 48h: only counts toward the 30-day active-regions window.
        seed("usseed0008", 90, 6.1, "62 km SSW of Lima, Peru", -12.51, -77.30, 38.0),
        seed("usseed0009", 200, 5.6, "Off the coast of Aisen, Chile", -45.40, -76.10, 12.0),
        seed("usseed0010", 320, 4.8, "9 km NNW of Mexico City, Mexico", 19.51, -99.18, 60.0),
        seed("usseed0011", 480, 5.2, "Tonga region", -19.92, -174.36, 110.0),
        seed("usseed0012", 650, 4.5, "33 km WSW of Port-au-Prince, Haiti", 18.48, -72.62, 14.0)
    ]


def recent_events_from_rows(rows):
    """Apply the recent-events contract to dict rows: M4.5+, last 48h,
    newest first, max 20 (mirrors sql/seismic_recent_events.sql)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ")
    recent = [r for r in rows if float(r.get("magnitude") or 0.0) >= 4.5 and r.get("time", "") >= cutoff]
    recent.sort(key=lambda r: r["time"], reverse=True)
    return recent[:20]


def active_regions_from_rows(rows):
    """Group last-30-day rows by parsed region, ranked by event count
    (mirrors sql/seismic_active_regions.sql)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    regions = {}
    for r in rows:
        if r.get("time", "") < cutoff:
            continue
        region = parse_region(r.get("place", ""))
        entry = regions.setdefault(region, {"region": region, "count": 0, "max_magnitude": 0.0})
        entry["count"] += 1
        entry["max_magnitude"] = max(entry["max_magnitude"], float(r.get("magnitude") or 0.0))
    ranked = sorted(regions.values(), key=lambda e: (-e["count"], -e["max_magnitude"]))
    return ranked[:15]


def load_sql(filename: str) -> str:
    with open(f"sql/{filename}", "r", encoding="utf-8") as f:
        return f.read()


def load_raw_events_sql(filename: str) -> str:
    return load_sql(filename).replace("usgs_raw_events.events", RAW_EVENTS_TABLE)


def format_raw_event_row(row_dict: dict) -> dict:
    t = row_dict.get("time")
    if isinstance(t, datetime):
        t = t.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "id": row_dict.get("id"),
        # BigQuery stores float32; round to USGS's 0.1 precision so prose and
        # UI never show artifacts like 5.199999809265137.
        "magnitude": round(float(row_dict.get("magnitude") or 0.0), 1),
        "place": row_dict.get("place") or "Unknown",
        "time": t,
        "latitude": float(row_dict.get("latitude") or 0.0),
        "longitude": float(row_dict.get("longitude") or 0.0),
        "depth_km": float(row_dict.get("depth_km") or 0.0)
    }


def get_simulated_feed_events():
    """Active simulated demo events shaped as feed events, newest first.
    Older injected events (pre feed-fields) without an id are skipped."""
    events = []
    for demo in get_all_demo_events():
        if not isinstance(demo, dict) or not demo.get("id"):
            continue
        event = format_raw_event_row(demo)
        event["simulated"] = True
        events.append(event)
    events.sort(key=lambda e: e.get("time") or "", reverse=True)
    return events


@router.get("/seismic-events")
def get_seismic_events():
    """Live event feed read from the BigQuery raw-events table (synced by the
    usgs_raw_events Fivetran connector), plus active regions over 30 days.
    Simulated injected events appear at the top, tagged simulated."""
    simulated = get_simulated_feed_events()

    if TESTING:
        rows = seismic_seed_events()
        real_events = recent_events_from_rows(rows)
        active_regions = active_regions_from_rows(rows)
    else:
        real_events = []
        active_regions = []
        try:
            client = bigquery.Client(project='centinela-498622')
            recent_rows = client.query(load_raw_events_sql("seismic_recent_events.sql")).result()
            real_events = [format_raw_event_row(dict(row)) for row in recent_rows]
            region_rows = client.query(load_raw_events_sql("seismic_active_regions.sql")).result()
            active_regions = [
                {
                    "region": row_dict.get("region") or "Unknown",
                    "count": int(row_dict.get("count") or 0),
                    "max_magnitude": round(float(row_dict.get("max_magnitude") or 0.0), 1)
                }
                for row_dict in (dict(row) for row in region_rows)
            ]
        except Exception as e:
            # The raw table only exists once the connector is deployed and has
            # synced; degrade to an empty (but well-formed) feed until then.
            print(f"Error querying raw seismic events from BigQuery: {e}", flush=True)

    for event in real_events:
        event["simulated"] = False
    return {"events": simulated + real_events, "active_regions": active_regions}


def find_raw_event_by_id(event_id: str):
    """Looks up one event: simulated demo events first, then the seeded table
    (TESTING) or the BigQuery raw-events table."""
    for event in get_simulated_feed_events():
        if event.get("id") == event_id:
            return event

    if TESTING:
        for row in seismic_seed_events():
            if row["id"] == event_id:
                event = dict(row)
                event["simulated"] = False
                return event
        return None

    try:
        client = bigquery.Client(project='centinela-498622')
        query = (
            f"SELECT {', '.join(RAW_EVENT_FIELDS)} FROM {RAW_EVENTS_TABLE} "
            "WHERE id = @event_id LIMIT 1"
        )
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("event_id", "STRING", event_id)]
        )
        for row in client.query(query, job_config=job_config).result():
            event = format_raw_event_row(dict(row))
            event["simulated"] = False
            return event
    except Exception as e:
        print(f"Error querying raw seismic event {event_id} from BigQuery: {e}", flush=True)
    return None


@router.get("/seismic-focus")
def get_seismic_focus(id: str):
    """Click-to-focus analysis of one event from the raw feed: derived risk
    score, severity grade, and a narration (real Gemini in production, a
    template string in TESTING)."""
    event = find_raw_event_by_id(id)
    if event is None:
        raise HTTPException(status_code=404, detail=f"Unknown seismic event id: {id}")

    risk_score = compute_event_risk(event.get("magnitude"), event.get("depth_km"))
    severity = severity_for_risk(risk_score)

    narration = ""
    if not TESTING:
        narration = run_event_narration_turn({
            **event,
            "risk_score": risk_score,
            "severity": severity
        })
    if not narration:
        narration = template_event_narration(event, risk_score, severity)

    return {
        "event": event,
        "risk_score": risk_score,
        "severity": severity,
        "narration": narration
    }
