/**
 * support_widget/static/support_widget/js/widget.js
 *
 * Self-contained support chat + voice call widget.
 * Embedded via {% include 'support_widget/widget_embed.html' %}
 *
 * State machine:
 *   idle → name → email → faq → chat → [consent → call]
 *
 * Key design decisions:
 *   - All WebRTC inline (no popup — popups get blocked by browsers)
 *   - Visitor can initiate call OR chat
 *   - Agent-initiated calls ring the visitor continuously
 *   - Audio-only recording (no video)
 *   - Messages persisted across panel open/close via sessionStorage
 */

(function () {
  'use strict';

  const ROOT = document.getElementById('sw-widget-root');
  if (!ROOT) return;

  // ── Config from data attributes ───────────────────────────────────────────
  const API_BASE    = ROOT.dataset.apiBase    || '/support';
  const BRAND_COLOR   = ROOT.dataset.brandColor   || '#6366f1';
  const BUBBLE_BOTTOM = ROOT.dataset.bubbleBottom || '24px';
  const BUBBLE_LEFT   = ROOT.dataset.bubbleLeft   || '';
  const BUBBLE_RIGHT  = ROOT.dataset.bubbleRight  || (ROOT.dataset.bubbleLeft ? '' : '24px');
  const _hPos = BUBBLE_LEFT ? `left:${BUBBLE_LEFT};right:auto;` : `right:${BUBBLE_RIGHT};left:auto;`;
  const PRE_NAME    = ROOT.dataset.userName   || '';
  const PRE_EMAIL   = ROOT.dataset.userEmail  || '';
  const IS_STAFF    = ROOT.dataset.isStaff    === 'true';
  const GREETING    = ROOT.dataset.greeting   || '👋 Hi! How can we help?';
  const TITLE       = ROOT.dataset.title      || 'Support';
  const WS_PROTO    = location.protocol === 'https:' ? 'wss' : 'ws';
  const WS_HOST     = location.host;

  // ── ICE servers for WebRTC ────────────────────────────────────────────────
  const ICE_SERVERS = [
    { urls: 'stun:stun.l.google.com:19302' },
    { urls: 'stun:stun1.l.google.com:19302' },
    // Add TURN server here for production:
    // { urls: 'turn:your.server:3478', username: 'u', credential: 'p' }
  ];

  // ── Persistent state (sessionStorage so it survives page reload) ──────────
  const STORE_KEY = 'sw_v2';
  let state = {
    step:          'idle',   // idle|name|email|faq|chat|consent|call
    session_token: null,
    visitor_name:  '',
    visitor_email: '',
    call_room_id:  null,
    open:          false,
  };

  // Message history — kept in memory, re-rendered on panel open
  let _messages = [];   // [{sender, body, timestamp}]

  function _loadState() {
    try {
      const s = JSON.parse(sessionStorage.getItem(STORE_KEY) || '{}');
      Object.assign(state, s.state || {});
      _messages = s.messages || [];
    } catch (_) {}
  }

  function _saveState() {
    try {
      sessionStorage.setItem(STORE_KEY, JSON.stringify({
        state:    { ...state, open: false },
        messages: _messages.slice(-100),   // keep last 100 messages
      }));
    } catch (_) {}
  }

  _loadState();

  // ── WebSocket (chat) ──────────────────────────────────────────────────────
  let _ws = null;

  function _connectWS(token) {
    if (_ws && _ws.readyState < 2) return;
    _ws = new WebSocket(`${WS_PROTO}://${WS_HOST}/ws/support/${token}/`);
    _ws.onmessage = _onWSMessage;
    _ws.onclose   = () => {
      if (state.session_token && !['idle', 'resolved'].includes(state.step)) {
        setTimeout(() => _connectWS(state.session_token), 3000);
      }
    };
  }

  function _sendWS(payload) {
    if (_ws && _ws.readyState === WebSocket.OPEN)
      _ws.send(JSON.stringify(payload));
  }

  function _onWSMessage(evt) {
    let d; try { d = JSON.parse(evt.data); } catch (_) { return; }
    switch (d.type) {
      case 'chat_message':
        if (d.sender !== 'visitor') {
          _addMessage(d.sender, d.body, d.timestamp);
          _playNotificationSound();
          _showBrowserNotification('New message from support', d.body);
        }
        break;
      case 'typing':
        _showTyping(d.sender);
        break;
      case 'session_updated':
        state.step = 'faq'; _saveState();
        _renderFAQ();
        break;
      case 'no_agent_available':
        _addMessage('system', d.message || "All agents busy. We'll email you shortly.");
        _resetAgentBtn();
        break;
      case 'start_call':
        // Agent-initiated call — open panel and ring
        if (!state.open) _togglePanel(true);
        _showIncomingCall(d.call_room_id, d.recording_notice);
        _ringContinuous();
        _showBrowserNotification('📞 Incoming Support Call', 'An agent wants to talk with you');
        break;
    }
  }

  // ── REST API ──────────────────────────────────────────────────────────────
  async function _api(path, method = 'GET', body = null) {
    try {
      const opts = { method, headers: { 'Content-Type': 'application/json' } };
      if (body) opts.body = JSON.stringify(body);
      const r = await fetch(`${API_BASE}${path}`, opts);
      return r.json();
    } catch (_) { return {}; }
  }

  // ── Build DOM ─────────────────────────────────────────────────────────────
  ROOT.innerHTML = `
  <style>
    #sw-panel, #sw-bubble {
      --sw-bg:#fff; --sw-body-bg:#f8fafc; --sw-border:#e5e7eb;
      --sw-text:#111; --sw-muted:#6b7280; --sw-label:#374151;
      --sw-faq-bg:#fff; --sw-input-bg:#fff;
      --sw-msg-agent-bg:#fff; --sw-msg-agent-color:#111;
      --sw-action-bg:#fff; --sw-footer-bg:#fff;
      --sw-card-bg:#fff; --sw-card-border:#e5e7eb;
      --sw-mute-bg:#f3f4f6;
      --sw-system-bg:#fef3c7; --sw-system-color:#92400e;
      --sw-notice-bg:#fffbeb; --sw-notice-border:#fbbf24; --sw-notice-color:#92400e;
    }
    [data-theme="dark"] #sw-panel, [data-theme="dark"] #sw-bubble {
      --sw-bg:#1e293b; --sw-body-bg:#0f172a; --sw-border:rgba(255,255,255,.08);
      --sw-text:#f1f5f9; --sw-muted:#94a3b8; --sw-label:#cbd5e1;
      --sw-faq-bg:#1e293b; --sw-input-bg:#0f172a;
      --sw-msg-agent-bg:#1e293b; --sw-msg-agent-color:#f1f5f9;
      --sw-action-bg:#1e293b; --sw-footer-bg:#1e293b;
      --sw-card-bg:#1e293b; --sw-card-border:rgba(255,255,255,.08);
      --sw-mute-bg:#273548;
      --sw-system-bg:rgba(251,191,36,.12); --sw-system-color:#fbbf24;
      --sw-notice-bg:rgba(251,191,36,.08); --sw-notice-border:rgba(251,191,36,.3); --sw-notice-color:#fbbf24;
    }
    #sw-bubble {
      position:fixed; bottom:${BUBBLE_BOTTOM}; ${_hPos} z-index:9900;
      width:58px; height:58px; border-radius:50%;
      background:${BRAND_COLOR};
      box-shadow:0 4px 20px rgba(0,0,0,.28);
      cursor:pointer; border:none; outline:none;
      display:flex; align-items:center; justify-content:center;
      animation:sw-pulse 2.8s infinite;
      transition:transform .2s;
    }
    #sw-bubble:hover { transform:scale(1.1); }
    #sw-bubble.ringing { animation:sw-ring 0.6s infinite; }
    @keyframes sw-pulse {
      0%,100%{ box-shadow:0 4px 20px rgba(0,0,0,.28),0 0 0 0 ${BRAND_COLOR}55; }
      50%    { box-shadow:0 4px 20px rgba(0,0,0,.28),0 0 0 12px ${BRAND_COLOR}00; }
    }
    @keyframes sw-ring {
      0%  { transform:scale(1)   rotate(0deg);   }
      20% { transform:scale(1.1) rotate(-8deg);  }
      40% { transform:scale(1.1) rotate(8deg);   }
      60% { transform:scale(1.1) rotate(-8deg);  }
      80% { transform:scale(1.1) rotate(8deg);   }
      100%{ transform:scale(1)   rotate(0deg);   }
    }
    #sw-bubble svg { width:26px; height:26px; fill:#fff; }
    #sw-badge {
      position:absolute; top:-4px; right:-4px;
      min-width:18px; height:18px; border-radius:9px; padding:0 4px;
      background:#ef4444; color:#fff; font-size:10px; font-weight:700;
      display:none; align-items:center; justify-content:center;
      font-family:sans-serif;
    }
    #sw-panel {
      position:fixed; bottom:calc(${BUBBLE_BOTTOM} + 68px); ${_hPos} z-index:9899;
      width:360px; max-height:min(580px, calc(100vh - var(--sw-bottom-gap, 100px)));
      background:var(--sw-bg); border-radius:18px;
      box-shadow:0 24px 60px rgba(0,0,0,.18);
      display:none; flex-direction:column; overflow:hidden;
      font-family:'Plus Jakarta Sans',system-ui,sans-serif;
    }
    #sw-panel.open { display:flex; animation:sw-up .25s cubic-bezier(.16,1,.3,1); }
    @keyframes sw-up { from{opacity:0;transform:translateY(18px)} to{opacity:1;transform:translateY(0)} }

    #sw-hdr {
      background:${BRAND_COLOR}; color:#fff;
      padding:13px 16px; display:flex; align-items:center; gap:10px; flex-shrink:0;
    }
    #sw-hdr-title { font-weight:700; font-size:.95rem; flex:1; }
    #sw-hdr-close {
      background:none; border:none; cursor:pointer;
      color:rgba(255,255,255,.8); font-size:1.15rem; line-height:1; padding:0 4px;
    }
    #sw-hdr-close:hover { color:#fff; }

    #sw-body {
      flex:1; overflow-y:auto; padding:14px;
      display:flex; flex-direction:column; gap:9px;
      background:var(--sw-body-bg); min-height:120px;
    }

    /* Messages */
    .sw-msg {
      max-width:84%; padding:9px 13px; border-radius:13px;
      font-size:.84rem; line-height:1.5; word-break:break-word;
    }
    .sw-msg.visitor { background:${BRAND_COLOR}; color:#fff; align-self:flex-end; border-bottom-right-radius:4px; }
    .sw-msg.agent   { background:var(--sw-msg-agent-bg); color:var(--sw-msg-agent-color); align-self:flex-start; border:1px solid var(--sw-border); border-bottom-left-radius:4px; }
    .sw-msg.bot     { background:var(--sw-msg-agent-bg); color:var(--sw-msg-agent-color); align-self:flex-start; border:1px solid var(--sw-border); border-bottom-left-radius:4px; }
    .sw-msg.system  { background:var(--sw-system-bg); color:var(--sw-system-color); align-self:center; font-size:.76rem; border-radius:8px; text-align:center; max-width:100%; padding:6px 12px; }
    .sw-msg-time    { font-size:.65rem; opacity:.55; margin-top:3px; }

    /* FAQ */
    .sw-faq {
      background:var(--sw-faq-bg); border:1px solid var(--sw-border); border-radius:10px;
      padding:10px 12px; cursor:pointer; font-size:.82rem; color:var(--sw-text);
      transition:border-color .15s;
    }
    .sw-faq:hover { border-color:${BRAND_COLOR}; }
    .sw-faq-q { font-weight:700; }
    .sw-faq-a { color:var(--sw-muted); display:none; margin-top:5px; line-height:1.5; }
    .sw-faq.open .sw-faq-a { display:block; }

    /* Forms */
    .sw-form { display:flex; flex-direction:column; gap:6px; }
    .sw-form label { font-size:.77rem; font-weight:700; color:var(--sw-label); }
    .sw-form input {
      border:1px solid var(--sw-border); border-radius:8px;
      padding:8px 11px; font-size:.86rem; outline:none; background:var(--sw-input-bg); color:var(--sw-text);
    }
    .sw-form input:focus { border-color:${BRAND_COLOR}; }

    /* Buttons */
    .sw-btn {
      padding:9px 15px; border-radius:9px; border:none; cursor:pointer;
      font-size:.84rem; font-weight:700; font-family:inherit;
      transition:opacity .15s, transform .1s; display:inline-flex; align-items:center; gap:6px;
    }
    .sw-btn:hover { opacity:.87; transform:translateY(-1px); }
    .sw-btn-primary { background:${BRAND_COLOR}; color:#fff; }
    .sw-btn-outline { background:transparent; border:1.5px solid ${BRAND_COLOR}; color:${BRAND_COLOR}; }
    .sw-btn-danger  { background:#ef4444; color:#fff; }
    .sw-btn-success { background:#10b981; color:#fff; }
    .sw-btn-full    { width:100%; justify-content:center; }

    /* Action bar (Talk to agent / Call buttons) */
    #sw-actions {
      padding:8px 12px; border-top:1px solid var(--sw-border);
      background:var(--sw-action-bg); display:none; flex-direction:column; gap:6px; flex-shrink:0;
    }
    #sw-actions .sw-action-row { display:flex; gap:6px; }

    /* Chat footer */
    #sw-footer {
      display:none; gap:8px; padding:10px 12px;
      border-top:1px solid var(--sw-border); background:var(--sw-footer-bg); flex-shrink:0;
    }
    #sw-input {
      flex:1; border:1px solid var(--sw-border); border-radius:9px;
      padding:8px 12px; font-size:.86rem; outline:none; resize:none;
      font-family:inherit; max-height:80px; background:var(--sw-input-bg); color:var(--sw-text);
    }
    #sw-input:focus { border-color:${BRAND_COLOR}; }
    #sw-send {
      width:38px; height:38px; border-radius:9px;
      background:${BRAND_COLOR}; border:none; cursor:pointer;
      display:flex; align-items:center; justify-content:center;
    }
    #sw-send svg { width:15px; height:15px; fill:#fff; }
    #sw-send:hover { opacity:.85; }

    /* Typing indicator */
    #sw-typing { font-size:.73rem; color:var(--sw-muted); min-height:17px; padding:2px 14px; flex-shrink:0; }

    /* Call card */
    #sw-call-card {
      background:var(--sw-card-bg); border:1.5px solid var(--sw-card-border); border-radius:14px;
      overflow:hidden; flex-shrink:0;
    }
    .sw-call-hdr {
      background:linear-gradient(135deg,${BRAND_COLOR},#8b5cf6);
      padding:18px 16px; text-align:center; position:relative;
    }
    .sw-call-avatar {
      width:56px; height:56px; border-radius:50%;
      background:rgba(255,255,255,.2);
      margin:0 auto 10px; display:flex; align-items:center;
      justify-content:center; font-size:1.6rem; position:relative;
    }
    .sw-call-avatar.ringing::after {
      content:''; position:absolute; inset:-6px; border-radius:50%;
      border:3px solid rgba(255,255,255,.5);
      animation:sw-ring-out 1s ease-out infinite;
    }
    @keyframes sw-ring-out {
      0%   { opacity:.8; transform:scale(1); }
      100% { opacity:0;  transform:scale(1.6); }
    }
    .sw-call-name   { color:#fff; font-weight:800; font-size:.95rem; }
    .sw-call-status { color:rgba(255,255,255,.8); font-size:.76rem; margin-top:3px; }
    .sw-call-timer  { text-align:center; font-family:monospace; font-size:.92rem; color:#10b981; padding:8px 0 2px; min-height:30px; }
    .sw-call-notice {
      background:var(--sw-notice-bg); border:1px solid var(--sw-notice-border); border-radius:8px;
      margin:10px 12px 0; padding:9px 11px; font-size:.74rem; color:var(--sw-notice-color); line-height:1.6;
    }
    .sw-call-btns   { display:flex; gap:8px; padding:10px 12px 14px; }
    .sw-call-ctrl   { display:flex; gap:12px; justify-content:center; padding:10px 12px 14px; }
    .sw-ctrl-btn {
      width:48px; height:48px; border-radius:50%; border:none; cursor:pointer;
      font-size:1.15rem; transition:transform .15s; display:flex; align-items:center; justify-content:center;
    }
    .sw-ctrl-btn:hover { transform:scale(1.1); }
    .sw-ctrl-mute   { background:var(--sw-mute-bg); border:1px solid var(--sw-border); }
    .sw-ctrl-hangup { background:#ef4444; }

    @media(max-width:420px) {
      #sw-panel { width:calc(100vw - 20px); ${BUBBLE_LEFT ? 'left:10px;right:auto;' : 'right:10px;left:auto;'} bottom:152px; }
    }
  </style>

  <button id="sw-bubble" title="Chat with support" aria-label="Open support">
    <svg viewBox="0 0 24 24"><path d="M20 2H4a2 2 0 00-2 2v18l4-4h14a2 2 0 002-2V4a2 2 0 00-2-2z"/></svg>
    <span id="sw-badge"></span>
  </button>

  <div id="sw-panel" role="dialog" aria-label="Support">
    <div id="sw-hdr">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="rgba(255,255,255,.9)">
        <path d="M20 2H4a2 2 0 00-2 2v18l4-4h14a2 2 0 002-2V4a2 2 0 00-2-2z"/>
      </svg>
      <span id="sw-hdr-title">${TITLE}</span>
      <button id="sw-hdr-close" aria-label="Close">✕</button>
    </div>

    <div id="sw-body"></div>
    <div id="sw-typing"></div>

    <!-- Action bar: chat with agent + voice call -->
    <div id="sw-actions">
      <div class="sw-action-row">
        <button class="sw-btn sw-btn-outline sw-btn-full" id="sw-btn-chat" style="flex:1">
          💬 Chat with agent
        </button>
        <button class="sw-btn sw-btn-success" id="sw-btn-call" style="flex:0 0 auto" title="Voice call">
          📞
        </button>
      </div>
    </div>

    <!-- Text input -->
    <div id="sw-footer">
      <textarea id="sw-input" placeholder="Type a message…" rows="1"></textarea>
      <button id="sw-send" aria-label="Send">
        <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
      </button>
    </div>
  </div>

  <audio id="sw-remote-audio" autoplay style="display:none"></audio>
  `;

  // ── Refs ──────────────────────────────────────────────────────────────────
  const $bubble   = document.getElementById('sw-bubble');
  const $panel    = document.getElementById('sw-panel');
  const $body     = document.getElementById('sw-body');
  const $footer   = document.getElementById('sw-footer');
  const $input    = document.getElementById('sw-input');
  const $send     = document.getElementById('sw-send');
  const $close    = document.getElementById('sw-hdr-close');
  const $actions  = document.getElementById('sw-actions');
  const $btnChat  = document.getElementById('sw-btn-chat');
  const $btnCall  = document.getElementById('sw-btn-call');
  const $typing   = document.getElementById('sw-typing');
  const $badge    = document.getElementById('sw-badge');

  let _unread = 0;
  let _typingTimer = null;
  let _ringInterval = null;   // continuous ring interval

  // ── Panel open/close ──────────────────────────────────────────────────────
  $bubble.addEventListener('click', () => _togglePanel());
  $close.addEventListener('click', () => _togglePanel(false));

  function _togglePanel(force) {
    state.open = (force !== undefined) ? !!force : !state.open;
    $panel.classList.toggle('open', state.open);
    if (state.open) {
      _unread = 0;
      $badge.style.display = 'none';
      _stopRing();
      if (state.step === 'idle') {
        _startWidget();
      } else {
        _restorePanel();
      }
    }
    _saveState();
  }

  // ── Restore panel after re-open ───────────────────────────────────────────
  function _restorePanel() {
    // Re-render all saved messages
    $body.innerHTML = '';
    _messages.forEach(m => _renderMessage(m.sender, m.body, m.timestamp));

    // Restore UI state
    if (['faq','chat','consent','call'].includes(state.step)) {
      $footer.style.display  = 'flex';
      $actions.style.display = 'flex';
    }
    if (state.step === 'consent' && state.call_room_id) {
      _showIncomingCall(state.call_room_id, state.recording_notice || '');
    }

    // Reconnect WS
    if (state.session_token) _connectWS(state.session_token);

    _scrollBottom();
  }

  // ── Start fresh ───────────────────────────────────────────────────────────
  async function _startWidget() {
    if (state.session_token) {
      _connectWS(state.session_token);
      _restorePanel();
      return;
    }
    // Brand new session
    _addMessage('bot', GREETING);
    const res = await _api('/session/', 'POST', {
      referrer_url: location.href,
      user_agent:   navigator.userAgent,
    });
    if (res.session_token) {
      state.session_token = res.session_token;
      _saveState();
      _connectWS(res.session_token);

      // Skip name/email onboarding if user data is already known (staff/logged-in users)
      if (PRE_NAME && PRE_EMAIL) {
        state.visitor_name  = PRE_NAME;
        state.visitor_email = PRE_EMAIL;
        _saveState();
        // Send session info to server silently
        _sendWS({ type: 'session_update', name: PRE_NAME, email: PRE_EMAIL });
        _api(`/session/${state.session_token}/`, 'POST', { name: PRE_NAME, email: PRE_EMAIL });
        // Go straight to chat — skip name/email forms
        _addMessage('bot', `Hi ${PRE_NAME}! How can we help you today? Type a message or click "Chat with agent".`);
        $footer.style.display  = 'flex';
        $actions.style.display = 'flex';
        state.step = 'chat'; _saveState();
      } else {
        _askName();
      }
    }
  }

  // ── Onboarding ────────────────────────────────────────────────────────────
  function _askName() {
    state.step = 'name'; _saveState();
    _appendForm("What's your name?", 'Your name', 'text', val => {
      state.visitor_name = val;
      _askEmail();
    });
  }

  function _askEmail() {
    state.step = 'email'; _saveState();
    _addMessage('bot', `Nice to meet you, ${state.visitor_name}! 😊 What's your email so we can follow up?`);
    _appendForm(null, 'your@email.com', 'email', val => {
      state.visitor_email = val;
      _sendWS({ type: 'session_update', name: state.visitor_name, email: state.visitor_email });
      _api(`/session/${state.session_token}/`, 'POST', { name: state.visitor_name, email: state.visitor_email });
      _renderFAQ();
    });
  }

  async function _renderFAQ() {
    state.step = 'faq'; _saveState();
    _addMessage('bot', `Thanks ${state.visitor_name}! Here are some common topics — or type your question, or contact an agent below.`);
    $footer.style.display  = 'flex';
    $actions.style.display = 'flex';
    const res = await _api('/faq/');
    if (res.results) res.results.forEach(_appendFAQ);
  }

  // ── Message helpers ───────────────────────────────────────────────────────
  function _addMessage(sender, body, timestamp) {
    const ts = timestamp || new Date().toISOString();
    _messages.push({ sender, body, timestamp: ts });
    _renderMessage(sender, body, ts);
    _saveState();
    if (!state.open && sender !== 'visitor') {
      _unread++;
      $badge.textContent = _unread > 9 ? '9+' : _unread;
      $badge.style.display = 'flex';
    }
  }

  function _renderMessage(sender, body, timestamp) {
    const d = document.createElement('div');
    d.className = `sw-msg ${sender}`;
    const p = document.createElement('div');
    p.textContent = body;
    d.appendChild(p);
    if (timestamp) {
      const t = document.createElement('div');
      t.className = 'sw-msg-time';
      t.textContent = new Date(timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      d.appendChild(t);
    }
    $body.appendChild(d);
    _scrollBottom();
  }

  function _appendForm(label, placeholder, type, onSubmit) {
    const wrap = document.createElement('div');
    wrap.className = 'sw-form';
    wrap.innerHTML = `
      ${label ? `<label>${label}</label>` : ''}
      <input type="${type}" placeholder="${placeholder}"/>
      <button class="sw-btn sw-btn-primary">Continue →</button>
    `;
    const inp = wrap.querySelector('input');
    const btn = wrap.querySelector('button');
    const submit = () => {
      const v = inp.value.trim();
      if (!v) { inp.focus(); return; }
      wrap.remove();
      onSubmit(v);
    };
    btn.addEventListener('click', submit);
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
    $body.appendChild(wrap);
    _scrollBottom();
    setTimeout(() => inp.focus(), 80);
  }

  function _appendFAQ(faq) {
    const d = document.createElement('div');
    d.className = 'sw-faq';
    d.innerHTML = `<div class="sw-faq-q">${faq.question}</div><div class="sw-faq-a">${faq.answer}</div>`;
    d.addEventListener('click', () => d.classList.toggle('open'));
    $body.appendChild(d);
    _scrollBottom();
  }

  function _scrollBottom() { $body.scrollTop = $body.scrollHeight; }

  function _showTyping(sender) {
    if (sender === 'visitor') return;
    $typing.textContent = 'Agent is typing…';
    clearTimeout(_typingTimer);
    _typingTimer = setTimeout(() => { $typing.textContent = ''; }, 2500);
  }

  // ── Chat input ────────────────────────────────────────────────────────────
  $send.addEventListener('click', _sendMessage);
  $input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); _sendMessage(); }
    else _sendWS({ type: 'typing', sender: 'visitor' });
  });

  async function _sendMessage() {
    const text = $input.value.trim();
    if (!text) return;
    $input.value = '';

    _addMessage('visitor', text);
    _sendWS({ type: 'chat_message', sender: 'visitor', body: text });

    if (state.step === 'faq') {
      const res = await _api(`/faq/?q=${encodeURIComponent(text)}`);
      if (res.results && res.results.length) {
        _addMessage('bot', 'Here are some articles that might help:');
        res.results.forEach(_appendFAQ);
      }
      state.step = 'chat'; _saveState();
    }
  }

  // ── Action bar: Chat with agent ───────────────────────────────────────────
  $btnChat.addEventListener('click', _requestAgent);

  function _requestAgent() {
    if (!_ws || _ws.readyState !== WebSocket.OPEN) {
      if (state.session_token) {
        _connectWS(state.session_token);
        setTimeout(_requestAgent, 1200);
      }
      return;
    }
    $btnChat.disabled = true;
    $btnChat.textContent = '⏳ Connecting…';
    _sendWS({ type: 'request_agent' });
    state.step = 'chat'; _saveState();
    setTimeout(() => { if ($btnChat.disabled) _resetAgentBtn(); }, 10000);
  }

  function _resetAgentBtn() {
    $btnChat.disabled = false;
    $btnChat.textContent = '💬 Chat with agent';
  }

  // ── Action bar: Visitor initiates voice call ──────────────────────────────
  $btnCall.addEventListener('click', _visitorInitiateCall);

  async function _visitorInitiateCall() {
    if (!state.session_token) return;

    $btnCall.disabled = true;
    $btnCall.textContent = '⏳';

    const res = await _api('/call/create/', 'POST', { session_token: state.session_token });

    $btnCall.disabled = false;
    $btnCall.textContent = '📞';

    if (!res.call_room_id) {
      _addMessage('system', '❌ Could not start call. Please try again.');
      return;
    }

    // Show the call card immediately as the "caller" — visitor is the offerer
    state.call_room_id = res.call_room_id;
    state.step = 'consent'; _saveState();
    _showOutgoingCall(res.call_room_id, res.recording_notice || '');
  }

  // ── Outgoing call (visitor initiated) ────────────────────────────────────
  function _showOutgoingCall(callRoomId, notice) {
    _removeCallCard();

    const card = document.createElement('div');
    card.id = 'sw-call-card';
    card.innerHTML = `
      <div class="sw-call-hdr">
        <div class="sw-call-avatar ringing" id="sw-call-avatar">📞</div>
        <div class="sw-call-name">Calling Support…</div>
        <div class="sw-call-status" id="sw-call-status">Waiting for an agent to answer</div>
      </div>
      <div class="sw-call-timer" id="sw-call-timer"></div>
      <div class="sw-call-notice">${notice || '⚠️ This call is recorded for quality purposes.'}</div>
      <div class="sw-call-btns" style="justify-content:center;">
        <button class="sw-btn sw-btn-danger" id="sw-hangup-pre">📵 Cancel Call</button>
      </div>
      <div id="sw-active-phase" style="display:none;">
        <div class="sw-call-ctrl">
          <button class="sw-ctrl-btn sw-ctrl-mute" id="sw-mute-btn">🎙️</button>
          <button class="sw-ctrl-btn sw-ctrl-hangup" id="sw-hangup-btn">📵</button>
        </div>
      </div>
    `;
    $body.appendChild(card);
    _scrollBottom();

    document.getElementById('sw-hangup-pre').onclick = () => _endCall(true);

    // Get mic and connect immediately — visitor sends the offer
    _startCallAsOfferer(callRoomId);
  }

  // ── Incoming call (agent initiated) ──────────────────────────────────────
  function _showIncomingCall(callRoomId, notice) {
    _removeCallCard();

    const card = document.createElement('div');
    card.id = 'sw-call-card';
    card.innerHTML = `
      <div class="sw-call-hdr">
        <div class="sw-call-avatar ringing" id="sw-call-avatar">📞</div>
        <div class="sw-call-name">Incoming Voice Call</div>
        <div class="sw-call-status" id="sw-call-status">Support agent is calling…</div>
      </div>
      <div class="sw-call-timer" id="sw-call-timer"></div>
      <div class="sw-call-notice">${notice || '⚠️ This call is recorded for quality purposes.'}</div>
      <div class="sw-call-btns" id="sw-consent-btns">
        <button class="sw-btn sw-btn-success sw-btn-full" id="sw-accept-btn">🎙️ Accept Call</button>
        <button class="sw-btn sw-btn-outline sw-btn-full" id="sw-decline-btn">Decline</button>
      </div>
      <div id="sw-active-phase" style="display:none;">
        <div class="sw-call-ctrl">
          <button class="sw-ctrl-btn sw-ctrl-mute" id="sw-mute-btn">🎙️</button>
          <button class="sw-ctrl-btn sw-ctrl-hangup" id="sw-hangup-btn">📵</button>
        </div>
      </div>
    `;
    $body.appendChild(card);
    _scrollBottom();

    document.getElementById('sw-accept-btn').onclick  = () => _acceptIncomingCall(callRoomId);
    document.getElementById('sw-decline-btn').onclick = () => _declineCall(callRoomId);
  }

  async function _acceptIncomingCall(callRoomId) {
    const consentBtns = document.getElementById('sw-consent-btns');
    if (consentBtns) consentBtns.style.display = 'none';
    _stopRing();
    // Visitor accepts and becomes the offerer
    await _startCallAsOfferer(callRoomId);
  }

  function _declineCall(callRoomId) {
    _stopRing();
    _removeCallCard();
    state.step = 'chat'; _saveState();
    // Tell server
    fetch(`${API_BASE.replace('/support','/support')}/call/${callRoomId}/end/`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
    }).catch(() => {});
    _addMessage('system', 'You declined the voice call. Feel free to send us a message instead.');
    // Ensure chat input is visible
    $footer.style.display  = 'flex';
    $actions.style.display = 'flex';
    _resetAgentBtn();
    // Request an agent via chat instead
    _sendWS({ type: 'request_agent' });
  }

  // ── WebRTC core ───────────────────────────────────────────────────────────
  let _pc = null, _stream = null, _callWS = null;
  let _callMuted = false, _callTimerInterval = null, _callStart = null;
  let _mediaRecorder = null, _recordChunks = [];

  async function _startCallAsOfferer(callRoomId) {
    const statusEl = document.getElementById('sw-call-status');
    if (statusEl) statusEl.textContent = 'Getting microphone…';

    // Get audio-only stream
    try {
      _stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    } catch (e) {
      _addMessage('system', '❌ Microphone access denied. Please allow microphone and try again.');
      _cleanupCall(); return;
    }

    _startRecording(_stream);

    _pc = new RTCPeerConnection({ iceServers: ICE_SERVERS });
    _stream.getTracks().forEach(t => _pc.addTrack(t, _stream));

    _pc.onicecandidate = evt => {
      if (evt.candidate) _callSignal({ type: 'ice', candidate: evt.candidate });
    };

    _pc.ontrack = evt => {
      const a = document.getElementById('sw-remote-audio');
      if (a) a.srcObject = evt.streams[0];
    };

    _pc.onconnectionstatechange = () => {
      const s = _pc && _pc.connectionState;
      if (s === 'connected') {
        _onCallConnected();
      } else if (['disconnected','failed','closed'].includes(s)) {
        _endCall(false);
      }
    };

    // Connect signaling
    _callWS = new WebSocket(`${WS_PROTO}://${WS_HOST}/ws/support/call/${callRoomId}/`);

    _callWS.onopen = async () => {
      // Tell the room this peer joined — agent will receive 'peer_joined'
      // and send back 'ready_for_offer' when they are set up
      _callSignal({ type: 'consent_given' });
      _callSignal({ type: 'visitor_joined' });
      if (statusEl) statusEl.textContent = 'Waiting for agent to answer…';
    };

    _callWS.onmessage = async evt => {
      let d; try { d = JSON.parse(evt.data); } catch (_) { return; }

      if (d.type === 'ready_for_offer') {
        // Agent is ready — NOW send the offer
        if (statusEl) statusEl.textContent = 'Connecting…';
        try {
          const offer = await _pc.createOffer();
          await _pc.setLocalDescription(offer);
          _callSignal({ type: 'offer', sdp: { type: _pc.localDescription.type, sdp: _pc.localDescription.sdp } });
        } catch(e) {
          _addMessage('system', '❌ Failed to create call offer. Please try again.');
          _cleanupCall();
        }
      } else if (d.type === 'answer') {
        await _pc.setRemoteDescription(new RTCSessionDescription({ type: d.sdp.type, sdp: d.sdp.sdp }));
      } else if (d.type === 'ice') {
        try { await _pc.addIceCandidate(new RTCIceCandidate(d.candidate)); } catch (_) {}
      } else if (d.type === 'call_ended') {
        _endCall(false);
      }
    };

    _callWS.onerror = () => {
      _addMessage('system', '❌ Call connection failed. Please try again.');
      _cleanupCall();
    };

    state.step = 'call'; _saveState();
  }

  function _callSignal(payload) {
    if (_callWS && _callWS.readyState === WebSocket.OPEN)
      _callWS.send(JSON.stringify(payload));
  }

  function _onCallConnected() {
    _stopRing();
    const avatarEl  = document.getElementById('sw-call-avatar');
    const statusEl  = document.getElementById('sw-call-status');
    const activeEl  = document.getElementById('sw-active-phase');
    const preBtns   = document.getElementById('sw-consent-btns');
    const preHangup = document.getElementById('sw-hangup-pre');

    if (avatarEl)  { avatarEl.classList.remove('ringing'); avatarEl.textContent = '🔊'; }
    if (statusEl)  statusEl.textContent = 'Connected';
    if (activeEl)  activeEl.style.display = 'block';
    if (preBtns)   preBtns.style.display = 'none';
    if (preHangup) preHangup.style.display = 'none';

    // Wire active controls
    const muteBtn   = document.getElementById('sw-mute-btn');
    const hangupBtn = document.getElementById('sw-hangup-btn');
    if (muteBtn)   muteBtn.onclick   = _toggleMute;
    if (hangupBtn) hangupBtn.onclick = () => _endCall(true);

    // Start timer
    _callStart = Date.now();
    _callTimerInterval = setInterval(() => {
      const el = document.getElementById('sw-call-timer');
      if (!el) { clearInterval(_callTimerInterval); return; }
      const secs = Math.floor((Date.now() - _callStart) / 1000);
      el.textContent = `${String(Math.floor(secs/60)).padStart(2,'0')}:${String(secs%60).padStart(2,'0')}`;
    }, 1000);
  }

  function _toggleMute() {
    _callMuted = !_callMuted;
    _stream && _stream.getAudioTracks().forEach(t => { t.enabled = !_callMuted; });
    const btn = document.getElementById('sw-mute-btn');
    if (btn) { btn.textContent = _callMuted ? '🔇' : '🎙️'; btn.style.opacity = _callMuted ? '.45' : '1'; }
  }

  function _endCall(notify = true) {
    if (notify) _callSignal({ type: 'call_ended' });
    _stopRing();
    _stopRecording(state.call_room_id);
    clearInterval(_callTimerInterval);

    // Notify server
    if (state.call_room_id) {
      fetch(`/support/call/${state.call_room_id}/end/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
      }).catch(() => {});
    }

    _cleanupCall();
    _addMessage('system', '📵 Call ended. You can continue chatting below.');
    state.step = 'chat'; _saveState();
    $footer.style.display  = 'flex';
    $actions.style.display = 'flex';
    _resetAgentBtn();
  }

  function _cleanupCall() {
    if (_pc)     { try { _pc.close(); } catch (_) {} _pc = null; }
    if (_stream) { _stream.getTracks().forEach(t => t.stop()); _stream = null; }
    if (_callWS) { try { _callWS.close(); } catch (_) {} _callWS = null; }
    clearInterval(_callTimerInterval);
    _callMuted = false;
    _removeCallCard();
  }

  function _removeCallCard() {
    const c = document.getElementById('sw-call-card');
    if (c) c.remove();
  }

  // ── Audio-only recording ──────────────────────────────────────────────────
  function _startRecording(stream) {
    _recordChunks = [];
    // Prefer audio/ogg;codecs=opus for better compatibility, fallback to webm audio
    const mimeTypes = [
      'audio/ogg;codecs=opus',
      'audio/webm;codecs=opus',
      'audio/webm',
    ];
    let mimeType = '';
    for (const mt of mimeTypes) {
      if (MediaRecorder.isTypeSupported(mt)) { mimeType = mt; break; }
    }
    try {
      _mediaRecorder = new MediaRecorder(stream, mimeType ? { mimeType } : {});
      _mediaRecorder.ondataavailable = e => { if (e.data.size) _recordChunks.push(e.data); };
      _mediaRecorder.start(1000);
    } catch (e) { console.warn('Recording not supported:', e); }
  }

  function _stopRecording(callRoomId) {
    if (!_mediaRecorder || _mediaRecorder.state === 'inactive') { _mediaRecorder = null; return; }
    const recorder = _mediaRecorder; _mediaRecorder = null;
    recorder.onstop = async () => {
      if (!callRoomId || !_recordChunks.length) return;
      const mimeType = recorder.mimeType || 'audio/webm';
      const ext      = mimeType.includes('ogg') ? 'ogg' : 'webm';
      const blob = new Blob(_recordChunks, { type: mimeType });
      const form = new FormData();
      form.append('file', blob, `call_${callRoomId}.${ext}`);
      try { await fetch(`/support/call/${callRoomId}/recording/`, { method: 'POST', body: form }); }
      catch (_) {}
      _recordChunks = [];
    };
    try { recorder.stop(); } catch (_) {}
  }

  // ── Ringing ───────────────────────────────────────────────────────────────
  function _ringContinuous() {
    _stopRing();
    $bubble.classList.add('ringing');
    // Ring immediately then repeat every 3 seconds
    _playRingTone();
    _ringInterval = setInterval(_playRingTone, 3000);
  }

  function _stopRing() {
    clearInterval(_ringInterval);
    _ringInterval = null;
    $bubble.classList.remove('ringing');
  }

  function _playRingTone() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const t   = ctx.currentTime;
      // Two-tone ring: high-low-high
      [[880, 0], [660, 0.18], [880, 0.36]].forEach(([freq, when]) => {
        const o = ctx.createOscillator();
        const g = ctx.createGain();
        o.connect(g); g.connect(ctx.destination);
        o.type = 'sine';
        o.frequency.value = freq;
        g.gain.setValueAtTime(0.35, t + when);
        g.gain.exponentialRampToValueAtTime(0.001, t + when + 0.15);
        o.start(t + when);
        o.stop(t + when + 0.15);
      });
    } catch (_) {}
  }

  // ── Browser notification ──────────────────────────────────────────────────
  function _notify(title, body) {
    if (!('Notification' in window)) return;
    if (Notification.permission === 'granted') {
      new Notification(title, { body, icon: '/static/favicon.ico' });
    } else if (Notification.permission !== 'denied') {
      Notification.requestPermission().then(p => {
        if (p === 'granted') new Notification(title, { body });
      });
    }
  }

  // Request notification permission early
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }

  function _playNotificationSound() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const o = ctx.createOscillator(), g = ctx.createGain();
      o.connect(g); g.connect(ctx.destination);
      o.type='sine'; o.frequency.setValueAtTime(1046,ctx.currentTime);
      o.frequency.exponentialRampToValueAtTime(784,ctx.currentTime+0.12);
      g.gain.setValueAtTime(0.18,ctx.currentTime);
      g.gain.exponentialRampToValueAtTime(0.001,ctx.currentTime+0.3);
      o.start(ctx.currentTime); o.stop(ctx.currentTime+0.3);
    } catch(_){}
  }
  function _showBrowserNotification(title, body) {
    if(!('Notification'in window)) return;
    if(Notification.permission==='granted'){
      const n=new Notification(title,{body:(body||'').substring(0,80),tag:'support-msg'});
      n.onclick=()=>{window.focus();_togglePanel(true);n.close();};
    } else if(Notification.permission!=='denied') Notification.requestPermission();
  }
  document.addEventListener('click',function _rn(){
    if(typeof Notification!=='undefined'&&Notification.permission==='default')
      Notification.requestPermission();
  },{once:true});

  // ── Public API ────────────────────────────────────────────────────────────
  window.SupportWidget = {
    open:  () => _togglePanel(true),
    close: () => _togglePanel(false),
  };

})();