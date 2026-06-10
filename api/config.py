"""Static configuration: the places registry and constants.

THE REGISTRY HOLDS STRUCTURE AND NAMES ONLY. Nothing coordinate-shaped is
hardcoded; coordinates are derived per place by api/places_resolver.py
(geocoded anchor + strongest-discharge GloFAS cell) and persisted by
api.main's resolution glue. kind: "flood-watch" | "seismic-watch".
All names here are assigned once at import and may be from-imported.
"""
import os

import api.core  # noqa: F401  (dotenv must run before the env read below)

REAL_CONNECTORS = [
    {"id": "kung_gleeful", "name": "USGS Raw Events (Connector SDK)", "type": "connector_sdk"},
    {"id": "rpm_muriate", "name": "Global Hydrology — GloFAS + Soil (Connector SDK)", "type": "connector_sdk"}
]

BASINS = [
    {
        "id": "rio_cauca", "name": "Rio Cauca", "country": "Colombia", "cc": "CO",
        "kind": "flood-watch",
        "places": [
            {"id": "cali", "name": "Cali"},
            {"id": "yumbo", "name": "Yumbo"},
            {"id": "jamundi", "name": "Jamundí"}
        ],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "rio_magdalena", "name": "Rio Magdalena", "country": "Colombia", "cc": "CO",
        "kind": "flood-watch",
        "places": [
            {"id": "neiva", "name": "Neiva"},
            {"id": "girardot", "name": "Girardot"},
            {"id": "honda", "name": "Honda"}
        ],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "lima_peru", "name": "Lima", "country": "Peru", "cc": "PE",
        "kind": "seismic-watch",
        "places": [{"id": "lima", "name": "Lima"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "guatemala_city", "name": "Guatemala City", "country": "Guatemala", "cc": "GT",
        "kind": "seismic-watch",
        "places": [{"id": "guatemala_city", "name": "Guatemala City"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "santiago_chile", "name": "Santiago", "country": "Chile", "cc": "CL",
        "kind": "seismic-watch",
        "places": [{"id": "santiago", "name": "Santiago"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "mexico_city", "name": "Mexico City", "country": "Mexico", "cc": "MX",
        "kind": "seismic-watch",
        "places": [{"id": "mexico_city", "name": "Mexico City"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "port_au_prince", "name": "Port-au-Prince", "country": "Haiti", "cc": "HT",
        "kind": "seismic-watch",
        "places": [{"id": "port_au_prince", "name": "Port-au-Prince"}],
        "connectors": REAL_CONNECTORS
    },
    # Promoted from the watchlist 2026-06-10 (evidence in
    # docs/02-Requirements/centinela-activity-scoring.md): Manaus rides the
    # Amazon's June peak, Bogotá is flood-active, Managua anchors the active
    # Cocos margin. Coordinates derive like everywhere else.
    {
        "id": "manaus", "name": "Manaus", "country": "Brazil", "cc": "BR",
        "kind": "flood-watch",
        "places": [{"id": "manaus", "name": "Manaus"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "bogota", "name": "Bogotá", "country": "Colombia", "cc": "CO",
        "kind": "flood-watch",
        "places": [{"id": "bogota", "name": "Bogotá"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "managua", "name": "Managua", "country": "Nicaragua", "cc": "NI",
        "kind": "seismic-watch",
        "places": [{"id": "managua", "name": "Managua"}],
        "connectors": REAL_CONNECTORS
    },
    # Global expansion 2026-06-10 (user-directed; not LatAm-limited). All
    # coordinates derive; adding a place stays one config row.
    {
        "id": "jakarta", "name": "Jakarta", "country": "Indonesia", "cc": "ID",
        "kind": "flood-watch",
        "places": [{"id": "jakarta", "name": "Jakarta"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "manila", "name": "Manila", "country": "Philippines", "cc": "PH",
        "kind": "seismic-watch",
        "places": [{"id": "manila", "name": "Manila"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "dhaka", "name": "Dhaka", "country": "Bangladesh", "cc": "BD",
        "kind": "flood-watch",
        "places": [{"id": "dhaka", "name": "Dhaka"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "kathmandu", "name": "Kathmandu", "country": "Nepal", "cc": "NP",
        "kind": "seismic-watch",
        "places": [{"id": "kathmandu", "name": "Kathmandu"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "istanbul", "name": "Istanbul", "country": "Türkiye", "cc": "TR",
        "kind": "seismic-watch",
        "places": [{"id": "istanbul", "name": "Istanbul"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "tokyo", "name": "Tokyo", "country": "Japan", "cc": "JP",
        "kind": "seismic-watch",
        "places": [{"id": "tokyo", "name": "Tokyo"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "taipei", "name": "Taipei", "country": "Taiwan", "cc": "TW",
        "kind": "seismic-watch",
        "places": [{"id": "taipei", "name": "Taipei"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "wellington", "name": "Wellington", "country": "New Zealand", "cc": "NZ",
        "kind": "seismic-watch",
        "places": [{"id": "wellington", "name": "Wellington"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "tehran", "name": "Tehran", "country": "Iran", "cc": "IR",
        "kind": "seismic-watch",
        "places": [{"id": "tehran", "name": "Tehran"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "karachi", "name": "Karachi", "country": "Pakistan", "cc": "PK",
        "kind": "flood-watch",
        "places": [{"id": "karachi", "name": "Karachi"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "bangkok", "name": "Bangkok", "country": "Thailand", "cc": "TH",
        "kind": "flood-watch",
        "places": [{"id": "bangkok", "name": "Bangkok"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "hanoi", "name": "Hanoi", "country": "Vietnam", "cc": "VN",
        "kind": "flood-watch",
        "places": [{"id": "hanoi", "name": "Hanoi"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "athens", "name": "Athens", "country": "Greece", "cc": "GR",
        "kind": "seismic-watch",
        "places": [{"id": "athens", "name": "Athens"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "naples", "name": "Naples", "country": "Italy", "cc": "IT",
        "kind": "seismic-watch",
        "places": [{"id": "naples", "name": "Naples"}],
        "connectors": REAL_CONNECTORS
    },
    {
        "id": "nairobi", "name": "Nairobi", "country": "Kenya", "cc": "KE",
        "kind": "flood-watch",
        "places": [{"id": "nairobi", "name": "Nairobi"}],
        "connectors": REAL_CONNECTORS
    }
]

def basin_municipalities(b):
    return [p["name"] for p in b["places"]]

CONNECTOR_ID = REAL_CONNECTORS[0]["id"]

SEISMIC_BBOX_PAD_DEG = 1.5

TELEMETRY_PROVENANCE = {"rainfall": "live", "discharge": "model-glofas", "soil": "model-ecmwf"}

LOCATION_CONDITIONS_PROVENANCE = {
    "rainfall": "observed · Google Weather",
    "river_discharge": "model · GloFAS via Open-Meteo",
    "soil_moisture": "model · ECMWF via Open-Meteo",
    "air_quality": "observed · Google Air Quality"
}

# The usgs_raw_events Fivetran connector syncs the global M4.5+ monthly feed.
RAW_EVENTS_TABLE = os.environ.get("SEISMIC_RAW_EVENTS_TABLE", "usgs_raw_events.events")
RAW_EVENT_FIELDS = ["id", "magnitude", "place", "time", "latitude", "longitude", "depth_km"]
