// Import the Firebase scripts inside the service worker
importScripts('https://www.gstatic.com/firebasejs/10.8.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/10.8.0/firebase-messaging-compat.js');

// Initialize Firebase app in the service worker
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
    body: payload.notification.body
  };

  self.registration.showNotification(notificationTitle, notificationOptions);
});
