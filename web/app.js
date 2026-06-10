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
  liveSeismic: [],
  seismicEvents: { events: [], active_regions: [] },
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
  seismicFeedAvailable: true,
  seismicEventsAvailable: false,
  seismicFocus: null,
  regionFilter: null,
  regionsExpanded: false,
  choroplethOn: true,
  simulatedActive: false,
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
let riskZoneCircles = {}; // municipality -> google.maps.Circle (choropleth-style risk zones)

// Seismic-focus map artifacts (transient overlay, separate from basin markers)
let seismicFocusMarker = null;
let seismicFocusCircle = null;

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
  "Lima": { lat: -12.046, lng: -77.043 },
  "Callao": { lat: -12.056, lng: -77.118 },
  "Chorrillos": { lat: -12.168, lng: -77.022 },
  "Guatemala City": { lat: 14.6349, lng: -90.5069 },
  "Mixco": { lat: 14.6333, lng: -90.6064 },
  "Villa Nueva": { lat: 14.5269, lng: -90.5969 },
  "Alto Pass": { lat: 3.4600, lng: -76.5100 },
  "Oak Creek": { lat: 3.4800, lng: -76.5200 },
  "Silver Valley": { lat: 3.5000, lng: -76.5300 },
  "Pine Ridge": { lat: 3.4000, lng: -76.5000 },
  "Riverdale": { lat: 3.4200, lng: -76.4900 }
};

// ==========================================================================
// Public Alert content (fixed, plain-language, authoritative copy)
// ==========================================================================
const HAZARD_LABELS = {
  FLOOD: "Flood",
  LANDSLIDE: "Landslide",
  SEISMIC: "Earthquake / seismic activity"
};

// Protective actions — used verbatim, no invented specifics.
const HAZARD_ACTIONS = {
  FLOOD: "Move to higher ground, away from the river channel and low-lying areas. Do not cross moving water.",
  LANDSLIDE: "Move away from steep slopes and the base of hillsides; avoid narrow valleys and drainage paths.",
  SEISMIC: "Drop, cover, and hold on. After shaking stops, move away from damaged structures to open ground."
};

// Named civil-protection authority (Colombia).
const ALERT_SOURCE = "Unidad Nacional para la Gestión del Riesgo de Desastres (UNGRD)";

// One TRUE, neutral, basin-level context line per area. No invented dates, tolls, or events.
const BASIN_HISTORY = {
  rio_cauca: "The Río Cauca basin has a documented history of rainy-season flooding.",
  rio_magdalena: "The Río Magdalena basin experiences seasonal flooding during Colombia's rainy seasons."
};

// 8-point compass labels, clockwise from North, used for the uphill directive.
const COMPASS_8 = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"];

// Public-map state (separate instance from the Operations map; fully additive).
let publicMap = null;
let publicMarkers = {};
let publicZoneCircle = null;
let publicEventMarker = null; // epicenter marker for the public event view
let youAreHereMarker = null;
let elevationService = null;
const elevationDirCache = {}; // municipality -> "north".."northwest" (only SUCCESSFUL results cached)
const elevationInFlight = new Set(); // municipalities with a query currently outstanding

// Safe-route state (Places + Directions; separate from all existing map state).
let placesService = null;
let directionsService = null;
let directionsRenderer = null;
let safeRouteBusy = false; // guards against overlapping searches
const COMPASS_DEGREES = { north: 0, northeast: 45, east: 90, southeast: 135, south: 180, southwest: 225, west: 270, northwest: 315 };

// Offline fallback used only if GET /basins fails or returns empty, so the UI
// never breaks. Mirrors the original two hardcoded basins.
const FALLBACK_BASINS = [
  { id: "rio_cauca", name: "Rio Cauca", country: "Colombia", municipalities: ["Cali", "Yumbo", "Jamundí"] },
  { id: "rio_magdalena", name: "Rio Magdalena", country: "Colombia", municipalities: ["Neiva", "Girardot", "Honda"] }
];

// Preserve the original municipality ordering for the two existing basins so they
// render exactly as before; any other basin (e.g. Lima) is driven from config.
const FALLBACK_BASIN_MUNIS = {
  "rio_cauca": ["Cali", "Yumbo", "Jamundí"],
  "rio_magdalena": ["Honda", "Girardot", "Neiva"]
};

function getBasinMunis(basinId) {
  if (FALLBACK_BASIN_MUNIS[basinId]) return FALLBACK_BASIN_MUNIS[basinId];
  const b = (appState.basins || []).find(x => x.id === basinId);
  return (b && Array.isArray(b.municipalities)) ? b.municipalities : [];
}

// Fetch the basin catalog from the backend and build the selector options from it,
// so any basin in config (including Lima/Peru) appears automatically.
async function loadBasins() {
  const basinSelect = document.getElementById("basin-select");
  try {
    const res = await fetch(`${API_BASE}/basins`);
    if (!res.ok) throw new Error(`Status ${res.status}`);
    const data = await res.json();
    if (!Array.isArray(data) || data.length === 0) throw new Error("Empty basins config");

    appState.basins = data;
    // The selector lists compound basins only; seismic-only places are reached
    // through the Live Seismic Events feed instead. Entries without a "kind"
    // (older backend without the contract field) keep appearing, so nothing
    // breaks until the kind-aware backend lands.
    const selectable = data.filter(b => b && b.kind !== "seismic");
    const options = selectable.length ? selectable : data;
    if (basinSelect) {
      basinSelect.innerHTML = options
        .map(b => `<option value="${b.id}">${b.name} (${b.country})${b.simulated ? " · SIMULATED" : ""}</option>`)
        .join("");
    }
    // Default to the first selectable basin returned (keeps rio_cauca as today).
    appState.selectedBasin = options[0].id;
    if (basinSelect) basinSelect.value = appState.selectedBasin;
    initConsoleLog(`Loaded ${data.length} basins from configuration (${options.length} selectable).`, "telemetry");
  } catch (err) {
    // Resilience: keep the existing hardcoded options/basins; never crash.
    appState.basins = FALLBACK_BASINS;
    console.warn("Could not load basins from backend; using fallback list:", err && err.message);
    initConsoleLog("Basin config unavailable; using built-in basin list.", "warn");
  }
}

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
document.addEventListener("DOMContentLoaded", async () => {
  initConsoleLog("Dashboard UI initialized. Attempting connection to local backend API...");
  initClock();
  setupEventHandlers();
  setupNotifications();
  setupSafeRouteControls();
  setupTooltipPositioning();

  appState.mode = "operations";

  // Populate the basin selector from backend config before loading telemetry.
  await loadBasins();

  // If Google Maps script finished loading before DOMContentLoaded
  if (window.googleMapsReady) {
    initMap();
  }

  // Warehouse-backed history: pre-seed the risk sparkline and load the
  // river/rainfall trend for the starting basin.
  setupChartTableToggles();
  seedRiskHistory(appState.selectedBasin);
  fetchTelemetryHistory(appState.selectedBasin);

  // Initial fetch
  fetchTelemetry().then(() => {
    startSyncCycle();
  });
});

window.onMapsReadyCallback = () => {
  initMap();
  // If the user is already in Public Alert mode when Maps finishes loading,
  // bring up the public map too.
  if (appState.mode === "public") {
    initPublicMap();
    renderPublicView();
  }
};

// Initialize Google Maps
function initMap() {
  const mapElement = document.getElementById("google-map");
  if (!mapElement || typeof google === "undefined") return;

  // Neutral default view; the per-basin bounds-fit recenters from the basin's
  // municipality markers as soon as they render, so no basin coords are hardcoded.
  const center = { lat: 0, lng: -75 };
  const zoom = 4;

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
// Public Alert Map ("This is your area")
// ==========================================================================
const BASIN_CENTERS = {
  rio_cauca: { lat: 3.43, lng: -76.51, zoom: 11 },
  rio_magdalena: { lat: 4.14, lng: -74.94, zoom: 8 }
};

function initPublicMap() {
  const el = document.getElementById("public-map");
  if (!el || typeof google === "undefined" || publicMap) return;

  const c = BASIN_CENTERS[appState.selectedBasin] || BASIN_CENTERS.rio_cauca;
  publicMap = new google.maps.Map(el, {
    center: { lat: c.lat, lng: c.lng },
    zoom: c.zoom,
    styles: darkMapStyles,
    disableDefaultUI: true,
    zoomControl: true
  });

  const loader = document.getElementById("public-map-loading");
  if (loader) loader.classList.add("hidden");
}

// Highlight the at-risk municipality and draw a subtle zone when an alert shows.
// Centers once per basin — no bounds re-fit on every poll.
function renderPublicMap(selectedMuni) {
  if (!publicMap || typeof google === "undefined" || !selectedMuni) return;

  const allowed = getBasinMunis(appState.selectedBasin);

  // Drop markers no longer in this basin.
  Object.keys(publicMarkers).forEach(name => {
    if (!allowed.includes(name)) {
      publicMarkers[name].setMap(null);
      delete publicMarkers[name];
    }
  });

  const basinRisk = database.risk.filter(m => allowed.includes(m.municipality));
  basinRisk.forEach(muni => {
    const coords = municipalityCoords[muni.municipality];
    if (!coords) return;

    const isSelected = muni.municipality === selectedMuni.municipality;
    const sev = getSeverityConfig(muni.risk_score);
    const iconUrl = getMarkerIconUrl(sev.colorHex, muni.dominant_hazard || "FLOOD");
    // Emphasize the at-risk (selected) municipality with a larger marker.
    const dim = isSelected ? 52 : 32;
    const markerIcon = {
      url: iconUrl,
      size: new google.maps.Size(36, 36),
      scaledSize: new google.maps.Size(dim, dim),
      anchor: new google.maps.Point(dim / 2, dim - 2)
    };

    if (publicMarkers[muni.municipality]) {
      publicMarkers[muni.municipality].setPosition(coords);
      publicMarkers[muni.municipality].setIcon(markerIcon);
      publicMarkers[muni.municipality].setZIndex(isSelected ? 1000 : 1);
    } else {
      publicMarkers[muni.municipality] = new google.maps.Marker({
        position: coords,
        map: publicMap,
        title: muni.municipality,
        icon: markerIcon,
        zIndex: isSelected ? 1000 : 1
      });
      // Tapping a marker selects that area (cards and map stay in sync).
      publicMarkers[muni.municipality].addListener("click", () => selectPublicArea(muni.municipality));
    }
  });

  // Subtle zone around the at-risk municipality, only when an alert is active.
  const selCoords = municipalityCoords[selectedMuni.municipality];
  const sevSel = getSeverityConfig(selectedMuni.risk_score);
  const alertActive = selectedMuni.risk_score >= 0.4;
  if (selCoords && alertActive) {
    if (!publicZoneCircle) {
      publicZoneCircle = new google.maps.Circle({
        map: publicMap,
        strokeColor: sevSel.colorHex,
        strokeOpacity: 0.6,
        strokeWeight: 1.5,
        fillColor: sevSel.colorHex,
        fillOpacity: 0.12,
        clickable: false
      });
    }
    publicZoneCircle.setOptions({ strokeColor: sevSel.colorHex, fillColor: sevSel.colorHex });
    publicZoneCircle.setCenter(selCoords);
    publicZoneCircle.setRadius(4000); // ~4 km advisory zone
    publicZoneCircle.setMap(publicMap);
  } else if (publicZoneCircle) {
    publicZoneCircle.setMap(null);
  }

  // Center once per basin; do not re-fit on every poll.
  if (selCoords && appState.publicCenteredBasin !== appState.selectedBasin) {
    publicMap.setCenter(selCoords);
    const c = BASIN_CENTERS[appState.selectedBasin] || BASIN_CENTERS.rio_cauca;
    publicMap.setZoom(c.zoom);
    appState.publicCenteredBasin = appState.selectedBasin;
  }

  requestGeolocationOnce();
}

// "You are here" point — shown only if geolocation is granted; silent on denial.
function requestGeolocationOnce() {
  if (appState.geoRequested || !navigator.geolocation) return;
  appState.geoRequested = true;
  navigator.geolocation.getCurrentPosition(
    (pos) => {
      if (!publicMap || typeof google === "undefined") return;
      const here = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      if (youAreHereMarker) {
        youAreHereMarker.setPosition(here);
      } else {
        youAreHereMarker = new google.maps.Marker({
          position: here,
          map: publicMap,
          title: "You are here",
          zIndex: 2000,
          icon: {
            path: google.maps.SymbolPath.CIRCLE,
            scale: 7,
            fillColor: "#38bdf8",
            fillOpacity: 1,
            strokeColor: "#07090f",
            strokeWeight: 2
          }
        });
      }
    },
    () => { /* denied or unavailable — skip silently */ },
    { enableHighAccuracy: false, timeout: 8000, maximumAge: 600000 }
  );
}

// ==========================================================================
// Uphill directive — Maps JS Elevation service (client-side)
// ==========================================================================
// Samples 8 points in a ring around the municipality, finds the direction
// rising fastest to higher ground. Hides the line if the service is unavailable
// or no surrounding point is higher (never fabricates a direction).
function computeUphillDirection(selectedMuni) {
  const lineEl = document.getElementById("public-alert-uphill");
  if (!lineEl) return;

  const coords = selectedMuni && municipalityCoords[selectedMuni.municipality];
  if (!coords || typeof google === "undefined" || !google.maps || !google.maps.ElevationService) {
    lineEl.hidden = true;
    return;
  }

  const name = selectedMuni.municipality;
  // Terrain is static, so a SUCCESSFUL direction is cached and reused.
  if (Object.prototype.hasOwnProperty.call(elevationDirCache, name)) {
    applyUphill(lineEl, elevationDirCache[name]);
    return;
  }
  // A query is already outstanding for this municipality; wait for its callback
  // rather than firing duplicates on every 5s poll.
  if (elevationInFlight.has(name)) return;
  elevationInFlight.add(name);

  if (!elevationService) elevationService = new google.maps.ElevationService();

  const radiusDeg = 0.025; // ~2.7 km
  const latRad = coords.lat * Math.PI / 180;
  const ring = COMPASS_8.map((_, i) => {
    const ang = (i * 45) * Math.PI / 180; // 0=N, clockwise
    return {
      lat: coords.lat + radiusDeg * Math.cos(ang),
      lng: coords.lng + (radiusDeg * Math.sin(ang)) / Math.cos(latRad)
    };
  });
  const locations = [{ lat: coords.lat, lng: coords.lng }, ...ring];

  elevationService.getElevationForLocations({ locations }, (results, status) => {
    elevationInFlight.delete(name); // query finished, clear the in-flight marker
    if (status !== "OK" || !results || results.length < 9) {
      // Genuine service failure: hide for now, do NOT cache, retry on next poll.
      applyUphill(lineEl, null);
      return;
    }
    const centerEl = results[0].elevation;
    let bestIdx = -1;
    let bestGain = 0;
    for (let i = 1; i < results.length; i++) {
      const gain = results[i].elevation - centerEl;
      if (gain > bestGain) { bestGain = gain; bestIdx = i - 1; }
    }
    const dir = bestIdx >= 0 ? COMPASS_8[bestIdx] : null;
    if (dir) {
      elevationDirCache[name] = dir; // cache ONLY a successful direction
      applyUphill(lineEl, dir);
    } else {
      // No surrounding point is higher: hide, do NOT cache, allow a later retry.
      applyUphill(lineEl, null);
    }
  });
}

function applyUphill(lineEl, dir) {
  if (dir) {
    lineEl.textContent = `Higher ground is to the ${dir}.`;
    lineEl.hidden = false;
  } else {
    lineEl.hidden = true;
  }
}

// ==========================================================================
// Nearest hospital / safe point + REAL walking route (Places + Directions)
// ==========================================================================
// Honest by construction: every label says "Nearest hospital / safe point",
// never "official shelter". On no result, REQUEST_DENIED, or any failure we
// show a clear "no route available" state and never draw a fabricated route.
// Destination choice is biased toward higher ground using live elevation plus
// the bundle's uphill compass direction.

// Place types treated as genuinely safer destinations.
const SAFE_PLACE_TYPES = ["hospital", "school", "stadium", "university"];
const SAFE_TYPE_LABELS = {
  hospital: "hospital",
  school: "school",
  stadium: "stadium",
  university: "university",
  city_hall: "public building",
  local_government_office: "public building"
};

function safeTypeLabel(types) {
  if (!Array.isArray(types)) return "safe point";
  for (const t of types) {
    if (SAFE_TYPE_LABELS[t]) return SAFE_TYPE_LABELS[t];
  }
  return "safe point";
}

// Haversine distance in metres (no extra Maps library required).
function haversineMeters(a, b) {
  const R = 6371000;
  const dLat = (b.lat - a.lat) * Math.PI / 180;
  const dLng = (b.lng - a.lng) * Math.PI / 180;
  const la1 = a.lat * Math.PI / 180;
  const la2 = b.lat * Math.PI / 180;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

// Initial bearing in degrees (0 = north, clockwise) from a to b.
function bearingDegrees(a, b) {
  const la1 = a.lat * Math.PI / 180;
  const la2 = b.lat * Math.PI / 180;
  const dLng = (b.lng - a.lng) * Math.PI / 180;
  const y = Math.sin(dLng) * Math.cos(la2);
  const x = Math.cos(la1) * Math.sin(la2) - Math.sin(la1) * Math.cos(la2) * Math.cos(dLng);
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360;
}

// Smallest absolute angular difference between two bearings (0..180).
function angleDiff(a, b) {
  const d = Math.abs(a - b) % 360;
  return d > 180 ? 360 - d : d;
}

// Resolve the routing origin: live geolocation if already granted, else the
// at-risk municipality's coordinates. Never blocks on a fresh permission prompt.
function resolveRouteOrigin(selectedMuni) {
  const muniCoords = municipalityCoords[selectedMuni.municipality];
  if (youAreHereMarker && typeof youAreHereMarker.getPosition === "function") {
    const p = youAreHereMarker.getPosition();
    if (p) {
      const here = { lat: p.lat(), lng: p.lng() };
      // Route from the device location only when it is plausibly inside the
      // monitored area. A viewer on another continent would otherwise get a
      // route through their own city, which reads as a broken feature.
      if (!muniCoords || haversineMeters(here, muniCoords) <= 40000) {
        return { coords: here, label: "your location" };
      }
      return muniCoords
        ? { coords: muniCoords, label: `${selectedMuni.municipality} (your device is outside the monitored area)` }
        : null;
    }
  }
  return muniCoords ? { coords: muniCoords, label: selectedMuni.municipality } : null;
}

// Promise wrapper around a single nearbySearch by type, ranked by distance.
function searchPlacesByType(origin, type) {
  return new Promise((resolve, reject) => {
    placesService.nearbySearch(
      { location: origin, rankBy: google.maps.places.RankBy.DISTANCE, type },
      (results, status) => {
        const S = google.maps.places.PlacesServiceStatus;
        if (status === S.OK && results) resolve(results.slice(0, 5));
        else if (status === S.ZERO_RESULTS) resolve([]);
        else reject(new Error(status)); // REQUEST_DENIED, OVER_QUERY_LIMIT, etc.
      }
    );
  });
}

// Gather candidate safe points across all types; dedupe by place_id.
async function gatherSafeCandidates(origin) {
  const settled = await Promise.allSettled(SAFE_PLACE_TYPES.map(t => searchPlacesByType(origin, t)));
  const anyResolved = settled.some(s => s.status === "fulfilled");
  if (!anyResolved) throw new Error("PLACES_FAILED"); // every type errored (e.g. REQUEST_DENIED)

  const seen = new Set();
  const candidates = [];
  settled.forEach(s => {
    if (s.status !== "fulfilled") return;
    s.value.forEach(p => {
      if (!p.place_id || seen.has(p.place_id) || !p.geometry || !p.geometry.location) return;
      seen.add(p.place_id);
      candidates.push({
        name: p.name,
        types: p.types || [],
        coords: { lat: p.geometry.location.lat(), lng: p.geometry.location.lng() }
      });
    });
  });
  return candidates.slice(0, 12); // cap elevation lookups
}

// Promise wrapper for batch elevation; resolves null on any failure (caller degrades).
function fetchElevations(points) {
  return new Promise((resolve) => {
    if (!google.maps.ElevationService) { resolve(null); return; }
    if (!elevationService) elevationService = new google.maps.ElevationService();
    elevationService.getElevationForLocations({ locations: points }, (results, status) => {
      if (status === "OK" && results && results.length === points.length) {
        resolve(results.map(r => r.elevation));
      } else {
        resolve(null);
      }
    });
  });
}

// Pick the destination: nearest genuinely safer point, biased toward higher
// ground. We restrict the choice to the nearest cluster of safe points so the
// route stays walkable, then bias uphill WITHIN that cluster — never trading a
// nearby refuge for a far one just because it sits higher.
const NEAR_CLUSTER = 5;
async function chooseHigherGroundDestination(origin, candidates, muniName) {
  const elevations = await fetchElevations([origin, ...candidates.map(c => c.coords)]);
  const enriched = candidates.map((c, i) => ({
    ...c,
    dist: haversineMeters(origin, c.coords),
    elev: elevations ? elevations[i + 1] : null
  }));
  const originElev = elevations ? elevations[0] : null;

  enriched.sort((a, b) => a.dist - b.dist);
  const near = enriched.slice(0, NEAR_CLUSTER); // nearest safe points only

  // Live elevation: among the nearest, choose the highest ground.
  const withElev = near.filter(c => c.elev !== null);
  if (originElev !== null && withElev.length) {
    withElev.sort((a, b) => b.elev - a.elev);
    const dest = withElev[0];
    return { dest, higher: dest.elev > originElev + 1 };
  }

  // Elevation degraded: bias by the bundle's uphill compass direction if known.
  const uphillDir = elevationDirCache[muniName];
  if (uphillDir && COMPASS_DEGREES[uphillDir] !== undefined) {
    const target = COMPASS_DEGREES[uphillDir];
    const aligned = near.filter(c => angleDiff(bearingDegrees(origin, c.coords), target) <= 90);
    const pool = aligned.length ? aligned : near;
    pool.sort((a, b) => a.dist - b.dist);
    return { dest: pool[0], higher: aligned.length > 0 };
  }

  return { dest: near[0], higher: false };
}

// Promise wrapper for a WALKING route.
function fetchWalkingRoute(origin, destination) {
  return new Promise((resolve, reject) => {
    directionsService.route(
      { origin, destination, travelMode: google.maps.TravelMode.WALKING },
      (result, status) => {
        if (status === "OK" && result) resolve(result);
        else reject(new Error(status));
      }
    );
  });
}

// Strip Google's HTML step instructions down to plain, readable text.
function stripHtml(html) {
  const tmp = document.createElement("div");
  tmp.innerHTML = html;
  return (tmp.textContent || tmp.innerText || "").replace(/\s+/g, " ").trim();
}

function setRouteStatus(message) {
  const el = document.getElementById("safe-route-status");
  if (el) el.textContent = message;
}

function clearSafeRoute() {
  if (directionsRenderer) directionsRenderer.setMap(null);
  const detail = document.getElementById("safe-route-detail");
  if (detail) detail.hidden = true;
}

// Main entry: find nearest safe point and render a real walking route.
async function findSafeRoute() {
  const btn = document.getElementById("find-safe-route-btn");
  const detail = document.getElementById("safe-route-detail");
  if (safeRouteBusy) return;

  const selectedMuni = appState.selectedMuni || (database.risk && database.risk.length ? database.risk[0] : null);
  if (!selectedMuni) { setRouteStatus("No at-risk area is selected yet."); return; }

  // Maps / Places must be loaded for any real result.
  if (typeof google === "undefined" || !google.maps || !google.maps.places || !publicMap) {
    clearSafeRoute();
    setRouteStatus("No route available right now. Mapping service is unavailable.");
    return;
  }

  const origin = resolveRouteOrigin(selectedMuni);
  if (!origin) {
    clearSafeRoute();
    setRouteStatus("No route available right now. Your area's location is unknown.");
    return;
  }

  safeRouteBusy = true;
  appState.routeMuni = selectedMuni.municipality;
  if (btn) { btn.disabled = true; btn.setAttribute("aria-busy", "true"); }
  if (detail) detail.hidden = true;
  setRouteStatus("Searching for the nearest hospital or safe point…");

  try {
    if (!placesService) placesService = new google.maps.places.PlacesService(publicMap);
    if (!directionsService) directionsService = new google.maps.DirectionsService();
    if (!directionsRenderer) {
      directionsRenderer = new google.maps.DirectionsRenderer({
        suppressMarkers: false,
        preserveViewport: false,
        polylineOptions: { strokeColor: "#38bdf8", strokeWeight: 5, strokeOpacity: 0.9 }
      });
    }

    const candidates = await gatherSafeCandidates(origin.coords);
    if (!candidates.length) {
      clearSafeRoute();
      setRouteStatus("No route available. No hospital or safe point was found nearby.");
      return;
    }

    const { dest, higher } = await chooseHigherGroundDestination(origin.coords, candidates, selectedMuni.municipality);
    setRouteStatus(`Calculating a walking route to ${dest.name}…`);

    const result = await fetchWalkingRoute(origin.coords, dest.coords);
    const leg = result.routes[0] && result.routes[0].legs[0];
    if (!leg) {
      clearSafeRoute();
      setRouteStatus("No route available. A walking route could not be calculated.");
      return;
    }

    // Draw the real route on the public map. Very short routes otherwise
    // fit-zoom past the styled tiles into a featureless canvas, so clamp.
    directionsRenderer.setMap(publicMap);
    directionsRenderer.setDirections(result);
    google.maps.event.addListenerOnce(publicMap, "idle", () => {
      if (publicMap.getZoom() > 16) publicMap.setZoom(16);
    });

    // Honest destination labeling — never "official shelter".
    const destEl = document.getElementById("safe-route-dest");
    const metaEl = document.getElementById("safe-route-meta");
    const stepsEl = document.getElementById("safe-route-steps");
    if (destEl) {
      destEl.textContent = `Nearest hospital / safe point: ${dest.name} (${safeTypeLabel(dest.types)})` +
        (higher ? " — on higher ground." : "");
    }
    if (metaEl) {
      metaEl.textContent = `Walking distance ${leg.distance.text}, about ${leg.duration.text}, from ${origin.label}.`;
    }
    if (stepsEl) {
      stepsEl.innerHTML = leg.steps.map(s => {
        const text = stripHtml(s.instructions);
        const dist = s.distance && s.distance.text ? ` (${s.distance.text})` : "";
        return `<li class="safe-route-step">${text}${dist}</li>`;
      }).join("");
    }
    if (detail) detail.hidden = false;
    setRouteStatus(`Route ready: ${leg.distance.text}, about ${leg.duration.text} on foot to ${dest.name}.`);
  } catch (err) {
    // Any Places/Directions failure (REQUEST_DENIED, ZERO_RESULTS, network) lands here.
    clearSafeRoute();
    setRouteStatus("No route available right now. The mapping service did not return a route.");
  } finally {
    safeRouteBusy = false;
    if (btn) { btn.disabled = false; btn.removeAttribute("aria-busy"); }
  }
}

function setupSafeRouteControls() {
  const btn = document.getElementById("find-safe-route-btn");
  if (btn) btn.addEventListener("click", findSafeRoute);
}

// ==========================================================================
// Tooltip positioning (escape card overflow clipping)
// ==========================================================================
// Cards clip overflow, so a tooltip positioned inside one gets cut off at the
// card edge. On show, switch the tooltip to fixed positioning computed from
// the trigger: centered above, clamped to the viewport horizontally, flipped
// below the trigger when there is no room above. Delegated listeners keep it
// working for tooltips re-rendered into the detail rail on every poll.
function positionTooltip(wrapper) {
  const tip = wrapper.querySelector(".tooltip-content");
  const trigger = wrapper.querySelector(".tooltip-trigger");
  if (!tip || !trigger || typeof trigger.getBoundingClientRect !== "function") return;

  const r = trigger.getBoundingClientRect();
  tip.style.position = "fixed";
  tip.style.bottom = "auto";
  tip.style.transform = "none";

  const w = tip.offsetWidth || 220;
  const h = tip.offsetHeight || 64;
  const margin = 8;

  let left = r.left + r.width / 2 - w / 2;
  left = Math.max(margin, Math.min(left, window.innerWidth - w - margin));

  let top = r.top - h - margin;
  let below = false;
  if (top < margin) {
    top = r.bottom + margin;
    below = true;
  }

  tip.style.left = `${left}px`;
  tip.style.top = `${top}px`;
  if (below) tip.classList.add("tooltip-below");
  else tip.classList.remove("tooltip-below");

  // Keep the arrow pointing at the trigger even when clamped to the viewport.
  const arrowX = Math.max(10, Math.min(r.left + r.width / 2 - left, w - 10));
  tip.style.setProperty("--tooltip-arrow-x", `${arrowX}px`);
}

function setupTooltipPositioning() {
  const reposition = (e) => {
    if (!e.target || typeof e.target.closest !== "function") return;
    const wrapper = e.target.closest(".tooltip-wrapper");
    if (wrapper) positionTooltip(wrapper);
  };
  document.addEventListener("mouseover", reposition);
  document.addEventListener("focusin", reposition);
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
  // Live seismic feed refreshes on the same poll, but independently: a missing
  // or failing seismic endpoint must never trip the offline banner. Prefers the
  // global /seismic-events contract; falls back to the legacy /live-seismic.
  fetchSeismicFeed();
  // Captured up front so a basin switch mid-flight can't mismark completion.
  const requestedBasin = appState.selectedBasin;
  try {
    const basinParam = `?basin=${requestedBasin}`;
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

    // A fetch for this basin has completed; the map overlay may now resolve
    // to either markers or an honest "no data" state.
    appState.lastFetchedBasin = requestedBasin;

    // Clear offline state if previously offline
    if (appState.isOffline) {
      setBackendOfflineState(false);
      initConsoleLog("Connection restored. Dashboard online.", "telemetry");
    }

    // Update DB
    database.risk = riskData;
    database.connector = statusData;
    database.alert = alertData;

    // One timeline sample per poll cycle, from data already fetched.
    recordRiskSamples(riskData);

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
    renderRiskTimeline();
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
// Live Risk Timeline (selected municipality's composite risk over the poll)
// ==========================================================================
// Rolling buffer per basin+municipality, appended once per poll cycle from
// the risk data the poll already loads — no extra fetches. Inline SVG only.
const RISK_TIMELINE_MAX_SAMPLES = 60;
const riskHistory = {}; // "basin|municipality" -> [{ t, score }]

function riskHistoryKey(basin, municipality) {
  return `${basin}|${municipality}`;
}

// Append one sample per municipality in the polled basin, so switching the
// selection shows that municipality's accumulated history, not a restart.
function recordRiskSamples(riskData) {
  if (!Array.isArray(riskData)) return;
  const now = Date.now();
  riskData.forEach(m => {
    if (!m || typeof m.risk_score !== "number") return;
    const key = riskHistoryKey(appState.selectedBasin, m.municipality);
    if (!riskHistory[key]) riskHistory[key] = [];
    riskHistory[key].push({ t: now, score: m.risk_score });
    if (riskHistory[key].length > RISK_TIMELINE_MAX_SAMPLES) {
      riskHistory[key].splice(0, riskHistory[key].length - RISK_TIMELINE_MAX_SAMPLES);
    }
  });
}

function prefersReducedMotion() {
  try {
    return typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch (e) {
    return true; // when unknown, prefer the non-animated rendering
  }
}

function renderRiskTimeline() {
  const chartEl = document.getElementById("risk-timeline-chart");
  const valueEl = document.getElementById("risk-timeline-value");
  const muniEl = document.getElementById("risk-timeline-muni");
  const summaryEl = document.getElementById("risk-timeline-summary");
  if (!chartEl) return;

  const selected = appState.selectedMuni;
  const samples = selected
    ? (riskHistory[riskHistoryKey(appState.selectedBasin, selected.municipality)] || [])
    : [];

  if (muniEl) muniEl.textContent = selected ? selected.municipality : "—";

  if (!selected || samples.length < 2) {
    chartEl.innerHTML = `<div class="risk-timeline-empty">Collecting samples&hellip;</div>`;
    if (valueEl) { valueEl.textContent = "--%"; valueEl.style.color = ""; }
    if (summaryEl) summaryEl.textContent = "Risk timeline is collecting samples.";
    return;
  }

  const latest = samples[samples.length - 1].score;
  const sev = getSeverityConfig(latest);
  if (valueEl) {
    valueEl.textContent = `${(latest * 100).toFixed(0)}%`;
    valueEl.style.color = sev.colorHex;
  }

  // ViewBox is 0..300 wide, 0..100 tall; score 0..1 maps bottom-to-top.
  const W = 300, H = 100;
  const stepX = W / (RISK_TIMELINE_MAX_SAMPLES - 1);
  const points = samples
    .map((s, i) => `${(i * stepX).toFixed(1)},${(H - Math.min(Math.max(s.score, 0), 1) * H).toFixed(1)}`)
    .join(" ");
  const lastX = ((samples.length - 1) * stepX).toFixed(1);
  const lastY = (H - Math.min(Math.max(latest, 0), 1) * H).toFixed(1);

  const animateClass = prefersReducedMotion() ? "" : "risk-timeline-line-animated";

  chartEl.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true" focusable="false" class="risk-timeline-svg">
      <!-- Threshold bands: warning 40-60, danger 60-80, critical 80-100 -->
      <rect x="0" y="0"  width="${W}" height="20" fill="#a855f7" opacity="0.10"></rect>
      <rect x="0" y="20" width="${W}" height="20" fill="#ef4444" opacity="0.09"></rect>
      <rect x="0" y="40" width="${W}" height="20" fill="#f59e0b" opacity="0.07"></rect>
      <line x1="0" y1="20" x2="${W}" y2="20" stroke="#a855f7" stroke-width="0.6" stroke-dasharray="3 3" opacity="0.55"></line>
      <line x1="0" y1="40" x2="${W}" y2="40" stroke="#ef4444" stroke-width="0.6" stroke-dasharray="3 3" opacity="0.55"></line>
      <line x1="0" y1="60" x2="${W}" y2="60" stroke="#f59e0b" stroke-width="0.6" stroke-dasharray="3 3" opacity="0.55"></line>
      <polyline class="risk-timeline-line ${animateClass}" points="${points}"
        fill="none" stroke="${sev.colorHex}" stroke-width="1.8"
        stroke-linejoin="round" stroke-linecap="round"></polyline>
      <circle cx="${lastX}" cy="${lastY}" r="2.6" fill="${sev.colorHex}"></circle>
    </svg>
    <div class="risk-timeline-band-labels" aria-hidden="true">
      <span class="band-label critical">80%</span>
      <span class="band-label danger">60%</span>
      <span class="band-label warning">40%</span>
    </div>
  `;

  if (summaryEl) {
    const scores = samples.map(s => s.score * 100);
    const minV = Math.min(...scores).toFixed(0);
    const maxV = Math.max(...scores).toFixed(0);
    summaryEl.textContent =
      `${selected.municipality} composite risk is ${(latest * 100).toFixed(0)}% (${sev.label}). ` +
      `Last ${samples.length} samples range from ${minV}% to ${maxV}%. ` +
      `Thresholds: warning 40%, danger 60%, critical 80%.`;
  }

  renderRiskTimelineTable(samples, selected);
}

// C3: data-table fallback for the sparkline.
function renderRiskTimelineTable(samples, selected) {
  const tableEl = document.getElementById("risk-timeline-table");
  if (!tableEl || tableEl.hidden) return;
  if (!selected || !samples || samples.length === 0) {
    tableEl.innerHTML = `<p class="chart-table-note">No samples yet.</p>`;
    return;
  }
  // One row per minute: the live 5s samples are near-identical and read as
  // duplicates in a table.
  const byMinute = new Map();
  samples.forEach(s => byMinute.set(Math.floor(s.t / 60000), s));
  const recent = [...byMinute.values()].slice(-12).reverse();
  tableEl.innerHTML = `
    <table class="chart-table">
      <caption class="visually-hidden">Recent composite risk samples for ${escapeHtml(selected.municipality)}</caption>
      <thead><tr><th scope="col">Time</th><th scope="col" class="num">Composite risk</th></tr></thead>
      <tbody>
        ${recent.map(s => `<tr>
          <td class="tabular-nums">${new Date(s.t).toLocaleTimeString()}</td>
          <td class="tabular-nums">${(s.score * 100).toFixed(0)}%</td>
        </tr>`).join("")}
      </tbody>
    </table>`;
}

// Seed the sparkline buffers from the server-recorded history so a fresh
// page load starts with real samples instead of "Collecting samples...".
async function seedRiskHistory(basin) {
  try {
    const res = await fetch(`${API_BASE}/risk-history?basin=${encodeURIComponent(basin)}`);
    if (!res.ok) return;
    const data = await res.json();
    const ticks = (data && Array.isArray(data.ticks)) ? data.ticks : [];
    if (!ticks.length) return;
    const seeded = new Set();
    ticks.forEach(tick => {
      if (!tick || typeof tick.t !== "number" || !tick.samples) return;
      Object.entries(tick.samples).forEach(([muni, score]) => {
        const key = riskHistoryKey(basin, muni);
        // Only pre-seed buffers the session has not started filling itself.
        if (riskHistory[key] && riskHistory[key].length && !seeded.has(key)) return;
        seeded.add(key);
        if (!riskHistory[key]) riskHistory[key] = [];
        riskHistory[key].push({ t: tick.t, score: Number(score) || 0 });
        if (riskHistory[key].length > RISK_TIMELINE_MAX_SAMPLES) {
          riskHistory[key].splice(0, riskHistory[key].length - RISK_TIMELINE_MAX_SAMPLES);
        }
      });
    });
    if (seeded.size) {
      initConsoleLog(`Risk timeline seeded with ${ticks.length} recorded ticks for ${basin}.`, "telemetry");
      renderRiskTimeline();
    }
  } catch (err) {
    console.warn("Could not seed risk history:", err && err.message);
  }
}

// ==========================================================================
// River & Rainfall Trend (warehouse history: real rainfall, seeded river)
// ==========================================================================
async function fetchTelemetryHistory(basin) {
  const chartEl = document.getElementById("telemetry-trend-chart");
  try {
    const res = await fetch(`${API_BASE}/telemetry-history?basin=${encodeURIComponent(basin)}`);
    if (!res.ok) throw new Error(`Status ${res.status}`);
    database.telemetryHistory = await res.json();
    renderTelemetryTrend();
  } catch (err) {
    database.telemetryHistory = null;
    if (chartEl) chartEl.innerHTML = `<div class="risk-timeline-empty">Telemetry history unavailable.</div>`;
    console.warn("Could not load telemetry history:", err && err.message);
  }
}

function renderTelemetryTrend() {
  const chartEl = document.getElementById("telemetry-trend-chart");
  const summaryEl = document.getElementById("telemetry-trend-summary");
  if (!chartEl) return;
  const hist = database.telemetryHistory;
  const allRiver = (hist && Array.isArray(hist.river)) ? hist.river.filter(r => r && r.time) : [];
  const allRain = (hist && Array.isArray(hist.rainfall)) ? hist.rainfall.filter(r => r && r.time) : [];
  // GloFAS model discharge: chart only the recent window so the 31-day series
  // does not stretch the x-domain away from the 48h rainfall bars.
  const allDischarge = (hist && Array.isArray(hist.discharge)) ? hist.discharge.filter(r => r && r.date) : [];
  const chartDischarge = allDischarge.slice(-8);

  // Minimum-data rule: a series under 3 points is dropped from the chart and
  // reported as a text KPI instead — never a lone floating dot.
  const MIN_POINTS = 3;
  const riverOk = allRiver.length >= MIN_POINTS;
  const rainOk = allRain.length >= MIN_POINTS;
  const dischargeOk = chartDischarge.length >= MIN_POINTS;
  const river = riverOk ? allRiver : [];
  const rain = rainOk ? allRain : [];
  const discharge = dischargeOk ? chartDischarge : [];

  const kpiNotes = [];
  if (!riverOk && allRiver.length) {
    const last = allRiver[allRiver.length - 1];
    kpiNotes.push(`River level: ${(Number(last.river_level_m) || 0).toFixed(1)} m vs ${(Number(last.threshold_m) || 0).toFixed(1)} m threshold (${allRiver.length} reading${allRiver.length === 1 ? "" : "s"} in window; too sparse to chart)`);
  }
  if (!rainOk && allRain.length) {
    const last = allRain[allRain.length - 1];
    kpiNotes.push(`Rainfall: ${(Number(last.precipitation_mm) || 0).toFixed(1)} mm/h latest (${allRain.length} reading${allRain.length === 1 ? "" : "s"} in window; too sparse to chart)`);
  }
  if (!dischargeOk && allDischarge.length) {
    const last = allDischarge[allDischarge.length - 1];
    kpiNotes.push(`River discharge (GloFAS model): ${(Number(last.discharge_m3s) || 0).toLocaleString()} m³/s latest (${allDischarge.length} day${allDischarge.length === 1 ? "" : "s"}; too sparse to chart)`);
  }
  const kpiHtml = kpiNotes.length
    ? `<div class="trend-kpi-notes">${kpiNotes.map(n => `<span>${escapeHtml(n)}</span>`).join("")}</div>`
    : "";

  if (!riverOk && !rainOk && !dischargeOk) {
    chartEl.innerHTML = `<div class="risk-timeline-empty">Not enough telemetry history to chart yet. The series grows as live readings accumulate.${kpiHtml}</div>`;
    if (summaryEl) summaryEl.textContent = "Telemetry history is still accumulating. " + kpiNotes.join(" ");
    renderTelemetryTrendTable(allRiver, allRain, allDischarge);
    return;
  }

  const W = 300, H = 100, PAD = 4;
  const times = [...river.map(r => Date.parse(r.time)), ...rain.map(r => Date.parse(r.time)),
                 ...discharge.map(r => Date.parse(r.date))].filter(t => !isNaN(t));
  const minT = Math.min(...times), maxT = Math.max(...times);
  const spanT = Math.max(1, maxT - minT);
  const x = t => PAD + ((t - minT) / spanT) * (W - 2 * PAD);

  // Rainfall bars: own scale from zero to its max.
  const maxRain = Math.max(1, ...rain.map(r => Number(r.precipitation_mm) || 0));
  const rainBars = rain.map(r => {
    const v = Number(r.precipitation_mm) || 0;
    const h = (v / maxRain) * (H * 0.45);
    return `<rect x="${(x(Date.parse(r.time)) - 1.6).toFixed(1)}" y="${(H - h).toFixed(1)}" width="3.2" height="${h.toFixed(1)}"
              fill="var(--primary)" opacity="0.45">
              <title>${new Date(r.time).toLocaleString()}: ${v.toFixed(1)} mm rainfall (live)</title>
            </rect>`;
  }).join("");

  // River line: scale around level + threshold.
  let riverLine = "", thresholdLine = "", breachMarks = "";
  const threshold = river.length ? Number(river[river.length - 1].threshold_m) || 0 : 0;
  if (river.length) {
    const levels = river.map(r => Number(r.river_level_m) || 0);
    const lo = Math.min(...levels, threshold) * 0.92;
    const hi = Math.max(...levels, threshold) * 1.08;
    const y = v => H - PAD - ((v - lo) / Math.max(0.001, hi - lo)) * (H - 2 * PAD);
    const pts = river.map(r => `${x(Date.parse(r.time)).toFixed(1)},${y(Number(r.river_level_m) || 0).toFixed(1)}`);
    riverLine = river.length > 1
      ? `<polyline points="${pts.join(" ")}" fill="none" stroke="#38bdf8" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"></polyline>`
      : `<circle cx="${pts[0].split(",")[0]}" cy="${pts[0].split(",")[1]}" r="2.5" fill="#38bdf8"></circle>`;
    if (threshold > 0) {
      thresholdLine = `<line x1="0" y1="${y(threshold).toFixed(1)}" x2="${W}" y2="${y(threshold).toFixed(1)}"
        stroke="#ef4444" stroke-width="0.8" stroke-dasharray="4 3" opacity="0.8"></line>`;
      // Breach markers: shape, not color alone.
      breachMarks = river.filter(r => (Number(r.river_level_m) || 0) > threshold).map(r => {
        const bx = x(Date.parse(r.time)), by = y(Number(r.river_level_m) || 0);
        return `<path d="M ${bx.toFixed(1)} ${(by - 4).toFixed(1)} l 3.4 5.8 l -6.8 0 Z" fill="#ef4444">
                  <title>${new Date(r.time).toLocaleString()}: ${(Number(r.river_level_m) || 0).toFixed(1)} m exceeds the ${threshold.toFixed(1)} m threshold</title>
                </path>`;
      }).join("");
    }
  }

  // GloFAS discharge line: own scale, distinct color, always-dashed so the
  // model series is visually distinct from the (gauge-style) river level.
  let dischargeLine = "";
  if (discharge.length) {
    const vals = discharge.map(r => Number(r.discharge_m3s) || 0);
    const dLo = Math.min(...vals) * 0.95, dHi = Math.max(...vals) * 1.05;
    const dy = v => H - PAD - ((v - dLo) / Math.max(0.001, dHi - dLo)) * (H * 0.55);
    const pts = discharge.map(r => `${x(Date.parse(r.date)).toFixed(1)},${dy(Number(r.discharge_m3s) || 0).toFixed(1)}`);
    dischargeLine = `<polyline points="${pts.join(" ")}" fill="none" stroke="#34d399" stroke-width="1.4"
      stroke-dasharray="5 3" stroke-linejoin="round" stroke-linecap="round" opacity="0.9">
      <title>River discharge (GloFAS model), m³/s</title></polyline>`;
  }

  // Time orientation: a gridline every 12h plus start/end labels (G5).
  let timeTicks = "";
  const TICK_MS = 12 * 3600 * 1000;
  for (let t = Math.ceil(minT / TICK_MS) * TICK_MS; t < maxT; t += TICK_MS) {
    timeTicks += `<line x1="${x(t).toFixed(1)}" y1="0" x2="${x(t).toFixed(1)}" y2="${H}"
      stroke="rgba(255,255,255,0.07)" stroke-width="0.6"></line>`;
  }
  const fmtTick = t => new Date(t).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  chartEl.innerHTML = `
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true" focusable="false" class="telemetry-trend-svg">
      ${timeTicks}${rainBars}${thresholdLine}${riverLine}${dischargeLine}${breachMarks}
    </svg>
    <div class="trend-legend" aria-hidden="true">
      <span class="trend-legend-item"><span class="trend-swatch trend-swatch-river"></span>River level (m)</span>
      <span class="trend-legend-item"><span class="trend-swatch trend-swatch-rain"></span>Rainfall (mm/h)</span>
      <span class="trend-legend-item"><span class="trend-swatch trend-swatch-discharge"></span>Discharge (GloFAS model)</span>
      <span class="trend-legend-item"><span class="trend-swatch trend-swatch-threshold"></span>Alert threshold</span>
    </div>
    <div class="trend-time-axis tabular-nums" aria-hidden="true">
      <span>${fmtTick(minT)}</span>
      <span>${fmtTick(maxT)}</span>
    </div>${kpiHtml}`;

  if (summaryEl) {
    const latestRiver = river.length ? Number(river[river.length - 1].river_level_m) || 0 : null;
    const totalRain = rain.reduce((acc, r) => acc + (Number(r.precipitation_mm) || 0), 0);
    const breaches = threshold > 0 ? river.filter(r => (Number(r.river_level_m) || 0) > threshold).length : 0;
    const latestDischarge = allDischarge.length ? Number(allDischarge[allDischarge.length - 1].discharge_m3s) || 0 : null;
    summaryEl.textContent =
      `${rain.length} hourly rainfall readings totaling ${totalRain.toFixed(1)} mm. ` +
      (latestRiver !== null
        ? `Latest river level ${latestRiver.toFixed(1)} m against a ${threshold.toFixed(1)} m threshold; ${breaches} reading${breaches === 1 ? "" : "s"} above threshold. `
        : `No charted river readings in the window. `) +
      (latestDischarge !== null ? `Latest modeled river discharge ${latestDischarge.toLocaleString()} m³/s (GloFAS).` : "") +
      (kpiNotes.length ? " " + kpiNotes.join(" ") : "");
  }

  renderTelemetryTrendTable(allRiver, allRain, allDischarge);
}

// C3: data-table fallback for the trend chart.
function renderTelemetryTrendTable(river, rain, discharge) {
  const tableEl = document.getElementById("telemetry-trend-table");
  if (!tableEl || tableEl.hidden) return;
  const riverRows = (river || []).slice(-10).reverse().map(r => `<tr>
      <td class="tabular-nums">${new Date(r.time).toLocaleString()}</td>
      <td class="tabular-nums">${(Number(r.river_level_m) || 0).toFixed(1)} m</td>
      <td class="tabular-nums">${(Number(r.threshold_m) || 0).toFixed(1)} m</td>
    </tr>`).join("");
  const rainRows = (rain || []).slice(-10).reverse().map(r => `<tr>
      <td class="tabular-nums">${new Date(r.time).toLocaleString()}</td>
      <td class="tabular-nums">${(Number(r.precipitation_mm) || 0).toFixed(1)} mm</td>
    </tr>`).join("");
  tableEl.innerHTML = `
    <table class="chart-table">
      <caption>River level (pipeline data, simulated gauge)</caption>
      <thead><tr><th scope="col">Time</th><th scope="col">Level</th><th scope="col">Threshold</th></tr></thead>
      <tbody>${riverRows || `<tr><td colspan="3">No readings in the window.</td></tr>`}</tbody>
    </table>
    <table class="chart-table">
      <caption>Hourly rainfall (live recorded)</caption>
      <thead><tr><th scope="col">Hour</th><th scope="col">Rainfall</th></tr></thead>
      <tbody>${rainRows || `<tr><td colspan="2">No readings in the window.</td></tr>`}</tbody>
    </table>
    <table class="chart-table">
      <caption>Daily river discharge (GloFAS model)</caption>
      <thead><tr><th scope="col">Date</th><th scope="col">Discharge</th></tr></thead>
      <tbody>${(discharge || []).slice(-10).reverse().map(r => `<tr>
        <td class="tabular-nums">${escapeHtml(r.date)}</td>
        <td class="tabular-nums">${(Number(r.discharge_m3s) || 0).toLocaleString()} m³/s</td>
      </tr>`).join("") || `<tr><td colspan="2">No model data yet.</td></tr>`}</tbody>
    </table>`;
}

function setupChartTableToggles() {
  const wire = (btnId, wrapId, rerender) => {
    const btn = document.getElementById(btnId);
    const wrap = document.getElementById(wrapId);
    if (!btn || !wrap) return;
    btn.addEventListener("click", () => {
      wrap.hidden = !wrap.hidden;
      btn.setAttribute("aria-pressed", String(!wrap.hidden));
      btn.textContent = wrap.hidden ? "View as table" : "Hide table";
      if (!wrap.hidden) rerender();
    });
  };
  wire("timeline-table-toggle", "risk-timeline-table", () => renderRiskTimeline());
  wire("trend-table-toggle", "telemetry-trend-table", () => renderTelemetryTrend());
}

// ==========================================================================
// Live Seismic Activity (real USGS events + clearly-labeled simulated ones)
// ==========================================================================
// Contract: GET /live-seismic?basin=<id> -> newest-first list of
// { municipality, magnitude, place, time, depth_km, latitude, longitude, simulated }.
// Honesty: events with simulated:true are always badged SIMULATED; real events
// are labeled as live USGS data. Never blended.
async function fetchLiveSeismic() {
  try {
    const res = await fetch(`${API_BASE}/live-seismic?basin=${appState.selectedBasin}`);
    if (!res.ok) throw new Error(`Status ${res.status}`);
    const data = await res.json();
    if (!Array.isArray(data)) throw new Error("Unexpected /live-seismic payload");
    database.liveSeismic = data;
    appState.seismicFeedAvailable = true;
  } catch (err) {
    // Endpoint missing (backend not yet deployed) or unreachable: show an
    // honest unavailable state, never stale or fabricated events.
    database.liveSeismic = [];
    appState.seismicFeedAvailable = false;
  }
  appState.simulatedActive = database.liveSeismic.some(ev => ev && ev.simulated === true);
  renderLiveSeismic();
}

// Magnitude buckets reuse the existing severity color scale.
function getMagnitudeSeverity(mag) {
  if (mag >= 6.0) return SEVERITY_SCALE.CRITICAL;
  if (mag >= 5.0) return SEVERITY_SCALE.DANGER;
  if (mag >= 4.0) return SEVERITY_SCALE.WARNING;
  return SEVERITY_SCALE.LOW;
}

function formatRelativeTime(isoString) {
  if (!isoString) return "unknown time";
  const t = new Date(isoString).getTime();
  if (isNaN(t)) return "unknown time";
  const diffSec = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (diffSec < 60) return `${diffSec}s ago`;
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ${mins % 60}m ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function renderLiveSeismic() {
  const container = document.getElementById("seismic-feed-container");
  if (!container) return;

  // Legacy basin-scoped rendering has no active-regions summary; clear any
  // strip left behind by the global feed so stale regions never linger.
  const regionsEl = document.getElementById("seismic-regions-container");
  if (regionsEl) regionsEl.innerHTML = "";

  if (!appState.seismicFeedAvailable) {
    container.innerHTML = `<div class="empty-alerts">Live seismic feed unavailable. Awaiting USGS connector...</div>`;
    return;
  }

  const events = [...database.liveSeismic].filter(ev => ev && typeof ev.magnitude === "number");
  if (events.length === 0) {
    container.innerHTML = `<div class="empty-alerts">No recent seismic activity in range.</div>`;
    return;
  }

  // Contract is newest-first; sort defensively so ordering never regresses.
  events.sort((a, b) => new Date(b.time) - new Date(a.time));

  container.innerHTML = events.map(ev => {
    const sev = getMagnitudeSeverity(ev.magnitude);
    const sourceTag = ev.simulated === true
      ? `<span class="badge badge-simulated">SIMULATED</span>`
      : `<span class="seismic-source-tag">LIVE &middot; USGS</span>`;
    const depthText = (typeof ev.depth_km === "number") ? `${ev.depth_km.toFixed(0)} km depth` : "depth unknown";
    return `
      <div class="seismic-event-row ${ev.simulated === true ? 'simulated' : ''}" style="border-left: 3px solid ${sev.colorHex};">
        <div class="seismic-mag tabular-nums" style="color: ${sev.colorHex};">M ${ev.magnitude.toFixed(1)}</div>
        <div class="seismic-event-info">
          <div class="seismic-event-title">
            <strong>${ev.municipality || "Unknown area"}</strong>
            ${sourceTag}
          </div>
          <div class="seismic-event-place">${ev.place || ""}</div>
          <div class="seismic-event-meta tabular-nums">${formatRelativeTime(ev.time)} &middot; ${depthText}</div>
        </div>
      </div>
    `;
  }).join("");
}

// ==========================================================================
// Live Seismic Events feed (global /seismic-events + click-to-focus)
// ==========================================================================
// Contract: GET /seismic-events -> { events: [{ id, magnitude, place, time,
// latitude, longitude, depth_km, simulated }], active_regions: [{ region,
// count, max_magnitude }] }. Clicking an event calls GET /seismic-focus?id=
// and opens a transient, clearly-labeled SEISMIC-ONLY focus view on the
// epicenter. While the endpoint is not deployed, the legacy basin-scoped
// /live-seismic feed renders instead, so the panel never breaks.

// Escaper for the new feed only: place/region/narration strings come from
// external feeds and the narration model, so they never land as raw HTML.
function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function fetchSeismicFeed() {
  try {
    const res = await fetch(`${API_BASE}/seismic-events`);
    if (!res.ok) throw new Error(`Status ${res.status}`);
    const data = await res.json();
    if (!data || !Array.isArray(data.events)) throw new Error("Unexpected /seismic-events payload");
    database.seismicEvents = {
      events: data.events.filter(ev => ev && typeof ev.magnitude === "number"),
      active_regions: Array.isArray(data.active_regions) ? data.active_regions : []
    };
    appState.seismicEventsAvailable = true;
    appState.simulatedActive = database.seismicEvents.events.some(ev => ev.simulated === true);
    renderSeismicEvents();
  } catch (err) {
    // Endpoint missing (backend contract not deployed yet) or unreachable:
    // keep the legacy basin-scoped feed working exactly as before.
    appState.seismicEventsAvailable = false;
    fetchLiveSeismic();
  }
}

// ==========================================================================
// Scope strip: live navigation. One pinned monitored-basin card plus the
// seismic regions that have events in the 48h feed. Picking aligns the page.
// ==========================================================================
function renderScopeStrip() {
  const strip = document.getElementById("scope-strip");
  if (!strip) return;

  const basinScoped = !appState.regionFilter && !appState.seismicFocus;
  const scopedBasin = (appState.basins || []).find(b => b && b.id === appState.selectedBasin);
  const basinName = scopedBasin ? scopedBasin.name : "Rio Cauca";
  const basinSimulated = !!(scopedBasin && scopedBasin.simulated);

  // Regions present in the live 48h feed, strongest live magnitude first.
  const counts = {};
  (database.seismicEvents.events || []).forEach(ev => {
    const region = eventRegion(ev);
    if (!region) return;
    if (!counts[region]) counts[region] = { region: region, count: 0, maxMag: 0 };
    counts[region].count += 1;
    counts[region].maxMag = Math.max(counts[region].maxMag, Number(ev.magnitude) || 0);
  });
  const liveRegions = Object.values(counts).sort((a, b) => (b.maxMag - a.maxMag) || (b.count - a.count));

  strip.innerHTML = `
    <button type="button" class="scope-item scope-basin ${basinScoped ? "active" : ""}"
            data-scope-basin="1" aria-pressed="${basinScoped}">
      <span class="scope-item-name">${escapeHtml(basinName)}</span>
      <span class="scope-item-meta">Monitored basin &middot; ${basinSimulated ? "SIMULATED" : "live pipeline"}</span>
    </button>
    ${liveRegions.map(r => {
      const sev = getMagnitudeSeverity(r.maxMag);
      const active = appState.regionFilter === r.region;
      return `
      <button type="button" class="scope-item ${active ? "active" : ""}"
              data-region="${escapeHtml(r.region)}" aria-pressed="${active}"
              style="border-left-color: ${sev.colorHex};">
        <span class="scope-item-name">${escapeHtml(r.region)}</span>
        <span class="scope-item-meta tabular-nums">${r.count} live &middot; max M ${r.maxMag.toFixed(1)}</span>
      </button>`;
    }).join("")}`;

  // Basin-scoped panels carry an explicit scope chip and collapse while a
  // seismic scope owns the page (G2).
  document.querySelectorAll("[data-scope-chip]").forEach(chip => {
    chip.textContent = `${basinName.toUpperCase()} BASIN${basinSimulated ? " · SIMULATED" : ""}`;
  });
  updateBasinPanelSubordination();
}

// While a seismic scope (region pick or event focus) is active, the
// basin-scoped panels collapse to their header so the page never shows
// Colombia panels at full volume under a Philippines map. Click to expand.
function updateBasinPanelSubordination() {
  // Information stays consequent with the selection: while a seismic scope
  // (region pick or event focus) owns the page, the basin-only panels
  // (timeline, trend, triage) disappear entirely. No flood/river model
  // exists for arbitrary event locations, so there is nothing honest those
  // panels could show for the selection. They return with the basin scope.
  const seismicScoped = !!(appState.seismicFocus || appState.regionFilter);
  document.querySelectorAll(".risk-timeline-panel, .telemetry-trend-panel, .alerts-panel").forEach(panel => {
    panel.classList.toggle("scope-hidden", seismicScoped);
    panel.classList.remove("subordinated", "seismic-scoped");
  });
}

// Return the page to the monitored-basin scope (the pinned strip card).
function selectBasinScope() {
  if (appState.regionFilter) {
    appState.regionFilter = null;
    renderSeismicEvents();
  }
  if (appState.seismicFocus) {
    exitSeismicFocus(); // refits the basin and clears the rail
  } else {
    appState.boundsFitForBasin = null;
    renderMapMarkers();
  }
  renderScopeStrip();
}

// Region of one event, matching sql/seismic_active_regions.sql: the text
// after the last comma of the USGS place string (or the whole string).
function eventRegion(ev) {
  const place = (ev && ev.place) ? String(ev.place) : "";
  const idx = place.lastIndexOf(",");
  return (idx >= 0 ? place.slice(idx + 1) : place).trim();
}

// Pick (or clear) a region scope: the feed filters to it, the map fits its
// epicenters, and the rail focuses the most recent event there. Clearing
// returns to the monitored-basin scope.
function toggleRegionFilter(region) {
  if (appState.regionFilter === region) {
    selectBasinScope();
    return;
  }
  appState.regionFilter = region;
  renderSeismicEvents();

  const matches = (database.seismicEvents.events || [])
    .filter(ev => eventRegion(ev) === region &&
      typeof ev.latitude === "number" && typeof ev.longitude === "number")
    .sort((a, b) => (new Date(b.time) - new Date(a.time)) || (b.magnitude - a.magnitude));

  if (map && typeof google !== "undefined" && matches.length) {
    const bounds = new google.maps.LatLngBounds();
    matches.forEach(ev => bounds.extend({ lat: ev.latitude, lng: ev.longitude }));
    map.fitBounds(bounds);
    if (matches.length === 1) map.setZoom(6);
    initConsoleLog(`Map fitted to ${matches.length} recent event${matches.length === 1 ? "" : "s"} in ${region}.`, "telemetry");
  }

  // The rail aligns to the region's most recent event; the map keeps the
  // region-wide fit instead of snapping to that single epicenter.
  if (matches.length) {
    focusSeismicEvent(matches[0].id, { keepMapView: true });
  }
}

function renderSeismicEvents() {
  const container = document.getElementById("seismic-feed-container");
  const regionsEl = document.getElementById("seismic-regions-container");
  if (!container) return;

  const events = database.seismicEvents.events;
  const activeRegions = database.seismicEvents.active_regions;

  // 30-day activity context row (collapsed by default): every active region,
  // non-interactive. Live navigation happens in the scope strip, which only
  // shows regions that actually have events in the 48h feed.
  if (regionsEl) {
    if (!activeRegions.length) {
      regionsEl.innerHTML = "";
    } else {
      const regions = [...activeRegions].sort((a, b) =>
        ((b.max_magnitude || 0) - (a.max_magnitude || 0)) || ((b.count || 0) - (a.count || 0)));
      regionsEl.innerHTML = regions.map(r => {
        const maxMag = typeof r.max_magnitude === "number" ? r.max_magnitude : 0;
        const sev = getMagnitudeSeverity(maxMag);
        const live48 = (events || []).filter(ev => eventRegion(ev) === r.region).length;
        return `
          <span class="seismic-region-chip context" style="border-left-color: ${sev.colorHex};">
            <span class="seismic-region-name">${escapeHtml(r.region)}</span>
            <span class="seismic-region-meta tabular-nums">${Number(r.count) || 0} in 30d &middot; max M ${maxMag.toFixed(1)}${live48 ? ` &middot; ${live48} live` : ""}</span>
          </span>`;
      }).join("");
    }
  }

  renderScopeStrip();

  if (events.length === 0) {
    container.innerHTML = `<div class="empty-alerts">No seismic events in the live feed right now.</div>`;
    return;
  }

  // Newest first; equally-recent events rank strongest first.
  const sorted = [...events].sort((a, b) =>
    (new Date(b.time) - new Date(a.time)) || (b.magnitude - a.magnitude));

  // Region filter: same parse as the active-regions SQL (text after the last
  // comma of the USGS place string).
  const filtered = appState.regionFilter
    ? sorted.filter(ev => eventRegion(ev) === appState.regionFilter)
    : sorted;

  let filterBar = "";
  if (appState.regionFilter) {
    filterBar = `
      <div class="seismic-filter-bar">
        <span>Showing 48h events in <strong>${escapeHtml(appState.regionFilter)}</strong></span>
        <button type="button" class="btn btn-sm seismic-filter-clear" data-clear-region-filter="1">Clear filter</button>
      </div>`;
  }

  if (appState.regionFilter && filtered.length === 0) {
    container.innerHTML = filterBar + `
      <div class="empty-alerts">
        ${escapeHtml(appState.regionFilter)} is active over the last 30 days, but has no M4.5+ events in the last 48 hours.
      </div>`;
    return;
  }

  container.innerHTML = filterBar + filtered.map(ev => {
    const sev = getMagnitudeSeverity(ev.magnitude);
    const simulated = ev.simulated === true;
    const sourceTag = simulated
      ? `<span class="badge badge-simulated">SIMULATED</span>`
      : `<span class="seismic-source-tag">LIVE &middot; USGS</span>`;
    const depthText = (typeof ev.depth_km === "number") ? `${ev.depth_km.toFixed(0)} km depth` : "depth unknown";
    const rel = formatRelativeTime(ev.time);
    const aria = `Focus map on magnitude ${ev.magnitude.toFixed(1)} ${simulated ? "simulated" : "live USGS"} seismic event, ${ev.place || "unknown location"}, ${rel}, ${depthText}`;
    return `
      <button type="button"
              class="seismic-event-row seismic-event-btn ${simulated ? "simulated" : ""}"
              data-event-id="${escapeHtml(ev.id)}"
              aria-label="${escapeHtml(aria)}"
              style="border-left: 3px solid ${sev.colorHex};">
        <div class="seismic-mag tabular-nums" style="color: ${sev.colorHex};">M ${ev.magnitude.toFixed(1)}</div>
        <div class="seismic-event-info">
          <div class="seismic-event-title">
            <strong>${escapeHtml(ev.place || "Unknown location")}</strong>
            ${sourceTag}
          </div>
          <div class="seismic-event-meta tabular-nums">${rel} &middot; ${depthText}</div>
        </div>
      </button>`;
  }).join("");
}

// Click-to-focus: fetch the seismic-only assessment for one event and open
// the transient focus view (map centered on the epicenter + detail rail).
async function focusSeismicEvent(eventId, opts = {}) {
  if (!eventId || appState.isOffline) return;
  initConsoleLog(`Requesting seismic-only focus for event ${eventId}...`, "action");

  // Instant feedback: the feed row already carries the event facts, so the
  // rail and map respond immediately; risk + narration stream in afterwards.
  const known = (database.seismicEvents.events || []).find(ev => ev && ev.id === eventId);
  if (known) {
    appState.seismicFocus = { event: known, pending: true };
    renderSeismicFocusRail();
    renderScopeStrip(); // hide basin-only panels with the selection, instantly
    placeSeismicFocusOnMap(opts.keepMapView);
    const mapPanel = document.getElementById("risk-map-container");
    if (mapPanel && typeof mapPanel.scrollIntoView === "function") {
      mapPanel.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "nearest" });
    }
  }

  const stillFocused = () =>
    appState.seismicFocus && appState.seismicFocus.event && appState.seismicFocus.event.id === eventId;

  // Real conditions at the epicenter (rainfall observed, discharge + soil
  // modeled) load in parallel with the assessment.
  const evForConditions = known;
  if (evForConditions && typeof evForConditions.latitude === "number" && typeof evForConditions.longitude === "number") {
    fetchLocationConditions(eventId, evForConditions.latitude, evForConditions.longitude);
  }

  try {
    const res = await fetch(`${API_BASE}/seismic-focus?id=${encodeURIComponent(eventId)}`);
    if (!res.ok) throw new Error(`Status ${res.status}`);
    const data = await res.json();
    if (!data || !data.event) throw new Error("Unexpected /seismic-focus payload");
    // The user may have clicked another event or closed the focus meanwhile.
    if (known && !stillFocused()) return;
    appState.seismicFocus = data;
    renderSeismicFocusRail();
    placeSeismicFocusOnMap(opts.keepMapView);
    const ev = data.event;
    initConsoleLog(
      `SEISMIC FOCUS: M ${(Number(ev.magnitude) || 0).toFixed(1)} — ${ev.place || "unknown location"} ` +
      `${ev.simulated === true ? "(SIMULATED)" : "(LIVE USGS)"}`, "telemetry");
    if (!known) {
      const mapPanel = document.getElementById("risk-map-container");
      if (mapPanel && typeof mapPanel.scrollIntoView === "function") {
        mapPanel.scrollIntoView({ behavior: prefersReducedMotion() ? "auto" : "smooth", block: "nearest" });
      }
      if (typeof ev.latitude === "number" && typeof ev.longitude === "number") {
        fetchLocationConditions(eventId, ev.latitude, ev.longitude);
      }
    }
  } catch (err) {
    initConsoleLog(`Seismic focus failed: ${err.message}. The /seismic-focus endpoint may not be deployed yet.`, "error");
    if (known && stillFocused()) {
      appState.seismicFocus.pending = false;
      appState.seismicFocus.error = true;
      renderSeismicFocusRail();
    }
  }
}

// Conditions at the epicenter: keyed by event id so stale responses for a
// previous focus never render into the current one.
async function fetchLocationConditions(eventId, lat, lng) {
  appState.locationConditions = { eventId: eventId, pending: true };
  try {
    const res = await fetch(`${API_BASE}/location-conditions?lat=${lat}&lng=${lng}`);
    if (!res.ok) throw new Error(`Status ${res.status}`);
    const data = await res.json();
    if (!appState.locationConditions || appState.locationConditions.eventId !== eventId) return;
    appState.locationConditions = { eventId: eventId, pending: false, data: data };
  } catch (err) {
    if (!appState.locationConditions || appState.locationConditions.eventId !== eventId) return;
    appState.locationConditions = { eventId: eventId, pending: false, data: null };
  }
  if (appState.seismicFocus && appState.seismicFocus.event && appState.seismicFocus.event.id === eventId) {
    renderSeismicFocusRail();
    if (appState.mode === "public") renderPublicView();
  }
}

// Markup for the conditions block (rail flavor). Returns "" when there is
// nothing to show; skeletons while pending.
function conditionsBlockHtml(eventId) {
  const lc = appState.locationConditions;
  if (!lc || lc.eventId !== eventId) return "";
  if (lc.pending) {
    return `
      <div class="epicenter-conditions" aria-busy="true">
        <span class="drawer-label">Conditions at the epicenter &middot; loading&hellip;</span>
        <span class="skeleton-block" style="width: 90%; height: 11px; margin-top: 6px;" aria-hidden="true"></span>
        <span class="skeleton-block" style="width: 75%; height: 11px; margin-top: 5px;" aria-hidden="true"></span>
      </div>`;
  }
  const d = lc.data;
  if (!d || (!d.rainfall && !d.river_discharge && !d.soil_moisture)) return "";
  const prov = d.provenance || {};
  const lines = [];
  if (d.rainfall) {
    lines.push(`<div class="condition-line"><span>Rain, last 24h: <strong class="tabular-nums">${(d.rainfall.total_24h_mm).toFixed(1)} mm</strong></span><span class="condition-source">${escapeHtml(prov.rainfall || "")}</span></div>`);
  }
  if (d.river_discharge) {
    const dir = d.river_discharge.direction;
    const arrow = dir === "rising" ? "&#9650;" : dir === "falling" ? "&#9660;" : "&#9654;";
    lines.push(`<div class="condition-line"><span>River discharge: <strong class="tabular-nums">${d.river_discharge.latest_m3s.toLocaleString()} m&sup3;/s</strong> ${arrow} ${dir}</span><span class="condition-source">${escapeHtml(prov.river_discharge || "")}</span></div>`);
  }
  if (d.soil_moisture) {
    lines.push(`<div class="condition-line"><span>Soil moisture: <strong class="tabular-nums">${d.soil_moisture.latest_m3m3.toFixed(2)} m&sup3;/m&sup3;</strong></span><span class="condition-source">${escapeHtml(prov.soil_moisture || "")}</span></div>`);
  }
  if (d.air_quality) {
    lines.push(`<div class="condition-line"><span>Air quality: <strong class="tabular-nums">${d.air_quality.aqi}</strong> ${escapeHtml(d.air_quality.category || "")}</span><span class="condition-source">${escapeHtml(prov.air_quality || "")}</span></div>`);
  }
  return `
    <div class="epicenter-conditions">
      <span class="drawer-label">Conditions at the epicenter</span>
      ${lines.join("")}
    </div>`;
}

function placeSeismicFocusOnMap(keepMapView = false) {
  const focus = appState.seismicFocus;
  if (!focus || !map || typeof google === "undefined") return;
  // The focus owns the map: basin risk zones come back when the focus closes.
  Object.values(riskZoneCircles).forEach(c => c.setMap(null));
  const ev = focus.event;
  if (typeof ev.latitude !== "number" || typeof ev.longitude !== "number") return;

  const pos = { lat: ev.latitude, lng: ev.longitude };
  const mag = Number(ev.magnitude) || 0;
  const sev = getMagnitudeSeverity(mag);
  const icon = {
    url: getMarkerIconUrl(sev.colorHex, "SEISMIC"),
    size: new google.maps.Size(36, 36),
    scaledSize: new google.maps.Size(52, 52),
    anchor: new google.maps.Point(26, 50)
  };
  const title = `Epicenter: M ${mag.toFixed(1)} ${ev.simulated === true ? "(SIMULATED)" : "(USGS)"}`;

  if (seismicFocusMarker) {
    seismicFocusMarker.setPosition(pos);
    seismicFocusMarker.setIcon(icon);
    seismicFocusMarker.setTitle(title);
    seismicFocusMarker.setMap(map);
  } else {
    seismicFocusMarker = new google.maps.Marker({
      position: pos, map: map, title: title, icon: icon, zIndex: 3000
    });
  }

  if (!seismicFocusCircle) {
    seismicFocusCircle = new google.maps.Circle({
      strokeOpacity: 0.55, strokeWeight: 1.5, fillOpacity: 0.1, clickable: false
    });
  }
  seismicFocusCircle.setOptions({ strokeColor: sev.colorHex, fillColor: sev.colorHex });
  seismicFocusCircle.setCenter(pos);
  // Rough felt-area cue scaled by magnitude — a visual aid, not a model output.
  seismicFocusCircle.setRadius(Math.max(1, mag) * 12000);
  seismicFocusCircle.setMap(map);

  // A region pick fits the whole region; the focus marker should not snap
  // the view to one epicenter in that flow.
  if (!keepMapView) {
    map.setCenter(pos);
    map.setZoom(7);
  }
}

function renderSeismicFocusRail() {
  const drawer = document.getElementById("muni-detail-drawer") || document.getElementById("muni-detail-rail");
  const focus = appState.seismicFocus;
  if (!drawer || !focus) return;

  const ev = focus.event;
  const mag = Number(ev.magnitude) || 0;
  const sevMag = getMagnitudeSeverity(mag);
  const sevRisk = focus.severity
    ? getSeverityConfigByLabel(focus.severity)
    : getSeverityConfig(typeof focus.risk_score === "number" ? focus.risk_score : 0);
  const simulated = ev.simulated === true;
  const sourceTag = simulated
    ? `<span class="badge badge-simulated">SIMULATED</span>`
    : `<span class="badge badge-live-usgs">LIVE &middot; USGS</span>`;
  const depthText = (typeof ev.depth_km === "number") ? `${ev.depth_km.toFixed(0)} km` : "unknown";
  const when = new Date(ev.time);
  const whenText = isNaN(when.getTime())
    ? "unknown time"
    : `${when.toLocaleString()} (${formatRelativeTime(ev.time)})`;
  const coordsText = (typeof ev.latitude === "number" && typeof ev.longitude === "number")
    ? `${ev.latitude.toFixed(3)}, ${ev.longitude.toFixed(3)}`
    : "unknown";
  const riskPct = (typeof focus.risk_score === "number") ? `${(focus.risk_score * 100).toFixed(0)}%` : "--";
  const noteText = simulated
    ? "Seismic-only focus on a clearly-labeled SIMULATED event. Flood and landslide telemetry is not modeled for this location."
    : "Seismic-only focus on a real event epicenter. Flood and landslide telemetry is not modeled for this location.";

  drawer.innerHTML = `
    <div class="drawer-grid seismic-focus-rail">
      <div class="seismic-focus-header">
        <span class="badge badge-seismic-focus">SEISMIC EVENT FOCUS</span>
        <button type="button" class="btn btn-sm seismic-focus-close" id="seismic-focus-close"
                aria-label="Exit seismic focus and return to the basin view">&times; Close</button>
      </div>
      <h3 class="drawer-muni-name seismic-focus-place">${escapeHtml(ev.place || "Unknown location")}</h3>
      <div class="seismic-focus-tags">${sourceTag}<span class="badge badge-seismic-focus" title="Flood and landslide telemetry is not modeled for this location.">SEISMIC-ONLY</span></div>
      <div class="seismic-focus-mag" style="color: ${sevMag.colorHex};">
        <span class="seismic-focus-mag-num tabular-nums">M ${mag.toFixed(1)}</span>
        <span class="seismic-focus-mag-label">magnitude</span>
      </div>
      <div class="drawer-metric">
        <span class="drawer-label">Depth</span>
        <span class="drawer-val tabular-nums">${depthText}</span>
      </div>
      <div class="drawer-metric">
        <span class="drawer-label">Time</span>
        <span class="drawer-val tabular-nums">${escapeHtml(whenText)}</span>
      </div>
      <div class="drawer-metric">
        <span class="drawer-label">Epicenter</span>
        <span class="drawer-val tabular-nums">${coordsText}</span>
      </div>
      <div class="drawer-divider"></div>
      ${focus.pending ? `
      <div class="drawer-metric">
        <span class="drawer-label">Derived Seismic Risk</span>
        <span class="skeleton-block" style="width: 110px; height: 18px;" aria-hidden="true"></span>
      </div>
      <div class="seismic-focus-narration" aria-busy="true">
        <span class="drawer-label">Narration &middot; generating&hellip;</span>
        <span class="skeleton-block" style="width: 100%; height: 12px; margin-top: 6px;" aria-hidden="true"></span>
        <span class="skeleton-block" style="width: 85%; height: 12px; margin-top: 6px;" aria-hidden="true"></span>
        <span class="skeleton-block" style="width: 60%; height: 12px; margin-top: 6px;" aria-hidden="true"></span>
      </div>` : focus.error ? `
      <div class="drawer-metric">
        <span class="drawer-label">Derived Seismic Risk</span>
        <span class="drawer-val">Assessment unavailable &mdash; feed data shown.</span>
      </div>` : `
      <div class="drawer-metric">
        <span class="drawer-label">Derived Seismic Risk</span>
        <span class="drawer-val tabular-nums" style="color: ${sevRisk.colorHex};">
          ${riskPct} <span class="badge ${sevRisk.badgeClass}">${escapeHtml(focus.severity || sevRisk.label)}</span>
        </span>
      </div>
      ${focus.narration ? `
      <div class="seismic-focus-narration">
        <span class="drawer-label">Narration</span>
        <p>${escapeHtml(focus.narration)}</p>
      </div>` : ""}`}
      ${conditionsBlockHtml(ev.id)}
      <p class="seismic-focus-note">${noteText}</p>
      <button type="button" class="btn btn-sm seismic-focus-return" id="seismic-focus-return">Close event focus &middot; back to the monitored basin</button>
    </div>
  `;

  const closeBtn = document.getElementById("seismic-focus-close");
  if (closeBtn) closeBtn.addEventListener("click", () => exitSeismicFocus());
  const returnBtn = document.getElementById("seismic-focus-return");
  if (returnBtn) returnBtn.addEventListener("click", () => exitSeismicFocus());
}

// Leave the transient focus view: drop the epicenter overlay and return the
// map and detail rail to the selected basin's normal state.
function exitSeismicFocus(refit = true) {
  if (!appState.seismicFocus) return;
  appState.seismicFocus = null;
  if (seismicFocusMarker) seismicFocusMarker.setMap(null);
  if (seismicFocusCircle) seismicFocusCircle.setMap(null);

  const drawer = document.getElementById("muni-detail-drawer") || document.getElementById("muni-detail-rail");
  if (drawer) {
    drawer.innerHTML = `<div class="drawer-instruction">Select a basin area to view detailed telemetry metrics.</div>`;
  }
  if (refit) {
    // Re-fit the map to the basin's markers on the next render.
    appState.boundsFitForBasin = null;
    renderMapMarkers();
  }
  renderScopeStrip();
  initConsoleLog("Exited seismic focus; returned to basin view.", "system");
}

// ==========================================================================
// Demo Controls (operator-only simulation tool, lives in Diagnostics)
// ==========================================================================
const DEMO_EVENT_MAGNITUDE = 6.4;

function setDemoStatus(message, isError) {
  const el = document.getElementById("demo-controls-status");
  if (!el) return;
  el.textContent = message;
  el.style.color = isError ? "var(--danger)" : "";
}

async function simulateDemoEvent() {
  if (appState.isOffline) return;
  const munis = getBasinMunis(appState.selectedBasin);
  const municipality = munis[0] || "";
  initConsoleLog(`OPERATOR: Injecting SIMULATED seismic event (M ${DEMO_EVENT_MAGNITUDE}, ${municipality}, ${appState.selectedBasin})...`, "action");
  try {
    const res = await fetch(`${API_BASE}/demo/inject-event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ basin: appState.selectedBasin, municipality, magnitude: DEMO_EVENT_MAGNITUDE })
    });
    if (!res.ok) throw new Error(`Status ${res.status}`);
    setDemoStatus(`SIMULATED event injected for ${municipality}. It will appear on the next poll, labeled SIMULATED.`, false);
    initConsoleLog("SIMULATED event registered. Refreshing telemetry...", "warn");
    await fetchTelemetry();
  } catch (err) {
    setDemoStatus(`Simulation failed: ${err.message}. Demo endpoint may not be deployed yet.`, true);
    initConsoleLog(`SIMULATED event injection failed: ${err.message}`, "error");
  }
}

async function clearDemoEvent() {
  if (appState.isOffline) return;
  initConsoleLog(`OPERATOR: Clearing SIMULATED events for ${appState.selectedBasin}...`, "action");
  try {
    const res = await fetch(`${API_BASE}/demo/clear-event`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ basin: appState.selectedBasin })
    });
    if (!res.ok) throw new Error(`Status ${res.status}`);
    setDemoStatus("Simulation cleared. Panel returns to live USGS data on the next poll.", false);
    initConsoleLog("SIMULATED events cleared. Refreshing telemetry...", "system");
    await fetchTelemetry();
  } catch (err) {
    setDemoStatus(`Clear failed: ${err.message}. Demo endpoint may not be deployed yet.`, true);
    initConsoleLog(`SIMULATED event clear failed: ${err.message}`, "error");
  }
}

// ==========================================================================
// Google Maps Marker Rendering
// ==========================================================================
// Translucent risk-colored circle per municipality (glance-level basin
// overview). Color is never the sole signal: the legend carries the numeric
// thresholds and each marker keeps its severity-labeled detail.
function syncRiskZones(basinRiskData) {
  if (!map || typeof google === "undefined") return;

  // Hidden entirely while a seismic focus owns the map, or when toggled off.
  if (!appState.choroplethOn || appState.seismicFocus) {
    Object.values(riskZoneCircles).forEach(c => c.setMap(null));
    return;
  }

  const present = new Set();
  basinRiskData.forEach(muni => {
    const coords = municipalityCoords[muni.municipality];
    if (!coords) return;
    present.add(muni.municipality);
    const sev = getSeverityConfig(muni.risk_score);
    const options = {
      center: { lat: coords.lat, lng: coords.lng },
      radius: 9000,
      strokeColor: sev.colorHex,
      strokeOpacity: 0.45,
      strokeWeight: 1,
      fillColor: sev.colorHex,
      fillOpacity: 0.13,
      clickable: false,
      map: map
    };
    if (riskZoneCircles[muni.municipality]) {
      riskZoneCircles[muni.municipality].setOptions(options);
    } else {
      riskZoneCircles[muni.municipality] = new google.maps.Circle(options);
    }
  });

  Object.keys(riskZoneCircles).forEach(name => {
    if (!present.has(name)) {
      riskZoneCircles[name].setMap(null);
      delete riskZoneCircles[name];
    }
  });
}

function renderMapMarkers() {
  if (!map || typeof google === "undefined") return;

  const allowedMunis = getBasinMunis(appState.selectedBasin);
  
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
        // Selecting a municipality ends any transient seismic focus, but keeps
        // the map where the user clicked (no bounds re-fit).
        if (appState.seismicFocus) exitSeismicFocus(false);
        appState.selectedMuni = muni;
        displayMuniDetails(muni);
        renderRiskTimeline();
        initConsoleLog(`Selected region: ${muni.municipality} (Risk Score: ${muni.risk_score.toFixed(2)})`, "action");
      });

      markers[muni.municipality] = marker;
    }

    bounds.extend(coords);
    hasValidCoords = true;
  });

  // Fit bounds only if we haven't fit bounds for this basin yet. While a
  // seismic focus is active the map stays on the epicenter — never re-fit.
  // Never fit while the map container is hidden (public mode): fitBounds on a
  // zero-size map collapses to a world view that survives the mode switch.
  const mapContainer = document.getElementById("risk-map-container");
  const mapVisible = !!(mapContainer && mapContainer.offsetWidth > 0 && mapContainer.offsetHeight > 0);
  if (hasValidCoords && mapVisible && appState.boundsFitForBasin !== appState.selectedBasin && !appState.seismicFocus) {
    map.fitBounds(bounds);
    appState.boundsFitForBasin = appState.selectedBasin;
  }

  // Choropleth-style risk zones follow the same render cycle as the markers.
  syncRiskZones(basinRiskData);

  // Keep details drawer updated if the selected muni is in the current basin.
  // A live seismic focus owns the rail until it is closed — the poll must not
  // overwrite it with municipality details.
  if (appState.selectedMuni && !appState.seismicFocus) {
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

  // Resolve the loading overlay: hide once markers are plotted; if a fetch for
  // this basin already completed with no rows, show an honest no-data state
  // instead of an indefinite spinner. While the fetch is still in flight the
  // loading state stays up.
  if (basinRiskData.length > 0) {
    setMapLoadingState("hide");
  } else if (appState.lastFetchedBasin === appState.selectedBasin) {
    setMapLoadingState("nodata");
  }
}

// Map overlay state machine: "loading" (spinner), "nodata", or "hide".
function setMapLoadingState(mode) {
  const loader = document.getElementById("map-loading-overlay");
  if (!loader) return;
  if (mode === "hide") {
    loader.classList.add("hidden");
    return;
  }
  loader.classList.remove("hidden");
  if (mode === "loading") {
    loader.innerHTML = `
      <div class="map-overlay-state" role="status">
        <div class="map-loading-spinner" aria-hidden="true"></div>
        <span>Loading basin data&hellip;</span>
      </div>`;
    loader.setAttribute("aria-label", "Loading basin data");
  } else if (mode === "nodata") {
    loader.innerHTML = `
      <div class="map-overlay-state" role="status">
        <span>No data for this area yet.</span>
      </div>`;
    loader.setAttribute("aria-label", "No data for this area yet");
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
  const scopedBasin = (appState.basins || []).find(b => b && b.id === appState.selectedBasin);
  const simulatedBadge = scopedBasin && scopedBasin.simulated
    ? `<span class="badge badge-simulated" title="River and soil values for this basin are modeled, not measured.">SIMULATED</span>`
    : "";

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
        ${simulatedBadge}${riskBadge}
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
        ${appState.simulatedActive ? '<span class="badge badge-simulated">SIMULATED EVENT ACTIVE</span>' : ''}
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
      // A seismic focus belongs to no basin; leave it before switching scope.
      // No re-fit here: the basin switch below resets the fit flag itself.
      if (appState.seismicFocus) exitSeismicFocus(false);
      appState.selectedBasin = e.target.value;
      initConsoleLog(`Switched catchment basin scope to: ${appState.selectedBasin}`, "action");

      // Recenter happens via the per-basin bounds-fit once the new basin's markers
      // render; reset the fit flag so it re-fits on this basin change (not every poll).
      appState.boundsFitForBasin = null;

      // Show the spinner overlay until the new basin's data renders.
      setMapLoadingState("loading");

      // Clear muni detail drawer/rail
      const drawer = document.getElementById("muni-detail-drawer") || document.getElementById("muni-detail-rail");
      if (drawer) {
        drawer.innerHTML = `<div class="drawer-instruction">Select a basin area to view detailed telemetry metrics.</div>`;
      }
      appState.selectedMuni = null;
      renderRiskTimeline();

      // Populate dropdown for Public mode
      populateMuniDropdown();

      // History panels follow the basin scope; a region filter belongs to
      // the global feed and is cleared for a clean slate.
      appState.regionFilter = null;
      seedRiskHistory(appState.selectedBasin);
      fetchTelemetryHistory(appState.selectedBasin);

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

  // Live seismic events feed: delegate clicks so rows re-rendered on every
  // poll stay clickable; rows are real buttons, so keyboard activation
  // (Enter/Space) comes for free.
  const seismicFeed = document.getElementById("seismic-feed-container");
  if (seismicFeed) {
    seismicFeed.addEventListener("click", (e) => {
      if (!e.target || typeof e.target.closest !== "function") return;
      const clearBtn = e.target.closest("[data-clear-region-filter]");
      if (clearBtn) { toggleRegionFilter(appState.regionFilter); return; }
      const row = e.target.closest(".seismic-event-btn");
      if (row && row.dataset && row.dataset.eventId) focusSeismicEvent(row.dataset.eventId);
    });
  }

  // Choropleth-style risk zones toggle on the map header.
  const choroToggle = document.getElementById("choropleth-toggle");
  if (choroToggle) {
    choroToggle.addEventListener("click", () => {
      appState.choroplethOn = !appState.choroplethOn;
      choroToggle.setAttribute("aria-pressed", String(appState.choroplethOn));
      choroToggle.textContent = `Risk zones: ${appState.choroplethOn ? "on" : "off"}`;
      renderMapMarkers();
    });
  }

  // Scope strip: delegate so items re-rendered each poll stay live.
  const scopeStrip = document.getElementById("scope-strip");
  if (scopeStrip) {
    scopeStrip.addEventListener("click", (e) => {
      if (!e.target || typeof e.target.closest !== "function") return;
      const basinCard = e.target.closest("[data-scope-basin]");
      if (basinCard) { selectBasinScope(); return; }
      const item = e.target.closest(".scope-item");
      if (item && item.dataset && item.dataset.region) toggleRegionFilter(item.dataset.region);
    });
  }

  // 30-day activity context row (collapsed by default in the feed panel).
  const regions30dToggle = document.getElementById("regions-30d-toggle");
  const regionsRow = document.getElementById("seismic-regions-container");
  if (regions30dToggle && regionsRow) {
    regions30dToggle.addEventListener("click", () => {
      regionsRow.hidden = !regionsRow.hidden;
      regions30dToggle.setAttribute("aria-pressed", String(!regionsRow.hidden));
    });
  }

  // Demo controls (operator-only simulation tool in Diagnostics)
  const simulateBtn = document.getElementById("simulate-event-btn");
  if (simulateBtn) simulateBtn.addEventListener("click", simulateDemoEvent);
  const clearSimBtn = document.getElementById("clear-simulation-btn");
  if (clearSimBtn) clearSimBtn.addEventListener("click", clearDemoEvent);

  // Initialize diagnostics slideout
  setupDiagnosticsSlideout();
  
  // Set up mode switch handlers
  const btnOps = document.getElementById("mode-btn-operations");
  const btnPub = document.getElementById("mode-btn-public");
  if (btnOps && btnPub) {
    btnOps.addEventListener("click", () => switchMode("operations"));
    btnPub.addEventListener("click", () => switchMode("public"));
  }
  
  // Public area cards: delegate so cards re-rendered each poll stay live.
  const publicAreaStrip = document.getElementById("public-area-strip");
  if (publicAreaStrip) {
    publicAreaStrip.addEventListener("click", (e) => {
      if (!e.target || typeof e.target.closest !== "function") return;
      const card = e.target.closest("[data-public-area]");
      if (card) selectPublicArea(card.dataset.publicArea);
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

function basinDisplayName(basinId) {
  if (!basinId) return null;
  const basin = (appState.basins || []).find(b => b && b.id === basinId);
  return basin ? basin.name : basinId;
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
        <span class="incident-log-title tabular-nums">[${timeStr}] <strong>${typeLabel}</strong>${(basinDisplayName(inc.basin) || inc.item_name) ? ` (${basinDisplayName(inc.basin) || inc.item_name})` : ""}</span>
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

// Keeps the public area selection valid for the scoped basin and renders the
// tappable area cards (the dropdown is gone everywhere by design).
function populateMuniDropdown() {
  const munis = getBasinMunis(appState.selectedBasin);

  if (!appState.selectedMuni || !munis.includes(appState.selectedMuni.municipality)) {
    const updated = database.risk.find(r => r.municipality === munis[0]);
    appState.selectedMuni = updated || { municipality: munis[0], risk_score: 0, dominant_hazard: "FLOOD" };
  } else {
    const updated = database.risk.find(r => r.municipality === appState.selectedMuni.municipality);
    if (updated) {
      appState.selectedMuni = updated;
    }
  }

  renderPublicAreaStrip(munis);
}

function renderPublicAreaStrip(munis) {
  const strip = document.getElementById("public-area-strip");
  if (!strip) return;
  strip.innerHTML = (munis || []).map(name => {
    const risk = database.risk.find(r => r.municipality === name);
    const sev = risk ? getSeverityConfig(risk.risk_score) : null;
    const active = appState.selectedMuni && appState.selectedMuni.municipality === name;
    return `
      <button type="button" class="scope-item public-area-item ${active ? "active" : ""}"
              data-public-area="${escapeHtml(name)}" aria-pressed="${active}"
              style="border-left-color: ${sev ? sev.colorHex : "var(--border-color)"};">
        <span class="scope-item-name">${escapeHtml(name)}</span>
        <span class="scope-item-meta">${sev ? `${escapeHtml(sev.label)} &middot; ${(risk.risk_score * 100).toFixed(0)}%` : "&mdash;"}</span>
      </button>`;
  }).join("");
}

// Public area selection (cards or map markers): the route, hero, alert card,
// and timeline all follow it.
function selectPublicArea(muniName) {
  const muniObj = database.risk.find(r => r.municipality === muniName);
  if (!muniObj) return;
  appState.selectedMuni = muniObj;
  renderRiskTimeline();
  renderPublicView();
}

function switchMode(newMode) {
  appState.mode = newMode;

  // Public mode has no basin selector and never shows a simulated basin:
  // residents always see the real (non-simulated) pipeline.
  if (newMode === "public") {
    const scoped = (appState.basins || []).find(b => b && b.id === appState.selectedBasin);
    if (scoped && scoped.simulated) {
      const real = (appState.basins || []).find(b => b && b.kind !== "seismic" && !b.simulated);
      const basinSelect = document.getElementById("basin-select");
      if (real && basinSelect) {
        initConsoleLog(`Public mode scopes to the live basin: ${real.name}.`, "telemetry");
        basinSelect.value = real.id;
        basinSelect.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }
  }

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
      // Any fit attempted while the map was hidden was suppressed (or, before
      // the guard, broken); restore the right view now that it has size.
      if (appState.seismicFocus) {
        placeSeismicFocusOnMap();
      } else {
        appState.boundsFitForBasin = null;
        renderMapMarkers();
      }
    }
  } else {
    initPublicMap();
    if (publicMap) google.maps.event.trigger(publicMap, 'resize');
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

// Plain-language wording for earthquake strength (kept simple and honest).
function magnitudeWord(mag) {
  if (mag >= 7) return "Great";
  if (mag >= 6) return "Major";
  if (mag >= 5) return "Strong";
  return "Moderate";
}

// Public seismic layer: the same real feed, read-only, in plain language.
function renderPublicSeismicList() {
  const listEl = document.getElementById("public-seismic-list");
  if (!listEl) return;
  const events = (database.seismicEvents.events || []).slice(0, 8);
  if (!events.length) {
    listEl.innerHTML = `<div class="empty-alerts">No magnitude 4.5+ earthquakes detected in the last 48 hours.</div>`;
    return;
  }
  listEl.innerHTML = events.map(ev => {
    const mag = Number(ev.magnitude) || 0;
    const sev = getMagnitudeSeverity(mag);
    const tag = ev.simulated === true ? " · SIMULATED (demo)" : "";
    const depth = (typeof ev.depth_km === "number") ? `, ${ev.depth_km.toFixed(0)} km deep` : "";
    return `
      <div class="plain-warning-card" style="border-left: 3px solid ${sev.colorHex};">
        <span class="plain-warning-title">${magnitudeWord(mag)} earthquake (M ${mag.toFixed(1)}) &middot; ${escapeHtml(ev.place || "Unknown location")}</span>
        <span class="plain-warning-body">${formatRelativeTime(ev.time)}${depth}${tag}</span>
      </div>`;
  }).join("");
}

// Show/hide the basin-specific public sections (irrelevant when the page is
// aligned to a remote seismic event).
function setPublicBasinSectionsVisible(visible) {
  ["safe-route-card", "public-advisories-card", "public-area-section"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.hidden = !visible;
  });
  const ctx = document.getElementById("public-alert-context");
  if (ctx) ctx.hidden = !visible;
  const mapTitle = document.getElementById("public-map-title");
  if (mapTitle) mapTitle.textContent = visible ? "This is your area" : "Event location";
}

// Cross-mode alignment: an event selected in Operations renders as a
// plain-language public event view (seismic-only, honestly labeled).
function renderPublicEventView(focus) {
  const ev = focus.event;
  const heroContainer = document.getElementById("public-status-hero");
  const guidanceList = document.getElementById("public-guidance-list");
  if (!heroContainer || !ev) return;

  setPublicBasinSectionsVisible(false);

  const mag = Number(ev.magnitude) || 0;
  const simulated = ev.simulated === true;
  const sevRisk = focus.severity
    ? getSeverityConfigByLabel(focus.severity)
    : getMagnitudeSeverity(mag);
  const statusWord = (focus.severity || sevRisk.label || "").toUpperCase() || "EVENT";
  const rel = formatRelativeTime(ev.time);
  const whenLocal = new Date(ev.time).toLocaleString();
  const source = simulated ? "Centinela demo (SIMULATED event)" : "U.S. Geological Survey (USGS)";

  const alertCard = document.getElementById("public-alert-card");
  if (alertCard) alertCard.style.borderLeft = `4px solid ${sevRisk.colorHex}`;
  const fieldsEl = document.getElementById("public-alert-fields");
  if (fieldsEl) {
    fieldsEl.innerHTML = `
      <div class="alert-field">
        <dt class="alert-field-label">Hazard</dt>
        <dd class="alert-field-value">Earthquake${simulated ? " (SIMULATED)" : ""}</dd>
      </div>
      <div class="alert-field">
        <dt class="alert-field-label">Where</dt>
        <dd class="alert-field-value">${escapeHtml(ev.place || "Unknown location")}</dd>
      </div>
      <div class="alert-field alert-field-wide">
        <dt class="alert-field-label">Action</dt>
        <dd class="alert-field-value">${HAZARD_ACTIONS.SEISMIC}</dd>
      </div>
      <div class="alert-field">
        <dt class="alert-field-label">When</dt>
        <dd class="alert-field-value">${escapeHtml(whenLocal)} (${rel})</dd>
      </div>
      <div class="alert-field">
        <dt class="alert-field-label">Source</dt>
        <dd class="alert-field-value">${source}</dd>
      </div>`;
  }
  const uphill = document.getElementById("public-alert-uphill");
  if (uphill) uphill.hidden = true;

  const depthText = (typeof ev.depth_km === "number") ? ` at a depth of ${ev.depth_km.toFixed(0)} km` : "";
  heroContainer.innerHTML = `
    <div class="public-hero-title">Selected event status</div>
    <div class="public-hero-status" style="color: ${sevRisk.colorHex}">${statusWord}</div>
    <p class="public-hero-desc">A ${magnitudeWord(mag).toLowerCase()} earthquake (magnitude ${mag.toFixed(1)}) occurred ${escapeHtml(ev.place || "at an unknown location")}, ${rel}${depthText}. This view is seismic-only: flood and landslide conditions are not modeled for this location.</p>
    ${conditionsBlockHtml(ev.id)}
    <div class="public-hero-timestamp">Last updated: ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</div>
  `;

  if (guidanceList) {
    guidanceList.innerHTML = [
      HAZARD_ACTIONS.SEISMIC,
      "Expect aftershocks. Each one is a reminder to stay clear of damaged structures.",
      "Check official sources for tsunami guidance if you are near the coast.",
      "Follow instructions from your local civil protection authorities."
    ].map(item => `
      <div class="guidance-item">
        <span class="guidance-item-bullet">&bull;</span>
        <span>${item}</span>
      </div>`).join("");
  }

  // Event location on the public map.
  initPublicMap();
  if (publicMap && typeof google !== "undefined" &&
      typeof ev.latitude === "number" && typeof ev.longitude === "number") {
    const pos = { lat: ev.latitude, lng: ev.longitude };
    if (!publicEventMarker) {
      publicEventMarker = new google.maps.Marker({ map: publicMap, zIndex: 2000 });
    }
    publicEventMarker.setPosition(pos);
    publicEventMarker.setIcon({
      url: getMarkerIconUrl(sevRisk.colorHex, "SEISMIC"),
      size: new google.maps.Size(36, 36),
      scaledSize: new google.maps.Size(48, 48),
      anchor: new google.maps.Point(24, 46)
    });
    publicEventMarker.setMap(publicMap);
    publicMap.setCenter(pos);
    publicMap.setZoom(6);
    appState.publicCenteredBasin = null; // re-center on return to basin view
  }
}

function renderPublicView() {
  const heroContainer = document.getElementById("public-status-hero");
  const guidanceList = document.getElementById("public-guidance-list");
  const warningsList = document.getElementById("public-warnings-list");

  if (!heroContainer) return;

  // The public seismic layer renders in both views.
  renderPublicSeismicList();

  // Cross-mode alignment: a seismic event selected in Operations owns the
  // public page too.
  if (appState.seismicFocus && appState.seismicFocus.event) {
    renderPublicEventView(appState.seismicFocus);
    return;
  }
  setPublicBasinSectionsVisible(true);
  if (publicEventMarker) publicEventMarker.setMap(null);

  const selectedMuni = appState.selectedMuni || (database.risk.length > 0 ? database.risk[0] : null);
  if (!selectedMuni) {
    heroContainer.innerHTML = `<div>No area data available.</div>`;
    return;
  }
  
  const severityConfig = getSeverityConfig(selectedMuni.risk_score);
  const statusWord = severityConfig.label.toUpperCase();

  // --- Structured 5-element alert card (Hazard, Where, Action, When, Source) ---
  const dominant = (selectedMuni.dominant_hazard || "FLOOD").toUpperCase();
  const hazardLabel = HAZARD_LABELS[dominant] || HAZARD_LABELS.FLOOD;
  const actionText = HAZARD_ACTIONS[dominant] || HAZARD_ACTIONS.FLOOD;
  const asOf = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  const alertCard = document.getElementById("public-alert-card");
  if (alertCard) {
    alertCard.style.borderLeft = `4px solid ${severityConfig.colorHex}`;
  }
  const fieldsEl = document.getElementById("public-alert-fields");
  if (fieldsEl) {
    fieldsEl.innerHTML = `
      <div class="alert-field">
        <dt class="alert-field-label">Hazard</dt>
        <dd class="alert-field-value">${hazardLabel}</dd>
      </div>
      <div class="alert-field">
        <dt class="alert-field-label">Where</dt>
        <dd class="alert-field-value">${selectedMuni.municipality}</dd>
      </div>
      <div class="alert-field alert-field-wide">
        <dt class="alert-field-label">Action</dt>
        <dd class="alert-field-value">${actionText}</dd>
      </div>
      <div class="alert-field">
        <dt class="alert-field-label">When</dt>
        <dd class="alert-field-value">as of ${asOf}</dd>
      </div>
      <div class="alert-field alert-field-wide">
        <dt class="alert-field-label">Source</dt>
        <dd class="alert-field-value">${ALERT_SOURCE}</dd>
      </div>
    `;
  }
  const contextEl = document.getElementById("public-alert-context");
  if (contextEl) {
    contextEl.textContent = BASIN_HISTORY[appState.selectedBasin] || "";
  }

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
    <div class="public-hero-title">Your area status</div>
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
      warningsHtml += `<div class="empty-alerts">No active warnings for this area.</div>`;
    }
    
    // Plain-language community advisory templated from the structured alert.
    // The technical (model-value-quoting) broadcast stays in Operations mode;
    // residents get severity + hazard + the protective action, nothing else.
    if (activeAlerts.length > 0 && alertData && alertData.agency_incident && alertData.agency_incident.affected_municipalities.length > 0) {
      const advisoryLines = activeAlerts.map(alert => {
        const sevConfig = getSeverityConfig(alert.risk_score);
        const hazardName = alert.dominant_hazard === 'FLOOD' ? 'flooding' : alert.dominant_hazard === 'LANDSLIDE' ? 'landslide' : 'earthquake';
        const action = HAZARD_ACTIONS[alert.dominant_hazard] || HAZARD_ACTIONS.FLOOD;
        return `<p class="advisory-line"><strong>${alert.municipality}:</strong> ${hazardName} risk is ${sevConfig.label}. ${action}</p>`;
      }).join("");
      warningsHtml += `
        <div class="broadcast-box" style="margin-top: 1rem;">
          <div class="broadcast-header">
            <span class="broadcast-tag">OFFICIAL EMERGENCY ADVISORY</span>
          </div>
          <div class="advisory-plain">
            ${advisoryLines}
            <p class="advisory-line advisory-source">Issued by ${ALERT_SOURCE}. Follow instructions from local authorities.</p>
          </div>
        </div>
      `;
    }
    
    warningsList.innerHTML = warningsHtml;
  }

  // "This is your area" map emphasis + client-side uphill directive.
  initPublicMap();
  renderPublicMap(selectedMuni);
  computeUphillDirection(selectedMuni);

  // A previously drawn route belongs to a different area now — clear it so a
  // stale route never lingers over the wrong municipality.
  if (appState.routeMuni && appState.routeMuni !== selectedMuni.municipality) {
    clearSafeRoute();
    appState.routeMuni = null;
    setRouteStatus("Tap the button to find the nearest hospital or safe point and a walking route.");
  }
}
