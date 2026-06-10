"""Fivetran Connector SDK: global hydrology (Open-Meteo).

Ingests, for every monitored place, two genuinely real model series:
  - daily river discharge (GloFAS v4 via the Open-Meteo flood API), and
  - hourly topsoil moisture (ECMWF via the Open-Meteo forecast API).
Both are MODEL data (not gauge measurements) and must always be labeled as
such downstream. No API key required; data is CC BY 4.0.

NOTHING IS HARDCODED: the place list is fetched from the Centinela service's
resolved registry at sync time (`service_url` in the connection configuration).
Each place carries a geocoded city anchor and an auto-discovered river cell
(the strongest-discharge GloFAS cell near the city): discharge samples the
river cell, soil samples the city anchor. The discharge pull covers a full
92-day window upserted on (place_id, date), so a coordinate change cleanly
overwrites the entire index baseline after one sync.

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


def validate_configuration(configuration: dict):
    if not (configuration or {}).get("service_url"):
        raise ValueError("Missing required configuration: service_url (the Centinela service base URL)")


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


def _fetch_registry(service_url: str):
    """The resolved registry from the live service. Raises when the service is
    unreachable or serves nothing usable (Fivetran retries on schedule).
    Unresolved places are skipped with a warning so one bad new entry never
    blocks the rest."""
    payload = _get_json(f"{service_url.rstrip('/')}/places", {})
    places = []
    for group in payload:
        for p in group.get("places") or []:
            if not p.get("resolved") or not p.get("anchor"):
                log.warning(f"Skipping unresolved place {p.get('id')} this sync")
                continue
            places.append({
                "place_id": p["id"],
                "name": p["name"],
                "basin_id": group["id"],
                "anchor": p["anchor"],
                # Falls back to the anchor when a place has no river in range.
                "hydro": p.get("hydro_point") or p["anchor"],
            })
    if not places:
        raise RuntimeError("Resolved registry is empty; aborting sync so Fivetran retries")
    return places


def update(configuration: dict, state: dict):
    validate_configuration(configuration=configuration)
    places = _fetch_registry(configuration["service_url"])
    discharge_rows = 0
    soil_rows = 0

    for place in places:
        try:
            flood = _get_json(FLOOD_URL, {
                "latitude": place["hydro"]["lat"], "longitude": place["hydro"]["lng"],
                "daily": "river_discharge", "past_days": 92, "forecast_days": 1
            })
            daily = flood.get("daily") or {}
            for date_str, value in zip(daily.get("time") or [], daily.get("river_discharge") or []):
                if value is None:
                    continue
                op.upsert(table="river_discharge", data={
                    "place_id": place["place_id"],
                    "place_name": place["name"],
                    "basin_id": place["basin_id"],
                    "latitude": place["hydro"]["lat"],
                    "longitude": place["hydro"]["lng"],
                    "date": date_str, "discharge_m3s": float(value)
                })
                discharge_rows += 1
        except Exception as e:
            log.warning(f"Flood fetch failed for {place['place_id']}: {e}")

        try:
            soil = _get_json(SOIL_URL, {
                "latitude": place["anchor"]["lat"], "longitude": place["anchor"]["lng"],
                "hourly": "soil_moisture_0_to_7cm", "past_days": 3, "forecast_days": 1
            })
            hourly = soil.get("hourly") or {}
            for ts_str, value in zip(hourly.get("time") or [], hourly.get("soil_moisture_0_to_7cm") or []):
                if value is None:
                    continue
                op.upsert(table="soil_moisture", data={
                    "place_id": place["place_id"],
                    "place_name": place["name"],
                    "basin_id": place["basin_id"],
                    "latitude": place["anchor"]["lat"],
                    "longitude": place["anchor"]["lng"],
                    "ts": f"{ts_str}:00Z" if len(ts_str) == 16 else ts_str,
                    "moisture_m3m3": float(value)
                })
                soil_rows += 1
        except Exception as e:
            log.warning(f"Soil fetch failed for {place['place_id']}: {e}")

    op.checkpoint({"places": len(places)})
    log.info(f"Global hydro sync complete: {discharge_rows} discharge rows, {soil_rows} soil rows upserted")


connector = Connector(update=update, schema=schema)

if __name__ == "__main__":
    connector.debug(configuration={"service_url": "https://centinela-v1-765013283380.us-central1.run.app"})
