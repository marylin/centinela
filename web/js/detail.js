// Detail orchestration: composes the per-place view when a tile or rail item
// is selected. Monitored places get the full panel set + the 5s telemetry
// poll; candidates get watchlist scores + live conditions and NO fabricated
// index. The seismic feed card is Phase C.

import { state, subscribe, riskRowFor, candidateByName, placeByName } from "./state.js";
import * as api from "./api.js";
import { getSeverityConfig, HAZARD_ICONS } from "./severity.js";
import { escapeHtml } from "./util.js";
import { renderMap } from "./map.js";
import { renderRail } from "./rail.js";
import { renderAlertCard } from "./alert-card.js";
import { renderConditions } from "./conditions.js";
import { renderRiskTimeline, renderTrend } from "./charts.js";
import { renderSeismicPanel } from "./seismic.js";
import { subscribeToPlace, unsubscribeFromPlace, getPlaceSubscriptions } from "./notify.js";
import { CADENCE } from "./poll.js";

let detailTimer = null;
let lastAlert = null;

function show(id, visible) {
  const el = document.getElementById(id);
  if (el) el.hidden = !visible;
}

function renderComponentsCard() {
  const el = document.getElementById("components-body");
  const sel = state.selection;
  if (!el || !sel || sel.kind !== "place") return;
  const row = riskRowFor(sel.name);
  if (!row) { el.innerHTML = `<div class="empty-alerts">Index loading…</div>`; return; }
  const score = Number(row.risk_score) || 0;
  const sev = getSeverityConfig(score);
  const comps = [
    ["Flood", row.flood_score, "river vs its own 92-day baseline"],
    ["Rain", row.rain_score, "observed 24h rainfall"],
    ["Soil", row.landslide_score !== undefined ? row.landslide_score : row.soil_score, "wetness amplifier"],
    ["Seismic", row.seismic_score, "strongest USGS detection in range"],
  ].filter(([, v]) => typeof v === "number");
  el.innerHTML = `
    <div class="components-headline">
      <span class="public-hero-status" style="color:${sev.colorHex}">${(score * 100).toFixed(0)}%</span>
      <span class="badge ${sev.badgeClass}">${sev.label}</span>
      <span class="tile-model-tag">CENTINELA MODEL INDEX</span>
      ${row.simulated ? '<span class="badge badge-simulated">SIMULATED</span>' : ""}
    </div>
    ${comps.map(([label, v, hint]) => `
      <div class="component-row">
        <span class="component-label">${label}</span>
        <span class="component-bar"><i style="width:${Math.round((Number(v) || 0) * 100)}%; background:${getSeverityConfig(Number(v) || 0).colorHex}"></i></span>
        <span class="tabular-nums">${(Number(v) || 0).toFixed(2)}</span>
        <span class="component-hint">${hint}</span>
      </div>`).join("")}
    ${typeof row.discharge_m3s === "number" ? `
      <div class="component-raws tabular-nums">river ${row.discharge_m3s.toFixed(1)} m³/s
        vs p50 ${Number(row.discharge_p50 || 0).toFixed(1)} / p90 ${Number(row.discharge_p90 || 0).toFixed(1)}
        · rain ${Number(row.rainfall_mm || 0).toFixed(1)} mm · soil ${Number(row.soil_moisture || 0).toFixed(3)}</div>` : ""}`;
}

function renderCandidateCard() {
  const el = document.getElementById("components-body");
  const sel = state.selection;
  if (!el || !sel || sel.kind !== "candidate") return;
  const c = candidateByName(sel.name);
  if (!c) return;
  const act = Number(c.activity_score) || 0;
  const sev = getSeverityConfig(act);
  el.innerHTML = `
    <div class="components-headline">
      <span class="public-hero-status" style="color:${sev.colorHex}">${act.toFixed(2)}</span>
      <span class="badge tile-badge">NOT MONITORED</span>
      <span class="tile-model-tag">ACTIVITY MODEL (USGS catalog + GloFAS reanalysis)</span>
    </div>
    <div class="component-row"><span class="component-label">Seismic</span>
      <span class="component-bar"><i style="width:${Math.round((Number(c.seismic_score) || 0) * 100)}%; background:${getSeverityConfig(Number(c.seismic_score) || 0).colorHex}"></i></span>
      <span class="tabular-nums">${(Number(c.seismic_score) || 0).toFixed(2)}</span>
      <span class="component-hint">${c.quake_90d_count || 0} quakes M4.5+ in 90 days${c.quake_90d_maxmag ? ` (max M ${Number(c.quake_90d_maxmag).toFixed(1)})` : ""}</span></div>
    <div class="component-row"><span class="component-label">Flood</span>
      <span class="component-bar"><i style="width:${Math.round((Number(c.flood_score) || 0) * 100)}%; background:${getSeverityConfig(Number(c.flood_score) || 0).colorHex}"></i></span>
      <span class="tabular-nums">${(Number(c.flood_score) || 0).toFixed(2)}</span>
      <span class="component-hint">${typeof c.days_above_seasonal_p90_last60 === "number" ? `${c.days_above_seasonal_p90_last60} days above seasonal p90 in the last 60` : "discharge n/a"}${c.cell_scale ? ` · ${c.cell_scale} cell` : ""}</span></div>
    <p class="candidate-honesty">This place is a watchlist candidate: it has NO model hazard index and is not
      monitored. The numbers above come from public archives, not live monitoring. Promotion into the
      registry is a one-row configuration change (coordinates derive automatically).</p>`;
}

async function refreshMonitoredDetail() {
  const sel = state.selection;
  if (!sel || sel.kind !== "place") return;
  try {
    const [risk, alert] = await Promise.all([
      api.getRisk(sel.groupId),
      api.getAlert(sel.groupId),
    ]);
    if (!state.selection || state.selection.name !== sel.name) return;
    state.riskByGroup[sel.groupId] = risk;
    lastAlert = alert;
    renderComponentsCard();
    renderAlertCard(alert);
    renderMap();
    renderRail();
  } catch (err) {
    console.error("Detail refresh failed:", err);
  }
}

function stopDetailPoll() {
  if (detailTimer) { clearInterval(detailTimer); detailTimer = null; }
}

let lastAlertGroup = null;

async function onSelectionChange() {
  stopDetailPoll();
  const sel = state.selection;
  if (!sel) return;
  // Alert payloads are per group: never let another group's narration or
  // advisories linger across a selection change.
  if (sel.groupId !== lastAlertGroup) {
    lastAlert = null;
    lastAlertGroup = sel.groupId;
  }
  renderRail();

  const monitored = sel.kind === "place";
  renderSubscribeButton();
  show("public-alert-card", monitored);
  show("risk-timeline-panel", monitored);
  show("trend-panel", monitored);
  renderSeismicPanel();

  if (monitored) {
    const tl = document.getElementById("risk-timeline-body");
    const tr = document.getElementById("trend-body");
    if (tl) tl.innerHTML = '<div class="empty-alerts">Loading recorded history…</div>';
    if (tr) tr.innerHTML = '<div class="empty-alerts">Loading telemetry series…</div>';
    renderComponentsCard();    // instant from cache
    renderAlertCard(lastAlert);
    renderMap();
    const p = placeByName(sel.name);
    if (p && p.anchor) renderConditions(p.anchor.lat, p.anchor.lng, `at ${sel.name} (city anchor)`);
    refreshMonitoredDetail();
    renderRiskTimeline();
    renderTrend();
    detailTimer = setInterval(refreshMonitoredDetail, CADENCE.detail);
  } else {
    renderCandidateCard();
    renderMap();
    const c = candidateByName(sel.name);
    if (c && typeof c.lat === "number") renderConditions(c.lat, c.lng, `at ${sel.name} (candidate anchor)`);
  }
}

export function setupDetail() {
  subscribe((topic) => {
    if (topic === "selection") onSelectionChange();
    if (topic === "index-data" && state.selection) {
      renderRail();
      renderSeismicPanel();
      if (state.selection.kind === "place") renderComponentsCard();
    }
    if (topic === "watchlist" && state.selection) renderRail();
    if (topic === "demo-changed" && state.selection && state.selection.kind === "place") refreshMonitoredDetail();
    if (topic === "seismic-focus" && state.selection) {
      // Basin-only panels yield while an event owns the page (nothing honest
      // could render there for an arbitrary epicenter).
      const focused = !!state.seismicFocus;
      const monitored = state.selection.kind === "place";
      show("public-alert-card", monitored && !focused);
      show("risk-timeline-panel", monitored && !focused);
      show("trend-panel", monitored && !focused);
    }
  });
}

// --- Per-place alert subscription button ------------------------------------

function renderSubscribeButton() {
  const btn = document.getElementById("place-subscribe-btn");
  const sel = state.selection;
  if (!btn) return;
  const monitored = !!(sel && sel.kind === "place");
  btn.hidden = !monitored;
  if (!monitored) return;
  const subscribed = !!getPlaceSubscriptions()[sel.groupId];
  btn.textContent = subscribed
    ? `Stop alerts for ${sel.name}`
    : `Get alerts for ${sel.name}`;
  btn.dataset.basin = sel.groupId;
  btn.dataset.subscribed = String(subscribed);
}

export function setupSubscribeButton() {
  const btn = document.getElementById("place-subscribe-btn");
  if (!btn) return;
  btn.addEventListener("click", async () => {
    const basin = btn.dataset.basin;
    if (!basin) return;
    btn.disabled = true;
    const wasSubscribed = btn.dataset.subscribed === "true";
    btn.textContent = wasSubscribed ? "Stopping alerts…" : "Enabling alerts…";
    try {
      if (wasSubscribed) await unsubscribeFromPlace(basin);
      else await subscribeToPlace(basin);
    } catch (err) {
      console.error("Subscription change failed:", err);
      alert(err.message || "Could not change the alert subscription.");
    } finally {
      btn.disabled = false;
      renderSubscribeButton();
    }
  });
}
