import sys
import subprocess
import requests
import json
from datetime import datetime, timezone, timedelta

def run_bq_query(query: str):
    """Executes a BigQuery SQL query using the bq CLI."""
    cmd = 'bq query --project_id=centinela-498622 --use_legacy_sql=false --quiet'
    print(f"Running query: {query[:120]}...")
    res = subprocess.run(cmd, shell=True, input=query, capture_output=True, text=True)
    if res.returncode != 0:
        print(f"Query failed! STDERR: {res.stderr}")
        raise RuntimeError(res.stderr)
    print("Query succeeded.")
    return res.stdout

def populate_all():
    # 1. Clear existing data in tables to ensure idempotency
    print("Clearing existing data...")
    run_bq_query("DELETE FROM unified_feeds.rainfall WHERE true")
    run_bq_query("DELETE FROM unified_feeds.soil_saturation WHERE true")
    run_bq_query("DELETE FROM unified_feeds.municipality_population WHERE true")

    # 2. Populate static municipality population data
    print("Populating municipality population...")
    pop_query = """
    INSERT INTO unified_feeds.municipality_population (municipality, population, basin)
    VALUES 
      ('Cali', 2227642, 'Rio Cauca'),
      ('Yumbo', 120000, 'Rio Cauca'),
      ('Jamundí', 120000, 'Rio Cauca')
    """
    run_bq_query(pop_query)

    # 3. Generate and populate mock storm data (rainfall)
    # We will insert mock data for Cali, Yumbo, Jamundí for the last 6 hours
    print("Populating mock storm rainfall data...")
    now_utc = datetime.now(timezone.utc)
    rainfall_values = []
    
    # Cali (RF-01) storm pattern
    cali_precip = [2.0, 5.0, 12.5, 25.0, 15.0, 4.5]
    # Yumbo (RF-02) storm pattern
    yumbo_precip = [1.5, 4.0, 10.0, 20.0, 12.0, 3.0]
    # Jamundí (RF-03) storm pattern
    jamundi_precip = [2.5, 6.0, 15.0, 30.0, 18.0, 5.0]

    for i in range(6):
        ts = (now_utc - timedelta(hours=6-i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rainfall_values.append(f"('{ts}', 'RF-01', {cali_precip[i]}, 'Rio Cauca', 'Cali')")
        rainfall_values.append(f"('{ts}', 'RF-02', {yumbo_precip[i]}, 'Rio Cauca', 'Yumbo')")
        rainfall_values.append(f"('{ts}', 'RF-03', {jamundi_precip[i]}, 'Rio Cauca', 'Jamundí')")

    if rainfall_values:
        rain_query = f"""
        INSERT INTO unified_feeds.rainfall (timestamp, station_id, precipitation_mm, basin, municipality)
        VALUES {', '.join(rainfall_values)}
        """
        run_bq_query(rain_query)

    # 4. Generate and populate mock soil-saturation data
    print("Populating mock storm soil saturation data...")
    saturation_values = []
    
    # Cali (SS-01) saturation pattern
    cali_sat = [0.35, 0.45, 0.60, 0.85, 0.95, 0.92]
    # Yumbo (SS-02) saturation pattern
    yumbo_sat = [0.30, 0.40, 0.55, 0.78, 0.88, 0.85]
    # Jamundí (SS-03) saturation pattern
    jamundi_sat = [0.40, 0.50, 0.68, 0.92, 0.98, 0.95]

    for i in range(6):
        ts = (now_utc - timedelta(hours=6-i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        saturation_values.append(f"('{ts}', 'SS-01', {cali_sat[i]}, 'Rio Cauca', 'Cali')")
        saturation_values.append(f"('{ts}', 'SS-02', {yumbo_sat[i]}, 'Rio Cauca', 'Yumbo')")
        saturation_values.append(f"('{ts}', 'SS-03', {jamundi_sat[i]}, 'Rio Cauca', 'Jamundí')")

    if saturation_values:
        sat_query = f"""
        INSERT INTO unified_feeds.soil_saturation (timestamp, station_id, saturation_index, basin, municipality)
        VALUES {', '.join(saturation_values)}
        """
        run_bq_query(sat_query)

    # 5. Wire one genuinely live feed: Open-Meteo current rainfall for Cali
    print("Fetching live Open-Meteo current rainfall...")
    try:
        url = "https://api.open-meteo.com/v1/forecast?latitude=3.4516&longitude=-76.5320&current=precipitation&timezone=UTC"
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        current = data.get("current", {})
        
        # Open-Meteo returns 'time' in ISO format like '2026-06-07T12:00'.
        # We append 'Z' to make it a valid UTC ISO timestamp.
        raw_time = current.get("time")
        if raw_time:
            timestamp_str = f"{raw_time}:00Z" if len(raw_time) == 16 else f"{raw_time}Z"
            precipitation = float(current.get("precipitation", 0.0))
            
            print(f"Live Rainfall: {precipitation} mm at {timestamp_str}")
            
            live_query = f"""
            INSERT INTO unified_feeds.rainfall (timestamp, station_id, precipitation_mm, basin, municipality)
            VALUES ('{timestamp_str}', 'OM-01', {precipitation}, 'Rio Cauca', 'Cali')
            """
            run_bq_query(live_query)
        else:
            print("Warning: No 'time' key in Open-Meteo current data")
    except Exception as e:
        print(f"Error fetching live Open-Meteo data: {e}")
        raise e

if __name__ == "__main__":
    populate_all()
