"""Fivetran Connector SDK: global hydrology (Open-Meteo).

Ingests, for every monitored place, two genuinely real model series:
  - daily river discharge (GloFAS v4 via the Open-Meteo flood API), and
  - hourly topsoil moisture (ECMWF via the Open-Meteo forecast API).
Both are MODEL data (not gauge measurements) and must always be labeled as
such downstream. No API key required; data is CC BY 4.0.

This is the interim river/soil source while the Google Flood Forecasting API
application is on the waitlist; the schema is source-agnostic so that swap is
a connector-only change.
"""

import json
import urllib.parse
import urllib.request

from fivetran_connector_sdk import Connector
from fivetran_connector_sdk import Logging as log
from fivetran_connector_sdk import Operations as op

FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
SOIL_URL = "https://api.open-meteo.com/v1/forecast"

# Monitored places: compound-basin municipalities + seismic-city anchors.
PLACES = [
    {"place_id": "cali",            "name": "Cali",            "basin_id": "rio_cauca",      "lat": 3.4516,   "lng": -76.5320},
    {"place_id": "yumbo",           "name": "Yumbo",           "basin_id": "rio_cauca",      "lat": 3.5855,   "lng": -76.4952},
    {"place_id": "jamundi",         "name": "Jamundí",         "basin_id": "rio_cauca",      "lat": 3.2610,   "lng": -76.5394},
    {"place_id": "neiva",           "name": "Neiva",           "basin_id": "rio_magdalena",  "lat": 2.9273,   "lng": -75.2819},
    {"place_id": "girardot",        "name": "Girardot",        "basin_id": "rio_magdalena",  "lat": 4.3009,   "lng": -74.8061},
    {"place_id": "honda",           "name": "Honda",           "basin_id": "rio_magdalena",  "lat": 5.2045,   "lng": -74.7411},
    {"place_id": "lima",            "name": "Lima",            "basin_id": "lima_peru",      "lat": -12.046,  "lng": -77.043},
    {"place_id": "guatemala_city",  "name": "Guatemala City",  "basin_id": "guatemala_city", "lat": 14.6349,  "lng": -90.5069},
    {"place_id": "santiago",        "name": "Santiago",        "basin_id": "santiago_chile", "lat": -33.4489, "lng": -70.6693},
    {"place_id": "mexico_city",     "name": "Mexico City",     "basin_id": "mexico_city",    "lat": 19.4326,  "lng": -99.1332},
    {"place_id": "port_au_prince",  "name": "Port-au-Prince",  "basin_id": "port_au_prince", "lat": 18.5944,  "lng": -72.3074},
]


def validate_configuration(configuration: dict):
    pass


def schema(configuration: dict):
    return [
        {
            "table": "river_discharge",
            "primary_key": ["place_id", "date"],
            "columns": {
                "place_id": "STRING",
                "place_name": "STRING",
                "basin_id": "STRING",
                "latitude": "FLOAT",
                "longitude": "FLOAT",
                "date": "NAIVE_DATE",
                "discharge_m3s": "FLOAT"
            }
        },
        {
            "table": "soil_moisture",
            "primary_key": ["place_id", "ts"],
            "columns": {
                "place_id": "STRING",
                "place_name": "STRING",
                "basin_id": "STRING",
                "latitude": "FLOAT",
                "longitude": "FLOAT",
                "ts": "UTC_DATETIME",
                "moisture_m3m3": "FLOAT"
            }
        }
    ]


def _get_json(base_url: str, params: dict) -> dict:
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "centinela-fivetran-connector"})
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def update(configuration: dict, state: dict):
    validate_configuration(configuration=configuration)
    discharge_rows = 0
    soil_rows = 0

    for place in PLACES:
        identity = {
            "place_id": place["place_id"],
            "place_name": place["name"],
            "basin_id": place["basin_id"],
            "latitude": place["lat"],
            "longitude": place["lng"],
        }

        try:
            flood = _get_json(FLOOD_URL, {
                "latitude": place["lat"], "longitude": place["lng"],
                "daily": "river_discharge", "past_days": 31, "forecast_days": 1
            })
            daily = flood.get("daily") or {}
            for date_str, value in zip(daily.get("time") or [], daily.get("river_discharge") or []):
                if value is None:
                    continue
                op.upsert(table="river_discharge", data={
                    **identity, "date": date_str, "discharge_m3s": float(value)
                })
                discharge_rows += 1
        except Exception as e:
            log.warning(f"Flood fetch failed for {place['place_id']}: {e}")

        try:
            soil = _get_json(SOIL_URL, {
                "latitude": place["lat"], "longitude": place["lng"],
                "hourly": "soil_moisture_0_to_7cm", "past_days": 3, "forecast_days": 1
            })
            hourly = soil.get("hourly") or {}
            for ts_str, value in zip(hourly.get("time") or [], hourly.get("soil_moisture_0_to_7cm") or []):
                if value is None:
                    continue
                op.upsert(table="soil_moisture", data={
                    **identity, "ts": f"{ts_str}:00Z" if len(ts_str) == 16 else ts_str,
                    "moisture_m3m3": float(value)
                })
                soil_rows += 1
        except Exception as e:
            log.warning(f"Soil fetch failed for {place['place_id']}: {e}")

    op.checkpoint({"places": len(PLACES)})
    log.info(f"Global hydro sync complete: {discharge_rows} discharge rows, {soil_rows} soil rows upserted")


connector = Connector(update=update, schema=schema)

if __name__ == "__main__":
    connector.debug(configuration={})
