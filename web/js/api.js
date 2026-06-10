// One function per backend endpoint. Every fetch funnels through request()
// so offline detection lives in exactly one place.

const API_BASE = window.location.origin;

let offlineCallback = null;
export function onOfflineChange(fn) { offlineCallback = fn; }

async function request(path, options) {
  try {
    const res = await fetch(`${API_BASE}${path}`, options);
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    if (offlineCallback) offlineCallback(false);
    return await res.json();
  } catch (err) {
    if (offlineCallback) offlineCallback(true);
    throw err;
  }
}

export const getPlaces = () => request("/places");
export const getRisk = (basin) => request(`/risk?basin=${encodeURIComponent(basin)}`);
export const getRiskAll = () => request("/risk-all");
export const getGroupSummaries = () => request("/group-summaries");
export const getWatchlist = () => request("/watchlist");
export const getAlert = (basin) => request(`/alert?basin=${encodeURIComponent(basin)}`);
export const getUiStrings = (lang) => request(`/ui-strings?lang=${encodeURIComponent(lang)}`);
export const getRiskHistory = (basin) => request(`/risk-history?basin=${encodeURIComponent(basin)}`);
export const getTelemetryHistory = (basin, place) =>
  request(`/telemetry-history?basin=${encodeURIComponent(basin)}${place ? `&place=${encodeURIComponent(place)}` : ""}`);
export const getSeismicEvents = () => request("/seismic-events");
export const getSeismicFocus = (id) => request(`/seismic-focus?id=${encodeURIComponent(id)}`);
export const getLocationConditions = (lat, lng) => request(`/location-conditions?lat=${lat}&lng=${lng}`);
export const getIncidents = () => request("/incidents");
export const getAutonomousHeals = () => request("/autonomous-heals");
export const getConnectorStatus = (basin) => request(`/connector-status?basin=${encodeURIComponent(basin)}`);
export const postBreak = () => request("/break", { method: "POST" });
export const postHeal = () => request("/heal", { method: "POST" });
export const reopenIncident = (id) => request(`/incidents/${encodeURIComponent(id)}/reopen`, { method: "POST" });
export const clearReopen = () => request("/incidents/clear-reopen", { method: "POST" });
export const subscribePlace = (token, basin) => request("/subscribe-place", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ token, basin }),
});
export const unsubscribePlace = (token, basin) => request("/unsubscribe-place", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ token, basin }),
});
export const registerToken = (token) => request("/register-token", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ token }),
});
export const demoInject = (basin, municipality, magnitude) => request("/demo/inject-event", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ basin, municipality, magnitude }),
});
export const demoClear = (basin) => request("/demo/clear-event", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ basin }),
});
