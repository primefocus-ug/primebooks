// Auto-activate new SW versions immediately
self.addEventListener('install', function(event) {
    self.skipWaiting();
});

self.addEventListener('activate', function(event) {
    event.waitUntil(clients.claim());
});

// ── Sound map ──────────────────────────────────
const SOUNDS = {
    sale_created:    '/static/sounds/sale.mp3',
    low_stock:       '/static/sounds/alert.mp3',
    payment_failed:  '/static/sounds/error.mp3',
    expense_created: '/static/sounds/notify.mp3',
    invoice_fiscalized: '/static/sounds/notify.mp3',
    default:         '/static/sounds/notify.mp3',
};

self.addEventListener('push', function(event) {
    let data;
    try {
        data = event.data.json();
    } catch (e) {
        data = {
            title: 'PrimeBooks',
            body: event.data ? event.data.text() : 'New notification',
            url: '/',
            notification_type: 'default'
        };
    }

    event.waitUntil(
        Promise.all([
            self.registration.showNotification(data.title, {
                body:     data.body,
                icon:     '/static/favicon/web-app-manifest-192x192.png',
                badge:    '/static/favicon/favicon-96x96.png',
                vibrate:  [200, 100, 200],
                tag:      data.notification_type || 'general',
                renotify: true,
                data:     { url: data.url, sound: data.notification_type }
            }),
            self.clients.matchAll({ type: 'window', includeUncontrolled: true })
                .then(function(clients) {
                    if (clients.length > 0) {
                        clients[0].postMessage({
                            type:  'PLAY_NOTIFICATION_SOUND',
                            sound: data.notification_type || 'default'
                        });
                    }
                })
        ])
    );
});

self.addEventListener('notificationclick', function(event) {
    event.notification.close();
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(function(clientList) {
                const url = event.notification.data.url;
                for (const client of clientList) {
                    if (client.url === url && 'focus' in client) return client.focus();
                }
                if (clients.openWindow) return clients.openWindow(url);
            })
    );
});