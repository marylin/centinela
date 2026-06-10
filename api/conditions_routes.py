"""Live conditions for any coordinate (rain, AQI, discharge, soil)."""
import math
import os
import time
from datetime import datetime, timezone, timedelta

import requests
from fastapi import APIRouter, HTTPException

from api.core import TESTING
from api.config import LOCATION_CONDITIONS_PROVENANCE

router = APIRouter()

LOCATION_CONDITIONS_CACHE = {}  # (lat, lng rounded) -> (expiry_epoch_s, payload)
LOCATION_CONDITIONS_TTL_S = 30 * 60

def fetch_location_rainfall_history(lat: float, lng: float, api_key: str):
    url = "https://weather.googleapis.com/v1/history/hours:lookup"
    params = {
        "location.latitude": lat,
        "location.longitude": lng,
        "hours": 24,
        "pageSize": 24,
        "unitsSystem": "METRIC"
    }
    resp = requests.get(url, params=params, headers={"X-Goog-Api-Key": api_key}, timeout=6.0)
    if resp.status_code != 200:
        raise RuntimeError(f"weather history status {resp.status_code}")
    hours = resp.json().get("historyHours", [])
    series = []
    for h in hours:
        qpf = ((h.get("precipitation") or {}).get("qpf") or {})
        t = ((h.get("interval") or {}).get("startTime")) or ""
        series.append({"time": t, "mm": round(float(qpf.get("quantity") or 0.0), 2)})
    series.reverse()  # API returns newest first; serve oldest-first for charts
    return {"total_24h_mm": round(sum(s["mm"] for s in series), 1), "hourly": series}

def fetch_location_discharge(lat: float, lng: float):
    url = "https://flood-api.open-meteo.com/v1/flood"
    params = {"latitude": lat, "longitude": lng, "daily": "river_discharge",
              "past_days": 7, "forecast_days": 1}
    resp = requests.get(url, params=params, timeout=6.0)
    if resp.status_code != 200:
        raise RuntimeError(f"flood api status {resp.status_code}")
    d = resp.json().get("daily") or {}
    series = [{"date": t, "m3s": round(float(v), 1)}
              for t, v in zip(d.get("time") or [], d.get("river_discharge") or [])
              if v is not None]
    if not series:
        return None
    latest, week_ago = series[-1]["m3s"], series[0]["m3s"]
    direction = "rising" if latest > week_ago * 1.05 else ("falling" if latest < week_ago * 0.95 else "steady")
    return {"latest_m3s": latest, "direction": direction, "daily": series}

def fetch_location_soil(lat: float, lng: float):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {"latitude": lat, "longitude": lng, "hourly": "soil_moisture_0_to_7cm",
              "past_days": 2, "forecast_days": 1}
    resp = requests.get(url, params=params, timeout=6.0)
    if resp.status_code != 200:
        raise RuntimeError(f"soil api status {resp.status_code}")
    h = resp.json().get("hourly") or {}
    values = [float(v) for v in (h.get("soil_moisture_0_to_7cm") or []) if v is not None]
    if not values:
        return None
    return {"latest_m3m3": round(values[-1], 3),
            "min_48h": round(min(values), 3), "max_48h": round(max(values), 3)}

def fetch_location_aqi(lat: float, lng: float, api_key: str):
    url = "https://airquality.googleapis.com/v1/currentConditions:lookup"
    resp = requests.post(url, json={"location": {"latitude": lat, "longitude": lng}},
                         headers={"X-Goog-Api-Key": api_key}, timeout=6.0)
    if resp.status_code != 200:
        raise RuntimeError(f"air quality status {resp.status_code}")
    indexes = resp.json().get("indexes") or []
    uaqi = next((i for i in indexes if i.get("code") == "uaqi"), indexes[0] if indexes else None)
    if not uaqi:
        return None
    return {"aqi": int(uaqi.get("aqi") or 0), "category": uaqi.get("category") or ""}


@router.get("/location-conditions")
def get_location_conditions(lat: float, lng: float):
    """Real conditions for any coordinate: observed 24h rainfall plus modeled
    river discharge and soil moisture, each labeled with its provenance."""
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
        raise HTTPException(status_code=400, detail="lat/lng out of range")

    if TESTING:
        hourly = [{"time": "", "mm": round(max(0.0, 1.4 * math.sin(i / 4.0)), 2)} for i in range(24)]
        return {
            "latitude": lat, "longitude": lng,
            "rainfall": {"total_24h_mm": round(sum(x["mm"] for x in hourly), 1), "hourly": hourly},
            "river_discharge": {"latest_m3s": 1234.5, "direction": "rising",
                                 "daily": [{"date": f"2026-06-0{d}", "m3s": 1000.0 + d * 30} for d in range(1, 9)]},
            "soil_moisture": {"latest_m3m3": 0.312, "min_48h": 0.298, "max_48h": 0.33},
            "air_quality": {"aqi": 82, "category": "Good air quality"},
            "provenance": LOCATION_CONDITIONS_PROVENANCE
        }

    cache_key = (round(lat, 2), round(lng, 2))
    now_s = time.time()
    cached = LOCATION_CONDITIONS_CACHE.get(cache_key)
    if cached and cached[0] > now_s:
        return cached[1]

    payload = {"latitude": lat, "longitude": lng, "rainfall": None,
               "river_discharge": None, "soil_moisture": None, "air_quality": None,
               "provenance": LOCATION_CONDITIONS_PROVENANCE}
    api_key = os.environ.get("GOOGLE_WEATHER_API_KEY")
    if api_key:
        try:
            payload["rainfall"] = fetch_location_rainfall_history(lat, lng, api_key)
        except Exception as e:
            print(f"location-conditions rainfall failed: {e}", flush=True)
        try:
            payload["air_quality"] = fetch_location_aqi(lat, lng, api_key)
        except Exception as e:
            print(f"location-conditions air quality failed: {e}", flush=True)
    try:
        payload["river_discharge"] = fetch_location_discharge(lat, lng)
    except Exception as e:
        print(f"location-conditions discharge failed: {e}", flush=True)
    try:
        payload["soil_moisture"] = fetch_location_soil(lat, lng)
    except Exception as e:
        print(f"location-conditions soil failed: {e}", flush=True)

    LOCATION_CONDITIONS_CACHE[cache_key] = (now_s + LOCATION_CONDITIONS_TTL_S, payload)
    return payload

