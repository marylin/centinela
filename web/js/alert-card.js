// The public alert card: the 5-field structured alert (Hazard / Where /
// Action / When / Source), severity-tiered guidance, and plain advisories.
// Copy carried over from the retired Public Alert mode; honest and fixed,
// never generated.

import { state, riskRowFor } from "./state.js";
import { getSeverityConfig } from "./severity.js";
import { escapeHtml } from "./util.js";

const HAZARD_LABELS = {
  FLOOD: "Flood",
  LANDSLIDE: "Landslide",
  SEISMIC: "Earthquake / seismic activity",
};

const HAZARD_ACTIONS = {
  FLOOD: "Move to higher ground, away from the river channel and low-lying areas. Do not cross moving water.",
  LANDSLIDE: "Move away from steep slopes and the base of hillsides; avoid narrow valleys and drainage paths.",
  SEISMIC: "Drop, cover, and hold on. After shaking stops, move away from damaged structures to open ground.",
};

const ALERT_SOURCE = "Unidad Nacional para la Gestión del Riesgo de Desastres (UNGRD)";

const BASIN_HISTORY = {
  rio_cauca: "The Río Cauca basin has a documented history of rainy-season flooding.",
  rio_magdalena: "The Río Magdalena basin experiences seasonal flooding during Colombia's rainy seasons.",
};

function guidanceFor(statusWord, quakeWatch) {
  if (quakeWatch && (statusWord === "CRITICAL" || statusWord === "DANGER")) {
    return {
      meaning: "Strong seismic activity has been detected nearby. Expect aftershocks.",
      items: [
        HAZARD_ACTIONS.SEISMIC,
        "Move to open ground away from buildings and power lines.",
        "Expect aftershocks; do not re-enter damaged structures.",
        "Follow instructions from civil protection authorities.",
      ],
    };
  }
  if (quakeWatch && statusWord === "WARNING") {
    return {
      meaning: "Elevated hazard signals for this area. Stay alert.",
      items: [
        "Review your earthquake plan and identify the nearest open assembly area.",
        "Keep emergency supplies and documents reachable.",
        "Follow official channels for updates.",
      ],
    };
  }
  if (quakeWatch) {
    return {
      meaning: "No elevated hazard signals right now. This area is monitored for earthquake activity.",
      items: [
        "Know your nearest open assembly area (park, plaza, stadium).",
        "Secure heavy furniture and keep an emergency kit reachable.",
        "Stay informed via local safety advisories and public announcements.",
      ],
    };
  }
  if (statusWord === "CRITICAL") {
    return {
      meaning: "Severe risk of flood, landslide, or seismic activity. Immediate threat to life and property.",
      items: [
        "EVACUATE IMMEDIATELY to higher ground.",
        "Avoid low-lying areas, river catchments, and steep slopes.",
        "Follow instructions from civil protection authorities without delay.",
        "Check on neighbors and vulnerable family members if safe to do so.",
      ],
    };
  }
  if (statusWord === "DANGER") {
    return {
      meaning: "High hazard probability detected. Conditions are deteriorating rapidly.",
      items: [
        "PREPARE TO EVACUATE. Secure emergency supply kits.",
        "Move valuable items, electronics, and documents to upper floors.",
        "Stand by and monitor official radio or messaging channels for evacuation orders.",
        "Avoid crossing flooded roads or flowing water.",
      ],
    };
  }
  if (statusWord === "WARNING") {
    return {
      meaning: "Moderate risk. Precautionary measures and vigilance are advised.",
      items: [
        "STAY VIGILANT. Monitor water levels in local streams and catchments.",
        "Review your family emergency plans and supply kits.",
        "Avoid steep terrains and non-essential travel in affected zones.",
        "Keep safety devices charged and notification options active.",
      ],
    };
  }
  return {
    meaning: "Hydrological conditions are safe and stable.",
    items: [
      "No immediate actions are required.",
      "Stay informed via local safety advisories and public announcements.",
    ],
  };
}

export function renderAlertCard(alertData) {
  const card = document.getElementById("public-alert-card");
  if (!card) return;
  const sel = state.selection;
  if (!sel || sel.kind !== "place") { card.hidden = true; return; }
  card.hidden = false;

  const row = riskRowFor(sel.name);
  const score = row ? Number(row.risk_score) || 0 : 0;
  const sev = getSeverityConfig(score);
  const statusWord = sev.label.toUpperCase();
  const group = (state.groups || []).find(g => g.id === sel.groupId) || {};
  const quakeWatch = group.kind === "seismic-watch";
  const dominant = ((row && row.dominant_hazard) || (quakeWatch ? "SEISMIC" : "FLOOD")).toUpperCase();
  const g = guidanceFor(statusWord, quakeWatch);
  const asOf = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  card.style.borderLeft = `4px solid ${sev.colorHex}`;
  const statusEl = document.getElementById("alert-status");
  if (statusEl) {
    statusEl.innerHTML = `<span class="public-hero-status" style="color:${sev.colorHex}">${statusWord}</span>
      <span class="alert-meaning">${escapeHtml(sel.name)}: ${escapeHtml(g.meaning)}${row && row.simulated ? ' <span class="badge badge-simulated">SIMULATED</span>' : ""}</span>`;
  }

  const fieldsEl = document.getElementById("alert-fields");
  if (fieldsEl) {
    fieldsEl.innerHTML = `
      <div class="alert-field"><dt>Hazard</dt><dd>${HAZARD_LABELS[dominant] || HAZARD_LABELS.FLOOD}</dd></div>
      <div class="alert-field"><dt>Where</dt><dd>${escapeHtml(sel.name)}</dd></div>
      <div class="alert-field alert-field-wide"><dt>Action</dt><dd>${HAZARD_ACTIONS[dominant] || HAZARD_ACTIONS.FLOOD}</dd></div>
      <div class="alert-field"><dt>When</dt><dd>as of ${asOf}</dd></div>
      <div class="alert-field alert-field-wide"><dt>Source</dt><dd>${ALERT_SOURCE}</dd></div>`;
  }

  const ctx = document.getElementById("alert-context");
  if (ctx) ctx.textContent = BASIN_HISTORY[sel.groupId] || "";

  const guidanceEl = document.getElementById("alert-guidance");
  if (guidanceEl) {
    guidanceEl.innerHTML = g.items.map(item =>
      `<div class="guidance-item"><span class="guidance-item-bullet">&bull;</span><span>${item}</span></div>`).join("");
  }

  // Plain advisories from the live graded alert (selected group only).
  const advEl = document.getElementById("alert-advisories");
  if (advEl) {
    const graded = (alertData && alertData.graded_alert) || [];
    const groupMunis = ((state.groups || []).find(x => x.id === sel.groupId) || { places: [] })
      .places.map(p => p.name);
    const active = graded.filter(a => groupMunis.includes(a.municipality) && a.severity !== "LOW");
    advEl.innerHTML = active.length
      ? active.map(a => {
          const s = getSeverityConfig(a.risk_score);
          const hz = a.dominant_hazard === "FLOOD" ? "River flooding" : a.dominant_hazard === "LANDSLIDE" ? "Landslide" : "Earthquake / seismic";
          return `<div class="plain-warning-card" style="border-left:3px solid ${s.colorHex};">
            <span class="plain-warning-title">${escapeHtml(a.municipality)}</span>
            <span class="plain-warning-body">${hz} risk is currently <strong>${s.label}</strong>.</span>
          </div>`;
        }).join("")
      : `<div class="empty-alerts">No active warnings for this area.</div>`;
  }
}
