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
  reopenedIncidentId: null
};

// Map instances & markers
let map = null;
let markers = [];

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

  const loader = document.getElementById("map-loading-overlay");
  if (loader) {
    loader.classList.add("hidden");
  }

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

  // Clear existing markers
  markers.forEach(m => m.setMap(null));
  markers = [];

  const basinNameMap = {
    "rio_cauca": "Rio Cauca",
    "rio_magdalena": "Rio Magdalena"
  };
  const selectedBasinName = basinNameMap[appState.selectedBasin] || "Rio Cauca";
  
  // Filter risk data by selected basin
  const basinRiskData = database.risk.filter(m => m.basin === selectedBasinName);

  basinRiskData.forEach(muni => {
    const coords = municipalityCoords[muni.municipality] || { lat: 3.43, lng: -76.51 };

    let color = "#22c55e"; // Low (Green)
    if (muni.risk_score >= 0.8) color = "#a855f7"; // Extreme (Purple)
    else if (muni.risk_score >= 0.6) color = "#ef4444"; // High (Red)
    else if (muni.risk_score >= 0.4) color = "#f59e0b"; // Moderate (Orange)

    const dominant = muni.dominant_hazard || "FLOOD";
    const emoji = dominant === "LANDSLIDE" ? "🪨" : dominant === "SEISMIC" ? "🫨" : "🌊";

    // Custom SVG Pin icon
    const pinSvg = {
      path: 'M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z',
      fillColor: color,
      fillOpacity: 0.95,
      strokeColor: '#07090f',
      strokeWeight: 1.5,
      scale: 1.5,
      anchor: new google.maps.Point(12, 22),
      labelOrigin: new google.maps.Point(12, 9)
    };

    const marker = new google.maps.Marker({
      position: coords,
      map: map,
      title: muni.municipality,
      icon: pinSvg,
      label: {
        text: emoji,
        color: '#ffffff',
        fontSize: '11px'
      }
    });

    marker.addListener("click", () => {
      appState.selectedMuni = muni;
      displayMuniDetails(muni);
      initConsoleLog(`Selected region: ${muni.municipality} (Risk Score: ${muni.risk_score.toFixed(2)})`, "action");
    });

    markers.push(marker);
  });

  // Keep details drawer updated if the selected muni is in the current basin
  if (appState.selectedMuni) {
    const updated = basinRiskData.find(m => m.municipality === appState.selectedMuni.municipality);
    if (updated) {
      displayMuniDetails(updated);
    } else {
      const drawer = document.getElementById("muni-detail-drawer");
      if (drawer) {
        drawer.innerHTML = `<div class="drawer-instruction">Hover over or select a basin area to view detailed telemetry metrics.</div>`;
      }
      appState.selectedMuni = null;
    }
  }
}

// ==========================================================================
// Details Panel / Drawer Rendering
// ==========================================================================
function displayMuniDetails(muni) {
  const drawer = document.getElementById("muni-detail-drawer");
  if (!drawer) return;
  
  let riskBadge = `<span class="badge" style="background-color: var(--success-glow); color: var(--success);">LOW RISK</span>`;
  if (muni.risk_score >= 0.8) {
    riskBadge = `<span class="badge" style="background-color: hsla(290, 80%, 50%, 0.15); color: hsl(290, 80%, 70%);">CRITICAL VALUE</span>`;
  } else if (muni.risk_score >= 0.6) {
    riskBadge = `<span class="badge badge-error">HIGH RISK</span>`;
  } else if (muni.risk_score >= 0.4) {
    riskBadge = `<span class="badge" style="background-color: var(--warning-glow); color: var(--warning);">MODERATE WARNING</span>`;
  }

  const dominant = muni.dominant_hazard || 'FLOOD';
  const dominantEmoji = dominant === 'LANDSLIDE' ? '🪨' : dominant === 'SEISMIC' ? '🫨' : '🌊';
  
  const hazardPills = `
    <span class="hazard-pill dominant">${dominantEmoji} ${dominant} (Dominant)</span>
    ${muni.flood_score !== undefined && dominant !== 'FLOOD' ? `<span class="hazard-pill secondary">🌊 Flood (${muni.flood_score.toFixed(2)})</span>` : ''}
    ${muni.landslide_score !== undefined && dominant !== 'LANDSLIDE' ? `<span class="hazard-pill secondary">🪨 Landslide (${muni.landslide_score.toFixed(2)})</span>` : ''}
    ${muni.seismic_score !== undefined && dominant !== 'SEISMIC' ? `<span class="hazard-pill secondary">🫨 Seismic (${muni.seismic_score.toFixed(2)})</span>` : ''}
  `;

  drawer.innerHTML = `
    <div class="drawer-grid">
      <div style="grid-column: 1 / -1; display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
        <h3 class="drawer-muni-name">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"></path>
            <circle cx="12" cy="10" r="3"></circle>
          </svg>
          ${muni.municipality}
        </h3>
        ${riskBadge}
      </div>

      <div class="drawer-hazard-row" style="grid-column: 1 / -1; display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.5rem;">
        ${hazardPills}
      </div>
      
      <div class="drawer-metric">
        <span class="drawer-label">Calculated Risk</span>
        <span class="drawer-val" style="color: ${muni.risk_score >= 0.6 ? 'var(--danger)' : muni.risk_score >= 0.4 ? 'var(--warning)' : 'var(--success)'}">
          ${muni.risk_score.toFixed(2)}
        </span>
      </div>

      <div class="drawer-metric">
        <span class="drawer-label">Dominant Hazard</span>
        <span class="drawer-val" style="color: var(--warning); text-transform: uppercase;">${muni.dominant_hazard || 'FLOOD'}</span>
      </div>
      
      <div class="drawer-metric">
        <span class="drawer-label">Rainfall (24h)</span>
        <span class="drawer-val">${muni.rainfall_mm.toFixed(1)} mm</span>
      </div>
      
      <div class="drawer-metric">
        <span class="drawer-label">River Level</span>
        <span class="drawer-val">${muni.river_level_m.toFixed(2)} m</span>
      </div>
      
      <div class="drawer-metric">
        <span class="drawer-label">Soil Saturation</span>
        <span class="drawer-val">${(muni.soil_saturation * 100).toFixed(0)}%</span>
      </div>

      <div class="drawer-metric">
        <span class="drawer-label">Slope / Susc.</span>
        <span class="drawer-val">${muni.slope_angle_deg !== undefined ? muni.slope_angle_deg.toFixed(0) + '°' : '--'} / ${muni.susceptibility_index !== undefined ? (muni.susceptibility_index * 100).toFixed(0) + '%' : '--'}</span>
      </div>

      <div class="drawer-metric">
        <span class="drawer-label">Earthquake</span>
        <span class="drawer-val">${muni.earthquake_magnitude ? muni.earthquake_magnitude.toFixed(1) + ' Mw' : 'None'}</span>
      </div>

      <div class="drawer-metric">
        <span class="drawer-label">Flood Score</span>
        <span class="drawer-val" style="color: var(--text-dark)">${muni.flood_score !== undefined ? muni.flood_score.toFixed(2) : '--'}</span>
      </div>

      <div class="drawer-metric">
        <span class="drawer-label">Landslide Score</span>
        <span class="drawer-val" style="color: var(--text-dark)">${muni.landslide_score !== undefined ? muni.landslide_score.toFixed(2) : '--'}</span>
      </div>

      <div class="drawer-metric">
        <span class="drawer-label">Seismic Score</span>
        <span class="drawer-val" style="color: var(--text-dark)">${muni.seismic_score !== undefined ? muni.seismic_score.toFixed(2) : '--'}</span>
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
  incidentCard.className = "alert-card alert-extreme";
  
  incidentCard.innerHTML = `
    <div class="alert-icon-wrapper" style="color: var(--danger)">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
        <line x1="12" y1="9" x2="12" y2="13"></line>
        <line x1="12" y1="17" x2="12.01" y2="17"></line>
      </svg>
    </div>
    <div class="alert-info">
      <div class="alert-title-row">
        <span class="alert-muni">${alertData.agency_incident.title}</span>
        <span class="alert-type text-danger" style="font-weight: 800; font-size: 0.7rem; border: 1px solid var(--danger); padding: 0.1rem 0.3rem; border-radius: 3px;">CIVIL ADVISORY</span>
      </div>
      <p class="alert-desc">${alertData.agency_incident.summary}</p>
      <div class="alert-meta" style="margin-top: 0.6rem;">
        <span>CRITICAL SEVERITY</span>
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
    card.style.border = "1px solid var(--border-color)";
    card.style.borderRadius = "8px";
    card.style.padding = "0.75rem";
    card.style.background = "rgba(255, 255, 255, 0.01)";
    card.style.transition = "border-color var(--transition-normal)";
    
    const isPaused = conn.status === "paused";
    const badgeClass = isPaused ? "connector-badge broken" : "connector-badge";
    const badgeText = isPaused ? "PAUSED" : "ACTIVE";
    const freshnessColor = conn.freshness === "FRESH" ? "var(--success)" : "var(--danger)";
    
    card.innerHTML = `
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.5rem;">
        <span style="font-size: 0.8rem; font-weight: 600; color: var(--text-main);">${conn.name}</span>
        <span class="${badgeClass}">${badgeText}</span>
      </div>
      <div style="display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 0.5rem; font-size: 0.7rem; margin-bottom: 0.75rem;">
        <div>
          <span style="color: var(--text-dark); display: block; font-size: 0.6rem; text-transform: uppercase;">Last Sync</span>
          <span style="font-weight: 500; font-family: var(--font-mono);">${parseISOTime(conn.last_sync_time)}</span>
        </div>
        <div>
          <span style="color: var(--text-dark); display: block; font-size: 0.6rem; text-transform: uppercase;">Freshness</span>
          <span style="font-weight: 600; color: ${freshnessColor};">${conn.freshness}</span>
        </div>
      </div>
      <div style="display: flex; gap: 0.5rem;">
        <button class="btn btn-danger ${isPaused ? 'hidden' : ''}" style="flex: 1; padding: 0.35rem 0.5rem; font-size: 0.7rem; border-radius: 4px;" onclick="window.breakConnector('${conn.connector_id}')">
          Interrupt
        </button>
        <button class="btn btn-success ${!isPaused ? 'hidden' : ''}" style="flex: 1; padding: 0.35rem 0.5rem; font-size: 0.7rem; border-radius: 4px;" onclick="window.healConnector('${conn.connector_id}')">
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
      
      // Clear muni detail drawer
      const drawer = document.getElementById("muni-detail-drawer");
      if (drawer) {
        drawer.innerHTML = `<div class="drawer-instruction">Hover over or select a basin area to view detailed telemetry metrics.</div>`;
      }
      appState.selectedMuni = null;

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
    container.innerHTML = `<div class="log-line system" style="color: var(--text-muted);">No autonomous self-heals logged.</div>`;
    return;
  }
  
  const sorted = [...heals].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));
  
  container.innerHTML = sorted.map(h => {
    const timeStr = parseISOTime(h.timestamp);
    return `<div class="log-line alert" style="border-left: 2px solid #22c55e; padding-left: 0.5rem; margin-bottom: 0.25rem;">
      <span style="color: var(--text-muted); font-size: 0.75rem;">[${timeStr}]</span>
      <strong style="color: #22c55e;">HEALED:</strong> 
      <span style="color: var(--text-dark);">${h.name} (${h.connector_id})</span>
      <span class="badge" style="background-color: rgba(34, 197, 94, 0.1); color: #22c55e; font-size: 0.55rem; padding: 0.05rem 0.25rem; margin-left: 0.25rem; border-radius: 3px;">autonomous, no human action</span>
    </div>`;
  }).join("");
}

function renderIncidents(incidents) {
  const container = document.getElementById("incidents-history-container");
  if (!container) return;

  if (!incidents || incidents.length === 0) {
    container.innerHTML = `<div class="log-line system" style="color: var(--text-muted);">No historical incidents recorded.</div>`;
    return;
  }

  const sorted = [...incidents].sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp));

  container.innerHTML = sorted.map(inc => {
    const timeStr = parseISOTime(inc.timestamp);
    const isReopened = appState.reopenedIncidentId === inc.id;
    const typeLabel = inc.type.toUpperCase();
    const borderLeftColor = inc.type === "alert" ? "#ef4444" : inc.type === "heal" ? "#22c55e" : "#eab308";
    
    return `<div class="log-line" style="border-left: 2px solid ${borderLeftColor}; padding: 0.35rem 0.5rem; margin-bottom: 0.25rem; display: flex; flex-direction: column; gap: 0.25rem; background: ${isReopened ? 'rgba(255,255,255,0.02)' : 'transparent'};">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <span style="font-size: 0.75rem; color: var(--text-muted);">[${timeStr}] <strong>${typeLabel}</strong> (${inc.basin})</span>
        ${isReopened 
          ? `<span style="font-size: 0.65rem; color: #ef4444; font-weight: bold;">REOPENED</span>` 
          : `<button onclick="window.reopenIncident('${inc.id}')" style="background: rgba(255,255,255,0.05); border: 1px solid var(--border-color); color: var(--text-dark); font-size: 0.6rem; padding: 0.15rem 0.35rem; border-radius: 3px; cursor: pointer;">Reopen</button>`
        }
      </div>
      <div style="font-size: 0.75rem; color: var(--text-dark); line-height: 1.2;">${inc.details}</div>
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
