# Architecture

How Centinela turns raw, real measurements into one honest risk level per place, reaches residents in their own language, and keeps its own data pipeline healthy without a human in the loop.

## 1. System Overview

Centinela is a FastAPI backend on Google Cloud Run that serves both the JSON API and the static web app. Hazard data is ingested by two custom Fivetran connectors into BigQuery; the backend reads from BigQuery over REST, computes a risk index per place, and renders alerts that are translated, spoken, and pushed to residents. An autonomous DataOps agent (Google ADK on Vertex Gemini) watches the connectors and self-heals stale data through the Fivetran MCP server.

### Component Summary

| Component | Responsibility |
|-----------|----------------|
| Fivetran connectors (x2) | Load the global USGS earthquake feed and daily GloFAS discharge + ECMWF soil moisture into BigQuery |
| BigQuery | Warehouse for all hazard signals; queried by the backend over REST with a cached access token |
| FastAPI backend (Cloud Run) | Hazard model, per-surface routers, static app, alert rendering |
| Firestore | Durable state (risk ticks, push tokens/topics, incidents, heal history) |
| DataOps agent (ADK/Gemini) | Detects stale connectors, forces re-sync via Fivetran MCP, records auditable heals |
| Narration (Gemini) | Plain-language guidance text per severity |
| Cloud Translation + Text-to-Speech | Resident-language alert text and spoken audio |
| Firebase Cloud Messaging | Per-place push topics, one message per severity change |
| Frontend (plain JS PWA) | Single-page app: place grid, detail view, maps, charts; installable, offline shell |

The composition root is `api/main.py`: it imports `api.core` first (which runs `load_dotenv()` and initializes Firebase/Firestore before any module reads the environment), then builds the FastAPI app, adds CORS, and includes one router per surface.

## 2. Data Pipeline

```
USGS feed ----\
GloFAS (Open-Meteo) --> Fivetran connector(s) --> BigQuery tables --> backend (REST)
ECMWF soil ---/
Google Weather + Air Quality --> recorded continuously by the backend --> Firestore/BigQuery
```

- **Two custom Fivetran connectors** load the data Centinela does not poll itself: the global USGS earthquake feed, and daily river discharge (GloFAS via Open-Meteo) plus soil moisture (ECMWF) for every place.
- **Observed rain and air quality** come from the Google Weather and Air Quality APIs and are recorded continuously by the backend, so the "observed" series is always current.
- **No seeding.** Even coordinates are derived. `resolution.py` and `places_resolver.py` geocode each place name and probe the river-model grid for the strongest channel nearby, producing the anchor point and a separate river monitoring point.
- **Provenance is preserved end to end.** Every series carries an observed-vs-model label that surfaces in the UI (for example "model, GloFAS" or "observed, Google Weather").

## 3. The Risk Model

`api/hazard.py` computes a 0 to 1 risk index per place by blending four signals:

1. **Flood** - river discharge compared against that same place's own 92-day baseline (sitting at roughly the 90th percentile maps to about 0.6).
2. **Rain** - observed 24-hour rainfall.
3. **Soil** - soil wetness, used as an amplifier rather than a standalone hazard.
4. **Seismic** - the strongest recent earthquake within the place's bounding box (USGS).

Design rules:

- **Strongest hazard dominates.** The index takes the leading hazard and lets co-occurring hazards raise it further, rather than averaging signals into mush.
- **Small streams are dampened** so a creek cannot read like a major river flood.
- **Per-place baselines, not global thresholds.** A discharge that is alarming in a dry region is normal in a wet one, so every place is compared against its own recent history (a 92-day window, the same window the resolver probes).
- **Everything is labeled MODEL.** The index is Centinela's own model and is never presented as an official measurement.

For N.A.M. (Not Actively Monitored) places, the backend computes an activity score from public earthquake and river records instead of a live index, and the UI labels it as history, not a live alarm.

## 4. Agent Design

Centinela uses two Gemini-based agents with distinct jobs.

### DataOps self-heal agent (`rapid_agent/agent.py`)

A Google ADK `LlmAgent` running on Vertex AI Gemini (location pinned to `us` in code). Its instruction makes it a focused operator, not an open-ended assistant:

- **Freshness rule.** A connector is stale if its last successful sync is more than 5 minutes ago, or it never succeeded and setup is incomplete.
- **Action.** On staleness, the agent uses the Fivetran MCP server's write tools to force a re-sync and raise the sync frequency.
- **Bounded retries.** Write calls are wrapped in a retry loop using a `sleep` tool for backoff (about 2s then 4s), up to 3 attempts.
- **No silent failure.** If all retries fail, the agent surfaces a visible "pipeline degraded" state and never hides the error.

The agent reaches Fivetran through an `McpToolset` over a stdio connection to the Fivetran MCP server (declared in `requirements.txt` as `git+https://github.com/fivetran/fivetran-mcp`). Every heal is recorded so the diagnostics UI and incident history can show what the agent did and when.

### Narration agent (`rapid_agent/centinela_agent.py`, `rapid_agent/narrate.py`)

A Gemini narration loop that turns a place's current severity and dominant hazard into short, plain-language guidance. Output is cached (`api/narration.py`) and then translated and spoken downstream. The canonical text is English; Cloud Translation produces the resident-language version with an original-English toggle preserved in the UI.

### Tool-use loop

The DataOps agent follows the standard ADK tool-use loop: read connector state, decide, call a tool (Fivetran MCP write or `sleep`), observe the result, and repeat until fresh or the retry budget is exhausted. Because writes are bounded and idempotent (force-sync, raise-frequency), repeated attempts cannot compound damage.

## 5. State and Storage

- **Firestore is the source of truth on Cloud Run.** Risk-history ticks, push tokens and per-place topic subscriptions, incidents, and the autonomous-heal log all live in Firestore (`api/stores.py`).
- **In-memory fallbacks** back the same interfaces for local development and tests (`TESTING=true`), so the app runs with no live GCP dependency.
- **Why Firestore, not in-memory, in production.** Cloud Run instances are ephemeral and can be recycled or scaled to zero; in-memory state is lost on every cold start. State that must survive (subscriptions, history, heal audit) is therefore persisted.

## 6. Integration Architecture

- **BigQuery over REST.** The backend fetches one OAuth access token and queries BigQuery via REST, refreshing the token on an interval. Shelling out to the `bq`/`gcloud` CLIs is deliberately avoided.
- **Fivetran MCP.** The DataOps agent's only write path into the pipeline; bounded to re-sync and frequency operations.
- **Firebase Cloud Messaging.** One topic per place. Subscribing a device adds it to that place's topic; a severity change publishes a single message to the topic.
- **Cloud Translation.** Per-string translation with a cache and a human-correction path; the source line is rendered honestly rather than impersonating an official authority.
- **Cloud Text-to-Speech.** Generates `/alert-audio` in the resident language and in English.
- **Google Maps JavaScript API.** Client-side, with an HTTP-referrer restriction to the deployment domain.
- **CAP v1.2 feed.** `/cap.xml` emits an OASIS Common Alerting Protocol document with English plus resident-language info blocks, identifying the sender as a demonstration system, not an alerting authority.

### Graceful degradation

Optional capabilities fail soft. If translation, speech, or push are unavailable, the core risk view still renders; the backend records the gap rather than failing the request, and the UI shows an offline banner when the API is unreachable.

## 7. Alert Flow

```
severity change detected
   -> render canonical English guidance (Gemini narration, cached)
   -> Cloud Translation -> resident-language text (cached, human-correctable)
   -> Cloud Text-to-Speech -> /alert-audio (local + English)
   -> FCM publish to the place topic (one message per severity change)
   -> CAP v1.2 document available at /cap.xml
   -> web app renders the public alert card (read + listen controls)
```

## 8. Frontend Architecture

- **No framework.** The UI is plain JavaScript ES modules under `web/js/`, served by the backend with a pinned JavaScript MIME type and `no-cache` so deploys propagate.
- **Two views, one shell.** `index.html` holds the all-places grid (monitored + N.A.M. + worldwide seismic) and a detail view (public alert card, map, hazard model, live conditions, risk timeline, rain/river/soil trends, nearby seismic).
- **Polling.** `poll.js` refreshes registry, index data, and watchlist on an interval; selection drives the detail view.
- **Charts.** `charts.js` renders lightweight inline-SVG sparklines with axis labels and point values, with an accessible fallback.
- **PWA.** `firebase-messaging-sw.js` is one service worker that handles push and caches the app shell (network-first, offline fallback). `manifest.json` makes it installable.

## 9. Deployment

- **Cloud Run, source build.** `gcloud run deploy centinela-v1 --source . --project=centinela-498622 --region=us-central1 --allow-unauthenticated --quiet` builds the container server-side with Buildpacks. No local Docker needed.
- **Process.** `Procfile` runs `uvicorn api.main:app` on `$PORT`.
- **Secrets.** Fivetran keys live in Secret Manager; Vertex, BigQuery, and Firestore access use the runtime service account. Nothing secret is committed.

## 10. Technology Decisions

- **FastAPI + plain-JS frontend** keeps the whole stack in one deployable unit with no build step for the UI, which matters for a fast-iterating demonstration.
- **BigQuery via REST, not CLI**, avoids spawning command windows and token churn, and keeps the backend portable to Cloud Run.
- **Firestore over in-memory** because Cloud Run instances are ephemeral; durable state must outlive a cold start.
- **ADK + Fivetran MCP** gives the self-heal agent a real, auditable write path into the pipeline instead of a mocked integration.
- **Per-place FCM topics** scale to many devices without the backend tracking individual tokens for fan-out.
- **Honest labeling as a design constraint**: model output is marked MODEL, demonstrations are marked SIMULATED, and alerts defer to local civil protection authorities.
