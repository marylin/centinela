// The public alert card, rendered in the RESIDENT'S LANGUAGE: the copy bundle
// comes from the backend (canonical English translated server-side and
// cached), the language rides on the alert payload, and the live narration
// broadcast arrives pre-translated with an original-English toggle. The
// authority name stays untranslated (proper noun).

import { state, riskRowFor } from "./state.js";
import { getUiStrings } from "./api.js";
import { getSeverityConfig } from "./severity.js";
import { escapeHtml } from "./util.js";

const BASIN_HISTORY = {
  rio_cauca: "The Río Cauca basin has a documented history of rainy-season flooding.",
  rio_magdalena: "The Río Magdalena basin experiences seasonal flooding during Colombia's rainy seasons.",
};

let englishOverride = false; // written-language toggle, reset per selection

export function resetAlertLanguage() { englishOverride = false; }

export function toggleAlertEnglish() { englishOverride = !englishOverride; }

export function setAlertEnglish(v) { englishOverride = !!v; }

export function isAlertEnglish() { return englishOverride; }

// The resident language's own name (autonym), capitalized, for the segmented
// Read/Listen labels. Falls back to the uppercased code if unknown.
function langName(code) {
  const c = code || "en";
  try {
    const n = new Intl.DisplayNames([c], { type: "language" }).of(c);
    return n ? n.charAt(0).toUpperCase() + n.slice(1) : c.toUpperCase();
  } catch (e) {
    return c.toUpperCase();
  }
}

const PLAY = "▶"; // ▶

const bundles = {};       // lang -> bundle (client cache)
let bundleFetching = {};  // lang -> promise

async function bundleFor(lang) {
  const l = lang || "en";
  if (bundles[l]) return bundles[l];
  if (!bundleFetching[l]) {
    bundleFetching[l] = getUiStrings(l)
      .then(d => { bundles[l] = d.bundle; return d.bundle; })
      .catch(() => null)
      .finally(() => { delete bundleFetching[l]; });
  }
  return await bundleFetching[l] || bundles.en || null;
}

function guidanceKey(statusWord, quakeWatch) {
  if (quakeWatch) {
    if (statusWord === "CRITICAL" || statusWord === "DANGER") return "quake_high";
    if (statusWord === "WARNING") return "quake_warning";
    return "quake_low";
  }
  return statusWord.toLowerCase() === "low" ? "low" : statusWord.toLowerCase();
}

export async function renderAlertCard(alertData) {
  const card = document.getElementById("public-alert-card");
  if (!card) return;
  const sel = state.selection;
  if (!sel || sel.kind !== "place") { card.hidden = true; return; }
  card.hidden = false;

  const nativeLang = (alertData && alertData.lang) || "en";
  const lang = englishOverride ? "en" : nativeLang;
  const b = await bundleFor(lang) || (await bundleFor("en"));
  if (!b || !state.selection || state.selection.name !== sel.name) return;

  const row = riskRowFor(sel.name);
  const score = row ? Number(row.risk_score) || 0 : 0;
  const sev = getSeverityConfig(score);
  const statusWord = sev.label.toUpperCase();
  const group = (state.groups || []).find(g => g.id === sel.groupId) || {};
  const quakeWatch = group.kind === "seismic-watch";
  const dominant = ((row && row.dominant_hazard) || (quakeWatch ? "SEISMIC" : "FLOOD")).toUpperCase();
  const g = b.guidance[guidanceKey(statusWord, quakeWatch)] || b.guidance.low;
  const statusLabel = (b.status_labels && b.status_labels[statusWord]) || sev.label;
  const asOf = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

  card.style.borderLeft = `4px solid ${sev.colorHex}`;
  const statusEl = document.getElementById("alert-status");
  if (statusEl) {
    statusEl.innerHTML = `<span class="public-hero-status" style="color:${sev.colorHex}">${escapeHtml(statusLabel.toUpperCase())}</span>
      <span class="alert-meaning">${escapeHtml(sel.name)}: ${escapeHtml(g.meaning)}${row && row.simulated ? ` <span class="badge badge-simulated">${escapeHtml(b.ui.simulated)}</span>` : ""}</span>`;
  }

  const fieldsEl = document.getElementById("alert-fields");
  if (fieldsEl) {
    fieldsEl.innerHTML = `
      <div class="alert-field"><dt>${escapeHtml(b.ui.hazard)}</dt><dd>${escapeHtml(b.hazard_labels[dominant] || b.hazard_labels.FLOOD)}</dd></div>
      <div class="alert-field"><dt>${escapeHtml(b.ui.where)}</dt><dd>${escapeHtml(sel.name)}</dd></div>
      <div class="alert-field alert-field-wide"><dt>${escapeHtml(b.ui.action)}</dt><dd>${escapeHtml(b.hazard_actions[dominant] || b.hazard_actions.FLOOD)}</dd></div>
      <div class="alert-field"><dt>${escapeHtml(b.ui.when)}</dt><dd>${escapeHtml(b.ui.as_of)} ${asOf}</dd></div>
      <div class="alert-field alert-field-wide"><dt>${escapeHtml(b.ui.source)}</dt><dd>${escapeHtml(b.ui.source_value)}</dd></div>`;
  }

  const isEnglishPlace = nativeLang === "en";
  const nativeName = langName(nativeLang);

  // Read group: a segmented local/English toggle for the written content.
  // English-native places have nothing to toggle, so the whole row hides.
  const readRow = document.getElementById("alert-read-row");
  const readLocalBtn = document.getElementById("alert-read-local-btn");
  const readEnBtn = document.getElementById("alert-read-en-btn");
  if (readRow) readRow.hidden = isEnglishPlace;
  if (!isEnglishPlace && readLocalBtn && readEnBtn) {
    readLocalBtn.textContent = nativeName;
    readEnBtn.textContent = "English";
    readLocalBtn.classList.toggle("seg-active", !englishOverride);
    readEnBtn.classList.toggle("seg-active", englishOverride);
    readLocalBtn.setAttribute("aria-pressed", String(!englishOverride));
    readEnBtn.setAttribute("aria-pressed", String(englishOverride));
  }

  // Listen group: local-language narration plus an always-English one for
  // visitors and responders. Labeled with the language name and a play glyph.
  const listenBtn = document.getElementById("alert-listen-btn");
  const listenEnBtn = document.getElementById("alert-listen-en-btn");
  const localListenLabel = isEnglishPlace ? `${PLAY} ${b.ui.listen}` : `${PLAY} ${nativeName}`;
  if (listenBtn) {
    if (listenBtn.dataset.playing !== "true") listenBtn.textContent = localListenLabel;
    listenBtn.dataset.idleLabel = localListenLabel;
    listenBtn.dataset.stopLabel = b.ui.stop;
    listenBtn.dataset.loadingLabel = b.ui.loading_audio;
  }
  if (listenEnBtn) {
    listenEnBtn.hidden = isEnglishPlace;
    if (listenEnBtn.dataset.playing !== "true") listenEnBtn.textContent = `${PLAY} English`;
    listenEnBtn.dataset.idleLabel = `${PLAY} English`;
  }

  const ctx = document.getElementById("alert-context");
  if (ctx) ctx.textContent = BASIN_HISTORY[sel.groupId] || "";

  const guidanceEl = document.getElementById("alert-guidance");
  if (guidanceEl) {
    guidanceEl.innerHTML = g.items.map(item =>
      `<div class="guidance-item"><span class="guidance-item-bullet">&bull;</span><span>${escapeHtml(item)}</span></div>`).join("");
  }

  const advEl = document.getElementById("alert-advisories");
  if (advEl) {
    // The 5s poll re-renders this block: remember whether the user had the
    // original-English toggle open so the rewrite never snaps it shut.
    const prevDetails = advEl.querySelector("details.broadcast-original");
    const keepOpen = !!(prevDetails && prevDetails.open);
    const graded = (alertData && alertData.graded_alert) || [];
    const groupMunis = (group.places || []).map(p => p.name);
    const active = graded.filter(a => groupMunis.includes(a.municipality) && a.severity !== "LOW");
    let html = active.length
      ? active.map(a => {
          const s = getSeverityConfig(a.risk_score);
          const hz = b.hazard_labels[a.dominant_hazard] || b.hazard_labels.FLOOD;
          const sLabel = (b.status_labels && b.status_labels[s.label.toUpperCase()]) || s.label;
          return `<div class="plain-warning-card" style="border-left:3px solid ${s.colorHex};">
            <span class="plain-warning-title">${escapeHtml(a.municipality)}</span>
            <span class="plain-warning-body">${escapeHtml(hz)} ${escapeHtml(b.ui.risk_is_currently)} <strong>${escapeHtml(sLabel)}</strong>.</span>
          </div>`;
        }).join("")
      : `<div class="empty-alerts">${escapeHtml(b.ui.no_warnings)}</div>`;

    // Live narration broadcast in the resident's language, original on demand.
    const broadcast = englishOverride
      ? (alertData && alertData.resident_broadcast)
      : (alertData && alertData.broadcast_translated);
    if (broadcast && active.length) {
      const original = alertData.resident_broadcast || "";
      html += `<div class="broadcast-box">
        <p class="advisory-line">${escapeHtml(broadcast)}</p>
        ${lang !== "en" && original ? `<details class="broadcast-original"${keepOpen ? " open" : ""}><summary>${escapeHtml(b.ui.original_english)}</summary><p>${escapeHtml(original)}</p></details>` : ""}
      </div>`;
    }
    advEl.innerHTML = html;
  }
}
