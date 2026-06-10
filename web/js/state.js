// Central client state + a tiny subscribe/notify bus. Selection is the spine
// of the new IA: one selected place (monitored or candidate) drives the
// detail view; null selection means the index grid owns the page.

export const state = {
  groups: [],            // resolved registry from /places
  groupSummaries: null,  // group id -> {worst_score, rank, ...}
  riskByGroup: {},       // group id -> risk rows (index rows per place)
  watchlist: null,       // /watchlist payload
  seismic: { events: [], active_regions: [] },
  selection: null,       // {kind: "place"|"candidate", id, name, groupId} | null
  seismicFocus: null,    // /seismic-focus payload when an event owns the map
  offline: false,
};

const listeners = new Set();

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function notify(topic) {
  listeners.forEach(fn => {
    try { fn(topic); } catch (err) { console.error("listener failed:", err); }
  });
}

// --- selection helpers ------------------------------------------------------

export function placeByName(name) {
  for (const g of state.groups) {
    for (const p of (g.places || [])) {
      if (p.name === name) return { ...p, groupId: g.id, groupName: g.name, kind: g.kind, country: g.country };
    }
  }
  return null;
}

export function riskRowFor(name) {
  for (const rows of Object.values(state.riskByGroup)) {
    const row = (rows || []).find(r => r.municipality === name);
    if (row) return row;
  }
  return null;
}

export function candidateByName(name) {
  return ((state.watchlist || {}).results || []).find(r => r.name === name) || null;
}

export function selectPlace(name) {
  const p = placeByName(name);
  if (!p) return;
  state.selection = { kind: "place", id: p.id, name: p.name, groupId: p.groupId };
  notify("selection");
}

export function selectCandidate(name) {
  const c = candidateByName(name);
  if (!c) return;
  state.selection = { kind: "candidate", id: name, name, groupId: null };
  notify("selection");
}

export function clearSelection() {
  state.selection = null;
  state.seismicFocus = null;
  notify("selection");
}
