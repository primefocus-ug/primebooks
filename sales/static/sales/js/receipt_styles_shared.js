// ============================================
// SHARED RECEIPT STYLES FOR PREVIEWS
// This file contains all receipt styles that should be
// consistent across receipt.html, draft previews, and print previews
// ============================================

/**
 * Get complete receipt styles for dynamic preview generation
 * This should match the styles in receipt.html exactly
 */
function getDynamicReceiptStyles() {
    return `
        <style>
            /* ==========================================
               RECEIPT DESIGN SYSTEM - COLOR VARIABLES
               ========================================== */
            :root {
                --receipt-primary: #7c3aed;      /* Purple */
                --receipt-primary-dark: #6d28d9;
                --receipt-secondary: #ec4899;    /* Pink */
                --receipt-accent: #f97316;       /* Orange */
                --receipt-dark: #1f2937;
                --receipt-gray: #6b7280;
                --receipt-light-gray: #f3f4f6;
                --receipt-border: #e5e7eb;
                --receipt-success: #10b981;
                --receipt-white: #ffffff;
            }

            /* ==========================================
               COMMON STYLES FOR BOTH FORMATS
               ========================================== */
            body {
                background: var(--receipt-light-gray) !important;
            }

            /* ==========================================
               A4 FORMAT STYLES (DEFAULT)
               ========================================== */
            .receipt-print-container.format-a4 {
                max-width: 210mm;
                min-height: 297mm;
                margin: 2rem auto;
                padding: 15mm;
                background: var(--receipt-white);
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1),
                            0 2px 4px -1px rgba(0, 0, 0, 0.06);
                border-radius: 8px;
            }

            /* ==========================================
               THERMAL FORMAT STYLES (80mm width)
               ========================================== */
            .receipt-print-container.format-thermal {
                max-width: 80mm;
                width: 80mm;
                margin: 2rem auto;
                padding: 5mm;
                background: var(--receipt-white);
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1),
                            0 2px 4px -1px rgba(0, 0, 0, 0.06);
                border-radius: 4px;
                font-size: 11px;
            }

            /* Thermal-specific header adjustments */
            .format-thermal .receipt-header {
                padding-bottom: 10px;
                margin-bottom: 10px;
                border-bottom: 2px dashed var(--receipt-dark);
            }

            .format-thermal .receipt-logo {
                width: 50px;
                height: 50px;
            }

            .format-thermal .receipt-store-name {
                font-size: 16px;
                margin-bottom: 4px;
            }

            .format-thermal .receipt-store-tagline {
                font-size: 9px;
                margin-bottom: 6px;
            }

            .format-thermal .receipt-store-details {
                font-size: 9px;
                line-height: 1.4;
                flex-direction: column;
                gap: 2px;
            }

            /* Thermal-specific grid - stacked vertically */
            .format-thermal .receipt-info-grid {
                grid-template-columns: 1fr;
                gap: 8px;
                margin-bottom: 10px;
            }

            .format-thermal .receipt-customer-section,
            .format-thermal .receipt-details-section {
                padding: 8px;
            }

            .format-thermal .receipt-customer-title,
            .format-thermal .receipt-info-label {
                font-size: 9px;
            }

            .format-thermal .receipt-customer-value,
            .format-thermal .receipt-info-value {
                font-size: 10px;
            }

            /* Thermal-specific table */
            .format-thermal .receipt-items-table th {
                padding: 6px 4px;
                font-size: 9px;
            }

            .format-thermal .receipt-items-table td {
                padding: 6px 4px;
                font-size: 9px;
            }

            .format-thermal .receipt-item-name {
                font-size: 10px;
                margin-bottom: 2px;
            }

            .format-thermal .receipt-item-code {
                font-size: 8px;
            }

            .format-thermal .receipt-item-badge {
                font-size: 7px;
                padding: 1px 4px;
            }

            /* Thermal-specific bottom section - stacked */
            .format-thermal .receipt-bottom-section {
                grid-template-columns: 1fr;
                gap: 10px;
                margin-bottom: 10px;
            }

            .format-thermal .receipt-qr-section {
                padding: 8px;
            }

            .format-thermal .receipt-efris-qr {
                width: 100px;
                height: 100px;
            }

            .format-thermal .receipt-efris-details {
                font-size: 8px;
            }

            .format-thermal .receipt-totals-section {
                padding-top: 8px;
            }

            .format-thermal .receipt-total-row {
                padding: 4px 0;
                font-size: 10px;
            }

            .format-thermal .receipt-total-row.final {
                font-size: 14px;
                padding-top: 8px;
            }

            /* Thermal-specific footer */
            .format-thermal .receipt-footer {
                margin-top: 8px;
                padding-top: 8px;
                border-top: 2px dashed var(--receipt-dark);
            }

            .format-thermal .receipt-footer-main {
                font-size: 10px;
            }

            .format-thermal .receipt-footer-powered {
                font-size: 8px;
            }

            /* ==========================================
               PRINT-SPECIFIC STYLES
               ========================================== */
            @media print {
                /* Hide all base template elements */
                .header,
                .sidebar,
                .sidebar-overlay,
                .print-controls,
                .format-selector,
                .no-print {
                    display: none !important;
                }

                /* Reset main wrapper */
                .main-wrapper {
                    margin: 0 !important;
                    padding: 0 !important;
                }

                .main-content {
                    padding: 0 !important;
                    max-width: 100% !important;
                }

                body {
                    background: white !important;
                }

                /* A4 Print Settings */
                .receipt-print-container.format-a4 {
                    width: 210mm !important;
                    min-height: 297mm !important;
                    margin: 0 !important;
                    padding: 15mm !important;
                    background: white !important;
                    box-shadow: none !important;
                    border-radius: 0 !important;
                }

                /* Thermal Print Settings (80mm) */
                .receipt-print-container.format-thermal {
                    width: 80mm !important;
                    max-width: 80mm !important;
                    margin: 0 !important;
                    padding: 5mm !important;
                    background: white !important;
                    box-shadow: none !important;
                    border-radius: 0 !important;
                }

                /* Ensure colors print */
                * {
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                }

                /* Page break control */
                .receipt-print-container {
                    page-break-after: avoid;
                }

                /* Dynamic page size based on format */
                @page {
                    margin: 0;
                }

                /* A4 page size */
                .format-a4 {
                    page: a4-page;
                }

                @page a4-page {
                    size: A4;
                }

                /* Thermal page size (80mm wide, auto height) */
                .format-thermal {
                    page: thermal-page;
                }

                @page thermal-page {
                    size: 80mm auto;
                }
            }

            /* ==========================================
               RECEIPT HEADER - CENTERED DESIGN
               ========================================== */
            .receipt-header {
                text-align: center;
                padding-bottom: 20px;
                border-bottom: 3px solid var(--receipt-primary);
                margin-bottom: 20px;
                background: linear-gradient(to bottom, rgba(124, 58, 237, 0.02), transparent);
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

            .receipt-store-info {
                max-width: 600px;
                margin: 0 auto;
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

            .receipt-store-tagline {
                font-size: 12px;
                color: var(--receipt-gray);
                font-style: italic;
                margin-bottom: 12px;
                font-weight: 500;
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

            .receipt-store-details div {
                display: flex;
                align-items: center;
                gap: 6px;
            }

            .receipt-store-details i {
                color: var(--receipt-primary);
                width: 14px;
            }

            /* ==========================================
               TWO-COLUMN INFO GRID (Customer + Receipt Info)
               ========================================== */
            .receipt-info-grid {
                display: grid;
                grid-template-columns: 1.2fr 1fr;
                gap: 20px;
                margin-bottom: 20px;
                padding: 0;
                background: transparent;
                border-radius: 0;
            }

            /* Customer Info Section - Left Column */
            .receipt-customer-section {
                background: linear-gradient(135deg, rgba(124, 58, 237, 0.05), rgba(236, 72, 153, 0.05));
                border: 2px solid var(--receipt-primary);
                border-radius: 10px;
                padding: 18px;
                box-shadow: 0 2px 8px rgba(124, 58, 237, 0.08);
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

            .receipt-customer-title i {
                font-size: 14px;
            }

            .receipt-customer-row {
                display: flex;
                justify-content: space-between;
                align-items: baseline;
                font-size: 11px;
                margin-bottom: 8px;
                padding: 6px 0;
                border-bottom: 1px solid rgba(124, 58, 237, 0.1);
            }

            .receipt-customer-row:last-child {
                margin-bottom: 0;
                border-bottom: none;
            }

            .receipt-customer-label {
                font-weight: 700;
                color: var(--receipt-gray);
                text-transform: uppercase;
                font-size: 9px;
                letter-spacing: 0.5px;
                flex-shrink: 0;
            }

            .receipt-customer-value {
                font-weight: 600;
                color: var(--receipt-dark);
                font-size: 11px;
                text-align: right;
                word-break: break-word;
            }

            .receipt-customer-walkin {
                text-align: center;
                color: var(--receipt-gray);
                font-style: italic;
                padding: 20px;
                font-size: 12px;
            }

            /* Receipt Details Section - Right Column */
            .receipt-details-section {
                background: var(--receipt-light-gray);
                border: 2px solid var(--receipt-border);
                border-radius: 10px;
                padding: 18px;
                display: flex;
                flex-direction: column;
                justify-content: center;
                gap: 12px;
                box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
            }

            .receipt-info-row {
                display: flex;
                justify-content: space-between;
                align-items: center;
                padding: 10px 0;
                border-bottom: 2px solid var(--receipt-border);
            }

            .receipt-info-row:last-child {
                border-bottom: none;
            }

            .receipt-info-label {
                font-weight: 700;
                color: var(--receipt-gray);
                text-transform: uppercase;
                font-size: 10px;
                letter-spacing: 0.6px;
                display: flex;
                align-items: center;
                gap: 6px;
            }

            .receipt-info-label i {
                color: var(--receipt-primary);
                font-size: 12px;
            }

            .receipt-info-value {
                font-weight: 800;
                color: var(--receipt-dark);
                font-size: 13px;
                font-family: 'Courier New', monospace;
                background: white;
                padding: 4px 10px;
                border-radius: 4px;
                border: 1px solid var(--receipt-border);
            }

            /* ==========================================
               ITEMS TABLE - DYNAMIC SIZING
               ========================================== */
            .receipt-items-table {
                width: 100%;
                border-collapse: collapse;
                margin-bottom: 15px;
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
                letter-spacing: 0.5px;
            }

            .receipt-items-table th:last-child,
            .receipt-items-table td:last-child {
                text-align: right;
            }

            .receipt-items-table tbody tr {
                border-bottom: 1px solid var(--receipt-border);
            }

            .receipt-items-table tbody tr:hover {
                background: var(--receipt-light-gray);
            }

            .receipt-items-table td {
                padding: 12px 10px;
                font-size: 12px;
                color: var(--receipt-dark);
            }

            /* Dynamic font sizing based on item count */
            .receipt-items-table.many-items td {
                padding: 8px 10px;
                font-size: 10px;
            }

            .receipt-items-table.many-items th {
                padding: 10px 10px;
                font-size: 10px;
            }

            .receipt-items-table.many-items .receipt-item-name {
                font-size: 10px;
            }

            .receipt-items-table.many-items .receipt-item-code {
                font-size: 8px;
            }

            .receipt-items-table.many-items .receipt-item-badge {
                font-size: 7px;
                padding: 1px 6px;
            }

            .receipt-item-name {
                font-weight: 600;
                color: var(--receipt-dark);
                margin-bottom: 3px;
            }

            .receipt-item-code {
                font-size: 10px;
                color: var(--receipt-gray);
                font-family: 'Courier New', monospace;
            }

            .receipt-item-badge {
                display: inline-block;
                padding: 2px 8px;
                border-radius: 4px;
                font-size: 9px;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.3px;
                margin-top: 4px;
            }

            .receipt-item-badge.product {
                background: #dbeafe;
                color: #1e40af;
            }

            .receipt-item-badge.service {
                background: #fce7f3;
                color: #be185d;
            }

            /* ==========================================
               TOTALS AND QR CODE SECTION - 50/50 SPLIT
               ========================================== */
            .receipt-bottom-section {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-bottom: 15px;
            }

            /* QR Code Section */
            .receipt-qr-section {
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 15px;
            }

            .receipt-efris-container {
                text-align: center;
            }

            .receipt-efris-qr {
                width: 150px;
                height: 150px;
                margin: 0 auto;
                border: 2px solid var(--receipt-border);
                border-radius: 8px;
                padding: 5px;
                background: white;
            }

            .receipt-efris-details {
                font-size: 10px;
                color: var(--receipt-dark);
                margin-top: 10px;
                line-height: 1.6;
            }

            /* Totals Section */
            .receipt-totals-section {
                border-top: 2px solid var(--receipt-primary);
                padding-top: 15px;
            }

            .receipt-total-row {
                display: flex;
                justify-content: space-between;
                padding: 8px 0;
                font-size: 13px;
            }

            .receipt-total-label {
                font-weight: 600;
                color: var(--receipt-gray);
            }

            .receipt-total-value {
                font-weight: 700;
                color: var(--receipt-dark);
            }

            .receipt-total-row.discount .receipt-total-value {
                color: #ef4444;
            }

            .receipt-total-row.final {
                border-top: 2px solid var(--receipt-dark);
                margin-top: 5px;
                padding-top: 15px;
                font-size: 18px;
            }

            .receipt-total-row.final .receipt-total-label,
            .receipt-total-row.final .receipt-total-value {
                color: var(--receipt-primary);
                font-weight: 800;
            }

            /* ==========================================
               FOOTER - REDUCED SPACING
               ========================================== */
            .receipt-footer {
                margin-top: 10px;
                padding-top: 15px;
                border-top: 2px solid var(--receipt-border);
                text-align: center;
            }

            .receipt-footer-main {
                font-size: 12px;
                color: var(--receipt-gray);
                margin-bottom: 5px;
                line-height: 1.2;
            }

            .receipt-footer-powered {
                font-size: 11px;
                color: var(--receipt-gray);
                margin-top: 5px;
            }

            .receipt-footer-powered strong {
                color: var(--receipt-primary);
                font-weight: 700;
            }

            .receipt-footer-powered a {
                color: var(--receipt-primary);
                text-decoration: none;
                font-weight: 600;
            }

            .receipt-footer-powered a:hover {
                text-decoration: underline;
            }

            /* ==========================================
               RESPONSIVE DESIGN
               ========================================== */
            @media screen and (max-width: 768px) {
                .receipt-print-container.format-a4 {
                    margin: 0.5rem;
                    padding: 20px;
                }

                .receipt-print-container.format-thermal {
                    margin: 0.5rem auto;
                }

                .receipt-store-details {
                    flex-direction: column;
                    gap: 6px;
                }

                .receipt-info-grid {
                    grid-template-columns: 1fr;
                }

                .receipt-bottom-section {
                    grid-template-columns: 1fr;
                }
            }
        </style>
    `;
}

// Export for use in other files
if (typeof window !== 'undefined') {
    window.getDynamicReceiptStyles = getDynamicReceiptStyles;
}