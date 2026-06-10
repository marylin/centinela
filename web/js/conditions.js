// Live conditions block for any coordinate: observed rain + AQI (Google),
// discharge + soil (Open-Meteo models), provenance-labeled. Used by the
// candidate detail and the monitored detail alike.

import { getLocationConditions } from "./api.js";
import { escapeHtml } from "./util.js";

let inFlightKey = null;

export async function renderConditions(lat, lng, label) {
  const el = document.getElementById("conditions-body");
  const head = document.getElementById("conditions-scope");
  if (!el) return;
  if (head) head.textContent = label || "";
  const key = `${lat.toFixed(3)},${lng.toFixed(3)}`;
  if (inFlightKey === key) return;
  inFlightKey = key;
  el.innerHTML = `<div class="empty-alerts">Loading live conditions…</div>`;
  try {
    const d = await getLocationConditions(lat, lng);
    if (inFlightKey !== key) return; // a newer selection took over
    const prov = d.provenance || {};
    const rows = [];
    if (d.rainfall && typeof d.rainfall.total_24h_mm === "number") {
      rows.push(["Rain (24h)", `${d.rainfall.total_24h_mm.toFixed(1)} mm`, prov.rainfall]);
    }
    if (d.air_quality && typeof d.air_quality.aqi === "number") {
      rows.push(["Air quality (UAQI)", `${d.air_quality.aqi}${d.air_quality.category ? ` · ${d.air_quality.category}` : ""}`, prov.air_quality]);
    }
    if (d.river_discharge && typeof d.river_discharge.latest_m3s === "number") {
      const dir = d.river_discharge.direction ? ` · ${d.river_discharge.direction}` : "";
      rows.push(["River discharge", `${d.river_discharge.latest_m3s.toFixed(1)} m³/s${dir}`, prov.river_discharge]);
    }
    if (d.soil_moisture && typeof d.soil_moisture.latest_m3m3 === "number") {
      rows.push(["Soil moisture", `${d.soil_moisture.latest_m3m3.toFixed(3)} m³/m³`, prov.soil_moisture]);
    }
    el.innerHTML = rows.length
      ? rows.map(([k, v, p]) => `
          <div class="conditions-row">
            <span class="conditions-key">${k}</span>
            <span class="conditions-value tabular-nums">${escapeHtml(v)}</span>
            <span class="conditions-prov">${escapeHtml(p || "")}</span>
          </div>`).join("")
      : `<div class="empty-alerts">No live conditions available for this point.</div>`;
  } catch (err) {
    if (inFlightKey === key) {
      el.innerHTML = `<div class="empty-alerts">Live conditions unavailable right now.</div>`;
    }
  } finally {
    if (inFlightKey === key) inFlightKey = null;
  }
}
