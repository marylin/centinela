// ==========================================================================
// HydroGuard Client-Side Application Engine (Unit 3A Static Shell)
// ==========================================================================

// 1. Placeholder Data conforming to the specified contract
const database = {
  risk: [
    { municipality: "Alto Pass", risk_score: 0.85, rainfall_mm: 45.2, river_level_m: 4.2, soil_saturation: 0.92, threshold: 0.80 },
    { municipality: "Oak Creek", risk_score: 0.42, rainfall_mm: 12.5, river_level_m: 1.8, soil_saturation: 0.65, threshold: 0.75 },
    { municipality: "Silver Valley", risk_score: 0.95, rainfall_mm: 58.0, river_level_m: 5.1, soil_saturation: 0.98, threshold: 0.70 },
    { municipality: "Pine Ridge", risk_score: 0.15, rainfall_mm: 2.1, river_level_m: 0.8, soil_saturation: 0.30, threshold: 0.85 },
    { municipality: "Riverdale", risk_score: 0.68, rainfall_mm: 32.4, river_level_m: 3.5, soil_saturation: 0.78, threshold: 0.70 }
  ],
  connector: {
    status: "healthy",
    last_sync_time: new Date().toISOString(),
    freshness: "0s"
  }
};

// 2. State Management
let appState = {
  isBroken: false,
  selectedMuni: null,
  syncProgress: 0,
  syncTimer: null,
  freshnessCounter: 0,
  lastSyncTime: new Date()
};

// 3. UI Node Map Coordinates (For SVG Visual Layout)
const mapCoordinates = {
  "Alto Pass": { x: 150, y: 110, color: "var(--warning)" },
  "Oak Creek": { x: 320, y: 150, color: "var(--success)" },
  "Silver Valley": { x: 480, y: 100, color: "hsl(290, 80%, 50%)" },
  "Pine Ridge": { x: 230, y: 280, color: "var(--success)" },
  "Riverdale": { x: 450, y: 270, color: "var(--warning)" }
};

// ==========================================================================
// Initialization & Lifecycle
// ==========================================================================
document.addEventListener("DOMContentLoaded", () => {
  initConsoleLog("Dashboard telemetry interface initialized.");
  initClock();
  renderRiskMap();
  renderAlerts();
  updateConnectorUI();
  startSyncCycle();
  setupEventHandlers();
});

// ==========================================================================
// Clock & Time Helpers
// ==========================================================================
function initClock() {
  const clockEl = document.getElementById("current-time");
  setInterval(() => {
    const now = new Date();
    clockEl.textContent = now.toLocaleTimeString();
    
    // Update freshness label
    if (!appState.isBroken) {
      appState.freshnessCounter = Math.floor((new Date() - appState.lastSyncTime) / 1000);
      document.getElementById("metric-freshness").textContent = formatFreshness(appState.freshnessCounter);
      database.connector.freshness = formatFreshness(appState.freshnessCounter);
    }
  }, 1000);
}

function formatFreshness(seconds) {
  if (seconds < 60) return `${seconds}s ago`;
  const mins = Math.floor(seconds / 60);
  return `${mins}m ${seconds % 60}s ago`;
}

function getShortTime(date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ==========================================================================
// Interactive SVG Map Renderer
// ==========================================================================
function renderRiskMap() {
  const container = document.getElementById("risk-map-container");
  
  // Clean container
  container.innerHTML = "";
  
  const width = 650;
  const height = 360;
  
  // Create SVG Element
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("class", "map-svg");
  
  // Define gradients and filters
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
    
    <!-- Background Grid Lines (SCADA Aesthetic) -->
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
    
    <!-- River Channels (Water flow vectors) -->
    <path id="main-river" class="river-path" d="M 50 80 Q 200 120 300 200 T 580 320" stroke="url(#river-gradient)" stroke-width="6" />
    <path id="trib-1" class="tributary-path" d="M 480 100 Q 420 180 350 200" />
    <path id="trib-2" class="tributary-path" d="M 150 110 Q 220 120 250 160" />
  `;

  // Draw Municipalities as Nodes
  database.risk.forEach(muni => {
    const coords = mapCoordinates[muni.municipality];
    if (!coords) return;
    
    const nodeGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
    nodeGroup.setAttribute("class", `muni-node ${appState.selectedMuni?.municipality === muni.municipality ? 'selected' : ''}`);
    nodeGroup.setAttribute("id", `muni-${muni.municipality.toLowerCase().replace(/\s+/g, '-')}`);
    
    // Node Color based on Risk Score
    let color = "var(--success)";
    if (muni.risk_score >= 0.9) color = "hsl(290, 80%, 50%)"; // Critical (Purple)
    else if (muni.risk_score >= 0.75) color = "var(--danger)"; // Danger (Red)
    else if (muni.risk_score >= 0.5) color = "var(--warning)"; // Warning (Orange)
    
    // Outer Selection Ring
    const selectionRing = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    selectionRing.setAttribute("cx", coords.x);
    selectionRing.setAttribute("cy", coords.y);
    selectionRing.setAttribute("r", 20);
    selectionRing.setAttribute("class", "muni-node-ring");
    
    // Outer Pulsing Glow (for dangerous nodes)
    if (muni.risk_score >= 0.75) {
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
    
    // Inner Solid Node
    const mainNode = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    mainNode.setAttribute("cx", coords.x);
    mainNode.setAttribute("cy", coords.y);
    mainNode.setAttribute("r", 10);
    mainNode.setAttribute("fill", color);
    mainNode.setAttribute("style", `color: ${color}`);
    
    // Label Text
    const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
    text.setAttribute("x", coords.x);
    text.setAttribute("y", coords.y - 18);
    text.setAttribute("class", "muni-text");
    text.textContent = muni.municipality;
    
    nodeGroup.appendChild(selectionRing);
    nodeGroup.appendChild(mainNode);
    nodeGroup.appendChild(text);
    
    // Events
    nodeGroup.addEventListener("mouseenter", () => displayMuniDetails(muni));
    nodeGroup.addEventListener("click", () => {
      appState.selectedMuni = muni;
      renderRiskMap(); // Redraw selection rings
      displayMuniDetails(muni);
      initConsoleLog(`Selected region: ${muni.municipality} (Risk Index: ${(muni.risk_score * 100).toFixed(0)}%)`, "action");
    });
    
    svg.appendChild(nodeGroup);
  });
  
  container.appendChild(svg);
  
  // Set flow status
  updateMapFlowVisuals();
}

function updateMapFlowVisuals() {
  const mainRiver = document.getElementById("main-river");
  const trib1 = document.getElementById("trib-1");
  const trib2 = document.getElementById("trib-2");
  
  if (!mainRiver) return;
  
  if (appState.isBroken) {
    mainRiver.classList.add("flow-halted");
    trib1.classList.add("flow-halted");
    trib2.classList.add("flow-halted");
  } else {
    mainRiver.classList.remove("flow-halted");
    trib1.classList.remove("flow-halted");
    trib2.classList.remove("flow-halted");
    
    // Check if there are extreme risks, speed up river flow representation
    const hasCritical = database.risk.some(m => m.risk_score >= 0.8);
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
  
  let riskBadge = `<span class="badge" style="background-color: var(--success-glow); color: var(--success);">LOW RISK</span>`;
  if (muni.risk_score >= 0.9) {
    riskBadge = `<span class="badge" style="background-color: hsla(290, 80%, 50%, 0.15); color: hsl(290, 80%, 70%);">CRITICAL OVERFLOW</span>`;
  } else if (muni.risk_score >= 0.75) {
    riskBadge = `<span class="badge badge-error">HIGH DANGER</span>`;
  } else if (muni.risk_score >= 0.5) {
    riskBadge = `<span class="badge" style="background-color: var(--warning-glow); color: var(--warning);">WARNING LIMIT</span>`;
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
        <span class="drawer-val" style="color: ${muni.risk_score >= 0.75 ? 'var(--danger)' : muni.risk_score >= 0.5 ? 'var(--warning)' : 'var(--success)'}">
          ${(muni.risk_score * 100).toFixed(0)}%
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
        <span class="drawer-label">Trigger Threshold</span>
        <span class="drawer-val" style="color: var(--text-dark)">${(muni.threshold * 100).toFixed(0)}%</span>
      </div>
    </div>
  `;
}

// ==========================================================================
// Alerts Engine
// ==========================================================================
function renderAlerts() {
  const container = document.getElementById("alert-feed-container");
  const badge = document.getElementById("active-alert-count");
  
  // Filter for municipalities exceeding threshold
  const activeAlerts = database.risk.filter(muni => muni.risk_score >= muni.threshold);
  
  badge.textContent = `${activeAlerts.length} Alert${activeAlerts.length === 1 ? '' : 's'}`;
  
  if (activeAlerts.length === 0) {
    container.innerHTML = `<div class="empty-alerts">No active warnings. System telemetry is within safe operating ranges.</div>`;
    badge.className = "badge badge-success";
    return;
  }
  
  badge.className = "badge badge-error";
  container.innerHTML = "";
  
  activeAlerts.forEach(muni => {
    const isExtreme = muni.risk_score >= 0.9;
    const card = document.createElement("div");
    card.setAttribute("class", `alert-card ${isExtreme ? 'alert-extreme' : 'alert-high'}`);
    
    card.innerHTML = `
      <div class="alert-icon-wrapper" style="color: ${isExtreme ? 'hsl(290, 80%, 60%)' : 'var(--danger)'}">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
          <line x1="12" y1="9" x2="12" y2="13"></line>
          <line x1="12" y1="17" x2="12.01" y2="17"></line>
        </svg>
      </div>
      <div class="alert-info">
        <div class="alert-title-row">
          <span class="alert-muni">${muni.municipality}</span>
          <span class="alert-type" style="color: ${isExtreme ? 'hsl(290, 80%, 75%)' : 'var(--danger)'}">
            ${isExtreme ? 'CRITICAL CATCHMENT' : 'FLOOD STAGE'}
          </span>
        </div>
        <p class="alert-desc">
          Telemetry index of ${(muni.risk_score * 100).toFixed(0)}% exceeds critical threshold of ${(muni.threshold * 100).toFixed(0)}%. River level is currently at ${muni.river_level_m.toFixed(2)}m with ${muni.rainfall_mm.toFixed(1)}mm rainfall.
        </p>
        <div class="alert-meta">
          <span>LIMIT EXCEEDED</span>
          <span>SAT: ${(muni.soil_saturation * 100).toFixed(0)}%</span>
        </div>
      </div>
    `;
    container.appendChild(card);
  });
}

// ==========================================================================
// Pipeline & Connection Management
// ==========================================================================
function updateConnectorUI() {
  const statusBadge = document.getElementById("connector-status-badge");
  const connStatusText = document.getElementById("metric-conn-status");
  const lastSyncText = document.getElementById("metric-last-sync");
  const systemLed = document.getElementById("system-status-led");
  const systemStatusText = document.getElementById("system-status-text");
  
  if (appState.isBroken) {
    database.connector.status = "broken";
    statusBadge.textContent = "BROKEN";
    statusBadge.className = "connector-badge broken";
    
    connStatusText.textContent = "Disconnected";
    connStatusText.className = "metric-val text-danger";
    
    systemLed.className = "led-dot danger-mode";
    systemStatusText.textContent = "TELEMETRY OFFLINE";
    
    document.getElementById("sync-progress").classList.add("halted");
  } else {
    database.connector.status = "healthy";
    statusBadge.textContent = "HEALTHY";
    statusBadge.className = "connector-badge";
    
    connStatusText.textContent = "Connected";
    connStatusText.className = "metric-val text-success";
    
    systemLed.className = "led-dot";
    systemStatusText.textContent = "SYSTEM ONLINE";
    
    document.getElementById("sync-progress").classList.remove("halted");
  }
  
  lastSyncText.textContent = getShortTime(appState.lastSyncTime);
  database.connector.last_sync_time = appState.lastSyncTime.toISOString();
}

function startSyncCycle() {
  const progressBar = document.getElementById("sync-progress");
  const intervalTime = 50; // Update progress bar every 50ms
  const cycleDuration = 5000; // Complete sync every 5s
  const steps = cycleDuration / intervalTime;
  let currentStep = 0;
  
  appState.syncTimer = setInterval(() => {
    if (appState.isBroken) {
      progressBar.style.width = "0%";
      return;
    }
    
    currentStep++;
    appState.syncProgress = (currentStep / steps) * 100;
    progressBar.style.width = `${appState.syncProgress}%`;
    
    if (currentStep >= steps) {
      currentStep = 0;
      appState.lastSyncTime = new Date();
      appState.freshnessCounter = 0;
      updateConnectorUI();
      
      // Simulate minor fluctuation in telemetry data to keep map "alive"
      fluctuateTelemetry();
      renderRiskMap();
      renderAlerts();
      
      initConsoleLog("Ingested telemetry pack: 5 basin records synchronized.", "telemetry");
    }
  }, intervalTime);
}

function fluctuateTelemetry() {
  database.risk.forEach(muni => {
    // Small changes of up to +/- 2%
    const change = (Math.random() - 0.5) * 0.04;
    muni.rainfall_mm = Math.max(0, muni.rainfall_mm + change * 5);
    muni.river_level_m = Math.max(0.2, muni.river_level_m + change * 0.5);
    muni.soil_saturation = Math.min(1.0, Math.max(0, muni.soil_saturation + change));
    
    // Recalculate risk score based on rainfall, river level and saturation
    const weightRain = 0.3;
    const weightRiver = 0.4;
    const weightSat = 0.3;
    
    // Normalize values roughly to 0-1 scale for calculation
    const normRain = Math.min(1.0, muni.rainfall_mm / 60);
    const normRiver = Math.min(1.0, muni.river_level_m / 6.0);
    const calculated = (normRain * weightRain) + (normRiver * weightRiver) + (muni.soil_saturation * weightSat);
    
    muni.risk_score = Math.min(1.0, Math.max(0.05, calculated));
  });
  
  // If a municipality is selected, update details too
  if (appState.selectedMuni) {
    const updated = database.risk.find(m => m.municipality === appState.selectedMuni.municipality);
    if (updated) displayMuniDetails(updated);
  }
}

// ==========================================================================
// Control Actions & Handlers
// ==========================================================================
function setupEventHandlers() {
  const breakBtn = document.getElementById("break-feed-btn");
  const restoreBtn = document.getElementById("restore-feed-btn");
  
  breakBtn.addEventListener("click", () => {
    appState.isBroken = true;
    
    breakBtn.classList.add("hidden");
    restoreBtn.classList.remove("hidden");
    
    updateConnectorUI();
    updateMapFlowVisuals();
    
    initConsoleLog("Manual Override: Connector sync process terminated.", "error");
    initConsoleLog("CRITICAL: Ingest pipeline disconnected. Displaying stale telemetry cache.", "warn");
  });
  
  restoreBtn.addEventListener("click", () => {
    appState.isBroken = false;
    
    restoreBtn.classList.add("hidden");
    breakBtn.classList.remove("hidden");
    
    appState.lastSyncTime = new Date();
    appState.freshnessCounter = 0;
    
    updateConnectorUI();
    updateMapFlowVisuals();
    
    initConsoleLog("Manual Override: Reconnecting ingest pipeline...", "action");
    initConsoleLog("Sync established. Connector reporting HEALTHY state.", "telemetry");
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
