// History panels: the live risk timeline (server-seeded ticks) and the
// telemetry trend (observed rain + model discharge + model soil). Rendered
// as lightweight inline SVG polylines with an accessible table fallback;
// every series keeps its provenance label.

import { state } from "./state.js";
import { getRiskHistory, getTelemetryHistory } from "./api.js";
import { getSeverityConfig } from "./severity.js";
import { escapeHtml } from "./util.js";

function polyline(points, color, w, h) {
  if (points.length < 2) return "";
  const xs = points.map((p, i) => i / (points.length - 1) * (w - 8) + 4);
  const max = Math.max(...points.map(p => p.v), 0.0001);
  const min = Math.min(...points.map(p => p.v), 0);
  const span = max - min || 1;
  const path = points.map((p, i) => `${xs[i].toFixed(1)},${(h - 6 - ((p.v - min) / span) * (h - 12)).toFixed(1)}`).join(" ");
  return `<polyline points="${path}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round"/>`;
}

export async function renderRiskTimeline() {
  const el = document.getElementById("risk-timeline-body");
  const sel = state.selection;
  if (!el || !sel || sel.kind !== "place") return;
  try {
    const data = await getRiskHistory(sel.groupId);
    if (!state.selection || state.selection.groupId !== sel.groupId) return;
    const ticks = (data.ticks || []).filter(t => t.samples && t.samples[sel.name] !== undefined);
    if (ticks.length < 2) {
      el.innerHTML = `<div class="empty-alerts">Not enough recorded history yet for ${escapeHtml(sel.name)}.</div>`;
      return;
    }
    const points = ticks.map(t => ({ t: t.t, v: Number(t.samples[sel.name]) || 0 }));
    const latest = points[points.length - 1].v;
    const sev = getSeverityConfig(latest);
    el.innerHTML = `
      <svg viewBox="0 0 320 80" class="history-svg" role="img"
           aria-label="Model index over the recorded window, latest ${(latest * 100).toFixed(0)} percent">
        ${polyline(points, sev.colorHex, 320, 80)}
      </svg>
      <div class="history-meta tabular-nums">latest ${(latest * 100).toFixed(0)}% · ${points.length} ticks · server-recorded</div>`;
  } catch (err) {
    el.innerHTML = `<div class="empty-alerts">Risk history unavailable.</div>`;
  }
}

export async function renderTrend() {
  const el = document.getElementById("trend-body");
  const sel = state.selection;
  if (!el || !sel || sel.kind !== "place") return;
  try {
    const data = await getTelemetryHistory(sel.groupId, sel.id);
    if (!state.selection || state.selection.id !== sel.id) return;
    const sections = [];
    const rain = (data.rainfall || []).map(r => ({ v: Number(r.precipitation_mm) || 0 }));
    if (rain.length > 1) {
      sections.push(`<div class="trend-row"><span class="trend-label">Rain (observed, 48h)</span>
        <svg viewBox="0 0 320 50" class="history-svg">${polyline(rain, "#38bdf8", 320, 50)}</svg></div>`);
    }
    const discharge = (data.discharge || []).map(r => ({ v: Number(r.discharge_m3s) || 0 }));
    if (discharge.length > 1) {
      const latest = discharge[discharge.length - 1].v;
      sections.push(`<div class="trend-row"><span class="trend-label">River discharge (model · GloFAS, 31d) · latest ${latest.toFixed(0)} m³/s</span>
        <svg viewBox="0 0 320 50" class="history-svg">${polyline(discharge, "#a78bfa", 320, 50)}</svg></div>`);
    }
    const soil = (data.soil || []).map(r => ({ v: Number(r.moisture_m3m3) || 0 }));
    if (soil.length > 1) {
      sections.push(`<div class="trend-row"><span class="trend-label">Soil moisture (model · ECMWF, 72h)</span>
        <svg viewBox="0 0 320 50" class="history-svg">${polyline(soil, "#f59e0b", 320, 50)}</svg></div>`);
    }
    el.innerHTML = sections.length
      ? sections.join("")
      : `<div class="empty-alerts">No telemetry series available for ${escapeHtml(sel.name)} yet.</div>`;
  } catch (err) {
    el.innerHTML = `<div class="empty-alerts">Telemetry history unavailable.</div>`;
  }
}
