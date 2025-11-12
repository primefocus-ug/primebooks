// efris/static/efris/js/efris-utils.js

/**
 * EFRIS Utilities
 * Common JavaScript functions for EFRIS operations
 */

const EFRISUtils = {
    /**
     * Format amount with currency
     */
    formatAmount: function(amount, currency = 'UGX') {
        const formatter = new Intl.NumberFormat('en-UG', {
            style: 'currency',
            currency: currency,
            minimumFractionDigits: 2
        });
        return formatter.format(amount);
    },

    /**
     * Format date
     */
    formatDate: function(dateString, format = 'short') {
        const date = new Date(dateString);
        const options = format === 'short'
            ? { year: 'numeric', month: 'short', day: 'numeric' }
            : { year: 'numeric', month: 'long', day: 'numeric', hour: '2-digit', minute: '2-digit' };
        return date.toLocaleDateString('en-UG', options);
    },

    /**
     * Get invoice type label
     */
    getInvoiceTypeLabel: function(typeCode) {
        const types = {
            '1': 'Invoice/Receipt',
            '2': 'Credit Note',
            '4': 'Debit Note',
            '5': 'Credit Memo'
        };
        return types[typeCode] || 'Unknown';
    },

    /**
     * Get approval status badge HTML
     */
    getStatusBadge: function(statusCode) {
        const statuses = {
            '101': '<span class="badge status-approved">Approved</span>',
            '102': '<span class="badge status-pending">Pending</span>',
            '103': '<span class="badge status-rejected">Rejected</span>'
        };
        return statuses[statusCode] || '<span class="badge bg-secondary">Unknown</span>';
    },

    /**
     * Validate TIN format
     */
    validateTIN: function(tin) {
        const cleanTIN = tin.replace(/[\s-]/g, '');
        return cleanTIN.length === 10 && /^\d+$/.test(cleanTIN);
    },

    /**
     * Show loading indicator
     */
    showLoading: function(message = 'Loading...') {
        const loadingHTML = `
            <div id="efris-loading" class="modal fade show" style="display: block; background: rgba(0,0,0,0.5);">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-body text-center py-4">
                            <div class="spinner-border text-primary mb-3" style="width: 3rem; height: 3rem;">
                                <span class="visually-hidden">Loading...</span>
                            </div>
                            <h5>${message}</h5>
                        </div>
                    </div>
                </div>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', loadingHTML);
    },

    /**
     * Hide loading indicator
     */
    hideLoading: function() {
        const loading = document.getElementById('efris-loading');
        if (loading) {
            loading.remove();
        }
    },

    /**
     * Show alert message
     */
    showAlert: function(message, type = 'info') {
        const alertHTML = `
            <div class="alert alert-${type} alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3"
                 style="z-index: 9999; min-width: 300px;" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;
        document.body.insertAdjacentHTML('beforeend', alertHTML);

        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            const alert = document.querySelector('.alert');
            if (alert) {
                alert.remove();
            }
        }, 5000);
    },

    /**
     * Confirm action
     */
    confirmAction: function(message, callback) {
        if (confirm(message)) {
            callback();
        }
    },

    /**
     * AJAX helper
     */
    ajax: function(url, options = {}) {
        const defaults = {
            method: 'GET',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        };

        const config = { ...defaults, ...options };

        // Add CSRF token for POST requests
        if (config.method === 'POST') {
            const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
            if (csrfToken) {
                config.headers['X-CSRFToken'] = csrfToken;
            }
        }

        return fetch(url, config)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .catch(error => {
                console.error('AJAX Error:', error);
                throw error;
            });
    }
};

// Make available globally
window.EFRISUtils = EFRISUtils;