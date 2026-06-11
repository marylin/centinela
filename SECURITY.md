# Security

Centinela is a public, read-mostly monitoring app with one privileged actor: an autonomous agent that can write to the data pipeline. The security model protects the request surface, bounds what the agent can do, keeps secrets out of the codebase, and treats honest labeling as a safety property.

## 1. Security Overview

### Defense layers

| Layer | Concern | Mechanism |
|-------|---------|-----------|
| 1. Request surface | Untrusted HTTP input, asset serving | Allowlisted asset names, pinned content types, validated query/body fields, CORS |
| 2. Autonomous agent | A Gemini agent with Fivetran write tools | Narrow instruction, bounded retries, idempotent writes, auditable heals, never silences errors |
| 3. Secrets and keys | Credentials for GCP, Fivetran, Firebase | Secret Manager + runtime service account; only public client keys ship to the browser |
| 4. Data and responsible AI | Resident data, model honesty | Minimal data (push token only), MODEL/SIMULATED labels, deferral to official authorities |

### Threat model

- **Malicious or malformed API input.** Mitigated by field validation, allowlisting of served asset names, and pinned MIME types.
- **Quota theft of client keys.** The Maps and Firebase web keys are visible in the browser by design; the Maps key is HTTP-referrer restricted to the deployment domain, and the Firebase web config is a public identifier, not a secret.
- **Agent over-reach.** The DataOps agent can only force a re-sync and raise sync frequency through the Fivetran MCP server. These are idempotent and non-destructive; there is no delete or schema-mutation path.
- **Stale or wrong hazard data presented as truth.** Mitigated by honest labeling (MODEL everywhere), provenance on every series, and explicit deferral to local civil protection authorities.
- **Leaking secrets via the repo or logs.** Mitigated by Secret Manager, gitignored env files, and not echoing secret values.

Out of scope for this demonstration: multi-tenant authz, account systems (there are no accounts), and DDoS mitigation beyond what Cloud Run provides.

## 2. Request Surface (Layer 1)

- **Asset allowlisting.** Static routes serve UI modules only from `web/js/` by an allowlisted name pattern and pin `text/javascript` (module scripts hard-require a JS MIME type). Icons and the manifest are similarly allowlisted with explicit content types. A directory mount is deliberately avoided so that `node_modules`, dotfiles, and wrong content types cannot be exposed.
- **Page routing.** Site pages (about, technology, privacy, terms, glossary) are served only from a fixed `PAGE_NAMES` set; anything else is a 404.
- **Input validation.** Query and body fields (place ids, basin ids, tokens) are validated before use; demo and test endpoints are clearly separated and their effects are labeled SIMULATED.
- **Transport and CORS.** Cloud Run serves over HTTPS. CORS is currently open for the demonstration; tightening `allow_origins` to the deployment domain is the first hardening step for a production deployment.

## 3. Autonomous Agent Guardrails (Layer 2)

The DataOps agent is the only component that can change the pipeline, so its blast radius is constrained by design:

- **Narrow instruction.** The agent's system instruction scopes it to one job: detect stale Fivetran connectors and restore freshness. It is not a general assistant.
- **Idempotent, non-destructive writes only.** Its tools force a re-sync and raise sync frequency. Repeating them cannot compound damage; there is no destructive operation available.
- **Bounded retries.** Write calls run in a retry loop with backoff (`sleep` tool, about 2s then 4s), capped at 3 attempts, so a failing tool cannot loop indefinitely or hammer the API.
- **No silent failure.** If recovery fails, the agent surfaces a visible "pipeline degraded" state. Hiding an error is explicitly disallowed.
- **Auditable.** Every heal is recorded and exposed through `/autonomous-heals` and the incident history, so the agent's actions are reviewable after the fact.
- **MCP isolation.** The agent reaches Fivetran only through the MCP toolset over stdio; it has no ambient credentials beyond what that toolset provides.

## 4. Secrets and Key Management (Layer 3)

- **Server secrets.** Fivetran API keys live in Google Secret Manager. Vertex AI, BigQuery, and Firestore access use the Cloud Run runtime service account, not embedded credentials.
- **Local secrets.** Development keys go once into a gitignored env file at the repo root and are never committed.
- **Public client keys.** The Google Maps JavaScript key and the Firebase web config ship to the browser by necessity. The Maps key is HTTP-referrer restricted to the deployment domain; the Firebase web config is a public app identifier. Both are documented in code as intentionally public.
- **Repo hygiene.** `.gitignore` excludes env files, credential filenames, the local virtual environment, working-notes directories, and runtime logs. History has been verified free of secrets and credential files.
- **Log hygiene.** Secret values are never written to logs or commit messages; a value is confirmed to exist or redacted rather than printed.

## 5. Data Protection and Responsible AI (Layer 4)

### Data minimization

- **No accounts, no tracking.** There is no sign-up, no analytics tracker, and no advertising.
- **One device-linked datum.** The only thing tied to a device is the Firebase push token, stored so alerts can be delivered and removable by turning alerts off or clearing site data. User choices (which cities are subscribed) live in the browser, not on the server.
- **Hazard data is about places, not people.** Earthquakes, rivers, and weather are public information about locations.

### Transparency

- The risk index is labeled MODEL everywhere and described as a demonstration, not an official authority.
- Anything generated for a demonstration is labeled SIMULATED.
- Translated alerts keep an honest source line and an original-English toggle; translations are cached and human-correctable.
- N.A.M. places are clearly marked as watched-from-public-records, not actively monitored, with no alerts.

### Human oversight and deferral

Every alert tells residents to follow their local civil protection authority, and that Centinela's model can be wrong, late, or missing information. The system never claims to be the authoritative warning.

## 6. Testing

Automated suites guard the behavior that matters for safety and correctness:

- `test_regression.py` - broad backend regression coverage.
- `test_demo_endpoints.py` - demo controls (inject/clear SIMULATED events, break/heal) behave and stay labeled.
- `test_history_endpoints.py` - risk and telemetry history endpoints.
- `test_seismic_events.py` - the worldwide and nearby seismic feeds.

Tests run against in-memory fallbacks (`TESTING=true`), so they need no live GCP credentials and cannot touch production state.
