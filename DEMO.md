# Demo Guide

A short walkthrough of Centinela for reviewers. Everything below uses real data, except where the UI labels something SIMULATED.

**Live app:** https://centinela-v1-765013283380.us-central1.run.app

## What it is, in one line

Centinela watches floods, heavy rain, unstable ground, and earthquakes in 29 cities (plus 9 it keeps an eye on), turns real measurements into one plain risk level per place, and reaches residents with translated, spoken, push alerts. An autonomous agent keeps the data pipeline healthy on its own.

## A 3-minute path

1. **All places.** On the landing page you see the monitored cities, the N.A.M. (Not Actively Monitored) places, and a live worldwide seismic feed from USGS. Each tile shows the current risk level: Low, Warning, Danger, or Critical.

2. **Open a city.** Pick a monitored city. You get:
   - a **public alert card** with the status, the dominant hazard, what to do, and an honest source line (it is a model, not an official authority);
   - a **map** with the place anchor and, when flood risk is elevated, the river monitoring point;
   - the **hazard model** breakdown (river, rain, soil, earthquake);
   - **live conditions** (observed rain and air quality);
   - a **risk timeline** and **rain / river / soil** charts, each with axis labels and point values.

3. **Read and listen in another language.** In the alert card footer, use **Read** to switch the written guidance between the resident language and English, and **Listen** to hear it spoken in either language. Translations are cached and human-correctable; the original English is always one tap away.

4. **Follow an earthquake.** Back on the landing page, tap any event in the worldwide seismic feed. It opens the nearest place with that event focused on the map.

5. **Watch the agent self-heal (Diagnostics).** Open the Diagnostics slideout (top right). You can:
   - **Simulate an outage** on a connector and watch the DataOps agent detect the staleness and force a re-sync through the Fivetran MCP server, with retries and a visible heal record;
   - **Inject a SIMULATED event** and see the full alert path react, always clearly labeled SIMULATED so it cannot be mistaken for a real warning;
   - review connector freshness, the autonomous-heal log, and incident history.

6. **Install it.** On Android or a desktop browser, use the **Install app** button to install Centinela as a PWA. On iPhone, use Share, then Add to Home Screen. Once installed, it opens from an icon and still shows the last data even if the network drops.

## For machine consumers

A standards-compliant OASIS CAP v1.2 feed is available at **/cap.xml**, with English and resident-language info blocks, identifying the sender as a demonstration system rather than an alerting authority.

## What to look for

- **Real data, honestly labeled.** River, rain, soil, and earthquake signals are real; the blended index is always marked MODEL; anything generated for the demo is marked SIMULATED.
- **Per-place baselines.** A city is judged against its own recent history, not a global threshold, so wet and dry regions are treated fairly.
- **Reach.** Translated text, spoken audio, per-place push, an installable offline app, and a CAP feed, all from one backend.
- **Autonomy with guardrails.** The pipeline heals itself, but the agent's writes are bounded and auditable, and a pipeline it cannot fix is surfaced as degraded, never hidden.

## Links

- App and API: https://centinela-v1-765013283380.us-central1.run.app
- API docs: https://centinela-v1-765013283380.us-central1.run.app/docs
- CAP feed: https://centinela-v1-765013283380.us-central1.run.app/cap.xml
- Demo video: _TODO: link to be added_
