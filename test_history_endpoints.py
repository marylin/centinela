"""Targeted tests for the history endpoints (/risk-history, /telemetry-history)
and the simulated flag on /basins. Runs the API in TESTING mode (seeded
series, no BigQuery / Firestore access)."""

import os
import subprocess
import sys
import time

import requests

PORT = 8004
SERVER_URL = f"http://127.0.0.1:{PORT}"

SOIL_KEYS = {"time", "moisture_m3m3"}
RAIN_KEYS = {"time", "precipitation_mm"}


def kill_port():
    try:
        output = subprocess.check_output(f"netstat -ano | findstr :{PORT}", shell=True).decode()
        for line in output.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 5 and parts[1].endswith(f":{PORT}"):
                pid = parts[-1]
                print(f"Killing process {pid} on port {PORT}...")
                subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)
    except Exception:
        pass


def wait_for_server(timeout: int = 10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            res = requests.get(f"{SERVER_URL}/risk", timeout=2)
            if res.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def fail(msg):
    print(f"ERROR: {msg}")
    sys.exit(1)


def run_tests():
    # 1. /places registry (and the /basins alias)
    print("\nStep 1: /places serves the registry with coordinates...")
    res = requests.get(f"{SERVER_URL}/places")
    if res.status_code != 200:
        fail(f"GET /places returned {res.status_code}")
    groups = {b["id"]: b for b in res.json()}
    if len(groups) != 10:
        fail(f"Expected 10 groups, got {sorted(groups.keys())}")
    for gid, g in groups.items():
        if "simulated" in g:
            fail(f"{gid} still carries a simulated flag: {g}")
        places = g.get("places") or []
        if not places or any(not (p.get("id") and isinstance(p.get("lat"), float)) for p in places):
            fail(f"{gid} places malformed: {places}")
    if groups["rio_cauca"].get("kind") != "flood-watch" or groups["lima_peru"].get("kind") != "seismic-watch":
        fail("kind values wrong on the registry")
    alias = requests.get(f"{SERVER_URL}/basins")
    if alias.status_code != 200 or alias.json() != res.json():
        fail("/basins alias does not mirror /places")
    print("Success: registry served with places + coordinates; no simulated flags.")

    # 2. /risk-history seeded series for the default basin
    print("\nStep 2: /risk-history returns a seeded series...")
    res = requests.get(f"{SERVER_URL}/risk-history", params={"basin": "rio_cauca"})
    if res.status_code != 200:
        fail(f"GET /risk-history returned {res.status_code}")
    body = res.json()
    if body.get("basin") != "rio_cauca":
        fail(f"Wrong basin echoed: {body.get('basin')}")
    ticks = body.get("ticks")
    if not isinstance(ticks, list) or len(ticks) < 10:
        fail(f"Expected a seeded tick series, got {type(ticks)} len={len(ticks) if isinstance(ticks, list) else 'n/a'}")
    times = [t["t"] for t in ticks]
    if times != sorted(times):
        fail("Ticks are not in ascending time order")
    for tick in ticks:
        samples = tick.get("samples")
        if not isinstance(samples, dict) or not samples:
            fail(f"Tick missing samples: {tick}")
        for muni in ("Cali", "Yumbo", "Jamundí"):
            if muni not in samples:
                fail(f"Tick missing {muni}: {sorted(samples.keys())}")
        for muni, score in samples.items():
            if not (0.0 <= float(score) <= 1.0):
                fail(f"Score out of range for {muni}: {score}")
    print(f"Success: {len(ticks)} ascending ticks covering all Cauca municipalities.")

    # 3. /risk-history scopes by basin
    print("\nStep 3: /risk-history scopes to the requested basin...")
    res = requests.get(f"{SERVER_URL}/risk-history", params={"basin": "rio_magdalena"})
    if res.status_code != 200:
        fail(f"GET /risk-history (magdalena) returned {res.status_code}")
    ticks = res.json().get("ticks") or []
    if not ticks or "Neiva" not in ticks[-1].get("samples", {}):
        fail(f"Magdalena history missing its municipalities: {ticks[-1] if ticks else 'no ticks'}")
    print("Success: Magdalena history carries Magdalena municipalities.")

    # 4. /telemetry-history real-series contract (rain + discharge + soil)
    print("\nStep 4: /telemetry-history returns rainfall + discharge + soil series...")
    res = requests.get(f"{SERVER_URL}/telemetry-history", params={"basin": "rio_cauca"})
    if res.status_code != 200:
        fail(f"GET /telemetry-history returned {res.status_code}")
    body = res.json()
    rain = body.get("rainfall")
    discharge = body.get("discharge")
    soil = body.get("soil")
    if "river" in body:
        fail("Seeded river series still present in telemetry history")
    if not isinstance(rain, list) or len(rain) < 2:
        fail(f"Rainfall series missing/too short: {rain}")
    if not isinstance(discharge, list) or len(discharge) < 2:
        fail(f"Discharge series missing/too short: {discharge}")
    if not isinstance(soil, list) or len(soil) < 2:
        fail(f"Soil series missing/too short: {soil}")
    for r in rain:
        if set(r.keys()) != RAIN_KEYS:
            fail(f"Rainfall row keys mismatch: {sorted(r.keys())}")
    for r in soil:
        if set(r.keys()) != SOIL_KEYS:
            fail(f"Soil row keys mismatch: {sorted(r.keys())}")
    prov = body.get("provenance") or {}
    if prov.get("rainfall") != "live" or prov.get("discharge") != "model-glofas" or prov.get("soil") != "model-ecmwf":
        fail(f"Provenance contract wrong: {prov}")
    scoped = requests.get(f"{SERVER_URL}/telemetry-history", params={"basin": "rio_cauca", "place": "cali"})
    if scoped.status_code != 200 or scoped.json().get("place") != "cali":
        fail(f"Place-scoped telemetry failed: {scoped.status_code}")
    print(f"Success: {len(rain)} rain + {len(discharge)} discharge + {len(soil)} soil rows, honest provenance, place scoping works.")

    # 5. Unknown basin is a 404
    print("\nStep 5: /telemetry-history rejects unknown basins...")
    res = requests.get(f"{SERVER_URL}/telemetry-history", params={"basin": "atlantis"})
    if res.status_code != 404:
        fail(f"Expected 404 for unknown basin, got {res.status_code}")
    print("Success: unknown basin returns 404.")

    # 6. /location-conditions seeded payload + provenance contract
    print("\nStep 6: /location-conditions returns the seeded multi-source payload...")
    res = requests.get(f"{SERVER_URL}/location-conditions", params={"lat": 5.77, "lng": 125.12})
    if res.status_code != 200:
        fail(f"GET /location-conditions returned {res.status_code}")
    body = res.json()
    rain = body.get("rainfall") or {}
    if len(rain.get("hourly") or []) != 24 or "total_24h_mm" not in rain:
        fail(f"Rainfall block malformed: {rain}")
    discharge = body.get("river_discharge") or {}
    if discharge.get("direction") not in ("rising", "falling", "steady") or not discharge.get("daily"):
        fail(f"Discharge block malformed: {discharge}")
    soil = body.get("soil_moisture") or {}
    if not (0.0 <= float(soil.get("latest_m3m3", -1)) <= 1.0):
        fail(f"Soil block malformed: {soil}")
    prov = body.get("provenance") or {}
    if "Google Weather" not in prov.get("rainfall", "") or "GloFAS" not in prov.get("river_discharge", ""):
        fail(f"Provenance contract wrong: {prov}")
    res = requests.get(f"{SERVER_URL}/location-conditions", params={"lat": 999, "lng": 0})
    if res.status_code != 400:
        fail(f"Expected 400 for out-of-range lat, got {res.status_code}")
    print("Success: seeded conditions payload with provenance; out-of-range rejected.")


def main():
    kill_port()
    print("Starting FastAPI server locally in TESTING mode...")
    python_exe = os.path.join(".venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = "python"

    server_log = open("server_history_endpoints.log", "w", encoding="utf-8")
    server_process = subprocess.Popen(
        [python_exe, "-u", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        stdout=server_log,
        stderr=server_log,
        env={**os.environ, "TESTING": "true"}
    )

    try:
        if not wait_for_server():
            fail("FastAPI server failed to start.")
        print("FastAPI server started successfully.")
        run_tests()
        print("\n=====================================================================")
        print("           HISTORY ENDPOINTS SUITE COMPLETED: SUCCESS                ")
        print("=====================================================================")
    finally:
        server_process.terminate()
        server_process.wait()
        server_log.close()


if __name__ == "__main__":
    main()
