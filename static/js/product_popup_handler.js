/**
 * Reusable Popup Manager
 * Use this across all pages for consistent popup behavior
 *
 * Usage:
 * PopupManager.open('product') - Opens product creation popup
 * PopupManager.open('category') - Opens category creation popup
 * PopupManager.open('supplier') - Opens supplier creation popup
 * PopupManager.onReceive('product', callback) - Handle received data
 */

const PopupManager = (function() {
    'use strict';

    // Configuration for different popup types
    const POPUP_CONFIGS = {
        product: {
            url: '/inventory/products/add/modal/',
            title: 'AddProduct',
            width: 900,
            height: 700,
            messageType: 'productCreated'
        },
        category: {
            url: '/inventory/categories/add/modal/',
            title: 'AddCategory',
            width: 800,
            height: 600,
            messageType: 'categoryCreated'
        },
        supplier: {
            url: '/inventory/suppliers/add/modal/',
            title: 'AddSupplier',
            width: 700,
            height: 500,
            messageType: 'supplierCreated'
        },
        customer: {
            url: '/crm/customers/add/modal/',
            title: 'AddCustomer',
            width: 800,
            height: 600,
            messageType: 'customerCreated'
        },
        tax_rate: {
            url: '/inventory/tax-rates/add/modal/',
            title: 'AddTaxRate',
            width: 600,
            height: 400,
            messageType: 'taxRateCreated'
        },
        warehouse: {
            url: '/inventory/warehouses/add/modal/',
            title: 'AddWarehouse',
            width: 700,
            height: 500,
            messageType: 'warehouseCreated'
        }
        // Add more configurations as needed
    };

    // Store callbacks for each popup type
    const callbacks = {};

    /**
     * Open a popup window
     * @param {string} type - Type of popup (product, category, etc.)
     * @param {object} options - Optional override settings
     * @returns {Window|null} - Popup window reference
     */
    function open(type, options = {}) {
        const config = POPUP_CONFIGS[type];

        if (!config) {
            console.error(`Unknown popup type: ${type}`);
            return null;
        }

        // Merge config with options
        const settings = { ...config, ...options };

        // Calculate centered position
        const left = (screen.width - settings.width) / 2;
        const top = (screen.height - settings.height) / 2;

        // Build window features string
        const features = [
            `width=${settings.width}`,
            `height=${settings.height}`,
            `left=${left}`,
            `top=${top}`,
            'scrollbars=yes',
            'resizable=yes'
        ].join(',');

        // Open the popup
        const popup = window.open(settings.url, settings.title, features);

        if (popup) {
            popup.focus();
        } else {
            alert('Please allow popups for this website to use this feature.');
        }

        return popup;
    }

    /**
     * Register a callback for when data is received from popup
     * @param {string} type - Type of popup (product, category, etc.)
     * @param {function} callback - Callback function to handle received data
     */
    function onReceive(type, callback) {
        const config = POPUP_CONFIGS[type];

        if (!config) {
            console.error(`Unknown popup type: ${type}`);
            return;
        }

        if (!callbacks[config.messageType]) {
            callbacks[config.messageType] = [];
        }

        callbacks[config.messageType].push(callback);
    }

    /**
     * Handle incoming messages from popups
     */
    function handleMessage(event) {
        // Optional: Verify origin for security
        // if (event.origin !== window.location.origin) return;

        const messageType = event.data.type;

        if (callbacks[messageType]) {
            callbacks[messageType].forEach(callback => {
                try {
                    callback(event.data);
                } catch (error) {
                    console.error('Error in popup callback:', error);
                }
            });
        }
    }

    /**
     * Add new item to Select2 dropdown and select it
     * @param {string} selector - jQuery selector for select element
     * @param {object} item - Item data with id and text/name
     * @param {string} textField - Field name to use for text (default: 'name')
     */
    function addToSelect2(selector, item, textField = 'name') {
        const $select = $(selector);

        if (!$select.length) {
            console.warn(`Select element not found: ${selector}`);
            return;
        }

        const text = item[textField] || item.name || item.text;
        const newOption = new Option(text, item.id, true, true);

        $select.append(newOption).trigger('change');
    }

    /**
     * Show success notification
     * @param {string} message - Success message to display
     * @param {string} type - Notification type (success, info, warning, danger)
     */
    function showNotification(message, type = 'success') {
        // Check if Bootstrap Toast is available
        if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
            const bgClass = {
                'success': 'bg-success',
                'info': 'bg-info',
                'warning': 'bg-warning',
                'danger': 'bg-danger'
            }[type] || 'bg-success';

            const icon = {
                'success': 'fa-check-circle',
                'info': 'fa-info-circle',
                'warning': 'fa-exclamation-triangle',
                'danger': 'fa-times-circle'
            }[type] || 'fa-check-circle';

            const toastHtml = `
                <div class="toast align-items-center text-white ${bgClass} border-0" role="alert">
                    <div class="d-flex">
                        <div class="toast-body">
                            <i class="fas ${icon} me-2"></i>${message}
                        </div>
                        <button type="button" class="btn-close btn-close-white me-2 m-auto"
                                data-bs-dismiss="toast"></button>
                    </div>
                </div>
            `;

            let container = document.getElementById('toast-container');
            if (!container) {
                container = document.createElement('div');
                container.id = 'toast-container';
                container.className = 'toast-container position-fixed top-0 end-0 p-3';
                container.style.zIndex = '9999';
                document.body.appendChild(container);
            }

            container.insertAdjacentHTML('beforeend', toastHtml);
            const toastElement = container.lastElementChild;
            const toast = new bootstrap.Toast(toastElement);
            toast.show();

            toastElement.addEventListener('hidden.bs.toast', function() {
                toastElement.remove();
            });
        } else {
            // Fallback to alert
            alert(message);
        }
    }

    /**
     * Refresh a DataTable
     * @param {string} selector - jQuery selector for table
     */
    function refreshDataTable(selector) {
        if ($.fn.DataTable && $(selector).length) {
            $(selector).DataTable().ajax.reload(null, false);
        }
    }

    /**
     * Register a configuration for a new popup type
     * @param {string} type - Unique identifier for popup type
     * @param {object} config - Configuration object
     */
    function registerPopup(type, config) {
        POPUP_CONFIGS[type] = {
            width: 800,
            height: 600,
            messageType: `${type}Created`,
            ...config
        };
    }

    // Initialize message listener
    window.addEventListener('message', handleMessage);

    // Public API
    return {
        open,
        onReceive,
        addToSelect2,
        showNotification,
        refreshDataTable,
        registerPopup,
        configs: POPUP_CONFIGS // Expose configs for inspection
    };
})();


/**
 * Pre-configured helper functions for common use cases
 */

// Product popup helpers
window.openProductPopup = function() {
    return PopupManager.open('product');
};

window.onProductCreated = function(callback) {
    PopupManager.onReceive('product', function(data) {
        const product = data.product;
        callback(product);
        PopupManager.showNotification(`Product "${product.name}" created successfully!`);
    });
};

// Category popup helpers
window.openCategoryPopup = function() {
    return PopupManager.open('category');
};

window.onCategoryCreated = function(callback) {
    PopupManager.onReceive('category', function(data) {
        const category = data.category;
        callback(category);
        PopupManager.showNotification(`Category "${category.name}" created successfully!`);
    });
};

// Supplier popup helpers
window.openSupplierPopup = function() {
    return PopupManager.open('supplier');
};

window.onSupplierCreated = function(callback) {
    PopupManager.onReceive('supplier', function(data) {
        const supplier = data.supplier;
        callback(supplier);
        PopupManager.showNotification(`Supplier "${supplier.name}" created successfully!`);
    });
};

// Customer popup helpers
window.openCustomerPopup = function() {
    return PopupManager.open('customer');
};

window.onCustomerCreated = function(callback) {
    PopupManager.onReceive('customer', function(data) {
        const customer = data.customer;
        callback(customer);
        PopupManager.showNotification(`Customer "${customer.name}" created successfully!`);
    });
};


/**
 * jQuery plugin for easy integration
 * Usage: $('#product_select').popupSelect('product');
 */
if (typeof jQuery !== 'undefined') {
    (function($) {
        $.fn.popupSelect = function(popupType, options = {}) {
            return this.each(function() {
                const $select = $(this);
                const $wrapper = $select.parent();

                // Create button if it doesn't exist
                if (!$wrapper.find('.popup-add-btn').length) {
                    const buttonText = options.buttonText || 'Add';
                    const buttonClass = options.buttonClass || 'btn-outline-primary';

                    const $button = $(`
                        <button type="button" class="btn ${buttonClass} popup-add-btn">
                            <i class="fas fa-plus me-1"></i>${buttonText}
                        </button>
                    `);

                    // Wrap in input-group if not already
                    if (!$wrapper.hasClass('input-group')) {
                        $select.wrap('<div class="input-group"></div>');
                    }

                    $select.after($button);

                    // Attach click handler
                    $button.on('click', function() {
                        PopupManager.open(popupType, options.popupOptions);
                    });
                }

                // Register callback to update this select
                PopupManager.onReceive(popupType, function(data) {
                    const itemKey = Object.keys(data).find(key => key !== 'type');
                    const item = data[itemKey];

                    if (item && item.id) {
                        PopupManager.addToSelect2($select, item, options.textField);
                    }
                });
            });
        };
    })(jQuery);
}


// Export for use in modules (if needed)
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PopupManager;
}