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

RIVER_KEYS = {"time", "river_level_m", "threshold_m"}
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
    # 1. /basins simulated flag
    print("\nStep 1: /basins carries the simulated flag...")
    res = requests.get(f"{SERVER_URL}/basins")
    if res.status_code != 200:
        fail(f"GET /basins returned {res.status_code}")
    basins = {b["id"]: b for b in res.json()}
    if basins.get("rio_magdalena", {}).get("simulated") is not True:
        fail(f"rio_magdalena should be simulated=true: {basins.get('rio_magdalena')}")
    for basin_id, b in basins.items():
        if basin_id != "rio_magdalena" and b.get("simulated") is not False:
            fail(f"{basin_id} should be simulated=false: {b}")
    print("Success: only rio_magdalena is flagged simulated.")

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

    # 4. /telemetry-history seeded series + provenance contract
    print("\nStep 4: /telemetry-history returns river + rainfall series...")
    res = requests.get(f"{SERVER_URL}/telemetry-history", params={"basin": "rio_cauca"})
    if res.status_code != 200:
        fail(f"GET /telemetry-history returned {res.status_code}")
    body = res.json()
    river = body.get("river")
    rain = body.get("rainfall")
    if not isinstance(river, list) or len(river) < 2:
        fail(f"River series missing/too short: {river}")
    if not isinstance(rain, list) or len(rain) < 2:
        fail(f"Rainfall series missing/too short: {rain}")
    for r in river:
        if set(r.keys()) != RIVER_KEYS:
            fail(f"River row keys mismatch: {sorted(r.keys())}")
    for r in rain:
        if set(r.keys()) != RAIN_KEYS:
            fail(f"Rainfall row keys mismatch: {sorted(r.keys())}")
    if [r["time"] for r in river] != sorted(r["time"] for r in river):
        fail("River series not in ascending time order")
    if [r["time"] for r in rain] != sorted(r["time"] for r in rain):
        fail("Rainfall series not in ascending time order")
    prov = body.get("provenance") or {}
    if prov.get("rainfall") != "live" or prov.get("river") != "pipeline-seeded":
        fail(f"Provenance contract wrong: {prov}")
    print(f"Success: {len(river)} river rows + {len(rain)} rainfall rows with honest provenance.")

    # 5. Unknown basin is a 404
    print("\nStep 5: /telemetry-history rejects unknown basins...")
    res = requests.get(f"{SERVER_URL}/telemetry-history", params={"basin": "atlantis"})
    if res.status_code != 404:
        fail(f"Expected 404 for unknown basin, got {res.status_code}")
    print("Success: unknown basin returns 404.")


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
