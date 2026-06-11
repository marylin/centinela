# QUICKGUIDE.md

Step-by-step setup, run, and deploy guide for Centinela.

---

## 1. Prerequisites

- **Python 3.11+** and `pip` - [Install Python](https://www.python.org/downloads/)
- **Git** - [Install Git](https://git-scm.com/downloads)
- For deploying or using live data: the **Google Cloud SDK** (`gcloud`) authenticated to the project - [Install gcloud](https://cloud.google.com/sdk/docs/install)

You do not need any of the Google Cloud services to run the app locally. With `TESTING=true`, the backend uses in-memory fallbacks and serves the full UI with mock data.

---

## 2. Clone and Install

```bash
git clone https://github.com/marylin/centinela.git
cd centinela

python -m venv .venv
. .venv/Scripts/activate         # Windows
# source .venv/bin/activate      # macOS / Linux

pip install -r requirements.txt
```

---

## 3. Run Locally (no cloud needed)

```bash
TESTING=true python -m uvicorn api.main:app --port 8000
```

Open **http://127.0.0.1:8000**. Serve on port 8000 specifically: the Google Maps key is HTTP-referrer restricted and allows `localhost:8000`, so the map will not render on other ports.

What you can do locally:
- Browse the all-places grid (monitored cities and N.A.M. watched places) and the worldwide seismic feed.
- Open a place to see its public alert card, map, hazard model, live conditions, risk timeline, and rain/river/soil trends.
- Open the Diagnostics slideout to simulate an outage (`break`), heal it, and inject a SIMULATED event.
- Read the site pages (about, technology, privacy, terms, glossary) as in-page modals.

---

## 4. Run Tests

```bash
TESTING=true python -m pytest test_regression.py test_demo_endpoints.py test_history_endpoints.py test_seismic_events.py -v
```

Tests use in-memory fallbacks and never touch live cloud state.

---

## 5. Configure Google Cloud (for live data)

Live data and alerts require a Google Cloud project with these enabled and a service account that can use them:

| Capability | Service |
|------------|---------|
| Warehouse | BigQuery |
| State | Firestore |
| Agent model + narration | Vertex AI (Gemini) |
| Translation | Cloud Translation |
| Spoken audio | Cloud Text-to-Speech |
| Push | Firebase Cloud Messaging |

- **Secrets:** Fivetran API keys belong in **Secret Manager**, not in the repo. On Cloud Run, BigQuery, Firestore, Vertex, Translation, and TTS are reached through the runtime **service account**, so you do not embed those credentials.
- **Local credentials:** if you want to hit live services locally, put development keys once into a gitignored env file at the repo root. Never commit it.
- **Region:** the Gemini location is pinned to `us` in code; keep your project resources consistent with that.

---

## 6. The Data Pipeline (Fivetran into BigQuery)

Centinela's hazard data is loaded by two custom Fivetran connectors. To deploy or re-sync a connector:

```bash
# Deploy a connector (example shape; values come from your environment)
fivetran deploy --api-key <base64 key:secret> \
  --destination <Warehouse> --connection <connection-name> \
  --configuration configuration.json --non-interactive
```

In normal operation you do not run this by hand: the autonomous DataOps agent detects a stale connector and forces a re-sync through the Fivetran MCP server, with retries and an auditable heal record. You can watch this in the Diagnostics slideout or at `/connector-status` and `/autonomous-heals`.

---

## 7. Deploy to Cloud Run

```bash
gcloud run deploy centinela-v1 \
  --source . \
  --project=centinela-498622 \
  --region=us-central1 \
  --allow-unauthenticated \
  --quiet
```

This builds the container server-side with Buildpacks (no local Docker). The `Procfile` runs `uvicorn api.main:app` on the provided `$PORT`. The command prints the new revision and the service URL when it finishes.

---

## 8. Verify the Live Deployment

Do not trust "it deployed" as "it works." Check the live URL:

```bash
U=https://centinela-v1-765013283380.us-central1.run.app
curl -s -o /dev/null -w "root=%{http_code}\n" "$U/"
curl -s -o /dev/null -w "cap=%{http_code}\n"  "$U/cap.xml"
curl -s "$U/connector-status" | head
```

Then open the app, pick a city, and confirm the alert card, map, and charts render with current data.

---

## 9. Troubleshooting

### The map does not render
The Google Maps key is HTTP-referrer restricted. Locally, serve on **port 8000** (allowed); other ports are blocked by the referrer restriction.

### State resets on Cloud Run
In-memory state does not survive Cloud Run cold starts or scale events. Durable state (subscriptions, history, heals) must use Firestore. If something resets, confirm it is being written to Firestore, not held in memory.

### Background work does not run when idle
Request-driven Cloud Run does not run in-process background loops without traffic. Periodic work (freshness checks, recompute) should be driven by an external trigger (Cloud Scheduler calling an endpoint), not an in-process timer.

### A bodyless POST returns 411
The Google Front End rejects bodyless POSTs with a 411. Send an explicit empty JSON body (`-d '{}'` with `Content-Type: application/json`) for POST endpoints that take no parameters.

### Port 8000 will not bind locally
After back-to-back local runs, the port can sit in TIME_WAIT. Wait about 60 seconds, or free it with `npx kill-port 8000`, before restarting.

### A connector looks stale
Open the Diagnostics slideout (or `/connector-status`). The DataOps agent should detect staleness and re-sync automatically, logging the heal to `/autonomous-heals`. If it cannot recover after its retries, it surfaces a "pipeline degraded" state on purpose rather than hiding it.

### Verify, do not assume
After a deploy, hard-reload long-lived browser tabs so the service worker picks up the new modules, and re-run the live checks in section 8.

---

## 10. Where Things Live

- **Backend entry:** `api/main.py` (composition root), `api/core.py` (env + clients, imported first).
- **Risk model:** `api/hazard.py`.
- **Agents:** `rapid_agent/agent.py` (DataOps self-heal), `rapid_agent/centinela_agent.py` and `rapid_agent/narrate.py` (narration).
- **Frontend:** `web/index.html`, `web/js/`, `web/pages/`.
- **Agent rules and project context:** `GEMINI.md`.
