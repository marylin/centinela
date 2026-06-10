// Diagnostics slideout: pipeline status, break/heal, demo controls, heal +
// incident history. Data loads when the slideout opens (no background poll
// in index mode). All actions use event delegation: no window globals.

import { state, notify } from "./state.js";
import * as api from "./api.js";
import { escapeHtml, formatRelativeTime } from "./util.js";

const DEMO_EVENT_MAGNITUDE = 7.2;

function setDemoStatus(message, isError) {
  const el = document.getElementById("demo-controls-status");
  if (!el) return;
  el.textContent = message;
  el.style.color = isError ? "var(--danger)" : "";
}

async function refreshDiagnostics() {
  const basin = (state.selection && state.selection.groupId) || (state.groups[0] && state.groups[0].id) || "rio_cauca";
  try {
    const [status, heals, incidents] = await Promise.all([
      api.getConnectorStatus(basin),
      api.getAutonomousHeals(),
      api.getIncidents(),
    ]);
    renderConnectors(status);
    renderHeals(heals);
    renderIncidents(incidents);
    renderDemoTargets();
  } catch (err) {
    console.error("Diagnostics refresh failed:", err);
  }
}

function renderConnectors(status) {
  const el = document.getElementById("diag-connectors");
  if (!el || !status) return;
  const conns = status.connectors || [];
  el.innerHTML = conns.map(c => `
    <div class="diag-connector-row">
      <span class="diag-connector-name">${escapeHtml(c.name || c.connector_id)}</span>
      <span class="badge ${status.status === "active" ? "badge-low" : "badge-danger"}">${escapeHtml(status.status || "unknown")}</span>
    </div>`).join("") || `<div class="empty-alerts">No connector data.</div>`;
  const sync = document.getElementById("diag-last-sync");
  if (sync) sync.textContent = status.last_sync_time && status.last_sync_time !== "never"
    ? `last sync ${formatRelativeTime(status.last_sync_time)}` : "";
}

function renderHeals(heals) {
  const el = document.getElementById("diag-heals");
  if (!el) return;
  const sorted = [...(heals || [])].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 6);
  el.innerHTML = sorted.map(h => `
    <div class="diag-history-row">
      <span>${escapeHtml(h.action || h.details || "heal")}</span>
      <span class="tabular-nums">${formatRelativeTime(h.timestamp)}</span>
    </div>`).join("") || `<div class="empty-alerts">No autonomous heals recorded.</div>`;
}

function renderIncidents(incidents) {
  const el = document.getElementById("diag-incidents");
  if (!el) return;
  const sorted = [...(incidents || [])].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp)).slice(0, 6);
  el.innerHTML = sorted.map(inc => `
    <div class="diag-history-row">
      <span>${escapeHtml(inc.type || "incident")} · ${escapeHtml(inc.basin || "")}</span>
      <span class="tabular-nums">${formatRelativeTime(inc.timestamp)}</span>
      <button type="button" class="btn btn-sm" data-reopen="${escapeHtml(inc.id)}">Reopen</button>
    </div>`).join("") || `<div class="empty-alerts">No incidents recorded.</div>`;
}

function renderDemoTargets() {
  const sel = document.getElementById("demo-muni-select");
  if (!sel) return;
  const options = [];
  (state.groups || []).forEach(g => (g.places || []).forEach(p =>
    options.push(`<option value="${escapeHtml(g.id)}|${escapeHtml(p.name)}">${escapeHtml(p.name)} (${escapeHtml(g.name)})</option>`)));
  if (sel.dataset.count !== String(options.length)) {
    sel.innerHTML = options.join("");
    sel.dataset.count = String(options.length);
  }
}

export function setupDiagnostics() {
  const toggleBtn = document.getElementById("diagnostics-toggle-btn");
  const closeBtn = document.getElementById("diagnostics-close-btn");
  const overlay = document.getElementById("diagnostics-overlay");
  const slideout = document.getElementById("diagnostics-slideout");
  if (!toggleBtn || !slideout) return;

  const open = () => {
    slideout.classList.add("open");
    if (overlay) overlay.classList.add("open");
    toggleBtn.setAttribute("aria-expanded", "true");
    refreshDiagnostics();
  };
  const close = () => {
    slideout.classList.remove("open");
    if (overlay) overlay.classList.remove("open");
    toggleBtn.setAttribute("aria-expanded", "false");
  };
  toggleBtn.addEventListener("click", open);
  if (closeBtn) closeBtn.addEventListener("click", close);
  if (overlay) overlay.addEventListener("click", close);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && slideout.classList.contains("open")) close();
  });

  slideout.addEventListener("click", async (e) => {
    const reopen = e.target.closest("[data-reopen]");
    if (reopen) {
      try { await api.reopenIncident(reopen.dataset.reopen); refreshDiagnostics(); } catch (err) { console.error(err); }
      return;
    }
    if (e.target.id === "diag-break-btn") {
      try { await api.postBreak(); refreshDiagnostics(); } catch (err) { console.error(err); }
      return;
    }
    if (e.target.id === "diag-heal-btn") {
      try { await api.postHeal(); refreshDiagnostics(); } catch (err) { console.error(err); }
      return;
    }
    if (e.target.id === "demo-inject-btn") {
      const sel = document.getElementById("demo-muni-select");
      if (!sel || !sel.value) return;
      const [basin, muni] = sel.value.split("|");
      setDemoStatus("Injecting SIMULATED event…", false);
      try {
        await api.demoInject(basin, muni, DEMO_EVENT_MAGNITUDE);
        setDemoStatus(`SIMULATED M ${DEMO_EVENT_MAGNITUDE} event injected for ${muni}.`, false);
        notify("demo-changed");
      } catch (err) { setDemoStatus(`Inject failed: ${err.message}`, true); }
      return;
    }
    if (e.target.id === "demo-clear-btn") {
      const sel = document.getElementById("demo-muni-select");
      const basin = sel && sel.value ? sel.value.split("|")[0] : ((state.groups[0] || {}).id || "rio_cauca");
      setDemoStatus("Clearing simulated events…", false);
      try {
        await api.demoClear(basin);
        setDemoStatus("Simulation cleared; live data resumes.", false);
        notify("demo-changed");
      } catch (err) { setDemoStatus(`Clear failed: ${err.message}`, true); }
    }
  });
}
