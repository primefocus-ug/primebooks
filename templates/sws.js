{% load static %}
// ─────────────────────────────────────────────────────────────────────────────
// PrimeBooks Service Worker — Firebase Cloud Messaging
// Served as a Django template so config is injected server-side.
// ─────────────────────────────────────────────────────────────────────────────

// ─── INSTALL ──────────────────────────────────────────────────────────────────
self.addEventListener('install', function (event) {
    console.log('[SW] Installing...');
    self.skipWaiting();
});

// ─── ACTIVATE: claim all tabs, clear old caches ───────────────────────────────
self.addEventListener('activate', function (event) {
    console.log('[SW] Activating...');
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(keys.map(function (k) { return caches.delete(k); }));
        }).then(function () {
            return clients.claim();
        })
    );
});

// ─── FIREBASE SDK ─────────────────────────────────────────────────────────────
try {
    importScripts('https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js');
    importScripts('https://www.gstatic.com/firebasejs/10.12.2/firebase-messaging-compat.js');
    console.log('[SW] Firebase SDK loaded OK');
} catch (e) {
    console.error('[SW] FAILED to load Firebase SDK:', e);
}

// ─── FIREBASE CONFIG — values come from Django settings, no placeholders ──────
const FIREBASE_CONFIG = {
    apiKey:            "{{ FIREBASE_API_KEY }}",
    authDomain:        "{{ FIREBASE_PROJECT_ID }}.firebaseapp.com",
    projectId:         "{{ FIREBASE_PROJECT_ID }}",
    storageBucket:     "{{ FIREBASE_PROJECT_ID }}.appspot.com",
    messagingSenderId: "{{ FIREBASE_SENDER_ID }}",
    appId:             "{{ FIREBASE_APP_ID }}",
};

// ─── INIT ─────────────────────────────────────────────────────────────────────
let messaging = null;
try {
    if (!firebase.apps.length) {
        firebase.initializeApp(FIREBASE_CONFIG);
    }
    messaging = firebase.messaging();
    console.log('[SW] Firebase messaging ready, project:', FIREBASE_CONFIG.projectId);
} catch (e) {
    console.error('[SW] Firebase init error:', e, 'Config:', JSON.stringify(FIREBASE_CONFIG));
}

// ─── SOUND MAP ────────────────────────────────────────────────────────────────
const SOUNDS = {
    sale_created:       '/static/sounds/sale.mp3',
    low_stock:          '/static/sounds/alert.mp3',
    payment_failed:     '/static/sounds/error.mp3',
    expense_created:    '/static/sounds/notify.mp3',
    invoice_fiscalized: '/static/sounds/notify.mp3',
    default:            '/static/sounds/notify.mp3',
};

// ─── BACKGROUND MESSAGE HANDLER ───────────────────────────────────────────────
if (messaging) {
    messaging.onBackgroundMessage(function (payload) {
        console.log('[SW] Background push:', payload);

        const data  = payload.data         || {};
        const notif = payload.notification || {};

        const title             = notif.title || data.title || 'PrimeBooks';
        const body              = notif.body  || data.body  || '';
        const url               = data.url    || '/';
        const notification_type = data.notification_type || 'default';
        const icon              = notif.icon || data.icon
                                  || '/static/favicon/web-app-manifest-192x192.png';

        const showPromise = self.registration.showNotification(title, {
            body:     body,
            icon:     icon,
            badge:    '/static/favicon/favicon-96x96.png',
            vibrate:  [200, 100, 200],
            tag:      notification_type,
            renotify: true,
            data:     { url: url, sound: notification_type },
        });

        const soundPromise = self.clients
            .matchAll({ type: 'window', includeUncontrolled: true })
            .then(function (wList) {
                if (wList.length > 0) {
                    wList[0].postMessage({ type: 'PLAY_NOTIFICATION_SOUND', sound: notification_type });
                }
            })
            .catch(function () {});

        return Promise.all([showPromise, soundPromise]);
    });
}

// ─── NOTIFICATION CLICK ───────────────────────────────────────────────────────
self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    var targetUrl = (event.notification.data && event.notification.data.url)
        ? event.notification.data.url : '/';

    event.waitUntil(
        self.clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(function (list) {
                for (var i = 0; i < list.length; i++) {
                    if (list[i].url === targetUrl && 'focus' in list[i]) {
                        return list[i].focus();
                    }
                }
                if (self.clients.openWindow) return self.clients.openWindow(targetUrl);
            })
    );
});

// ─── PING keep-alive ──────────────────────────────────────────────────────────
self.addEventListener('message', function (event) {
    if (event.data && event.data.type === 'PING' && event.ports && event.ports[0]) {
        event.ports[0].postMessage({ type: 'PONG' });
    }
});