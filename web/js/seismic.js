// Seismic events. Detail view: a NEARBY-only feed card (~800 km of the
// selection) with click-to-focus; a focused event owns the map and shows a
// SEISMIC-ONLY content block while basin panels hide. Index view: the
// WORLDWIDE list; clicking an event opens the nearest place's detail with
// that event focused.

import { state, notify, placeByName, candidateByName, selectPlace, selectCandidate } from "./state.js";
import { getSeismicFocus } from "./api.js";
import { getMagnitudeSeverity } from "./severity.js";
import { escapeHtml, formatRelativeTime, haversineMeters } from "./util.js";
import { renderMap } from "./map.js";
import { renderConditions } from "./conditions.js";

const NEAR_RADIUS_M = 800000;

function selectionCoords() {
  const sel = state.selection;
  if (!sel) return null;
  if (sel.kind === "candidate") {
    const c = candidateByName(sel.name);
    return c && typeof c.lat === "number" ? { lat: c.lat, lng: c.lng } : null;
  }
  const p = placeByName(sel.name);
  return p && p.anchor ? { lat: p.anchor.lat, lng: p.anchor.lng } : null;
}

export function renderSeismicPanel() {
  const listEl = document.getElementById("seismic-feed-body");
  const chipsEl = document.getElementById("seismic-region-chips");
  if (!listEl) return;

  const focus = state.seismicFocus;
  const focusBox = document.getElementById("seismic-focus-content");
  if (focusBox) {
    if (focus && focus.event) {
      const ev = focus.event;
      const mag = Number(ev.magnitude) || 0;
      const sev = getMagnitudeSeverity(mag);
      const depth = typeof ev.depth_km === "number" ? ` at ${ev.depth_km.toFixed(0)} km depth` : "";
      focusBox.hidden = false;
      focusBox.style.borderLeft = `4px solid ${sev.colorHex}`;
      focusBox.innerHTML = `
        <div class="focus-head">
          <strong>M ${mag.toFixed(1)} ${escapeHtml(ev.place || "event")}</strong>
          ${ev.simulated ? '<span class="badge badge-simulated">SIMULATED</span>' : '<span class="badge scope-chip">LIVE · USGS</span>'}
          <button type="button" class="btn btn-sm" id="seismic-focus-close">Close</button>
        </div>
        <p class="focus-body">${formatRelativeTime(ev.time)}${depth}. ${escapeHtml(focus.narration || "")}</p>
        <p class="focus-note">SEISMIC-ONLY view: flood and landslide conditions are not modeled for this location.</p>`;
    } else {
      focusBox.hidden = true;
    }
  }

  const coords = selectionCoords();
  const all = (state.seismic.events || []).filter(ev => typeof ev.magnitude === "number");
  const events = coords
    ? all.filter(ev => typeof ev.latitude === "number" &&
        haversineMeters(coords, { lat: ev.latitude, lng: ev.longitude }) <= NEAR_RADIUS_M)
    : all;

  const scopeNote = `within ~800 km of ${escapeHtml((state.selection || {}).name || "the selection")}`;
  const header = `<div class="seismic-filter-bar"><span>M 4.5+ events, last 48h, ${scopeNote}</span></div>`;

  const rows = events.slice(0, 10).map(ev => {
    const sev = getMagnitudeSeverity(ev.magnitude);
    const tag = ev.simulated ? '<span class="badge badge-simulated">SIMULATED</span>' : '<span class="seismic-source-tag">LIVE · USGS</span>';
    const depth = typeof ev.depth_km === "number" ? `${ev.depth_km.toFixed(0)} km depth` : "depth unknown";
    return `
      <button type="button" class="seismic-row" data-event="${escapeHtml(ev.id)}" style="border-left:3px solid ${sev.colorHex};">
        <span class="seismic-mag tabular-nums" style="color:${sev.colorHex}">M ${ev.magnitude.toFixed(1)}</span>
        <span class="seismic-info">
          <span>${escapeHtml(ev.place || "Unknown location")} ${tag}</span>
          <span class="seismic-meta tabular-nums">${formatRelativeTime(ev.time)} · ${depth}</span>
        </span>
      </button>`;
  }).join("");

  listEl.innerHTML = header + (rows ||
    `<div class="empty-alerts">No magnitude 4.5+ earthquakes ${scopeNote} in the last 48 hours. Worldwide activity is on the All-places page.</div>`);

  if (chipsEl) {
    const regions = (state.seismic.active_regions || []).slice(0, 6);
    chipsEl.innerHTML = regions.map(r =>
      `<span class="badge scope-chip">${escapeHtml(r.region)} · ${r.count}</span>`).join("");
  }
}

export async function focusEvent(id) {
  // Immediate feedback: the focus fetch generates narration server-side and
  // can take several seconds; a silent wait reads as a dead click.
  const focusBox = document.getElementById("seismic-focus-content");
  if (focusBox) {
    focusBox.hidden = false;
    focusBox.innerHTML = `<div class="empty-alerts">Loading event details…</div>`;
  }
  try {
    const data = await getSeismicFocus(id);
    if (!data || !data.event) return;
    state.seismicFocus = data;
    notify("seismic-focus");
    renderSeismicPanel();
    renderMap();
    const ev = data.event;
    if (typeof ev.latitude === "number") {
      renderConditions(ev.latitude, ev.longitude, "at the epicenter");
    }
  } catch (err) {
    console.error("Seismic focus failed:", err);
    if (focusBox) focusBox.innerHTML = `<div class="empty-alerts">Event details unavailable right now.</div>`;
  }
}

// --- Worldwide list (index page) -------------------------------------------

function nearestPlaceTo(lat, lng) {
  let best = null, bestDist = Infinity;
  (state.groups || []).forEach(g => (g.places || []).forEach(p => {
    if (!p.anchor) return;
    const d = haversineMeters({ lat, lng }, { lat: p.anchor.lat, lng: p.anchor.lng });
    if (d < bestDist) { bestDist = d; best = { kind: "place", name: p.name }; }
  }));
  (((state.watchlist || {}).results) || []).forEach(c => {
    if (typeof c.lat !== "number") return;
    const d = haversineMeters({ lat, lng }, { lat: c.lat, lng: c.lng });
    if (d < bestDist) { bestDist = d; best = { kind: "candidate", name: c.name }; }
  });
  return best ? { ...best, km: Math.round(bestDist / 1000) } : null;
}

export function renderWorldwideEvents() {
  const el = document.getElementById("world-events-body");
  if (!el) return;
  const events = (state.seismic.events || [])
    .filter(ev => typeof ev.magnitude === "number")
    .slice(0, 12);
  if (!events.length) {
    el.innerHTML = `<div class="empty-alerts">Loading the live USGS feed…</div>`;
    return;
  }
  el.innerHTML = events.map(ev => {
    const sev = getMagnitudeSeverity(ev.magnitude);
    const near = (typeof ev.latitude === "number") ? nearestPlaceTo(ev.latitude, ev.longitude) : null;
    const tag = ev.simulated ? '<span class="badge badge-simulated">SIMULATED</span>' : '<span class="seismic-source-tag">LIVE · USGS</span>';
    return `
      <button type="button" class="seismic-row" data-world-event="${escapeHtml(ev.id)}"
              style="border-left:3px solid ${sev.colorHex};">
        <span class="seismic-mag tabular-nums" style="color:${sev.colorHex}">M ${ev.magnitude.toFixed(1)}</span>
        <span class="seismic-info">
          <span>${escapeHtml(ev.place || "Unknown location")} ${tag}</span>
          <span class="seismic-meta tabular-nums">${formatRelativeTime(ev.time)}${near ? ` · nearest: ${escapeHtml(near.name)} (${near.km.toLocaleString()} km)` : ""}</span>
        </span>
      </button>`;
  }).join("");
}

export function setupWorldwideEvents() {
  const card = document.getElementById("world-events-card");
  if (!card) return;
  card.addEventListener("click", (e) => {
    const row = e.target.closest("[data-world-event]");
    if (!row) return;
    const ev = (state.seismic.events || []).find(x => x.id === row.dataset.worldEvent);
    if (!ev || typeof ev.latitude !== "number") return;
    const near = nearestPlaceTo(ev.latitude, ev.longitude);
    if (!near) return;
    if (near.kind === "candidate") selectCandidate(near.name);
    else selectPlace(near.name);
    focusEvent(ev.id);
  });
}

export function clearSeismicFocus() {
  if (!state.seismicFocus) return;
  state.seismicFocus = null;
  notify("seismic-focus");
  renderSeismicPanel();
  renderMap();
  const sel = state.selection;
  if (sel) {
    const coords = selectionCoords();
    if (coords) renderConditions(coords.lat, coords.lng, `at ${sel.name}`);
  }
}

export function setupSeismicPanel() {
  const panel = document.getElementById("seismic-panel");
  if (!panel) return;
  panel.addEventListener("click", (e) => {
    if (e.target.id === "seismic-focus-close" || e.target.closest("#seismic-focus-close")) {
      clearSeismicFocus();
      return;
    }
    const row = e.target.closest("[data-event]");
    if (row) focusEvent(row.dataset.event);
  });
}
