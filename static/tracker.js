/**
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║  PrimeBooks — Universal Tracker  (tracker.js)                   ║
 * ║                                                                  ║
 * ║  Zero dependencies. Include once in base.html.                  ║
 * ║                                                                  ║
 * ║  INCLUDE IN BASE TEMPLATE (before </body>):                     ║
 * ║    <script src="{% static 'js/tracker.js' %}"></script>         ║
 * ║                                                                  ║
 * ║  ADD TO ANY BUTTON:                                              ║
 * ║    <button data-track="product" data-id="{{ product.pk }}"      ║
 * ║            data-label="{{ product.name }}">Track</button>        ║
 * ║                                                                  ║
 * ║  THEME                                                           ║
 * ║    Reads your existing [data-theme='dark'] switcher on <html>.  ║
 * ║    Light mode = default.  Dark = [data-theme='dark'].           ║
 * ║    Theme switches instantly — no JS needed, just CSS vars.      ║
 * ║                                                                  ║
 * ║  "VIEW FULL PAGE" opens a full-screen modal overlay showing     ║
 * ║    the same data in a 2-column layout.                          ║
 * ╚══════════════════════════════════════════════════════════════════╝
 */

(function () {
  "use strict";

  const API_BASE    = "/api/track/";
  const CSRF_COOKIE = "csrftoken";

  /* ═══════════════════════════════════════════════════════════════════
     CSS
     Light theme is the default.
     [data-theme='dark'] on <html> overrides all colour tokens.
     Works instantly with your existing theme switcher — zero JS.
  ═══════════════════════════════════════════════════════════════════ */

  const CSS = `
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,300;0,400;0,500;1,300&family=Syne:wght@600;700;800&display=swap');

    /* ── LIGHT (default) ────────────────────────────────────────────── */
    :root {
      --trk-bg:               #ffffff;
      --trk-s1:               #f8fafc;
      --trk-s2:               #f1f5f9;
      --trk-s3:               #e9eef6;
      --trk-bd:               #dde3ec;
      --trk-bd2:              #cbd5e1;
      --trk-text:             #0f172a;
      --trk-sub:              #475569;
      --trk-dim:              #94a3b8;
      --trk-overlay:          rgba(15,23,42,0.45);
      --trk-shadow:           rgba(15,23,42,0.18);
      --trk-table-zebra:      rgba(241,245,249,0.7);
      --trk-diff-from-bg:     #fef2f2;
      --trk-diff-from-color:  #dc2626;
      --trk-diff-from-bd:     #fecaca;
      --trk-diff-to-bg:       #f0fdf4;
      --trk-diff-to-color:    #16a34a;
      --trk-diff-to-bd:       #bbf7d0;
      --trk-td-last:          #16a34a;
      --trk-error-color:      #dc2626;
      --trk-mono:             'DM Mono', monospace;
      --trk-display:          'Syne', sans-serif;
    }

    /* ── DARK — your [data-theme='dark'] switcher triggers this ─────── */
    [data-theme='dark'] {
      --trk-bg:               #060f1c;
      --trk-s1:               #0a1628;
      --trk-s2:               #0e1d32;
      --trk-s3:               #12233b;
      --trk-bd:               #172338;
      --trk-bd2:              #1e2f45;
      --trk-text:             #ddeaf7;
      --trk-sub:              #4d6a87;
      --trk-dim:              #243550;
      --trk-overlay:          rgba(2,8,20,0.82);
      --trk-shadow:           rgba(0,0,0,0.65);
      --trk-table-zebra:      rgba(14,29,50,0.4);
      --trk-diff-from-bg:     #240808;
      --trk-diff-from-color:  #f87171;
      --trk-diff-from-bd:     rgba(248,113,113,0.15);
      --trk-diff-to-bg:       #042214;
      --trk-diff-to-color:    #4ade80;
      --trk-diff-to-bd:       rgba(74,222,128,0.15);
      --trk-td-last:          #4ade80;
      --trk-error-color:      #f87171;
    }

    /* ── OVERLAY ────────────────────────────────────────────────────── */
    #trk-overlay {
      position:fixed; inset:0; z-index:9998;
      background:var(--trk-overlay);
      backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px);
      opacity:0; transition:opacity .25s ease; pointer-events:none;
    }
    #trk-overlay.trk-visible { opacity:1; pointer-events:all; }

    /* ── DRAWER PANEL ───────────────────────────────────────────────── */
    #trk-panel {
      position:fixed; top:0; right:0; bottom:0;
      width:min(600px,100vw); z-index:9999;
      background:var(--trk-bg);
      border-left:1px solid var(--trk-bd2);
      box-shadow:-24px 0 80px var(--trk-shadow);
      display:flex; flex-direction:column;
      transform:translateX(100%);
      transition:transform .32s cubic-bezier(.22,.68,0,1.08);
      font-family:var(--trk-display);
    }
    #trk-panel.trk-visible { transform:translateX(0); }

    #trk-panel-accent {
      height:2px; flex-shrink:0;
      background:linear-gradient(90deg,transparent,var(--trk-accent,#0ea5e9),transparent);
    }

    /* ── HEADER ─────────────────────────────────────────────────────── */
    #trk-header {
      padding:18px 24px 16px;
      border-bottom:1px solid var(--trk-bd2); flex-shrink:0;
    }
    #trk-chip-row {
      display:flex; align-items:center;
      justify-content:space-between; margin-bottom:12px;
    }
    #trk-chip { display:flex; align-items:center; gap:7px; }
    #trk-chip-icon { font-size:14px; }
    #trk-chip-label {
      font-size:9px; font-family:var(--trk-mono);
      letter-spacing:.18em; text-transform:uppercase;
    }
    #trk-chip-id {
      font-size:10px; font-family:var(--trk-mono);
      color:var(--trk-sub); margin-left:4px;
    }
    #trk-close-btn {
      width:30px; height:30px; border-radius:7px;
      border:1px solid var(--trk-bd2); background:transparent;
      color:var(--trk-sub); font-size:18px; cursor:pointer;
      display:flex; align-items:center; justify-content:center;
      transition:all .14s; line-height:1;
    }
    #trk-close-btn:hover { background:var(--trk-s3); color:var(--trk-text); }

    #trk-title-row { display:flex; align-items:flex-start; gap:10px; margin-bottom:4px; }
    #trk-title {
      flex:1; font-size:21px; font-weight:800; color:var(--trk-text);
      letter-spacing:-.03em; line-height:1.2;
    }
    #trk-badge {
      font-size:10px; padding:3px 11px; border-radius:20px;
      font-family:var(--trk-mono); font-weight:600;
      flex-shrink:0; margin-top:3px;
    }
    #trk-subtitle {
      font-size:12px; color:var(--trk-sub);
      font-family:var(--trk-mono); margin-bottom:14px;
    }

    #trk-stats {
      display:grid; gap:8px;
      grid-template-columns:repeat(auto-fit,minmax(110px,1fr));
    }
    .trk-stat {
      background:var(--trk-s2); border:1px solid var(--trk-bd2);
      border-radius:8px; padding:8px 11px; transition:border-color .15s;
    }
    .trk-stat:hover { border-color:var(--trk-stat-color,var(--trk-bd2)); }
    .trk-stat-label {
      font-size:9px; color:var(--trk-sub); font-family:var(--trk-mono);
      letter-spacing:.06em; margin-bottom:4px;
    }
    .trk-stat-value { font-size:12px; font-weight:700; font-family:var(--trk-mono); line-height:1.2; }

    /* ── BODY ───────────────────────────────────────────────────────── */
    #trk-body {
      flex:1; overflow-y:auto; padding:22px 24px;
      scrollbar-width:thin; scrollbar-color:var(--trk-bd2) transparent;
    }
    #trk-body::-webkit-scrollbar { width:3px; }
    #trk-body::-webkit-scrollbar-thumb { background:var(--trk-bd2); border-radius:3px; }

    /* ── FOOTER ─────────────────────────────────────────────────────── */
    #trk-footer {
      padding:12px 24px; border-top:1px solid var(--trk-bd2);
      flex-shrink:0; display:flex; gap:8px; align-items:center;
    }
    #trk-footer-meta {
      flex:1; font-size:10px; color:var(--trk-dim); font-family:var(--trk-mono);
    }
    #trk-expand-btn {
      padding:7px 15px; border-radius:7px;
      border:1px solid var(--trk-bd2); background:var(--trk-s2);
      color:var(--trk-sub); font-size:11px; font-family:var(--trk-mono);
      cursor:pointer; transition:all .13s;
    }
    #trk-expand-btn:hover { color:var(--trk-text); background:var(--trk-s3); }
    #trk-close-link {
      padding:7px 18px; border-radius:7px;
      font-size:11px; font-family:var(--trk-mono);
      cursor:pointer; transition:all .13s; border:1px solid transparent;
    }

    /* ═══════════════════════════════════════════════════════════════
       MODAL  — "View full page"
       A centred overlay that shows the same data in a 2-col layout.
    ═══════════════════════════════════════════════════════════════ */
    #trk-modal-overlay {
      position:fixed; inset:0; z-index:10000;
      background:var(--trk-overlay);
      backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px);
      display:flex; align-items:center; justify-content:center; padding:24px;
      opacity:0; pointer-events:none; transition:opacity .22s ease;
    }
    #trk-modal-overlay.trk-visible { opacity:1; pointer-events:all; }

    #trk-modal {
      background:var(--trk-bg);
      border:1px solid var(--trk-bd2);
      border-radius:14px;
      box-shadow:0 32px 100px var(--trk-shadow);
      width:min(940px,100%); max-height:calc(100vh - 48px);
      display:flex; flex-direction:column;
      transform:scale(.96) translateY(8px);
      transition:transform .24s cubic-bezier(.22,.68,0,1.08);
      font-family:var(--trk-display); overflow:hidden;
    }
    #trk-modal-overlay.trk-visible #trk-modal { transform:scale(1) translateY(0); }

    #trk-modal-accent {
      height:3px; flex-shrink:0;
      background:linear-gradient(90deg,transparent,var(--trk-accent,#0ea5e9),transparent);
    }

    #trk-modal-header {
      padding:20px 28px 18px;
      border-bottom:1px solid var(--trk-bd2); flex-shrink:0;
    }
    #trk-modal-chip-row {
      display:flex; align-items:center;
      justify-content:space-between; margin-bottom:14px;
    }
    #trk-modal-chip { display:flex; align-items:center; gap:8px; }
    #trk-modal-chip-icon  { font-size:15px; }
    #trk-modal-chip-label {
      font-size:9px; font-family:var(--trk-mono);
      letter-spacing:.18em; text-transform:uppercase;
    }
    #trk-modal-chip-id {
      font-size:10px; font-family:var(--trk-mono);
      color:var(--trk-sub); margin-left:4px;
    }
    #trk-modal-close-btn {
      width:32px; height:32px; border-radius:8px;
      border:1px solid var(--trk-bd2); background:transparent;
      color:var(--trk-sub); font-size:19px; cursor:pointer;
      display:flex; align-items:center; justify-content:center;
      transition:all .14s; line-height:1;
    }
    #trk-modal-close-btn:hover { background:var(--trk-s3); color:var(--trk-text); }

    #trk-modal-title-row { display:flex; align-items:flex-start; gap:10px; margin-bottom:5px; }
    #trk-modal-title {
      flex:1; font-size:26px; font-weight:800; color:var(--trk-text);
      letter-spacing:-.03em; line-height:1.2;
    }
    #trk-modal-badge {
      font-size:10px; padding:3px 12px; border-radius:20px;
      font-family:var(--trk-mono); font-weight:600;
      flex-shrink:0; margin-top:5px;
    }
    #trk-modal-subtitle {
      font-size:12px; color:var(--trk-sub);
      font-family:var(--trk-mono); margin-bottom:16px;
    }
    #trk-modal-stats {
      display:grid; gap:10px;
      grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
    }

    /* 2-column body */
    #trk-modal-body {
      flex:1; overflow-y:auto; padding:28px;
      display:grid; grid-template-columns:1fr 1fr; gap:0 32px; align-content:start;
      scrollbar-width:thin; scrollbar-color:var(--trk-bd2) transparent;
    }
    #trk-modal-body::-webkit-scrollbar { width:3px; }
    #trk-modal-body::-webkit-scrollbar-thumb { background:var(--trk-bd2); }
    /* Full-width items in modal */
    #trk-modal-body > .trk-efris    { grid-column:1/-1; }
    #trk-modal-body > .trk-wide     { grid-column:1/-1; }

    #trk-modal-footer {
      padding:13px 28px; border-top:1px solid var(--trk-bd2);
      flex-shrink:0; display:flex; justify-content:flex-end; gap:8px;
    }
    #trk-modal-close-link {
      padding:8px 22px; border-radius:8px; border:1px solid transparent;
      font-size:12px; font-family:var(--trk-mono); cursor:pointer; transition:all .13s;
    }

    /* ── EFRIS BLOCK ────────────────────────────────────────────────── */
    .trk-efris {
      display:flex; align-items:flex-start; gap:12px;
      padding:12px 16px; border-radius:9px; margin-bottom:28px;
    }
    .trk-efris-icon   { font-size:20px; line-height:1; margin-top:1px; }
    .trk-efris-status { font-size:10px; font-family:var(--trk-mono); font-weight:700; letter-spacing:.08em; margin-bottom:3px; }
    .trk-efris-ref    { font-size:11px; font-family:var(--trk-mono); opacity:.8; margin-bottom:2px; }
    .trk-efris-date   { font-size:10.5px; color:var(--trk-sub); font-family:var(--trk-mono); }

    /* ── SECTION ────────────────────────────────────────────────────── */
    .trk-section { margin-bottom:28px; }
    .trk-sec-header { display:flex; align-items:center; gap:8px; margin-bottom:16px; }
    .trk-sec-title {
      font-size:9px; font-family:var(--trk-mono); color:var(--trk-dim);
      text-transform:uppercase; letter-spacing:.14em; white-space:nowrap;
    }
    .trk-sec-count {
      font-size:9px; background:var(--trk-s3); color:var(--trk-sub);
      border:1px solid var(--trk-bd2); padding:1px 7px; border-radius:20px;
      font-family:var(--trk-mono);
    }
    .trk-sec-line { flex:1; height:1px; background:var(--trk-bd2); }

    /* ── TIMELINE ───────────────────────────────────────────────────── */
    .trk-timeline { position:relative; }
    .trk-tl-spine {
      position:absolute; left:14px; top:8px; bottom:4px;
      width:1px; background:var(--trk-bd2);
    }
    .trk-tl-item { display:flex; gap:14px; padding-left:36px; position:relative; margin-bottom:20px; }
    .trk-tl-item:last-child { margin-bottom:0; }
    .trk-tl-dot {
      position:absolute; left:7px; top:3px;
      width:15px; height:15px; border-radius:50%;
      display:flex; align-items:center; justify-content:center; flex-shrink:0;
    }
    .trk-tl-dot-inner { width:5px; height:5px; border-radius:50%; }
    .trk-tl-content { flex:1; min-width:0; }
    .trk-tl-toprow { display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin-bottom:4px; }
    .trk-tag { font-size:9px; padding:2px 8px; border-radius:4px; font-family:var(--trk-mono); font-weight:600; letter-spacing:.06em; }
    .trk-tl-sub   { font-size:11px; color:var(--trk-sub); font-family:var(--trk-mono); }
    .trk-tl-qty   { margin-left:auto; font-family:var(--trk-mono); font-size:13px; font-weight:700; }
    .trk-tl-label { font-size:12.5px; color:var(--trk-text); font-weight:600; margin-bottom:3px; line-height:1.3; }
    .trk-tl-note  { font-size:11.5px; color:var(--trk-sub); margin-bottom:4px; line-height:1.4; }
    .trk-tl-meta  { display:flex; align-items:center; gap:7px; flex-wrap:wrap; font-size:10.5px; color:var(--trk-dim); font-family:var(--trk-mono); }
    .trk-tl-running { margin-left:auto; color:var(--trk-sub); }
    .trk-dot-sep  { color:var(--trk-bd2); }

    /* ── AUDIT ──────────────────────────────────────────────────────── */
    .trk-audit-item { display:flex; gap:12px; margin-bottom:16px; align-items:flex-start; }
    .trk-audit-item:last-child { margin-bottom:0; }
    .trk-sev-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; margin-top:5px; }
    .trk-audit-desc { font-size:12.5px; color:var(--trk-text); font-weight:500; margin-bottom:4px; line-height:1.35; }
    .trk-diff-row { display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-bottom:5px; }
    .trk-diff-from {
      font-size:10px; font-family:var(--trk-mono); padding:2px 7px; border-radius:4px;
      background:var(--trk-diff-from-bg); color:var(--trk-diff-from-color); border:1px solid var(--trk-diff-from-bd);
    }
    .trk-diff-arrow { color:var(--trk-dim); font-size:11px; }
    .trk-diff-to {
      font-size:10px; font-family:var(--trk-mono); padding:2px 7px; border-radius:4px;
      background:var(--trk-diff-to-bg); color:var(--trk-diff-to-color); border:1px solid var(--trk-diff-to-bd);
    }
    .trk-audit-meta { font-size:10.5px; color:var(--trk-dim); font-family:var(--trk-mono); }

    /* ── TABLE ──────────────────────────────────────────────────────── */
    .trk-table-wrap { border:1px solid var(--trk-bd2); border-radius:9px; overflow:hidden; }
    .trk-table { width:100%; border-collapse:collapse; font-size:12px; }
    .trk-table thead tr { background:var(--trk-s3); border-bottom:1px solid var(--trk-bd2); }
    .trk-table th {
      padding:9px 13px; font-size:9px; color:var(--trk-dim);
      font-family:var(--trk-mono); font-weight:600;
      letter-spacing:.1em; text-transform:uppercase;
    }
    .trk-table th:first-child { text-align:left; }
    .trk-table th:not(:first-child) { text-align:right; }
    .trk-table tbody tr { border-bottom:1px solid var(--trk-bd); }
    .trk-table tbody tr:last-child { border-bottom:none; }
    .trk-table tbody tr:nth-child(even) { background:var(--trk-table-zebra); }
    .trk-table td { padding:11px 13px; color:var(--trk-sub); font-family:var(--trk-mono); }
    .trk-table td:first-child { text-align:left; color:var(--trk-text); font-weight:600; font-family:var(--trk-display); }
    .trk-table td:not(:first-child) { text-align:right; }
    .trk-table td.trk-td-last { color:var(--trk-td-last); font-weight:700; }

    /* ── KEYVALUE ───────────────────────────────────────────────────── */
    .trk-kv-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .trk-kv-item { background:var(--trk-s2); border:1px solid var(--trk-bd2); border-radius:8px; padding:10px 12px; }
    .trk-kv-label { font-size:9px; color:var(--trk-sub); font-family:var(--trk-mono); letter-spacing:.06em; margin-bottom:4px; }
    .trk-kv-value { font-size:12.5px; color:var(--trk-text); font-weight:600; }

    /* ── SKELETON ───────────────────────────────────────────────────── */
    @keyframes trk-pulse { 0%,100%{opacity:.35} 50%{opacity:.75} }
    .trk-skel { border-radius:5px; background:var(--trk-s3); animation:trk-pulse 1.4s ease infinite; }
    .trk-skel-row { display:flex; gap:10px; margin-bottom:20px; }
    .trk-skel-circ { width:15px; height:15px; border-radius:50%; flex-shrink:0; }

    /* ── ERROR ──────────────────────────────────────────────────────── */
    .trk-error-box { text-align:center; padding:40px 20px; }
    .trk-error-icon { font-size:32px; margin-bottom:12px; }
    .trk-error-msg  { font-size:13px; color:var(--trk-error-color); margin-bottom:6px; }
    .trk-error-det  { font-size:11px; color:var(--trk-sub); font-family:var(--trk-mono); }

    /* ── TRACK BUTTONS (auto-styled) ────────────────────────────────── */
    [data-track] {
      display:inline-flex; align-items:center; gap:5px;
      padding:3px 10px; border-radius:6px; cursor:pointer;
      font-size:11px; font-family:var(--trk-mono);
      border:1px solid var(--trk-bd2); background:transparent;
      color:var(--trk-sub); transition:all .14s;
      white-space:nowrap; user-select:none;
    }
    [data-track]:hover {
      border-color:var(--trk-accent,#0ea5e9);
      color:var(--trk-accent,#0ea5e9);
      background:color-mix(in srgb,var(--trk-accent,#0ea5e9) 8%,transparent);
    }
    [data-track]::before { content:attr(data-track-icon,'◎'); font-size:9px; }
  `;

  /* ═══════════════════════════════════════════════
     COLOUR MAPS
  ═══════════════════════════════════════════════ */

  const TYPE_COLORS = {
    product:"#0ea5e9", sale:"#22c55e",   invoice:"#8b5cf6",
    expense:"#f97316", user:"#ec4899",   customer:"#06b6d4",
    budget: "#84cc16", transfer:"#10b981",purchase:"#eab308",
    payment:"#38bdf8", report:"#64748b",
  };
  const TYPE_ICONS = {
    product:"⬡", sale:"◈",    invoice:"◇",  expense:"◉",
    user:"◎",    customer:"⊙", budget:"◑",   transfer:"⇄",
    purchase:"↓", payment:"◆", report:"▤",
  };

  const TAG_COLORS = {
    PURCHASE:"#22c55e",SALE:"#0ea5e9",RETURN:"#8b5cf6",VOID:"#ef4444",
    REFUND:"#f97316",ADJUSTMENT:"#eab308",TRANSFER_IN:"#10b981",TRANSFER_OUT:"#64748b",
    created:"#22c55e",updated:"#0ea5e9",deleted:"#ef4444",approved:"#22c55e",
    rejected:"#ef4444",paid:"#22c55e",sent:"#38bdf8",cancelled:"#ef4444",
    efris:"#8b5cf6",login:"#ec4899",locked:"#ef4444",
    login_success:"#22c55e",login_failed:"#ef4444",
  };
  const tagColor = (t) => TAG_COLORS[t] || TAG_COLORS[(t||"").toUpperCase()] || "#64748b";

  /* Badge colours split by theme */
  const BADGE_LIGHT = {
    green:  {bg:"#dcfce7",color:"#15803d",bd:"#86efac"},
    blue:   {bg:"#dbeafe",color:"#1d4ed8",bd:"#93c5fd"},
    purple: {bg:"#ede9fe",color:"#7c3aed",bd:"#c4b5fd"},
    red:    {bg:"#fee2e2",color:"#dc2626",bd:"#fca5a5"},
    yellow: {bg:"#fefce8",color:"#a16207",bd:"#fde047"},
    dim:    {bg:"#f1f5f9",color:"#475569",bd:"#cbd5e1"},
  };
  const BADGE_DARK = {
    green:  {bg:"#042214",color:"#4ade80",bd:"rgba(74,222,128,.18)"},
    blue:   {bg:"#051830",color:"#38bdf8",bd:"rgba(56,189,248,.18)"},
    purple: {bg:"#180d35",color:"#a78bfa",bd:"rgba(167,139,250,.18)"},
    red:    {bg:"#240808",color:"#f87171",bd:"rgba(248,113,113,.18)"},
    yellow: {bg:"#241c00",color:"#facc15",bd:"rgba(250,204,21,.18)"},
    dim:    {bg:"#0a1628",color:"#4d6a87",bd:"#172338"},
  };
  function badgeStyle(c) {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    return (dark ? BADGE_DARK : BADGE_LIGHT)[c] || (dark ? BADGE_DARK : BADGE_LIGHT).dim;
  }

  const SEV_COLORS = {
    info:"#0ea5e9",success:"#22c55e",warning:"#eab308",error:"#ef4444",critical:"#dc2626",
  };
  const sevColor = (s) => SEV_COLORS[s] || SEV_COLORS.info;

  const STAT_COLORS = {
    green:"#22c55e",blue:"#0ea5e9",purple:"#8b5cf6",
    red:"#ef4444",yellow:"#eab308",dim:"#64748b",
  };
  const statColor = (c) => STAT_COLORS[c] || STAT_COLORS.dim;

  /* EFRIS config split by theme */
  const EFRIS_LIGHT = {
    fiscalized:{label:"Fiscalized",  color:"#7c3aed",bg:"#ede9fe",icon:"⬡"},
    pending:   {label:"Pending Sync",color:"#a16207",bg:"#fefce8",icon:"◌"},
    failed:    {label:"Sync Failed", color:"#dc2626",bg:"#fee2e2",icon:"⚠"},
  };
  const EFRIS_DARK = {
    fiscalized:{label:"Fiscalized",  color:"#a78bfa",bg:"#180d35",icon:"⬡"},
    pending:   {label:"Pending Sync",color:"#facc15",bg:"#241c00",icon:"◌"},
    failed:    {label:"Sync Failed", color:"#f87171",bg:"#240808",icon:"⚠"},
  };
  function efrisCfg(status) {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    return (dark ? EFRIS_DARK : EFRIS_LIGHT)[status] || null;
  }

  /* ═══════════════════════════════════════════════
     UTILITIES
  ═══════════════════════════════════════════════ */

  function fmtDate(d) {
    if (!d) return "—";
    try {
      const dt = new Date(d);
      return dt.toLocaleDateString("en-GB", {day:"2-digit",month:"short",year:"numeric"})
           + "  " + dt.toLocaleTimeString("en-GB", {hour:"2-digit",minute:"2-digit"});
    } catch { return d; }
  }

  function getCookie(name) {
    const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return m ? decodeURIComponent(m[1]) : "";
  }

  function h(tag, attrs={}, ...children) {
    const el = document.createElement(tag);
    for (const [k,v] of Object.entries(attrs)) {
      if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
      else el.setAttribute(k, v);
    }
    for (const c of children.flat(Infinity)) {
      if (c == null) continue;
      el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return el;
  }

  /* ═══════════════════════════════════════════════
     DOM BUILD
  ═══════════════════════════════════════════════ */

  function injectStyles() {
    if (document.getElementById("trk-styles")) return;
    const s = document.createElement("style");
    s.id = "trk-styles"; s.textContent = CSS;
    document.head.appendChild(s);
  }

  function buildShell() {
    if (document.getElementById("trk-panel")) return;

    /* Drawer overlay */
    const overlay = h("div", {id:"trk-overlay"});
    overlay.addEventListener("click", closeTracker);

    /* Drawer panel */
    const panel = h("div", {id:"trk-panel"},
      h("div", {id:"trk-panel-accent"}),
      h("div", {id:"trk-header"},
        h("div", {id:"trk-chip-row"},
          h("div", {id:"trk-chip"},
            h("span", {id:"trk-chip-icon"}),
            h("span", {id:"trk-chip-label"}),
            h("span", {id:"trk-chip-id"}),
          ),
          h("button", {id:"trk-close-btn","aria-label":"Close tracker",onclick:closeTracker}, "×"),
        ),
        h("div", {id:"trk-title-row"},
          h("h2",  {id:"trk-title"}, "Loading…"),
          h("span",{id:"trk-badge"}),
        ),
        h("div", {id:"trk-subtitle"}),
        h("div", {id:"trk-stats"}),
      ),
      h("div", {id:"trk-body"}),
      h("div", {id:"trk-footer"},
        h("span",  {id:"trk-footer-meta"}),
        h("button",{id:"trk-expand-btn", onclick:openModal}, "⤢  View full page"),
        h("button",{id:"trk-close-link", onclick:closeTracker}, "Close"),
      ),
    );

    /* Modal overlay */
    const modalOverlay = h("div", {id:"trk-modal-overlay"});
    modalOverlay.addEventListener("click", e => { if (e.target===modalOverlay) closeModal(); });

    const modal = h("div", {id:"trk-modal"},
      h("div", {id:"trk-modal-accent"}),
      h("div", {id:"trk-modal-header"},
        h("div", {id:"trk-modal-chip-row"},
          h("div", {id:"trk-modal-chip"},
            h("span",{id:"trk-modal-chip-icon"}),
            h("span",{id:"trk-modal-chip-label"}),
            h("span",{id:"trk-modal-chip-id"}),
          ),
          h("button",{id:"trk-modal-close-btn","aria-label":"Close modal",onclick:closeModal},"×"),
        ),
        h("div",{id:"trk-modal-title-row"},
          h("h2", {id:"trk-modal-title"}),
          h("span",{id:"trk-modal-badge"}),
        ),
        h("div",{id:"trk-modal-subtitle"}),
        h("div",{id:"trk-modal-stats"}),
      ),
      h("div",{id:"trk-modal-body"}),
      h("div",{id:"trk-modal-footer"},
        h("button",{id:"trk-modal-close-link",onclick:closeModal},"✕  Close"),
      ),
    );
    modalOverlay.appendChild(modal);

    document.body.appendChild(overlay);
    document.body.appendChild(panel);
    document.body.appendChild(modalOverlay);
  }

  /* ═══════════════════════════════════════════════
     RENDER HELPERS
  ═══════════════════════════════════════════════ */

  function renderSkeleton(bodyEl) {
    bodyEl.innerHTML = "";
    const statsRow = h("div",{style:{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:"8px",marginBottom:"28px",gridColumn:"1/-1"}});
    for (let i=0;i<4;i++) statsRow.appendChild(h("div",{class:"trk-skel",style:{height:"52px",borderRadius:"8px",animationDelay:`${i*.08}s`}}));
    bodyEl.appendChild(statsRow);
    for (let i=0;i<4;i++) {
      const row = h("div",{class:"trk-skel-row"});
      row.appendChild(h("div",{class:"trk-skel trk-skel-circ",style:{animationDelay:`${i*.1}s`}}));
      const lines = h("div",{style:{flex:1}});
      lines.appendChild(h("div",{class:"trk-skel",style:{height:"10px",width:"75%",marginBottom:"6px",animationDelay:`${i*.1}s`}}));
      lines.appendChild(h("div",{class:"trk-skel",style:{height:"9px",width:"50%",animationDelay:`${i*.12}s`}}));
      row.appendChild(lines); bodyEl.appendChild(row);
    }
  }

  function renderEfris(efris) {
    if (!efris) return null;
    const cfg = efrisCfg(efris.status);
    if (!cfg) return null;
    return h("div",{class:"trk-efris",style:{background:cfg.bg,border:`1px solid ${cfg.color}30`}},
      h("span",{class:"trk-efris-icon",style:{color:cfg.color}},cfg.icon),
      h("div",{},
        h("div",{class:"trk-efris-status",style:{color:cfg.color}},`EFRIS · ${cfg.label.toUpperCase()}`),
        efris.reference ? h("div",{class:"trk-efris-ref",style:{color:cfg.color}},efris.reference) : null,
        efris.synced_at ? h("div",{class:"trk-efris-date"},`Synced ${fmtDate(efris.synced_at)}`) : null,
      ),
    );
  }

  function renderSecHeader(title,count) {
    return h("div",{class:"trk-sec-header"},
      h("span",{class:"trk-sec-title"},title),
      count!=null ? h("span",{class:"trk-sec-count"},String(count)) : null,
      h("div",{class:"trk-sec-line"}),
    );
  }

  function renderTimeline(items) {
    const wrap = h("div",{class:"trk-timeline"});
    wrap.appendChild(h("div",{class:"trk-tl-spine"}));
    (items||[]).forEach(item => {
      const clr   = tagColor(item.tag||item.label);
      const isPos = (item.qty||"").startsWith("+");
      const topRow = h("div",{class:"trk-tl-toprow"});
      if (item.tag) topRow.appendChild(h("span",{class:"trk-tag",style:{background:`${clr}18`,color:clr,border:`1px solid ${clr}25`}},item.tag));
      if (item.sub) topRow.appendChild(h("span",{class:"trk-tl-sub"},item.sub));
      if (item.qty) topRow.appendChild(h("span",{class:"trk-tl-qty",style:{color:isPos?"#22c55e":"#ef4444"}},item.qty));
      const metaRow = h("div",{class:"trk-tl-meta"},
        h("span",{},item.user||""),
        h("span",{class:"trk-dot-sep"},"·"),
        h("span",{},fmtDate(item.date)),
      );
      if (item.running) metaRow.appendChild(h("span",{class:"trk-tl-running"},`→ ${item.running}`));
      const dot = h("div",{class:"trk-tl-dot",style:{background:`${clr}18`,border:`1.5px solid ${clr}`}},
        h("div",{class:"trk-tl-dot-inner",style:{background:clr}}));
      wrap.appendChild(h("div",{class:"trk-tl-item"},dot,
        h("div",{class:"trk-tl-content"},topRow,
          h("div",{class:"trk-tl-label"},item.label||""),
          item.note?h("div",{class:"trk-tl-note"},item.note):null,
          metaRow,
        )
      ));
    });
    return wrap;
  }

  function renderAudit(items) {
    const wrap = h("div",{});
    (items||[]).forEach(item => {
      const clr   = sevColor(item.severity);
      const inner = h("div",{},h("div",{class:"trk-audit-desc"},item.description||""));
      if (item.diff) {
        inner.appendChild(h("div",{class:"trk-diff-row"},
          h("span",{class:"trk-diff-from"},item.diff.from),
          h("span",{class:"trk-diff-arrow"},"→"),
          h("span",{class:"trk-diff-to"},item.diff.to),
        ));
      }
      inner.appendChild(h("div",{class:"trk-audit-meta"},`${item.user||"System"} · ${fmtDate(item.date)}`));
      wrap.appendChild(h("div",{class:"trk-audit-item"},
        h("div",{class:"trk-sev-dot",style:{background:clr,boxShadow:`0 0 5px ${clr}66`}}),
        inner,
      ));
    });
    return wrap;
  }

  function renderTable(section) {
    const cols = section.columns||[]; const rows = section.rows||[];
    const thead = h("thead",{},h("tr",{},
      ...cols.map((c,i)=>h("th",{style:{textAlign:i===0?"left":"right"}},c)),
    ));
    const tbody = h("tbody",{});
    rows.forEach(row=>{
      const tr=h("tr",{});
      row.forEach((cell,ci)=>tr.appendChild(h("td",{
        class:ci===row.length-1?"trk-td-last":"",
        style:{textAlign:ci===0?"left":"right"},
      },cell)));
      tbody.appendChild(tr);
    });
    return h("div",{class:"trk-table-wrap"},h("table",{class:"trk-table"},thead,tbody));
  }

  function renderKeyvalue(section) {
    const grid = h("div",{class:"trk-kv-grid"});
    (section.pairs||[]).forEach(pair=>grid.appendChild(h("div",{class:"trk-kv-item"},
      h("div",{class:"trk-kv-label"},pair.label),
      h("div",{class:"trk-kv-value"},pair.value),
    )));
    return grid;
  }

  /**
   * Render one section.
   * inModal=true  → wide sections (non-keyvalue) get class 'trk-wide'
   *                 so the 2-col grid spans them full width.
   */
  function renderSection(section, inModal=false) {
    const count = section.items?.length ?? section.rows?.length ?? section.pairs?.length;
    const isWide = section.type !== "keyvalue";
    const cls = "trk-section" + (inModal && isWide ? " trk-wide" : "");
    const wrap = h("div",{class:cls}, renderSecHeader(section.title,count));
    if      (section.type==="timeline") wrap.appendChild(renderTimeline(section.items));
    else if (section.type==="audit")    wrap.appendChild(renderAudit(section.items));
    else if (section.type==="table"||section.type==="lineitems") wrap.appendChild(renderTable(section));
    else if (section.type==="keyvalue") wrap.appendChild(renderKeyvalue(section));
    return wrap;
  }

  /* ═══════════════════════════════════════════════
     SHARED HEADER FILL  (drawer + modal share this)
  ═══════════════════════════════════════════════ */

  function applyHeader(prefix, data, type, id) {
    const meta      = data.meta  || {};
    const stats     = data.stats || [];
    const typeColor = TYPE_COLORS[type] || "#0ea5e9";
    const bs        = badgeStyle(meta.badge_color);

    // Accent bar
    document.getElementById(`${prefix}-accent`).style.background =
      `linear-gradient(90deg,transparent,${typeColor},transparent)`;
    // Pass accent to panel/modal for button hover colour
    const root = prefix==="trk-panel"
      ? document.getElementById("trk-panel")
      : document.getElementById("trk-modal");
    root.style.setProperty("--trk-accent", typeColor);

    // Chip
    const icon  = document.getElementById(`${prefix}-chip-icon`);
    const label = document.getElementById(`${prefix}-chip-label`);
    const cid   = document.getElementById(`${prefix}-chip-id`);
    icon.textContent  = TYPE_ICONS[type] || "·";
    icon.style.color  = typeColor;
    label.textContent = `${type.charAt(0).toUpperCase()+type.slice(1)} Tracker`;
    label.style.color = typeColor;
    cid.textContent   = meta.id_label ? `· ${meta.id_label}` : "";

    // Title + badge
    document.getElementById(`${prefix}-title`).textContent = meta.title || `#${id}`;
    const badge = document.getElementById(`${prefix}-badge`);
    if (meta.badge) {
      badge.textContent = meta.badge;
      badge.style.display = "";
      Object.assign(badge.style, {background:bs.bg,color:bs.color,border:`1px solid ${bs.bd}`});
    } else {
      badge.style.display = "none";
    }
    document.getElementById(`${prefix}-subtitle`).textContent = meta.subtitle || "";

    // Stats
    const statsEl = document.getElementById(`${prefix}-stats`);
    statsEl.innerHTML = "";
    stats.forEach(s => {
      const clr = statColor(s.color);
      statsEl.appendChild(h("div",{class:"trk-stat",style:{"--trk-stat-color":clr}},
        h("div",{class:"trk-stat-label"},s.label),
        h("div",{class:"trk-stat-value",style:{color:clr}},s.value),
      ));
    });
  }

  /* ═══════════════════════════════════════════════
     RENDER DRAWER BODY
  ═══════════════════════════════════════════════ */

  function renderDrawer(data, type, id) {
    applyHeader("trk-panel", data, type, id);

    const typeColor = TYPE_COLORS[type] || "#0ea5e9";
    document.getElementById("trk-footer-meta").textContent = `${type} · id ${id}`;
    const cl = document.getElementById("trk-close-link");
    Object.assign(cl.style, {background:`${typeColor}18`,color:typeColor,border:`1px solid ${typeColor}40`});

    const body = document.getElementById("trk-body");
    body.innerHTML = "";
    const efrisEl = renderEfris(data.efris);
    if (efrisEl) body.appendChild(efrisEl);
    const sects = data.sections || [];
    if (!sects.length) {
      body.appendChild(h("div",{style:{textAlign:"center",padding:"40px 20px",
        color:"var(--trk-dim)",fontSize:"12px",fontFamily:"'DM Mono',monospace"}},
        "No tracking data available for this record."));
    } else {
      sects.forEach(sec => body.appendChild(renderSection(sec, false)));
    }
  }

  /* ═══════════════════════════════════════════════
     MODAL — "View full page"
  ═══════════════════════════════════════════════ */

  function openModal() {
    if (!_currentData) return;
    const {data, type, id} = _currentData;
    const typeColor = TYPE_COLORS[type] || "#0ea5e9";

    applyHeader("trk-modal", data, type, id);

    // Style close button
    const cl = document.getElementById("trk-modal-close-link");
    Object.assign(cl.style, {
      background:`${typeColor}18`, color:typeColor,
      border:`1px solid ${typeColor}40`,
      padding:"8px 22px", borderRadius:"8px",
      fontSize:"12px", fontFamily:"'DM Mono',monospace",
    });

    // Populate body (2-col)
    const body = document.getElementById("trk-modal-body");
    body.innerHTML = "";
    const efrisEl = renderEfris(data.efris);
    if (efrisEl) body.appendChild(efrisEl);
    (data.sections||[]).forEach(sec => body.appendChild(renderSection(sec, true)));

    document.getElementById("trk-modal-overlay").classList.add("trk-visible");
  }

  function closeModal() {
    document.getElementById("trk-modal-overlay").classList.remove("trk-visible");
  }

  /* ═══════════════════════════════════════════════
     OPEN / CLOSE DRAWER
  ═══════════════════════════════════════════════ */

  let _currentType = null;
  let _currentId   = null;
  let _currentData = null;   // { data, type, id } — held for modal

  function openTracker(type, id, label) {
    _currentType = type;
    _currentId   = id;
    _currentData = null;

    // Ensure the shell has been built before trying to access any DOM elements.
    // Guards against callers invoking PrimeTracker.open() before DOMContentLoaded.
    injectStyles();
    buildShell();

    document.getElementById("trk-overlay").classList.add("trk-visible");
    document.getElementById("trk-panel").classList.add("trk-visible");
    document.body.style.overflow = "hidden";

    // Instant title
    document.getElementById("trk-title").textContent    = label || "Loading…";
    document.getElementById("trk-subtitle").textContent = "";
    document.getElementById("trk-badge").style.display  = "none";
    document.getElementById("trk-stats").innerHTML      = "";
    document.getElementById("trk-expand-btn").style.display = "none";

    // Accent + chip immediately
    const typeColor = TYPE_COLORS[type] || "#0ea5e9";
    document.getElementById("trk-panel").style.setProperty("--trk-accent", typeColor);
    document.getElementById("trk-panel-accent").style.background =
      `linear-gradient(90deg,transparent,${typeColor},transparent)`;
    document.getElementById("trk-chip-icon").textContent  = TYPE_ICONS[type]||"·";
    document.getElementById("trk-chip-icon").style.color  = typeColor;
    document.getElementById("trk-chip-label").textContent = `${type.charAt(0).toUpperCase()+type.slice(1)} Tracker`;
    document.getElementById("trk-chip-label").style.color = typeColor;
    document.getElementById("trk-chip-id").textContent    = "";

    renderSkeleton(document.getElementById("trk-body"));

    fetch(`${API_BASE}?type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}`, {
      headers:{"X-CSRFToken":getCookie(CSRF_COOKIE),"Accept":"application/json"},
      credentials:"same-origin",
    })
      .then(r => {
        if (!r.ok) return r.json().then(d=>Promise.reject(d.error||`HTTP ${r.status}`));
        return r.json();
      })
      .then(data => {
        if (_currentId !== id) return;
        _currentData = {data, type, id};
        renderDrawer(data, type, id);
        document.getElementById("trk-expand-btn").style.display = "";
      })
      .catch(err => {
        if (_currentId !== id) return;
        const body = document.getElementById("trk-body");
        body.innerHTML = "";
        body.appendChild(h("div",{class:"trk-error-box"},
          h("div",{class:"trk-error-icon"},"⚠"),
          h("div",{class:"trk-error-msg"},"Could not load tracking data"),
          h("div",{class:"trk-error-det"},String(err)),
        ));
      });
  }

  function closeTracker() {
    _currentId   = null;
    _currentData = null;
    closeModal();
    document.getElementById("trk-overlay").classList.remove("trk-visible");
    document.getElementById("trk-panel").classList.remove("trk-visible");
    document.body.style.overflow = "";
  }

  /* ═══════════════════════════════════════════════
     EVENT DELEGATION  — works on dynamic rows too
  ═══════════════════════════════════════════════ */

  document.addEventListener("click", e => {
    const btn = e.target.closest("[data-track]");
    if (!btn) return;
    e.preventDefault();
    const type  = btn.dataset.track;
    const id    = btn.dataset.id;
    const label = btn.dataset.label || btn.textContent.trim() || "";
    if (!type || !id) return;
    openTracker(type, id, label);
  });

  document.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    // Close modal first if open, then drawer
    const mo = document.getElementById("trk-modal-overlay");
    if (mo && mo.classList.contains("trk-visible")) { closeModal(); return; }
    closeTracker();
  });

  /* ═══════════════════════════════════════════════
     INIT
  ═══════════════════════════════════════════════ */

  function init() { injectStyles(); buildShell(); }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Public API
  window.PrimeTracker = { open:openTracker, close:closeTracker, openModal };

})();/**
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║  PrimeBooks — Universal Tracker  (tracker.js)                   ║
 * ║                                                                  ║
 * ║  Zero dependencies. Include once in base.html.                  ║
 * ║                                                                  ║
 * ║  INCLUDE IN BASE TEMPLATE (before </body>):                     ║
 * ║    <script src="{% static 'js/tracker.js' %}"></script>         ║
 * ║                                                                  ║
 * ║  ADD TO ANY BUTTON:                                              ║
 * ║    <button data-track="product" data-id="{{ product.pk }}"      ║
 * ║            data-label="{{ product.name }}">Track</button>        ║
 * ║                                                                  ║
 * ║  THEME                                                           ║
 * ║    Reads your existing [data-theme='dark'] switcher on <html>.  ║
 * ║    Light mode = default.  Dark = [data-theme='dark'].           ║
 * ║    Theme switches instantly — no JS needed, just CSS vars.      ║
 * ║                                                                  ║
 * ║  "VIEW FULL PAGE" opens a full-screen modal overlay showing     ║
 * ║    the same data in a 2-column layout.                          ║
 * ╚══════════════════════════════════════════════════════════════════╝
 */

(function () {
  "use strict";

  const API_BASE    = "/api/track/";
  const CSRF_COOKIE = "csrftoken";

  /* ═══════════════════════════════════════════════════════════════════
     CSS
     Light theme is the default.
     [data-theme='dark'] on <html> overrides all colour tokens.
     Works instantly with your existing theme switcher — zero JS.
  ═══════════════════════════════════════════════════════════════════ */

  const CSS = `
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,300;0,400;0,500;1,300&family=Syne:wght@600;700;800&display=swap');

    /* ── LIGHT (default) ────────────────────────────────────────────── */
    :root {
      --trk-bg:               #ffffff;
      --trk-s1:               #f8fafc;
      --trk-s2:               #f1f5f9;
      --trk-s3:               #e9eef6;
      --trk-bd:               #dde3ec;
      --trk-bd2:              #cbd5e1;
      --trk-text:             #0f172a;
      --trk-sub:              #475569;
      --trk-dim:              #94a3b8;
      --trk-overlay:          rgba(15,23,42,0.45);
      --trk-shadow:           rgba(15,23,42,0.18);
      --trk-table-zebra:      rgba(241,245,249,0.7);
      --trk-diff-from-bg:     #fef2f2;
      --trk-diff-from-color:  #dc2626;
      --trk-diff-from-bd:     #fecaca;
      --trk-diff-to-bg:       #f0fdf4;
      --trk-diff-to-color:    #16a34a;
      --trk-diff-to-bd:       #bbf7d0;
      --trk-td-last:          #16a34a;
      --trk-error-color:      #dc2626;
      --trk-mono:             'DM Mono', monospace;
      --trk-display:          'Syne', sans-serif;
    }

    /* ── DARK — your [data-theme='dark'] switcher triggers this ─────── */
    [data-theme='dark'] {
      --trk-bg:               #060f1c;
      --trk-s1:               #0a1628;
      --trk-s2:               #0e1d32;
      --trk-s3:               #12233b;
      --trk-bd:               #172338;
      --trk-bd2:              #1e2f45;
      --trk-text:             #ddeaf7;
      --trk-sub:              #4d6a87;
      --trk-dim:              #243550;
      --trk-overlay:          rgba(2,8,20,0.82);
      --trk-shadow:           rgba(0,0,0,0.65);
      --trk-table-zebra:      rgba(14,29,50,0.4);
      --trk-diff-from-bg:     #240808;
      --trk-diff-from-color:  #f87171;
      --trk-diff-from-bd:     rgba(248,113,113,0.15);
      --trk-diff-to-bg:       #042214;
      --trk-diff-to-color:    #4ade80;
      --trk-diff-to-bd:       rgba(74,222,128,0.15);
      --trk-td-last:          #4ade80;
      --trk-error-color:      #f87171;
    }

    /* ── OVERLAY ────────────────────────────────────────────────────── */
    #trk-overlay {
      position:fixed; inset:0; z-index:9998;
      background:var(--trk-overlay);
      backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px);
      opacity:0; transition:opacity .25s ease; pointer-events:none;
    }
    #trk-overlay.trk-visible { opacity:1; pointer-events:all; }

    /* ── DRAWER PANEL ───────────────────────────────────────────────── */
    #trk-panel {
      position:fixed; top:0; right:0; bottom:0;
      width:min(600px,100vw); z-index:9999;
      background:var(--trk-bg);
      border-left:1px solid var(--trk-bd2);
      box-shadow:-24px 0 80px var(--trk-shadow);
      display:flex; flex-direction:column;
      transform:translateX(100%);
      transition:transform .32s cubic-bezier(.22,.68,0,1.08);
      font-family:var(--trk-display);
    }
    #trk-panel.trk-visible { transform:translateX(0); }

    #trk-panel-accent {
      height:2px; flex-shrink:0;
      background:linear-gradient(90deg,transparent,var(--trk-accent,#0ea5e9),transparent);
    }

    /* ── HEADER ─────────────────────────────────────────────────────── */
    #trk-header {
      padding:18px 24px 16px;
      border-bottom:1px solid var(--trk-bd2); flex-shrink:0;
    }
    #trk-chip-row {
      display:flex; align-items:center;
      justify-content:space-between; margin-bottom:12px;
    }
    #trk-chip { display:flex; align-items:center; gap:7px; }
    #trk-chip-icon { font-size:14px; }
    #trk-chip-label {
      font-size:9px; font-family:var(--trk-mono);
      letter-spacing:.18em; text-transform:uppercase;
    }
    #trk-chip-id {
      font-size:10px; font-family:var(--trk-mono);
      color:var(--trk-sub); margin-left:4px;
    }
    #trk-close-btn {
      width:30px; height:30px; border-radius:7px;
      border:1px solid var(--trk-bd2); background:transparent;
      color:var(--trk-sub); font-size:18px; cursor:pointer;
      display:flex; align-items:center; justify-content:center;
      transition:all .14s; line-height:1;
    }
    #trk-close-btn:hover { background:var(--trk-s3); color:var(--trk-text); }

    #trk-title-row { display:flex; align-items:flex-start; gap:10px; margin-bottom:4px; }
    #trk-title {
      flex:1; font-size:21px; font-weight:800; color:var(--trk-text);
      letter-spacing:-.03em; line-height:1.2;
    }
    #trk-badge {
      font-size:10px; padding:3px 11px; border-radius:20px;
      font-family:var(--trk-mono); font-weight:600;
      flex-shrink:0; margin-top:3px;
    }
    #trk-subtitle {
      font-size:12px; color:var(--trk-sub);
      font-family:var(--trk-mono); margin-bottom:14px;
    }

    #trk-stats {
      display:grid; gap:8px;
      grid-template-columns:repeat(auto-fit,minmax(110px,1fr));
    }
    .trk-stat {
      background:var(--trk-s2); border:1px solid var(--trk-bd2);
      border-radius:8px; padding:8px 11px; transition:border-color .15s;
    }
    .trk-stat:hover { border-color:var(--trk-stat-color,var(--trk-bd2)); }
    .trk-stat-label {
      font-size:9px; color:var(--trk-sub); font-family:var(--trk-mono);
      letter-spacing:.06em; margin-bottom:4px;
    }
    .trk-stat-value { font-size:12px; font-weight:700; font-family:var(--trk-mono); line-height:1.2; }

    /* ── BODY ───────────────────────────────────────────────────────── */
    #trk-body {
      flex:1; overflow-y:auto; padding:22px 24px;
      scrollbar-width:thin; scrollbar-color:var(--trk-bd2) transparent;
    }
    #trk-body::-webkit-scrollbar { width:3px; }
    #trk-body::-webkit-scrollbar-thumb { background:var(--trk-bd2); border-radius:3px; }

    /* ── FOOTER ─────────────────────────────────────────────────────── */
    #trk-footer {
      padding:12px 24px; border-top:1px solid var(--trk-bd2);
      flex-shrink:0; display:flex; gap:8px; align-items:center;
    }
    #trk-footer-meta {
      flex:1; font-size:10px; color:var(--trk-dim); font-family:var(--trk-mono);
    }
    #trk-expand-btn {
      padding:7px 15px; border-radius:7px;
      border:1px solid var(--trk-bd2); background:var(--trk-s2);
      color:var(--trk-sub); font-size:11px; font-family:var(--trk-mono);
      cursor:pointer; transition:all .13s;
    }
    #trk-expand-btn:hover { color:var(--trk-text); background:var(--trk-s3); }
    #trk-close-link {
      padding:7px 18px; border-radius:7px;
      font-size:11px; font-family:var(--trk-mono);
      cursor:pointer; transition:all .13s; border:1px solid transparent;
    }

    /* ═══════════════════════════════════════════════════════════════
       MODAL  — "View full page"
       A centred overlay that shows the same data in a 2-col layout.
    ═══════════════════════════════════════════════════════════════ */
    #trk-modal-overlay {
      position:fixed; inset:0; z-index:10000;
      background:var(--trk-overlay);
      backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px);
      display:flex; align-items:center; justify-content:center; padding:24px;
      opacity:0; pointer-events:none; transition:opacity .22s ease;
    }
    #trk-modal-overlay.trk-visible { opacity:1; pointer-events:all; }

    #trk-modal {
      background:var(--trk-bg);
      border:1px solid var(--trk-bd2);
      border-radius:14px;
      box-shadow:0 32px 100px var(--trk-shadow);
      width:min(940px,100%); max-height:calc(100vh - 48px);
      display:flex; flex-direction:column;
      transform:scale(.96) translateY(8px);
      transition:transform .24s cubic-bezier(.22,.68,0,1.08);
      font-family:var(--trk-display); overflow:hidden;
    }
    #trk-modal-overlay.trk-visible #trk-modal { transform:scale(1) translateY(0); }

    #trk-modal-accent {
      height:3px; flex-shrink:0;
      background:linear-gradient(90deg,transparent,var(--trk-accent,#0ea5e9),transparent);
    }

    #trk-modal-header {
      padding:20px 28px 18px;
      border-bottom:1px solid var(--trk-bd2); flex-shrink:0;
    }
    #trk-modal-chip-row {
      display:flex; align-items:center;
      justify-content:space-between; margin-bottom:14px;
    }
    #trk-modal-chip { display:flex; align-items:center; gap:8px; }
    #trk-modal-chip-icon  { font-size:15px; }
    #trk-modal-chip-label {
      font-size:9px; font-family:var(--trk-mono);
      letter-spacing:.18em; text-transform:uppercase;
    }
    #trk-modal-chip-id {
      font-size:10px; font-family:var(--trk-mono);
      color:var(--trk-sub); margin-left:4px;
    }
    #trk-modal-close-btn {
      width:32px; height:32px; border-radius:8px;
      border:1px solid var(--trk-bd2); background:transparent;
      color:var(--trk-sub); font-size:19px; cursor:pointer;
      display:flex; align-items:center; justify-content:center;
      transition:all .14s; line-height:1;
    }
    #trk-modal-close-btn:hover { background:var(--trk-s3); color:var(--trk-text); }

    #trk-modal-title-row { display:flex; align-items:flex-start; gap:10px; margin-bottom:5px; }
    #trk-modal-title {
      flex:1; font-size:26px; font-weight:800; color:var(--trk-text);
      letter-spacing:-.03em; line-height:1.2;
    }
    #trk-modal-badge {
      font-size:10px; padding:3px 12px; border-radius:20px;
      font-family:var(--trk-mono); font-weight:600;
      flex-shrink:0; margin-top:5px;
    }
    #trk-modal-subtitle {
      font-size:12px; color:var(--trk-sub);
      font-family:var(--trk-mono); margin-bottom:16px;
    }
    #trk-modal-stats {
      display:grid; gap:10px;
      grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
    }

    /* 2-column body */
    #trk-modal-body {
      flex:1; overflow-y:auto; padding:28px;
      display:grid; grid-template-columns:1fr 1fr; gap:0 32px; align-content:start;
      scrollbar-width:thin; scrollbar-color:var(--trk-bd2) transparent;
    }
    #trk-modal-body::-webkit-scrollbar { width:3px; }
    #trk-modal-body::-webkit-scrollbar-thumb { background:var(--trk-bd2); }
    /* Full-width items in modal */
    #trk-modal-body > .trk-efris    { grid-column:1/-1; }
    #trk-modal-body > .trk-wide     { grid-column:1/-1; }

    #trk-modal-footer {
      padding:13px 28px; border-top:1px solid var(--trk-bd2);
      flex-shrink:0; display:flex; justify-content:flex-end; gap:8px;
    }
    #trk-modal-close-link {
      padding:8px 22px; border-radius:8px; border:1px solid transparent;
      font-size:12px; font-family:var(--trk-mono); cursor:pointer; transition:all .13s;
    }

    /* ── EFRIS BLOCK ────────────────────────────────────────────────── */
    .trk-efris {
      display:flex; align-items:flex-start; gap:12px;
      padding:12px 16px; border-radius:9px; margin-bottom:28px;
    }
    .trk-efris-icon   { font-size:20px; line-height:1; margin-top:1px; }
    .trk-efris-status { font-size:10px; font-family:var(--trk-mono); font-weight:700; letter-spacing:.08em; margin-bottom:3px; }
    .trk-efris-ref    { font-size:11px; font-family:var(--trk-mono); opacity:.8; margin-bottom:2px; }
    .trk-efris-date   { font-size:10.5px; color:var(--trk-sub); font-family:var(--trk-mono); }

    /* ── SECTION ────────────────────────────────────────────────────── */
    .trk-section { margin-bottom:28px; }
    .trk-sec-header { display:flex; align-items:center; gap:8px; margin-bottom:16px; }
    .trk-sec-title {
      font-size:9px; font-family:var(--trk-mono); color:var(--trk-dim);
      text-transform:uppercase; letter-spacing:.14em; white-space:nowrap;
    }
    .trk-sec-count {
      font-size:9px; background:var(--trk-s3); color:var(--trk-sub);
      border:1px solid var(--trk-bd2); padding:1px 7px; border-radius:20px;
      font-family:var(--trk-mono);
    }
    .trk-sec-line { flex:1; height:1px; background:var(--trk-bd2); }

    /* ── TIMELINE ───────────────────────────────────────────────────── */
    .trk-timeline { position:relative; }
    .trk-tl-spine {
      position:absolute; left:14px; top:8px; bottom:4px;
      width:1px; background:var(--trk-bd2);
    }
    .trk-tl-item { display:flex; gap:14px; padding-left:36px; position:relative; margin-bottom:20px; }
    .trk-tl-item:last-child { margin-bottom:0; }
    .trk-tl-dot {
      position:absolute; left:7px; top:3px;
      width:15px; height:15px; border-radius:50%;
      display:flex; align-items:center; justify-content:center; flex-shrink:0;
    }
    .trk-tl-dot-inner { width:5px; height:5px; border-radius:50%; }
    .trk-tl-content { flex:1; min-width:0; }
    .trk-tl-toprow { display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin-bottom:4px; }
    .trk-tag { font-size:9px; padding:2px 8px; border-radius:4px; font-family:var(--trk-mono); font-weight:600; letter-spacing:.06em; }
    .trk-tl-sub   { font-size:11px; color:var(--trk-sub); font-family:var(--trk-mono); }
    .trk-tl-qty   { margin-left:auto; font-family:var(--trk-mono); font-size:13px; font-weight:700; }
    .trk-tl-label { font-size:12.5px; color:var(--trk-text); font-weight:600; margin-bottom:3px; line-height:1.3; }
    .trk-tl-note  { font-size:11.5px; color:var(--trk-sub); margin-bottom:4px; line-height:1.4; }
    .trk-tl-meta  { display:flex; align-items:center; gap:7px; flex-wrap:wrap; font-size:10.5px; color:var(--trk-dim); font-family:var(--trk-mono); }
    .trk-tl-running { margin-left:auto; color:var(--trk-sub); }
    .trk-dot-sep  { color:var(--trk-bd2); }

    /* ── AUDIT ──────────────────────────────────────────────────────── */
    .trk-audit-item { display:flex; gap:12px; margin-bottom:16px; align-items:flex-start; }
    .trk-audit-item:last-child { margin-bottom:0; }
    .trk-sev-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; margin-top:5px; }
    .trk-audit-desc { font-size:12.5px; color:var(--trk-text); font-weight:500; margin-bottom:4px; line-height:1.35; }
    .trk-diff-row { display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-bottom:5px; }
    .trk-diff-from {
      font-size:10px; font-family:var(--trk-mono); padding:2px 7px; border-radius:4px;
      background:var(--trk-diff-from-bg); color:var(--trk-diff-from-color); border:1px solid var(--trk-diff-from-bd);
    }
    .trk-diff-arrow { color:var(--trk-dim); font-size:11px; }
    .trk-diff-to {
      font-size:10px; font-family:var(--trk-mono); padding:2px 7px; border-radius:4px;
      background:var(--trk-diff-to-bg); color:var(--trk-diff-to-color); border:1px solid var(--trk-diff-to-bd);
    }
    .trk-audit-meta { font-size:10.5px; color:var(--trk-dim); font-family:var(--trk-mono); }

    /* ── TABLE ──────────────────────────────────────────────────────── */
    .trk-table-wrap { border:1px solid var(--trk-bd2); border-radius:9px; overflow:hidden; }
    .trk-table { width:100%; border-collapse:collapse; font-size:12px; }
    .trk-table thead tr { background:var(--trk-s3); border-bottom:1px solid var(--trk-bd2); }
    .trk-table th {
      padding:9px 13px; font-size:9px; color:var(--trk-dim);
      font-family:var(--trk-mono); font-weight:600;
      letter-spacing:.1em; text-transform:uppercase;
    }
    .trk-table th:first-child { text-align:left; }
    .trk-table th:not(:first-child) { text-align:right; }
    .trk-table tbody tr { border-bottom:1px solid var(--trk-bd); }
    .trk-table tbody tr:last-child { border-bottom:none; }
    .trk-table tbody tr:nth-child(even) { background:var(--trk-table-zebra); }
    .trk-table td { padding:11px 13px; color:var(--trk-sub); font-family:var(--trk-mono); }
    .trk-table td:first-child { text-align:left; color:var(--trk-text); font-weight:600; font-family:var(--trk-display); }
    .trk-table td:not(:first-child) { text-align:right; }
    .trk-table td.trk-td-last { color:var(--trk-td-last); font-weight:700; }

    /* ── KEYVALUE ───────────────────────────────────────────────────── */
    .trk-kv-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .trk-kv-item { background:var(--trk-s2); border:1px solid var(--trk-bd2); border-radius:8px; padding:10px 12px; }
    .trk-kv-label { font-size:9px; color:var(--trk-sub); font-family:var(--trk-mono); letter-spacing:.06em; margin-bottom:4px; }
    .trk-kv-value { font-size:12.5px; color:var(--trk-text); font-weight:600; }

    /* ── SKELETON ───────────────────────────────────────────────────── */
    @keyframes trk-pulse { 0%,100%{opacity:.35} 50%{opacity:.75} }
    .trk-skel { border-radius:5px; background:var(--trk-s3); animation:trk-pulse 1.4s ease infinite; }
    .trk-skel-row { display:flex; gap:10px; margin-bottom:20px; }
    .trk-skel-circ { width:15px; height:15px; border-radius:50%; flex-shrink:0; }

    /* ── ERROR ──────────────────────────────────────────────────────── */
    .trk-error-box { text-align:center; padding:40px 20px; }
    .trk-error-icon { font-size:32px; margin-bottom:12px; }
    .trk-error-msg  { font-size:13px; color:var(--trk-error-color); margin-bottom:6px; }
    .trk-error-det  { font-size:11px; color:var(--trk-sub); font-family:var(--trk-mono); }

    /* ── TRACK BUTTONS (auto-styled) ────────────────────────────────── */
    [data-track] {
      display:inline-flex; align-items:center; gap:5px;
      padding:3px 10px; border-radius:6px; cursor:pointer;
      font-size:11px; font-family:var(--trk-mono);
      border:1px solid var(--trk-bd2); background:transparent;
      color:var(--trk-sub); transition:all .14s;
      white-space:nowrap; user-select:none;
    }
    [data-track]:hover {
      border-color:var(--trk-accent,#0ea5e9);
      color:var(--trk-accent,#0ea5e9);
      background:color-mix(in srgb,var(--trk-accent,#0ea5e9) 8%,transparent);
    }
    [data-track]::before { content:attr(data-track-icon,'◎'); font-size:9px; }
  `;

  /* ═══════════════════════════════════════════════
     COLOUR MAPS
  ═══════════════════════════════════════════════ */

  const TYPE_COLORS = {
    product:"#0ea5e9", sale:"#22c55e",   invoice:"#8b5cf6",
    expense:"#f97316", user:"#ec4899",   customer:"#06b6d4",
    budget: "#84cc16", transfer:"#10b981",purchase:"#eab308",
    payment:"#38bdf8", report:"#64748b",
  };
  const TYPE_ICONS = {
    product:"⬡", sale:"◈",    invoice:"◇",  expense:"◉",
    user:"◎",    customer:"⊙", budget:"◑",   transfer:"⇄",
    purchase:"↓", payment:"◆", report:"▤",
  };

  const TAG_COLORS = {
    PURCHASE:"#22c55e",SALE:"#0ea5e9",RETURN:"#8b5cf6",VOID:"#ef4444",
    REFUND:"#f97316",ADJUSTMENT:"#eab308",TRANSFER_IN:"#10b981",TRANSFER_OUT:"#64748b",
    created:"#22c55e",updated:"#0ea5e9",deleted:"#ef4444",approved:"#22c55e",
    rejected:"#ef4444",paid:"#22c55e",sent:"#38bdf8",cancelled:"#ef4444",
    efris:"#8b5cf6",login:"#ec4899",locked:"#ef4444",
    login_success:"#22c55e",login_failed:"#ef4444",
  };
  const tagColor = (t) => TAG_COLORS[t] || TAG_COLORS[(t||"").toUpperCase()] || "#64748b";

  /* Badge colours split by theme */
  const BADGE_LIGHT = {
    green:  {bg:"#dcfce7",color:"#15803d",bd:"#86efac"},
    blue:   {bg:"#dbeafe",color:"#1d4ed8",bd:"#93c5fd"},
    purple: {bg:"#ede9fe",color:"#7c3aed",bd:"#c4b5fd"},
    red:    {bg:"#fee2e2",color:"#dc2626",bd:"#fca5a5"},
    yellow: {bg:"#fefce8",color:"#a16207",bd:"#fde047"},
    dim:    {bg:"#f1f5f9",color:"#475569",bd:"#cbd5e1"},
  };
  const BADGE_DARK = {
    green:  {bg:"#042214",color:"#4ade80",bd:"rgba(74,222,128,.18)"},
    blue:   {bg:"#051830",color:"#38bdf8",bd:"rgba(56,189,248,.18)"},
    purple: {bg:"#180d35",color:"#a78bfa",bd:"rgba(167,139,250,.18)"},
    red:    {bg:"#240808",color:"#f87171",bd:"rgba(248,113,113,.18)"},
    yellow: {bg:"#241c00",color:"#facc15",bd:"rgba(250,204,21,.18)"},
    dim:    {bg:"#0a1628",color:"#4d6a87",bd:"#172338"},
  };
  function badgeStyle(c) {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    return (dark ? BADGE_DARK : BADGE_LIGHT)[c] || (dark ? BADGE_DARK : BADGE_LIGHT).dim;
  }

  const SEV_COLORS = {
    info:"#0ea5e9",success:"#22c55e",warning:"#eab308",error:"#ef4444",critical:"#dc2626",
  };
  const sevColor = (s) => SEV_COLORS[s] || SEV_COLORS.info;

  const STAT_COLORS = {
    green:"#22c55e",blue:"#0ea5e9",purple:"#8b5cf6",
    red:"#ef4444",yellow:"#eab308",dim:"#64748b",
  };
  const statColor = (c) => STAT_COLORS[c] || STAT_COLORS.dim;

  /* EFRIS config split by theme */
  const EFRIS_LIGHT = {
    fiscalized:{label:"Fiscalized",  color:"#7c3aed",bg:"#ede9fe",icon:"⬡"},
    pending:   {label:"Pending Sync",color:"#a16207",bg:"#fefce8",icon:"◌"},
    failed:    {label:"Sync Failed", color:"#dc2626",bg:"#fee2e2",icon:"⚠"},
  };
  const EFRIS_DARK = {
    fiscalized:{label:"Fiscalized",  color:"#a78bfa",bg:"#180d35",icon:"⬡"},
    pending:   {label:"Pending Sync",color:"#facc15",bg:"#241c00",icon:"◌"},
    failed:    {label:"Sync Failed", color:"#f87171",bg:"#240808",icon:"⚠"},
  };
  function efrisCfg(status) {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    return (dark ? EFRIS_DARK : EFRIS_LIGHT)[status] || null;
  }

  /* ═══════════════════════════════════════════════
     UTILITIES
  ═══════════════════════════════════════════════ */

  function fmtDate(d) {
    if (!d) return "—";
    try {
      const dt = new Date(d);
      return dt.toLocaleDateString("en-GB", {day:"2-digit",month:"short",year:"numeric"})
           + "  " + dt.toLocaleTimeString("en-GB", {hour:"2-digit",minute:"2-digit"});
    } catch { return d; }
  }

  function getCookie(name) {
    const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return m ? decodeURIComponent(m[1]) : "";
  }

  function h(tag, attrs={}, ...children) {
    const el = document.createElement(tag);
    for (const [k,v] of Object.entries(attrs)) {
      if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
      else el.setAttribute(k, v);
    }
    for (const c of children.flat(Infinity)) {
      if (c == null) continue;
      el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return el;
  }

  /* ═══════════════════════════════════════════════
     DOM BUILD
  ═══════════════════════════════════════════════ */

  function injectStyles() {
    if (document.getElementById("trk-styles")) return;
    const s = document.createElement("style");
    s.id = "trk-styles"; s.textContent = CSS;
    document.head.appendChild(s);
  }

  function buildShell() {
    if (document.getElementById("trk-panel")) return;

    /* Drawer overlay */
    const overlay = h("div", {id:"trk-overlay"});
    overlay.addEventListener("click", closeTracker);

    /* Drawer panel */
    const panel = h("div", {id:"trk-panel"},
      h("div", {id:"trk-panel-accent"}),
      h("div", {id:"trk-header"},
        h("div", {id:"trk-chip-row"},
          h("div", {id:"trk-chip"},
            h("span", {id:"trk-chip-icon"}),
            h("span", {id:"trk-chip-label"}),
            h("span", {id:"trk-chip-id"}),
          ),
          h("button", {id:"trk-close-btn","aria-label":"Close tracker",onclick:closeTracker}, "×"),
        ),
        h("div", {id:"trk-title-row"},
          h("h2",  {id:"trk-title"}, "Loading…"),
          h("span",{id:"trk-badge"}),
        ),
        h("div", {id:"trk-subtitle"}),
        h("div", {id:"trk-stats"}),
      ),
      h("div", {id:"trk-body"}),
      h("div", {id:"trk-footer"},
        h("span",  {id:"trk-footer-meta"}),
        h("button",{id:"trk-expand-btn", onclick:openModal}, "⤢  View full page"),
        h("button",{id:"trk-close-link", onclick:closeTracker}, "Close"),
      ),
    );

    /* Modal overlay */
    const modalOverlay = h("div", {id:"trk-modal-overlay"});
    modalOverlay.addEventListener("click", e => { if (e.target===modalOverlay) closeModal(); });

    const modal = h("div", {id:"trk-modal"},
      h("div", {id:"trk-modal-accent"}),
      h("div", {id:"trk-modal-header"},
        h("div", {id:"trk-modal-chip-row"},
          h("div", {id:"trk-modal-chip"},
            h("span",{id:"trk-modal-chip-icon"}),
            h("span",{id:"trk-modal-chip-label"}),
            h("span",{id:"trk-modal-chip-id"}),
          ),
          h("button",{id:"trk-modal-close-btn","aria-label":"Close modal",onclick:closeModal},"×"),
        ),
        h("div",{id:"trk-modal-title-row"},
          h("h2", {id:"trk-modal-title"}),
          h("span",{id:"trk-modal-badge"}),
        ),
        h("div",{id:"trk-modal-subtitle"}),
        h("div",{id:"trk-modal-stats"}),
      ),
      h("div",{id:"trk-modal-body"}),
      h("div",{id:"trk-modal-footer"},
        h("button",{id:"trk-modal-close-link",onclick:closeModal},"✕  Close"),
      ),
    );
    modalOverlay.appendChild(modal);

    document.body.appendChild(overlay);
    document.body.appendChild(panel);
    document.body.appendChild(modalOverlay);
  }

  /* ═══════════════════════════════════════════════
     RENDER HELPERS
  ═══════════════════════════════════════════════ */

  function renderSkeleton(bodyEl) {
    bodyEl.innerHTML = "";
    const statsRow = h("div",{style:{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:"8px",marginBottom:"28px",gridColumn:"1/-1"}});
    for (let i=0;i<4;i++) statsRow.appendChild(h("div",{class:"trk-skel",style:{height:"52px",borderRadius:"8px",animationDelay:`${i*.08}s`}}));
    bodyEl.appendChild(statsRow);
    for (let i=0;i<4;i++) {
      const row = h("div",{class:"trk-skel-row"});
      row.appendChild(h("div",{class:"trk-skel trk-skel-circ",style:{animationDelay:`${i*.1}s`}}));
      const lines = h("div",{style:{flex:1}});
      lines.appendChild(h("div",{class:"trk-skel",style:{height:"10px",width:"75%",marginBottom:"6px",animationDelay:`${i*.1}s`}}));
      lines.appendChild(h("div",{class:"trk-skel",style:{height:"9px",width:"50%",animationDelay:`${i*.12}s`}}));
      row.appendChild(lines); bodyEl.appendChild(row);
    }
  }

  function renderEfris(efris) {
    if (!efris) return null;
    const cfg = efrisCfg(efris.status);
    if (!cfg) return null;
    return h("div",{class:"trk-efris",style:{background:cfg.bg,border:`1px solid ${cfg.color}30`}},
      h("span",{class:"trk-efris-icon",style:{color:cfg.color}},cfg.icon),
      h("div",{},
        h("div",{class:"trk-efris-status",style:{color:cfg.color}},`EFRIS · ${cfg.label.toUpperCase()}`),
        efris.reference ? h("div",{class:"trk-efris-ref",style:{color:cfg.color}},efris.reference) : null,
        efris.synced_at ? h("div",{class:"trk-efris-date"},`Synced ${fmtDate(efris.synced_at)}`) : null,
      ),
    );
  }

  function renderSecHeader(title,count) {
    return h("div",{class:"trk-sec-header"},
      h("span",{class:"trk-sec-title"},title),
      count!=null ? h("span",{class:"trk-sec-count"},String(count)) : null,
      h("div",{class:"trk-sec-line"}),
    );
  }

  function renderTimeline(items) {
    const wrap = h("div",{class:"trk-timeline"});
    wrap.appendChild(h("div",{class:"trk-tl-spine"}));
    (items||[]).forEach(item => {
      const clr   = tagColor(item.tag||item.label);
      const isPos = (item.qty||"").startsWith("+");
      const topRow = h("div",{class:"trk-tl-toprow"});
      if (item.tag) topRow.appendChild(h("span",{class:"trk-tag",style:{background:`${clr}18`,color:clr,border:`1px solid ${clr}25`}},item.tag));
      if (item.sub) topRow.appendChild(h("span",{class:"trk-tl-sub"},item.sub));
      if (item.qty) topRow.appendChild(h("span",{class:"trk-tl-qty",style:{color:isPos?"#22c55e":"#ef4444"}},item.qty));
      const metaRow = h("div",{class:"trk-tl-meta"},
        h("span",{},item.user||""),
        h("span",{class:"trk-dot-sep"},"·"),
        h("span",{},fmtDate(item.date)),
      );
      if (item.running) metaRow.appendChild(h("span",{class:"trk-tl-running"},`→ ${item.running}`));
      const dot = h("div",{class:"trk-tl-dot",style:{background:`${clr}18`,border:`1.5px solid ${clr}`}},
        h("div",{class:"trk-tl-dot-inner",style:{background:clr}}));
      wrap.appendChild(h("div",{class:"trk-tl-item"},dot,
        h("div",{class:"trk-tl-content"},topRow,
          h("div",{class:"trk-tl-label"},item.label||""),
          item.note?h("div",{class:"trk-tl-note"},item.note):null,
          metaRow,
        )
      ));
    });
    return wrap;
  }

  function renderAudit(items) {
    const wrap = h("div",{});
    (items||[]).forEach(item => {
      const clr   = sevColor(item.severity);
      const inner = h("div",{},h("div",{class:"trk-audit-desc"},item.description||""));
      if (item.diff) {
        inner.appendChild(h("div",{class:"trk-diff-row"},
          h("span",{class:"trk-diff-from"},item.diff.from),
          h("span",{class:"trk-diff-arrow"},"→"),
          h("span",{class:"trk-diff-to"},item.diff.to),
        ));
      }
      inner.appendChild(h("div",{class:"trk-audit-meta"},`${item.user||"System"} · ${fmtDate(item.date)}`));
      wrap.appendChild(h("div",{class:"trk-audit-item"},
        h("div",{class:"trk-sev-dot",style:{background:clr,boxShadow:`0 0 5px ${clr}66`}}),
        inner,
      ));
    });
    return wrap;
  }

  function renderTable(section) {
    const cols = section.columns||[]; const rows = section.rows||[];
    const thead = h("thead",{},h("tr",{},
      ...cols.map((c,i)=>h("th",{style:{textAlign:i===0?"left":"right"}},c)),
    ));
    const tbody = h("tbody",{});
    rows.forEach(row=>{
      const tr=h("tr",{});
      row.forEach((cell,ci)=>tr.appendChild(h("td",{
        class:ci===row.length-1?"trk-td-last":"",
        style:{textAlign:ci===0?"left":"right"},
      },cell)));
      tbody.appendChild(tr);
    });
    return h("div",{class:"trk-table-wrap"},h("table",{class:"trk-table"},thead,tbody));
  }

  function renderKeyvalue(section) {
    const grid = h("div",{class:"trk-kv-grid"});
    (section.pairs||[]).forEach(pair=>grid.appendChild(h("div",{class:"trk-kv-item"},
      h("div",{class:"trk-kv-label"},pair.label),
      h("div",{class:"trk-kv-value"},pair.value),
    )));
    return grid;
  }

  /**
   * Render one section.
   * inModal=true  → wide sections (non-keyvalue) get class 'trk-wide'
   *                 so the 2-col grid spans them full width.
   */
  function renderSection(section, inModal=false) {
    const count = section.items?.length ?? section.rows?.length ?? section.pairs?.length;
    const isWide = section.type !== "keyvalue";
    const cls = "trk-section" + (inModal && isWide ? " trk-wide" : "");
    const wrap = h("div",{class:cls}, renderSecHeader(section.title,count));
    if      (section.type==="timeline") wrap.appendChild(renderTimeline(section.items));
    else if (section.type==="audit")    wrap.appendChild(renderAudit(section.items));
    else if (section.type==="table"||section.type==="lineitems") wrap.appendChild(renderTable(section));
    else if (section.type==="keyvalue") wrap.appendChild(renderKeyvalue(section));
    return wrap;
  }

  /* ═══════════════════════════════════════════════
     SHARED HEADER FILL  (drawer + modal share this)
  ═══════════════════════════════════════════════ */

  function applyHeader(prefix, data, type, id) {
    const meta      = data.meta  || {};
    const stats     = data.stats || [];
    const typeColor = TYPE_COLORS[type] || "#0ea5e9";
    const bs        = badgeStyle(meta.badge_color);

    // Accent bar
    document.getElementById(`${prefix}-accent`).style.background =
      `linear-gradient(90deg,transparent,${typeColor},transparent)`;
    // Pass accent to panel/modal for button hover colour
    const root = prefix==="trk-panel"
      ? document.getElementById("trk-panel")
      : document.getElementById("trk-modal");
    root.style.setProperty("--trk-accent", typeColor);

    // Chip
    const icon  = document.getElementById(`${prefix}-chip-icon`);
    const label = document.getElementById(`${prefix}-chip-label`);
    const cid   = document.getElementById(`${prefix}-chip-id`);
    icon.textContent  = TYPE_ICONS[type] || "·";
    icon.style.color  = typeColor;
    label.textContent = `${type.charAt(0).toUpperCase()+type.slice(1)} Tracker`;
    label.style.color = typeColor;
    cid.textContent   = meta.id_label ? `· ${meta.id_label}` : "";

    // Title + badge
    document.getElementById(`${prefix}-title`).textContent = meta.title || `#${id}`;
    const badge = document.getElementById(`${prefix}-badge`);
    if (meta.badge) {
      badge.textContent = meta.badge;
      badge.style.display = "";
      Object.assign(badge.style, {background:bs.bg,color:bs.color,border:`1px solid ${bs.bd}`});
    } else {
      badge.style.display = "none";
    }
    document.getElementById(`${prefix}-subtitle`).textContent = meta.subtitle || "";

    // Stats
    const statsEl = document.getElementById(`${prefix}-stats`);
    statsEl.innerHTML = "";
    stats.forEach(s => {
      const clr = statColor(s.color);
      statsEl.appendChild(h("div",{class:"trk-stat",style:{"--trk-stat-color":clr}},
        h("div",{class:"trk-stat-label"},s.label),
        h("div",{class:"trk-stat-value",style:{color:clr}},s.value),
      ));
    });
  }

  /* ═══════════════════════════════════════════════
     RENDER DRAWER BODY
  ═══════════════════════════════════════════════ */

  function renderDrawer(data, type, id) {
    applyHeader("trk-panel", data, type, id);

    const typeColor = TYPE_COLORS[type] || "#0ea5e9";
    document.getElementById("trk-footer-meta").textContent = `${type} · id ${id}`;
    const cl = document.getElementById("trk-close-link");
    Object.assign(cl.style, {background:`${typeColor}18`,color:typeColor,border:`1px solid ${typeColor}40`});

    const body = document.getElementById("trk-body");
    body.innerHTML = "";
    const efrisEl = renderEfris(data.efris);
    if (efrisEl) body.appendChild(efrisEl);
    const sects = data.sections || [];
    if (!sects.length) {
      body.appendChild(h("div",{style:{textAlign:"center",padding:"40px 20px",
        color:"var(--trk-dim)",fontSize:"12px",fontFamily:"'DM Mono',monospace"}},
        "No tracking data available for this record."));
    } else {
      sects.forEach(sec => body.appendChild(renderSection(sec, false)));
    }
  }

  /* ═══════════════════════════════════════════════
     MODAL — "View full page"
  ═══════════════════════════════════════════════ */

  function openModal() {
    if (!_currentData) return;
    const {data, type, id} = _currentData;
    const typeColor = TYPE_COLORS[type] || "#0ea5e9";

    applyHeader("trk-modal", data, type, id);

    // Style close button
    const cl = document.getElementById("trk-modal-close-link");
    Object.assign(cl.style, {
      background:`${typeColor}18`, color:typeColor,
      border:`1px solid ${typeColor}40`,
      padding:"8px 22px", borderRadius:"8px",
      fontSize:"12px", fontFamily:"'DM Mono',monospace",
    });

    // Populate body (2-col)
    const body = document.getElementById("trk-modal-body");
    body.innerHTML = "";
    const efrisEl = renderEfris(data.efris);
    if (efrisEl) body.appendChild(efrisEl);
    (data.sections||[]).forEach(sec => body.appendChild(renderSection(sec, true)));

    document.getElementById("trk-modal-overlay").classList.add("trk-visible");
  }

  function closeModal() {
    document.getElementById("trk-modal-overlay").classList.remove("trk-visible");
  }

  /* ═══════════════════════════════════════════════
     OPEN / CLOSE DRAWER
  ═══════════════════════════════════════════════ */

  let _currentType = null;
  let _currentId   = null;
  let _currentData = null;   // { data, type, id } — held for modal

  function openTracker(type, id, label) {
    _currentType = type;
    _currentId   = id;
    _currentData = null;

    // Ensure the shell has been built before trying to access any DOM elements.
    // Guards against callers invoking PrimeTracker.open() before DOMContentLoaded.
    injectStyles();
    buildShell();

    document.getElementById("trk-overlay").classList.add("trk-visible");
    document.getElementById("trk-panel").classList.add("trk-visible");
    document.body.style.overflow = "hidden";

    // Instant title
    document.getElementById("trk-title").textContent    = label || "Loading…";
    document.getElementById("trk-subtitle").textContent = "";
    document.getElementById("trk-badge").style.display  = "none";
    document.getElementById("trk-stats").innerHTML      = "";
    document.getElementById("trk-expand-btn").style.display = "none";

    // Accent + chip immediately
    const typeColor = TYPE_COLORS[type] || "#0ea5e9";
    document.getElementById("trk-panel").style.setProperty("--trk-accent", typeColor);
    document.getElementById("trk-panel-accent").style.background =
      `linear-gradient(90deg,transparent,${typeColor},transparent)`;
    document.getElementById("trk-chip-icon").textContent  = TYPE_ICONS[type]||"·";
    document.getElementById("trk-chip-icon").style.color  = typeColor;
    document.getElementById("trk-chip-label").textContent = `${type.charAt(0).toUpperCase()+type.slice(1)} Tracker`;
    document.getElementById("trk-chip-label").style.color = typeColor;
    document.getElementById("trk-chip-id").textContent    = "";

    renderSkeleton(document.getElementById("trk-body"));

    fetch(`${API_BASE}?type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}`, {
      headers:{"X-CSRFToken":getCookie(CSRF_COOKIE),"Accept":"application/json"},
      credentials:"same-origin",
    })
      .then(r => {
        if (!r.ok) return r.json().then(d=>Promise.reject(d.error||`HTTP ${r.status}`));
        return r.json();
      })
      .then(data => {
        if (_currentId !== id) return;
        _currentData = {data, type, id};
        renderDrawer(data, type, id);
        document.getElementById("trk-expand-btn").style.display = "";
      })
      .catch(err => {
        if (_currentId !== id) return;
        const body = document.getElementById("trk-body");
        body.innerHTML = "";
        body.appendChild(h("div",{class:"trk-error-box"},
          h("div",{class:"trk-error-icon"},"⚠"),
          h("div",{class:"trk-error-msg"},"Could not load tracking data"),
          h("div",{class:"trk-error-det"},String(err)),
        ));
      });
  }

  function closeTracker() {
    _currentId   = null;
    _currentData = null;
    closeModal();
    document.getElementById("trk-overlay").classList.remove("trk-visible");
    document.getElementById("trk-panel").classList.remove("trk-visible");
    document.body.style.overflow = "";
  }

  /* ═══════════════════════════════════════════════
     EVENT DELEGATION  — works on dynamic rows too
  ═══════════════════════════════════════════════ */

  document.addEventListener("click", e => {
    const btn = e.target.closest("[data-track]");
    if (!btn) return;
    e.preventDefault();
    const type  = btn.dataset.track;
    const id    = btn.dataset.id;
    const label = btn.dataset.label || btn.textContent.trim() || "";
    if (!type || !id) return;
    openTracker(type, id, label);
  });

  document.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    // Close modal first if open, then drawer
    const mo = document.getElementById("trk-modal-overlay");
    if (mo && mo.classList.contains("trk-visible")) { closeModal(); return; }
    closeTracker();
  });

  /* ═══════════════════════════════════════════════
     INIT
  ═══════════════════════════════════════════════ */

  function init() { injectStyles(); buildShell(); }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Public API
  window.PrimeTracker = { open:openTracker, close:closeTracker, openModal };

})();/**
 * ╔══════════════════════════════════════════════════════════════════╗
 * ║  PrimeBooks — Universal Tracker  (tracker.js)                   ║
 * ║                                                                  ║
 * ║  Zero dependencies. Include once in base.html.                  ║
 * ║                                                                  ║
 * ║  INCLUDE IN BASE TEMPLATE (before </body>):                     ║
 * ║    <script src="{% static 'js/tracker.js' %}"></script>         ║
 * ║                                                                  ║
 * ║  ADD TO ANY BUTTON:                                              ║
 * ║    <button data-track="product" data-id="{{ product.pk }}"      ║
 * ║            data-label="{{ product.name }}">Track</button>        ║
 * ║                                                                  ║
 * ║  THEME                                                           ║
 * ║    Reads your existing [data-theme='dark'] switcher on <html>.  ║
 * ║    Light mode = default.  Dark = [data-theme='dark'].           ║
 * ║    Theme switches instantly — no JS needed, just CSS vars.      ║
 * ║                                                                  ║
 * ║  "VIEW FULL PAGE" opens a full-screen modal overlay showing     ║
 * ║    the same data in a 2-column layout.                          ║
 * ╚══════════════════════════════════════════════════════════════════╝
 */

(function () {
  "use strict";

  const API_BASE    = "/api/track/";
  const CSRF_COOKIE = "csrftoken";

  /* ═══════════════════════════════════════════════════════════════════
     CSS
     Light theme is the default.
     [data-theme='dark'] on <html> overrides all colour tokens.
     Works instantly with your existing theme switcher — zero JS.
  ═══════════════════════════════════════════════════════════════════ */

  const CSS = `
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:ital,wght@0,300;0,400;0,500;1,300&family=Syne:wght@600;700;800&display=swap');

    /* ── LIGHT (default) ────────────────────────────────────────────── */
    :root {
      --trk-bg:               #ffffff;
      --trk-s1:               #f8fafc;
      --trk-s2:               #f1f5f9;
      --trk-s3:               #e9eef6;
      --trk-bd:               #dde3ec;
      --trk-bd2:              #cbd5e1;
      --trk-text:             #0f172a;
      --trk-sub:              #475569;
      --trk-dim:              #94a3b8;
      --trk-overlay:          rgba(15,23,42,0.45);
      --trk-shadow:           rgba(15,23,42,0.18);
      --trk-table-zebra:      rgba(241,245,249,0.7);
      --trk-diff-from-bg:     #fef2f2;
      --trk-diff-from-color:  #dc2626;
      --trk-diff-from-bd:     #fecaca;
      --trk-diff-to-bg:       #f0fdf4;
      --trk-diff-to-color:    #16a34a;
      --trk-diff-to-bd:       #bbf7d0;
      --trk-td-last:          #16a34a;
      --trk-error-color:      #dc2626;
      --trk-mono:             'DM Mono', monospace;
      --trk-display:          'Syne', sans-serif;
    }

    /* ── DARK — your [data-theme='dark'] switcher triggers this ─────── */
    [data-theme='dark'] {
      --trk-bg:               #060f1c;
      --trk-s1:               #0a1628;
      --trk-s2:               #0e1d32;
      --trk-s3:               #12233b;
      --trk-bd:               #172338;
      --trk-bd2:              #1e2f45;
      --trk-text:             #ddeaf7;
      --trk-sub:              #4d6a87;
      --trk-dim:              #243550;
      --trk-overlay:          rgba(2,8,20,0.82);
      --trk-shadow:           rgba(0,0,0,0.65);
      --trk-table-zebra:      rgba(14,29,50,0.4);
      --trk-diff-from-bg:     #240808;
      --trk-diff-from-color:  #f87171;
      --trk-diff-from-bd:     rgba(248,113,113,0.15);
      --trk-diff-to-bg:       #042214;
      --trk-diff-to-color:    #4ade80;
      --trk-diff-to-bd:       rgba(74,222,128,0.15);
      --trk-td-last:          #4ade80;
      --trk-error-color:      #f87171;
    }

    /* ── OVERLAY ────────────────────────────────────────────────────── */
    #trk-overlay {
      position:fixed; inset:0; z-index:9998;
      background:var(--trk-overlay);
      backdrop-filter:blur(8px); -webkit-backdrop-filter:blur(8px);
      opacity:0; transition:opacity .25s ease; pointer-events:none;
    }
    #trk-overlay.trk-visible { opacity:1; pointer-events:all; }

    /* ── DRAWER PANEL ───────────────────────────────────────────────── */
    #trk-panel {
      position:fixed; top:0; right:0; bottom:0;
      width:min(600px,100vw); z-index:9999;
      background:var(--trk-bg);
      border-left:1px solid var(--trk-bd2);
      box-shadow:-24px 0 80px var(--trk-shadow);
      display:flex; flex-direction:column;
      transform:translateX(100%);
      transition:transform .32s cubic-bezier(.22,.68,0,1.08);
      font-family:var(--trk-display);
    }
    #trk-panel.trk-visible { transform:translateX(0); }

    #trk-panel-accent {
      height:2px; flex-shrink:0;
      background:linear-gradient(90deg,transparent,var(--trk-accent,#0ea5e9),transparent);
    }

    /* ── HEADER ─────────────────────────────────────────────────────── */
    #trk-header {
      padding:18px 24px 16px;
      border-bottom:1px solid var(--trk-bd2); flex-shrink:0;
    }
    #trk-chip-row {
      display:flex; align-items:center;
      justify-content:space-between; margin-bottom:12px;
    }
    #trk-chip { display:flex; align-items:center; gap:7px; }
    #trk-chip-icon { font-size:14px; }
    #trk-chip-label {
      font-size:9px; font-family:var(--trk-mono);
      letter-spacing:.18em; text-transform:uppercase;
    }
    #trk-chip-id {
      font-size:10px; font-family:var(--trk-mono);
      color:var(--trk-sub); margin-left:4px;
    }
    #trk-close-btn {
      width:30px; height:30px; border-radius:7px;
      border:1px solid var(--trk-bd2); background:transparent;
      color:var(--trk-sub); font-size:18px; cursor:pointer;
      display:flex; align-items:center; justify-content:center;
      transition:all .14s; line-height:1;
    }
    #trk-close-btn:hover { background:var(--trk-s3); color:var(--trk-text); }

    #trk-title-row { display:flex; align-items:flex-start; gap:10px; margin-bottom:4px; }
    #trk-title {
      flex:1; font-size:21px; font-weight:800; color:var(--trk-text);
      letter-spacing:-.03em; line-height:1.2;
    }
    #trk-badge {
      font-size:10px; padding:3px 11px; border-radius:20px;
      font-family:var(--trk-mono); font-weight:600;
      flex-shrink:0; margin-top:3px;
    }
    #trk-subtitle {
      font-size:12px; color:var(--trk-sub);
      font-family:var(--trk-mono); margin-bottom:14px;
    }

    #trk-stats {
      display:grid; gap:8px;
      grid-template-columns:repeat(auto-fit,minmax(110px,1fr));
    }
    .trk-stat {
      background:var(--trk-s2); border:1px solid var(--trk-bd2);
      border-radius:8px; padding:8px 11px; transition:border-color .15s;
    }
    .trk-stat:hover { border-color:var(--trk-stat-color,var(--trk-bd2)); }
    .trk-stat-label {
      font-size:9px; color:var(--trk-sub); font-family:var(--trk-mono);
      letter-spacing:.06em; margin-bottom:4px;
    }
    .trk-stat-value { font-size:12px; font-weight:700; font-family:var(--trk-mono); line-height:1.2; }

    /* ── BODY ───────────────────────────────────────────────────────── */
    #trk-body {
      flex:1; overflow-y:auto; padding:22px 24px;
      scrollbar-width:thin; scrollbar-color:var(--trk-bd2) transparent;
    }
    #trk-body::-webkit-scrollbar { width:3px; }
    #trk-body::-webkit-scrollbar-thumb { background:var(--trk-bd2); border-radius:3px; }

    /* ── FOOTER ─────────────────────────────────────────────────────── */
    #trk-footer {
      padding:12px 24px; border-top:1px solid var(--trk-bd2);
      flex-shrink:0; display:flex; gap:8px; align-items:center;
    }
    #trk-footer-meta {
      flex:1; font-size:10px; color:var(--trk-dim); font-family:var(--trk-mono);
    }
    #trk-expand-btn {
      padding:7px 15px; border-radius:7px;
      border:1px solid var(--trk-bd2); background:var(--trk-s2);
      color:var(--trk-sub); font-size:11px; font-family:var(--trk-mono);
      cursor:pointer; transition:all .13s;
    }
    #trk-expand-btn:hover { color:var(--trk-text); background:var(--trk-s3); }
    #trk-close-link {
      padding:7px 18px; border-radius:7px;
      font-size:11px; font-family:var(--trk-mono);
      cursor:pointer; transition:all .13s; border:1px solid transparent;
    }

    /* ═══════════════════════════════════════════════════════════════
       MODAL  — "View full page"
       A centred overlay that shows the same data in a 2-col layout.
    ═══════════════════════════════════════════════════════════════ */
    #trk-modal-overlay {
      position:fixed; inset:0; z-index:10000;
      background:var(--trk-overlay);
      backdrop-filter:blur(10px); -webkit-backdrop-filter:blur(10px);
      display:flex; align-items:center; justify-content:center; padding:24px;
      opacity:0; pointer-events:none; transition:opacity .22s ease;
    }
    #trk-modal-overlay.trk-visible { opacity:1; pointer-events:all; }

    #trk-modal {
      background:var(--trk-bg);
      border:1px solid var(--trk-bd2);
      border-radius:14px;
      box-shadow:0 32px 100px var(--trk-shadow);
      width:min(940px,100%); max-height:calc(100vh - 48px);
      display:flex; flex-direction:column;
      transform:scale(.96) translateY(8px);
      transition:transform .24s cubic-bezier(.22,.68,0,1.08);
      font-family:var(--trk-display); overflow:hidden;
    }
    #trk-modal-overlay.trk-visible #trk-modal { transform:scale(1) translateY(0); }

    #trk-modal-accent {
      height:3px; flex-shrink:0;
      background:linear-gradient(90deg,transparent,var(--trk-accent,#0ea5e9),transparent);
    }

    #trk-modal-header {
      padding:20px 28px 18px;
      border-bottom:1px solid var(--trk-bd2); flex-shrink:0;
    }
    #trk-modal-chip-row {
      display:flex; align-items:center;
      justify-content:space-between; margin-bottom:14px;
    }
    #trk-modal-chip { display:flex; align-items:center; gap:8px; }
    #trk-modal-chip-icon  { font-size:15px; }
    #trk-modal-chip-label {
      font-size:9px; font-family:var(--trk-mono);
      letter-spacing:.18em; text-transform:uppercase;
    }
    #trk-modal-chip-id {
      font-size:10px; font-family:var(--trk-mono);
      color:var(--trk-sub); margin-left:4px;
    }
    #trk-modal-close-btn {
      width:32px; height:32px; border-radius:8px;
      border:1px solid var(--trk-bd2); background:transparent;
      color:var(--trk-sub); font-size:19px; cursor:pointer;
      display:flex; align-items:center; justify-content:center;
      transition:all .14s; line-height:1;
    }
    #trk-modal-close-btn:hover { background:var(--trk-s3); color:var(--trk-text); }

    #trk-modal-title-row { display:flex; align-items:flex-start; gap:10px; margin-bottom:5px; }
    #trk-modal-title {
      flex:1; font-size:26px; font-weight:800; color:var(--trk-text);
      letter-spacing:-.03em; line-height:1.2;
    }
    #trk-modal-badge {
      font-size:10px; padding:3px 12px; border-radius:20px;
      font-family:var(--trk-mono); font-weight:600;
      flex-shrink:0; margin-top:5px;
    }
    #trk-modal-subtitle {
      font-size:12px; color:var(--trk-sub);
      font-family:var(--trk-mono); margin-bottom:16px;
    }
    #trk-modal-stats {
      display:grid; gap:10px;
      grid-template-columns:repeat(auto-fit,minmax(130px,1fr));
    }

    /* 2-column body */
    #trk-modal-body {
      flex:1; overflow-y:auto; padding:28px;
      display:grid; grid-template-columns:1fr 1fr; gap:0 32px; align-content:start;
      scrollbar-width:thin; scrollbar-color:var(--trk-bd2) transparent;
    }
    #trk-modal-body::-webkit-scrollbar { width:3px; }
    #trk-modal-body::-webkit-scrollbar-thumb { background:var(--trk-bd2); }
    /* Full-width items in modal */
    #trk-modal-body > .trk-efris    { grid-column:1/-1; }
    #trk-modal-body > .trk-wide     { grid-column:1/-1; }

    #trk-modal-footer {
      padding:13px 28px; border-top:1px solid var(--trk-bd2);
      flex-shrink:0; display:flex; justify-content:flex-end; gap:8px;
    }
    #trk-modal-close-link {
      padding:8px 22px; border-radius:8px; border:1px solid transparent;
      font-size:12px; font-family:var(--trk-mono); cursor:pointer; transition:all .13s;
    }

    /* ── EFRIS BLOCK ────────────────────────────────────────────────── */
    .trk-efris {
      display:flex; align-items:flex-start; gap:12px;
      padding:12px 16px; border-radius:9px; margin-bottom:28px;
    }
    .trk-efris-icon   { font-size:20px; line-height:1; margin-top:1px; }
    .trk-efris-status { font-size:10px; font-family:var(--trk-mono); font-weight:700; letter-spacing:.08em; margin-bottom:3px; }
    .trk-efris-ref    { font-size:11px; font-family:var(--trk-mono); opacity:.8; margin-bottom:2px; }
    .trk-efris-date   { font-size:10.5px; color:var(--trk-sub); font-family:var(--trk-mono); }

    /* ── SECTION ────────────────────────────────────────────────────── */
    .trk-section { margin-bottom:28px; }
    .trk-sec-header { display:flex; align-items:center; gap:8px; margin-bottom:16px; }
    .trk-sec-title {
      font-size:9px; font-family:var(--trk-mono); color:var(--trk-dim);
      text-transform:uppercase; letter-spacing:.14em; white-space:nowrap;
    }
    .trk-sec-count {
      font-size:9px; background:var(--trk-s3); color:var(--trk-sub);
      border:1px solid var(--trk-bd2); padding:1px 7px; border-radius:20px;
      font-family:var(--trk-mono);
    }
    .trk-sec-line { flex:1; height:1px; background:var(--trk-bd2); }

    /* ── TIMELINE ───────────────────────────────────────────────────── */
    .trk-timeline { position:relative; }
    .trk-tl-spine {
      position:absolute; left:14px; top:8px; bottom:4px;
      width:1px; background:var(--trk-bd2);
    }
    .trk-tl-item { display:flex; gap:14px; padding-left:36px; position:relative; margin-bottom:20px; }
    .trk-tl-item:last-child { margin-bottom:0; }
    .trk-tl-dot {
      position:absolute; left:7px; top:3px;
      width:15px; height:15px; border-radius:50%;
      display:flex; align-items:center; justify-content:center; flex-shrink:0;
    }
    .trk-tl-dot-inner { width:5px; height:5px; border-radius:50%; }
    .trk-tl-content { flex:1; min-width:0; }
    .trk-tl-toprow { display:flex; align-items:center; flex-wrap:wrap; gap:6px; margin-bottom:4px; }
    .trk-tag { font-size:9px; padding:2px 8px; border-radius:4px; font-family:var(--trk-mono); font-weight:600; letter-spacing:.06em; }
    .trk-tl-sub   { font-size:11px; color:var(--trk-sub); font-family:var(--trk-mono); }
    .trk-tl-qty   { margin-left:auto; font-family:var(--trk-mono); font-size:13px; font-weight:700; }
    .trk-tl-label { font-size:12.5px; color:var(--trk-text); font-weight:600; margin-bottom:3px; line-height:1.3; }
    .trk-tl-note  { font-size:11.5px; color:var(--trk-sub); margin-bottom:4px; line-height:1.4; }
    .trk-tl-meta  { display:flex; align-items:center; gap:7px; flex-wrap:wrap; font-size:10.5px; color:var(--trk-dim); font-family:var(--trk-mono); }
    .trk-tl-running { margin-left:auto; color:var(--trk-sub); }
    .trk-dot-sep  { color:var(--trk-bd2); }

    /* ── AUDIT ──────────────────────────────────────────────────────── */
    .trk-audit-item { display:flex; gap:12px; margin-bottom:16px; align-items:flex-start; }
    .trk-audit-item:last-child { margin-bottom:0; }
    .trk-sev-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; margin-top:5px; }
    .trk-audit-desc { font-size:12.5px; color:var(--trk-text); font-weight:500; margin-bottom:4px; line-height:1.35; }
    .trk-diff-row { display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-bottom:5px; }
    .trk-diff-from {
      font-size:10px; font-family:var(--trk-mono); padding:2px 7px; border-radius:4px;
      background:var(--trk-diff-from-bg); color:var(--trk-diff-from-color); border:1px solid var(--trk-diff-from-bd);
    }
    .trk-diff-arrow { color:var(--trk-dim); font-size:11px; }
    .trk-diff-to {
      font-size:10px; font-family:var(--trk-mono); padding:2px 7px; border-radius:4px;
      background:var(--trk-diff-to-bg); color:var(--trk-diff-to-color); border:1px solid var(--trk-diff-to-bd);
    }
    .trk-audit-meta { font-size:10.5px; color:var(--trk-dim); font-family:var(--trk-mono); }

    /* ── TABLE ──────────────────────────────────────────────────────── */
    .trk-table-wrap { border:1px solid var(--trk-bd2); border-radius:9px; overflow:hidden; }
    .trk-table { width:100%; border-collapse:collapse; font-size:12px; }
    .trk-table thead tr { background:var(--trk-s3); border-bottom:1px solid var(--trk-bd2); }
    .trk-table th {
      padding:9px 13px; font-size:9px; color:var(--trk-dim);
      font-family:var(--trk-mono); font-weight:600;
      letter-spacing:.1em; text-transform:uppercase;
    }
    .trk-table th:first-child { text-align:left; }
    .trk-table th:not(:first-child) { text-align:right; }
    .trk-table tbody tr { border-bottom:1px solid var(--trk-bd); }
    .trk-table tbody tr:last-child { border-bottom:none; }
    .trk-table tbody tr:nth-child(even) { background:var(--trk-table-zebra); }
    .trk-table td { padding:11px 13px; color:var(--trk-sub); font-family:var(--trk-mono); }
    .trk-table td:first-child { text-align:left; color:var(--trk-text); font-weight:600; font-family:var(--trk-display); }
    .trk-table td:not(:first-child) { text-align:right; }
    .trk-table td.trk-td-last { color:var(--trk-td-last); font-weight:700; }

    /* ── KEYVALUE ───────────────────────────────────────────────────── */
    .trk-kv-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
    .trk-kv-item { background:var(--trk-s2); border:1px solid var(--trk-bd2); border-radius:8px; padding:10px 12px; }
    .trk-kv-label { font-size:9px; color:var(--trk-sub); font-family:var(--trk-mono); letter-spacing:.06em; margin-bottom:4px; }
    .trk-kv-value { font-size:12.5px; color:var(--trk-text); font-weight:600; }

    /* ── SKELETON ───────────────────────────────────────────────────── */
    @keyframes trk-pulse { 0%,100%{opacity:.35} 50%{opacity:.75} }
    .trk-skel { border-radius:5px; background:var(--trk-s3); animation:trk-pulse 1.4s ease infinite; }
    .trk-skel-row { display:flex; gap:10px; margin-bottom:20px; }
    .trk-skel-circ { width:15px; height:15px; border-radius:50%; flex-shrink:0; }

    /* ── ERROR ──────────────────────────────────────────────────────── */
    .trk-error-box { text-align:center; padding:40px 20px; }
    .trk-error-icon { font-size:32px; margin-bottom:12px; }
    .trk-error-msg  { font-size:13px; color:var(--trk-error-color); margin-bottom:6px; }
    .trk-error-det  { font-size:11px; color:var(--trk-sub); font-family:var(--trk-mono); }

    /* ── TRACK BUTTONS (auto-styled) ────────────────────────────────── */
    [data-track] {
      display:inline-flex; align-items:center; gap:5px;
      padding:3px 10px; border-radius:6px; cursor:pointer;
      font-size:11px; font-family:var(--trk-mono);
      border:1px solid var(--trk-bd2); background:transparent;
      color:var(--trk-sub); transition:all .14s;
      white-space:nowrap; user-select:none;
    }
    [data-track]:hover {
      border-color:var(--trk-accent,#0ea5e9);
      color:var(--trk-accent,#0ea5e9);
      background:color-mix(in srgb,var(--trk-accent,#0ea5e9) 8%,transparent);
    }
    [data-track]::before { content:attr(data-track-icon,'◎'); font-size:9px; }
  `;

  /* ═══════════════════════════════════════════════
     COLOUR MAPS
  ═══════════════════════════════════════════════ */

  const TYPE_COLORS = {
    product:"#0ea5e9", sale:"#22c55e",   invoice:"#8b5cf6",
    expense:"#f97316", user:"#ec4899",   customer:"#06b6d4",
    budget: "#84cc16", transfer:"#10b981",purchase:"#eab308",
    payment:"#38bdf8", report:"#64748b",
  };
  const TYPE_ICONS = {
    product:"⬡", sale:"◈",    invoice:"◇",  expense:"◉",
    user:"◎",    customer:"⊙", budget:"◑",   transfer:"⇄",
    purchase:"↓", payment:"◆", report:"▤",
  };

  const TAG_COLORS = {
    PURCHASE:"#22c55e",SALE:"#0ea5e9",RETURN:"#8b5cf6",VOID:"#ef4444",
    REFUND:"#f97316",ADJUSTMENT:"#eab308",TRANSFER_IN:"#10b981",TRANSFER_OUT:"#64748b",
    created:"#22c55e",updated:"#0ea5e9",deleted:"#ef4444",approved:"#22c55e",
    rejected:"#ef4444",paid:"#22c55e",sent:"#38bdf8",cancelled:"#ef4444",
    efris:"#8b5cf6",login:"#ec4899",locked:"#ef4444",
    login_success:"#22c55e",login_failed:"#ef4444",
  };
  const tagColor = (t) => TAG_COLORS[t] || TAG_COLORS[(t||"").toUpperCase()] || "#64748b";

  /* Badge colours split by theme */
  const BADGE_LIGHT = {
    green:  {bg:"#dcfce7",color:"#15803d",bd:"#86efac"},
    blue:   {bg:"#dbeafe",color:"#1d4ed8",bd:"#93c5fd"},
    purple: {bg:"#ede9fe",color:"#7c3aed",bd:"#c4b5fd"},
    red:    {bg:"#fee2e2",color:"#dc2626",bd:"#fca5a5"},
    yellow: {bg:"#fefce8",color:"#a16207",bd:"#fde047"},
    dim:    {bg:"#f1f5f9",color:"#475569",bd:"#cbd5e1"},
  };
  const BADGE_DARK = {
    green:  {bg:"#042214",color:"#4ade80",bd:"rgba(74,222,128,.18)"},
    blue:   {bg:"#051830",color:"#38bdf8",bd:"rgba(56,189,248,.18)"},
    purple: {bg:"#180d35",color:"#a78bfa",bd:"rgba(167,139,250,.18)"},
    red:    {bg:"#240808",color:"#f87171",bd:"rgba(248,113,113,.18)"},
    yellow: {bg:"#241c00",color:"#facc15",bd:"rgba(250,204,21,.18)"},
    dim:    {bg:"#0a1628",color:"#4d6a87",bd:"#172338"},
  };
  function badgeStyle(c) {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    return (dark ? BADGE_DARK : BADGE_LIGHT)[c] || (dark ? BADGE_DARK : BADGE_LIGHT).dim;
  }

  const SEV_COLORS = {
    info:"#0ea5e9",success:"#22c55e",warning:"#eab308",error:"#ef4444",critical:"#dc2626",
  };
  const sevColor = (s) => SEV_COLORS[s] || SEV_COLORS.info;

  const STAT_COLORS = {
    green:"#22c55e",blue:"#0ea5e9",purple:"#8b5cf6",
    red:"#ef4444",yellow:"#eab308",dim:"#64748b",
  };
  const statColor = (c) => STAT_COLORS[c] || STAT_COLORS.dim;

  /* EFRIS config split by theme */
  const EFRIS_LIGHT = {
    fiscalized:{label:"Fiscalized",  color:"#7c3aed",bg:"#ede9fe",icon:"⬡"},
    pending:   {label:"Pending Sync",color:"#a16207",bg:"#fefce8",icon:"◌"},
    failed:    {label:"Sync Failed", color:"#dc2626",bg:"#fee2e2",icon:"⚠"},
  };
  const EFRIS_DARK = {
    fiscalized:{label:"Fiscalized",  color:"#a78bfa",bg:"#180d35",icon:"⬡"},
    pending:   {label:"Pending Sync",color:"#facc15",bg:"#241c00",icon:"◌"},
    failed:    {label:"Sync Failed", color:"#f87171",bg:"#240808",icon:"⚠"},
  };
  function efrisCfg(status) {
    const dark = document.documentElement.getAttribute("data-theme") === "dark";
    return (dark ? EFRIS_DARK : EFRIS_LIGHT)[status] || null;
  }

  /* ═══════════════════════════════════════════════
     UTILITIES
  ═══════════════════════════════════════════════ */

  function fmtDate(d) {
    if (!d) return "—";
    try {
      const dt = new Date(d);
      return dt.toLocaleDateString("en-GB", {day:"2-digit",month:"short",year:"numeric"})
           + "  " + dt.toLocaleTimeString("en-GB", {hour:"2-digit",minute:"2-digit"});
    } catch { return d; }
  }

  function getCookie(name) {
    const m = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`));
    return m ? decodeURIComponent(m[1]) : "";
  }

  function h(tag, attrs={}, ...children) {
    const el = document.createElement(tag);
    for (const [k,v] of Object.entries(attrs)) {
      if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on")) el.addEventListener(k.slice(2).toLowerCase(), v);
      else el.setAttribute(k, v);
    }
    for (const c of children.flat(Infinity)) {
      if (c == null) continue;
      el.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return el;
  }

  /* ═══════════════════════════════════════════════
     DOM BUILD
  ═══════════════════════════════════════════════ */

  function injectStyles() {
    if (document.getElementById("trk-styles")) return;
    const s = document.createElement("style");
    s.id = "trk-styles"; s.textContent = CSS;
    document.head.appendChild(s);
  }

  function buildShell() {
    if (document.getElementById("trk-panel")) return;

    /* Drawer overlay */
    const overlay = h("div", {id:"trk-overlay"});
    overlay.addEventListener("click", closeTracker);

    /* Drawer panel */
    const panel = h("div", {id:"trk-panel"},
      h("div", {id:"trk-panel-accent"}),
      h("div", {id:"trk-header"},
        h("div", {id:"trk-chip-row"},
          h("div", {id:"trk-chip"},
            h("span", {id:"trk-chip-icon"}),
            h("span", {id:"trk-chip-label"}),
            h("span", {id:"trk-chip-id"}),
          ),
          h("button", {id:"trk-close-btn","aria-label":"Close tracker",onclick:closeTracker}, "×"),
        ),
        h("div", {id:"trk-title-row"},
          h("h2",  {id:"trk-title"}, "Loading…"),
          h("span",{id:"trk-badge"}),
        ),
        h("div", {id:"trk-subtitle"}),
        h("div", {id:"trk-stats"}),
      ),
      h("div", {id:"trk-body"}),
      h("div", {id:"trk-footer"},
        h("span",  {id:"trk-footer-meta"}),
        h("button",{id:"trk-expand-btn", onclick:openModal}, "⤢  View full page"),
        h("button",{id:"trk-close-link", onclick:closeTracker}, "Close"),
      ),
    );

    /* Modal overlay */
    const modalOverlay = h("div", {id:"trk-modal-overlay"});
    modalOverlay.addEventListener("click", e => { if (e.target===modalOverlay) closeModal(); });

    const modal = h("div", {id:"trk-modal"},
      h("div", {id:"trk-modal-accent"}),
      h("div", {id:"trk-modal-header"},
        h("div", {id:"trk-modal-chip-row"},
          h("div", {id:"trk-modal-chip"},
            h("span",{id:"trk-modal-chip-icon"}),
            h("span",{id:"trk-modal-chip-label"}),
            h("span",{id:"trk-modal-chip-id"}),
          ),
          h("button",{id:"trk-modal-close-btn","aria-label":"Close modal",onclick:closeModal},"×"),
        ),
        h("div",{id:"trk-modal-title-row"},
          h("h2", {id:"trk-modal-title"}),
          h("span",{id:"trk-modal-badge"}),
        ),
        h("div",{id:"trk-modal-subtitle"}),
        h("div",{id:"trk-modal-stats"}),
      ),
      h("div",{id:"trk-modal-body"}),
      h("div",{id:"trk-modal-footer"},
        h("button",{id:"trk-modal-close-link",onclick:closeModal},"✕  Close"),
      ),
    );
    modalOverlay.appendChild(modal);

    document.body.appendChild(overlay);
    document.body.appendChild(panel);
    document.body.appendChild(modalOverlay);
  }

  /* ═══════════════════════════════════════════════
     RENDER HELPERS
  ═══════════════════════════════════════════════ */

  function renderSkeleton(bodyEl) {
    bodyEl.innerHTML = "";
    const statsRow = h("div",{style:{display:"grid",gridTemplateColumns:"repeat(4,1fr)",gap:"8px",marginBottom:"28px",gridColumn:"1/-1"}});
    for (let i=0;i<4;i++) statsRow.appendChild(h("div",{class:"trk-skel",style:{height:"52px",borderRadius:"8px",animationDelay:`${i*.08}s`}}));
    bodyEl.appendChild(statsRow);
    for (let i=0;i<4;i++) {
      const row = h("div",{class:"trk-skel-row"});
      row.appendChild(h("div",{class:"trk-skel trk-skel-circ",style:{animationDelay:`${i*.1}s`}}));
      const lines = h("div",{style:{flex:1}});
      lines.appendChild(h("div",{class:"trk-skel",style:{height:"10px",width:"75%",marginBottom:"6px",animationDelay:`${i*.1}s`}}));
      lines.appendChild(h("div",{class:"trk-skel",style:{height:"9px",width:"50%",animationDelay:`${i*.12}s`}}));
      row.appendChild(lines); bodyEl.appendChild(row);
    }
  }

  function renderEfris(efris) {
    if (!efris) return null;
    const cfg = efrisCfg(efris.status);
    if (!cfg) return null;
    return h("div",{class:"trk-efris",style:{background:cfg.bg,border:`1px solid ${cfg.color}30`}},
      h("span",{class:"trk-efris-icon",style:{color:cfg.color}},cfg.icon),
      h("div",{},
        h("div",{class:"trk-efris-status",style:{color:cfg.color}},`EFRIS · ${cfg.label.toUpperCase()}`),
        efris.reference ? h("div",{class:"trk-efris-ref",style:{color:cfg.color}},efris.reference) : null,
        efris.synced_at ? h("div",{class:"trk-efris-date"},`Synced ${fmtDate(efris.synced_at)}`) : null,
      ),
    );
  }

  function renderSecHeader(title,count) {
    return h("div",{class:"trk-sec-header"},
      h("span",{class:"trk-sec-title"},title),
      count!=null ? h("span",{class:"trk-sec-count"},String(count)) : null,
      h("div",{class:"trk-sec-line"}),
    );
  }

  function renderTimeline(items) {
    const wrap = h("div",{class:"trk-timeline"});
    wrap.appendChild(h("div",{class:"trk-tl-spine"}));
    (items||[]).forEach(item => {
      const clr   = tagColor(item.tag||item.label);
      const isPos = (item.qty||"").startsWith("+");
      const topRow = h("div",{class:"trk-tl-toprow"});
      if (item.tag) topRow.appendChild(h("span",{class:"trk-tag",style:{background:`${clr}18`,color:clr,border:`1px solid ${clr}25`}},item.tag));
      if (item.sub) topRow.appendChild(h("span",{class:"trk-tl-sub"},item.sub));
      if (item.qty) topRow.appendChild(h("span",{class:"trk-tl-qty",style:{color:isPos?"#22c55e":"#ef4444"}},item.qty));
      const metaRow = h("div",{class:"trk-tl-meta"},
        h("span",{},item.user||""),
        h("span",{class:"trk-dot-sep"},"·"),
        h("span",{},fmtDate(item.date)),
      );
      if (item.running) metaRow.appendChild(h("span",{class:"trk-tl-running"},`→ ${item.running}`));
      const dot = h("div",{class:"trk-tl-dot",style:{background:`${clr}18`,border:`1.5px solid ${clr}`}},
        h("div",{class:"trk-tl-dot-inner",style:{background:clr}}));
      wrap.appendChild(h("div",{class:"trk-tl-item"},dot,
        h("div",{class:"trk-tl-content"},topRow,
          h("div",{class:"trk-tl-label"},item.label||""),
          item.note?h("div",{class:"trk-tl-note"},item.note):null,
          metaRow,
        )
      ));
    });
    return wrap;
  }

  function renderAudit(items) {
    const wrap = h("div",{});
    (items||[]).forEach(item => {
      const clr   = sevColor(item.severity);
      const inner = h("div",{},h("div",{class:"trk-audit-desc"},item.description||""));
      if (item.diff) {
        inner.appendChild(h("div",{class:"trk-diff-row"},
          h("span",{class:"trk-diff-from"},item.diff.from),
          h("span",{class:"trk-diff-arrow"},"→"),
          h("span",{class:"trk-diff-to"},item.diff.to),
        ));
      }
      inner.appendChild(h("div",{class:"trk-audit-meta"},`${item.user||"System"} · ${fmtDate(item.date)}`));
      wrap.appendChild(h("div",{class:"trk-audit-item"},
        h("div",{class:"trk-sev-dot",style:{background:clr,boxShadow:`0 0 5px ${clr}66`}}),
        inner,
      ));
    });
    return wrap;
  }

  function renderTable(section) {
    const cols = section.columns||[]; const rows = section.rows||[];
    const thead = h("thead",{},h("tr",{},
      ...cols.map((c,i)=>h("th",{style:{textAlign:i===0?"left":"right"}},c)),
    ));
    const tbody = h("tbody",{});
    rows.forEach(row=>{
      const tr=h("tr",{});
      row.forEach((cell,ci)=>tr.appendChild(h("td",{
        class:ci===row.length-1?"trk-td-last":"",
        style:{textAlign:ci===0?"left":"right"},
      },cell)));
      tbody.appendChild(tr);
    });
    return h("div",{class:"trk-table-wrap"},h("table",{class:"trk-table"},thead,tbody));
  }

  function renderKeyvalue(section) {
    const grid = h("div",{class:"trk-kv-grid"});
    (section.pairs||[]).forEach(pair=>grid.appendChild(h("div",{class:"trk-kv-item"},
      h("div",{class:"trk-kv-label"},pair.label),
      h("div",{class:"trk-kv-value"},pair.value),
    )));
    return grid;
  }

  /**
   * Render one section.
   * inModal=true  → wide sections (non-keyvalue) get class 'trk-wide'
   *                 so the 2-col grid spans them full width.
   */
  function renderSection(section, inModal=false) {
    const count = section.items?.length ?? section.rows?.length ?? section.pairs?.length;
    const isWide = section.type !== "keyvalue";
    const cls = "trk-section" + (inModal && isWide ? " trk-wide" : "");
    const wrap = h("div",{class:cls}, renderSecHeader(section.title,count));
    if      (section.type==="timeline") wrap.appendChild(renderTimeline(section.items));
    else if (section.type==="audit")    wrap.appendChild(renderAudit(section.items));
    else if (section.type==="table"||section.type==="lineitems") wrap.appendChild(renderTable(section));
    else if (section.type==="keyvalue") wrap.appendChild(renderKeyvalue(section));
    return wrap;
  }

  /* ═══════════════════════════════════════════════
     SHARED HEADER FILL  (drawer + modal share this)
  ═══════════════════════════════════════════════ */

  function applyHeader(prefix, data, type, id) {
    const meta      = data.meta  || {};
    const stats     = data.stats || [];
    const typeColor = TYPE_COLORS[type] || "#0ea5e9";
    const bs        = badgeStyle(meta.badge_color);

    // Accent bar
    document.getElementById(`${prefix}-accent`).style.background =
      `linear-gradient(90deg,transparent,${typeColor},transparent)`;
    // Pass accent to panel/modal for button hover colour
    const root = prefix==="trk-panel"
      ? document.getElementById("trk-panel")
      : document.getElementById("trk-modal");
    root.style.setProperty("--trk-accent", typeColor);

    // Chip
    const icon  = document.getElementById(`${prefix}-chip-icon`);
    const label = document.getElementById(`${prefix}-chip-label`);
    const cid   = document.getElementById(`${prefix}-chip-id`);
    icon.textContent  = TYPE_ICONS[type] || "·";
    icon.style.color  = typeColor;
    label.textContent = `${type.charAt(0).toUpperCase()+type.slice(1)} Tracker`;
    label.style.color = typeColor;
    cid.textContent   = meta.id_label ? `· ${meta.id_label}` : "";

    // Title + badge
    document.getElementById(`${prefix}-title`).textContent = meta.title || `#${id}`;
    const badge = document.getElementById(`${prefix}-badge`);
    if (meta.badge) {
      badge.textContent = meta.badge;
      badge.style.display = "";
      Object.assign(badge.style, {background:bs.bg,color:bs.color,border:`1px solid ${bs.bd}`});
    } else {
      badge.style.display = "none";
    }
    document.getElementById(`${prefix}-subtitle`).textContent = meta.subtitle || "";

    // Stats
    const statsEl = document.getElementById(`${prefix}-stats`);
    statsEl.innerHTML = "";
    stats.forEach(s => {
      const clr = statColor(s.color);
      statsEl.appendChild(h("div",{class:"trk-stat",style:{"--trk-stat-color":clr}},
        h("div",{class:"trk-stat-label"},s.label),
        h("div",{class:"trk-stat-value",style:{color:clr}},s.value),
      ));
    });
  }

  /* ═══════════════════════════════════════════════
     RENDER DRAWER BODY
  ═══════════════════════════════════════════════ */

  function renderDrawer(data, type, id) {
    applyHeader("trk-panel", data, type, id);

    const typeColor = TYPE_COLORS[type] || "#0ea5e9";
    document.getElementById("trk-footer-meta").textContent = `${type} · id ${id}`;
    const cl = document.getElementById("trk-close-link");
    Object.assign(cl.style, {background:`${typeColor}18`,color:typeColor,border:`1px solid ${typeColor}40`});

    const body = document.getElementById("trk-body");
    body.innerHTML = "";
    const efrisEl = renderEfris(data.efris);
    if (efrisEl) body.appendChild(efrisEl);
    const sects = data.sections || [];
    if (!sects.length) {
      body.appendChild(h("div",{style:{textAlign:"center",padding:"40px 20px",
        color:"var(--trk-dim)",fontSize:"12px",fontFamily:"'DM Mono',monospace"}},
        "No tracking data available for this record."));
    } else {
      sects.forEach(sec => body.appendChild(renderSection(sec, false)));
    }
  }

  /* ═══════════════════════════════════════════════
     MODAL — "View full page"
  ═══════════════════════════════════════════════ */

  function openModal() {
    if (!_currentData) return;
    const {data, type, id} = _currentData;
    const typeColor = TYPE_COLORS[type] || "#0ea5e9";

    applyHeader("trk-modal", data, type, id);

    // Style close button
    const cl = document.getElementById("trk-modal-close-link");
    Object.assign(cl.style, {
      background:`${typeColor}18`, color:typeColor,
      border:`1px solid ${typeColor}40`,
      padding:"8px 22px", borderRadius:"8px",
      fontSize:"12px", fontFamily:"'DM Mono',monospace",
    });

    // Populate body (2-col)
    const body = document.getElementById("trk-modal-body");
    body.innerHTML = "";
    const efrisEl = renderEfris(data.efris);
    if (efrisEl) body.appendChild(efrisEl);
    (data.sections||[]).forEach(sec => body.appendChild(renderSection(sec, true)));

    document.getElementById("trk-modal-overlay").classList.add("trk-visible");
  }

  function closeModal() {
    document.getElementById("trk-modal-overlay").classList.remove("trk-visible");
  }

  /* ═══════════════════════════════════════════════
     OPEN / CLOSE DRAWER
  ═══════════════════════════════════════════════ */

  let _currentType = null;
  let _currentId   = null;
  let _currentData = null;   // { data, type, id } — held for modal

  function openTracker(type, id, label) {
    _currentType = type;
    _currentId   = id;
    _currentData = null;

    // Ensure the shell has been built before trying to access any DOM elements.
    // Guards against callers invoking PrimeTracker.open() before DOMContentLoaded.
    injectStyles();
    buildShell();

    document.getElementById("trk-overlay").classList.add("trk-visible");
    document.getElementById("trk-panel").classList.add("trk-visible");
    document.body.style.overflow = "hidden";

    // Instant title
    document.getElementById("trk-title").textContent    = label || "Loading…";
    document.getElementById("trk-subtitle").textContent = "";
    document.getElementById("trk-badge").style.display  = "none";
    document.getElementById("trk-stats").innerHTML      = "";
    document.getElementById("trk-expand-btn").style.display = "none";

    // Accent + chip immediately
    const typeColor = TYPE_COLORS[type] || "#0ea5e9";
    document.getElementById("trk-panel").style.setProperty("--trk-accent", typeColor);
    document.getElementById("trk-panel-accent").style.background =
      `linear-gradient(90deg,transparent,${typeColor},transparent)`;
    document.getElementById("trk-chip-icon").textContent  = TYPE_ICONS[type]||"·";
    document.getElementById("trk-chip-icon").style.color  = typeColor;
    document.getElementById("trk-chip-label").textContent = `${type.charAt(0).toUpperCase()+type.slice(1)} Tracker`;
    document.getElementById("trk-chip-label").style.color = typeColor;
    document.getElementById("trk-chip-id").textContent    = "";

    renderSkeleton(document.getElementById("trk-body"));

    fetch(`${API_BASE}?type=${encodeURIComponent(type)}&id=${encodeURIComponent(id)}`, {
      headers:{"X-CSRFToken":getCookie(CSRF_COOKIE),"Accept":"application/json"},
      credentials:"same-origin",
    })
      .then(r => {
        if (!r.ok) return r.json().then(d=>Promise.reject(d.error||`HTTP ${r.status}`));
        return r.json();
      })
      .then(data => {
        if (_currentId !== id) return;
        _currentData = {data, type, id};
        renderDrawer(data, type, id);
        document.getElementById("trk-expand-btn").style.display = "";
      })
      .catch(err => {
        if (_currentId !== id) return;
        const body = document.getElementById("trk-body");
        body.innerHTML = "";
        body.appendChild(h("div",{class:"trk-error-box"},
          h("div",{class:"trk-error-icon"},"⚠"),
          h("div",{class:"trk-error-msg"},"Could not load tracking data"),
          h("div",{class:"trk-error-det"},String(err)),
        ));
      });
  }

  function closeTracker() {
    _currentId   = null;
    _currentData = null;
    closeModal();
    document.getElementById("trk-overlay").classList.remove("trk-visible");
    document.getElementById("trk-panel").classList.remove("trk-visible");
    document.body.style.overflow = "";
  }

  /* ═══════════════════════════════════════════════
     EVENT DELEGATION  — works on dynamic rows too
  ═══════════════════════════════════════════════ */

  document.addEventListener("click", e => {
    const btn = e.target.closest("[data-track]");
    if (!btn) return;
    e.preventDefault();
    const type  = btn.dataset.track;
    const id    = btn.dataset.id;
    const label = btn.dataset.label || btn.textContent.trim() || "";
    if (!type || !id) return;
    openTracker(type, id, label);
  });

  document.addEventListener("keydown", e => {
    if (e.key !== "Escape") return;
    // Close modal first if open, then drawer
    const mo = document.getElementById("trk-modal-overlay");
    if (mo && mo.classList.contains("trk-visible")) { closeModal(); return; }
    closeTracker();
  });

  /* ═══════════════════════════════════════════════
     INIT
  ═══════════════════════════════════════════════ */

  function init() { injectStyles(); buildShell(); }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // Public API
  window.PrimeTracker = { open:openTracker, close:closeTracker, openModal };

})();