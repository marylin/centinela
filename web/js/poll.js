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
    const [summaries, seismic] = await Promise.all([
      api.getGroupSummaries(),
      api.getSeismicEvents(),
    ]);
    const map = {};
    (summaries.groups || []).forEach((g, i) => { map[g.id] = { ...g, rank: i }; });
    state.groupSummaries = map;
    if (seismic && Array.isArray(seismic.events)) state.seismic = seismic;

    // Per-group risk rows: the backend caches the index 60s per group, so
    // seven parallel calls are cheap and keep every tile honest.
    const ids = (state.groups || []).map(g => g.id);
    const rows = await Promise.all(ids.map(id => api.getRisk(id).catch(() => null)));
    ids.forEach((id, i) => { if (rows[i]) state.riskByGroup[id] = rows[i]; });
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
