"""Targeted tests for the raw USGS pipeline endpoints (/seismic-events,
/seismic-focus), the /basins kind flag, and the simulated-event demo flow.
Runs the API in TESTING mode (seeded raw-events data, template narration)."""

import os
import subprocess
import sys
import time

import requests

PORT = 8002
SERVER_URL = f"http://127.0.0.1:{PORT}"

EVENT_KEYS = {"id", "magnitude", "place", "time", "latitude", "longitude", "depth_km", "simulated"}
REGION_KEYS = {"region", "count", "max_magnitude"}
SEVERITIES = {"Low", "Warning", "Danger", "Critical"}


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
    # 1. /basins kind flag
    print("\nStep 1: /basins entries carry the kind flag...")
    res = requests.get(f"{SERVER_URL}/basins")
    if res.status_code != 200:
        fail(f"GET /basins returned {res.status_code}")
    basins = {b["id"]: b for b in res.json()}
    expected_kinds = {
        "rio_cauca": "flood-watch",
        "rio_magdalena": "flood-watch",
        "lima_peru": "seismic-watch",
        "guatemala_city": "seismic-watch",
        "santiago_chile": "seismic-watch",
        "mexico_city": "seismic-watch",
        "port_au_prince": "seismic-watch"
    }
    for basin_id, kind in expected_kinds.items():
        if basin_id not in basins:
            fail(f"Basin {basin_id} missing from /basins")
        if basins[basin_id].get("kind") != kind:
            fail(f"Basin {basin_id} kind={basins[basin_id].get('kind')!r}, expected {kind!r}")
    print(f"Success: all {len(expected_kinds)} basins tagged with the correct kind.")

    # 2. /seismic-events feed shape
    print("\nStep 2: /seismic-events returns the seeded raw feed...")
    res = requests.get(f"{SERVER_URL}/seismic-events")
    if res.status_code != 200:
        fail(f"GET /seismic-events returned {res.status_code}")
    body = res.json()
    events = body.get("events")
    regions = body.get("active_regions")
    if not isinstance(events, list) or not events:
        fail("events missing or empty")
    if not isinstance(regions, list) or not regions:
        fail("active_regions missing or empty")
    for e in events:
        if set(e.keys()) != EVENT_KEYS:
            fail(f"Event keys mismatch: {sorted(e.keys())}")
        if e["simulated"] is not False:
            fail(f"Unexpected simulated event before injection: {e['id']}")
        if e["magnitude"] < 4.5:
            fail(f"Event {e['id']} below M4.5: {e['magnitude']}")
    times = [e["time"] for e in events]
    if times != sorted(times, reverse=True):
        fail("Events are not sorted newest first")
    if len(events) > 20:
        fail(f"More than 20 events returned: {len(events)}")
    for r in regions:
        if set(r.keys()) != REGION_KEYS:
            fail(f"Region keys mismatch: {sorted(r.keys())}")
    counts = [r["count"] for r in regions]
    if counts != sorted(counts, reverse=True):
        fail("active_regions not ranked by event count")
    peru = next((r for r in regions if r["region"] == "Peru"), None)
    if not peru or peru["count"] != 2 or abs(peru["max_magnitude"] - 6.1) > 1e-9:
        fail(f"Peru region aggregation wrong: {peru}")
    print(f"Success: {len(events)} real events (newest first) and {len(regions)} active regions.")

    # 3. /seismic-focus on a real seeded event
    print("\nStep 3: /seismic-focus analyzes a seeded event...")
    res = requests.get(f"{SERVER_URL}/seismic-focus", params={"id": "usseed0001"})
    if res.status_code != 200:
        fail(f"GET /seismic-focus returned {res.status_code}")
    focus = res.json()
    event = focus.get("event") or {}
    if event.get("id") != "usseed0001" or event.get("simulated") is not False:
        fail(f"Focus event wrong: {event}")
    # M6.8 at 180 km depth: (6.8/8.0) * 0.85 = 0.72 -> Danger
    if abs(focus["risk_score"] - 0.72) > 1e-9:
        fail(f"risk_score expected 0.72, got {focus['risk_score']}")
    if focus["severity"] != "Danger":
        fail(f"severity expected Danger, got {focus['severity']}")
    if focus["severity"] not in SEVERITIES:
        fail(f"severity outside enum: {focus['severity']}")
    narration = focus.get("narration") or ""
    if "M6.8" not in narration or "Danger" not in narration:
        fail(f"Template narration missing event facts: {narration}")
    print("Success: derived risk 0.72 (Danger) with template narration.")

    # 4. Unknown id -> 404
    print("\nStep 4: /seismic-focus rejects unknown ids...")
    res = requests.get(f"{SERVER_URL}/seismic-focus", params={"id": "no-such-event"})
    if res.status_code != 404:
        fail(f"Expected 404 for unknown id, got {res.status_code}")
    print("Success: unknown event id returns 404.")

    # 5. Injected simulated event appears at the top and is focusable
    print("\nStep 5: demo inject adds a simulated event to the feed...")
    res = requests.post(f"{SERVER_URL}/demo/inject-event", json={
        "basin": "lima_peru",
        "municipality": "Lima",
        "magnitude": 6.5
    })
    if res.status_code != 200:
        fail(f"POST /demo/inject-event returned {res.status_code}: {res.text}")
    sim_id = (res.json().get("event") or {}).get("id") or ""
    if not sim_id.startswith("sim-lima_peru"):
        fail(f"Injected event id unexpected: {sim_id!r}")

    res = requests.get(f"{SERVER_URL}/seismic-events")
    events = res.json()["events"]
    top = events[0]
    if top["id"] != sim_id or top["simulated"] is not True:
        fail(f"Simulated event not at top of feed: {top}")
    if "Lima" not in top["place"]:
        fail(f"Simulated event place missing municipality: {top['place']}")
    if any(e["simulated"] for e in events[1:]):
        fail("More than one simulated event in feed")

    res = requests.get(f"{SERVER_URL}/seismic-focus", params={"id": sim_id})
    if res.status_code != 200:
        fail(f"GET /seismic-focus for simulated event returned {res.status_code}")
    focus = res.json()
    if focus["event"].get("simulated") is not True:
        fail(f"Focused simulated event not tagged simulated: {focus['event']}")
    # M6.5 at 10 km depth: (6.5/8.0) * 1.0 = 0.81 -> Critical
    if abs(focus["risk_score"] - 0.81) > 1e-9 or focus["severity"] != "Critical":
        fail(f"Simulated focus grading wrong: {focus['risk_score']} / {focus['severity']}")
    if "SIMULATED" not in focus["narration"]:
        fail(f"Simulated narration not flagged: {focus['narration']}")
    print("Success: simulated event tops the feed, focusable, tagged simulated.")

    # 6. Clear removes the simulated event everywhere
    print("\nStep 6: demo clear removes the simulated event...")
    res = requests.post(f"{SERVER_URL}/demo/clear-event", json={"basin": "lima_peru"})
    if res.status_code != 200:
        fail(f"POST /demo/clear-event returned {res.status_code}")
    res = requests.get(f"{SERVER_URL}/seismic-events")
    if any(e["simulated"] for e in res.json()["events"]):
        fail("Simulated event still in feed after clear")
    res = requests.get(f"{SERVER_URL}/seismic-focus", params={"id": sim_id})
    if res.status_code != 404:
        fail(f"Cleared simulated event still focusable: {res.status_code}")
    print("Success: feed and focus are clean after clear.")


def main():
    kill_port()
    print("Starting FastAPI server locally in TESTING mode...")
    python_exe = os.path.join(".venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = "python"

    server_log = open("server_seismic_events.log", "w", encoding="utf-8")
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
        print("            SEISMIC EVENTS SUITE COMPLETED: SUCCESS                  ")
        print("=====================================================================")
    finally:
        server_process.terminate()
        server_process.wait()
        server_log.close()


if __name__ == "__main__":
    main()
