// FCM notifications: token flow, copy button, foreground messages.
// Exported as a setup function (no import-time side effects) so the
// regression suite can import this module in Node with mocks on globalThis
// and assert the listener registration.

import { registerToken, subscribePlace as apiSubscribePlace, unsubscribePlace as apiUnsubscribePlace } from "./api.js";

const firebaseConfig = {
  apiKey: "AIzaSyCD5dZslaW5oKA2chzr5BNyJzHODf4LW04",
  authDomain: "centinela-498622.firebaseapp.com",
  projectId: "centinela-498622",
  storageBucket: "centinela-498622.firebasestorage.app",
  messagingSenderId: "765013283380",
  appId: "1:765013283380:web:8a93b5e191e9d6a4ed0b5e"
};

const VAPID_KEY = "BPbtW64PIDcBIzGTXBkV29ze7DT5pMaLqyqljNJ3R0YphvJBrSDLpDDdCsRSjWB0BBhCRC1yPYbDTACE3uww79A";

// --- Per-place topic subscriptions -----------------------------------------

const SUBS_KEY = "centinela-place-subs";

export function getPlaceSubscriptions() {
  try { return JSON.parse(localStorage.getItem(SUBS_KEY) || "{}"); }
  catch { return {}; }
}

function saveSubs(subs) {
  try { localStorage.setItem(SUBS_KEY, JSON.stringify(subs)); } catch {}
}

async function ensureToken() {
  if (typeof firebase === "undefined" || !firebase.messaging) {
    throw new Error("Push is not supported in this browser.");
  }
  if (!firebase.apps || !firebase.apps.length) firebase.initializeApp(firebaseConfig);
  const messaging = firebase.messaging();
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notification permission was not granted.");
  const swReg = await navigator.serviceWorker.register("/firebase-messaging-sw.js");
  const token = await messaging.getToken({ vapidKey: VAPID_KEY, serviceWorkerRegistration: swReg });
  if (!token) throw new Error("Could not obtain a push token.");
  return token;
}

export async function subscribeToPlace(basin) {
  const token = await ensureToken();
  await apiSubscribePlace(token, basin);
  const subs = getPlaceSubscriptions();
  subs[basin] = true;
  saveSubs(subs);
}

export async function unsubscribeFromPlace(basin) {
  const subs = getPlaceSubscriptions();
  try {
    const token = await ensureToken();
    await apiUnsubscribePlace(token, basin);
  } finally {
    delete subs[basin];
    saveSubs(subs);
  }
}

export function setupNotifications() {
  const enableBtn = document.getElementById("enable-notifications-btn");
  if (!enableBtn) return;

  enableBtn.addEventListener("click", async () => {
    try {
      if (typeof firebase === "undefined" || !firebase.messaging) {
        console.warn("Firebase messaging unavailable.");
        return;
      }
      if (!firebase.apps || !firebase.apps.length) firebase.initializeApp(firebaseConfig);
      const messaging = firebase.messaging();

      const permission = await Notification.requestPermission();
      if (permission !== "granted") return;

      const swReg = await navigator.serviceWorker.register("/firebase-messaging-sw.js");
      const token = await messaging.getToken({ vapidKey: VAPID_KEY, serviceWorkerRegistration: swReg });
      if (!token) return;

      await registerToken(token);

      const box = document.getElementById("token-display-box");
      const tokenEl = document.getElementById("notification-token");
      if (box) box.classList.remove("hidden");
      if (tokenEl) tokenEl.textContent = token;
      enableBtn.textContent = "Notifications enabled";
      enableBtn.disabled = true;

      messaging.onMessage((payload) => {
        const title = (payload.notification && payload.notification.title) || "Centinela alert";
        const body = (payload.notification && payload.notification.body) || "";
        try { new Notification(title, { body }); } catch (e) { console.log("FG message:", title, body); }
      });
    } catch (err) {
      console.error("Notification setup failed:", err);
    }
  });

  const copyBtn = document.getElementById("copy-token-btn");
  if (copyBtn) {
    copyBtn.addEventListener("click", () => {
      const tokenEl = document.getElementById("notification-token");
      if (tokenEl && navigator.clipboard) navigator.clipboard.writeText(tokenEl.textContent || "");
    });
  }
}
