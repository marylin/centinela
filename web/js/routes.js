// Safe-route card. Same honest semantics as the retired public mode:
//   flood-watch places: destination must EARN "safety" (>= 10 m verified
//   elevation gain); otherwise fall back to the uphill directive only.
//   seismic-watch places: nearest open assembly area (park/plaza/stadium),
//   where nearest genuinely is the criterion.
//   event focus: route from the epicenter to the nearest open ground, only
//   when a walkable origin (< 5 km from a road network result) makes sense.
// Origin: device location when within 40 km of the place, else the anchor
// (labeled, never silently).

import { state, placeByName } from "./state.js";
import { escapeHtml, haversineMeters } from "./util.js";
import { renderMap } from "./map.js";

const COMPASS_8 = ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"];
const MIN_ELEVATION_GAIN_M = 10;

let busy = false;
let directionsRenderer = null;
let routeKey = null;
let deviceCoords = null;
let uphillCache = {};

function setStatus(msg) {
  const el = document.getElementById("route-status");
  if (el) el.textContent = msg;
}

function mapsReady() { return typeof google !== "undefined" && window.googleMapsReady; }

function getMapInstance() {
  // The map module owns the instance; reach it via the DOM-bound renderer.
  const el = document.getElementById("google-map");
  return el && el.__gm_map ? el.__gm_map : null;
}

async function elevationAt(points) {
  return new Promise((resolve) => {
    new google.maps.ElevationService().getElevationForLocations({ locations: points }, (res, status) => {
      resolve(status === "OK" && res ? res : null);
    });
  });
}

export async function computeUphill(name) {
  if (uphillCache[name]) return uphillCache[name];
  const p = placeByName(name);
  if (!p || !p.anchor || !mapsReady()) return null;
  const center = { lat: p.anchor.lat, lng: p.anchor.lng };
  const ring = COMPASS_8.map((_, i) => {
    const rad = (i * 45) * Math.PI / 180;
    return { lat: center.lat + 0.018 * Math.cos(rad), lng: center.lng + 0.018 * Math.sin(rad) };
  });
  const res = await elevationAt([center, ...ring]);
  if (!res || res.length < 9) return null;
  const base = res[0].elevation;
  let best = -1, bestGain = 0;
  res.slice(1).forEach((r, i) => {
    const gain = r.elevation - base;
    if (gain > bestGain) { bestGain = gain; best = i; }
  });
  if (best < 0 || bestGain < 3) return null;
  const out = { direction: COMPASS_8[best], gain: bestGain };
  uphillCache[name] = out;
  return out;
}

function requestDevicePosition() {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    if (deviceCoords) return resolve(deviceCoords);
    navigator.geolocation.getCurrentPosition(
      (pos) => { deviceCoords = { lat: pos.coords.latitude, lng: pos.coords.longitude }; resolve(deviceCoords); },
      () => resolve(null), { timeout: 6000 });
  });
}

function placesSearch(map, origin, types, keyword) {
  return new Promise((resolve) => {
    new google.maps.places.PlacesService(map).nearbySearch(
      { location: origin, rankBy: google.maps.places.RankBy.DISTANCE, type: types, keyword },
      (results, status) => resolve(status === "OK" && results ? results : []));
  });
}

async function pickFloodDestination(map, origin) {
  // Verified-uphill rule: among nearby refuge-typed places, the destination
  // must offer >= 10 m of REAL elevation gain over the origin.
  const candidates = [];
  for (const type of ["hospital", "school", "stadium"]) {
    const found = await placesSearch(map, origin, type);
    candidates.push(...found.slice(0, 6));
    if (candidates.length >= 12) break;
  }
  if (!candidates.length) return null;
  const points = [origin, ...candidates.map(c => ({ lat: c.geometry.location.lat(), lng: c.geometry.location.lng() }))];
  const elev = await elevationAt(points);
  if (!elev) return null;
  const base = elev[0].elevation;
  let best = null, bestGain = MIN_ELEVATION_GAIN_M;
  candidates.forEach((c, i) => {
    const gain = elev[i + 1].elevation - base;
    if (gain >= bestGain) { bestGain = gain; best = c; }
  });
  return best ? { place: best, note: `verified ${bestGain.toFixed(0)} m higher than the origin` } : null;
}

async function pickQuakeDestination(map, origin) {
  for (const type of ["park", "stadium"]) {
    const found = await placesSearch(map, origin, type);
    if (found.length) return { place: found[0], note: "nearest open assembly area" };
  }
  return null;
}

async function routeTo(map, origin, dest, originLabel, note) {
  return new Promise((resolve) => {
    new google.maps.DirectionsService().route({
      origin, destination: dest.place.geometry.location, travelMode: google.maps.TravelMode.WALKING,
    }, (result, status) => {
      if (status !== "OK" || !result) return resolve(false);
      if (!directionsRenderer) {
        directionsRenderer = new google.maps.DirectionsRenderer({ suppressMarkers: false, preserveViewport: true });
      }
      directionsRenderer.setMap(map);
      directionsRenderer.setDirections(result);
      const leg = result.routes[0].legs[0];
      const steps = document.getElementById("route-steps");
      if (steps) {
        steps.innerHTML = leg.steps.slice(0, 6).map(s =>
          `<li>${s.instructions} <span class="tabular-nums">(${s.distance.text})</span></li>`).join("");
      }
      setStatus(`Walking route from ${originLabel} to ${escapeHtml(dest.place.name)} (${leg.distance.text}, ${leg.duration.text}; ${note}).`);
      resolve(true);
    });
  });
}

export function clearRoute() {
  if (directionsRenderer) directionsRenderer.setMap(null);
  const steps = document.getElementById("route-steps");
  if (steps) steps.innerHTML = "";
  routeKey = null;
}

export async function findSafeRoute() {
  if (busy || !mapsReady()) return;
  const sel = state.selection;
  if (!sel || sel.kind !== "place") return;
  const p = placeByName(sel.name);
  if (!p || !p.anchor) return;
  busy = true;
  setStatus("Searching for a verified safe point…");
  try {
    const mapEl = document.getElementById("google-map");
    // PlacesService needs a map or node; the node form avoids reaching into
    // the map module's internals.
    const map = new google.maps.Map(document.createElement("div"));
    const focus = state.seismicFocus && state.seismicFocus.event;
    let origin, originLabel;
    if (focus && typeof focus.latitude === "number") {
      origin = { lat: focus.latitude, lng: focus.longitude };
      originLabel = "the epicenter area";
    } else {
      const device = await requestDevicePosition();
      const anchor = { lat: p.anchor.lat, lng: p.anchor.lng };
      if (device && haversineMeters(device, anchor) <= 40000) {
        origin = device; originLabel = "your location";
      } else {
        origin = anchor; originLabel = `${sel.name} center (demo origin)`;
      }
    }

    const quake = (focus && true) || ((state.groups.find(g => g.id === sel.groupId) || {}).kind === "seismic-watch");
    const dest = quake ? await pickQuakeDestination(map, origin) : await pickFloodDestination(map, origin);

    if (!dest) {
      const uphill = await computeUphill(sel.name);
      setStatus(quake
        ? "No mapped open assembly area found nearby. Move to the largest open space away from buildings."
        : uphill
          ? `No destination with verified ≥${MIN_ELEVATION_GAIN_M} m elevation gain nearby. Higher ground is to the ${uphill.direction} (+${uphill.gain.toFixed(0)} m within ~2 km).`
          : "No verified higher ground found nearby. Follow local civil-protection guidance.");
      clearRoute();
      busy = false;
      return;
    }

    // Route on the real visible map: the renderer binds to whatever map the
    // directions renderer was given; reuse the visible element via a map
    // bound to it (single shared instance pattern from the map module).
    const visibleMap = window.__centinelaMap || null;
    const ok = await routeTo(visibleMap || map, origin, dest, originLabel, dest.note);
    if (!ok) setStatus("Routing service unavailable right now.");
    routeKey = sel.name;
  } catch (err) {
    console.error("Route failed:", err);
    setStatus("Route search failed.");
  } finally {
    busy = false;
  }
}

export async function renderRouteCard() {
  const card = document.getElementById("route-card");
  if (!card) return;
  const sel = state.selection;
  const monitored = sel && sel.kind === "place";
  card.hidden = !monitored;
  if (!monitored) { clearRoute(); return; }
  if (routeKey && routeKey !== sel.name) clearRoute();
  const group = state.groups.find(g => g.id === sel.groupId) || {};
  const quake = group.kind === "seismic-watch";
  setStatus(quake
    ? "Tap the button to find the nearest open assembly area."
    : "Tap the button to find a walking route to verified higher ground.");
  if (!quake && mapsReady()) {
    const uphill = await computeUphill(sel.name);
    const el = document.getElementById("route-uphill");
    if (el) {
      el.hidden = !uphill;
      if (uphill) el.textContent = `Higher ground is to the ${uphill.direction} (+${uphill.gain.toFixed(0)} m within ~2 km).`;
    }
  } else {
    const el = document.getElementById("route-uphill");
    if (el) el.hidden = true;
  }
}

export function setupRouteCard() {
  const btn = document.getElementById("route-find-btn");
  if (btn) btn.addEventListener("click", findSafeRoute);
}
