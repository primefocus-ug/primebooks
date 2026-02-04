// ============================================
// INDEPENDENT PRINT PREVIEW FOR CART SECTION
// Complete standalone implementation with embedded CSS
// ============================================

/**
 * Show print preview with format selector (COMPLETELY INDEPENDENT)
 */
function printReceiptPreview() {
    if (SaleState.cart.length === 0) {
        showError('Cart is empty. Add items before previewing.');
        return;
    }

    // Create current cart as temporary draft for preview
    const tempDraft = {
        id: Date.now(),
        name: 'Current Cart Preview',
        cart: SaleState.cart,
        customer: SaleState.selectedCustomer,
        storeId: document.getElementById('storeSelect')?.value,
        documentType: document.querySelector('input[name="document_type"]:checked')?.value || 'RECEIPT',
        paymentMethod: document.getElementById('paymentMethod')?.value || 'CASH',
        dueDate: document.getElementById('dueDate')?.value || null,
        discount: SaleState.discount,
        totalAmount: parseFloat(document.getElementById('totalAmount')?.value) || 0,
        itemCount: SaleState.cart.reduce((sum, item) => sum + item.quantity, 0),
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
    };

    // Show print preview modal
    showPrintPreviewModal(tempDraft);
}

/**
 * Show print preview modal with format selector
 */
function showPrintPreviewModal(draft) {
    const modalHTML = createPrintPreviewModalHTML(draft);

    // Remove existing modal if present
    const existingModal = document.getElementById('printPreviewModal');
    if (existingModal) {
        existingModal.remove();
    }

    // Add new modal to body
    const modalContainer = document.createElement('div');
    modalContainer.innerHTML = modalHTML;
    document.body.appendChild(modalContainer);

    const modal = new bootstrap.Modal(modalContainer.querySelector('#printPreviewModal'));
    modal.show();

    // Load initial preview (A4 format)
    loadPrintPreview(draft, 'a4');

    // Setup format switcher
    const formatRadios = document.querySelectorAll('input[name="printPreviewFormat"]');
    formatRadios.forEach(radio => {
        radio.addEventListener('change', function() {
            loadPrintPreview(draft, this.value);
        });
    });

    // Cleanup on close
    modalContainer.querySelector('#printPreviewModal').addEventListener('hidden.bs.modal', function() {
        document.body.removeChild(modalContainer);
    });
}

/**
 * Create print preview modal HTML with embedded CSS
 */
function createPrintPreviewModalHTML(draft) {
    return `
        <div class="modal fade" id="printPreviewModal" tabindex="-1">
            <div class="modal-dialog modal-fullscreen">
                <div class="modal-content">
                    <div class="modal-header bg-light">
                        <div class="d-flex align-items-center gap-3 flex-grow-1">
                            <h5 class="modal-title mb-0">
                                <i class="bi bi-printer me-2"></i>Print Preview
                            </h5>
                            <small class="text-muted">Current cart preview</small>
                        </div>

                        <div class="format-selector-inline me-3">
                            <div class="btn-group" role="group">
                                <input type="radio" class="btn-check" name="printPreviewFormat"
                                       id="printPreviewFormatA4" value="a4" checked>
                                <label class="btn btn-outline-primary btn-sm" for="printPreviewFormatA4">
                                    <i class="bi bi-file-earmark-text me-1"></i>A4
                                </label>

                                <input type="radio" class="btn-check" name="printPreviewFormat"
                                       id="printPreviewFormatThermal" value="thermal">
                                <label class="btn btn-outline-primary btn-sm" for="printPreviewFormatThermal">
                                    <i class="bi bi-receipt me-1"></i>Thermal
                                </label>
                            </div>
                        </div>

                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>

                    <div class="modal-body p-0" style="background: #f3f4f6; overflow: auto;">
                        <div id="printPreviewContent"></div>
                    </div>

                    <div class="modal-footer bg-light">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                            <i class="bi bi-x-circle me-2"></i>Close
                        </button>
                        <button type="button" class="btn btn-info" onclick="saveAsDraft()">
                            <i class="bi bi-save me-2"></i>Save as Draft
                        </button>
                        <button type="button" class="btn btn-primary" onclick="printFromPreview()">
                            <i class="bi bi-printer-fill me-2"></i>Print
                        </button>
                        <button type="button" class="btn btn-success" onclick="completeSale()" data-bs-dismiss="modal">
                            <i class="bi bi-check-circle-fill me-2"></i>Complete Sale
                        </button>
                    </div>
                </div>
            </div>
        </div>
    `;
}

/**
 * Load print preview in selected format
 */
function loadPrintPreview(draft, format) {
    const previewContent = document.getElementById('printPreviewContent');
    if (!previewContent) return;

    const receiptHTML = generatePrintPreviewReceipt(draft, format);
    previewContent.innerHTML = receiptHTML;
}

/**
 * Generate complete print preview receipt with embedded CSS
 */
function generatePrintPreviewReceipt(draft, format = 'a4') {
    const storeSelect = document.getElementById('storeSelect');
    const selectedOption = storeSelect?.options[storeSelect.selectedIndex];
    const currentStore = getCurrentStoreData(selectedOption);
    const storeDisplayName = currentStore.name || COMPANY_INFO.name;
    const storeInitial = storeDisplayName.charAt(0).toUpperCase();
    const customer = draft.customer;

    // Calculate totals
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
    const currentDate = new Date();
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
               PRINT PREVIEW RECEIPT STYLES - EMBEDDED
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

            .receipt-print-container {
                position: relative;
                background: white;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
                border-radius: 8px;
                z-index: 2;
            }

            .receipt-print-container.format-a4 {
                max-width: 210mm;
                min-height: 297mm;
                margin: 2rem auto;
                padding: 15mm;
            }

            .receipt-print-container.format-thermal {
                max-width: 80mm;
                width: 80mm;
                margin: 2rem auto;
                padding: 5mm;
                font-size: 11px;
            }

            /* Watermark */
            .watermark-container {
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                pointer-events: none;
                z-index: 1;
                overflow: hidden;
            }

            .watermark-text {
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

            .watermark-text:nth-child(1) {
                top: 20%;
                left: 50%;
                transform: translateX(-50%) rotate(-45deg);
            }

            .watermark-text:nth-child(2) {
                top: 50%;
                left: 50%;
                transform: translateX(-50%) rotate(-45deg);
            }

            .watermark-text:nth-child(3) {
                top: 80%;
                left: 50%;
                transform: translateX(-50%) rotate(-45deg);
            }

            .format-thermal .watermark-text {
                font-size: 60px;
                letter-spacing: 10px;
            }

            /* Header */
            .receipt-header {
                text-align: center;
                padding-bottom: 20px;
                border-bottom: 3px solid var(--receipt-primary);
                margin-bottom: 20px;
                background: linear-gradient(to bottom, rgba(124, 58, 237, 0.02), transparent);
                position: relative;
                z-index: 3;
            }

            .format-thermal .receipt-header {
                padding-bottom: 10px;
                margin-bottom: 10px;
                border-bottom: 2px dashed var(--receipt-primary);
            }

            .receipt-logo-section {
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

            .receipt-store-name {
                font-size: 26px;
                font-weight: 800;
                color: var(--receipt-primary);
                text-transform: uppercase;
                letter-spacing: 1px;
                margin-bottom: 8px;
                text-shadow: 0 2px 4px rgba(124, 58, 237, 0.1);
            }

            .format-thermal .receipt-store-name {
                font-size: 16px;
            }

            .receipt-store-tagline {
                font-size: 12px;
                color: var(--receipt-gray);
                font-style: italic;
                margin-bottom: 12px;
            }

            .format-thermal .receipt-store-tagline {
                font-size: 9px;
            }

            .receipt-store-details {
                font-size: 11px;
                color: var(--receipt-dark);
                line-height: 1.8;
                display: flex;
                flex-wrap: wrap;
                justify-content: center;
                gap: 8px 20px;
            }

            .format-thermal .receipt-store-details {
                font-size: 9px;
                flex-direction: column;
                gap: 2px;
            }

            .receipt-store-details div {
                display: flex;
                align-items: center;
                gap: 6px;
            }

            .receipt-store-details i {
                color: var(--receipt-primary);
                width: 14px;
            }

            /* Info Grid */
            .receipt-info-grid {
                display: grid;
                grid-template-columns: 1.2fr 1fr;
                gap: 20px;
                margin-bottom: 20px;
                position: relative;
                z-index: 3;
            }

            .format-thermal .receipt-info-grid {
                grid-template-columns: 1fr;
                gap: 8px;
            }

            .receipt-customer-section {
                background: linear-gradient(135deg, rgba(124, 58, 237, 0.05), rgba(236, 72, 153, 0.05));
                border: 2px solid var(--receipt-primary);
                border-radius: 10px;
                padding: 18px;
                box-shadow: 0 2px 8px rgba(124, 58, 237, 0.08);
            }

            .format-thermal .receipt-customer-section {
                padding: 8px;
            }

            .receipt-customer-title {
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

            .format-thermal .receipt-customer-title {
                font-size: 9px;
            }

            .receipt-customer-row {
                display: flex;
                justify-content: space-between;
                font-size: 11px;
                margin-bottom: 8px;
                padding: 6px 0;
                border-bottom: 1px solid rgba(124, 58, 237, 0.1);
            }

            .format-thermal .receipt-customer-row {
                font-size: 9px;
            }

            .receipt-customer-label {
                font-weight: 700;
                color: var(--receipt-gray);
                text-transform: uppercase;
                font-size: 9px;
            }

            .receipt-customer-value {
                font-weight: 600;
                color: var(--receipt-dark);
                font-size: 11px;
            }

            .format-thermal .receipt-customer-value {
                font-size: 9px;
            }

            .receipt-customer-walkin {
                text-align: center;
                color: var(--receipt-gray);
                font-style: italic;
                padding: 20px;
                font-size: 12px;
            }

            .format-thermal .receipt-customer-walkin {
                padding: 10px;
                font-size: 10px;
            }

            .receipt-details-section {
                background: var(--receipt-light-gray);
                border: 2px solid var(--receipt-border);
                border-radius: 10px;
                padding: 18px;
                display: flex;
                flex-direction: column;
                gap: 12px;
            }

            .format-thermal .receipt-details-section {
                padding: 8px;
                gap: 8px;
            }

            .receipt-info-row {
                display: flex;
                justify-content: space-between;
                padding: 10px 0;
                border-bottom: 2px solid var(--receipt-border);
            }

            .format-thermal .receipt-info-row {
                padding: 6px 0;
            }

            .receipt-info-label {
                font-weight: 700;
                color: var(--receipt-gray);
                text-transform: uppercase;
                font-size: 10px;
                display: flex;
                align-items: center;
                gap: 6px;
            }

            .format-thermal .receipt-info-label {
                font-size: 9px;
            }

            .receipt-info-value {
                font-weight: 800;
                color: var(--receipt-dark);
                font-size: 13px;
                font-family: 'Courier New', monospace;
                background: white;
                padding: 4px 10px;
                border-radius: 4px;
            }

            .format-thermal .receipt-info-value {
                font-size: 10px;
                padding: 2px 6px;
            }

            /* Preview Notice - Blue */
            .preview-notice {
                margin-bottom: 20px;
                animation: pulse-border-blue 2s ease-in-out infinite;
                position: relative;
                z-index: 3;
            }

            .preview-notice-content {
                background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%);
                border: 3px dashed #3b82f6;
                border-radius: 12px;
                padding: 15px 20px;
                text-align: center;
                color: #1e40af;
                font-size: 14px;
                font-weight: 600;
                box-shadow: 0 2px 8px rgba(59, 130, 246, 0.2);
            }

            .format-thermal .preview-notice-content {
                padding: 8px;
                font-size: 10px;
                border-width: 2px;
            }

            @keyframes pulse-border-blue {
                0%, 100% { border-color: #3b82f6; }
                50% { border-color: #2563eb; }
            }

            /* Items Table */
            .receipt-items-table {
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 15px;
                position: relative;
                z-index: 3;
            }

            .receipt-items-table thead {
                background: linear-gradient(135deg, var(--receipt-primary), var(--receipt-primary-dark));
                color: white;
            }

            .receipt-items-table th {
                padding: 12px 10px;
                text-align: left;
                font-size: 11px;
                font-weight: 700;
                text-transform: uppercase;
            }

            .format-thermal .receipt-items-table th {
                padding: 6px 4px;
                font-size: 9px;
            }

            .receipt-items-table td {
                padding: 12px 10px;
                font-size: 12px;
                color: var(--receipt-dark);
                border-bottom: 1px solid var(--receipt-border);
            }

            .format-thermal .receipt-items-table td {
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
            .receipt-bottom-section {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 15px;
                position: relative;
                z-index: 3;
            }

            .format-thermal .receipt-bottom-section {
                grid-template-columns: 1fr;
                gap: 10px;
            }

            .receipt-qr-section {
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 15px;
            }

            .preview-qr-placeholder {
                text-align: center;
                padding: 20px;
                color: var(--receipt-gray);
            }

            .format-thermal .preview-qr-placeholder {
                padding: 10px;
            }

            .receipt-totals-section {
                border-top: 2px solid var(--receipt-primary);
                padding-top: 15px;
            }

            .format-thermal .receipt-totals-section {
                padding-top: 10px;
            }

            .receipt-total-row {
                display: flex;
                justify-content: space-between;
                padding: 8px 0;
                font-size: 13px;
            }

            .format-thermal .receipt-total-row {
                font-size: 10px;
                padding: 4px 0;
            }

            .receipt-total-row.final {
                border-top: 2px solid var(--receipt-dark);
                margin-top: 5px;
                padding-top: 15px;
                font-size: 18px;
                font-weight: 800;
                color: var(--receipt-primary);
            }

            .format-thermal .receipt-total-row.final {
                font-size: 14px;
                padding-top: 8px;
            }

            /* Footer */
            .receipt-footer {
                margin-top: 10px;
                padding-top: 15px;
                border-top: 2px solid var(--receipt-border);
                text-align: center;
                position: relative;
                z-index: 3;
            }

            .receipt-footer-main {
                font-size: 12px;
                color: var(--receipt-gray);
                margin-bottom: 5px;
            }

            .format-thermal .receipt-footer-main {
                font-size: 10px;
            }

            .receipt-footer-powered {
                font-size: 11px;
                color: var(--receipt-gray);
                margin-top: 5px;
            }

            .format-thermal .receipt-footer-powered {
                font-size: 8px;
            }

            @media print {
                .receipt-print-container {
                    box-shadow: none !important;
                    margin: 0 !important;
                }

                .receipt-print-container.format-a4 {
                    width: 210mm !important;
                    padding: 15mm !important;
                }

                .receipt-print-container.format-thermal {
                    width: 80mm !important;
                    padding: 5mm !important;
                }
            }
        </style>

        <div class="receipt-print-container format-${format}" id="printReceiptContainer">
            <div class="watermark-container">
                <div class="watermark-text">PREVIEW</div>
                <div class="watermark-text">PREVIEW</div>
                <div class="watermark-text">PREVIEW</div>
            </div>

            <div class="receipt-header">
                <div class="receipt-logo-section">
                    ${storeLogoHTML}
                    <div class="receipt-store-info">
                        <div class="receipt-store-name">${escapeHtml(storeDisplayName)}</div>
                        <div class="receipt-store-tagline">${currentStore.physical_address || ''}</div>
                        <div class="receipt-store-details">
                            ${currentStore.phone ? `<div><i class="bi bi-telephone-fill"></i> ${escapeHtml(currentStore.phone)}</div>` : ''}
                            ${currentStore.email ? `<div><i class="bi bi-envelope-fill"></i> ${escapeHtml(currentStore.email)}</div>` : ''}
                            ${currentStore.tin ? `<div><strong>TIN:</strong> ${escapeHtml(currentStore.tin)}</div>` : ''}
                        </div>
                    </div>
                </div>
            </div>

            <div class="receipt-info-grid">
                <div class="receipt-customer-section">
                    <div class="receipt-customer-title">
                        <i class="bi bi-person-circle"></i>
                        Customer Information
                    </div>
                    ${customer ? `
                        <div class="receipt-customer-row">
                            <span class="receipt-customer-label">Name:</span>
                            <span class="receipt-customer-value">${escapeHtml(customer.name)}</span>
                        </div>
                        ${customer.phone ? `<div class="receipt-customer-row">
                            <span class="receipt-customer-label">Phone:</span>
                            <span class="receipt-customer-value">${escapeHtml(customer.phone)}</span>
                        </div>` : ''}
                        ${customer.email ? `<div class="receipt-customer-row">
                            <span class="receipt-customer-label">Email:</span>
                            <span class="receipt-customer-value">${escapeHtml(customer.email)}</span>
                        </div>` : ''}
                        ${customer.tin ? `<div class="receipt-customer-row">
                            <span class="receipt-customer-label">TIN:</span>
                            <span class="receipt-customer-value">${escapeHtml(customer.tin)}</span>
                        </div>` : ''}
                    ` : `
                        <div class="receipt-customer-walkin">
                            <i class="bi bi-person-walking"></i> Walk-in Customer
                        </div>
                    `}
                </div>

                <div class="receipt-details-section">
                    <div class="receipt-info-row">
                        <span class="receipt-info-label">
                            <i class="bi bi-receipt"></i>
                            ${docTypeLabel} No:
                        </span>
                        <span class="receipt-info-value">PREVIEW-${Date.now().toString().slice(-6)}</span>
                    </div>
                    <div class="receipt-info-row">
                        <span class="receipt-info-label">
                            <i class="bi bi-clock-history"></i>
                            Date:
                        </span>
                        <span class="receipt-info-value">${currentDate.toLocaleDateString('en-GB')} ${currentDate.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</span>
                    </div>
                </div>
            </div>



            <table class="receipt-items-table">
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

            <div class="receipt-bottom-section">
                <div class="receipt-qr-section">
                    <div class="preview-qr-placeholder">
                        <i class="bi bi-qr-code" style="font-size: 80px; opacity: 0.2;"></i>
                        <div style="margin-top: 10px; font-size: 11px;">QR Code will appear<br>after completing sale</div>
                    </div>
                </div>

                <div class="receipt-totals-section">
                    <div class="receipt-total-row">
                        <span>Subtotal:</span>
                        <span>${formatCurrency(subtotal)} UGX</span>
                    </div>
                    ${totalTax > 0 ? `<div class="receipt-total-row">
                        <span>Tax (18%):</span>
                        <span>${formatCurrency(totalTax)} UGX</span>
                    </div>` : ''}
                    ${totalDiscount > 0 ? `<div class="receipt-total-row">
                        <span>Discount:</span>
                        <span>-${formatCurrency(totalDiscount)} UGX</span>
                    </div>` : ''}
                    <div class="receipt-total-row final">
                        <span>TOTAL:</span>
                        <span>${formatCurrency(total)} UGX</span>
                    </div>
                </div>
            </div>

            <div class="receipt-footer">
                <div class="receipt-footer-main">
                    <div style="color: #dc2626; font-weight: 700; font-style: italic; margin-bottom: 6px;">
                        *Goods and money once received cannot be returned!*
                    </div>
                    <div style="font-weight: 600; font-size: 13px;">
                        THANK YOU FOR THE BUSINESS!
                    </div>
                </div>
                <div style="font-size: 10px; margin: 10px 0 5px 0;">
                    Preview: ${new Date().toLocaleDateString('en-GB')} ${new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
                </div>
                <div class="receipt-footer-powered">
                    Powered by <strong>Primebooks</strong> (www.primebooks.sale)
                </div>
            </div>
        </div>
    `;
}

/**
 * Print from preview modal
 */
function printFromPreview() {
    window.print();
}

// Export functions
window.printReceiptPreview = printReceiptPreview;
window.printFromPreview = printFromPreview;