import os
import sys
import time
import subprocess
import requests

def wait_for_server(url: str, timeout: int = 30):
    """Wait for the local server to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            res = requests.get(f"{url}/risk", timeout=10)
            if res.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False

def run_regression():
    print("=====================================================================")
    print("                    STARTING REGRESSION SUITE                        ")
    print("=====================================================================")
    
    server_url = "http://127.0.0.1:8000"
    server_process = None
    
    # 1. Start uvicorn server if not already running
    try:
        res = requests.get(f"{server_url}/risk", timeout=10)
        if res.status_code == 200:
            print("FastAPI server is already running.")
        else:
            raise Exception("Server returned non-200 status code")
    except Exception:
        print("Starting FastAPI server locally...")
        python_exe = os.path.join(".venv", "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = "python"
        
        server_process = subprocess.Popen(
            [python_exe, "-m", "uvicorn", "api.main:app", "--host", "127.0.0.1", "--port", "8000"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        if not wait_for_server(server_url):
            print("ERROR: FastAPI server failed to start.")
            if server_process:
                server_process.terminate()
            sys.exit(1)
        print("FastAPI server started successfully.")

    try:
        # 2. Load: Populate BigQuery tables
        print("\nStep 1: Populating/loading mock & live feeds...")
        python_exe = os.path.join(".venv", "Scripts", "python.exe")
        if not os.path.exists(python_exe):
            python_exe = "python"
            
        res_load = subprocess.run([python_exe, "rapid_agent/populate.py"], capture_output=True, text=True)
        if res_load.returncode != 0:
            print(f"ERROR: Loading data failed!\nSTDERR: {res_load.stderr}")
            sys.exit(1)
        print("Success: Data loaded into BigQuery.")

        # 3. Risk: Query GET /risk
        print("\nStep 2: Checking GET /risk...")
        res_risk = requests.get(f"{server_url}/risk")
        if res_risk.status_code != 200:
            print(f"ERROR: GET /risk failed with status code {res_risk.status_code}")
            sys.exit(1)
            
        risk_data = res_risk.json()
        print(f"Success: GET /risk returned {len(risk_data)} municipalities:")
        for r in risk_data:
            print(f"  - {r['municipality']}: score={r['risk_score']}, rain={r['rainfall_mm']}mm, river={r['river_level_m']}m, saturation={r['soil_saturation']}")

        # 4. Alert: Query GET /alert
        print("\nStep 3: Checking GET /alert (Gemini-narrated)...")
        res_alert = requests.get(f"{server_url}/alert")
        if res_alert.status_code != 200:
            print(f"ERROR: GET /alert failed with status code {res_alert.status_code}")
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
            print(f"ERROR: POST /break failed with status code {res_break.status_code}")
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
            print(f"ERROR: POST /heal failed with status code {res_heal.status_code}")
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
                print(f"ERROR: JS click handler execution check failed!\\nSTDERR: {res_js.stderr}\\nSTDOUT: {res_js.stdout}")
                sys.exit(1)
            print("Success: JS click handler runs with no console error.")
        finally:
            if os.path.exists(temp_name):
                os.remove(temp_name)

        print("\n=====================================================================")
        print("               REGRESSION SUITE COMPLETED: SUCCESS                   ")
        print("=====================================================================")

    finally:
        if server_process:
            print("\nShutting down FastAPI server...")
            server_process.terminate()
            server_process.wait()

if __name__ == "__main__":
    run_regression()
