# Scaling

How Centinela behaves as the number of monitored places, residents, and alert volume grows, and where the real cost and bottlenecks are.

## Current Capacity

Centinela runs as a single Cloud Run service (autoscaling, request-driven) that serves both the API and the static app:

- **Places:** 29 actively monitored cities plus 9 N.A.M. watched places. Adding a place is configuration plus one resolution pass (geocode + river-grid probe); cost scales roughly linearly with place count.
- **Reads:** the hazard model reads each place's signals from BigQuery over REST using a cached access token, refreshed on an interval rather than per query.
- **State:** Firestore holds risk-history ticks, push subscriptions, incidents, and the heal log. Cloud Run instances are ephemeral, so durable state lives in Firestore, not in memory.
- **Push:** Firebase Cloud Messaging uses one topic per place. Fan-out to subscribed devices is handled by FCM, so the backend publishes one message per severity change regardless of how many devices are subscribed.
- **Self-heal agent:** the DataOps agent checks connector freshness and acts only when a connector is stale; its cost is bounded by retry limits, not by traffic.

Assumptions for the current version: single deployment, demonstration-scale resident volume, one BigQuery dataset, and Fivetran on its configured sync cadence.

## Where It Scales Cleanly

### Frontend
Plain static assets (HTML, CSS, ES modules) served by the backend with `no-cache`, plus a service-worker app-shell cache. This scales trivially and could move behind a CDN with no code change. The PWA offline shell already offloads repeat loads to the client.

### Push fan-out
Per-place FCM topics mean resident count does not increase backend work: 10 or 10,000 subscribers to a city is still one publish per severity change. This is the cleanest scaling property in the system.

### Reads
BigQuery handles far more data than Centinela queries. The backend caps cost by caching the access token and by reading per-place rather than scanning broadly. Group summaries and risk-all endpoints batch reads.

## Where the Bottlenecks Are

### Per-place compute grows with place count
Each monitored place needs a risk computation and continuous recording of observed rain and air quality. At hundreds of places this becomes the dominant backend cost. Mitigations: batch BigQuery reads, compute on a schedule and cache ticks in Firestore (already the pattern for history), and parallelize per-place work.

### Cloud Run cold starts and background work
Request-driven autoscaling means background loops do not run when there is no traffic, and a scaled-to-zero instance pays a cold start. Centinela learned this directly: background threads starve without traffic, so scheduled work must be driven by an external trigger (Cloud Scheduler hitting an endpoint) rather than an in-process loop, and durable state must survive cold starts. At higher scale, set a minimum instance count and move periodic work to Cloud Scheduler + a dedicated endpoint.

### LLM, translation, and speech are the cost drivers
These are the metered, per-event costs:

| Service | When it is called | Scaling lever |
|---------|-------------------|---------------|
| Vertex AI Gemini (narration) | Per severity-change guidance, cached | Cache aggressively per (place, severity); only regenerate on change |
| Cloud Translation | Per alert string, per language | Cache per string (already done); human-correctable cache entries are reused |
| Cloud Text-to-Speech | Per `/alert-audio` request | Cache generated audio per (text, language, voice) |
| BigQuery | Per read | Cached token, per-place reads, scheduled precompute |
| DataOps agent (Gemini) | Only when a connector is stale | Bounded by freshness checks and retry limits |

Translation and audio are cached per string and per (text, language, voice), so steady-state alerts are cheap; cost spikes only when content changes. Narration is cached per severity so a place sitting at one level does not re-bill.

### Firestore write volume
Risk ticks and heal records are small and append-mostly. At many places times frequent ticks this grows; mitigations are batched writes and a retention policy on history.

## Scaling Path

1. **Now:** single Cloud Run service, autoscaling on request volume, Firestore state, Fivetran on cadence, per-place FCM topics.
2. **More places / steady load:** set a minimum instance count, move periodic recompute and freshness checks to Cloud Scheduler hitting dedicated endpoints (so they run without user traffic), and precompute risk on a schedule into Firestore.
3. **Many regions / many residents:** front the static app with a CDN, shard BigQuery reads, and keep push on FCM topics (no change needed). Translation/TTS caches carry most of the load.
4. **Multi-tenant or partner feeds:** the CAP v1.2 feed already lets emergency-management systems consume alerts without hitting the UI; this is the integration seam for scale-out consumers.

## Observability at Scale

- **Connector freshness and heals** are exposed at `/connector-status` and `/autonomous-heals`, with incident history, so pipeline health is visible without log spelunking.
- **Structured logs** from Cloud Run can ship to a centralized logging platform; volume grows linearly with traffic and stays modest.
- **Diagnostics UI** surfaces connector state, autonomous heals, and incidents directly in the app for live demos and operations.

## Architecture Decisions for Scale

- **Per-place topics over device fan-out** so resident growth does not add backend work.
- **Cache by content, not by request** for narration, translation, and audio, so steady state is nearly free and cost tracks change, not traffic.
- **External scheduling over in-process loops** because request-driven Cloud Run does not run background threads without traffic.
- **Durable state in Firestore** because ephemeral instances cannot hold state across cold starts or scale events.
- **CAP feed as the scale-out seam** so high-volume machine consumers read a standards feed instead of the interactive app.

## What Does Not Need to Scale

- **The N.A.M. activity scores** are derived from public records and change slowly; they can be computed infrequently and cached.
- **The worldwide seismic feed** is a single USGS source shared by all clients; one fetch serves everyone.
- **The self-heal agent** acts only on staleness, not per request, so its cost does not grow with traffic.
