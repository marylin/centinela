// Side rail: the same 23 places as mini items while a detail view owns the
// page. Keyed once, updated in place, ordered by CSS order (tap-race rule).

import { state, selectPlace, selectCandidate } from "./state.js";
import { getSeverityConfig } from "./severity.js";
import { escapeHtml } from "./util.js";

export function renderRail() {
  const list = document.getElementById("rail-list");
  if (!list) return;

  const items = [];
  (state.groups || []).forEach(g => (g.places || []).forEach(p =>
    items.push({ key: `p:${p.name}`, name: p.name, kind: "place", groupId: g.id })));
  (((state.watchlist || {}).results) || []).forEach(r =>
    items.push({ key: `c:${r.name}`, name: r.name, kind: "candidate" }));

  const keys = items.map(i => i.key).join("|");
  if (list.dataset.keys !== keys) {
    list.innerHTML = items.map(i => `
      <button type="button" class="rail-item${i.kind === "candidate" ? " rail-candidate" : ""}"
              data-kind="${i.kind}" data-name="${escapeHtml(i.name)}">
        <span class="rail-name"></span>
        <span class="rail-meta tabular-nums"></span>${i.kind === "candidate" ? '<span class="badge tile-badge">watch</span>' : ""}
      </button>`).join("");
    list.dataset.keys = keys;
  }

  const summaries = state.groupSummaries || {};
  Array.from(list.children).forEach((el, idx) => {
    const item = items[idx];
    if (!item) return;
    el.querySelector(".rail-name").textContent = item.name;
    let score = null;
    if (item.kind === "place") {
      const row = (state.riskByGroup[item.groupId] || []).find(r => r.municipality === item.name);
      score = row ? Number(row.risk_score) || 0 : null;
      // ONE merged list: everything orders by its score, worst first.
      el.style.order = String(score === null ? 1500 : 1000 - Math.round(score * 1000));
    } else {
      const r = (((state.watchlist || {}).results) || []).find(x => x.name === item.name);
      score = r ? Number(r.activity_score) || 0 : null;
      el.style.order = String(score === null ? 1500 : 1000 - Math.round(score * 1000));
    }
    const sev = score === null ? null : getSeverityConfig(score);
    el.style.borderLeftColor = sev ? sev.colorHex : "var(--border-color)";
    el.querySelector(".rail-meta").textContent = score === null ? "" : `${(score * 100).toFixed(0)}%`;
    const active = !!(state.selection && state.selection.name === item.name);
    el.classList.toggle("active", active);
    el.setAttribute("aria-current", String(active));
  });
}

export function setupRail() {
  const list = document.getElementById("rail-list");
  if (!list) return;
  list.addEventListener("click", (e) => {
    const item = e.target.closest("[data-name]");
    if (!item) return;
    if (item.dataset.kind === "candidate") selectCandidate(item.dataset.name);
    else selectPlace(item.dataset.name);
  });
}
