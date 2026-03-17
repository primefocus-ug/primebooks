/**
 * support_widget/static/support_widget/js/widget.js
 *
 * Self-contained support chat widget.
 * Loaded via {% include 'support_widget/widget_embed.html' %} in base.html.
 *
 * State machine:
 *   idle → onboarding (name) → onboarding (email) → faq → chatting → [call_consent → call]
 *
 * All API calls use relative paths so they work on any tenant subdomain.
 */

(function () {
  'use strict';

  // ── Config (injected by widget_embed.html via data attributes) ──────────
  const ROOT   = document.getElementById('sw-widget-root');
  if (!ROOT) return;

  const API_BASE    = ROOT.dataset.apiBase    || '/support';
  const WS_BASE     = ROOT.dataset.wsBase     || `ws${location.protocol === 'https:' ? 's' : ''}://${location.host}`;
  const BRAND_COLOR = ROOT.dataset.brandColor || '#6366f1';
  const GREETING    = ROOT.dataset.greeting   || "👋 Hi! How can we help?";
  const TITLE       = ROOT.dataset.title      || "Support";

  // ── Persistent state ─────────────────────────────────────────────────────
  const STORAGE_KEY = 'sw_session';
  let state = {
    open:          false,
    step:          'idle',       // idle | name | email | faq | chat | consent | call
    session_token: null,
    visitor_name:  '',
    visitor_email: '',
    call_room_id:  null,
    recording_notice: '',
  };

  function loadState() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '{}');
      Object.assign(state, saved);
    } catch (_) {}
  }

  function saveState() {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify({
      session_token:    state.session_token,
      visitor_name:     state.visitor_name,
      visitor_email:    state.visitor_email,
      call_room_id:     state.call_room_id,
      step:             state.step,
    }));
  }

  loadState();

  // ── WebSocket ─────────────────────────────────────────────────────────────
  let ws = null;

  function connectWS(token) {
    if (ws && ws.readyState < 2) return; // already open / connecting
    ws = new WebSocket(`${WS_BASE}/ws/support/${token}/`);
    ws.onopen    = () => { /* connected */ };
    ws.onmessage = onWSMessage;
    ws.onerror   = () => { /* will trigger onclose */ };
    ws.onclose   = () => {
      // Auto-reconnect as long as the session is active and panel is open
      if (state.session_token && state.step !== 'idle' && state.step !== 'resolved') {
        setTimeout(() => connectWS(state.session_token), 3000);
      }
    };
  }

  function onWSMessage(evt) {
    let data;
    try { data = JSON.parse(evt.data); } catch (_) { return; }

    switch (data.type) {
      case 'chat_message':
        appendMessage(data.sender, data.body, data.timestamp);
        break;
      case 'typing':
        showTyping(data.sender);
        break;
      case 'session_updated':
        state.step = 'faq';
        renderFAQ();
        break;
      case 'no_agent_available':
        appendMessage('system', data.message);
        // Re-enable the agent button so visitor can try again later
        if (agentBtn) { agentBtn.disabled = false; agentBtn.textContent = '💬 Talk to a human agent'; }
        break;
      case 'start_call':
        // Agent initiated a call — show consent banner in the widget
        renderCallConsent(data.call_room_id, data.recording_notice);
        break;
    }
  }

  function sendWS(payload) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(payload));
    }
  }

  // ── API helpers ───────────────────────────────────────────────────────────
  async function api(path, method = 'GET', body = null) {
    const opts = {
      method,
      headers: { 'Content-Type': 'application/json' },
    };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch(`${API_BASE}${path}`, opts);
    return res.json();
  }

  // ── DOM Build ─────────────────────────────────────────────────────────────
  ROOT.innerHTML = `
    <style>
      #sw-bubble {
        position: fixed; bottom: 24px; right: 24px; z-index: 9900;
        width: 56px; height: 56px; border-radius: 50%;
        background: ${BRAND_COLOR};
        box-shadow: 0 4px 20px rgba(0,0,0,0.25);
        cursor: pointer; border: none; outline: none;
        display: flex; align-items: center; justify-content: center;
        transition: transform .2s, box-shadow .2s;
        animation: sw-pulse 2.5s infinite;
      }
      #sw-bubble:hover { transform: scale(1.1); box-shadow: 0 6px 28px rgba(0,0,0,0.3); }
      @keyframes sw-pulse {
        0%,100% { box-shadow: 0 4px 20px rgba(0,0,0,.25), 0 0 0 0 ${BRAND_COLOR}55; }
        50%      { box-shadow: 0 4px 20px rgba(0,0,0,.25), 0 0 0 10px ${BRAND_COLOR}00; }
      }
      #sw-bubble svg { width: 26px; height: 26px; fill: #fff; }

      #sw-unread-badge {
        position: absolute; top: -4px; right: -4px;
        width: 18px; height: 18px; border-radius: 50%;
        background: #ef4444; color: #fff;
        font-size: 10px; font-weight: 700;
        display: none; align-items: center; justify-content: center;
        font-family: sans-serif;
      }

      #sw-panel {
        position: fixed; bottom: 92px; right: 24px; z-index: 9899;
        width: 360px; max-height: 560px;
        background: #fff; border-radius: 16px;
        box-shadow: 0 20px 60px rgba(0,0,0,0.18);
        display: none; flex-direction: column; overflow: hidden;
        font-family: 'Plus Jakarta Sans', system-ui, sans-serif;
        transition: opacity .2s, transform .2s;
      }
      #sw-panel.open { display: flex; animation: sw-slide-in .25s ease; }
      @keyframes sw-slide-in {
        from { opacity:0; transform: translateY(16px); }
        to   { opacity:1; transform: translateY(0); }
      }

      #sw-header {
        background: ${BRAND_COLOR}; color: #fff;
        padding: 14px 16px 12px; display: flex; align-items: center; gap: 10px;
        flex-shrink: 0;
      }
      #sw-header-title { font-weight: 700; font-size: .95rem; flex:1; }
      #sw-close-btn {
        background: none; border: none; cursor: pointer;
        color: rgba(255,255,255,.8); font-size: 1.2rem; line-height: 1;
        padding: 0 4px;
      }
      #sw-close-btn:hover { color: #fff; }

      #sw-body {
        flex: 1; overflow-y: auto; padding: 16px;
        display: flex; flex-direction: column; gap: 10px;
        background: #f8fafc; min-height: 0;
      }

      .sw-msg {
        max-width: 85%; padding: 9px 13px; border-radius: 12px;
        font-size: .85rem; line-height: 1.5; word-break: break-word;
      }
      .sw-msg.visitor  { background: ${BRAND_COLOR}; color: #fff; align-self: flex-end; border-bottom-right-radius: 4px; }
      .sw-msg.agent    { background: #fff; color: #111; align-self: flex-start; border: 1px solid #e5e7eb; border-bottom-left-radius: 4px; }
      .sw-msg.bot      { background: #fff; color: #111; align-self: flex-start; border: 1px solid #e5e7eb; border-bottom-left-radius: 4px; }
      .sw-msg.system   { background: #fef3c7; color: #92400e; align-self: center; font-size: .78rem; border-radius: 8px; text-align:center; max-width:100%; }

      .sw-faq-item {
        background: #fff; border: 1px solid #e5e7eb; border-radius: 10px;
        padding: 10px 12px; cursor: pointer; font-size: .83rem;
        color: #374151; transition: border-color .15s, background .15s;
      }
      .sw-faq-item:hover { border-color: ${BRAND_COLOR}; background: #f5f3ff; }
      .sw-faq-question { font-weight: 600; margin-bottom: 4px; }
      .sw-faq-answer   { color: #6b7280; display: none; margin-top: 6px; line-height: 1.5; }
      .sw-faq-item.expanded .sw-faq-answer { display: block; }

      .sw-form-group { display: flex; flex-direction: column; gap: 6px; }
      .sw-form-group label { font-size: .78rem; font-weight: 600; color: #374151; }
      .sw-form-group input {
        border: 1px solid #d1d5db; border-radius: 8px;
        padding: 8px 12px; font-size: .87rem; outline: none;
        transition: border-color .15s;
      }
      .sw-form-group input:focus { border-color: ${BRAND_COLOR}; }

      .sw-btn {
        padding: 9px 16px; border-radius: 8px; border: none; cursor: pointer;
        font-size: .85rem; font-weight: 700; transition: opacity .15s, transform .1s;
        font-family: inherit;
      }
      .sw-btn:hover { opacity: .88; transform: translateY(-1px); }
      .sw-btn-primary { background: ${BRAND_COLOR}; color: #fff; }
      .sw-btn-outline { background: transparent; border: 1px solid ${BRAND_COLOR}; color: ${BRAND_COLOR}; }
      .sw-btn-danger  { background: #ef4444; color: #fff; }
      .sw-btn-sm      { padding: 6px 12px; font-size: .78rem; }

      #sw-footer {
        display: flex; gap: 8px; padding: 10px 12px;
        border-top: 1px solid #e5e7eb; background: #fff; flex-shrink: 0;
      }
      #sw-input {
        flex: 1; border: 1px solid #d1d5db; border-radius: 8px;
        padding: 8px 12px; font-size: .87rem; outline: none; resize: none;
        font-family: inherit; max-height: 80px;
        transition: border-color .15s;
      }
      #sw-input:focus { border-color: ${BRAND_COLOR}; }
      #sw-send-btn {
        width: 38px; height: 38px; border-radius: 8px;
        background: ${BRAND_COLOR}; border: none; cursor: pointer;
        display: flex; align-items: center; justify-content: center;
        transition: opacity .15s;
      }
      #sw-send-btn svg { width: 16px; height: 16px; fill: #fff; }
      #sw-send-btn:hover { opacity: .85; }

      #sw-agent-btn-wrap { padding: 8px 12px; border-top: 1px solid #e5e7eb; background: #fff; }

      #sw-typing { font-size: .75rem; color: #9ca3af; min-height: 18px; padding: 0 4px; }

      .sw-consent-box {
        background: #fffbeb; border: 1px solid #fbbf24; border-radius: 10px;
        padding: 12px; font-size: .83rem; color: #78350f; line-height: 1.6;
      }
      .sw-consent-box strong { display: block; margin-bottom: 4px; }
      .sw-call-link {
        display: flex; align-items: center; gap: 8px;
        background: #f0fdf4; border: 1px solid #86efac;
        border-radius: 10px; padding: 12px; text-decoration: none;
        color: #166534; font-weight: 600; font-size: .87rem;
        transition: background .15s;
      }
      .sw-call-link:hover { background: #dcfce7; }
      .sw-call-link svg { width: 20px; height: 20px; fill: #16a34a; flex-shrink:0; }

      @media (max-width: 420px) {
        #sw-panel { width: calc(100vw - 24px); right: 12px; bottom: 80px; }
      }
    </style>

    <!-- Bubble -->
    <button id="sw-bubble" title="Chat with support" aria-label="Open support chat">
      <svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
        <path d="M20 2H4a2 2 0 00-2 2v18l4-4h14a2 2 0 002-2V4a2 2 0 00-2-2z"/>
      </svg>
      <span id="sw-unread-badge"></span>
    </button>

    <!-- Panel -->
    <div id="sw-panel" role="dialog" aria-label="Support chat">
      <div id="sw-header">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="rgba(255,255,255,.9)">
          <path d="M20 2H4a2 2 0 00-2 2v18l4-4h14a2 2 0 002-2V4a2 2 0 00-2-2z"/>
        </svg>
        <span id="sw-header-title">${TITLE}</span>
        <button id="sw-close-btn" aria-label="Close chat">✕</button>
      </div>

      <div id="sw-body"></div>
      <div id="sw-typing"></div>

      <!-- Agent escalation button -->
      <div id="sw-agent-btn-wrap" style="display:none;">
        <button class="sw-btn sw-btn-outline" style="width:100%" id="sw-agent-btn">
          💬 Talk to a human agent
        </button>
      </div>

      <!-- Chat input footer (hidden until chat stage) -->
      <div id="sw-footer" style="display:none;">
        <textarea id="sw-input" placeholder="Type a message…" rows="1"></textarea>
        <button id="sw-send-btn" aria-label="Send">
          <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
    </div>
  `;

  // ── Element refs ──────────────────────────────────────────────────────────
  const bubble    = document.getElementById('sw-bubble');
  const panel     = document.getElementById('sw-panel');
  const body      = document.getElementById('sw-body');
  const footer    = document.getElementById('sw-footer');
  const input     = document.getElementById('sw-input');
  const sendBtn   = document.getElementById('sw-send-btn');
  const closeBtn  = document.getElementById('sw-close-btn');
  const agentWrap = document.getElementById('sw-agent-btn-wrap');
  const agentBtn  = document.getElementById('sw-agent-btn');
  const typingEl  = document.getElementById('sw-typing');
  const badge     = document.getElementById('sw-unread-badge');

  let unreadCount = 0;
  let typingTimer = null;

  // ── Open / close ──────────────────────────────────────────────────────────
  bubble.addEventListener('click', togglePanel);
  closeBtn.addEventListener('click', () => togglePanel(false));

  function togglePanel(forceOpen) {
    state.open = (forceOpen === true || forceOpen === false) ? forceOpen : !state.open;
    panel.classList.toggle('open', state.open);
    if (state.open) {
      unreadCount = 0;
      badge.style.display = 'none';
      if (state.step === 'idle') startWidget();
    }
  }

  // ── Initialise ────────────────────────────────────────────────────────────
  async function startWidget() {
    if (state.session_token) {
      // Restore existing session
      connectWS(state.session_token);
      if (state.step === 'faq')   { renderFAQ(); return; }
      if (state.step === 'chat')  { renderChat(); return; }
      if (state.step === 'consent' || state.step === 'call') { renderChat(); return; }
    }

    // New session
    appendMessage('bot', GREETING);
    const res = await api('/session/', 'POST', {
      referrer_url: location.href,
      user_agent:   navigator.userAgent,
    });
    if (res.ok) {
      state.session_token = res.session_token;
      saveState();
      connectWS(res.session_token);
      askName();
    }
  }

  // ── Onboarding steps ──────────────────────────────────────────────────────
  function askName() {
    state.step = 'name';
    appendForm('name', "What's your name?", 'Your name', (val) => {
      state.visitor_name = val;
      state.step = 'email';
      saveState();
      askEmail();
    });
  }

  function askEmail() {
    appendMessage('bot', `Nice to meet you, ${state.visitor_name}! 😊 What's your email so we can follow up if needed?`);
    appendForm('email', null, 'your@email.com', (val) => {
      state.visitor_email = val;
      saveState();
      sendWS({ type: 'session_update', name: state.visitor_name, email: state.visitor_email });
      // Also persist via REST in case WS drops
      api(`/session/${state.session_token}/`, 'POST', {
        name: state.visitor_name, email: state.visitor_email,
      });
      state.step = 'faq';
      renderFAQ();
    }, 'email');
  }

  async function renderFAQ() {
    state.step = 'faq';
    saveState();
    appendMessage('bot', `Thanks ${state.visitor_name}! Here are some common topics — or just ask me anything below.`);
    agentWrap.style.display = 'block';
    footer.style.display    = 'flex';

    // Fetch default FAQs
    const res = await api('/faq/');
    if (res.results && res.results.length) {
      res.results.forEach(faq => appendFAQ(faq));
    }
  }

  function renderChat() {
    agentWrap.style.display = 'block';
    footer.style.display    = 'flex';
  }

  // ── DOM helpers ───────────────────────────────────────────────────────────
  function appendMessage(sender, text, timestamp) {
    const div = document.createElement('div');
    div.className = `sw-msg ${sender}`;
    div.textContent = text;
    body.appendChild(div);
    scrollBottom();
    if (!state.open) {
      unreadCount++;
      badge.textContent = unreadCount > 9 ? '9+' : unreadCount;
      badge.style.display = 'flex';
    }
  }

  function appendForm(fieldType, labelText, placeholder, onSubmit, inputType = 'text') {
    const wrap = document.createElement('div');
    wrap.className = 'sw-form-group';
    wrap.innerHTML = `
      ${labelText ? `<label>${labelText}</label>` : ''}
      <input type="${inputType}" placeholder="${placeholder}" />
      <button class="sw-btn sw-btn-primary">Continue →</button>
    `;
    const inp = wrap.querySelector('input');
    const btn = wrap.querySelector('button');
    btn.addEventListener('click', () => {
      const val = inp.value.trim();
      if (!val) { inp.focus(); return; }
      wrap.remove();
      onSubmit(val);
    });
    inp.addEventListener('keydown', e => { if (e.key === 'Enter') btn.click(); });
    body.appendChild(wrap);
    scrollBottom();
    setTimeout(() => inp.focus(), 100);
  }

  function appendFAQ(faq) {
    const div = document.createElement('div');
    div.className = 'sw-faq-item';
    div.innerHTML = `
      <div class="sw-faq-question">${faq.question}</div>
      <div class="sw-faq-answer">${faq.answer}</div>
    `;
    div.addEventListener('click', () => div.classList.toggle('expanded'));
    body.appendChild(div);
    scrollBottom();
  }

  function scrollBottom() {
    body.scrollTop = body.scrollHeight;
  }

  function showTyping(sender) {
    if (sender === 'visitor') return; // don't show visitor's own typing
    typingEl.textContent = 'Agent is typing…';
    clearTimeout(typingTimer);
    typingTimer = setTimeout(() => { typingEl.textContent = ''; }, 2500);
  }

  // ── Chat input ────────────────────────────────────────────────────────────
  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
    else sendWS({ type: 'typing', sender: 'visitor' });
  });

  async function sendMessage() {
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    appendMessage('visitor', text);
    sendWS({ type: 'chat_message', sender: 'visitor', body: text });

    // If still in FAQ stage, also search FAQs
    if (state.step === 'faq') {
      const res = await api(`/faq/?q=${encodeURIComponent(text)}`);
      if (res.results && res.results.length) {
        appendMessage('bot', "Here are some articles that might help:");
        res.results.forEach(f => appendFAQ(f));
      }
    }
    if (state.step === 'faq') { state.step = 'chat'; saveState(); }
  }

  // ── Agent escalation ──────────────────────────────────────────────────────
  agentBtn.addEventListener('click', () => {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      // WS not ready — reconnect first then retry
      if (state.session_token) {
        connectWS(state.session_token);
        setTimeout(() => agentBtn.click(), 1500);
      }
      return;
    }
    agentBtn.disabled = true;
    agentBtn.textContent = '⏳ Connecting to an agent…';
    sendWS({ type: 'request_agent' });
    state.step = 'chat';
    saveState();
    // Safety timeout: re-enable button if no response in 10s
    setTimeout(() => {
      if (agentBtn.disabled) {
        agentBtn.disabled = false;
        agentBtn.textContent = '💬 Talk to a human agent';
      }
    }, 10000);
  });

  // ── WebRTC call initiation ────────────────────────────────────────────────
  // Exposed so the agent dashboard can trigger the call link being sent to the visitor.
  // The visitor widget listens for a 'chat_message' of type system with a call link.
  // When a call_room_id arrives via WS, render the consent + call button.
  function renderCallConsent(callRoomId, notice) {
    state.call_room_id    = callRoomId;
    state.recording_notice = notice;
    state.step = 'consent';
    saveState();

    const box = document.createElement('div');
    box.className = 'sw-consent-box';
    box.innerHTML = `<strong>📞 Voice Call</strong>${notice}`;
    body.appendChild(box);

    const btnWrap = document.createElement('div');
    btnWrap.style.cssText = 'display:flex;gap:8px;';
    btnWrap.innerHTML = `
      <button class="sw-btn sw-btn-primary" id="sw-accept-call">Accept &amp; Join Call</button>
      <button class="sw-btn sw-btn-outline" id="sw-decline-call">Decline</button>
    `;
    body.appendChild(btnWrap);
    scrollBottom();

    document.getElementById('sw-accept-call').onclick = () => {
      btnWrap.remove(); box.remove();
      state.step = 'call'; saveState();
      window.open(`/support/call/${callRoomId}/?role=visitor`, '_blank',
        'width=520,height=400,toolbar=no,menubar=no');
    };
    document.getElementById('sw-decline-call').onclick = () => {
      btnWrap.remove(); box.remove();
      state.step = 'chat'; saveState();
    };
  }

  // Expose for external use (e.g. auto-open from notification)
  window.SupportWidget = {
    open:  () => togglePanel(true),
    close: () => togglePanel(false),
  };

})();