// Import the Firebase scripts inside the service worker
importScripts('https://www.gstatic.com/firebasejs/10.8.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.8.0/firebase-messaging-compat.js');

// Initialize Firebase app in the service worker. Public Firebase web config:
// these identifiers are meant to ship in the client and are not secrets. The
// API key is HTTP-referrer restricted to the deployment domain in the Google
// Cloud console.
firebase.initializeApp({
  apiKey: "AIzaSyCD5dZslaW5oKA2chzr5BNyJzHODf4LW04",
  authDomain: "centinela-498622.firebaseapp.com",
  projectId: "centinela-498622",
  storageBucket: "centinela-498622.firebasestorage.app",
  messagingSenderId: "765013283380",
  appId: "1:765013283380:web:9fd5a47da7c575de43f061",
  measurementId: "G-4JWEX55YPH"
});

const messaging = firebase.messaging();

// Handle background messages
messaging.onBackgroundMessage((payload) => {
  console.log('[firebase-messaging-sw.js] Received background message ', payload);
  const notificationTitle = payload.notification.title;
  const notificationOptions = {
    body: payload.notification.body,
    icon: "/assets/icons/icon-192.png",
    data: payload.data || {}
  };

  self.registration.showNotification(notificationTitle, notificationOptions);
});


// --- PWA app-shell caching -------------------------------------------------
// Network-first so deploys stay fresh online, with a cached shell for offline.
// One worker owns the whole scope, so push (above) and offline (below) coexist.
const CACHE = "centinela-shell-v4";
const SHELL = [
  "/", "/style.css", "/manifest.json",
  "/assets/icons/icon-192.png", "/assets/icons/icon-512.png",
  "/assets/js/main.js", "/assets/js/state.js", "/assets/js/api.js", "/assets/js/tiles.js",
  "/assets/js/poll.js", "/assets/js/notify.js", "/assets/js/diagnostics.js", "/assets/js/rail.js",
  "/assets/js/detail.js", "/assets/js/map.js", "/assets/js/seismic.js", "/assets/js/alert-card.js",
  "/assets/js/charts.js", "/assets/js/conditions.js", "/assets/js/severity.js",
  "/assets/js/map-styles.js", "/assets/js/util.js", "/assets/js/pages.js",
];

self.addEventListener("install", (event) => {
  self.skipWaiting();
  // Individual adds so one missing asset can't abort the whole precache.
  event.waitUntil(caches.open(CACHE).then(c => Promise.allSettled(SHELL.map(u => c.add(u)))));
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(k => k !== CACHE && k.startsWith("centinela-")).map(k => caches.delete(k)));
    await self.clients.claim();
  })());
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // leave Maps / Firebase / fonts alone

  const isNav = req.mode === "navigate";
  const isAsset = url.pathname === "/style.css" || url.pathname === "/manifest.json"
    || url.pathname.startsWith("/assets/");
  if (!isNav && !isAsset) return; // API/dynamic: default network, app shows its offline banner

  event.respondWith((async () => {
    try {
      const fresh = await fetch(req);
      if (fresh && fresh.ok) {
        const cache = await caches.open(CACHE);
        // Only the root navigation seeds the shell key; other routes (e.g.
        // /technology) must not overwrite it. Static assets cache by URL.
        if (isNav) { if (url.pathname === "/") cache.put("/", fresh.clone()); }
        else cache.put(req, fresh.clone());
      }
      return fresh;
    } catch (err) {
      const cache = await caches.open(CACHE);
      const cached = await cache.match(isNav ? "/" : req);
      return cached || Response.error();
    }
  })());
});

// Tapping the notification opens the place page it points at.
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const route = (event.notification.data && event.notification.data.route) || "";
  const url = self.location.origin + "/" + route;
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    for (const w of wins) {
      if (w.url.startsWith(self.location.origin) && "focus" in w) {
        w.navigate(url);
        return w.focus();
      }
    }
    return clients.openWindow(url);
  }));
});
