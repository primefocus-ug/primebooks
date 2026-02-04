// ============================================
// INDEPENDENT DRAFT PREVIEW SYSTEM
// Complete standalone implementation with embedded CSS
// ============================================

/**
 * Show draft preview (COMPLETELY INDEPENDENT)
 */
function showDraftPreview(draftIndex) {
    const draft = SaleState.drafts[draftIndex];
    if (!draft) {
        showError('Draft not found');
        return;
    }

    const modalHTML = createDraftPreviewModalHTML(draft);

    const existingModal = document.getElementById('draftPreviewModal');
    if (existingModal) {
        existingModal.remove();
    }

    const modalContainer = document.createElement('div');
    modalContainer.innerHTML = modalHTML;
    document.body.appendChild(modalContainer);

    const modal = new bootstrap.Modal(modalContainer.querySelector('#draftPreviewModal'));
    modal.show();

    loadDraftPreviewContent(draft, 'a4');

    const formatRadios = document.querySelectorAll('input[name="draftPreviewFormat"]');
    formatRadios.forEach(radio => {
        radio.addEventListener('change', function() {
            loadDraftPreviewContent(draft, this.value);
        });
    });

    modalContainer.querySelector('#draftPreviewModal').addEventListener('hidden.bs.modal', function() {
        document.body.removeChild(modalContainer);
    });
}

/**
 * Create draft preview modal HTML
 */
function createDraftPreviewModalHTML(draft) {
    const draftDate = new Date(draft.updatedAt || draft.createdAt);
    const formattedDate = draftDate.toLocaleDateString();
    const formattedTime = draftDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    return `
        <div class="modal fade" id="draftPreviewModal" tabindex="-1">
            <div class="modal-dialog modal-fullscreen">
                <div class="modal-content">
                    <div class="modal-header bg-light">
                        <div class="d-flex align-items-center gap-3 flex-grow-1">
                            <h5 class="modal-title mb-0">
                                <i class="bi bi-eye me-2"></i>Draft Preview: ${escapeHtml(draft.name)}
                            </h5>
                            <small class="text-muted">
                                <i class="bi bi-clock me-1"></i>${formattedDate} ${formattedTime}
                            </small>
                        </div>

                        <div class="format-selector-inline me-3">
                            <div class="btn-group" role="group">
                                <input type="radio" class="btn-check" name="draftPreviewFormat"
                                       id="draftPreviewFormatA4" value="a4" checked>
                                <label class="btn btn-outline-primary btn-sm" for="draftPreviewFormatA4">
                                    <i class="bi bi-file-earmark-text me-1"></i>A4
                                </label>

                                <input type="radio" class="btn-check" name="draftPreviewFormat"
                                       id="draftPreviewFormatThermal" value="thermal">
                                <label class="btn btn-outline-primary btn-sm" for="draftPreviewFormatThermal">
                                    <i class="bi bi-receipt me-1"></i>Thermal
                                </label>
                            </div>
                        </div>

                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>

                    <div class="modal-body p-0" style="background: #f3f4f6; overflow: auto;">
                        <div id="draftPreviewContent"></div>
                    </div>

                    <div class="modal-footer bg-light">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                            <i class="bi bi-x-circle me-2"></i>Close
                        </button>
                        <button type="button" class="btn btn-info" onclick="emailDraftByIndex(${draftIndex})">
                            <i class="bi bi-envelope me-2"></i>Email
                        </button>
                        <button type="button" class="btn btn-primary" onclick="printDraftPreview()">
                            <i class="bi bi-printer me-2"></i>Print
                        </button>
                        <button type="button" class="btn btn-success" onclick="loadDraftByIndex(${draftIndex})" data-bs-dismiss="modal">
                            <i class="bi bi-upload me-2"></i>Load Draft
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Load draft preview content
 */
function loadDraftPreviewContent(draft, format) {
    const previewContent = document.getElementById('draftPreviewContent');
    if (!previewContent) return;

    const receiptHTML = generateDraftPreviewReceipt(draft, format);
    previewContent.innerHTML = receiptHTML;
}

/**
 * Generate complete draft preview receipt with embedded CSS
 */
function generateDraftPreviewReceipt(draft, format = 'a4') {
    const storeSelect = document.getElementById('storeSelect');
    const selectedOption = storeSelect?.options[storeSelect.selectedIndex];
    const currentStore = getCurrentStoreData(selectedOption);
    const storeDisplayName = currentStore.name || COMPANY_INFO.name;
    const storeInitial = storeDisplayName.charAt(0).toUpperCase();
    const customer = draft.customer;

    let subtotal = 0;
    let totalTax = 0;
    let totalDiscount = 0;

    draft.cart.forEach(item => {
        const itemTotal = calculateItemTotal(item);
        subtotal += itemTotal.subtotal;
        totalTax += itemTotal.tax;
        totalDiscount += itemTotal.discount;
    });

    if (draft.discount && draft.discount.value > 0) {
        if (draft.discount.type === 'percentage') {
            totalDiscount += subtotal * (draft.discount.value / 100);
        } else {
            totalDiscount += Math.min(draft.discount.value, subtotal);
        }
    }

    const total = subtotal - totalDiscount + totalTax;
    const currentDate = new Date(draft.updatedAt || draft.createdAt);
    const docTypeLabel = draft.documentType === 'INVOICE' ? 'Invoice' : 'Receipt';

    const storeLogoHTML = currentStore.logo_url
        ? `<img src="${escapeHtml(currentStore.logo_url)}" alt="${escapeHtml(storeDisplayName)}" class="receipt-logo" />`
        : `<div class="receipt-logo" style="background: linear-gradient(135deg, #7c3aed, #ec4899); border-radius: 12px; display: flex; align-items: center; justify-content: center; color: white; font-weight: 800; font-size: 32px; box-shadow: 0 4px 12px rgba(124, 58, 237, 0.2);">
               ${storeInitial}
           </div>`;

    const itemsTableRows = draft.cart.map((item) => {
        const itemTotal = calculateItemTotal(item);
        return `
            <tr>
                <td style="text-align: center; font-weight: 600;">${item.quantity}</td>
                <td>
                    <div class="receipt-item-name">${escapeHtml(item.name)}</div>
                    ${item.code ? `<div class="receipt-item-code">Code: ${escapeHtml(item.code)}</div>` : ''}
                    <span class="receipt-item-badge ${item.item_type.toLowerCase()}">
                        ${item.item_type}
                    </span>
                </td>
                <td style="text-align: right; font-weight: 600;">
                    ${formatCurrency(item.unit_price)}
                </td>
                <td style="text-align: right; font-weight: 700; font-size: 13px;">
                    ${formatCurrency(itemTotal.total)}
                </td>
            </tr>
        `;
    }).join('');

    return `
        <style>
            /* ==========================================
               DRAFT PREVIEW RECEIPT STYLES - EMBEDDED
               ========================================== */
            :root {
                --receipt-primary: #7c3aed;
                --receipt-primary-dark: #6d28d9;
                --receipt-secondary: #ec4899;
                --receipt-dark: #1f2937;
                --receipt-gray: #6b7280;
                --receipt-light-gray: #f3f4f6;
                --receipt-border: #e5e7eb;
                --receipt-white: #ffffff;
            }

            .draft-receipt-container {
                position: relative;
                background: white;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                border-radius: 8px;
                z-index: 2;
            }

            .draft-receipt-container.format-a4 {
                max-width: 210mm;
                min-height: 297mm;
                margin: 2rem auto;
                padding: 15mm;
            }

            .draft-receipt-container.format-thermal {
                max-width: 80mm;
                width: 80mm;
                margin: 2rem auto;
                padding: 5mm;
                font-size: 11px;
            }

            /* Watermark */
            .draft-watermark-container {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                pointer-events: none;
                z-index: 1;
                overflow: hidden;
            }

            .draft-watermark-text {
                position: absolute;
                font-size: 120px;
                font-weight: 900;
                color: rgba(124, 58, 237, 0.08);
                transform: rotate(-45deg);
                white-space: nowrap;
                letter-spacing: 20px;
                text-transform: uppercase;
                user-select: none;
            }

            .draft-watermark-text:nth-child(1) {
                top: 20%;
                left: 50%;
                transform: translateX(-50%) rotate(-45deg);
            }

            .draft-watermark-text:nth-child(2) {
                top: 50%;
                left: 50%;
                transform: translateX(-50%) rotate(-45deg);
            }

            .draft-watermark-text:nth-child(3) {
                top: 80%;
                left: 50%;
                transform: translateX(-50%) rotate(-45deg);
            }

            .format-thermal .draft-watermark-text {
                font-size: 60px;
                letter-spacing: 10px;
            }

            /* Header */
            .draft-receipt-header {
                text-align: center;
                padding-bottom: 20px;
                border-bottom: 3px solid var(--receipt-primary);
                margin-bottom: 20px;
                background: linear-gradient(to bottom, rgba(124, 58, 237, 0.02), transparent);
                position: relative;
                z-index: 3;
            }

            .format-thermal .draft-receipt-header {
                padding-bottom: 10px;
                margin-bottom: 10px;
                border-bottom: 2px dashed var(--receipt-primary);
            }

            .draft-receipt-logo-section {
                display: flex;
                flex-direction: column;
                align-items: center;
                gap: 12px;
            }

            .receipt-logo {
                width: 90px;
                height: 90px;
                object-fit: contain;
                margin-bottom: 5px;
            }

            .format-thermal .receipt-logo {
                width: 50px;
                height: 50px;
            }

            .draft-receipt-store-name {
                font-size: 26px;
                font-weight: 800;
                color: var(--receipt-primary);
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 8px;
                text-shadow: 0 2px 4px rgba(124, 58, 237, 0.1);
            }

            .format-thermal .draft-receipt-store-name {
                font-size: 16px;
            }

            .draft-receipt-store-tagline {
                font-size: 12px;
                color: var(--receipt-gray);
                font-style: italic;
                margin-bottom: 12px;
            }

            .format-thermal .draft-receipt-store-tagline {
                font-size: 9px;
            }

            .draft-receipt-store-details {
                font-size: 11px;
                color: var(--receipt-dark);
                line-height: 1.8;
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                gap: 8px 20px;
            }

            .format-thermal .draft-receipt-store-details {
                font-size: 9px;
                flex-direction: column;
                gap: 2px;
            }

            .draft-receipt-store-details div {
                display: flex;
                align-items: center;
                gap: 6px;
            }

            .draft-receipt-store-details i {
                color: var(--receipt-primary);
                width: 14px;
            }

            /* Info Grid */
            .draft-receipt-info-grid {
                display: grid;
                grid-template-columns: 1.2fr 1fr;
                gap: 20px;
                margin-bottom: 20px;
                position: relative;
                z-index: 3;
            }

            .format-thermal .draft-receipt-info-grid {
                grid-template-columns: 1fr;
                gap: 8px;
            }

            .draft-receipt-customer-section {
                background: linear-gradient(135deg, rgba(124, 58, 237, 0.05), rgba(236, 72, 153, 0.05));
                border: 2px solid var(--receipt-primary);
                border-radius: 10px;
                padding: 18px;
                box-shadow: 0 2px 8px rgba(124, 58, 237, 0.08);
            }

            .format-thermal .draft-receipt-customer-section {
                padding: 8px;
            }

            .draft-receipt-customer-title {
                font-size: 12px;
                font-weight: 800;
                color: var(--receipt-primary);
                margin-bottom: 12px;
                text-transform: uppercase;
                letter-spacing: 0.8px;
                border-bottom: 2px solid var(--receipt-primary);
                padding-bottom: 6px;
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .format-thermal .draft-receipt-customer-title {
                font-size: 9px;
            }

            .draft-receipt-customer-row {
                display: flex;
                justify-content: space-between;
                font-size: 11px;
                margin-bottom: 8px;
                padding: 6px 0;
                border-bottom: 1px solid rgba(124, 58, 237, 0.1);
            }

            .format-thermal .draft-receipt-customer-row {
                font-size: 9px;
            }

            .draft-receipt-customer-label {
                font-weight: 700;
                color: var(--receipt-gray);
                text-transform: uppercase;
                font-size: 9px;
            }

            .draft-receipt-customer-value {
                font-weight: 600;
                color: var(--receipt-dark);
                font-size: 11px;
            }

            .format-thermal .draft-receipt-customer-value {
                font-size: 9px;
            }

            .draft-receipt-customer-walkin {
                text-align: center;
                color: var(--receipt-gray);
                font-style: italic;
                padding: 20px;
                font-size: 12px;
            }

            .format-thermal .draft-receipt-customer-walkin {
                padding: 10px;
                font-size: 10px;
            }

            .draft-receipt-details-section {
                background: var(--receipt-light-gray);
                border: 2px solid var(--receipt-border);
                border-radius: 10px;
                padding: 18px;
                display: flex;
                flex-direction: column;
                gap: 12px;
            }

            .format-thermal .draft-receipt-details-section {
                padding: 8px;
                gap: 8px;
            }

            .draft-receipt-info-row {
                display: flex;
                justify-content: space-between;
                padding: 10px 0;
                border-bottom: 2px solid var(--receipt-border);
            }

            .format-thermal .draft-receipt-info-row {
                padding: 6px 0;
            }

            .draft-receipt-info-label {
                font-weight: 700;
                color: var(--receipt-gray);
                text-transform: uppercase;
                font-size: 10px;
                display: flex;
                align-items: center;
                gap: 6px;
            }

            .format-thermal .draft-receipt-info-label {
                font-size: 9px;
            }

            .draft-receipt-info-value {
                font-weight: 800;
                color: var(--receipt-dark);
                font-size: 13px;
                font-family: 'Courier New', monospace;
                background: white;
                padding: 4px 10px;
                border-radius: 4px;
            }

            .format-thermal .draft-receipt-info-value {
                font-size: 10px;
                padding: 2px 6px;
            }

            /* Draft Notice - Yellow */
            .draft-notice {
                margin-bottom: 20px;
                animation: pulse-border-yellow 2s ease-in-out infinite;
                position: relative;
                z-index: 3;
            }

            .draft-notice-content {
                background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
                border: 3px dashed #ffc107;
                border-radius: 12px;
                padding: 15px 20px;
                text-align: center;
                color: #856404;
                font-size: 14px;
                font-weight: 600;
                box-shadow: 0 2px 8px rgba(255, 193, 7, 0.2);
            }

            .format-thermal .draft-notice-content {
                padding: 8px;
                font-size: 10px;
                border-width: 2px;
            }

            @keyframes pulse-border-yellow {
                0%, 100% { border-color: #ffc107; }
                50% { border-color: #ff9800; }
            }

            /* Items Table */
            .draft-receipt-items-table {
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 15px;
                position: relative;
                z-index: 3;
            }

            .draft-receipt-items-table thead {
                background: linear-gradient(135deg, var(--receipt-primary), var(--receipt-primary-dark));
                color: white;
            }

            .draft-receipt-items-table th {
                padding: 12px 10px;
                text-align: left;
                font-size: 11px;
                font-weight: 700;
                text-transform: uppercase;
            }

            .format-thermal .draft-receipt-items-table th {
                padding: 6px 4px;
                font-size: 9px;
            }

            .draft-receipt-items-table td {
                padding: 12px 10px;
                font-size: 12px;
                color: var(--receipt-dark);
                border-bottom: 1px solid var(--receipt-border);
            }

            .format-thermal .draft-receipt-items-table td {
                padding: 6px 4px;
                font-size: 9px;
            }

            .receipt-item-name {
                font-weight: 600;
                color: var(--receipt-dark);
                margin-bottom: 3px;
            }

            .receipt-item-code {
                font-size: 10px;
                color: var(--receipt-gray);
            }

            .format-thermal .receipt-item-code {
                font-size: 8px;
            }

            .receipt-item-badge {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 9px;
                font-weight: 600;
                text-transform: uppercase;
                margin-top: 4px;
            }

            .format-thermal .receipt-item-badge {
                font-size: 7px;
                padding: 1px 4px;
            }

            .receipt-item-badge.product {
                background: #dbeafe;
                color: #1e40af;
            }

            .receipt-item-badge.service {
                background: #fce7f3;
                color: #be185d;
            }

            /* Bottom Section */
            .draft-receipt-bottom-section {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 15px;
                position: relative;
                z-index: 3;
            }

            .format-thermal .draft-receipt-bottom-section {
                grid-template-columns: 1fr;
                gap: 10px;
            }

            .draft-receipt-qr-section {
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 15px;
            }

            .draft-qr-placeholder {
                text-align: center;
                padding: 20px;
                color: var(--receipt-gray);
            }

            .format-thermal .draft-qr-placeholder {
                padding: 10px;
            }

            .draft-receipt-totals-section {
                border-top: 2px solid var(--receipt-primary);
                padding-top: 15px;
            }

            .format-thermal .draft-receipt-totals-section {
                padding-top: 10px;
            }

            .draft-receipt-total-row {
                display: flex;
                justify-content: space-between;
                padding: 8px 0;
                font-size: 13px;
            }

            .format-thermal .draft-receipt-total-row {
                font-size: 10px;
                padding: 4px 0;
            }

            .draft-receipt-total-row.final {
                border-top: 2px solid var(--receipt-dark);
                margin-top: 5px;
                padding-top: 15px;
                font-size: 18px;
                font-weight: 800;
                color: var(--receipt-primary);
            }

            .format-thermal .draft-receipt-total-row.final {
                font-size: 14px;
                padding-top: 8px;
            }

            /* Footer */
            .draft-receipt-footer {
                margin-top: 10px;
                padding-top: 15px;
                border-top: 2px solid var(--receipt-border);
                text-align: center;
                position: relative;
                z-index: 3;
            }

            .draft-receipt-footer-main {
                font-size: 12px;
                color: var(--receipt-gray);
                margin-bottom: 5px;
            }

            .format-thermal .draft-receipt-footer-main {
                font-size: 10px;
            }

            .draft-receipt-footer-powered {
                font-size: 11px;
                color: var(--receipt-gray);
                margin-top: 5px;
            }

            .format-thermal .draft-receipt-footer-powered {
                font-size: 8px;
            }

            @media print {
                .draft-receipt-container {
                    box-shadow: none !important;
                    margin: 0 !important;
                }

                .draft-receipt-container.format-a4 {
                    width: 210mm !important;
                    padding: 15mm !important;
                }

                .draft-receipt-container.format-thermal {
                    width: 80mm !important;
                    padding: 5mm !important;
                }
            }
        </style>

        <div class="draft-receipt-container format-${format}" id="draftReceiptContainer">
            <div class="draft-watermark-container">
                <div class="draft-watermark-text">PREVIEW</div>
                <div class="draft-watermark-text">PREVIEW</div>
                <div class="draft-watermark-text">PREVIEW</div>
            </div>

            <div class="draft-receipt-header">
                <div class="draft-receipt-logo-section">
                    ${storeLogoHTML}
                    <div class="receipt-store-info">
                        <div class="draft-receipt-store-name">${escapeHtml(storeDisplayName)}</div>
                        <div class="draft-receipt-store-tagline">${currentStore.physical_address || ''}</div>
                        <div class="draft-receipt-store-details">
                            ${currentStore.phone ? `<div><i class="bi bi-telephone-fill"></i> ${escapeHtml(currentStore.phone)}</div>` : ''}
                            ${currentStore.email ? `<div><i class="bi bi-envelope-fill"></i> ${escapeHtml(currentStore.email)}</div>` : ''}
                            ${currentStore.tin ? `<div><strong>TIN:</strong> ${escapeHtml(currentStore.tin)}</div>` : ''}
                        </div>
                    </div>
                </div>
            </div>

            <div class="draft-receipt-info-grid">
                <div class="draft-receipt-customer-section">
                    <div class="draft-receipt-customer-title">
                        <i class="bi bi-person-circle"></i>
                        Customer Information
                    </div>
                    ${customer ? `
                        <div class="draft-receipt-customer-row">
                            <span class="draft-receipt-customer-label">Name:</span>
                            <span class="draft-receipt-customer-value">${escapeHtml(customer.name)}</span>
                        </div>
                        ${customer.phone ? `<div class="draft-receipt-customer-row">
                            <span class="draft-receipt-customer-label">Phone:</span>
                            <span class="draft-receipt-customer-value">${escapeHtml(customer.phone)}</span>
                        </div>` : ''}
                        ${customer.email ? `<div class="draft-receipt-customer-row">
                            <span class="draft-receipt-customer-label">Email:</span>
                            <span class="draft-receipt-customer-value">${escapeHtml(customer.email)}</span>
                        </div>` : ''}
                        ${customer.tin ? `<div class="draft-receipt-customer-row">
                            <span class="draft-receipt-customer-label">TIN:</span>
                            <span class="draft-receipt-customer-value">${escapeHtml(customer.tin)}</span>
                        </div>` : ''}
                    ` : `
                        <div class="draft-receipt-customer-walkin">
                            <i class="bi bi-person-walking"></i> Walk-in Customer
                        </div>
                    `}
                </div>

                <div class="draft-receipt-details-section">
                    <div class="draft-receipt-info-row">
                        <span class="draft-receipt-info-label">
                            <i class="bi bi-receipt"></i>
                            ${docTypeLabel} No:
                        </span>
                        <span class="draft-receipt-info-value">DRAFT-${draft.id}</span>
                    </div>
                    <div class="draft-receipt-info-row">
                        <span class="draft-receipt-info-label">
                            <i class="bi bi-clock-history"></i>
                            Date:
                        </span>
                        <span class="draft-receipt-info-value">${currentDate.toLocaleDateString('en-GB')} ${currentDate.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                </div>
            </div>

            <div class="draft-notice">
                <div class="draft-notice-content">
                    <i class="bi bi-exclamation-triangle-fill me-2"></i>
                    <strong>DRAFT PREVIEW - NOT OFFICIAL</strong><br>
                    This is a saved draft. Load and complete the sale to generate an official receipt.
                </div>
            </div>

            <table class="draft-receipt-items-table">
                <thead>
                    <tr>
                        <th style="width: 10%;">Qty</th>
                        <th style="width: 50%;">Description</th>
                        <th style="width: 15%; text-align: right;">@ Price</th>
                        <th style="width: 25%; text-align: right;">Amount</th>
                    </tr>
                </thead>
                <tbody>
                    ${itemsTableRows}
                </tbody>
            </table>

            <div class="draft-receipt-bottom-section">
                <div class="draft-receipt-qr-section">
                    <div class="draft-qr-placeholder">
                        <i class="bi bi-qr-code" style="font-size: 80px; opacity: 0.2;"></i>
                        <div style="margin-top: 10px; font-size: 11px;">QR Code will appear<br>after fiscalization</div>
                    </div>
                </div>

                <div class="draft-receipt-totals-section">
                    <div class="draft-receipt-total-row">
                        <span>Subtotal:</span>
                        <span>${formatCurrency(subtotal)} UGX</span>
                    </div>
                    ${totalTax > 0 ? `<div class="draft-receipt-total-row">
                        <span>Tax (18%):</span>
                        <span>${formatCurrency(totalTax)} UGX</span>
                    </div>` : ''}
                    ${totalDiscount > 0 ? `<div class="draft-receipt-total-row">
                        <span>Discount:</span>
                        <span>-${formatCurrency(totalDiscount)} UGX</span>
                    </div>` : ''}
                    <div class="draft-receipt-total-row final">
                        <span>TOTAL:</span>
                        <span>${formatCurrency(total)} UGX</span>
                    </div>
                </div>
            </div>

            <div class="draft-receipt-footer">
                <div class="draft-receipt-footer-main">
                    <div style="color: #dc2626; font-weight: 700; font-style: italic; margin-bottom: 6px;">
                        *Goods and money once received cannot be returned!*
                    </div>
                    <div style="font-weight: 600; font-size: 13px;">
                        THANK YOU FOR THE BUSINESS!
                    </div>
                </div>
                <div style="font-size: 10px; margin: 10px 0 5px 0;">
                    Draft Saved: ${currentDate.toLocaleDateString('en-GB')} ${currentDate.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                </div>
                <div class="draft-receipt-footer-powered">
                    Powered by <strong>Primebooks</strong> (www.primebooks.sale)
                </div>
            </div>
        </div>
    `;
}

/**
 * Print draft preview
 */
function printDraftPreview() {
    window.print();
}

/**
 * Update displayDraftsList to include preview button
 */
function displayDraftsListEnhanced() {
    const draftsList = document.getElementById('draftsList');
    const emptyState = document.getElementById('draftsEmptyState');
    const draftsCount = document.getElementById('draftsCount');
    const totalDraftsCount = document.getElementById('totalDraftsCount');
    const lastDraftDate = document.getElementById('lastDraftDate');

    if (!draftsList || !emptyState) return;

    if (SaleState.drafts.length === 0) {
        draftsList.innerHTML = '';
        emptyState.style.display = 'block';
        if (draftsCount) draftsCount.textContent = '0';
        if (totalDraftsCount) totalDraftsCount.textContent = '0';
        if (lastDraftDate) lastDraftDate.textContent = 'Never';
        return;
    }

    emptyState.style.display = 'none';
    if (draftsCount) draftsCount.textContent = SaleState.drafts.length;
    if (totalDraftsCount) totalDraftsCount.textContent = SaleState.drafts.length;

    if (lastDraftDate && SaleState.drafts.length > 0) {
        const lastDate = new Date(SaleState.drafts[0].updatedAt || SaleState.drafts[0].createdAt);
        lastDraftDate.textContent = lastDate.toLocaleDateString();
    }

    draftsList.innerHTML = SaleState.drafts.map((draft, index) => {
        const draftDate = new Date(draft.updatedAt || draft.createdAt);
        const formattedDate = draftDate.toLocaleDateString();
        const formattedTime = draftDate.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const total = draft.totalAmount || draft.cart.reduce((sum, item) => sum + (item.unit_price * item.quantity), 0);
        const customerName = draft.customer?.name || 'No customer';

        return `
            <div class="draft-item" data-draft-index="${index}">
                <div class="draft-item-header">
                    <div class="draft-item-title">
                        <h6 class="mb-0">${escapeHtml(draft.name)}</h6>
                        <small class="text-muted">
                            <i class="bi bi-calendar me-1"></i>${formattedDate} ${formattedTime}
                        </small>
                    </div>
                    <div class="draft-item-actions">
                        <button class="btn btn-sm btn-outline-secondary" onclick="showDraftPreview(${index})" title="Preview">
                            <i class="bi bi-eye"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-primary" onclick="loadDraftByIndex(${index})" title="Load">
                            <i class="bi bi-upload"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-info" onclick="printDraftByIndex(${index})" title="Print">
                            <i class="bi bi-printer"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-success" onclick="emailDraftByIndex(${index})" title="Email">
                            <i class="bi bi-envelope"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-warning" onclick="editDraftName(${draft.id}, '${escapeHtml(draft.name).replace(/'/g, "\\'")}')" title="Rename">
                            <i class="bi bi-pencil"></i>
                        </button>
                        <button class="btn btn-sm btn-outline-danger" onclick="deleteDraftById(${draft.id})" title="Delete">
                            <i class="bi bi-trash"></i>
                        </button>
                    </div>
                </div>
                <div class="draft-item-details">
                    <div class="row">
                        <div class="col-6">
                            <small class="text-muted">Items:</small>
                            <div class="fw-semibold">${draft.itemCount || draft.cart.length}</div>
                        </div>
                        <div class="col-6">
                            <small class="text-muted">Total:</small>
                            <div class="fw-semibold">${formatCurrency(total)}</div>
                        </div>
                    </div>
                    <div class="row mt-2">
                        <div class="col-6">
                            <small class="text-muted">Customer:</small>
                            <div class="text-truncate">${escapeHtml(customerName)}</div>
                        </div>
                        <div class="col-6">
                            <small class="text-muted">Type:</small>
                            <div>
                                <span class="badge ${draft.documentType === 'INVOICE' ? 'bg-info' : 'bg-secondary'}">
                                    ${draft.documentType || 'RECEIPT'}
                                </span>
                            </div>
                        </div>
                    </div>
                    ${draft.cart && draft.cart.length > 0 ? `
                        <div class="mt-2">
                            <small class="text-muted">Items:</small>
                            <div class="draft-items-preview">
                                ${draft.cart.slice(0, 3).map(item => `
                                    <span class="badge bg-light text-dark me-1">
                                        ${item.quantity}× ${item.name.substring(0, 15)}${item.name.length > 15 ? '...' : ''}
                                    </span>
                                `).join('')}
                                ${draft.cart.length > 3 ? `<span class="badge bg-light text-dark">+${draft.cart.length - 3} more</span>` : ''}
                            </div>
                        </div>
                    ` : ''}
                </div>
            </div>
        `;
    }).join('');
}

// Export functions
window.showDraftPreview = showDraftPreview;
window.printDraftPreview = printDraftPreview;

// Override displayDraftsList
if (typeof displayDraftsList !== 'undefined') {
    displayDraftsList = displayDraftsListEnhanced;
}