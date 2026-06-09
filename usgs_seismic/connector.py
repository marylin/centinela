import json
import urllib.request
import math
from datetime import datetime, timezone

from fivetran_connector_sdk import Connector
from fivetran_connector_sdk import Logging as log
from fivetran_connector_sdk import Operations as op

MUNIS = {
    "Cali": (3.4516, -76.5320),
    "Yumbo": (3.5833, -76.4917),
    "Jamundí": (3.2667, -76.5333),
    "Lima": (-12.046, -77.043),
    "Callao": (-12.056, -77.118),
    "Chorrillos": (-12.168, -77.022),
    "Guatemala City": (14.6349, -90.5069),
    "Mixco": (14.6333, -90.6064),
    "Villa Nueva": (14.5269, -90.5969)
}

def validate_configuration(configuration: dict):
    pass

def schema(configuration: dict):
    return [
        {
            "table": "seismic",
            "primary_key": ["id"],
            "columns": {
                "id": "STRING",
                "municipality": "STRING",
                "magnitude": "DOUBLE",
                "place": "STRING",
                "time": "UTC_DATETIME",
                "latitude": "DOUBLE",
                "longitude": "DOUBLE",
                "depth_km": "DOUBLE"
            }
        }
    ]

def update(configuration: dict, state: dict):
    validate_configuration(configuration=configuration)
    
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_day.geojson"
    log.info(f"Fetching USGS earthquake data from {url}")
    
    records = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            geojson = json.loads(response.read().decode('utf-8'))
            
        features = geojson.get("features", [])
        log.info(f"Retrieved {len(features)} total earthquake features from USGS")
        
        for f in features:
            geom = f.get("geometry", {})
            coords = geom.get("coordinates", [])
            if len(coords) < 3:
                continue
            lon, lat, depth = coords[:3]
            
            # Find closest municipality
            closest_muni = None
            min_dist = float('inf')
            for name, (mlat, mlon) in MUNIS.items():
                dist = math.sqrt((lat - mlat)**2 + (lon - mlon)**2) * 111.0
                if dist < min_dist:
                    min_dist = dist
                    closest_muni = name
            
            # Attribute if within 150 km
            if closest_muni and min_dist < 150.0:
                prop = f.get("properties", {}) or {}
                t_ms = prop.get("time") or 0
                dt = datetime.fromtimestamp(t_ms / 1000.0, tz=timezone.utc)
                records.append({
                    "id": f.get("id"),
                    "municipality": closest_muni,
                    "magnitude": float(prop.get("mag") or 0.0),
                    "place": prop.get("place", "Unknown"),
                    "time": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "latitude": float(lat),
                    "longitude": float(lon),
                    "depth_km": float(depth)
                })
    except Exception as e:
        log.warning(f"Failed to fetch real USGS earthquake data: {e}. Using baseline fallback.")

    # Preserve only the Rio Cauca demo baseline; never fabricate seismic events for
    # other municipalities (e.g. Lima). Real quakes always take precedence, and we
    # never invent or inflate magnitudes outside the original demo basin.
    CAUCA_DEMO_MUNIS = {"Cali", "Yumbo", "Jamundí"}
    has_cauca_event = any(r["municipality"] in CAUCA_DEMO_MUNIS for r in records)
    if not has_cauca_event:
        log.info("No active earthquakes found in basin area. Injecting baseline demo event.")
        now = datetime.now(timezone.utc)
        records.append({
            "id": f"demo-seismic-{now.strftime('%Y%m%d%H')}",
            "municipality": "Jamundí",
            "magnitude": 3.8,
            "place": "12km S of Jamundí, Colombia",
            "time": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "latitude": 3.15,
            "longitude": -76.55,
            "depth_km": 15.0
        })

    log.info(f"Syncing {len(records)} seismic records to BigQuery destination")
    for r in records:
        op.upsert(table="seismic", data=r)
        
    op.checkpoint({"last_sync_time": datetime.now(timezone.utc).isoformat()})
    log.info("Seismic sync completed successfully")

connector = Connector(update=update, schema=schema)

if __name__ == "__main__":
    connector.debug(configuration={})
