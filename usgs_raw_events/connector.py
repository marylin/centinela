"""Fivetran Connector SDK: raw USGS M4.5+ monthly feed.

Ingests the global USGS 4.5_month GeoJSON summary into a raw-events table,
upserted by USGS event id. Unlike the per-municipality seismic connector
(usgs_seismic/), this table carries NO municipality attribution and NO
baseline/demo events: every row is a real USGS detection, verbatim.
Downstream organization (recent events, active regions) happens in BigQuery.
"""

import json
import urllib.request
from datetime import datetime, timezone

from fivetran_connector_sdk import Connector
from fivetran_connector_sdk import Logging as log
from fivetran_connector_sdk import Operations as op

FEED_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_month.geojson"


def validate_configuration(configuration: dict):
    pass


def schema(configuration: dict):
    return [
        {
            "table": "events",
            "primary_key": ["id"],
            "columns": {
                "id": "STRING",
                "magnitude": "FLOAT",
                "place": "STRING",
                "time": "UTC_DATETIME",
                "latitude": "FLOAT",
                "longitude": "FLOAT",
                "depth_km": "FLOAT"
            }
        }
    ]


def update(configuration: dict, state: dict):
    validate_configuration(configuration=configuration)

    log.info(f"Fetching raw USGS M4.5+ monthly feed from {FEED_URL}")
    req = urllib.request.Request(FEED_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        geojson = json.loads(response.read().decode("utf-8"))

    features = geojson.get("features", [])
    log.info(f"Retrieved {len(features)} earthquake features from USGS")

    synced = 0
    for f in features:
        event_id = f.get("id")
        if not event_id:
            continue
        coords = (f.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 3:
            continue
        lon, lat, depth = coords[:3]
        prop = f.get("properties") or {}
        t_ms = prop.get("time") or 0
        dt = datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc)
        op.upsert(table="events", data={
            "id": event_id,
            "magnitude": float(prop.get("mag") or 0.0),
            "place": prop.get("place") or "Unknown",
            "time": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latitude": float(lat),
            "longitude": float(lon),
            "depth_km": float(depth)
        })
        synced += 1

    op.checkpoint({"last_sync_time": datetime.now(timezone.utc).isoformat()})
    log.info(f"Raw USGS sync completed: {synced} events upserted")


connector = Connector(update=update, schema=schema)

if __name__ == "__main__":
    connector.debug(configuration={})
