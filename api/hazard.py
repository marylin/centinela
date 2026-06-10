"""Centinela model hazard index + the live weather recorder.

index = weighted blend over real feeds (GloFAS discharge vs the place's own
92-day baseline, soil wetness, observed 24h rain, USGS-in-bbox seismic);
weights renormalize over the components that have data. Severity bands
40/60/80. OUR model, surfaced as MODEL, never an official authority warning.
"""
import os
import time
import concurrent.futures
from datetime import datetime, timezone, timedelta

import requests
from google.cloud import bigquery

import api.core as core
from api.core import TESTING, MOCK_DB_STATE
from api.config import BASINS, RAW_EVENTS_TABLE
from api.stores import get_incidents_list
from api.resolution import municipality_coordinates, group_seismic_bbox

WEATHER_CACHE = {}
WEATHER_CACHE_EXPIRY = None

def fetch_precipitation_for_muni(muni: str, lat: float, lng: float, api_key: str):
    url = "https://weather.googleapis.com/v1/currentConditions:lookup"
    params = {
        "location.latitude": lat,
        "location.longitude": lng,
        "unitsSystem": "METRIC"
    }
    headers = {
        "X-Goog-Api-Key": api_key
    }
    attempts = 3
    backoff = 1.0
    for attempt in range(attempts):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=2.0)
            if resp.status_code == 200:
                data = resp.json()
                precip = data.get("precipitation", {}).get("amount", {}).get("millimeters", 0.0)
                return float(precip)
            else:
                print(f"Weather API error for {muni}: {resp.status_code} (attempt {attempt + 1}/{attempts})", flush=True)
        except Exception as e:
            err_msg = str(e)
            if api_key in err_msg:
                err_msg = err_msg.replace(api_key, "REDACTED_KEY")
            print(f"Error fetching weather for {muni}: {err_msg} (attempt {attempt + 1}/{attempts})", flush=True)
        
        if attempt < attempts - 1:
            time.sleep(backoff)
            backoff *= 2.0
            
    return None

# In-memory fallbacks/stores

# ---------------------------------------------------------------------------
# CENTINELA MODEL HAZARD INDEX (real-data unification)
# ---------------------------------------------------------------------------
# index = weighted blend over real feeds; weights renormalize over the
# components that have data. Severity bands stay 40/60/80. OUR model index,
# surfaced as such, never presented as an official authority warning.

INDEX_CACHE = {}          # basin id -> (expiry_epoch_s, rows)
INDEX_CACHE_TTL_S = 60    # /risk is polled every 5s per client; BQ once a minute

DOMINANT_BY_COMPONENT = {"flood": "FLOOD", "rain": "FLOOD", "soil": "LANDSLIDE", "landslide": "LANDSLIDE", "seismic": "SEISMIC"}

def refresh_weather_records():
    """Fetch live observed rainfall for every registry place (5-min cache) and
    record it into BigQuery so per-place rainfall history accumulates (D1)."""
    try:
        api_key = os.environ.get("GOOGLE_WEATHER_API_KEY")
        if not api_key:
            print("Warning: GOOGLE_WEATHER_API_KEY environment variable is not set.", flush=True)
            return
        now_utc = datetime.now(timezone.utc)
        global WEATHER_CACHE_EXPIRY, WEATHER_CACHE
        if WEATHER_CACHE_EXPIRY and now_utc < WEATHER_CACHE_EXPIRY:
            return
        print("Weather cache expired or empty. Fetching new data from Google Weather API...", flush=True)
        muni_coords = municipality_coordinates()
        if not muni_coords:
            print("Weather refresh skipped: no resolved places yet.", flush=True)
            return
        new_precip = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
            futures = {
                executor.submit(fetch_precipitation_for_muni, muni, coord["lat"], coord["lng"], api_key): muni
                for muni, coord in muni_coords.items()
            }
            for future in concurrent.futures.as_completed(futures):
                muni = futures[future]
                try:
                    val = future.result()
                    if val is not None:
                        new_precip[muni] = val
                except Exception as e:
                    print(f"Error in future result for {muni}: {e}", flush=True)

        if not new_precip:
            return
        WEATHER_CACHE.update(new_precip)
        WEATHER_CACHE_EXPIRY = now_utc + timedelta(minutes=5)
        try:
            bq_client = bigquery.Client(project='centinela-498622')
            timestamp_str = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
            rows_to_insert = []
            for muni, precip_val in new_precip.items():
                coord = muni_coords[muni]
                safe_muni = muni.replace("'", "\\'")
                rows_to_insert.append(
                    f"('{timestamp_str}', 'GMP-01', {precip_val}, '{coord['basin']}', '{safe_muni}')")
            if rows_to_insert:
                insert_query = f"""
                INSERT INTO unified_feeds.rainfall (timestamp, station_id, precipitation_mm, basin, municipality)
                VALUES {', '.join(rows_to_insert)}
                """
                bq_client.query(insert_query).result()
                print(f"Recorded {len(rows_to_insert)} live weather rows to BigQuery.", flush=True)
        except Exception as bq_err:
            print(f"Error writing Weather API data to BigQuery: {bq_err}", flush=True)
    except Exception as weather_err:
        print(f"Error in Weather API integration flow: {weather_err}", flush=True)


def component_scores(discharge_stat, soil_latest, rain_mm_24h, quake_mag):
    """0-1 component scores from raw real values; absent data -> absent
    component (never a fabricated zero that would dilute the index).

    Calibration (documented, OUR model):
      flood:     discharge vs the place's own 92d baseline; sitting at P90 = 0.6
      rain:      50 mm observed in 24h saturates the component
      seismic:   (magnitude - 4.0) / 3.5 -> M4 ambient 0, M7.5+ saturates
      landslide: derived = soil wetness x the strongest water driver
                 (wet ground is an amplifier, not an alarm by itself)
    """
    comps = {}
    soil_s = None
    if discharge_stat and discharge_stat.get("latest") is not None             and discharge_stat.get("p50") is not None and discharge_stat.get("p90") is not None:
        p50 = float(discharge_stat["p50"])
        p90 = float(discharge_stat["p90"])
        spread = max(p90 - p50, max(abs(p50) * 0.10, 0.001))
        ratio = (float(discharge_stat["latest"]) - p50) / spread
        comps["flood"] = max(0.0, min(1.0, 0.6 * ratio))
    if rain_mm_24h is not None:
        comps["rain"] = max(0.0, min(1.0, float(rain_mm_24h) / 50.0))
    if quake_mag is not None:
        comps["seismic"] = max(0.0, min(1.0, (float(quake_mag) - 4.0) / 3.5))
    else:
        # The events feed always answers; a quiet 48h is a real zero.
        comps["seismic"] = 0.0
    if soil_latest is not None:
        soil_s = max(0.0, min(1.0, (float(soil_latest) - 0.20) / 0.30))
        water_driver = max(comps.get("flood", 0.0), comps.get("rain", 0.0))
        comps["landslide"] = round(soil_s * water_driver, 3)
    return comps


def blend_index(comps):
    """Index = the strongest single hazard, bumped by co-occurrence of the
    others (a catastrophic single signal must alert on its own; several
    moderate signals together raise, but never dominate)."""
    if not comps:
        return 0.0, "FLOOD"
    dominant_key = max(comps, key=lambda k: comps[k])
    m = comps[dominant_key]
    others = [v for k, v in comps.items() if k != dominant_key]
    bump = (sum(others) / len(others)) * 0.5 if others else 0.0
    index = m + (1.0 - m) * bump
    return round(max(0.0, min(1.0, index)), 2), DOMINANT_BY_COMPONENT[dominant_key]


def index_row(place, comps, raw):
    """One /risk row. Legacy keys (municipality, risk_score, flood_score,
    landslide_score, seismic_score, dominant_hazard) are kept so downstream
    consumers migrate gradually; seeded-era fields are gone."""
    index, dominant = blend_index(comps)
    return {
        "municipality": place["name"],
        "place_id": place["id"],
        "risk_score": index,
        "flood_score": round(comps.get("flood", 0.0), 2),
        "landslide_score": round(comps.get("landslide", 0.0), 2),
        "rain_score": round(comps.get("rain", 0.0), 2),
        "seismic_score": round(comps.get("seismic", 0.0), 2),
        "rainfall_mm": round(float(raw.get("rain_mm") or 0.0), 1),
        "discharge_m3s": raw.get("discharge_latest"),
        "discharge_p50": raw.get("discharge_p50"),
        "discharge_p90": raw.get("discharge_p90"),
        "soil_moisture": raw.get("soil_latest"),
        "earthquake_magnitude": raw.get("quake_mag"),
        "dominant_hazard": dominant,
        "components_available": sorted(comps.keys()),
        "provenance": "centinela-model-index"
    }


def compute_hazard_index(basin_config):
    """Real-feed index rows for every place in the group (one BQ round per
    signal, all places at once)."""
    refresh_weather_records()

    places = basin_config["places"]
    bbox = group_seismic_bbox(basin_config) or {}
    ids_sql = ", ".join(f"'{p['id']}'" for p in places)
    names_sql = ", ".join("'" + p["name"].replace("'", "\\'") + "'" for p in places)

    discharge_stats, soil_latest, rain_24h = {}, {}, {}
    quake_mag = None
    client = bigquery.Client(project='centinela-498622')

    try:
        q = f"""
        SELECT place_id,
               ARRAY_AGG(discharge_m_3_s ORDER BY date DESC LIMIT 1)[OFFSET(0)] AS latest,
               APPROX_QUANTILES(discharge_m_3_s, 100)[OFFSET(50)] AS p50,
               APPROX_QUANTILES(discharge_m_3_s, 100)[OFFSET(90)] AS p90
        FROM global_hydro.river_discharge
        WHERE place_id IN ({ids_sql})
          AND date >= DATE_SUB(CURRENT_DATE(), INTERVAL 92 DAY)
        GROUP BY place_id"""
        for row in client.query(q).result():
            d = dict(row)
            discharge_stats[d["place_id"]] = d
    except Exception as e:
        print(f"Index discharge query failed: {e}", flush=True)

    try:
        q = f"""
        SELECT place_id,
               ARRAY_AGG(moisture_m_3_m_3 ORDER BY ts DESC LIMIT 1)[OFFSET(0)] AS latest
        FROM global_hydro.soil_moisture
        WHERE place_id IN ({ids_sql})
        GROUP BY place_id"""
        for row in client.query(q).result():
            d = dict(row)
            soil_latest[d["place_id"]] = d.get("latest")
    except Exception as e:
        print(f"Index soil query failed: {e}", flush=True)

    try:
        q = f"""
        SELECT municipality, SUM(precipitation_mm) AS total
        FROM unified_feeds.rainfall
        WHERE municipality IN ({names_sql})
          AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 24 HOUR)
        GROUP BY municipality"""
        for row in client.query(q).result():
            d = dict(row)
            rain_24h[d["municipality"]] = float(d.get("total") or 0.0)
    except Exception as e:
        print(f"Index rainfall query failed: {e}", flush=True)

    if all(k in bbox for k in ("lat_min", "lat_max", "lng_min", "lng_max")):
        try:
            q = f"""
            SELECT MAX(magnitude) AS max_mag
            FROM {RAW_EVENTS_TABLE}
            WHERE time >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 48 HOUR)
              AND latitude BETWEEN {bbox['lat_min']} AND {bbox['lat_max']}
              AND longitude BETWEEN {bbox['lng_min']} AND {bbox['lng_max']}"""
            for row in client.query(q).result():
                m = dict(row).get("max_mag")
                quake_mag = round(float(m), 1) if m is not None else None
        except Exception as e:
            print(f"Index seismic query failed: {e}", flush=True)

    rows = []
    for place in places:
        dstat = discharge_stats.get(place["id"])
        raw = {
            "discharge_latest": round(float(dstat["latest"]), 1) if dstat and dstat.get("latest") is not None else None,
            "discharge_p50": round(float(dstat["p50"]), 1) if dstat and dstat.get("p50") is not None else None,
            "discharge_p90": round(float(dstat["p90"]), 1) if dstat and dstat.get("p90") is not None else None,
            "soil_latest": round(float(soil_latest[place["id"]]), 3) if soil_latest.get(place["id"]) is not None else None,
            "rain_mm": rain_24h.get(place["name"]),
            "quake_mag": quake_mag
        }
        comps = component_scores(dstat, raw["soil_latest"], raw["rain_mm"], raw["quake_mag"])
        rows.append(index_row(place, comps, raw))
    return rows


def testing_index_rows(basin_config):
    """Deterministic TESTING fixtures shaped exactly like production index
    rows; varied per place so severity bands and demo flows are exercised."""
    populated = MOCK_DB_STATE.get("populated", True)
    rows = []
    for i, place in enumerate(basin_config["places"]):
        if basin_config["kind"] == "flood-watch":
            dstat = {"latest": 1300.0 + i * 120, "p50": 1000.0, "p90": 1400.0}
            soil = [0.42, 0.36, 0.47][i % 3]
            rain = [4.5, 2.0, 9.5][i % 3]
            quake = [None, None, 3.8][i % 3]
        else:
            dstat = {"latest": 60.0, "p50": 55.0, "p90": 90.0}
            soil = 0.18
            rain = 0.0
            quake = 4.9
        if not populated:
            dstat = {"latest": dstat["p50"], "p50": dstat["p50"], "p90": dstat["p90"]}
            soil, rain, quake = 0.21, 0.0, None
        raw = {
            "discharge_latest": dstat["latest"], "discharge_p50": dstat["p50"],
            "discharge_p90": dstat["p90"], "soil_latest": soil,
            "rain_mm": rain, "quake_mag": quake
        }
        comps = component_scores(dstat, soil, rain, quake)
        rows.append(index_row(place, comps, raw))
    return rows


def compute_base_risk(basin: str = "rio_cauca"):
    """Hazard-index rows per place in the scoped group (name kept from the
    composite era so call sites stay stable)."""
    if core.REOPENED_INCIDENT_ID:
        incidents = get_incidents_list()
        matching = next((inc for inc in incidents if inc["id"] == core.REOPENED_INCIDENT_ID), None)
        if matching and "risk_data" in matching:
            return matching["risk_data"]

    basin_config = next((b for b in BASINS if b["id"] == basin), BASINS[0])

    if TESTING:
        return testing_index_rows(basin_config)

    now_s = time.time()
    cached = INDEX_CACHE.get(basin)
    if cached and cached[0] > now_s:
        return cached[1]
    rows = compute_hazard_index(basin_config)
    INDEX_CACHE[basin] = (now_s + INDEX_CACHE_TTL_S, rows)
    return rows


