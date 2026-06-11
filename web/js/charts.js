// History panels: the live risk timeline (server-seeded ticks) and the
// telemetry trend (observed rain + model discharge + model soil). Rendered
// as lightweight inline SVG sparklines with area fill, point markers and an
// emphasized latest reading; every series keeps its provenance label.

import { state } from "./state.js";
import { getRiskHistory, getTelemetryHistory } from "./api.js";
import { getSeverityConfig } from "./severity.js";
import { escapeHtml } from "./util.js";

// One sparkline: area + line + a few dots + a prominent last point. When
// `domain` is given the y axis is fixed (e.g. risk 0..1) so gridlines mean
// something; otherwise it auto-scales to the series for shape.
function spark(points, color, w, h, opts = {}) {
  if (points.length < 2) return "";
  const pad = 5;
  const xs = points.map((p, i) => pad + (i / (points.length - 1)) * (w - pad * 2));
  const lo = opts.domain ? opts.domain[0] : Math.min(...points.map(p => p.v));
  const hi = opts.domain ? opts.domain[1] : Math.max(...points.map(p => p.v));
  const span = (hi - lo) || 1;
  const y = v => (h - pad) - ((v - lo) / span) * (h - pad * 2);
  const pts = points.map((p, i) => `${xs[i].toFixed(1)},${y(p.v).toFixed(1)}`);

  let grid = "";
  if (opts.gridlines) {
    grid = opts.gridlines.map(g =>
      `<line x1="${pad}" y1="${y(g).toFixed(1)}" x2="${(w - pad).toFixed(1)}" y2="${y(g).toFixed(1)}"
             stroke="#2a3242" stroke-width="1" stroke-dasharray="3 3"/>`).join("");
  }

  const area = `<polygon points="${xs[0].toFixed(1)},${(h - pad).toFixed(1)} ${pts.join(" ")} ${xs[xs.length - 1].toFixed(1)},${(h - pad).toFixed(1)}"
                  fill="${color}" fill-opacity="0.12"/>`;
  const line = `<polyline points="${pts.join(" ")}" fill="none" stroke="${color}"
                  stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;

  const everyN = Math.max(1, Math.ceil(points.length / 7));
  let dots = "";
  points.forEach((p, i) => {
    const last = i === points.length - 1;
    if (i % everyN === 0 || last) {
      dots += `<circle cx="${xs[i].toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="${last ? 3.4 : 1.9}"
                 fill="${last ? color : "#0f141f"}" stroke="${color}" stroke-width="1.3"/>`;
    }
  });
  return grid + area + line + dots;
}

// Wraps a sparkline SVG with subtle y-axis ticks (top/bottom) and x-axis
// endpoints, so each series shows the metric and time window it covers.
function chartBlock(svg, yTop, yBottom, xLeft, xRight) {
  return `<div class="chart">
    <div class="chart-yaxis tabular-nums"><span>${escapeHtml(yTop)}</span><span>${escapeHtml(yBottom)}</span></div>
    <div class="chart-main">${svg}
      <div class="chart-xaxis"><span>${escapeHtml(xLeft)}</span><span>${escapeHtml(xRight)}</span></div>
    </div>
  </div>`;
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
    // Fixed 0..1 risk domain with gridlines at the band edges, so the latest
    // dot's height is meaningful rather than auto-scaled noise.
    const svg = `<svg viewBox="0 0 320 64" class="history-svg" role="img"
           aria-label="Risk index over the recorded window, latest ${(latest * 100).toFixed(0)} percent">
        ${spark(points, sev.colorHex, 320, 64, { domain: [0, 1], gridlines: [0.25, 0.5, 0.75] })}
      </svg>`;
    el.innerHTML = `
      <div class="chart-axis-title">Risk index (%)</div>
      ${chartBlock(svg, "100", "0", "older", "now")}
      <div class="history-meta tabular-nums">latest <strong style="color:${sev.colorHex}">${(latest * 100).toFixed(0)}%</strong> · ${points.length} ticks · server-recorded</div>`;
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

    const rows = [
      { series: (data.rainfall || []).map(r => ({ v: Number(r.precipitation_mm) || 0 })),
        color: "#38bdf8", label: "Rain", unit: "mm", prov: "observed · Google Weather",
        window: "48h ago", yUnit: "mm" },
      { series: (data.discharge || []).map(r => ({ v: Number(r.discharge_m3s) || 0 })),
        color: "#a78bfa", label: "River discharge", unit: "m³/s", prov: "model · GloFAS",
        window: "31d ago", yUnit: "m³/s" },
      { series: (data.soil || []).map(r => ({ v: Number(r.moisture_m3m3) || 0 })),
        color: "#f59e0b", label: "Soil moisture", unit: "m³/m³", prov: "model · ECMWF",
        window: "72h ago", yUnit: "m³/m³" },
    ];

    const fmt = v => (v >= 100 ? v.toFixed(0) : v >= 1 ? v.toFixed(1) : v.toFixed(2));
    const sections = rows.filter(r => r.series.length > 1).map(r => {
      const vals = r.series.map(p => p.v);
      const hi = Math.max(...vals), lo = Math.min(...vals);
      const latest = r.series[r.series.length - 1].v;
      const latestTxt = `${fmt(latest)} ${r.unit}`;
      const svg = `<svg viewBox="0 0 320 38" class="history-svg" role="img"
        aria-label="${escapeHtml(r.label)} in ${escapeHtml(r.yUnit)}, latest ${escapeHtml(latestTxt)}">${spark(r.series, r.color, 320, 38)}</svg>`;
      return `<div class="trend-row">
        <div class="trend-head"><span class="trend-label">${r.label} <span class="trend-unit">(${r.yUnit})</span></span>
          <span class="trend-latest tabular-nums" style="color:${r.color}">${latestTxt}</span></div>
        ${chartBlock(svg, fmt(hi), fmt(lo), r.window, "now")}
        <span class="trend-prov">${r.prov}</span>
      </div>`;
    });

    el.innerHTML = sections.length
      ? sections.join("")
      : `<div class="empty-alerts">No telemetry series available for ${escapeHtml(sel.name)} yet.</div>`;
  } catch (err) {
    el.innerHTML = `<div class="empty-alerts">Telemetry history unavailable.</div>`;
  }
}
