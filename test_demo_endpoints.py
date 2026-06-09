import os
import subprocess
import sys
import time

import requests

PORT = 8001
SERVER_URL = f"http://127.0.0.1:{PORT}"

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

LIVE_EVENT_KEYS = {"municipality", "magnitude", "place", "time", "depth_km", "latitude", "longitude", "simulated"}

def run_tests():
    print("\nStep 1: /live-seismic returns real rows (or empty) for all basins...")
    for basin in ["rio_cauca", "rio_magdalena", "lima_peru", "guatemala_city",
                  "santiago_chile", "mexico_city", "port_au_prince"]:
        res = requests.get(f"{SERVER_URL}/live-seismic", params={"basin": basin}, timeout=30)
        if res.status_code != 200:
            fail(f"/live-seismic for {basin} returned {res.status_code}: {res.text}")
        events = res.json()
        if not isinstance(events, list):
            fail(f"/live-seismic for {basin} did not return a list: {events}")
        for e in events:
            if set(e.keys()) != LIVE_EVENT_KEYS:
                fail(f"/live-seismic event keys mismatch for {basin}: {e}")
            if e["simulated"] is not False:
                fail(f"/live-seismic event not tagged simulated=false for {basin}: {e}")
        times = [e["time"] for e in events]
        if times != sorted(times, reverse=True):
            fail(f"/live-seismic events not newest-first for {basin}: {times}")
        print(f"  {basin}: {len(events)} real events, schema and ordering OK")
    print("Success: /live-seismic works for all basins.")

    print("\nStep 2: /live-seismic rejects unknown basin...")
    res = requests.get(f"{SERVER_URL}/live-seismic", params={"basin": "atlantis"})
    if res.status_code != 404:
        fail(f"Expected 404 for unknown basin, got {res.status_code}")
    print("Success: unknown basin returns 404.")

    print("\nStep 3: snapshot baseline /risk and /alert (no demo event active)...")
    baseline_risk = requests.get(f"{SERVER_URL}/risk", params={"basin": "rio_cauca"}).json()
    baseline_alert = requests.get(f"{SERVER_URL}/alert", params={"basin": "rio_cauca"}).json()
    if any(r.get("simulated") for r in baseline_risk):
        fail(f"Baseline risk rows already tagged simulated: {baseline_risk}")
    print("Success: baseline captured, no simulated rows.")

    print("\nStep 4: inject simulated event (rio_cauca, Cali, M6.5)...")
    res = requests.post(f"{SERVER_URL}/demo/inject-event",
                        json={"basin": "rio_cauca", "municipality": "Cali", "magnitude": 6.5})
    if res.status_code != 200:
        fail(f"inject-event failed: {res.status_code} {res.text}")
    if res.json()["event"]["simulated"] is not True:
        fail(f"inject-event response not tagged simulated: {res.json()}")
    time.sleep(0.5)

    risk = requests.get(f"{SERVER_URL}/risk", params={"basin": "rio_cauca"}).json()
    cali = next((r for r in risk if r["municipality"] == "Cali"), None)
    if cali is None:
        fail("Cali missing from risk data after inject")
    if cali["earthquake_magnitude"] != 6.5:
        fail(f"Cali earthquake_magnitude is {cali['earthquake_magnitude']}, expected 6.5")
    if cali["seismic_score"] != 0.93:
        fail(f"Cali seismic_score is {cali['seismic_score']}, expected 0.93")
    if cali["risk_score"] != 0.7:
        fail(f"Cali risk_score is {cali['risk_score']}, expected 0.7")
    if cali["dominant_hazard"] != "SEISMIC":
        fail(f"Cali dominant_hazard is {cali['dominant_hazard']}, expected SEISMIC")
    if cali.get("simulated") is not True:
        fail(f"Merged Cali row not tagged simulated: {cali}")
    baseline_cali = next(r for r in baseline_risk if r["municipality"] == "Cali")
    if cali["risk_score"] <= baseline_cali["risk_score"]:
        fail(f"Cali risk did not spike: {baseline_cali['risk_score']} -> {cali['risk_score']}")
    for r in risk:
        if r["municipality"] == "Cali":
            continue
        baseline_row = next(b for b in baseline_risk if b["municipality"] == r["municipality"])
        if r != baseline_row:
            fail(f"Non-injected municipality changed: {r} vs {baseline_row}")
    print("Success: Cali spiked (0.42 -> 0.7, SEISMIC, simulated), other rows unchanged.")

    print("\nStep 5: /alert reflects the simulated event...")
    alert = requests.get(f"{SERVER_URL}/alert", params={"basin": "rio_cauca"}).json()
    cali_alert = next((a for a in alert["graded_alert"] if a["municipality"] == "Cali"), None)
    if cali_alert is None or cali_alert["risk_score"] != 0.7 or cali_alert["severity"] != "HIGH":
        fail(f"Cali alert grading wrong: {cali_alert}")
    if "Cali" not in alert["agency_incident"]["affected_municipalities"]:
        fail(f"Cali missing from affected municipalities: {alert['agency_incident']}")
    print("Success: /alert grades Cali HIGH and lists it as affected.")

    print("\nStep 6: /incidents has a clearly simulated entry...")
    incidents = requests.get(f"{SERVER_URL}/incidents").json()
    sim_incidents = [i for i in incidents if i.get("simulated") and i.get("basin") == "rio_cauca"]
    if not sim_incidents:
        fail(f"No simulated incident logged: {incidents}")
    if "SIMULATED" not in sim_incidents[0]["details"]:
        fail(f"Simulated incident not clearly labeled: {sim_incidents[0]['details']}")
    print("Success: simulated incident logged and labeled.")

    print("\nStep 7: /live-seismic never shows the injected event...")
    live = requests.get(f"{SERVER_URL}/live-seismic", params={"basin": "rio_cauca"}, timeout=30).json()
    if any(e["simulated"] for e in live):
        fail(f"/live-seismic leaked a simulated event: {live}")
    print("Success: /live-seismic stays real-data only.")

    print("\nStep 8: clear-event resets /risk, /alert and /incidents...")
    res = requests.post(f"{SERVER_URL}/demo/clear-event", json={"basin": "rio_cauca"})
    if res.status_code != 200:
        fail(f"clear-event failed: {res.status_code} {res.text}")
    time.sleep(0.5)
    risk_after = requests.get(f"{SERVER_URL}/risk", params={"basin": "rio_cauca"}).json()
    if risk_after != baseline_risk:
        fail(f"Risk did not reset to baseline after clear: {risk_after}")
    alert_after = requests.get(f"{SERVER_URL}/alert", params={"basin": "rio_cauca"}).json()
    if alert_after["graded_alert"] != baseline_alert["graded_alert"]:
        fail(f"Alert grading did not reset after clear: {alert_after['graded_alert']}")
    incidents_after = requests.get(f"{SERVER_URL}/incidents").json()
    if any(i.get("simulated") and i.get("basin") == "rio_cauca" for i in incidents_after):
        fail(f"Simulated incidents remain after clear: {incidents_after}")
    print("Success: everything back to baseline after clear.")

    print("\nStep 9: inject/clear on every seismic-only basin...")
    seismic_only = [
        ("lima_peru", "Lima"),
        ("guatemala_city", "Guatemala City"),
        ("santiago_chile", "Santiago"),
        ("mexico_city", "Mexico City"),
        ("port_au_prince", "Port-au-Prince")
    ]
    for basin_id, muni in seismic_only:
        baseline = requests.get(f"{SERVER_URL}/risk", params={"basin": basin_id}).json()
        res = requests.post(f"{SERVER_URL}/demo/inject-event",
                            json={"basin": basin_id, "municipality": muni, "magnitude": 7.0})
        if res.status_code != 200:
            fail(f"inject-event for {basin_id} failed: {res.status_code} {res.text}")
        time.sleep(0.5)
        basin_risk = requests.get(f"{SERVER_URL}/risk", params={"basin": basin_id}).json()
        row = next(r for r in basin_risk if r["municipality"] == muni)
        if row["seismic_score"] != 1.0 or row["risk_score"] != 1.0:
            fail(f"{basin_id} seismic-only spike wrong: {row}")
        if row.get("simulated") is not True or row["dominant_hazard"] != "SEISMIC":
            fail(f"{basin_id} merged row wrong: {row}")
        requests.post(f"{SERVER_URL}/demo/clear-event", json={"basin": basin_id})
        time.sleep(0.5)
        if requests.get(f"{SERVER_URL}/risk", params={"basin": basin_id}).json() != baseline:
            fail(f"{basin_id} risk did not reset after clear")
        print(f"  {basin_id}: {muni} spiked to EXTREME and reset")
    print("Success: every seismic-only basin spikes and resets.")

    print("\nStep 10: validation errors...")
    res = requests.post(f"{SERVER_URL}/demo/inject-event",
                        json={"basin": "atlantis", "municipality": "Cali", "magnitude": 6.0})
    if res.status_code != 404:
        fail(f"Expected 404 for unknown basin, got {res.status_code}")
    res = requests.post(f"{SERVER_URL}/demo/inject-event",
                        json={"basin": "rio_cauca", "municipality": "Lima", "magnitude": 6.0})
    if res.status_code != 400:
        fail(f"Expected 400 for municipality outside basin, got {res.status_code}")
    res = requests.post(f"{SERVER_URL}/demo/clear-event", json={"basin": "atlantis"})
    if res.status_code != 404:
        fail(f"Expected 404 for clear on unknown basin, got {res.status_code}")
    print("Success: validation errors returned as expected.")

def main():
    print("=====================================================================")
    print("                 DEMO ENDPOINTS TEST SUITE (TESTING mode)            ")
    print("=====================================================================")
    kill_port()
    server_log = open("server_demo_test.log", "w", encoding="utf-8")
    server_process = subprocess.Popen(
        [sys.executable, "-u", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", str(PORT)],
        stdout=server_log,
        stderr=server_log,
        env={**os.environ, "TESTING": "true"}
    )
    try:
        if not wait_for_server():
            fail("FastAPI server failed to start on test port.")
        run_tests()
        print("\n=====================================================================")
        print("              DEMO ENDPOINTS SUITE COMPLETED: SUCCESS                ")
        print("=====================================================================")
    finally:
        server_process.terminate()
        server_process.wait()
        server_log.close()

if __name__ == "__main__":
    main()
