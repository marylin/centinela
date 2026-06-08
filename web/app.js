// ==========================================================================
// Centinela Client-Side Application Engine (Unit 3B Backend Integrated)
// ==========================================================================

const API_BASE = window.location.origin;

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
  lastSyncTime: null
};

// 3. UI Node Map Coordinates (Supports 3A mock and 3B live Cali/Yumbo/Jamundí)
const mapCoordinates = {
  "Cali": { x: 220, y: 140 },
  "Yumbo": { x: 380, y: 190 },
  "Jamundí": { x: 480, y: 270 },
  "Alto Pass": { x: 150, y: 110 },
  "Oak Creek": { x: 320, y: 150 },
  "Silver Valley": { x: 480, y: 100 },
  "Pine Ridge": { x: 230, y: 280 },
  "Riverdale": { x: 450, y: 270 }
};

// ==========================================================================
// Initialization & Lifecycle
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
  initConsoleLog("Dashboard UI initialized. Attempting connection to local backend API...");
  initClock();
  setupEventHandlers();
  
  // Initial fetch
  fetchTelemetry().then(() => {
    startSyncCycle();
  });
});

// ==========================================================================
// Clock & Time Helpers
// ==========================================================================
function initClock() {
  const clockEl = document.getElementById("current-time");
  setInterval(() => {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString();
    
    // Update freshness calculation from database if available
    if (appState.lastSyncTime && !appState.isOffline && database.connector.status === "active") {
      appState.freshnessCounter = Math.max(0, Math.floor((new Date() - appState.lastSyncTime) / 1000));
      document.getElementById("metric-freshness").textContent = formatFreshness(appState.freshnessCounter);
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
    const [riskRes, statusRes, alertRes] = await Promise.all([
      fetch(`${API_BASE}/risk`),
      fetch(`${API_BASE}/connector-status`),
      fetch(`${API_BASE}/alert`)
    ]);

    if (!riskRes.ok || !statusRes.ok || !alertRes.ok) {
      throw new Error(`API error: risk=${riskRes.status}, status=${statusRes.status}, alert=${alertRes.status}`);
    }

    const riskData = await riskRes.json();
    const statusData = await statusRes.json();
    const alertData = await alertRes.json();

    // Clear offline state if previously offline
    if (appState.isOffline) {
      setBackendOfflineState(false);
      initConsoleLog("Connection restored. Dashboard online.", "telemetry");
    }

    // Update DB
    database.risk = riskData;
    database.connector = statusData;
    database.alert = alertData;

    // Set last local sync timestamp
    if (statusData.last_sync_time && statusData.last_sync_time !== "never") {
      appState.lastSyncTime = new Date(statusData.last_sync_time);
    } else {
      appState.lastSyncTime = new Date();
    }

    // Refresh UI Components
    renderRiskMap();
    renderAlerts();
    updateConnectorUI();

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
  const breakBtn = document.getElementById("break-feed-btn");
  const restoreBtn = document.getElementById("restore-feed-btn");
  
  if (isOffline) {
    banner.classList.remove("hidden");
    systemLed.className = "led-dot warning-mode";
    systemText.textContent = "API OFFLINE";
    
    // Disable buttons
    breakBtn.disabled = true;
    restoreBtn.disabled = true;
    
    // Reset status fields
    document.getElementById("connector-status-badge").textContent = "OFFLINE";
    document.getElementById("connector-status-badge").className = "connector-badge broken";
    document.getElementById("metric-conn-status").textContent = "API Unreachable";
    document.getElementById("metric-conn-status").className = "metric-val text-danger";
    document.getElementById("metric-freshness").textContent = "STALE";
    
    // Set river flow representation to halted
    const mainRiver = document.getElementById("main-river");
    if (mainRiver) mainRiver.className.baseVal = "river-path flow-halted";
  } else {
    banner.classList.add("hidden");
    breakBtn.disabled = false;
    restoreBtn.disabled = false;
  }
}

// ==========================================================================
// Interactive SVG Map Renderer
// ==========================================================================
function renderRiskMap() {
  const container = document.getElementById("risk-map-container");
  if (!container) return;
  
  container.innerHTML = "";
  
  const width = 650;
  const height = 360;
  
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "map-svg");
  
  svg.innerHTML = `
    <defs>
      <filter id="glow-heavy" x="-20%" y="-20%" width="140%" height="140%">
        <feGaussianBlur stdDeviation="6" result="blur" />
        <feComposite in="SourceGraphic" in2="blur" operator="over" />
      </filter>
      <linearGradient id="river-gradient" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#1e3a8a" />
        <stop offset="50%" stop-color="#3b82f6" />
        <stop offset="100%" stop-color="#0284c7" />
      </linearGradient>
    </defs>
    
    <!-- Background Grid Lines -->
    <g stroke="rgba(255,255,255,0.015)" stroke-width="1">
      <line x1="0" y1="60" x2="650" y2="60" />
      <line x1="0" y1="120" x2="650" y2="120" />
      <line x1="0" y1="180" x2="650" y2="180" />
      <line x1="0" y1="240" x2="650" y2="240" />
      <line x1="0" y1="300" x2="650" y2="300" />
      <line x1="100" y1="0" x2="100" y2="360" />
      <line x1="200" y1="0" x2="200" y2="360" />
      <line x1="300" y1="0" x2="300" y2="360" />
      <line x1="400" y1="0" x2="400" y2="360" />
      <line x1="500" y1="0" x2="500" y2="360" />
      <line x1="600" y1="0" x2="600" y2="360" />
    </g>
    
    <!-- Channels -->
    <path id="main-river" class="river-path" d="M 50 80 Q 200 120 300 200 T 580 320" stroke="url(#river-gradient)" stroke-width="6" />
    <path id="trib-1" class="tributary-path" d="M 480 100 Q 420 180 350 200" />
    <path id="trib-2" class="tributary-path" d="M 150 110 Q 220 120 250 160" />
  `;

  // Draw nodes from risk data array
  database.risk.forEach(muni => {
    const coords = mapCoordinates[muni.municipality] || { x: 300, y: 180 }; // Fallback to center
    
    const nodeGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
    nodeGroup.setAttribute("class", `muni-node ${appState.selectedMuni?.municipality === muni.municipality ? 'selected' : ''}`);
    nodeGroup.setAttribute("id", `muni-${muni.municipality.toLowerCase().replace(/\s+/g, '-')}`);
    
    let color = "var(--success)";
    if (muni.risk_score >= 0.8) color = "hsl(290, 80%, 50%)"; // Critical (Purple)
    else if (muni.risk_score >= 0.6) color = "var(--danger)"; // Danger (Red)
    else if (muni.risk_score >= 0.4) color = "var(--warning)"; // Warning (Orange)
    
    const selectionRing = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    selectionRing.setAttribute("cx", coords.x);
    selectionRing.setAttribute("cy", coords.y);
    selectionRing.setAttribute("r", 20);
    selectionRing.setAttribute("class", "muni-node-ring");
    
    if (muni.risk_score >= 0.6) {
      const glowCircle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      glowCircle.setAttribute("cx", coords.x);
      glowCircle.setAttribute("cy", coords.y);
      glowCircle.setAttribute("r", 15);
      glowCircle.setAttribute("fill", "none");
      glowCircle.setAttribute("stroke", color);
      glowCircle.setAttribute("stroke-width", 2);
      glowCircle.setAttribute("opacity", 0.6);
      glowCircle.style.animation = "pulseGrad 2s infinite";
      nodeGroup.appendChild(glowCircle);
    }
    
    const mainNode = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    mainNode.setAttribute("cx", coords.x);
    mainNode.setAttribute("cy", coords.y);
    mainNode.setAttribute("r", 10);
    mainNode.setAttribute("fill", color);
    
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", coords.x);
    text.setAttribute("y", coords.y - 18);
    text.setAttribute("class", "muni-text");
    text.textContent = muni.municipality;
    
    nodeGroup.appendChild(selectionRing);
    nodeGroup.appendChild(mainNode);
    nodeGroup.appendChild(text);
    
    nodeGroup.addEventListener("mouseenter", () => displayMuniDetails(muni));
    nodeGroup.addEventListener("click", () => {
      appState.selectedMuni = muni;
      renderRiskMap();
      displayMuniDetails(muni);
      initConsoleLog(`Selected region: ${muni.municipality} (Risk Score: ${muni.risk_score.toFixed(2)})`, "action");
    });
    
    svg.appendChild(nodeGroup);
  });
  
  container.appendChild(svg);
  updateMapFlowVisuals();
  
  // Update details drawer if selection exists
  if (appState.selectedMuni) {
    const updated = database.risk.find(m => m.municipality === appState.selectedMuni.municipality);
    if (updated) displayMuniDetails(updated);
  }
}

// Adjust visual water currents depending on status
function updateMapFlowVisuals() {
  const mainRiver = document.getElementById("main-river");
  const trib1 = document.getElementById("trib-1");
  const trib2 = document.getElementById("trib-2");
  
  if (!mainRiver) return;
  
  if (appState.isOffline || database.connector.status === "paused") {
    mainRiver.className.baseVal = "river-path flow-halted";
    if (trib1) trib1.className.baseVal = "tributary-path flow-halted";
    if (trib2) trib2.className.baseVal = "tributary-path flow-halted";
  } else {
    mainRiver.className.baseVal = "river-path";
    if (trib1) trib1.className.baseVal = "tributary-path";
    if (trib2) trib2.className.baseVal = "tributary-path";
    
    const hasCritical = database.risk.some(m => m.risk_score >= 0.6);
    if (hasCritical) {
      mainRiver.classList.add("flow-high");
    } else {
      mainRiver.classList.remove("flow-high");
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
      
      <div class="drawer-metric">
        <span class="drawer-label">Calculated Risk</span>
        <span class="drawer-val" style="color: ${muni.risk_score >= 0.6 ? 'var(--danger)' : muni.risk_score >= 0.4 ? 'var(--warning)' : 'var(--success)'}">
          ${muni.risk_score.toFixed(2)}
        </span>
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
        <span class="drawer-label">Alert Threshold</span>
        <span class="drawer-val" style="color: var(--text-dark)">${muni.threshold.toFixed(2)} m</span>
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
  
  const affectedList = alertData.agency_incident.affected_municipalities;
  badge.textContent = `${affectedList.length} Alert${affectedList.length === 1 ? '' : 's'}`;
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
  const statusBadge = document.getElementById("connector-status-badge");
  const connStatusText = document.getElementById("metric-conn-status");
  const lastSyncText = document.getElementById("metric-last-sync");
  const systemLed = document.getElementById("system-status-led");
  const systemStatusText = document.getElementById("system-status-text");
  const breakBtn = document.getElementById("break-feed-btn");
  const restoreBtn = document.getElementById("restore-feed-btn");
  const progressBar = document.getElementById("sync-progress");
  
  if (appState.isOffline) return;

  const isPaused = database.connector.status === "paused";
  
  lastSyncText.textContent = parseISOTime(database.connector.last_sync_time);
  
  if (isPaused) {
    statusBadge.textContent = "PAUSED / OUTAGE";
    statusBadge.className = "connector-badge broken";
    
    connStatusText.textContent = "Degraded State";
    connStatusText.className = "metric-val text-danger";
    
    systemLed.className = "led-dot danger-mode";
    systemStatusText.textContent = "TELEMETRY DEGRADED";
    
    document.getElementById("metric-freshness").textContent = "STALE";
    progressBar.classList.add("halted");
    
    // Toggle action buttons
    breakBtn.classList.add("hidden");
    restoreBtn.classList.remove("hidden");
  } else {
    statusBadge.textContent = "ACTIVE";
    statusBadge.className = "connector-badge";
    
    connStatusText.textContent = "Healthy / Synced";
    connStatusText.className = "metric-val text-success";
    
    systemLed.className = "led-dot";
    systemStatusText.textContent = "SYSTEM ONLINE";
    
    progressBar.classList.remove("halted");
    
    // Toggle action buttons
    restoreBtn.classList.add("hidden");
    breakBtn.classList.remove("hidden");
  }
}

function startSyncCycle() {
  const progressBar = document.getElementById("sync-progress");
  const intervalTime = 50;
  const cycleDuration = 5000; // Poll API every 5 seconds
  const steps = cycleDuration / intervalTime;
  let currentStep = 0;
  
  if (appState.syncTimer) clearInterval(appState.syncTimer);
  
  appState.syncTimer = setInterval(() => {
    if (appState.isOffline || database.connector.status === "paused") {
      progressBar.style.width = "0%";
      return;
    }
    
    currentStep++;
    appState.syncProgress = (currentStep / steps) * 100;
    progressBar.style.width = `${appState.syncProgress}%`;
    
    if (currentStep >= steps) {
      currentStep = 0;
      fetchTelemetry();
    }
  }, intervalTime);
}

// ==========================================================================
// Control Actions & Handlers
// ==========================================================================
function setupEventHandlers() {
  const breakBtn = document.getElementById("break-feed-btn");
  const restoreBtn = document.getElementById("restore-feed-btn");
  
  breakBtn.addEventListener("click", async () => {
    if (appState.isOffline) return;
    initConsoleLog("Sending interrupt trigger to backend API...", "action");
    
    try {
      const response = await fetch(`${API_BASE}/break`, { method: "POST" });
      if (!response.ok) throw new Error(`Status ${response.status}`);
      
      initConsoleLog("Outage simulation registered on backend.", "error");
      await fetchTelemetry();
    } catch (err) {
      initConsoleLog(`Outage trigger failed: ${err.message}`, "error");
    }
  });
  
  restoreBtn.addEventListener("click", async () => {
    if (appState.isOffline) return;
    initConsoleLog("Sending heal request to backend API...", "action");
    
    try {
      const response = await fetch(`${API_BASE}/heal`, { method: "POST" });
      if (!response.ok) throw new Error(`Status ${response.status}`);
      
      const data = await response.json();
      if (data.status === "Success") {
        initConsoleLog("Heal signal received. Synchronization in progress...", "action");
      } else {
        initConsoleLog(`Heal error: ${data.error || 'unspecified error'}`, "warn");
      }
      await fetchTelemetry();
    } catch (err) {
      initConsoleLog(`Heal call failed: ${err.message}`, "error");
    }
  });
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
