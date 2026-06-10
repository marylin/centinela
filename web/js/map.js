// The single map: city anchor pins, risk zones, river-cell hazard markers,
// seismic focus, candidate pins, you-are-here. One instance for the whole
// app (the old ops/public split is gone).

import { state } from "./state.js";
import { getSeverityConfig, getMagnitudeSeverity, getMarkerIconUrl } from "./severity.js";
import { darkMapStyles } from "./map-styles.js";

let map = null;
let placeMarkers = {};
let zoneCircles = {};
let hazardMarkers = {};
let focusMarker = null;
let focusCircle = null;
let candidateMarker = null;
let youAreHereMarker = null;
let geoRequested = false;
let centeredKey = null; // selection key the map last centered on
let lastCenter = null;
let lastZoom = null;

function mapsReady() { return typeof google !== "undefined" && window.googleMapsReady; }

// Call whenever the detail view becomes visible: a map created (or last
// painted) inside a hidden container has zero size and renders glitched
// until it gets an explicit resize + recenter.
export function onDetailShown() {
  if (!mapsReady()) return;
  initMap();
  if (!map) return;
  google.maps.event.trigger(map, "resize");
  if (lastCenter) {
    map.setCenter(lastCenter);
    if (lastZoom) map.setZoom(lastZoom);
  }
}

export function initMap() {
  if (map || !mapsReady()) return;
  const el = document.getElementById("google-map");
  if (!el) return;
  map = new google.maps.Map(el, {
    center: { lat: 4.5, lng: -74.0 },
    zoom: 5,
    styles: darkMapStyles,
    disableDefaultUI: true,
    zoomControl: true,
  });
  window.__centinelaMap = map; // route renderer draws on the shared instance
}

function clearStore(store) {
  Object.values(store).forEach(m => m.setMap(null));
  return {};
}

// Recenter only when the selection (or focus) actually changes; user zoom and
// pan always win across polls (the hard-won zoom lesson).
function centerOnce(key, pos, zoom) {
  lastCenter = pos;
  lastZoom = zoom;
  if (centeredKey === key) return;
  map.setCenter(pos);
  map.setZoom(zoom);
  centeredKey = key;
}

function shouldShowHazard(w) {
  if (!w.hydro || !w.row) return false;
  if ((Number(w.row.flood_score) || 0) < 0.4) return false;
  return Math.abs(w.hydro.lat - w.pos.lat) >= 0.02 || Math.abs(w.hydro.lng - w.pos.lng) >= 0.02;
}

export function renderMap() {
  if (!mapsReady()) return;
  initMap();
  if (!map) return;

  const sel = state.selection;
  if (!sel) return;

  // --- seismic focus owns the map when active -------------------------------
  const focusEv = state.seismicFocus && state.seismicFocus.event;
  if (focusEv && typeof focusEv.latitude === "number") {
    const pos = { lat: focusEv.latitude, lng: focusEv.longitude };
    const mag = Number(focusEv.magnitude) || 0;
    const sev = getMagnitudeSeverity(mag);
    if (!focusMarker) focusMarker = new google.maps.Marker({ zIndex: 2000 });
    focusMarker.setOptions({
      position: pos, map,
      title: `M ${mag.toFixed(1)} (${focusEv.place || "event"})`,
      icon: {
        url: getMarkerIconUrl(sev.colorHex, "SEISMIC"),
        size: new google.maps.Size(36, 36),
        scaledSize: new google.maps.Size(48, 48),
        anchor: new google.maps.Point(24, 46),
      },
    });
    if (!focusCircle) {
      focusCircle = new google.maps.Circle({ strokeOpacity: 0.6, strokeWeight: 1, fillOpacity: 0.12, clickable: false });
    }
    focusCircle.setOptions({ strokeColor: sev.colorHex, fillColor: sev.colorHex, center: pos, radius: Math.max(1, mag) * 12000, map });
    centerOnce(`event:${focusEv.id}`, pos, 6);
    return;
  }
  if (focusMarker) focusMarker.setMap(null);
  if (focusCircle) focusCircle.setMap(null);

  // --- candidate selection: a single anchor pin ------------------------------
  if (sel.kind === "candidate") {
    placeMarkers = clearStore(placeMarkers);
    zoneCircles = clearStore(zoneCircles);
    hazardMarkers = clearStore(hazardMarkers);
    const c = (((state.watchlist || {}).results) || []).find(r => r.name === sel.name);
    if (!c || typeof c.lat !== "number") return;
    const pos = { lat: c.lat, lng: c.lng };
    const sev = getSeverityConfig(Number(c.activity_score) || 0);
    if (!candidateMarker) candidateMarker = new google.maps.Marker({ zIndex: 900 });
    candidateMarker.setOptions({
      position: pos, map,
      title: `${sel.name} (watchlist candidate, not monitored)`,
      icon: {
        url: getMarkerIconUrl(sev.colorHex, "FLOOD"),
        size: new google.maps.Size(36, 36),
        scaledSize: new google.maps.Size(40, 40),
        anchor: new google.maps.Point(20, 38),
      },
    });
    centerOnce(`candidate:${sel.name}`, pos, 9);
    return;
  }
  if (candidateMarker) { candidateMarker.setMap(null); candidateMarker = null; }

  // --- monitored place: the whole group renders, selection emphasized -------
  const group = (state.groups || []).find(g => g.id === sel.groupId);
  if (!group) return;
  const rows = state.riskByGroup[group.id] || [];
  const wanted = {};
  (group.places || []).forEach(p => {
    if (!p.anchor) return;
    const row = rows.find(r => r.municipality === p.name);
    const score = row ? Number(row.risk_score) || 0 : 0;
    wanted[p.name] = {
      pos: { lat: p.anchor.lat, lng: p.anchor.lng },
      sev: getSeverityConfig(score),
      dominant: (row && row.dominant_hazard) || "FLOOD",
      row, score,
      hydro: p.hydro_point,
    };
  });

  Object.keys(placeMarkers).forEach(name => {
    if (!wanted[name]) { placeMarkers[name].setMap(null); delete placeMarkers[name]; }
  });
  Object.keys(zoneCircles).forEach(name => {
    if (!wanted[name] || wanted[name].score < 0.4) {
      zoneCircles[name].setMap(null); delete zoneCircles[name];
    }
  });
  Object.keys(hazardMarkers).forEach(name => {
    if (!wanted[name] || !shouldShowHazard(wanted[name])) {
      hazardMarkers[name].setMap(null); delete hazardMarkers[name];
    }
  });

  Object.entries(wanted).forEach(([name, w]) => {
    const selected = name === sel.name;
    const icon = {
      url: getMarkerIconUrl(w.sev.colorHex, w.dominant),
      size: new google.maps.Size(36, 36),
      scaledSize: selected ? new google.maps.Size(48, 48) : new google.maps.Size(36, 36),
      anchor: selected ? new google.maps.Point(24, 46) : new google.maps.Point(18, 34),
    };
    if (placeMarkers[name]) {
      placeMarkers[name].setOptions({ position: w.pos, icon, title: name, map, zIndex: selected ? 1000 : 500 });
    } else {
      placeMarkers[name] = new google.maps.Marker({ position: w.pos, icon, title: name, map, zIndex: selected ? 1000 : 500 });
    }

    if (w.score >= 0.4) {
      if (!zoneCircles[name]) {
        zoneCircles[name] = new google.maps.Circle({ strokeOpacity: 0.5, strokeWeight: 1, fillOpacity: 0.1, clickable: false });
      }
      zoneCircles[name].setOptions({ strokeColor: w.sev.colorHex, fillColor: w.sev.colorHex, center: w.pos, radius: 4000, map });
    }

    if (shouldShowHazard(w)) {
      const hp = w.hydro;
      const hsev = getSeverityConfig(Number(w.row.flood_score) || 0);
      const title = `River monitoring point: ${name} (${(hp.cell_p50_m3s || 0).toLocaleString()} m³/s median)`;
      const hicon = {
        url: getMarkerIconUrl(hsev.colorHex, "FLOOD"),
        size: new google.maps.Size(36, 36),
        scaledSize: new google.maps.Size(30, 30),
        anchor: new google.maps.Point(15, 29),
      };
      if (hazardMarkers[name]) {
        hazardMarkers[name].setOptions({ position: { lat: hp.lat, lng: hp.lng }, icon: hicon, title, map });
      } else {
        hazardMarkers[name] = new google.maps.Marker({ position: { lat: hp.lat, lng: hp.lng }, icon: hicon, title, map, zIndex: 800 });
      }
    }
  });

  const selWanted = wanted[sel.name];
  if (selWanted) {
    centerOnce(`place:${sel.name}`, selWanted.pos, (group.places || []).length > 1 ? 10 : 11);
  }
  requestGeolocationOnce();
}

function requestGeolocationOnce() {
  if (geoRequested || !navigator.geolocation) return;
  geoRequested = true;
  navigator.geolocation.getCurrentPosition((pos) => {
    if (!map) return;
    const here = { lat: pos.coords.latitude, lng: pos.coords.longitude };
    if (!youAreHereMarker) {
      youAreHereMarker = new google.maps.Marker({
        map, title: "You are here", zIndex: 2000,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 7, fillColor: "#38bdf8", fillOpacity: 1, strokeColor: "#07090f", strokeWeight: 2 },
      });
    }
    youAreHereMarker.setPosition(here);
  }, () => {}, { timeout: 8000 });
}
