
// 🔔 Firebase Messaging Service Worker - handles push when PWA is CLOSED
importScripts('https://www.gstatic.com/firebasejs/12.19.0/firebase-app-compat.js');
importScripts('https://www.gstatic.com/firebasejs/12.19.0/firebase-messaging-compat.js');

firebase.initializeApp({
  apiKey: "AIzaSyCyutGoQfbfBOqJd5GstrfFuz1J2x1yIi4",
  authDomain: "bizhub-market.firebaseapp.com",
  projectId: "bizhub-market",
  storageBucket: "bizhub-market.firebasestorage.app",
  messagingSenderId: "815993881097",
  appId: "1:815993881097:web:92711c0ebbacea9362eed8"
});

const messaging = firebase.messaging();

// Background push - when app closed
messaging.onBackgroundMessage(function(payload) {
  console.log('[SW] Background message', payload);
  const title = payload.notification?.title || payload.data?.title || 'BizHub Alert!';
  const options = {
    body: payload.notification?.body || payload.data?.body || 'You have a new notification',
    icon: '/static/uploads/bizhub-app-icon.png',
    badge: '/static/uploads/bizhub-app-icon.png',
    vibrate: [300,100,300],
    data: payload.data,
    tag: 'bizhub-notif',
    requireInteraction: true
  };
  self.registration.showNotification(title, options);
});

// Click notification to open app
self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  event.waitUntil(
    clients.openWindow('/notifications')
  );
});
