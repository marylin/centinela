// Bootstrap + hash router + view switching. Phase A: the index grid is live;
// tile selection routes to the detail view shell (full detail lands in
// Phase B; until then the shell shows the selection honestly).

import { state, subscribe, clearSelection } from "./state.js";
import { onOfflineChange } from "./api.js";
import { renderTiles, setupTiles } from "./tiles.js";
import { refreshRegistry, refreshIndexData, refreshWatchlist, startPolling } from "./poll.js";
import { setupNotifications } from "./notify.js";
import { setupDiagnostics } from "./diagnostics.js";
import { setupRail } from "./rail.js";
import { setupDetail } from "./detail.js";
import { renderMap } from "./map.js";

// Maps loader callback: modules are module-scoped, so the bootstrap callback
// must be attached to window explicitly.
window.onMapsReadyCallback = () => {
  window.googleMapsReady = true;
  if (state.selection) renderMap();
};

function applyView() {
  const app = document.getElementById("app");
  if (!app) return;
  const detail = !!state.selection;
  app.classList.toggle("view-detail", detail);
  app.classList.toggle("view-index", !detail);
  const detailView = document.getElementById("detail-view");
  const indexView = document.getElementById("index-view");
  if (detailView) detailView.hidden = !detail;
  if (indexView) indexView.hidden = detail;
  if (detail) {
    const heading = document.getElementById("detail-heading");
    if (heading) {
      heading.textContent = state.selection.name;
      heading.focus();
    }
    document.title = `Centinela · ${state.selection.name}`;
    const kindEl = document.getElementById("detail-kind");
    if (kindEl) kindEl.textContent = state.selection.kind === "candidate"
      ? "Watchlist candidate · NOT MONITORED" : "Monitored place · MODEL INDEX";
    location.hash = state.selection.kind === "candidate"
      ? `#/candidate/${encodeURIComponent(state.selection.name)}`
      : `#/place/${encodeURIComponent(state.selection.id)}`;
  } else {
    document.title = "Centinela · All places";
    if (location.hash) history.replaceState(null, "", location.pathname);
  }
}

function setupRouting() {
  window.addEventListener("hashchange", () => {
    if (!location.hash && state.selection) clearSelection();
  });
  const back = document.getElementById("back-to-grid");
  if (back) back.addEventListener("click", () => clearSelection());
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.selection) clearSelection();
  });
}

function setupOfflineBanner() {
  onOfflineChange((offline) => {
    if (state.offline === offline) return;
    state.offline = offline;
    const banner = document.getElementById("api-offline-banner");
    if (banner) banner.classList.toggle("hidden", !offline);
  });
}

function startClock() {
  const el = document.getElementById("system-time");
  if (!el) return;
  const tick = () => { el.textContent = new Date().toLocaleTimeString(); };
  tick();
  setInterval(tick, 1000);
}

document.addEventListener("DOMContentLoaded", async () => {
  setupOfflineBanner();
  setupTiles();
  setupRail();
  setupDetail();
  setupRouting();
  setupNotifications();
  setupDiagnostics();
  startClock();

  subscribe((topic) => {
    if (topic === "selection") applyView();
    if (["registry", "index-data", "watchlist"].includes(topic)) renderTiles();
    if (topic === "demo-changed") refreshIndexData();
  });

  await refreshRegistry();
  renderTiles();
  refreshIndexData();
  refreshWatchlist();
  startPolling();
});
