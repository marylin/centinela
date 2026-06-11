# Centinela: project context

Project context for agents and contributors working in this repository.

## Project

Centinela is real-data multi-hazard monitoring (floods, heavy rain, unstable ground, earthquakes) for 29 actively monitored cities plus 9 N.A.M. (Not Actively Monitored) watched places. A FastAPI backend on Google Cloud Run serves both the JSON API and the static PWA. Built for a Gemini-only hackathon.

## Architecture

- Backend: FastAPI on Cloud Run; modular routers under `api/`; composition root is `api/main.py` (it imports `api.core` first, which runs dotenv and Firebase/Firestore init before any module-level environment reads).
- Data: two Fivetran connectors load into BigQuery (USGS earthquakes, GloFAS discharge via Open-Meteo, ECMWF soil); observed rain and air quality come from Google Weather and Air Quality. BigQuery is read over REST with a cached access token.
- State: Firestore in production; in-memory fallbacks under `TESTING=true`.
- Agents: `rapid_agent/agent.py` is the DataOps self-heal agent (ADK `LlmAgent` on Vertex Gemini, Fivetran MCP write tools). `rapid_agent/centinela_agent.py` and `rapid_agent/narrate.py` handle plain-language narration.
- Risk model: `api/hazard.py`, four signals against a per-place 92-day baseline; the strongest hazard dominates; labeled MODEL everywhere.
- Alerts: Cloud Translation (cached, human-correctable) plus Cloud Text-to-Speech (resident language and English) plus Firebase Cloud Messaging per-place topics plus a CAP v1.2 feed at `/cap.xml`.
- Frontend: plain JavaScript ES modules in `web/js/`, Google Maps, PWA (one service worker handles push and caches the app shell), site pages in `web/pages/`.

## Key patterns

- `api.core` is imported first so the environment and clients are ready before other modules read them.
- One router per surface; durable state lives in Firestore (Cloud Run instances are ephemeral, so in-memory state does not survive a cold start).
- Cache by content: narration per (place, severity), translation per string, audio per (text, language, voice).
- DataOps agent: a connector is stale with no successful sync in 5 minutes; writes are idempotent (force re-sync, raise frequency) with bounded retries; a pipeline it cannot recover is surfaced as degraded; every heal is recorded.
- BigQuery is queried over REST with a cached token, not the `bq`/`gcloud` CLIs.

## Commands

- Local run: `TESTING=true python -m uvicorn api.main:app --port 8000` (serve on 8000 so the HTTP-referrer-restricted Maps key works).
- Tests: `TESTING=true python -m pytest test_regression.py test_demo_endpoints.py test_history_endpoints.py test_seismic_events.py -v`.
- Deploy: `gcloud run deploy centinela-v1 --source . --project=centinela-498622 --region=us-central1 --allow-unauthenticated --quiet`.

## Product constraints

- Honest labeling: model output is marked MODEL, demonstrations are marked SIMULATED, and alerts defer to the local civil protection authority.
- Secrets: Fivetran keys live in Secret Manager; GCP access uses the runtime service account. The client Maps and Firebase keys are public and HTTP-referrer restricted, and are documented as such in code.

## File organization

```
api/            FastAPI routers + hazard model + clients/state (composition root api/main.py)
rapid_agent/    DataOps self-heal agent + narration
web/            index.html, style.css, js/ (ES modules), pages/, manifest, service worker
test_*.py       regression, demo endpoints, history endpoints, seismic events
```
