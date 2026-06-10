// Design system: severity scale, hazard iconography, marker builder.
// Carried over verbatim from the monolith so the visual language is identical.

const HAZARD_ICONS = {
  FLOOD: `
    <svg class="hazard-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M12 12c-2-2.67-4-2.67-6 0-2 2.67-4 2.67-6 0"></path>
      <path d="M24 12c-2-2.67-4-2.67-6 0-2 2.67-4 2.67-6 0"></path>
      <path d="M12 18c-2-2.67-4-2.67-6 0-2 2.67-4 2.67-6 0"></path>
      <path d="M24 18c-2-2.67-4-2.67-6 0-2 2.67-4 2.67-6 0"></path>
    </svg>
  `,
  LANDSLIDE: `
    <svg class="hazard-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 20h18L12 4z"></path>
      <circle cx="7" cy="12" r="1" fill="currentColor"></circle>
      <circle cx="9" cy="15" r="1" fill="currentColor"></circle>
      <circle cx="15" cy="11" r="1" fill="currentColor"></circle>
      <circle cx="17" cy="14" r="1.5" fill="currentColor"></circle>
    </svg>
  `,
  SEISMIC: `
    <svg class="hazard-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
      <path d="M2 12h3l2-7 3 14 3-11 2 7 2-4 2 4h3"></path>
    </svg>
  `
};

const HAZARD_INNER_SVGS = {
  FLOOD: `
    <path d="M12 12c-2-2.67-4-2.67-6 0-2 2.67-4 2.67-6 0" />
    <path d="M24 12c-2-2.67-4-2.67-6 0-2 2.67-4 2.67-6 0" />
    <path d="M12 18c-2-2.67-4-2.67-6 0-2 2.67-4 2.67-6 0" />
    <path d="M24 18c-2-2.67-4-2.67-6 0-2 2.67-4 2.67-6 0" />
  `,
  LANDSLIDE: `
    <path d="M3 20h18L12 4z" />
    <circle cx="7" cy="12" r="1" fill="currentColor" />
    <circle cx="9" cy="15" r="1" fill="currentColor" />
    <circle cx="15" cy="11" r="1" fill="currentColor" />
    <circle cx="17" cy="14" r="1.5" fill="currentColor" />
  `,
  SEISMIC: `
    <path d="M2 12h3l2-7 3 14 3-11 2 7 2-4 2 4h3" />
  `
};

const SEVERITY_SCALE = {
  LOW: {
    label: "Low",
    class: "low",
    badgeClass: "badge-low",
    colorHex: "#22c55e",
    icon: `
      <svg class="severity-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"></circle>
        <path d="m9 12 2 2 4-4"></path>
      </svg>
    `
  },
  WARNING: {
    label: "Warning",
    class: "warning",
    badgeClass: "badge-warning",
    colorHex: "#f59e0b",
    icon: `
      <svg class="severity-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path>
        <line x1="12" y1="9" x2="12" y2="13"></line>
        <line x1="12" y1="17" x2="12.01" y2="17"></line>
      </svg>
    `
  },
  DANGER: {
    label: "Danger",
    class: "danger",
    badgeClass: "badge-danger",
    colorHex: "#ef4444",
    icon: `
      <svg class="severity-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon>
        <line x1="12" y1="8" x2="12" y2="12"></line>
        <line x1="12" y1="16" x2="12.01" y2="16"></line>
      </svg>
    `
  },
  CRITICAL: {
    label: "Critical",
    class: "critical",
    badgeClass: "badge-critical",
    colorHex: "#a855f7",
    icon: `
      <svg class="severity-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="m12 3-1.912 5.886H3.886L8.9 12.528l-1.912 5.886L12 14.828l4.912 3.586-1.912-5.886 5.014-3.642h-6.202L12 3z"></path>
      </svg>
    `
  }
};


export function getSeverityConfig(score) {
  if (score >= 0.8) return SEVERITY_SCALE.CRITICAL;
  if (score >= 0.6) return SEVERITY_SCALE.DANGER;
  if (score >= 0.4) return SEVERITY_SCALE.WARNING;
  return SEVERITY_SCALE.LOW;
}

export function getSeverityConfigByLabel(label) {
  const l = (label || "").toUpperCase();
  if (l === "EXTREME" || l === "CRITICAL") return SEVERITY_SCALE.CRITICAL;
  if (l === "HIGH" || l === "DANGER") return SEVERITY_SCALE.DANGER;
  if (l === "MODERATE" || l === "WARNING") return SEVERITY_SCALE.WARNING;
  return SEVERITY_SCALE.LOW;
}

export function getMagnitudeSeverity(mag) {
  if (mag >= 6.0) return SEVERITY_SCALE.CRITICAL;
  if (mag >= 5.0) return SEVERITY_SCALE.DANGER;
  if (mag >= 4.0) return SEVERITY_SCALE.WARNING;
  return SEVERITY_SCALE.LOW;
}

export function getMarkerIconUrl(color, hazard) {
  const innerSvg = HAZARD_INNER_SVGS[hazard] || HAZARD_INNER_SVGS.FLOOD;
  const svg = `
    <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 36 36">
      <path d="M18 2C11.4 2 6 7.4 6 14c0 9 12 20 12 20s12-11 12-20c0-6.6-5.4-12-12-12z" fill="${color}" stroke="#07090f" stroke-width="2"/>
      <circle cx="18" cy="14" r="7" fill="#07090f"/>
      <g transform="translate(12, 8) scale(0.5)" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" fill="none">
        ${innerSvg}
      </g>
    </svg>
  `;
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg.trim())}`;
}

export { HAZARD_ICONS, SEVERITY_SCALE };
