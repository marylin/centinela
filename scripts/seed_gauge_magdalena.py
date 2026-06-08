from google.cloud import bigquery
from datetime import datetime, timezone

client = bigquery.Client(project="centinela-498622")
NOW = datetime.now(timezone.utc)

gauge_rows = [
    {
        "_row": 1000,
        "reading_time": NOW.strftime("%Y-%m-%d %H:%M:%S"),
        "river_level_m": 4.8,
        "station_id": "MG-G01",
        "alert_threshold_m": 6,
        "basin": "Rio Magdalena",
    }
]
errors = client.insert_rows_json("centinela-498622.google_sheets.rapidagent", gauge_rows)
if errors:
    print("ERROR:", errors)
else:
    print("Inserted 1 gauge row for Rio Magdalena.")
