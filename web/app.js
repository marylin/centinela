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
    if (basinSelect) {
      basinSelect.innerHTML = data
        .map(b => `<option value="${b.id}">${b.name} (${b.country})</option>`)
        .join("");
    }
    // Default to the first basin returned (keeps rio_cauca as today).
    appState.selectedBasin = data[0].id;
    if (basinSelect) basinSelect.value = appState.selectedBasin;
    initConsoleLog(`Loaded ${data.length} basins from configuration.`, "telemetry");
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

  appState.mode = "operations";

  // Populate the basin selector from backend config before loading telemetry.
  await loadBasins();

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
  if (youAreHereMarker && typeof youAreHereMarker.getPosition === "function") {
    const p = youAreHereMarker.getPosition();
    if (p) return { coords: { lat: p.lat(), lng: p.lng() }, label: "your location" };
  }
  const coords = municipalityCoords[selectedMuni.municipality];
  return coords ? { coords, label: selectedMuni.municipality } : null;
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

    // Draw the real route on the public map.
    directionsRenderer.setMap(publicMap);
    directionsRenderer.setDirections(result);

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
  // or failing /live-seismic endpoint must never trip the offline banner.
  fetchLiveSeismic();
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
      appState.selectedBasin = e.target.value;
      initConsoleLog(`Switched catchment basin scope to: ${appState.selectedBasin}`, "action");

      // Recenter happens via the per-basin bounds-fit once the new basin's markers
      // render; reset the fit flag so it re-fits on this basin change (not every poll).
      appState.boundsFitForBasin = null;

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
      renderRiskTimeline();

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
  
  // Set up muni selector dropdown change handler
  const muniSelect = document.getElementById("muni-select");
  if (muniSelect) {
    muniSelect.addEventListener("change", (e) => {
      const muniName = e.target.value;
      const muniObj = database.risk.find(r => r.municipality === muniName);
      if (muniObj) {
        appState.selectedMuni = muniObj;
        renderRiskTimeline();
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

  const munis = getBasinMunis(appState.selectedBasin);
  
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
