// Poll scheduler. Index mode is deliberately calm: group summaries + per-group
// risk + the seismic feed every 60s, the watchlist every 10 minutes. The 5s
// telemetry poll only exists while a MONITORED place is selected (Phase B
// wires it); candidates and the index grid never poll fast.

import { state, notify } from "./state.js";
import * as api from "./api.js";

export const CADENCE = { index: 60000, watchlist: 600000, detail: 5000 };

export async function refreshRegistry() {
  const groups = await api.getPlaces();
  if (Array.isArray(groups) && groups.length) {
    state.groups = groups;
    notify("registry");
  }
}

export async function refreshIndexData() {
  try {
    // ONE bulk call for every group's index rows (one warehouse pass server
    // side) + the seismic feed. This is what keeps first paint fast.
    const [all, seismic] = await Promise.all([
      api.getRiskAll(),
      api.getSeismicEvents(),
    ]);
    (all.groups || []).forEach(g => { state.riskByGroup[g.id] = g.rows || []; });
    if (seismic && Array.isArray(seismic.events)) state.seismic = seismic;
    notify("index-data");
  } catch (err) {
    console.error("Index refresh failed:", err);
  }
}

export async function refreshWatchlist() {
  try {
    state.watchlist = await api.getWatchlist();
    notify("watchlist");
  } catch (err) {
    console.error("Watchlist refresh failed:", err);
  }
}

export function startPolling() {
  setInterval(refreshIndexData, CADENCE.index);
  setInterval(refreshWatchlist, CADENCE.watchlist);
}
