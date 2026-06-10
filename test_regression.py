import os
import sys
import time
import subprocess
import requests
import threading

def kill_port_8000():
    try:
        # Find and kill any process on port 8000 on Windows
        output = subprocess.check_output("netstat -ano | findstr :8000", shell=True).decode()
        for line in output.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 5 and parts[1].endswith(":8000"):
                pid = parts[-1]
                print(f"Killing process {pid} on port 8000...")
                subprocess.run(f"taskkill /F /PID {pid}", shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(0.5)
    except Exception:
        pass

def wait_for_server(url: str, timeout: int = 5):
    """Wait for the local server to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            res = requests.get(f"{url}/risk", timeout=2)
            if res.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False

def run_test_logic(server_url):
    print("\nStep 1: Setting up mock database state to populated...")
    res_set = requests.post(f"{server_url}/test/set-db-state", json={"populated": True})
    if res_set.status_code != 200:
        print(f"ERROR: Failed to set mock db state: {res_set.text}")
        sys.exit(1)
    print("Success: Mock DB state initialized.")

    # 3. Risk: Query GET /risk
    print("\nStep 2: Checking GET /risk...")
    res_risk = requests.get(f"{server_url}/risk")
    if res_risk.status_code != 200:
        print(f"ERROR: GET /risk failed with status code {res_risk.status_code}")
        sys.exit(1)
        
    risk_data = res_risk.json()
    print(f"Success: GET /risk returned {len(risk_data)} municipalities:")
    for r in risk_data:
        print(f"  - {r['municipality']}: index={r['risk_score']}, rain={r['rainfall_mm']}mm, discharge={r.get('discharge_m3s')}m3/s, soil={r.get('soil_moisture')}")

    # 4. Alert: Query GET /alert
    print("\nStep 3: Checking GET /alert (Gemini-narrated/mocked)...")
    res_alert = requests.get(f"{server_url}/alert")
    if res_alert.status_code != 200:
        print(f"ERROR: GET /alert failed with status code {res_alert.status_code}, response: {res_alert.text}")
        sys.exit(1)
        
    alert_data = res_alert.json()
    print("Success: GET /alert data returned:")
    print(f"  Incident Summary: {alert_data['agency_incident']['summary'][:120]}...")
    print(f"  Broadcast: {alert_data['resident_broadcast'][:120]}...")
    
    # Verify numbers match /risk
    for alert in alert_data['graded_alert']:
        matching_risk = next((x for x in risk_data if x['municipality'] == alert['municipality']), None)
        if not matching_risk:
            print(f"ERROR: Alert municipality {alert['municipality']} not found in risk data!")
            sys.exit(1)
        if matching_risk['risk_score'] != alert['risk_score']:
            print(f"ERROR: Alert risk score ({alert['risk_score']}) does not match risk data score ({matching_risk['risk_score']})!")
            sys.exit(1)
    print("Success: Graded alerts match risk scores exactly.")

    # 5. Break: POST /break
    print("\nStep 4: Breaking the pipeline (POST /break)...")
    res_break = requests.post(f"{server_url}/break")
    if res_break.status_code != 200:
        print(f"ERROR: POST /break failed with status code {res_break.status_code}, response: {res_break.text}")
        sys.exit(1)
        
    print("Success: Outage simulation initiated.")
    
    # Verify status is paused
    res_status = requests.get(f"{server_url}/connector-status")
    status_data = res_status.json()
    if status_data['status'] != 'paused':
        print(f"ERROR: Connector status is {status_data['status']}, expected 'paused'!")
        sys.exit(1)
    print("Success: Connector status confirmed as 'paused'.")

    # 6. Heal: POST /heal
    print("\nStep 5: Healing the pipeline (POST /heal)...")
    res_heal = requests.post(f"{server_url}/heal")
    if res_heal.status_code != 200:
        print(f"ERROR: POST /heal failed with status code {res_heal.status_code}, response: {res_heal.text}")
        sys.exit(1)
        
    print("Success: Heal flow executed.")
    
    # Verify status is active again
    res_status = requests.get(f"{server_url}/connector-status")
    status_data = res_status.json()
    if status_data['status'] != 'active':
        print(f"ERROR: Connector status is {status_data['status']}, expected 'active' after heal!")
        sys.exit(1)
    print(f"Success: Connector is active and fresh (last sync: {status_data['last_sync_time']}).")

    # 7. Enable Alerts UI check: Fetch index.html and verify elements exist
    print("\nStep 6: Verifying Firebase Enable Alerts UI elements exist...")
    res_ui = requests.get(server_url)
    if res_ui.status_code != 200:
        print(f"ERROR: GET / (UI) failed with status code {res_ui.status_code}")
        sys.exit(1)
        
    ui_html = res_ui.text
    required_elements = [
        'id="enable-notifications-btn"',
        'id="token-display-box"',
        'id="notification-token"',
        'id="copy-token-btn"'
    ]
    for elem in required_elements:
        if elem not in ui_html:
            print(f"ERROR: Required UI element '{elem}' not found in index.html!")
            sys.exit(1)
    print("Success: Firebase Enable Alerts UI elements verified in index.html.")

    # 8. Run JS DOM and handler execution check
    print("\nStep 7: Verifying click handler in app.js via Node.js mock execution...")
    js_verifier = """
const mockElements = {};
const clickListeners = {};

global.window = {
  location: { origin: 'http://127.0.0.1:8000' }
};

global.navigator = {
  clipboard: {
    writeText: async (txt) => {
      console.log('Clipboard wrote:', txt);
    }
  }
};

global.Notification = {
  requestPermission: async () => 'granted'
};

global.firebase = {
  initializeApp: () => ({}),
  messaging: () => ({
    getToken: async () => 'mock-fcm-token',
    onMessage: () => {}
  })
};

global.fetch = async (url, options) => {
  if (url.includes('/risk')) {
    return { ok: true, json: async () => [] };
  }
  if (url.includes('/connector-status')) {
    return { ok: true, json: async () => ({ status: 'active', connectors: [] }) };
  }
  if (url.includes('/alert')) {
    return { ok: true, json: async () => ({ graded_alert: [], agency_incident: { affected_municipalities: [] }, resident_broadcast: '' }) };
  }
  if (url.includes('/autonomous-heals')) {
    return { ok: true, json: async () => [] };
  }
  if (url.includes('/incidents')) {
    return { ok: true, json: async () => [] };
  }
  return {
    ok: true,
    json: async () => ({ status: 'Success' })
  };
};

global.document = {
  addEventListener: (event, cb) => {
    if (event === 'DOMContentLoaded') {
      setTimeout(cb, 0);
    }
  },
  getElementById: (id) => {
    if (!mockElements[id]) {
      mockElements[id] = {
        id: id,
        classList: {
          remove: (cls) => {},
          add: (cls) => {}
        },
        className: { baseVal: '' },
        addEventListener: (event, cb) => {
          if (event === 'click') {
            clickListeners[id] = cb;
          }
        },
        style: { width: '0%' },
        textContent: '',
        innerHTML: '',
        appendChild: () => {}
      };
    }
    return mockElements[id];
  },
  createElement: (tag) => ({
    setAttribute: () => {},
    appendChild: () => {},
    classList: { add: () => {}, remove: () => {} },
    style: {},
    addEventListener: () => {},
    scrollTop: 0,
    scrollHeight: 100
  }),
  createElementNS: (ns, tag) => ({
    setAttribute: () => {},
    appendChild: () => {},
    classList: { add: () => {}, remove: () => {} },
    style: { animation: '' },
    addEventListener: () => {},
    scrollTop: 0,
    scrollHeight: 100
  })
};

global.setInterval = (cb, ms) => {
  return 1;
};

const fs = require('fs');
const code = fs.readFileSync('web/app.js', 'utf8');
eval(code);

setTimeout(async () => {
  const clickHandler = clickListeners['enable-notifications-btn'];
  if (!clickHandler) {
    console.error('ERROR: Click listener on enable-notifications-btn not registered');
    process.exit(1);
  }
  
  try {
    await clickHandler();
    process.exit(0);
  } catch (err) {
    console.error('ERROR: Click handler threw error:', err);
    process.exit(1);
  }
}, 50);
"""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False) as f:
        f.write(js_verifier)
        temp_name = f.name
        
    try:
        res_js = subprocess.run(["node", temp_name], capture_output=True, text=True)
        if res_js.returncode != 0:
            print(f"ERROR: JS click handler execution check failed!\nSTDERR: {res_js.stderr}\nSTDOUT: {res_js.stdout}")
            sys.exit(1)
        print("Success: JS click handler runs with no console error.")
    finally:
        if os.path.exists(temp_name):
            os.remove(temp_name)

    # 9. Verify FCM push notifications state transition and cooldown
    print("\nStep 8: Verifying FCM push notifications, state transition, and cooldown...")
    
    # Clear push history
    requests.post(f"{server_url}/test/clear-sent-pushes")
    
    # Register token - triggers a transition check as background task
    requests.post(f"{server_url}/register-token", json={"token": "mock-fcm-token-test-1"})
    time.sleep(0.5)  # Wait briefly for background task to run
    
    # Verify first push is sent
    history = requests.get(f"{server_url}/test/sent-pushes").json()
    if len(history) != 1:
        print(f"ERROR: Expected exactly 1 push after registration, got {len(history)}")
        sys.exit(1)
    print("Success: First push notification sent on initial registration transition.")
    
    # Steady-state polling of /alert should send nothing
    requests.get(f"{server_url}/alert")
    requests.get(f"{server_url}/alert")
    history = requests.get(f"{server_url}/test/sent-pushes").json()
    if len(history) != 1:
        print(f"ERROR: Steady-state polling of /alert sent extra pushes! Count: {len(history)}")
        sys.exit(1)
    print("Success: Steady-state polling of /alert sends no pushes.")
    
    # Manual check-alerts in steady state should send nothing
    requests.post(f"{server_url}/check-alerts")
    time.sleep(0.5)
    history = requests.get(f"{server_url}/test/sent-pushes").json()
    if len(history) != 1:
        print(f"ERROR: Steady-state /check-alerts sent extra pushes! Count: {len(history)}")
        sys.exit(1)
    print("Success: Steady-state manual check-alerts sends no pushes.")
    
    # Clear data to transition state to healthy (empty alerts)
    print("Transitioning basin to healthy state (setting mock db state)...")
    requests.post(f"{server_url}/test/set-db-state", json={"populated": False})
    
    # Trigger check-alerts - transitions to empty state, should not send a push
    requests.post(f"{server_url}/check-alerts")
    time.sleep(0.5)
    history = requests.get(f"{server_url}/test/sent-pushes").json()
    if len(history) != 1:
        print(f"ERROR: Transition to healthy state sent an extra push! Count: {len(history)}")
        sys.exit(1)
    print("Success: Transition to healthy state sends no pushes.")
    
    # Populate data again to transition back to active alert
    print("Reloading storm data to transition back to active alert...")
    requests.post(f"{server_url}/test/set-db-state", json={"populated": True})
    
    # Trigger check-alerts - transitions to active alert, should attempt a new push
    requests.post(f"{server_url}/check-alerts")
    time.sleep(0.5)
    history = requests.get(f"{server_url}/test/sent-pushes").json()
    if len(history) != 2:
        print(f"ERROR: Transition to active alert should have triggered a second push, got: {len(history)}")
        sys.exit(1)
    print("Success: Second push notification sent on active alert transition.")
    
    # Trigger check-alerts again immediately - should hit cooldown and not send a third push
    print("Triggering check-alerts again to verify 10-minute cooldown...")
    requests.post(f"{server_url}/check-alerts")
    time.sleep(0.5)
    history = requests.get(f"{server_url}/test/sent-pushes").json()
    if len(history) != 2:
        print(f"ERROR: Cooldown check failed! Cooldown should have blocked the third push, got: {len(history)}")
        sys.exit(1)
    print("Success: Cooldown prevents duplicate notifications within window.")

    # 10. Verify Autonomous Self-Heal
    print("\nStep 9: Verifying Autonomous Self-Heal...")
    # Clear autonomous heals log
    requests.post(f"{server_url}/test/clear-autonomous-heals")
    
    # Break the first connector
    requests.post(f"{server_url}/break")
    
    # Verify status is paused
    status_data = requests.get(f"{server_url}/connector-status").json()
    if status_data['status'] != 'paused':
        print("ERROR: Connector status did not change to paused during auto-heal test!")
        sys.exit(1)
        
    # Trigger /check-alerts (which now runs autonomous heal)
    requests.post(f"{server_url}/check-alerts")
    time.sleep(0.5)  # Wait for background task
    
    # Verify status is active again
    status_data = requests.get(f"{server_url}/connector-status").json()
    if status_data['status'] != 'active':
        print(f"ERROR: Connector status is {status_data['status']}, expected active after auto-heal!")
        sys.exit(1)
        
    # Verify autonomous heals history log is recorded
    heals = requests.get(f"{server_url}/autonomous-heals").json()
    if len(heals) != 1:
        print(f"ERROR: Expected exactly 1 autonomous heal log, got {len(heals)}")
        sys.exit(1)
    if heals[0]["connector_id"] != "kung_gleeful":
        print(f"ERROR: Unexpected autonomous heal entry: {heals[0]}")
        sys.exit(1)
    if "autonomous, no human action" not in heals[0]["message"]:
        print(f"ERROR: Missing autonomous label in heal entry: {heals[0]}")
        sys.exit(1)
    print("Success: Autonomous self-heal verified.")

    # 11. Verify Persistent Memory & Multi-Basin
    print("\nStep 10: Verifying Persistent Memory, Incident Log & Multi-Basin...")
    # Clear incidents
    requests.post(f"{server_url}/test/clear-incidents")
    
    # Break a connector to trigger an incident log
    requests.post(f"{server_url}/break", params={"connector_id": "plausibly_illustrate", "basin": "rio_cauca"})
    
    # Check incidents log has been updated
    incidents = requests.get(f"{server_url}/incidents").json()
    if len(incidents) < 1:
        print(f"ERROR: Expected at least 1 incident log in history, got {len(incidents)}")
        sys.exit(1)
        
    incident_id = incidents[0]["id"]
    print(f"Success: Incident logged with ID: {incident_id}")
    
    # Reopen incident
    reopen_res = requests.post(f"{server_url}/incidents/{incident_id}/reopen")
    if reopen_res.status_code != 200:
        print(f"ERROR: Failed to reopen incident {incident_id}: {reopen_res.text}")
        sys.exit(1)
        
    # Verify risk override is active
    risk_override = requests.get(f"{server_url}/risk").json()
    if not any(r["municipality"] == "Cali" for r in risk_override):
        print(f"ERROR: Override risk data does not contain expected municipalities: {risk_override}")
        sys.exit(1)
        
    # Verify alert override is active
    alert_override = requests.get(f"{server_url}/alert").json()
    if "REOPENED HISTORICAL INCIDENT" not in alert_override["agency_incident"]["title"]:
        print(f"ERROR: Reopened alert title did not match override: {alert_override['agency_incident']['title']}")
        sys.exit(1)
    print("Success: Incident reopen overrides verified.")
    
    # Clear reopen override
    clear_res = requests.post(f"{server_url}/incidents/clear-reopen")
    if clear_res.status_code != 200:
        print(f"ERROR: Failed to clear reopen override: {clear_res.text}")
        sys.exit(1)
        
    # Verify risk returned to live
    risk_live = requests.get(f"{server_url}/risk").json()
    alert_live = requests.get(f"{server_url}/alert").json()
    if "REOPENED" in alert_live["agency_incident"]["title"]:
        print("ERROR: Override alert title still active after clear-reopen!")
        sys.exit(1)
    print("Success: Returned to live view successfully.")
    
    # Check second basin (Rio Magdalena) mock data
    magdalena_risk = requests.get(f"{server_url}/risk", params={"basin": "rio_magdalena"}).json()
    if not any(r["municipality"] == "Neiva" for r in magdalena_risk):
        print(f"ERROR: Rio Magdalena risk data did not return expected municipalities: {magdalena_risk}")
        sys.exit(1)
    print("Success: Multi-basin (Rio Magdalena) risk score checked.")

    # 12. Verify new seismic-only basin (Lima, Peru)
    print("\nStep 11: Verifying seismic-only basin (Lima, Peru)...")

    # /basins should expose lima_peru from config automatically
    basins = requests.get(f"{server_url}/basins").json()
    if not any(b["id"] == "lima_peru" for b in basins):
        print(f"ERROR: /basins did not include lima_peru from config: {basins}")
        sys.exit(1)
    print("Success: /basins exposes lima_peru from config.")

    # /risk for Lima: the registry anchor place, real model-index rows
    lima_risk = requests.get(f"{server_url}/risk", params={"basin": "lima_peru"}).json()
    expected_munis = {"Lima"}
    returned_munis = {r["municipality"] for r in lima_risk}
    if returned_munis != expected_munis:
        print(f"ERROR: Lima risk municipalities mismatch. Expected {expected_munis}, got {returned_munis}")
        sys.exit(1)
    for r in lima_risk:
        if r.get("provenance") != "centinela-model-index":
            print(f"ERROR: {r['municipality']} missing model-index provenance: {r}")
            sys.exit(1)
        if r["dominant_hazard"] not in ("FLOOD", "LANDSLIDE", "SEISMIC"):
            print(f"ERROR: {r['municipality']} dominant_hazard invalid: {r['dominant_hazard']}")
            sys.exit(1)
        # Seeded-era fields must be gone entirely.
        for dead in ("river_level_m", "threshold", "soil_saturation", "slope_angle_deg", "susceptibility_index"):
            if dead in r:
                print(f"ERROR: seeded-era field {dead} still present: {r}")
                sys.exit(1)
        if not (0.0 <= r["risk_score"] <= 1.0):
            print(f"ERROR: {r['municipality']} index out of range: {r['risk_score']}")
            sys.exit(1)
    print("Success: Lima serves real model-index rows with no seeded-era fields.")

    # /connector-status for Lima: USGS seismic connector only
    lima_status = requests.get(f"{server_url}/connector-status", params={"basin": "lima_peru"}).json()
    lima_connectors = lima_status.get("connectors", [])
    if not any(c["connector_id"] == "kung_gleeful" for c in lima_connectors):
        print(f"ERROR: Lima connector-status missing the USGS raw events connector: {lima_connectors}")
        sys.exit(1)
    print("Success: Lima connector-status returns the USGS seismic feed.")

    # /alert for Lima: graded alerts match risk scores
    lima_alert = requests.get(f"{server_url}/alert", params={"basin": "lima_peru"}).json()
    for alert in lima_alert["graded_alert"]:
        matching = next((x for x in lima_risk if x["municipality"] == alert["municipality"]), None)
        if not matching or matching["risk_score"] != alert["risk_score"]:
            print(f"ERROR: Lima alert score mismatch for {alert['municipality']}")
            sys.exit(1)
    print("Success: Lima /alert graded alerts match risk scores.")

    # /incidents must still respond for the Lima basin
    lima_incidents = requests.get(f"{server_url}/incidents", params={"basin": "lima_peru"})
    if lima_incidents.status_code != 200:
        print(f"ERROR: /incidents failed for lima_peru with status {lima_incidents.status_code}")
        sys.exit(1)
    print("Success: /incidents responds for lima_peru.")

    # 13. Verify second seismic-only basin (Guatemala City)
    print("\nStep 12: Verifying seismic-only basin (Guatemala City)...")

    # /basins should expose guatemala_city from config automatically
    basins_gt = requests.get(f"{server_url}/basins").json()
    if not any(b["id"] == "guatemala_city" for b in basins_gt):
        print(f"ERROR: /basins did not include guatemala_city from config: {basins_gt}")
        sys.exit(1)
    print("Success: /basins exposes guatemala_city from config.")

    # /risk for Guatemala City: the registry anchor place, real model-index rows
    gt_risk = requests.get(f"{server_url}/risk", params={"basin": "guatemala_city"}).json()
    expected_gt = {"Guatemala City"}
    returned_gt = {r["municipality"] for r in gt_risk}
    if returned_gt != expected_gt:
        print(f"ERROR: Guatemala City risk municipalities mismatch. Expected {expected_gt}, got {returned_gt}")
        sys.exit(1)
    for r in gt_risk:
        if r.get("provenance") != "centinela-model-index":
            print(f"ERROR: {r['municipality']} missing model-index provenance: {r}")
            sys.exit(1)
        for dead in ("river_level_m", "threshold", "soil_saturation"):
            if dead in r:
                print(f"ERROR: seeded-era field {dead} still present: {r}")
                sys.exit(1)
    print("Success: Guatemala City serves real model-index rows with no seeded-era fields.")

    # /connector-status for Guatemala City: USGS seismic connector only
    gt_status = requests.get(f"{server_url}/connector-status", params={"basin": "guatemala_city"}).json()
    gt_connectors = gt_status.get("connectors", [])
    if not any(c["connector_id"] == "kung_gleeful" for c in gt_connectors):
        print(f"ERROR: Guatemala City connector-status missing the USGS raw events connector: {gt_connectors}")
        sys.exit(1)
    print("Success: Guatemala City connector-status returns the USGS seismic feed.")

    # /alert for Guatemala City: graded alerts match risk scores
    gt_alert = requests.get(f"{server_url}/alert", params={"basin": "guatemala_city"}).json()
    for alert in gt_alert["graded_alert"]:
        matching = next((x for x in gt_risk if x["municipality"] == alert["municipality"]), None)
        if not matching or matching["risk_score"] != alert["risk_score"]:
            print(f"ERROR: Guatemala City alert score mismatch for {alert['municipality']}")
            sys.exit(1)
    print("Success: Guatemala City /alert graded alerts match risk scores.")

    # /incidents must still respond for the Guatemala City basin
    gt_incidents = requests.get(f"{server_url}/incidents", params={"basin": "guatemala_city"})
    if gt_incidents.status_code != 200:
        print(f"ERROR: /incidents failed for guatemala_city with status {gt_incidents.status_code}")
        sys.exit(1)
    print("Success: /incidents responds for guatemala_city.")

    # 14. Verify the portfolio seismic-only basins (Santiago, Mexico City, Port-au-Prince)
    print("\nStep 13: Verifying seismic-only basins (Santiago, Mexico City, Port-au-Prince)...")
    new_seismic_basins = {
        "santiago_chile": {"Santiago"},
        "mexico_city": {"Mexico City"},
        "port_au_prince": {"Port-au-Prince"}
    }
    for basin_id, expected in new_seismic_basins.items():
        # /basins should expose the basin from config automatically
        basins_list = requests.get(f"{server_url}/basins").json()
        if not any(b["id"] == basin_id for b in basins_list):
            print(f"ERROR: /basins did not include {basin_id} from config: {basins_list}")
            sys.exit(1)

        # /risk: three real municipalities, seismic-dominant, flood/landslide as no-data
        basin_risk = requests.get(f"{server_url}/risk", params={"basin": basin_id}).json()
        returned = {r["municipality"] for r in basin_risk}
        if returned != expected:
            print(f"ERROR: {basin_id} risk municipalities mismatch. Expected {expected}, got {returned}")
            sys.exit(1)
        for r in basin_risk:
            if r.get("provenance") != "centinela-model-index":
                print(f"ERROR: {r['municipality']} missing model-index provenance: {r}")
                sys.exit(1)
            if "river_level_m" in r or "soil_saturation" in r:
                print(f"ERROR: seeded-era fields still present: {r}")
                sys.exit(1)

        # /connector-status: USGS seismic connector only
        basin_status = requests.get(f"{server_url}/connector-status", params={"basin": basin_id}).json()
        if not any(c["connector_id"] == "kung_gleeful" for c in basin_status.get("connectors", [])):
            print(f"ERROR: {basin_id} connector-status missing the USGS seismic connector: {basin_status}")
            sys.exit(1)

        # /alert: graded alerts match risk scores
        basin_alert = requests.get(f"{server_url}/alert", params={"basin": basin_id}).json()
        for alert in basin_alert["graded_alert"]:
            matching = next((x for x in basin_risk if x["municipality"] == alert["municipality"]), None)
            if not matching or matching["risk_score"] != alert["risk_score"]:
                print(f"ERROR: {basin_id} alert score mismatch for {alert['municipality']}")
                sys.exit(1)

        # /incidents must still respond for the basin
        basin_incidents = requests.get(f"{server_url}/incidents", params={"basin": basin_id})
        if basin_incidents.status_code != 200:
            print(f"ERROR: /incidents failed for {basin_id} with status {basin_incidents.status_code}")
            sys.exit(1)
        print(f"Success: {basin_id} verified (basins, risk, connector-status, alert, incidents).")

    # 15. Candidate watchlist (read-only, deterministic fixture under TESTING)
    print("\nStep 14: Verifying GET /watchlist (candidate watchlist)...")
    from datetime import date as _date
    res_watch = requests.get(f"{server_url}/watchlist")
    if res_watch.status_code != 200:
        print(f"ERROR: GET /watchlist failed with status {res_watch.status_code}")
        sys.exit(1)
    watch = res_watch.json()
    if watch.get("status") != "ok":
        print(f"ERROR: watchlist status is {watch.get('status')}, expected 'ok' under TESTING")
        sys.exit(1)
    if not watch.get("computed_at"):
        print(f"ERROR: watchlist computed_at missing: {watch.get('computed_at')}")
        sys.exit(1)
    rows = watch.get("results", [])
    if len(rows) != 12:
        print(f"ERROR: watchlist expected 12 candidates, got {len(rows)}")
        sys.exit(1)
    scores = [r["activity_score"] for r in rows]
    if scores != sorted(scores, reverse=True):
        print(f"ERROR: watchlist not sorted by activity_score desc: {scores}")
        sys.exit(1)
    required = ["name", "country", "lat", "lng", "aqi_covered", "cell_scale",
                "activity_score", "seismic_score", "flood_score",
                "quake_90d_count", "days_above_seasonal_p90_last60"]
    for r in rows:
        missing = [k for k in required if k not in r]
        if missing:
            print(f"ERROR: watchlist row {r.get('name')} missing fields: {missing}")
            sys.exit(1)
    if sum(1 for r in rows if r["aqi_covered"]) != 6:
        print(f"ERROR: watchlist expected exactly 6 AQI-covered candidates")
        sys.exit(1)
    manaus = next((r for r in rows if r["name"] == "Manaus"), None)
    if not manaus or manaus["lat"] != -3.18 or manaus["lng"] != -60.03:
        print(f"ERROR: Manaus must use the river cell (-3.18, -60.03), got {manaus}")
        sys.exit(1)
    months = watch.get("season_months", [])
    if len(months) != 3 or _date.today().month not in months:
        print(f"ERROR: season_months invalid or missing current month: {months}")
        sys.exit(1)
    res_watch2 = requests.get(f"{server_url}/watchlist")
    if res_watch2.json().get("results") != rows:
        print("ERROR: watchlist TESTING fixture is not deterministic across calls")
        sys.exit(1)
    print(f"Success: /watchlist returned 12 ranked candidates (top: {rows[0]['name']}), deterministic fixture verified.")

def run_regression():
    print("=====================================================================")
    print("                    STARTING REGRESSION SUITE                        ")
    print("=====================================================================")
    
    kill_port_8000()
    server_url = "http://127.0.0.1:8000"
    server_process = None
    
    print("Starting FastAPI server locally in TESTING mode...")
    python_exe = os.path.join(".venv", "Scripts", "python.exe")
    if not os.path.exists(python_exe):
        python_exe = "python"
    
    server_log = open("server.log", "w", encoding="utf-8")
    server_process = subprocess.Popen(
        [python_exe, "-u", "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"],
        stdout=server_log,
        stderr=server_log,
        env={**os.environ, "TESTING": "true"}
    )
    
    if not wait_for_server(server_url):
        print("ERROR: FastAPI server failed to start.")
        if server_process:
            server_process.terminate()
        sys.exit(1)
    print("FastAPI server started successfully.")

    success = False
    def thread_target():
        nonlocal success
        try:
            run_test_logic(server_url)
            success = True
        except Exception as e:
            print(f"ERROR in test execution: {e}")
            import traceback
            traceback.print_exc()

    t = threading.Thread(target=thread_target)
    t.daemon = True
    t.start()
    t.join(timeout=25.0)

    if t.is_alive():
        print("ERROR: Test suite timed out after 25 seconds (hard overall timeout).")
        success = False

    if server_process:
        print("\nShutting down FastAPI server...")
        server_process.terminate()
        server_process.wait()
        
    if success:
        print("\n=====================================================================")
        print("               REGRESSION SUITE COMPLETED: SUCCESS                   ")
        print("=====================================================================")
        sys.exit(0)
    else:
        print("\n=====================================================================")
        print("               REGRESSION SUITE COMPLETED: FAILED                    ")
        print("=====================================================================")
        sys.exit(1)

if __name__ == "__main__":
    run_regression()
