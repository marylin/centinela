// The index tile grid: ONE entry point for all 23 places. Monitored places
// render with their MODEL index; watchlist candidates render visually
// distinct with their activity score and a NOT MONITORED treatment.
//
// Tap-race rule (hard lesson): tile nodes are created once per key set and
// then updated IN PLACE; ordering is CSS flex `order` on stable nodes, never
// a DOM rebuild. Focus and mid-poll taps always survive.

import { state, selectPlace, selectCandidate } from "./state.js";
import { getSeverityConfig, HAZARD_ICONS } from "./severity.js";
import { escapeHtml } from "./util.js";

function monitoredTileHtml(name) {
  return `
    <button type="button" class="tile tile-monitored" data-place="${escapeHtml(name)}">
      <div class="tile-head">
        <span class="tile-name"></span>
        <span class="tile-hazard" aria-hidden="true"></span>
      </div>
      <div class="tile-severity"></div>
      <div class="tile-bar"><i></i></div>
      <div class="tile-meta tabular-nums"></div>
    </button>`;
}

function candidateTileHtml(name) {
  return `
    <button type="button" class="tile tile-candidate" data-candidate="${escapeHtml(name)}">
      <div class="tile-head">
        <span class="tile-name"></span>
        <span class="badge tile-badge">NOT MONITORED</span>
      </div>
      <div class="tile-severity"></div>
      <div class="tile-bar"><i></i></div>
      <div class="tile-meta tabular-nums"></div>
    </button>`;
}

function applyFilter(grid, filterText) {
  const f = (filterText || "").trim().toLowerCase();
  let shown = 0;
  Array.from(grid.children).forEach(el => {
    const name = (el.dataset.place || el.dataset.candidate || "").toLowerCase();
    const hide = !!f && !name.includes(f);
    el.classList.toggle("tile-hidden", hide);
    if (!hide) shown += 1;
  });
  return shown;
}

export function renderTiles() {
  const monitoredGrid = document.getElementById("tile-grid-monitored");
  const candidateGrid = document.getElementById("tile-grid-candidates");
  if (!monitoredGrid || !candidateGrid) return;

  // --- monitored tiles (keyed once) ---
  const places = [];
  (state.groups || []).forEach(g => (g.places || []).forEach(p =>
    places.push({ name: p.name, groupId: g.id, kind: g.kind, country: g.country })));
  const placeKeys = places.map(p => p.name).join("|");
  if (monitoredGrid.dataset.keys !== placeKeys) {
    monitoredGrid.innerHTML = places.map(p => monitoredTileHtml(p.name)).join("");
    monitoredGrid.dataset.keys = placeKeys;
  }

  const summaries = state.groupSummaries || {};
  Array.from(monitoredGrid.children).forEach((el, idx) => {
    const p = places[idx];
    if (!p) return;
    const row = (state.riskByGroup[p.groupId] || []).find(r => r.municipality === p.name);
    const score = row ? Number(row.risk_score) || 0 : null;
    const sev = score === null ? null : getSeverityConfig(score);
    const dominant = (row && row.dominant_hazard) || (p.kind === "seismic-watch" ? "SEISMIC" : "FLOOD");
    el.querySelector(".tile-name").textContent = p.name;
    el.querySelector(".tile-hazard").innerHTML = HAZARD_ICONS[dominant] || HAZARD_ICONS.FLOOD;
    el.querySelector(".tile-severity").innerHTML = sev
      ? `<span class="badge ${sev.badgeClass}">${sev.label}</span> <span class="tabular-nums">${(score * 100).toFixed(0)}%</span> <span class="tile-model-tag">MODEL</span>`
      : `<span class="tile-model-tag">loading…</span>`;
    const bar = el.querySelector(".tile-bar i");
    bar.style.width = `${Math.round((score || 0) * 100)}%`;
    bar.style.background = sev ? sev.colorHex : "transparent";
    el.style.borderLeftColor = sev ? sev.colorHex : "var(--border-color)";
    let meta = `${p.country}`;
    if (row && typeof row.discharge_m3s === "number" && typeof row.discharge_p50 === "number" && row.discharge_p50 > 0) {
      meta += ` · river ${(row.discharge_m3s / row.discharge_p50).toFixed(1)}× typical`;
    }
    if (row && row.simulated) meta += " · SIMULATED";
    el.querySelector(".tile-meta").textContent = meta;
    // Order: group rank from the summaries, place order inside the group.
    const s = summaries[p.groupId];
    el.style.order = String((s ? s.rank : 50) * 10 + (idx % 10));
    el.setAttribute("aria-label",
      `${p.name}, ${p.country} — monitored, ${sev ? sev.label : "loading"}${score !== null ? `, index ${(score * 100).toFixed(0)} percent` : ""}, dominant hazard ${dominant.toLowerCase()}`);
  });

  // --- candidate tiles (keyed once) ---
  const rows = ((state.watchlist || {}).results || []);
  const candKeys = rows.map(r => r.name).join("|");
  if (rows.length && candidateGrid.dataset.keys !== candKeys) {
    candidateGrid.innerHTML = rows.map(r => candidateTileHtml(r.name)).join("");
    candidateGrid.dataset.keys = candKeys;
  }
  Array.from(candidateGrid.children).forEach((el, idx) => {
    const r = rows[idx];
    if (!r) return;
    const act = Number(r.activity_score) || 0;
    const sev = getSeverityConfig(act);
    el.querySelector(".tile-name").textContent = r.name;
    el.querySelector(".tile-severity").innerHTML =
      `<span class="tabular-nums">activity ${act.toFixed(2)}</span> <span class="tile-model-tag">ACTIVITY MODEL</span>`;
    const bar = el.querySelector(".tile-bar i");
    bar.style.width = `${Math.round(act * 100)}%`;
    bar.style.background = sev.colorHex;
    el.style.borderLeftColor = sev.colorHex;
    const badges = [];
    if (r.aqi_covered) badges.push("AQI");
    if (r.cell_scale === "creek") badges.push("creek cell");
    el.querySelector(".tile-meta").textContent =
      `${r.country || ""} · seis ${(Number(r.seismic_score) || 0).toFixed(2)} · flood ${(Number(r.flood_score) || 0).toFixed(2)}${badges.length ? " · " + badges.join(" · ") : ""}`;
    el.style.order = String(idx);
    el.setAttribute("aria-label",
      `${r.name}, ${r.country || ""} — watchlist candidate, not monitored, activity ${act.toFixed(2)}`);
  });

  // Filter + live region count.
  const filter = document.getElementById("place-filter");
  const status = document.getElementById("grid-status");
  const shown = applyFilter(monitoredGrid, filter && filter.value) +
    applyFilter(candidateGrid, filter && filter.value);
  if (status) status.textContent = `${shown} places shown`;
}

export function setupTiles() {
  const onTap = (e) => {
    const tile = e.target.closest("[data-place], [data-candidate]");
    if (!tile) return;
    if (tile.dataset.place) selectPlace(tile.dataset.place);
    else selectCandidate(tile.dataset.candidate);
  };
  const mon = document.getElementById("tile-grid-monitored");
  const cand = document.getElementById("tile-grid-candidates");
  if (mon) mon.addEventListener("click", onTap);
  if (cand) cand.addEventListener("click", onTap);
  const filter = document.getElementById("place-filter");
  if (filter) filter.addEventListener("input", () => renderTiles());
}
