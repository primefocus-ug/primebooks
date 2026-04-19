// ─── firebase-init.js ────────────────────────────────────────────────────────
// Include this script on every page (after your Firebase SDK scripts).
// It requests permission, gets the FCM token, and POSTs it to your Django view.
//
// Add these script tags to your base template BEFORE this file:
//
//   <script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js"></script>
//   <script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-messaging-compat.js"></script>
//
// Then after them:
//   <script src="{% static 'js/firebase-init.js' %}"></script>
//
// The VAPID key below is the "Web Push certificate" public key from:
//   Firebase Console → Project Settings → Cloud Messaging → Web Push certificates

(function () {
    // ── 1. Firebase config — replace with yours ───────────────────────────────
    const firebaseConfig = {
      apiKey: "AIzaSyDw9m46zLPfxwbiRMqzB9ftLvdLg-aNZ1w",
      authDomain: "fcm-pro-3dd2f.firebaseapp.com",
      projectId: "fcm-pro-3dd2f",
      storageBucket: "fcm-pro-3dd2f.firebasestorage.app",
      messagingSenderId: "562803335953",
      appId: "1:562803335953:web:c476b06a0135440294e2b0"
    };

    // ── 2. Your Firebase Web Push VAPID public key ────────────────────────────
    // Firebase Console → Project Settings → Cloud Messaging → Web Push certificates
    const FIREBASE_VAPID_KEY = "BM16rS8BveaV-jlP_9InWPQaD0YwCN_R4Wrm6eybNRvSQymerDDa7iHwR2bwpAfDeNtLXbXJbPfU7yvoueZjWcc";

    // ── 3. Your Django endpoint that saves the token ──────────────────────────
    const SUBSCRIBE_URL = "/push/subscribe/";

    // ── 4. Initialise ─────────────────────────────────────────────────────────
    if (!firebase.apps.length) {
        firebase.initializeApp(firebaseConfig);
    }
    const messaging = firebase.messaging();

    // ── 5. Register our custom service worker ────────────────────────────────
    //    The SW file must be at the root of your site (or set its scope accordingly)
    async function registerAndSubscribe() {
        if (!('serviceWorker' in navigator) || !('Notification' in window)) {
            console.warn('[FCM] Push notifications not supported in this browser.');
            return;
        }

        try {
            const registration = await navigator.serviceWorker.register(
                '/static/js/sws.js',   // adjust path to where you serve the SW
                { scope: '/' }
            );

            // Request notification permission
            const permission = await Notification.requestPermission();
            if (permission !== 'granted') {
                console.log('[FCM] Notification permission denied.');
                return;
            }

            // Get the FCM registration token
            const token = await messaging.getToken({
                vapidKey:            FIREBASE_VAPID_KEY,
                serviceWorkerRegistration: registration,
            });

            if (!token) {
                console.warn('[FCM] No registration token available.');
                return;
            }

            console.log('[FCM] Token:', token);

            // POST the token to Django
            const csrfToken = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
            await fetch(SUBSCRIBE_URL, {
                method:  'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken':  csrfToken,
                },
                body: JSON.stringify({ fcm_token: token }),
            });

            console.log('[FCM] Subscription saved to server.');

        } catch (err) {
            console.error('[FCM] Error registering for push:', err);
        }
    }

    // ── 6. Handle foreground messages (app is open) ───────────────────────────
    messaging.onMessage(function (payload) {
        console.log('[FCM] Foreground message:', payload);
        const data             = payload.data || {};
        const notification_type = data.notification_type || 'default';

        // Play sound via existing mechanism
        const soundMap = {
            sale_created:       '/static/sounds/sale.mp3',
            low_stock:          '/static/sounds/alert.mp3',
            payment_failed:     '/static/sounds/error.mp3',
            expense_created:    '/static/sounds/notify.mp3',
            invoice_fiscalized: '/static/sounds/notify.mp3',
            default:            '/static/sounds/notify.mp3',
        };
        const audio = new Audio(soundMap[notification_type] || soundMap.default);
        audio.play().catch(() => {});

        // Optionally show a toast / in-app notification here
    });

    // ── 7. Run on page load ───────────────────────────────────────────────────
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', registerAndSubscribe);
    } else {
        registerAndSubscribe();
    }
})();