// ============================================
// PRINT PREVIEW - FULLY SELF-CONTAINED v3
// Fixed: print output matches preview exactly
// ============================================

function _pp_esc(str) {
    if (typeof esc === 'function') return esc(String(str ?? ''));
    const d = document.createElement('div'); d.textContent = String(str ?? ''); return d.innerHTML;
}

function _pp_fmt(n) {
    if (typeof fmt === 'function') return fmt(Number(n) || 0);
    return new Intl.NumberFormat('en-UG', { style:'currency', currency:'UGX', minimumFractionDigits:0, maximumFractionDigits:0 }).format(Number(n) || 0);
}

function _pp_calcItem(item) {
    if (typeof calcItemTotal === 'function') return calcItemTotal(item);
    const sub = (item.unit_price || 0) * (item.quantity || 1);
    const disc = item.discount_amount || 0;
    const after = sub - disc;
    const rate = parseFloat(item.tax_rate) || 0;
    let tax = 0;
    if (rate > 0) { const m = rate / 100; tax = (after / (1 + m)) * m; }
    return { subtotal: sub, discount: disc, tax, total: after };
}

function _pp_getStore(selectedOption) {
    if (selectedOption && selectedOption.value) {
        return {
            name:             selectedOption.text?.split('·')[0]?.trim() || '',
            phone:            selectedOption.dataset.phone    || '',
            email:            selectedOption.dataset.email    || '',
            tin:              selectedOption.dataset.tin      || '',
            physical_address: selectedOption.dataset.address  || selectedOption.dataset.location || '',
            logo_url:         selectedOption.dataset.logo     || ''
        };
    }
    if (typeof DEFAULT_STORE !== 'undefined') {
        return {
            name:             DEFAULT_STORE.name    || (typeof COMPANY_INFO !== 'undefined' ? COMPANY_INFO.name : ''),
            phone:            DEFAULT_STORE.phone   || '',
            email:            DEFAULT_STORE.email   || '',
            tin:              DEFAULT_STORE.tin     || '',
            physical_address: DEFAULT_STORE.address || '',
            logo_url:         ''
        };
    }
    return { name:'', phone:'', email:'', tin:'', physical_address:'', logo_url:'' };
}

// ── Build the complete receipt HTML (screen + print safe) ──
function _pp_buildHTML(draft, format) {
    const storeEl   = document.getElementById('storeSelect');
    const selOpt    = storeEl?.options[storeEl.selectedIndex];
    const store     = _pp_getStore(selOpt);
    const storeName = store.name || (typeof COMPANY_INFO !== 'undefined' ? COMPANY_INFO.name : 'Store');
    const customer  = draft.customer;
    const isA4      = format !== 'thermal';

    let subtotal = 0, totalTax = 0, totalDiscount = 0;
    draft.cart.forEach(item => {
        const t = _pp_calcItem(item);
        subtotal += t.subtotal; totalTax += t.tax; totalDiscount += t.discount;
    });
    if (draft.discount?.value > 0) {
        totalDiscount += draft.discount.type === 'percentage'
            ? subtotal * (draft.discount.value / 100)
            : Math.min(draft.discount.value, subtotal);
    }
    const total    = subtotal - totalDiscount + totalTax;
    const now      = new Date();
    const dateStr  = now.toLocaleDateString('en-GB');
    const timeStr  = now.toLocaleTimeString('en-GB', { hour:'2-digit', minute:'2-digit' });
    const docLabel = (draft.documentType || 'RECEIPT') === 'INVOICE' ? 'Invoice' : 'Receipt';
    const refNo    = 'PREVIEW-' + String(Date.now()).slice(-6);

    const logoHTML = store.logo_url
        ? `<img src="${_pp_esc(store.logo_url)}" alt="${_pp_esc(storeName)}" style="width:${isA4?'88':'50'}px;height:${isA4?'88':'50'}px;object-fit:contain;">`
        : `<div style="width:${isA4?'88':'50'}px;height:${isA4?'88':'50'}px;border-radius:${isA4?'12':'8'}px;display:inline-flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#7c3aed,#ec4899);color:#fff;font-weight:800;font-size:${isA4?'32':'20'}px;">${_pp_esc(storeName.charAt(0).toUpperCase())}</div>`;

    const itemRows = draft.cart.map(item => {
        const t = _pp_calcItem(item);
        const badgeBg  = (item.item_type||'').toLowerCase() === 'service' ? '#fce7f3' : '#dbeafe';
        const badgeClr = (item.item_type||'').toLowerCase() === 'service' ? '#be185d'  : '#1e40af';
        return `<tr>
            <td style="text-align:center;font-weight:600;padding:${isA4?'10':'5'}px 8px;">${item.quantity}</td>
            <td style="padding:${isA4?'10':'5'}px 8px;">
                <div style="font-weight:600;margin-bottom:2px;">${_pp_esc(item.name)}</div>
                ${item.code ? `<div style="font-size:${isA4?'10':'8'}px;color:#6b7280;">Code: ${_pp_esc(item.code)}</div>` : ''}
                <span style="display:inline-block;padding:1px 6px;border-radius:4px;font-size:${isA4?'9':'7'}px;font-weight:600;text-transform:uppercase;margin-top:2px;background:${badgeBg};color:${badgeClr};">${_pp_esc(item.item_type||'PRODUCT')}</span>
            </td>
            <td style="text-align:right;font-weight:600;padding:${isA4?'10':'5'}px 8px;">${_pp_fmt(item.unit_price)}</td>
            <td style="text-align:right;font-weight:700;padding:${isA4?'10':'5'}px 8px;">${_pp_fmt(t.total)}</td>
        </tr>`;
    }).join('');

    // All layout uses inline styles so it survives @media print exactly as-is
    const w = isA4 ? '210mm' : '80mm';
    const p = isA4 ? '15mm' : '5mm';
    const fs = isA4 ? '12px' : '10px';

    return `
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.0/font/bootstrap-icons.css">
<style>
  /* Reset */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #f3f4f6; font-family: Arial, sans-serif; font-size: ${fs}; }

  /* The receipt card */
  .receipt {
    position: relative;
    background: #fff;
    width: ${w};
    margin: ${isA4 ? '2rem' : '1rem'} auto;
    padding: ${p};
    box-shadow: 0 4px 12px rgba(0,0,0,.12);
    border-radius: 8px;
    overflow: hidden;
  }

  /* Watermark — hidden at print */
  .wm-wrap { position:absolute; inset:0; pointer-events:none; overflow:hidden; z-index:0; }
  .wm {
    position:absolute; font-size:${isA4?'110':'55'}px; font-weight:900;
    color:rgba(59,130,246,.07); white-space:nowrap; letter-spacing:${isA4?'18':'8'}px;
    text-transform:uppercase; user-select:none; pointer-events:none;
  }
  .wm-1 { top:20%; left:50%; transform:translateX(-50%) rotate(-45deg); }
  .wm-2 { top:58%; left:50%; transform:translateX(-50%) rotate(-45deg); }

  /* All content sits above watermark */
  .rc { position:relative; z-index:1; }

  /* Notice banner — hidden at print */
  .notice {
    background:linear-gradient(135deg,#dbeafe,#bfdbfe);
    border:3px dashed #3b82f6; border-radius:10px;
    padding:${isA4?'12px 16px':'6px 8px'};
    text-align:center; color:#1e40af;
    font-size:${isA4?'13px':'9px'}; font-weight:600;
    margin-bottom:${isA4?'16px':'10px'};
  }

  /* Table resets */
  table { width:100%; border-collapse:collapse; }
  thead { background:linear-gradient(135deg,#7c3aed,#6d28d9); color:#fff; }
  th { padding:${isA4?'10px 8px':'5px 4px'}; text-align:left; font-size:${isA4?'11px':'8px'}; font-weight:700; text-transform:uppercase; }
  td { border-bottom:1px solid #e5e7eb; font-size:${isA4?'12px':'9px'}; color:#1f2937; vertical-align:top; }

  /* ── PRINT RULES ── */
  @media print {
    @page {
      size: ${isA4 ? 'A4 portrait' : '80mm auto'};
      margin: 0;
    }
    html, body {
      width: ${w};
      background: #fff !important;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }
    body { margin: 0; padding: 0; }
    .receipt {
      width: ${w} !important;
      margin: 0 !important;
      padding: ${p} !important;
      box-shadow: none !important;
      border-radius: 0 !important;
      page-break-inside: avoid;
    }
    .wm-wrap { display: none !important; }
    .notice  { display: none !important; }
    /* Force background colors to print */
    thead { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
</style>
</head>
<body>
<div class="receipt">

  <!-- Watermark (screen only) -->
  <div class="wm-wrap">
    <div class="wm wm-1">PREVIEW</div>
    <div class="wm wm-2">PREVIEW</div>
  </div>

  <!-- Header -->
  <div class="rc" style="text-align:center;padding-bottom:${isA4?'16px':'9px'};border-bottom:${isA4?'3px':'2px'} solid #7c3aed;margin-bottom:${isA4?'16px':'9px'};">
    ${logoHTML}
    <div style="font-size:${isA4?'24px':'15px'};font-weight:800;color:#7c3aed;text-transform:uppercase;letter-spacing:1px;margin:${isA4?'10px':'6px'} 0 4px;">${_pp_esc(storeName)}</div>
    ${store.physical_address ? `<div style="font-size:${isA4?'12px':'9px'};color:#6b7280;font-style:italic;margin-bottom:8px;">${_pp_esc(store.physical_address)}</div>` : ''}
    <div style="font-size:${isA4?'11px':'9px'};color:#1f2937;display:flex;flex-wrap:wrap;justify-content:center;gap:4px 14px;">
      ${store.phone ? `<span><i class="bi bi-telephone-fill" style="color:#7c3aed;"></i> ${_pp_esc(store.phone)}</span>` : ''}
      ${store.email ? `<span><i class="bi bi-envelope-fill"  style="color:#7c3aed;"></i> ${_pp_esc(store.email)}</span>` : ''}
      ${store.tin   ? `<span><strong>TIN:</strong> ${_pp_esc(store.tin)}</span>` : ''}
    </div>
  </div>

  <!-- Customer + Meta -->
  <div class="rc" style="display:grid;grid-template-columns:${isA4?'1.2fr 1fr':'1fr'};gap:${isA4?'16px':'8px'};margin-bottom:${isA4?'16px':'10px'};">
    <!-- Customer box -->
    <div style="background:linear-gradient(135deg,rgba(124,58,237,.05),rgba(236,72,153,.05));border:2px solid #7c3aed;border-radius:10px;padding:${isA4?'14px':'8px'};">
      <div style="font-size:${isA4?'11px':'9px'};font-weight:800;color:#7c3aed;margin-bottom:8px;text-transform:uppercase;letter-spacing:.7px;border-bottom:2px solid #7c3aed;padding-bottom:5px;display:flex;align-items:center;gap:6px;">
        <i class="bi bi-person-circle"></i> Customer
      </div>
      ${customer ? `
        <div style="display:flex;justify-content:space-between;font-size:${isA4?'11px':'9px'};padding:4px 0;border-bottom:1px solid rgba(124,58,237,.1);">
          <span style="font-weight:700;color:#6b7280;font-size:9px;text-transform:uppercase;">Name:</span>
          <span style="font-weight:600;color:#1f2937;">${_pp_esc(customer.name)}</span>
        </div>
        ${customer.phone ? `<div style="display:flex;justify-content:space-between;font-size:${isA4?'11px':'9px'};padding:4px 0;border-bottom:1px solid rgba(124,58,237,.1);">
          <span style="font-weight:700;color:#6b7280;font-size:9px;text-transform:uppercase;">Phone:</span>
          <span style="font-weight:600;color:#1f2937;">${_pp_esc(customer.phone)}</span>
        </div>` : ''}
        ${customer.email ? `<div style="display:flex;justify-content:space-between;font-size:${isA4?'11px':'9px'};padding:4px 0;border-bottom:1px solid rgba(124,58,237,.1);">
          <span style="font-weight:700;color:#6b7280;font-size:9px;text-transform:uppercase;">Email:</span>
          <span style="font-weight:600;color:#1f2937;">${_pp_esc(customer.email)}</span>
        </div>` : ''}
        ${customer.tin ? `<div style="display:flex;justify-content:space-between;font-size:${isA4?'11px':'9px'};padding:4px 0;">
          <span style="font-weight:700;color:#6b7280;font-size:9px;text-transform:uppercase;">TIN:</span>
          <span style="font-weight:600;color:#1f2937;">${_pp_esc(customer.tin)}</span>
        </div>` : ''}
      ` : `<div style="text-align:center;color:#6b7280;font-style:italic;padding:16px;font-size:${isA4?'12px':'10px'};"><i class="bi bi-person-walking"></i> Walk-in Customer</div>`}
    </div>
    <!-- Meta box -->
    <div style="background:#f3f4f6;border:2px solid #e5e7eb;border-radius:10px;padding:${isA4?'14px':'8px'};display:flex;flex-direction:column;gap:8px;">
      <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:2px solid #e5e7eb;">
        <span style="font-weight:700;color:#6b7280;text-transform:uppercase;font-size:${isA4?'10px':'8px'};display:flex;align-items:center;gap:4px;"><i class="bi bi-receipt"></i> ${docLabel} No:</span>
        <span style="font-weight:800;color:#1f2937;font-size:${isA4?'12px':'10px'};font-family:'Courier New',monospace;background:#fff;padding:2px 8px;border-radius:4px;">${refNo}</span>
      </div>
      <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:2px solid #e5e7eb;">
        <span style="font-weight:700;color:#6b7280;text-transform:uppercase;font-size:${isA4?'10px':'8px'};display:flex;align-items:center;gap:4px;"><i class="bi bi-clock-history"></i> Date:</span>
        <span style="font-weight:800;color:#1f2937;font-size:${isA4?'12px':'10px'};font-family:'Courier New',monospace;background:#fff;padding:2px 8px;border-radius:4px;">${dateStr} ${timeStr}</span>
      </div>
      ${draft.paymentMethod ? `<div style="display:flex;justify-content:space-between;padding:6px 0;">
        <span style="font-weight:700;color:#6b7280;text-transform:uppercase;font-size:${isA4?'10px':'8px'};display:flex;align-items:center;gap:4px;"><i class="bi bi-cash-coin"></i> Payment:</span>
        <span style="font-weight:800;color:#1f2937;font-size:${isA4?'12px':'10px'};font-family:'Courier New',monospace;background:#fff;padding:2px 8px;border-radius:4px;">${_pp_esc((draft.paymentMethod||'').replace(/_/g,' '))}</span>
      </div>` : ''}
    </div>
  </div>


  <!-- Items table -->
  <div class="rc" style="margin-bottom:${isA4?'14px':'10px'};">
    <table>
      <thead>
        <tr>
          <th style="width:10%">Qty</th>
          <th style="width:48%">Description</th>
          <th style="width:18%;text-align:right">@ Price</th>
          <th style="width:24%;text-align:right">Amount</th>
        </tr>
      </thead>
      <tbody>${itemRows}</tbody>
    </table>
  </div>

  <!-- Totals + QR -->
  <div class="rc" style="display:grid;grid-template-columns:${isA4?'1fr 1fr':'1fr'};gap:${isA4?'16px':'8px'};margin-bottom:${isA4?'14px':'10px'};">
    ${isA4 ? `<div style="display:flex;align-items:center;justify-content:center;padding:12px;">
      <div style="text-align:center;color:#6b7280;">
        <i class="bi bi-qr-code" style="font-size:72px;opacity:.18;display:block;"></i>
        <div style="margin-top:8px;font-size:11px;">QR Code appears<br>after completing sale</div>
      </div>
    </div>` : ''}
    <div style="border-top:2px solid #7c3aed;padding-top:12px;">
      <div style="display:flex;justify-content:space-between;padding:6px 0;font-size:${isA4?'13px':'10px'};">
        <span>Subtotal:</span><span>${_pp_fmt(subtotal)}</span>
      </div>
      ${totalTax > 0 ? `<div style="display:flex;justify-content:space-between;padding:6px 0;font-size:${isA4?'13px':'10px'};">
        <span>Tax (18%):</span><span>${_pp_fmt(totalTax)}</span>
      </div>` : ''}
      ${totalDiscount > 0 ? `<div style="display:flex;justify-content:space-between;padding:6px 0;font-size:${isA4?'13px':'10px'};">
        <span>Discount:</span><span>−${_pp_fmt(totalDiscount)}</span>
      </div>` : ''}
      <div style="display:flex;justify-content:space-between;border-top:2px solid #1f2937;margin-top:4px;padding-top:10px;font-size:${isA4?'18px':'14px'};font-weight:800;color:#7c3aed;">
        <span>TOTAL:</span><span>${_pp_fmt(total)}</span>
      </div>
    </div>
  </div>

  <!-- Footer -->
  <div class="rc" style="margin-top:10px;padding-top:12px;border-top:2px solid #e5e7eb;text-align:center;">
    <div style="color:#dc2626;font-weight:700;font-style:italic;margin-bottom:5px;font-size:${isA4?'12px':'9px'};">
      *Goods and money once received cannot be returned!*
    </div>
    <div style="font-weight:600;font-size:${isA4?'13px':'10px'};">THANK YOU FOR THE BUSINESS!</div>
    <div style="font-size:${isA4?'10px':'8px'};color:#6b7280;margin:8px 0 4px;">Preview: ${dateStr} ${timeStr}</div>
    <div style="font-size:${isA4?'11px':'8px'};color:#6b7280;">Powered by <strong>Primebooks</strong> (www.primebooks.sale)</div>
  </div>

</div>
</body>
</html>`;
}

// ── Print via dedicated popup window ──
// This is the key fix: we open a new window with the receipt HTML already
// fully laid out, so @media print in the MAIN page never interferes.
function _pp_printInWindow(draft, format) {
    const html = _pp_buildHTML(draft, format);
    const pw = window.open('', '_blank', 'width=900,height=700');
    if (!pw) {
        alert('Pop-up blocked. Please allow pop-ups for this site and try again.');
        return;
    }
    pw.document.open();
    pw.document.write(html);
    pw.document.close();
    // Wait for images/fonts to load before printing
    pw.addEventListener('load', () => {
        pw.focus();
        pw.print();
        // Close after print dialog dismissed (slight delay)
        pw.addEventListener('afterprint', () => pw.close());
    });
}

// ── Public: preview modal ──
function printReceiptPreview() {
    if (!SaleState.cart.length) {
        if (typeof showError === 'function') showError('Cart is empty. Add items before previewing.');
        return;
    }
    const draft = {
        id:            Date.now(),
        name:          'Current Cart Preview',
        cart:          SaleState.cart,
        customer:      SaleState.selectedCustomer,
        documentType:  document.getElementById('documentTypeField')?.value || SaleState.docType || 'RECEIPT',
        paymentMethod: document.getElementById('paymentMethodField')?.value || SaleState.paymentMethod || 'CASH',
        dueDate:       document.getElementById('dueDate')?.value || null,
        discount:      SaleState.discount || { type:'percentage', value:0 },
        totalAmount:   parseFloat(document.getElementById('totalAmount')?.value) || 0,
        itemCount:     SaleState.cart.reduce((s, i) => s + i.quantity, 0),
        createdAt:     new Date().toISOString(),
        updatedAt:     new Date().toISOString()
    };

    // Track current format selection
    let currentFormat = 'a4';

    document.getElementById('printPreviewModal')?.remove();

    const wrap = document.createElement('div');
    wrap.innerHTML = `
        <div class="modal fade" id="printPreviewModal" tabindex="-1">
            <div class="modal-dialog modal-fullscreen">
                <div class="modal-content">
                    <div class="modal-header bg-light">
                        <div class="d-flex align-items-center gap-3 flex-grow-1">
                            <h5 class="modal-title mb-0"><i class="bi bi-printer me-2"></i>Print Preview</h5>
                            <small class="text-muted">Current cart — not yet saved</small>
                        </div>
                        <div class="me-3">
                            <div class="btn-group">
                                <input type="radio" class="btn-check" name="ppFmt" id="ppFmtA4" value="a4" checked>
                                <label class="btn btn-outline-primary btn-sm" for="ppFmtA4">
                                    <i class="bi bi-file-earmark-text me-1"></i>A4
                                </label>
                                <input type="radio" class="btn-check" name="ppFmt" id="ppFmtThermal" value="thermal">
                                <label class="btn btn-outline-primary btn-sm" for="ppFmtThermal">
                                    <i class="bi bi-receipt me-1"></i>Thermal
                                </label>
                            </div>
                        </div>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body p-0" style="background:#f3f4f6;overflow:auto">
                        <iframe id="ppFrame" style="width:100%;height:100%;border:none;min-height:calc(100vh - 120px);"></iframe>
                    </div>
                    <div class="modal-footer bg-light">
                        <button class="btn btn-secondary" data-bs-dismiss="modal">
                            <i class="bi bi-x-circle me-1"></i>Close
                        </button>
                        <button class="btn btn-info" id="ppSaveDraft">
                            <i class="bi bi-save me-1"></i>Save as Draft
                        </button>
                        <button class="btn btn-primary" id="ppPrintBtn">
                            <i class="bi bi-printer-fill me-1"></i>Print
                        </button>
                        <button class="btn btn-success" id="ppCompleteBtn">
                            <i class="bi bi-check-circle-fill me-1"></i>Complete Sale
                        </button>
                    </div>
                </div>
            </div>
        </div>`;
    document.body.appendChild(wrap);

    // Render into iframe so the modal page CSS never touches the receipt
    function renderIntoFrame(format) {
        currentFormat = format;
        const frame = document.getElementById('ppFrame');
        const html  = _pp_buildHTML(draft, format);
        // Write directly into the iframe document
        frame.contentDocument.open();
        frame.contentDocument.write(html);
        frame.contentDocument.close();
    }

    renderIntoFrame('a4');

    // Format switcher
    wrap.querySelectorAll('input[name="ppFmt"]').forEach(r => {
        r.addEventListener('change', function () { renderIntoFrame(this.value); });
    });

    // Button wiring
    wrap.querySelector('#ppSaveDraft').addEventListener('click', () => {
        if (typeof saveAsDraft === 'function') saveAsDraft();
        bootstrap.Modal.getInstance(wrap.querySelector('#printPreviewModal'))?.hide();
    });

    wrap.querySelector('#ppPrintBtn').addEventListener('click', () => {
        // Print ONLY the iframe content — totally isolated from main page
        const frame = document.getElementById('ppFrame');
        frame.contentWindow.focus();
        frame.contentWindow.print();
    });

    wrap.querySelector('#ppCompleteBtn').addEventListener('click', () => {
        bootstrap.Modal.getInstance(wrap.querySelector('#printPreviewModal'))?.hide();
        setTimeout(() => { if (typeof openPaymentModal === 'function') openPaymentModal(); }, 300);
    });

    const modal = new bootstrap.Modal(wrap.querySelector('#printPreviewModal'));
    modal.show();
    wrap.querySelector('#printPreviewModal').addEventListener('hidden.bs.modal', () => wrap.remove());
}

// Kept for backward compat — not used internally anymore
function printFromPreview() {
    const frame = document.getElementById('ppFrame');
    if (frame) { frame.contentWindow.focus(); frame.contentWindow.print(); }
}

window.printReceiptPreview  = printReceiptPreview;
window.printFromPreview     = printFromPreview;