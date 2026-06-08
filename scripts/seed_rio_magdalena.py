"""Seed Rio Magdalena mock hazard data into BigQuery.

Run once:  python scripts/seed_rio_magdalena.py

Idempotent: deletes any existing Rio Magdalena rows before inserting fresh ones,
so it is safe to re-run.
"""

from datetime import datetime, timezone, timedelta
from google.cloud import bigquery

PROJECT = "centinela-498622"
BASIN = "Rio Magdalena"

# Municipalities and their realistic hazard profiles.
# Neiva: upper valley, moderate flood / landslide.
# Girardot: mid-valley, elevated compound risk (flood + seismic proximity to Bogotá arc).
# Honda: narrowing gorge, high flood risk, steeper slopes.
MUNICIPALITIES = [
    {
        "municipality": "Neiva",
        "population": 380000,
        "rainfall_mm": 18.4,
        "saturation_index": 0.72,
        "river_level_m": 3.8,
        "alert_threshold_m": 5.5,
        "slope_angle_deg": 14.0,
        "susceptibility_index": 0.32,
        "earthquake_magnitude": None,
    },
    {
        "municipality": "Girardot",
        "population": 108000,
        "rainfall_mm": 22.1,
        "saturation_index": 0.81,
        "river_level_m": 4.6,
        "alert_threshold_m": 5.5,
        "slope_angle_deg": 21.0,
        "susceptibility_index": 0.58,
        "earthquake_magnitude": 3.2,
    },
    {
        "municipality": "Honda",
        "population": 53000,
        "rainfall_mm": 31.5,
        "saturation_index": 0.91,
        "river_level_m": 5.8,
        "alert_threshold_m": 6.0,
        "slope_angle_deg": 29.0,
        "susceptibility_index": 0.74,
        "earthquake_magnitude": None,
    },
]

NOW = datetime.now(timezone.utc)


def run():
    client = bigquery.Client(project=PROJECT)

    # ── municipality_population ────────────────────────────────────────────────
    print("Inserting municipality_population rows...")
    # Delete existing rows for this basin first (BigQuery DML)
    client.query(
        f"DELETE FROM unified_feeds.municipality_population WHERE basin = '{BASIN}'"
    ).result()
    rows = [
        {"municipality": m["municipality"], "population": m["population"], "basin": BASIN}
        for m in MUNICIPALITIES
    ]
    errors = client.insert_rows_json("centinela-498622.unified_feeds.municipality_population", rows)
    if errors:
        print(f"  ERROR: {errors}")
    else:
        print(f"  Inserted {len(rows)} rows.")

    # ── rainfall ───────────────────────────────────────────────────────────────
    print("Inserting rainfall rows...")
    client.query(
        f"DELETE FROM unified_feeds.rainfall WHERE basin = '{BASIN}'"
    ).result()
    rain_rows = [
        {
            "timestamp": NOW.isoformat(),
            "station_id": f"MG-R{i+1:02d}",
            "precipitation_mm": m["rainfall_mm"],
            "basin": BASIN,
            "municipality": m["municipality"],
        }
        for i, m in enumerate(MUNICIPALITIES)
    ]
    errors = client.insert_rows_json("centinela-498622.unified_feeds.rainfall", rain_rows)
    if errors:
        print(f"  ERROR: {errors}")
    else:
        print(f"  Inserted {len(rain_rows)} rows.")

    # ── soil_saturation ────────────────────────────────────────────────────────
    print("Inserting soil_saturation rows...")
    client.query(
        f"DELETE FROM unified_feeds.soil_saturation WHERE basin = '{BASIN}'"
    ).result()
    soil_rows = [
        {
            "timestamp": NOW.isoformat(),
            "station_id": f"MG-S{i+1:02d}",
            "saturation_index": m["saturation_index"],
            "basin": BASIN,
            "municipality": m["municipality"],
        }
        for i, m in enumerate(MUNICIPALITIES)
    ]
    errors = client.insert_rows_json("centinela-498622.unified_feeds.soil_saturation", soil_rows)
    if errors:
        print(f"  ERROR: {errors}")
    else:
        print(f"  Inserted {len(soil_rows)} rows.")

    # ── landslide ──────────────────────────────────────────────────────────────
    # Landslide table has no basin column; municipality uniqueness is sufficient
    # since municipalities are basin-scoped.  We delete by municipality name list.
    print("Inserting landslide rows...")
    munis_quoted = ", ".join(f"'{m['municipality']}'" for m in MUNICIPALITIES)
    client.query(
        f"DELETE FROM unified_feeds.landslide WHERE municipality IN ({munis_quoted})"
    ).result()
    landslide_rows = [
        {
            "timestamp": NOW.isoformat(),
            "municipality": m["municipality"],
            "slope_angle_deg": m["slope_angle_deg"],
            "susceptibility_index": m["susceptibility_index"],
            "risk_level": (
                "HIGH" if m["susceptibility_index"] >= 0.65
                else "MODERATE" if m["susceptibility_index"] >= 0.40
                else "LOW"
            ),
        }
        for m in MUNICIPALITIES
    ]
    errors = client.insert_rows_json("centinela-498622.unified_feeds.landslide", landslide_rows)
    if errors:
        print(f"  ERROR: {errors}")
    else:
        print(f"  Inserted {len(landslide_rows)} rows.")

    # ── google_sheets.rapidagent (river gauge) ─────────────────────────────────
    # One basin-level gauge row matching how Rio Cauca is seeded (single row,
    # partitioned by basin, all municipalities share the same river level).
    # alert_threshold_m is INTEGER in the schema -- use int values.
    print("Inserting gauge row into google_sheets.rapidagent...")
    client.query(
        f"DELETE FROM google_sheets.rapidagent WHERE basin = '{BASIN}'"
    ).result()

    gauge_rows = [
        {
            "_row": 1000,
            "reading_time": NOW.strftime("%Y-%m-%d %H:%M:%S"),
            "river_level_m": 4.8,          # current median for the basin
            "station_id": "MG-G01",
            "alert_threshold_m": 6,         # must be INTEGER
            "basin": BASIN,
        }
    ]
    errors = client.insert_rows_json("centinela-498622.google_sheets.rapidagent", gauge_rows)
    if errors:
        print(f"  ERROR: {errors}")
    else:
        print(f"  Inserted 1 gauge row.")

    print("\nDone seeding Rio Magdalena data.")


if __name__ == "__main__":
    run()
