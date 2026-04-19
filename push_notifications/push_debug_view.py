"""
push_debug_view.py — Temporary debug page for FCM token registration.

HOW TO USE:
1. Add to your push_notifications/urls.py:
      path('debug/', views.push_debug, name='push_debug'),

2. Visit: https://yoursite.com/push/debug/

3. Open DevTools → Console while the page loads.
   The page will walk through every step and show you exactly what fails.

4. REMOVE this view once notifications are working.
"""

from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse


@login_required
def push_debug(request):
    """
    Renders a standalone debug page that tests every layer of FCM setup
    directly in the browser console. No extra dependencies needed.
    """
    from django.conf import settings
    import json

    import html as _html

    # Pull config values to expose to the page
    firebase_vapid = getattr(settings, 'FIREBASE_VAPID_PUBLIC_KEY', '').strip()

    # Check DB state for this user
    from push_notifications.models import PushSubscription
    subs = list(
        PushSubscription.objects
        .filter(user=request.user)
        .values('id', 'fcm_token', 'is_active', 'created_at', 'last_used_at')
    )
    subs_json = json.dumps(subs, default=str).replace("</", "<\\/").replace("\n", " ").replace("\r", "")
    safe_user = _html.escape(str(request.user))
    safe_uid  = _html.escape(str(request.user.pk))
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="csrf-token" content="{_html.escape(request.META.get('CSRF_COOKIE', '').strip())}">
<title>FCM Push Debug</title>
<style>
  body {{ font-family: monospace; background: #0d1117; color: #c9d1d9; padding: 2rem; margin: 0; }}
  h1   {{ color: #58a6ff; margin-bottom: 0.5rem; }}
  h2   {{ color: #8b949e; font-size: 0.9rem; margin: 0 0 2rem; font-weight: normal; }}
  .card {{ background: #161b22; border: 1px solid #30363d; border-radius: 8px;
            padding: 1.25rem 1.5rem; margin-bottom: 1rem; }}
  .card h3 {{ margin: 0 0 0.75rem; font-size: 0.95rem; color: #8b949e; text-transform: uppercase; letter-spacing: 0.05em; }}
  .step {{ display: flex; align-items: flex-start; gap: 0.75rem; padding: 0.5rem 0;
            border-bottom: 1px solid #21262d; font-size: 0.875rem; }}
  .step:last-child {{ border-bottom: none; }}
  .icon {{ font-size: 1rem; width: 1.25rem; flex-shrink: 0; margin-top: 0.1rem; }}
  .pending {{ color: #8b949e; }}
  .ok      {{ color: #3fb950; }}
  .fail    {{ color: #f85149; }}
  .warn    {{ color: #d29922; }}
  .detail  {{ color: #8b949e; font-size: 0.8rem; margin-top: 0.2rem; word-break: break-all; }}
  button   {{ background: #238636; color: white; border: none; border-radius: 6px;
               padding: 0.6rem 1.2rem; font-family: monospace; font-size: 0.875rem;
               cursor: pointer; margin-top: 1rem; }}
  button:hover {{ background: #2ea043; }}
  button:disabled {{ background: #21262d; color: #484f58; cursor: not-allowed; }}
  #log {{ background: #010409; border: 1px solid #30363d; border-radius: 6px;
           padding: 1rem; font-size: 0.8rem; height: 200px; overflow-y: auto;
           white-space: pre-wrap; margin-top: 0.75rem; color: #8b949e; }}
  pre  {{ background: #010409; padding: 1rem; border-radius: 6px; overflow-x: auto;
           font-size: 0.8rem; border: 1px solid #30363d; }}
</style>
</head>
<body>

<h1>🔔 FCM Push Notification Debug</h1>
<h2>Logged in as: {safe_user} (id={safe_uid}) &nbsp;|&nbsp; <a href="/push/debug/?run=1" style="color:#58a6ff">Re-run tests</a></h2>

<div class="card">
  <h3>📦 DB Subscriptions for this user</h3>
  <pre id="dbSubs"></pre>
</div>

<div class="card">
  <h3>🔬 Browser Step-by-Step Tests</h3>
  <div id="steps"></div>
  <button id="runBtn" onclick="runTests()">▶ Run All Tests</button>
</div>

<div class="card">
  <h3>📋 Console Log</h3>
  <div id="log"></div>
</div>

<script>
// ── Data from server ──────────────────────────────────────────────────────────
const DB_SUBS       = {subs_json};
const VAPID_KEY     = "{firebase_vapid.replace(chr(10), '').replace(chr(13), '').replace('"', '\\"')}";
const SUBSCRIBE_URL = "/push/subscribe/";

// ── Firebase config — MUST match what you put in base.html and sws.js ────────
// If this is wrong here, it is wrong everywhere.
const FIREBASE_CONFIG = {{
  // Replace these with your REAL values:
  apiKey: "AIzaSyDw9m46zLPfxwbiRMqzB9ftLvdLg-aNZ1w",
  authDomain: "fcm-pro-3dd2f.firebaseapp.com",
  projectId: "fcm-pro-3dd2f",
  storageBucket: "fcm-pro-3dd2f.firebasestorage.app",
  messagingSenderId: "562803335953",
  appId: "1:562803335953:web:c476b06a0135440294e2b0"
}};

// ── Helpers ───────────────────────────────────────────────────────────────────
const stepsEl = document.getElementById('steps');
const logEl   = document.getElementById('log');

function log(msg) {{
  const ts = new Date().toISOString().substr(11, 8);
  logEl.textContent += `[${{ts}}] ${{msg}}\\n`;
  logEl.scrollTop = logEl.scrollHeight;
  console.log('[FCM-Debug]', msg);
}}

function addStep(id, label) {{
  const div = document.createElement('div');
  div.className = 'step';
  div.id = 'step-' + id;
  div.innerHTML = `
    <span class="icon pending" id="icon-${{id}}">⏳</span>
    <div>
      <div>${{label}}</div>
      <div class="detail" id="detail-${{id}}"></div>
    </div>`;
  stepsEl.appendChild(div);
}}

function setStep(id, status, detail) {{
  const icon   = document.getElementById('icon-' + id);
  const detEl  = document.getElementById('detail-' + id);
  const map    = {{ ok: ['✅','ok'], fail: ['❌','fail'], warn: ['⚠️','warn'], pending: ['⏳','pending'] }};
  const [ico, cls] = map[status] || map.pending;
  icon.textContent = ico;
  icon.className   = 'icon ' + cls;
  if (detail) detEl.textContent = detail;
}}

function getCsrf() {{
  const m = document.querySelector('meta[name="csrf-token"]');
  if (m) return m.getAttribute('content');
  const c = document.cookie.split('; ').find(r => r.startsWith('csrftoken='));
  return c ? c.split('=')[1] : '';
}}

// ── Show DB state ─────────────────────────────────────────────────────────────
document.getElementById('dbSubs').textContent =
  DB_SUBS.length
    ? JSON.stringify(DB_SUBS, null, 2)
    : '⚠ No subscriptions found in DB for this user.\\n  Grant permission below — a token should appear here after you refresh.';

// ── Main test runner ──────────────────────────────────────────────────────────
async function runTests() {{
  document.getElementById('runBtn').disabled = true;
  stepsEl.innerHTML = '';
  logEl.textContent = '';

  // Define steps
  addStep('sw',       'Service Worker API supported');
  addStep('notif',    'Notifications API supported');
  addStep('swreg',    'Register /sws.js service worker');
  addStep('swactive', 'Service worker becomes active');
  addStep('perm',     'Notification permission granted');
  addStep('fbload',   'Firebase SDK loaded (firebase object exists)');
  addStep('fbinit',   'Firebase app initialise');
  addStep('token',    'Get FCM registration token');
  addStep('save',     'Save token to Django backend');
  addStep('done',     'All done');

  // 1. Service Worker support
  log('Checking Service Worker support...');
  if (!('serviceWorker' in navigator)) {{
    setStep('sw', 'fail', 'navigator.serviceWorker not available — browser does not support SW');
    log('FAIL: No serviceWorker support');
    return;
  }}
  setStep('sw', 'ok', 'navigator.serviceWorker available');
  log('OK: serviceWorker supported');

  // 2. Notifications API
  log('Checking Notifications API...');
  if (!('Notification' in window)) {{
    setStep('notif', 'fail', 'window.Notification not available — browser does not support push');
    log('FAIL: No Notification API');
    return;
  }}
  setStep('notif', 'ok', `Notification supported. Current permission: "${{Notification.permission}}"`);
  log(`OK: Notification API, permission=${{Notification.permission}}`);

  // 3. Register SW
  log('Registering service worker at /sws.js ...');
  let swReg;
  try {{
    swReg = await navigator.serviceWorker.register('/sws.js', {{
      scope: '/',
      updateViaCache: 'none',
    }});
    setStep('swreg', 'ok', `Registered. Scope: ${{swReg.scope}}`);
    log(`OK: SW registered. scope=${{swReg.scope}}`);
  }} catch(e) {{
    setStep('swreg', 'fail',
      `FAILED: ${{e.message}} — Check that /sws.js is served at the ROOT of your domain, ` +
      `not /static/js/sws.js. In Django you need a view or whitenoise rule for /sws.js.`);
    log(`FAIL: SW register error: ${{e}}`);
    return;
  }}

  // 4. SW active
  log('Waiting for SW to become active...');
  try {{
    await navigator.serviceWorker.ready;
    const sw = swReg.active || swReg.installing || swReg.waiting;
    setStep('swactive', 'ok', `SW state: ${{sw ? sw.state : 'unknown'}}`);
    log(`OK: SW ready. state=${{sw ? sw.state : '?'}}`);
  }} catch(e) {{
    setStep('swactive', 'fail', `${{e.message}}`);
    log(`FAIL: SW ready error: ${{e}}`);
  }}

  // 5. Notification permission
  log('Requesting notification permission...');
  let perm;
  try {{
    perm = await Notification.requestPermission();
    if (perm === 'granted') {{
      setStep('perm', 'ok', 'Permission granted');
      log('OK: Permission granted');
    }} else if (perm === 'denied') {{
      setStep('perm', 'fail',
        'Permission DENIED. Go to Chrome site settings and reset notification permission for this site.');
      log('FAIL: Permission denied');
      return;
    }} else {{
      setStep('perm', 'warn', `Permission: ${{perm}} (default — user dismissed the prompt)`);
      log(`WARN: Permission ${{perm}}`);
      return;
    }}
  }} catch(e) {{
    setStep('perm', 'fail', `${{e.message}}`);
    log(`FAIL: requestPermission error: ${{e}}`);
    return;
  }}

  // 6. Firebase SDK loaded
  log('Checking Firebase SDK...');
  if (typeof firebase === 'undefined') {{
    setStep('fbload', 'fail',
      'firebase is not defined! The Firebase SDK <script> tags are missing from the page. ' +
      'Make sure base.html includes the two firebase-app-compat and firebase-messaging-compat scripts BEFORE this page loads.');
    log('FAIL: firebase undefined');
    return;
  }}
  setStep('fbload', 'ok', `firebase SDK loaded. apps: ${{firebase.apps.length}}`);
  log(`OK: firebase defined, ${{firebase.apps.length}} app(s)`);

  // 7. Firebase init
  log('Initialising Firebase app...');
  let messaging;
  try {{
    if (!firebase.apps.length) {{
      firebase.initializeApp(FIREBASE_CONFIG);
      log('Firebase app initialised fresh');
    }} else {{
      log('Firebase app already initialised, reusing');
    }}
    messaging = firebase.messaging();
    setStep('fbinit', 'ok', `projectId: ${{FIREBASE_CONFIG.projectId}}`);
    log(`OK: Firebase init. projectId=${{FIREBASE_CONFIG.projectId}}`);
  }} catch(e) {{
    setStep('fbinit', 'fail',
      `${{e.message}} — Common causes: wrong projectId, invalid apiKey, ` +
      `or messagingSenderId does not match the VAPID key.`);
    log(`FAIL: Firebase init error: ${{e}}`);
    return;
  }}

  // 8. Get token
  log(`Getting FCM token with VAPID key: ${{VAPID_KEY.substring(0,20)}}...`);
  if (!VAPID_KEY || VAPID_KEY.includes('YOUR_') || VAPID_KEY.includes('REPLACE')) {{
    setStep('token', 'fail',
      'FIREBASE_VAPID_PUBLIC_KEY is still a placeholder! ' +
      'Set FIREBASE_VAPID_PUBLIC_KEY in Django settings.py with the real key from ' +
      'Firebase Console → Project Settings → Cloud Messaging → Web Push certificates.');
    log('FAIL: VAPID key is placeholder');
    return;
  }}
  let token;
  try {{
    token = await messaging.getToken({{
      vapidKey: VAPID_KEY,
      serviceWorkerRegistration: swReg,
    }});
    if (!token) {{
      setStep('token', 'fail',
        'getToken() returned null/empty. This usually means the VAPID key does not match ' +
        'the Firebase project, or the SW could not be claimed by Firebase.');
      log('FAIL: token is empty');
      return;
    }}
    setStep('token', 'ok', `Token: ${{token.substring(0, 50)}}...`);
    log(`OK: Token obtained (${{token.length}} chars)`);
  }} catch(e) {{
    setStep('token', 'fail',
      `${{e.message}} — Common causes: (1) sws.js has wrong Firebase config, ` +
      `(2) VAPID key does not match this Firebase project, ` +
      `(3) Chrome blocked by an extension or Android battery saver.`);
    log(`FAIL: getToken error: ${{e}}`);
    return;
  }}

  // 9. Save to backend
  log('Saving token to Django backend...');
  try {{
    const resp = await fetch(SUBSCRIBE_URL, {{
      method: 'POST',
      headers: {{
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf(),
      }},
      body: JSON.stringify({{ fcm_token: token }}),
    }});
    const body = await resp.text();
    if (resp.ok) {{
      setStep('save', 'ok', `HTTP ${{resp.status}} — ${{body}}`);
      log(`OK: Token saved. Response: ${{body}}`);
    }} else {{
      setStep('save', 'fail',
        `HTTP ${{resp.status}} — ${{body}} — Check Django logs for the error in save_subscription view.`);
      log(`FAIL: Backend returned ${{resp.status}}: ${{body}}`);
      return;
    }}
  }} catch(e) {{
    setStep('save', 'fail', `Network error: ${{e.message}}`);
    log(`FAIL: fetch error: ${{e}}`);
    return;
  }}

  // 10. Done
  setStep('done', 'ok',
    '🎉 All steps passed! Refresh this page — your FCM token should now appear in the DB Subscriptions panel above. ' +
    'If it does, complete a test sale and you should receive a notification.');
  log('ALL STEPS PASSED. Token is saved. Push should now work.');
  document.getElementById('runBtn').disabled = false;
}}

// Auto-run if ?run=1
if (new URLSearchParams(location.search).get('run') === '1') {{
  runTests();
}}
</script>

<!-- Firebase SDK — same versions as base.html -->
<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.2/firebase-messaging-compat.js"></script>

</body>
</html>"""

    return HttpResponse(html, content_type='text/html')