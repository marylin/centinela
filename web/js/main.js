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
import { setupDetail, setupSubscribeButton, setupListenButton, setupAlertLanguageToggle } from "./detail.js";
import { renderMap } from "./map.js";
import { setupSeismicPanel, setupWorldwideEvents, renderWorldwideEvents, clearSeismicFocus } from "./seismic.js";
import { onDetailShown } from "./map.js";
import { setupPages } from "./pages.js";

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
    // The map lives in this container: now that it is visible it must be
    // resized and recentered or it paints glitched (hidden-init bug).
    onDetailShown();
    const heading = document.getElementById("detail-heading");
    if (heading) {
      heading.textContent = state.selection.name;
      heading.focus();
    }
    document.title = `Centinela · ${state.selection.name}`;
    const kindEl = document.getElementById("detail-kind");
    if (kindEl) kindEl.textContent = state.selection.kind === "candidate"
      ? "Watched from public records (N.A.M. = not actively monitored)"
      : "We measure flood, rain, soil and earthquake signals here around the clock.";
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
  const railToggle = document.getElementById("rail-toggle");
  const rail = document.getElementById("side-rail");
  if (railToggle && rail) {
    railToggle.addEventListener("click", () => {
      const open = rail.classList.toggle("rail-open");
      railToggle.setAttribute("aria-expanded", String(open));
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape" || !state.selection) return;
    // A site-page modal owns Escape while it is open; don't also peel the view.
    const pageModal = document.getElementById("page-modal");
    if (pageModal && pageModal.classList.contains("open")) return;
    // Escape peels back one layer: focus first, then the selection.
    if (state.seismicFocus) clearSeismicFocus();
    else clearSelection();
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

function setupServiceWorker() {
  // Register the worker on every load (not only when notifications are enabled)
  // so the page is controlled from first visit, satisfying PWA install criteria
  // and enabling the offline shell. Registration is idempotent; the
  // notifications flow reuses this same registration for its push token.
  if (!("serviceWorker" in navigator)) return;
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/firebase-messaging-sw.js").catch(() => {});
  });
}

let deferredInstallPrompt = null;
function setupInstallPrompt() {
  const btn = document.getElementById("install-app-btn");
  if (!btn) return;
  window.addEventListener("beforeinstallprompt", (e) => {
    // Android/desktop: stash the event and surface our own button. iOS never
    // fires this (install stays manual via Share > Add to Home Screen).
    e.preventDefault();
    deferredInstallPrompt = e;
    btn.hidden = false;
  });
  btn.addEventListener("click", async () => {
    if (!deferredInstallPrompt) return;
    deferredInstallPrompt.prompt();
    await deferredInstallPrompt.userChoice;
    deferredInstallPrompt = null;
    btn.hidden = true;
  });
  window.addEventListener("appinstalled", () => { btn.hidden = true; });
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

  // View switching subscribes FIRST: the detail renderers must only ever run
  // against a visible container (the map cannot initialize while hidden).
  subscribe((topic) => {
    if (topic === "selection") applyView();
    if (["registry", "index-data", "watchlist"].includes(topic)) { renderTiles(); renderWorldwideEvents(); }
    if (topic === "demo-changed") refreshIndexData();
  });

  setupTiles();
  setupRail();
  setupDetail();
  setupSubscribeButton();
  setupListenButton();
  setupAlertLanguageToggle();
  setupSeismicPanel();
  setupWorldwideEvents();
  setupRouting();
  setupNotifications();
  setupDiagnostics();
  setupPages();
  setupServiceWorker();
  setupInstallPrompt();
  startClock();

  await refreshRegistry();
  renderTiles();
  refreshIndexData();
  refreshWatchlist();
  startPolling();
});
