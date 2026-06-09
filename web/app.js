const API_BASE = window.location.origin;

// Initialize Firebase App & Messaging
const firebaseConfig = {
  apiKey: "AIzaSyCD5dZslaW5oKA2chzr5BNyJzHODf4LW04",
  authDomain: "centinela-498622.firebaseapp.com",
  projectId: "centinela-498622",
  storageBucket: "centinela-498622.firebasestorage.app",
  messagingSenderId: "765013283380",
  appId: "1:765013283380:web:9fd5a47da7c575de43f061",
  measurementId: "G-4JWEX55YPH"
};

let messaging;
try {
  firebase.initializeApp(firebaseConfig);
  messaging = firebase.messaging();
} catch (e) {
  console.error("Firebase initialization failed: ", e);
}

// 1. Data Store
const database = {
  risk: [],
  connector: {
    status: "unknown",
    last_sync_time: "never",
    freshness: "unknown"
  },
  alert: null
};

// 2. Application State
let appState = {
  isOffline: false,
  selectedMuni: null,
  syncProgress: 0,
  syncTimer: null,
  freshnessCounter: 0,
  lastSyncTime: null,
  selectedBasin: "rio_cauca",
  reopenedIncidentId: null,
  boundsFitForBasin: null
};

// Map instances & markers
let map = null;
let markers = {};

// 3. Design System & Icon Set Foundation
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

function getSeverityConfig(score) {
  if (score >= 0.8) return SEVERITY_SCALE.CRITICAL;
  if (score >= 0.6) return SEVERITY_SCALE.DANGER;
  if (score >= 0.4) return SEVERITY_SCALE.WARNING;
  return SEVERITY_SCALE.LOW;
}

function getSeverityConfigByLabel(label) {
  const l = (label || '').toUpperCase();
  if (l === 'EXTREME' || l === 'CRITICAL') return SEVERITY_SCALE.CRITICAL;
  if (l === 'HIGH' || l === 'DANGER') return SEVERITY_SCALE.DANGER;
  if (l === 'MODERATE' || l === 'WARNING') return SEVERITY_SCALE.WARNING;
  return SEVERITY_SCALE.LOW;
}

function getMarkerIconUrl(color, hazard) {
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

// 3. Municipality Coordinates for Google Maps
const municipalityCoords = {
  "Cali": { lat: 3.4516, lng: -76.5320 },
  "Yumbo": { lat: 3.5855, lng: -76.4952 },
  "Jamundí": { lat: 3.2610, lng: -76.5394 },
  "Neiva": { lat: 2.9273, lng: -75.2819 },
  "Girardot": { lat: 4.3009, lng: -74.8061 },
  "Honda": { lat: 5.2045, lng: -74.7411 },
  "Alto Pass": { lat: 3.4600, lng: -76.5100 },
  "Oak Creek": { lat: 3.4800, lng: -76.5200 },
  "Silver Valley": { lat: 3.5000, lng: -76.5300 },
  "Pine Ridge": { lat: 3.4000, lng: -76.5000 },
  "Riverdale": { lat: 3.4200, lng: -76.4900 }
};

// Google Maps Dark styles
const darkMapStyles = [
  { elementType: "geometry", stylers: [{ color: "#0d1326" }] },
  { elementType: "labels.text.stroke", stylers: [{ color: "#0d1326" }] },
  { elementType: "labels.text.fill", stylers: [{ color: "#596f90" }] },
  {
    featureType: "administrative.locality",
    elementType: "labels.text.fill",
    stylers: [{ color: "#8a9eb8" }],
  },
  {
    featureType: "poi",
    elementType: "labels.text.fill",
    stylers: [{ color: "#8a9eb8" }],
  },
  {
    featureType: "poi.park",
    elementType: "geometry",
    stylers: [{ color: "#111b30" }],
  },
  {
    featureType: "poi.park",
    elementType: "labels.text.fill",
    stylers: [{ color: "#3b537a" }],
  },
  {
    featureType: "road",
    elementType: "geometry",
    stylers: [{ color: "#1b253b" }],
  },
  {
    featureType: "road",
    elementType: "geometry.stroke",
    stylers: [{ color: "#151e30" }],
  },
  {
    featureType: "road",
    elementType: "labels.text.fill",
    stylers: [{ color: "#4f6585" }],
  },
  {
    featureType: "road.highway",
    elementType: "geometry",
    stylers: [{ color: "#24324f" }],
  },
  {
    featureType: "road.highway",
    elementType: "geometry.stroke",
    stylers: [{ color: "#151e30" }],
  },
  {
    featureType: "road.highway",
    elementType: "labels.text.fill",
    stylers: [{ color: "#6b82a3" }],
  },
  {
    featureType: "water",
    elementType: "geometry",
    stylers: [{ color: "#172d54" }],
  },
  {
    featureType: "water",
    elementType: "labels.text.fill",
    stylers: [{ color: "#3b537a" }],
  },
  {
    featureType: "water",
    elementType: "labels.text.stroke",
    stylers: [{ color: "#172d54" }],
  },
];

// ==========================================================================
// Initialization & Lifecycle
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
  initConsoleLog("Dashboard UI initialized. Attempting connection to local backend API...");
  initClock();
  setupEventHandlers();
  setupNotifications();
  
  appState.mode = "operations";
  
  // If Google Maps script finished loading before DOMContentLoaded
  if (window.googleMapsReady) {
    initMap();
  }

  // Initial fetch
  fetchTelemetry().then(() => {
    startSyncCycle();
  });
});

window.onMapsReadyCallback = () => {
  initMap();
};

// Initialize Google Maps
function initMap() {
  const mapElement = document.getElementById("google-map");
  if (!mapElement || typeof google === "undefined") return;

  const center = appState.selectedBasin === "rio_cauca" ? { lat: 3.43, lng: -76.51 } : { lat: 4.14, lng: -74.94 };
  const zoom = appState.selectedBasin === "rio_cauca" ? 11 : 8;

  map = new google.maps.Map(mapElement, {
    center: center,
    zoom: zoom,
    styles: darkMapStyles,
    disableDefaultUI: true,
    zoomControl: true
  });

  renderMapMarkers();
}

// ==========================================================================
// Clock & Time Helpers
// ==========================================================================
function initClock() {
  const clockEl = document.getElementById("current-time");
  setInterval(() => {
    const now = new Date();
    if (clockEl) {
      clockEl.textContent = now.toLocaleTimeString();
    }
    
    // Update freshness calculation from database if available
    if (appState.lastSyncTime && !appState.isOffline && database.connector.status === "active") {
      appState.freshnessCounter = Math.max(0, Math.floor((new Date() - appState.lastSyncTime) / 1000));
      const freshnessEl = document.getElementById("metric-freshness");
      if (freshnessEl) {
        freshnessEl.textContent = formatFreshness(appState.freshnessCounter);
      }
    }
  }, 1000);
}

// Format seconds into readable timer string
function formatFreshness(seconds) {
  if (seconds < 60) return `${seconds}s ago`;
  const mins = Math.floor(seconds / 60);
  return `${mins}m ${seconds % 60}s ago`;
}

// Parse ISO strings into localized time strings
function parseISOTime(isoString) {
  if (!isoString || isoString === "never") return "--:--:--";
  try {
    const d = new Date(isoString);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch (e) {
    return "--:--:--";
  }
}

// ==========================================================================
// Backend API Telemetry Retrieval
// ==========================================================================
async function fetchTelemetry() {
  try {
    const basinParam = `?basin=${appState.selectedBasin}`;
    const [riskRes, statusRes, alertRes, autoHealsRes, incidentsRes] = await Promise.all([
      fetch(`${API_BASE}/risk${basinParam}`),
      fetch(`${API_BASE}/connector-status${basinParam}`),
      fetch(`${API_BASE}/alert${basinParam}`),
      fetch(`${API_BASE}/autonomous-heals`),
      fetch(`${API_BASE}/incidents`)
    ]);

    if (!riskRes.ok || !statusRes.ok || !alertRes.ok || !autoHealsRes.ok || !incidentsRes.ok) {
      throw new Error(`API error: risk=${riskRes.status}, status=${statusRes.status}, alert=${alertRes.status}, autoHeals=${autoHealsRes.status}, incidents=${incidentsRes.status}`);
    }

    const riskData = await riskRes.json();
    const statusData = await statusRes.json();
    const alertData = await alertRes.json();
    const autoHealsData = await autoHealsRes.json();
    const incidentsData = await incidentsRes.json();

    // Clear offline state if previously offline
    if (appState.isOffline) {
      setBackendOfflineState(false);
      initConsoleLog("Connection restored. Dashboard online.", "telemetry");
    }

    // Update DB
    database.risk = riskData;
    database.connector = statusData;
    database.alert = alertData;

    // Detect reopened incident state
    const clearReopenBtn = document.getElementById("clear-reopen-btn");
    if (alertData.agency_incident && alertData.agency_incident.title.startsWith("REOPENED HISTORICAL INCIDENT")) {
      const match = alertData.agency_incident.title.match(/inc_\d+/);
      if (match) {
        appState.reopenedIncidentId = match[0];
      }
      if (clearReopenBtn) clearReopenBtn.classList.remove("hidden");
    } else {
      appState.reopenedIncidentId = null;
      if (clearReopenBtn) clearReopenBtn.classList.add("hidden");
    }

    // Set last local sync timestamp
    if (statusData.last_sync_time && statusData.last_sync_time !== "never") {
      appState.lastSyncTime = new Date(statusData.last_sync_time);
    } else {
      appState.lastSyncTime = new Date();
    }

    // Refresh UI Components
    renderMapMarkers();
    renderAlerts();
    updateConnectorUI();
    renderAutonomousHeals(autoHealsData);
    renderIncidents(incidentsData);

    // Populate municipality dropdown and refresh public view if in public mode
    populateMuniDropdown();
    if (appState.mode === "public") {
      renderPublicView();
    }

  } catch (err) {
    console.error("Fetch telemetry failed:", err);
    if (!appState.isOffline) {
      setBackendOfflineState(true);
      initConsoleLog("CRITICAL: Local backend API is unreachable. Checking connection...", "error");
    }
  }
}

// Toggle offline banner and interactive states
function setBackendOfflineState(isOffline) {
  appState.isOffline = isOffline;
  
  const banner = document.getElementById("api-offline-banner");
  const systemLed = document.getElementById("system-status-led");
  const systemText = document.getElementById("system-status-text");
  
  if (isOffline) {
    if (banner) banner.classList.remove("hidden");
    if (systemLed) systemLed.className = "led-dot danger-mode";
    if (systemText) systemText.textContent = "API OFFLINE";
    
    // Clear connectors container and show offline
    const container = document.getElementById("pipeline-connectors-container");
    if (container) {
      container.innerHTML = `<div class="empty-alerts">API Unreachable</div>`;
    }
  } else {
    if (banner) banner.classList.add("hidden");
  }
}

// ==========================================================================
// Google Maps Marker Rendering
// ==========================================================================
function renderMapMarkers() {
  if (!map || typeof google === "undefined") return;

  const basinMunis = {
    "rio_cauca": ["Cali", "Yumbo", "Jamundí"],
    "rio_magdalena": ["Honda", "Girardot", "Neiva"]
  };
  const allowedMunis = basinMunis[appState.selectedBasin] || [];
  
  // Filter risk data by selected basin
  const basinRiskData = database.risk.filter(m => allowedMunis.includes(m.municipality));

  // 1. Remove markers that are no longer allowed or in the current basin
  Object.keys(markers).forEach(muniName => {
    if (!allowedMunis.includes(muniName)) {
      markers[muniName].setMap(null);
      delete markers[muniName];
    }
  });

  const bounds = new google.maps.LatLngBounds();
  let hasValidCoords = false;

  basinRiskData.forEach(muni => {
    const coords = municipalityCoords[muni.municipality];
    if (!coords) return;

    const severityConfig = getSeverityConfig(muni.risk_score);
    const color = severityConfig.colorHex;
    const dominant = muni.dominant_hazard || "FLOOD";

    const iconUrl = getMarkerIconUrl(color, dominant);
    const markerIcon = {
      url: iconUrl,
      size: new google.maps.Size(36, 36),
      anchor: new google.maps.Point(18, 34)
    };

    if (markers[muni.municipality]) {
      // Diff / Update existing marker
      const marker = markers[muni.municipality];
      marker.setPosition(coords);
      marker.setIcon(markerIcon);
    } else {
      // Create new marker
      const marker = new google.maps.Marker({
        position: coords,
        map: map,
        title: muni.municipality,
        icon: markerIcon
      });

      marker.addListener("click", () => {
        appState.selectedMuni = muni;
        displayMuniDetails(muni);
        initConsoleLog(`Selected region: ${muni.municipality} (Risk Score: ${muni.risk_score.toFixed(2)})`, "action");
      });

      markers[muni.municipality] = marker;
    }

    bounds.extend(coords);
    hasValidCoords = true;
  });

  // Fit bounds only if we haven't fit bounds for this basin yet
  if (hasValidCoords && appState.boundsFitForBasin !== appState.selectedBasin) {
    map.fitBounds(bounds);
    appState.boundsFitForBasin = appState.selectedBasin;
  }

  // Keep details drawer updated if the selected muni is in the current basin
  if (appState.selectedMuni) {
    const updated = basinRiskData.find(m => m.municipality === appState.selectedMuni.municipality);
    if (updated) {
      displayMuniDetails(updated);
    } else {
      const drawer = document.getElementById("muni-detail-drawer") || document.getElementById("muni-detail-rail");
      if (drawer) {
        drawer.innerHTML = `<div class="drawer-instruction">Select a basin area to view detailed telemetry metrics.</div>`;
      }
      appState.selectedMuni = null;
    }
  }

  // Hide loading overlay once markers are plotted
  const loader = document.getElementById("map-loading-overlay");
  if (loader && basinRiskData.length > 0) {
    loader.classList.add("hidden");
  }
}

// ==========================================================================
// Details Panel / Drawer Rendering
// ==========================================================================
function displayMuniDetails(muni) {
  const drawer = document.getElementById("muni-detail-drawer") || document.getElementById("muni-detail-rail");
  if (!drawer) return;
  
  const severityConfig = getSeverityConfig(muni.risk_score);
  const riskBadge = `<span class="badge ${severityConfig.badgeClass}">${severityConfig.label}</span>`;

  // Calculations for River vs Threshold bullet gauge
  const pct = muni.threshold > 0 ? (muni.river_level_m / muni.threshold) * 100 : 0;
  const pctText = pct.toFixed(0);
  const isExceeded = muni.river_level_m > muni.threshold;
  const exceededText = isExceeded ? '<span class="gauge-exceeded-label" aria-live="polite">[EXCEEDED]</span>' : '';
  const exceededClass = isExceeded ? 'exceeded' : '';
  
  // Dynamic scaling for bullet gauge
  const maxScaleValue = Math.max(muni.threshold * 1.3, muni.river_level_m);
  const fillPct = maxScaleValue > 0 ? (muni.river_level_m / maxScaleValue) * 100 : 0;
  const targetPct = maxScaleValue > 0 ? (muni.threshold / maxScaleValue) * 100 : 0;

  // Render HTML
  drawer.innerHTML = `
    <div class="drawer-grid">
      <div class="muni-detail-header">
        <h3 class="drawer-muni-name">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
            <circle cx="12" cy="10" r="3"></circle>
          </svg>
          ${muni.municipality}
        </h3>
        ${riskBadge}
      </div>

      <!-- Composite Risk Readout -->
      <div class="composite-risk-card">
        <div class="detail-section-header">
          <span class="drawer-label">Composite Risk Index</span>
          <div class="tooltip-wrapper">
            <button type="button" class="tooltip-trigger" aria-label="Composite Risk Info" aria-describedby="risk-tooltip">
              <svg class="info-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="16" x2="12" y2="12"></line>
                <line x1="12" y1="8" x2="12.01" y2="8"></line>
              </svg>
            </button>
            <div id="risk-tooltip" class="tooltip-content" role="tooltip">
              Weighted composite of active hazard models including flood levels, landslide susceptibility, and seismic activity.
            </div>
          </div>
        </div>
        <div class="risk-percentage-display ${severityConfig.class}">
          <span class="risk-percentage-num tabular-nums">${(muni.risk_score * 100).toFixed(0)}%</span>
          <span class="risk-percentage-label">${severityConfig.label} Risk Level</span>
        </div>
      </div>

      <!-- River vs Threshold Bullet Gauge -->
      <div class="bullet-gauge-card">
        <div class="detail-section-header">
          <span class="drawer-label">River vs Alert Threshold</span>
          <div class="tooltip-wrapper">
            <button type="button" class="tooltip-trigger" aria-label="River Level vs Threshold Info" aria-describedby="river-tooltip">
              <svg class="info-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="16" x2="12" y2="12"></line>
                <line x1="12" y1="8" x2="12.01" y2="8"></line>
              </svg>
            </button>
            <div id="river-tooltip" class="tooltip-content" role="tooltip">
              Current river level in meters compared to the alert threshold. Values above 100% represent warning exceedance.
            </div>
          </div>
        </div>
        <div class="bullet-gauge-meta">
          <span class="bullet-gauge-text-val tabular-nums">Level: <strong>${muni.river_level_m.toFixed(2)}m</strong> / Thresh: ${muni.threshold.toFixed(2)}m</span>
          <span class="bullet-gauge-pct tabular-nums ${isExceeded ? 'text-danger font-bold' : ''}">
            ${pctText}% ${exceededText}
          </span>
        </div>
        <div class="bullet-gauge-track" aria-label="River level of ${muni.river_level_m.toFixed(2)}m compared to threshold of ${muni.threshold.toFixed(2)}m (${pctText}%)">
          <div class="bullet-gauge-fill ${exceededClass}" style="width: ${fillPct}%"></div>
          <div class="bullet-gauge-target" style="left: ${targetPct}%" title="Threshold: ${muni.threshold.toFixed(2)}m"></div>
        </div>
      </div>

      <!-- Hazard Sub-scores horizontal bars -->
      <div class="sub-scores-card">
        <div class="detail-section-header">
          <span class="drawer-label">Hazard Sub-Scores</span>
          <div class="tooltip-wrapper">
            <button type="button" class="tooltip-trigger" aria-label="Hazard Sub-scores Info" aria-describedby="hazards-tooltip">
              <svg class="info-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="12" cy="12" r="10"></circle>
                <line x1="12" y1="16" x2="12" y2="12"></line>
                <line x1="12" y1="8" x2="12.01" y2="8"></line>
              </svg>
            </button>
            <div id="hazards-tooltip" class="tooltip-content" role="tooltip">
              Individual hazard index scores modeled for flood propagation, landslide slope slip, and seismic activity.
            </div>
          </div>
        </div>

        <div class="sub-score-item">
          <div class="sub-score-info">
            <span class="sub-score-icon-label">${HAZARD_ICONS.FLOOD} Flood</span>
            <span class="sub-score-val tabular-nums">${muni.flood_score !== undefined ? (muni.flood_score * 100).toFixed(0) + '%' : '--'}</span>
          </div>
          <div class="sub-score-track" aria-label="Flood sub-score: ${muni.flood_score !== undefined ? (muni.flood_score * 100).toFixed(0) + '%' : '--'}">
            <div class="sub-score-fill flood-fill" style="width: ${muni.flood_score !== undefined ? (muni.flood_score * 100) : 0}%"></div>
          </div>
        </div>

        <div class="sub-score-item">
          <div class="sub-score-info">
            <span class="sub-score-icon-label">${HAZARD_ICONS.LANDSLIDE} Landslide</span>
            <span class="sub-score-val tabular-nums">${muni.landslide_score !== undefined ? (muni.landslide_score * 100).toFixed(0) + '%' : '--'}</span>
          </div>
          <div class="sub-score-track" aria-label="Landslide sub-score: ${muni.landslide_score !== undefined ? (muni.landslide_score * 100).toFixed(0) + '%' : '--'}">
            <div class="sub-score-fill landslide-fill" style="width: ${muni.landslide_score !== undefined ? (muni.landslide_score * 100) : 0}%"></div>
          </div>
        </div>

        <div class="sub-score-item">
          <div class="sub-score-info">
            <span class="sub-score-icon-label">${HAZARD_ICONS.SEISMIC} Seismic</span>
            <span class="sub-score-val tabular-nums">${muni.seismic_score !== undefined ? (muni.seismic_score * 100).toFixed(0) + '%' : '--'}</span>
          </div>
          <div class="sub-score-track" aria-label="Seismic sub-score: ${muni.seismic_score !== undefined ? (muni.seismic_score * 100).toFixed(0) + '%' : '--'}">
            <div class="sub-score-fill seismic-fill" style="width: ${muni.seismic_score !== undefined ? (muni.seismic_score * 100) : 0}%"></div>
          </div>
        </div>
      </div>

      <!-- Other Telemetry Metrics -->
      <div class="drawer-divider"></div>
      
      <div class="drawer-metric">
        <span class="drawer-label">Dominant Hazard</span>
        <span class="drawer-val warning text-critical">${muni.dominant_hazard || 'FLOOD'}</span>
      </div>

      <div class="drawer-metric">
        <span class="drawer-label">Rainfall (24h)</span>
        <span class="drawer-val tabular-nums">${muni.rainfall_mm.toFixed(1)} mm</span>
      </div>

      <div class="drawer-metric">
        <span class="drawer-label">Soil Saturation</span>
        <span class="drawer-val tabular-nums">${(muni.soil_saturation * 100).toFixed(0)}%</span>
      </div>

      <div class="drawer-metric">
        <span class="drawer-label">Slope / Susc.</span>
        <span class="drawer-val tabular-nums">${muni.slope_angle_deg !== undefined ? muni.slope_angle_deg.toFixed(0) + '°' : '--'} / ${muni.susceptibility_index !== undefined ? (muni.susceptibility_index * 100).toFixed(0) + '%' : '--'}</span>
      </div>

      <div class="drawer-metric">
        <span class="drawer-label">Earthquake</span>
        <span class="drawer-val tabular-nums">${muni.earthquake_magnitude ? muni.earthquake_magnitude.toFixed(1) + ' Mw' : 'None'}</span>
      </div>
    </div>
  `;
}

// ==========================================================================
// Alerts Engine (Integrates GET /alert data)
// ==========================================================================
function renderAlerts() {
  const container = document.getElementById("alert-feed-container");
  const badge = document.getElementById("active-alert-count");
  if (!container || !badge) return;
  
  const alertData = database.alert;
  
  if (!alertData || !alertData.agency_incident || alertData.agency_incident.affected_municipalities.length === 0) {
    container.innerHTML = `
      <div class="empty-alerts">No active warnings. System telemetry is within safe operating ranges.</div>
      <div class="broadcast-box empty">
        <span class="broadcast-tag">CIVIL PROTECTION BROADCAST</span>
        <p style="padding: 0.5rem 0; font-size: 0.75rem;">No active broadcasts at this time.</p>
      </div>
    `;
    badge.textContent = "0 Alerts";
    badge.className = "badge badge-success";
    return;
  }
  
  const affectedList = alertData.graded_alert ? alertData.graded_alert.filter(a => a.severity === 'HIGH' || a.severity === 'EXTREME').map(a => `${a.municipality} (${a.dominant_hazard})`) : alertData.agency_incident.affected_municipalities;
  const rawAffectedCount = alertData.agency_incident.affected_municipalities.length;
  badge.textContent = `${rawAffectedCount} Alert${rawAffectedCount === 1 ? '' : 's'}`;
  badge.className = "badge badge-error";
  container.innerHTML = "";
  
  // 1. Render Agency Incident Advisory Card
  const incidentCard = document.createElement("div");
  let highestSeverity = "CRITICAL";
  if (alertData.graded_alert && alertData.graded_alert.length > 0) {
    const grades = alertData.graded_alert.map(a => getSeverityConfigByLabel(a.severity));
    if (grades.includes(SEVERITY_SCALE.CRITICAL)) highestSeverity = "CRITICAL";
    else if (grades.includes(SEVERITY_SCALE.DANGER)) highestSeverity = "DANGER";
    else if (grades.includes(SEVERITY_SCALE.WARNING)) highestSeverity = "WARNING";
    else highestSeverity = "LOW";
  }
  const mainSeverity = SEVERITY_SCALE[highestSeverity];

  incidentCard.className = `alert-card alert-${mainSeverity.class}`;
  
  incidentCard.innerHTML = `
    <div class="alert-icon-wrapper">
      ${mainSeverity.icon}
    </div>
    <div class="alert-info">
      <div class="alert-title-row">
        <span class="alert-muni">${alertData.agency_incident.title}</span>
        <span class="alert-type civil-advisory-badge text-${mainSeverity.class}">CIVIL ADVISORY</span>
      </div>
      <p class="alert-desc">${alertData.agency_incident.summary}</p>
      <div class="alert-meta alert-meta-row">
        <span>${mainSeverity.label.toUpperCase()} SEVERITY</span>
        <span>AFFECTED: ${affectedList.join(", ")}</span>
      </div>
    </div>
  `;
  container.appendChild(incidentCard);
  
  // 2. Render Resident Broadcast advisory terminal
  const broadcastCard = document.createElement("div");
  broadcastCard.className = "broadcast-box";
  broadcastCard.innerHTML = `
    <div class="broadcast-header">
      <span class="broadcast-tag">CIVIL PROTECTION SYSTEM BROADCAST</span>
      <span class="broadcast-status pulse-slow">TRANSMITTING</span>
    </div>
    <pre class="broadcast-text">${alertData.resident_broadcast}</pre>
  `;
  container.appendChild(broadcastCard);
}

// ==========================================================================
// Pipeline & Connection Management UI Updates
// ==========================================================================
function updateConnectorUI() {
  const container = document.getElementById("pipeline-connectors-container");
  const systemLed = document.getElementById("system-status-led");
  const systemStatusText = document.getElementById("system-status-text");
  const progressBar = document.getElementById("sync-progress");
  
  if (appState.isOffline || !container) return;

  const connectors = database.connector.connectors || [];
  if (connectors.length === 0) {
    container.innerHTML = `<div class="empty-alerts">No active connectors.</div>`;
    return;
  }

  const anyPaused = connectors.some(c => c.status === "paused");
  if (anyPaused) {
    if (systemLed) systemLed.className = "led-dot danger-mode";
    if (systemStatusText) systemStatusText.textContent = "TELEMETRY DEGRADED";
    if (progressBar) progressBar.classList.add("halted");
  } else {
    if (systemLed) systemLed.className = "led-dot";
    if (systemStatusText) systemStatusText.textContent = "SYSTEM ONLINE";
    if (progressBar) progressBar.classList.remove("halted");
  }

  container.innerHTML = "";
  connectors.forEach(conn => {
    const card = document.createElement("div");
    card.className = "connector-card";
    
    const isPaused = conn.status === "paused";
    const badgeClass = isPaused ? "connector-badge broken" : "connector-badge";
    const badgeText = isPaused ? "PAUSED" : "ACTIVE";
    const freshnessColor = conn.freshness === "FRESH" ? "var(--success)" : "var(--danger)";
    
    card.innerHTML = `
      <div class="connector-header">
        <span class="connector-title">${conn.name}</span>
        <span class="${badgeClass}">${badgeText}</span>
      </div>
      <div class="connector-details-grid">
        <div>
          <span class="connector-detail-label">Last Sync</span>
          <span class="connector-detail-value tabular-nums">${parseISOTime(conn.last_sync_time)}</span>
        </div>
        <div>
          <span class="connector-detail-label">Freshness</span>
          <span class="connector-detail-value freshness" style="color: ${freshnessColor};">${conn.freshness}</span>
        </div>
      </div>
      <div class="connector-actions">
        <button class="btn btn-danger btn-connector ${isPaused ? 'hidden' : ''}" onclick="window.breakConnector('${conn.connector_id}')">
          Interrupt
        </button>
        <button class="btn btn-success btn-connector ${!isPaused ? 'hidden' : ''}" onclick="window.healConnector('${conn.connector_id}')">
          Reconnect
        </button>
      </div>
    `;
    container.appendChild(card);
  });
}

function startSyncCycle() {
  const progressBar = document.getElementById("sync-progress");
  const intervalTime = 50;
  const cycleDuration = 5000; // Poll API every 5 seconds
  const steps = cycleDuration / intervalTime;
  let currentStep = 0;
  
  if (appState.syncTimer) clearInterval(appState.syncTimer);
  
  appState.syncTimer = setInterval(() => {
    if (appState.isOffline) {
      if (progressBar) progressBar.style.width = "0%";
      return;
    }
    
    currentStep++;
    appState.syncProgress = (currentStep / steps) * 100;
    if (progressBar) progressBar.style.width = `${appState.syncProgress}%`;
    
    if (currentStep >= steps) {
      currentStep = 0;
      fetchTelemetry();
    }
  }, intervalTime);
}

// ==========================================================================
// Control Actions & Handlers
// ==========================================================================
window.breakConnector = async (id) => {
  if (appState.isOffline) return;
  initConsoleLog(`Sending interrupt trigger for connector ${id} to backend API...`, "action");
  try {
    const response = await fetch(`${API_BASE}/break?connector_id=${id}&basin=${appState.selectedBasin}`, { method: "POST" });
    if (!response.ok) throw new Error(`Status ${response.status}`);
    initConsoleLog(`Outage simulation registered for ${id}.`, "error");
    await fetchTelemetry();
  } catch (err) {
    initConsoleLog(`Outage trigger failed: ${err.message}`, "error");
  }
};

window.healConnector = async (id) => {
  if (appState.isOffline) return;
  initConsoleLog(`Sending heal request for connector ${id} to backend API...`, "action");
  try {
    const response = await fetch(`${API_BASE}/heal?connector_id=${id}&basin=${appState.selectedBasin}`, { method: "POST" });
    if (!response.ok) throw new Error(`Status ${response.status}`);
    const data = await response.json();
    if (data.status === "Success") {
      initConsoleLog(`Heal signal received for ${id}. Synchronization in progress...`, "action");
    } else {
      initConsoleLog(`Heal error: ${data.error || 'unspecified error'}`, "warn");
    }
    await fetchTelemetry();
  } catch (err) {
    initConsoleLog(`Heal call failed: ${err.message}`, "error");
  }
};

function setupEventHandlers() {
  // Basin selector handler
  const basinSelect = document.getElementById("basin-select");
  if (basinSelect) {
    basinSelect.addEventListener("change", (e) => {
      appState.selectedBasin = e.target.value;
      initConsoleLog(`Switched catchment basin scope to: ${appState.selectedBasin}`, "action");
      
      // Center map on new basin
      if (map) {
        if (appState.selectedBasin === "rio_cauca") {
          map.setCenter({ lat: 3.43, lng: -76.51 });
          map.setZoom(11);
        } else {
          map.setCenter({ lat: 4.14, lng: -74.94 });
          map.setZoom(8);
        }
      }
      
      // Show loading overlay
      const loader = document.getElementById("map-loading-overlay");
      if (loader) {
        loader.classList.remove("hidden");
      }
      
      // Clear muni detail drawer/rail
      const drawer = document.getElementById("muni-detail-drawer") || document.getElementById("muni-detail-rail");
      if (drawer) {
        drawer.innerHTML = `<div class="drawer-instruction">Select a basin area to view detailed telemetry metrics.</div>`;
      }
      appState.selectedMuni = null;

      // Populate dropdown for Public mode
      populateMuniDropdown();

      fetchTelemetry();
    });
  }

  // Clear reopened incident handler
  const clearReopenBtn = document.getElementById("clear-reopen-btn");
  if (clearReopenBtn) {
    clearReopenBtn.addEventListener("click", async () => {
      initConsoleLog("Returning to live telemetry stream...", "action");
      try {
        const res = await fetch(`${API_BASE}/incidents/clear-reopen`, { method: "POST" });
        if (res.ok) {
          appState.reopenedIncidentId = null;
          clearReopenBtn.classList.add("hidden");
          initConsoleLog("Returned to live telemetry mode.", "system");
          await fetchTelemetry();
        }
      } catch (err) {
        initConsoleLog(`Error clearing reopened incident: ${err.message}`, "error");
      }
    });
  }

  // Initialize diagnostics slideout
  setupDiagnosticsSlideout();
  
  // Set up mode switch handlers
  const btnOps = document.getElementById("mode-btn-operations");
  const btnPub = document.getElementById("mode-btn-public");
  if (btnOps && btnPub) {
    btnOps.addEventListener("click", () => switchMode("operations"));
    btnPub.addEventListener("click", () => switchMode("public"));
  }
  
  // Set up muni selector dropdown change handler
  const muniSelect = document.getElementById("muni-select");
  if (muniSelect) {
    muniSelect.addEventListener("change", (e) => {
      const muniName = e.target.value;
      const muniObj = database.risk.find(r => r.municipality === muniName);
      if (muniObj) {
        appState.selectedMuni = muniObj;
        renderPublicView();
      }
    });
  }
}

// ==========================================================================
// Console Logging Component
// ==========================================================================
function initConsoleLog(message, type = "system") {
  const consoleContainer = document.getElementById("log-console-container");
  if (!consoleContainer) return;
  
  const line = document.createElement("div");
  line.setAttribute("class", `log-line ${type}`);
  
  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  line.textContent = `[${timestamp}] ${message}`;
  
  consoleContainer.appendChild(line);
  consoleContainer.scrollTop = consoleContainer.scrollHeight;
}

// ==========================================================================
// Firebase Notification subscription setup
// ==========================================================================
let fcmToken = null;

async function setupNotifications() {
  const enableBtn = document.getElementById("enable-notifications-btn");
  const tokenBox = document.getElementById("token-display-box");
  const tokenCode = document.getElementById("notification-token");
  const copyBtn = document.getElementById("copy-token-btn");
  
  if (!enableBtn || !messaging) return;
  
  enableBtn.addEventListener("click", async () => {
    initConsoleLog("Requesting push notification permission...", "action");
    try {
      const permission = await Notification.requestPermission();
      if (permission === "granted") {
        initConsoleLog("Permission granted. Retrieving FCM registration token...", "telemetry");
        
        // Retrieve token
        const token = await messaging.getToken({
          vapidKey: "BAcAdo08wSoDyqq2f8U_dJ9XENWt6trHywG_BKkoLCXqf4jSGJuKSi8DC3ikCfoLdHVxVU0Cy64-csmkjOyhMEU"
        });
        
        if (token) {
          fcmToken = token;
          if (tokenCode) tokenCode.textContent = token;
          if (tokenBox) tokenBox.classList.remove("hidden");
          initConsoleLog("FCM token retrieved successfully.", "telemetry");
          
          // Send token to backend
          await registerTokenWithBackend(token);
        } else {
          initConsoleLog("No FCM registration token available. Request permission again.", "warn");
        }
      } else {
        initConsoleLog("Notification permission denied.", "warn");
      }
    } catch (err) {
      initConsoleLog(`Firebase init error: ${err.message}`, "error");
      console.error(err);
    }
  });
  
  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      if (fcmToken) {
        navigator.clipboard.writeText(fcmToken);
        initConsoleLog("FCM registration token copied to clipboard.", "action");
      }
    });
  }
  
  // Foreground message handler
  messaging.onMessage((payload) => {
    console.log("Message received in foreground: ", payload);
    initConsoleLog(`[ALERT BROADCAST]: ${payload.notification.body}`, "warn");
    // Show browser notification if active
    new Notification(payload.notification.title, {
      body: payload.notification.body
    });
  });
}

async function registerTokenWithBackend(token) {
  try {
    const res = await fetch(`${API_BASE}/register-token`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: token })
    });
    if (res.ok) {
      initConsoleLog("FCM token registered with backend alert service.", "telemetry");
    } else {
      throw new Error(`Status ${res.status}`);
    }
  } catch (err) {
    initConsoleLog(`FCM token registration failed: ${err.message}`, "error");
  }
}

function renderAutonomousHeals(heals) {
  const container = document.getElementById("auto-heals-container");
  if (!container) return;
  
  if (!heals || heals.length === 0) {
    container.innerHTML = `<div class="log-line system">No autonomous self-heals logged.</div>`;
    return;
  }
  
  const sorted = [...heals].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  
  container.innerHTML = sorted.map(h => {
    const timeStr = parseISOTime(h.timestamp);
    return `<div class="log-line alert heal-log-item">
      <span class="heal-log-time tabular-nums">[${timeStr}]</span>
      <strong class="heal-log-label">HEALED:</strong> 
      <span class="heal-log-details">${h.name} (${h.connector_id})</span>
      <span class="badge badge-autonomous-mini">autonomous, no human action</span>
    </div>`;
  }).join("");
}

function renderIncidents(incidents) {
  const container = document.getElementById("incidents-history-container");
  if (!container) return;

  if (!incidents || incidents.length === 0) {
    container.innerHTML = `<div class="log-line system">No historical incidents recorded.</div>`;
    return;
  }

  const sorted = [...incidents].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

  container.innerHTML = sorted.map(inc => {
    const timeStr = parseISOTime(inc.timestamp);
    const isReopened = appState.reopenedIncidentId === inc.id;
    const typeLabel = inc.type.toUpperCase();
    
    let severityClass = "low";
    if (inc.type === "alert" || inc.type === "outage") severityClass = "danger";
    else if (inc.type === "heal") severityClass = "low";
    else severityClass = "warning";
    
    return `<div class="log-line incident-log-item border-${severityClass} ${isReopened ? 'reopened' : ''}">
      <div class="incident-log-header">
        <span class="incident-log-title tabular-nums">[${timeStr}] <strong>${typeLabel}</strong> (${inc.basin})</span>
        ${isReopened 
          ? `<span class="incident-log-status-badge">REOPENED</span>` 
          : `<button onclick="window.reopenIncident('${inc.id}')" class="btn-incident-reopen">Reopen</button>`
        }
      </div>
      <div class="incident-log-details">${inc.details}</div>
    </div>`;
  }).join("");
}

window.reopenIncident = async (id) => {
  if (appState.isOffline) return;
  initConsoleLog(`Reopening historical incident ${id}...`, "action");
  try {
    const res = await fetch(`${API_BASE}/incidents/${id}/reopen`, { method: "POST" });
    if (res.ok) {
      appState.reopenedIncidentId = id;
      initConsoleLog(`Incident ${id} reopened. Telemetry view locked to historical snapshot.`, "warn");
      await fetchTelemetry();
    } else {
      initConsoleLog(`Failed to reopen incident: ${res.statusText}`, "warn");
    }
  } catch (err) {
    initConsoleLog(`Error reopening incident: ${err.message}`, "error");
  }
};

function populateMuniDropdown() {
  const muniSelect = document.getElementById("muni-select");
  if (!muniSelect) return;
  
  const basinMunis = {
    "rio_cauca": ["Cali", "Yumbo", "Jamundí"],
    "rio_magdalena": ["Honda", "Girardot", "Neiva"]
  };
  const munis = basinMunis[appState.selectedBasin] || [];
  
  const currentOptions = Array.from(muniSelect.options).map(o => o.value);
  const optionsChanged = currentOptions.length !== munis.length || !currentOptions.every((val, i) => val === munis[i]);
  
  if (optionsChanged) {
    muniSelect.innerHTML = munis.map(m => `<option value="${m}">${m}</option>`).join("");
  }
  
  if (!appState.selectedMuni || !munis.includes(appState.selectedMuni.municipality)) {
    const updated = database.risk.find(r => r.municipality === munis[0]);
    appState.selectedMuni = updated || { municipality: munis[0], risk_score: 0, dominant_hazard: "FLOOD" };
  } else {
    const updated = database.risk.find(r => r.municipality === appState.selectedMuni.municipality);
    if (updated) {
      appState.selectedMuni = updated;
    }
  }
  
  muniSelect.value = appState.selectedMuni.municipality;
}

function switchMode(newMode) {
  appState.mode = newMode;
  
  const wrapper = document.getElementById("dashboard-wrapper");
  if (wrapper) {
    wrapper.className = `dashboard-wrapper mode-${newMode}`;
  }
  
  const btnOps = document.getElementById("mode-btn-operations");
  const btnPub = document.getElementById("mode-btn-public");
  if (btnOps && btnPub) {
    if (newMode === "operations") {
      btnOps.classList.add("active");
      btnPub.classList.remove("active");
    } else {
      btnPub.classList.add("active");
      btnOps.classList.remove("active");
    }
  }
  
  if (newMode === "operations") {
    if (map) {
      google.maps.event.trigger(map, 'resize');
    }
  } else {
    populateMuniDropdown();
    renderPublicView();
  }
}

function setupDiagnosticsSlideout() {
  const toggleBtn = document.getElementById("diagnostics-toggle-btn");
  const closeBtn = document.getElementById("diagnostics-close-btn");
  const overlay = document.getElementById("diagnostics-overlay");
  const slideout = document.getElementById("diagnostics-slideout");
  
  if (!toggleBtn || !slideout) return;
  
  const openSlideout = () => {
    slideout.classList.add("open");
    if (overlay) overlay.classList.add("open");
    toggleBtn.setAttribute("aria-expanded", "true");
  };
  
  const closeSlideout = () => {
    slideout.classList.remove("open");
    if (overlay) overlay.classList.remove("open");
    toggleBtn.setAttribute("aria-expanded", "false");
  };
  
  toggleBtn.addEventListener("click", openSlideout);
  if (closeBtn) closeBtn.addEventListener("click", closeSlideout);
  if (overlay) overlay.addEventListener("click", closeSlideout);
  // Close on Escape key
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && slideout.classList.contains("open")) closeSlideout();
  });
}

function renderPublicView() {
  const heroContainer = document.getElementById("public-status-hero");
  const guidanceList = document.getElementById("public-guidance-list");
  const warningsList = document.getElementById("public-warnings-list");
  
  if (!heroContainer) return;
  
  const selectedMuni = appState.selectedMuni || (database.risk.length > 0 ? database.risk[0] : null);
  if (!selectedMuni) {
    heroContainer.innerHTML = `<div>No area data available.</div>`;
    return;
  }
  
  const severityConfig = getSeverityConfig(selectedMuni.risk_score);
  const statusWord = severityConfig.label.toUpperCase();
  
  let whatThisMeans = "Hydrological conditions are safe and stable.";
  let guidanceItems = [
    "No immediate actions are required.",
    "Stay informed via local safety advisories and public announcements."
  ];
  
  if (statusWord === "CRITICAL") {
    whatThisMeans = "Severe risk of flood, landslide, or seismic activity. Immediate threat to life and property.";
    guidanceItems = [
      "EVACUATE IMMEDIATELY to higher ground.",
      "Avoid low-lying areas, river catchments, and steep slopes.",
      "Follow instructions from civil protection authorities without delay.",
      "Check on neighbors and vulnerable family members if safe to do so."
    ];
  } else if (statusWord === "DANGER") {
    whatThisMeans = "High hazard probability detected. Conditions are deteriorating rapidly.";
    guidanceItems = [
      "PREPARE TO EVACUATE. Secure emergency supply kits.",
      "Move valuable items, electronics, and documents to upper floors.",
      "Stand by and monitor official radio or messaging channels for evacuation orders.",
      "Avoid crossing flooded roads or flowing water."
    ];
  } else if (statusWord === "WARNING") {
    whatThisMeans = "Moderate risk. Precautionary measures and vigilance are advised.";
    guidanceItems = [
      "STAY VIGILANT. Monitor water levels in local streams and catchments.",
      "Review your family emergency plans and supply kits.",
      "Avoid steep terrains and non-essential travel in affected zones.",
      "Keep safety devices charged and notification options active."
    ];
  }
  
  const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  
  heroContainer.innerHTML = `
    <div class="public-hero-title">Selected catchment status</div>
    <div class="public-hero-status" style="color: ${severityConfig.colorHex}">${statusWord}</div>
    <p class="public-hero-desc">${selectedMuni.municipality}: ${whatThisMeans}</p>
    <div class="public-hero-timestamp">Last updated: ${timestamp}</div>
  `;
  
  if (guidanceList) {
    guidanceList.innerHTML = guidanceItems.map(item => `
      <div class="guidance-item">
        <span class="guidance-item-bullet">&bull;</span>
        <span>${item}</span>
      </div>
    `).join("");
  }
  
  if (warningsList) {
    const alertData = database.alert;
    let warningsHtml = "";
    
    const allowedMunis = database.risk.map(m => m.municipality);
    const activeAlerts = (alertData && alertData.graded_alert) 
      ? alertData.graded_alert.filter(a => allowedMunis.includes(a.municipality) && a.severity !== 'LOW')
      : [];
      
    if (activeAlerts.length > 0) {
      warningsHtml += activeAlerts.map(alert => {
        const sevConfig = getSeverityConfig(alert.risk_score);
        const hazardName = alert.dominant_hazard === 'FLOOD' ? 'River Flooding' : alert.dominant_hazard === 'LANDSLIDE' ? 'Landslide' : 'Earthquake / Seismic Activity';
        return `
          <div class="plain-warning-card" style="border-left: 3px solid ${sevConfig.colorHex};">
            <span class="plain-warning-title">${alert.municipality}</span>
            <span class="plain-warning-body">${hazardName} risk is currently <strong>${sevConfig.label}</strong>.</span>
          </div>
        `;
      }).join("");
    } else {
      warningsHtml += `<div class="empty-alerts">No active warnings for this basin catchment.</div>`;
    }
    
    if (alertData && alertData.resident_broadcast && alertData.agency_incident && alertData.agency_incident.affected_municipalities.length > 0) {
      warningsHtml += `
        <div class="broadcast-box" style="margin-top: 1rem;">
          <div class="broadcast-header">
            <span class="broadcast-tag">OFFICIAL EMERGENCY ADVISORY</span>
          </div>
          <pre class="broadcast-text" style="white-space: pre-wrap; font-family: inherit; font-size: 0.8rem; padding: 1rem; color: var(--text-main);">${alertData.resident_broadcast}</pre>
        </div>
      `;
    }
    
    warningsList.innerHTML = warningsHtml;
  }
}
