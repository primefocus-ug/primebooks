// ============================================
// SALE PAGE - MAIN MODULE
// ============================================

import keyboardNavigation from 'sales/js/keyboard-navigation.js';
import offlineSaleManager from 'static/js/offline-manager.js';

// ============================================
// GLOBAL STATE
// ============================================

window.SaleState = {
    cart: [],
    items: [],
    currentPage: 1,
    itemsPerPage: 20,
    totalItems: 0,
    selectedCustomer: null,
    currentItemType: 'all',
    discount: {
        type: 'percentage',
        value: 0
    },
    searchCache: new Map(),
    recentCustomers: [],
    drafts: [],
    keyboardShortcutsEnabled: true,
    activeTab: 'searchTab'
};

// Credit information
let currentCustomerCredit = {
    allowCredit: false,
    creditLimit: 0,
    creditBalance: 0,
    creditAvailable: 0,
    creditStatus: '',
    hasOverdue: false
};

// ============================================
// UTILITY FUNCTIONS
// ============================================

window.getCookie = function(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
};

window.formatCurrency = function(amount) {
    return new Intl.NumberFormat('en-UG', {
        style: 'currency',
        currency: 'UGX',
        minimumFractionDigits: 0,
        maximumFractionDigits: 0
    }).format(amount);
};

window.escapeHtml = function(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
};

window.showToast = function(message, type = 'info') {
    const container = document.querySelector('.toast-container');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <i class="bi ${type === 'success' ? 'bi-check-circle-fill text-success' :
                          type === 'error' ? 'bi-exclamation-circle-fill text-danger' :
                          type === 'warning' ? 'bi-exclamation-triangle-fill text-warning' :
                          'bi-info-circle-fill text-info'}"></i>
        <span>${message}</span>
    `;

    container.appendChild(toast);
    setTimeout(() => toast.classList.add('show'), 10);

    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => {
            if (container.contains(toast)) {
                container.removeChild(toast);
            }
        }, 300);
    }, 5000);

    // Announce to screen readers
    if (keyboardNavigation.announce) {
        keyboardNavigation.announce(message);
    }
};

window.showError = function(message) {
    console.error('Error:', message);

    try {
        const errorContent = document.getElementById('errorModalContent');
        if (errorContent) {
            errorContent.innerHTML = `
                <div class="alert alert-danger">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    ${escapeHtml(message)}
                </div>
            `;
            const modal = new bootstrap.Modal(document.getElementById('errorModal'));
            modal.show();
            return;
        }
    } catch (e) {
        console.warn('Could not show error modal:', e);
    }

    alert('Error: ' + message);
};

window.showLoading = function(show) {
    const loadingOverlay = document.getElementById('loadingOverlay');
    if (loadingOverlay) {
        loadingOverlay.style.display = show ? 'flex' : 'none';
    }
};

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// ============================================
// INITIALIZATION
// ============================================

document.addEventListener('DOMContentLoaded', async function() {
    console.log('✅ Initializing Sale Page...');

    // Initialize offline manager first
    const offlineReady = await offlineSaleManager.init();
    if (offlineReady) {
        console.log('✅ Offline features enabled');
        showToast('Offline mode enabled - you can work without internet!', 'success');
    }

    // Initialize keyboard navigation
    setTimeout(() => {
        keyboardNavigation.init();
        showToast('⌨️ Keyboard Navigation Enabled - Press ? for shortcuts', 'info');
    }, 500);

    // Setup event listeners
    setupSaleEventListeners();
    setupCustomerSearchListeners();
    setupCustomerDropdownCloseHandler();

    // Load initial data
    loadRecentCustomers();
    checkForDrafts();

    const storeId = document.getElementById('storeSelect')?.value;
    if (storeId) {
        loadItems();
    }

    const paymentMethodSelect = document.getElementById('paymentMethod');
    if (paymentMethodSelect) {
        paymentMethodSelect.addEventListener('change', validatePaymentMethod);
    }

    toggleDueDateSection();

    // Check for customer from URL
    const urlParams = new URLSearchParams(window.location.search);
    const customerIdFromUrl = urlParams.get('customer_id');
    if (customerIdFromUrl) {
        console.log('🔗 Customer ID from URL:', customerIdFromUrl);
        showToast('Loading customer...', 'info');
        fetchAndSelectCustomerById(customerIdFromUrl);
    }

    // Setup credit adjustment type change handler
    const adjustmentType = document.getElementById('creditAdjustmentType');
    const hintText = document.getElementById('creditAdjustmentHint');

    if (adjustmentType && hintText) {
        adjustmentType.addEventListener('change', function() {
            const type = this.value;
            const currentLimit = currentCustomerCredit.creditLimit;
            const currentBalance = currentCustomerCredit.creditBalance;

            switch(type) {
                case 'SET_LIMIT':
                    hintText.textContent = `Current limit: ${formatCurrency(currentLimit)}. Enter new limit.`;
                    break;
                case 'INCREASE_LIMIT':
                    hintText.textContent = `Current limit: ${formatCurrency(currentLimit)}. Enter amount to add.`;
                    break;
                case 'DECREASE_LIMIT':
                    hintText.textContent = `Current limit: ${formatCurrency(currentLimit)}. Enter amount to subtract.`;
                    break;
                case 'ADD_BALANCE':
                    hintText.textContent = `Current balance: ${formatCurrency(currentBalance)}. Enter amount to add.`;
                    break;
                case 'REDUCE_BALANCE':
                    hintText.textContent = `Current balance: ${formatCurrency(currentBalance)}. Enter amount to subtract.`;
                    break;
                default:
                    hintText.textContent = '';
            }
        });

        adjustmentType.dispatchEvent(new Event('change'));
    }

    // Show keyboard tutorial if first visit
    if (!localStorage.getItem('keyboardTutorialCompleted')) {
        setTimeout(() => {
            const tutorial = document.getElementById('keyboardTutorial');
            if (tutorial) tutorial.classList.add('show');
        }, 1000);
    }

    console.log('✅ Sale Page Initialized');
});

// ============================================
// EVENT LISTENERS SETUP
// ============================================

function setupSaleEventListeners() {
    // Store selection
    const storeSelect = document.getElementById('storeSelect');
    if (storeSelect) {
        storeSelect.addEventListener('change', function() {
            const storeId = this.value;
            console.log('🏪 Store changed to:', storeId);

            SaleState.currentPage = 1;
            loadItems();
            validateStoreSelection();

            if (SaleState.selectedCustomer) {
                console.log('🧹 Clearing customer selection due to store change');
                removeCustomer();
                showToast('Customer cleared. Please select customer for this branch.', 'info');
            }

            if (SaleState.activeTab === 'recentTab') {
                loadRecentCustomers();
            }

            const customerSearch = document.getElementById('customerSearch');
            if (customerSearch) customerSearch.value = '';

            const customerDropdown = document.getElementById('customerDropdown');
            if (customerDropdown) customerDropdown.classList.remove('show');

            for (const key of SaleState.searchCache.keys()) {
                if (key.includes('customer-search')) {
                    SaleState.searchCache.delete(key);
                }
            }
        });
    }

    // Product search
    const productSearchBar = document.getElementById('productSearchBar');
    if (productSearchBar) {
        productSearchBar.addEventListener('input', debounce(function(e) {
            console.log('🔍 Product search:', e.target.value);
            SaleState.currentPage = 1;
            loadItems();
        }, 300));
    }

    // Document type change
    document.querySelectorAll('input[name="document_type"]').forEach(radio => {
        radio.addEventListener('change', function() {
            console.log('📄 Document type changed to:', this.value);
            toggleDueDateSection();
            validateDocumentRequirements();
        });
    });

    // Discount value input
    const discountValue = document.getElementById('discountValue');
    if (discountValue) {
        discountValue.addEventListener('input', function() {
            const value = parseFloat(this.value) || 0;
            this.value = value;
        });
    }

    // Customer tab handlers
    const searchTabBtn = document.getElementById('searchTabBtn');
    const recentTabBtn = document.getElementById('recentTabBtn');
    const efrisTabBtn = document.getElementById('efrisTabBtn');

    if (searchTabBtn) {
        searchTabBtn.addEventListener('click', function(e) {
            console.log('🔍 Switched to Search tab');
            SaleState.activeTab = 'searchTab';
            setTimeout(setupCustomerSearchListeners, 100);
        });
    }

    if (recentTabBtn) {
        recentTabBtn.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('🕐 Switched to Recent tab');
            SaleState.activeTab = 'recentTab';
            loadRecentCustomers();
            const recentTab = new bootstrap.Tab(this);
            recentTab.show();
        });
    }

    if (efrisTabBtn) {
        efrisTabBtn.addEventListener('click', function(e) {
            e.preventDefault();
            console.log('🏛️ Switched to EFRIS tab');
            SaleState.activeTab = 'efrisTab';

            const efrisResults = document.getElementById('efrisQueryResults');
            const taxpayerTIN = document.getElementById('taxpayerTIN');
            const efrisError = document.getElementById('efrisError');

            if (efrisResults) efrisResults.style.display = 'none';
            if (taxpayerTIN) taxpayerTIN.value = '';
            if (efrisError) efrisError.style.display = 'none';

            const efrisTab = new bootstrap.Tab(this);
            efrisTab.show();
        });
    }

    // Payment method change
    const paymentMethodSelect = document.getElementById('paymentMethod');
    if (paymentMethodSelect) {
        paymentMethodSelect.addEventListener('change', function() {
            console.log('💳 Payment method changed to:', this.value);
            validatePaymentMethod();
            updateCreditAdjustmentVisibility();
        });
    }

    // New customer modal
    const newCustomerModal = document.getElementById('newCustomerModal');
    if (newCustomerModal) {
        newCustomerModal.addEventListener('show.bs.modal', function() {
            console.log('👤 Opening new customer modal');

            const storeSelect = document.getElementById('storeSelect');
            if (!storeSelect || !storeSelect.value) {
                showError('Please select a branch first before creating a customer');
                const modal = bootstrap.Modal.getInstance(newCustomerModal);
                if (modal) modal.hide();
                return;
            }

            const form = document.getElementById('newCustomerForm');
            if (form) form.reset();
        });

        newCustomerModal.addEventListener('hidden.bs.modal', function() {
            const form = document.getElementById('newCustomerForm');
            if (form) form.reset();
        });
    }

    // Form enter key handler
    const createSaleForm = document.getElementById('createSaleForm');
    if (createSaleForm) {
        createSaleForm.addEventListener('keypress', function(e) {
            if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') {
                e.preventDefault();
            }
        });
    }

    // Beforeunload warning
    window.addEventListener('beforeunload', function(e) {
        if (SaleState.cart.length > 0) {
            const message = 'You have items in your cart. Are you sure you want to leave?';
            e.returnValue = message;
            return message;
        }
    });

    // Online/offline detection
    window.addEventListener('online', function() {
        console.log('✅ Connection restored');
        showToast('Connection restored', 'success');
    });

    window.addEventListener('offline', function() {
        console.log('❌ Connection lost');
        showToast('No internet connection. Some features may not work.', 'warning');
    });

    console.log('✅ All sale event listeners attached successfully');
}

// ============================================
// CUSTOMER SEARCH
// ============================================

function createDebouncedSearch() {
    let timeout;
    let currentController = null;

    return function(func, wait) {
        return function executedFunction(...args) {
            if (currentController) {
                currentController.abort();
            }
            clearTimeout(timeout);
            timeout = setTimeout(() => {
                currentController = new AbortController();
                func.call(this, ...args, currentController);
            }, wait);
        };
    };
}

const debouncedSearchCustomers = createDebouncedSearch();

function setupCustomerSearchListeners() {
    const customerSearch = document.getElementById('customerSearch');

    if (!customerSearch) {
        console.warn('Customer search input not found during setup');
        return;
    }

    const newSearch = customerSearch.cloneNode(true);
    customerSearch.parentNode.replaceChild(newSearch, customerSearch);

    newSearch.addEventListener('input', debouncedSearchCustomers(searchCustomers, 300));

    newSearch.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
            e.preventDefault();
            searchCustomers();
        }
    });

    newSearch.addEventListener('focus', function() {
        if (this.value.trim().length >= 2) {
            const dropdown = document.getElementById('customerDropdown');
            if (dropdown && dropdown.querySelector('.customer-list-item')) {
                dropdown.classList.add('show');
            }
        }
    });

    console.log('✅ Customer search listeners attached');
}

function setupCustomerDropdownCloseHandler() {
    document.addEventListener('click', function(event) {
        const dropdown = document.getElementById('customerDropdown');
        const customerSection = document.querySelector('.customer-section');

        if (!dropdown || !customerSection) return;

        if (customerSection.contains(event.target)) {
            return;
        }

        dropdown.classList.remove('show');
    });
}

window.searchCustomers = async function(controller = null) {
    const customerSearch = document.getElementById('customerSearch');
    const searchLoading = document.getElementById('customerSearchLoading');
    const searchError = document.getElementById('customerSearchError');
    const dropdown = document.getElementById('customerDropdown');

    if (!customerSearch) {
        console.error('Customer search input not found');
        return;
    }

    const query = customerSearch.value.trim();

    if (searchError) searchError.style.display = 'none';

    if (query.length < 2) {
        if (dropdown) dropdown.classList.remove('show');
        if (searchLoading) searchLoading.style.display = 'none';
        return;
    }

    const storeSelect = document.getElementById('storeSelect');
    if (!storeSelect || !storeSelect.value) {
        if (searchError) {
            searchError.textContent = 'Please select a branch first to search customers';
            searchError.style.display = 'block';
        }
        return;
    }

    const storeId = storeSelect.value;

    if (searchLoading) searchLoading.style.display = 'flex';

    try {
        // Use offline-capable search
        const data = await offlineSaleManager.searchCustomers(query, storeId);

        if (data.customers && data.customers.length > 0) {
            displayCustomerList(data.customers);
        } else {
            const customerList = document.getElementById('customerList');
            if (customerList) {
                customerList.innerHTML = `
                    <div class="text-center py-3">
                        <i class="bi bi-person-x" style="font-size: 2rem; opacity: 0.3;"></i>
                        <p class="mt-2 mb-1">No customers found in this branch</p>
                        <small class="text-muted">Try a different search term or create a new customer</small>
                        <div class="mt-2">
                            <button class="btn btn-sm btn-primary"
                                    onclick="showNewCustomerModal()">
                                <i class="bi bi-plus me-1"></i> Create New Customer
                            </button>
                        </div>
                    </div>
                `;
            }
            if (dropdown) dropdown.classList.add('show');
        }

    } catch (error) {
        console.error('❌ Customer search error:', error);

        if (searchError) {
            searchError.textContent = `Search failed: ${error.message}. Please try again.`;
            searchError.style.display = 'block';
        }
    } finally {
        if (searchLoading) searchLoading.style.display = 'none';
    }
};

function displayCustomerList(customers) {
    const list = document.getElementById('customerList');
    const dropdown = document.getElementById('customerDropdown');

    if (!list) {
        console.error('Customer list element not found');
        return;
    }

    list.innerHTML = '';

    let customerArray = Array.isArray(customers) ? customers : [];

    console.log('📋 Displaying customer list, count:', customerArray.length);

    if (customerArray.length === 0) {
        if (dropdown) dropdown.classList.remove('show');
        return;
    }

    const listHTML = customerArray.map(customer => {
        const customerId = customer.id || customer.pk || customer.customer_id;
        const customerName = customer.name || customer.full_name || customer.business_name || 'Unknown';
        const customerPhone = customer.phone || customer.phone_number || customer.mobile || '';
        const customerEmail = customer.email || customer.email_address || '';
        const customerTin = customer.tin || customer.tax_id || '';
        const customerType = customer.customer_type || '';

        const isSelected = SaleState.selectedCustomer &&
                          SaleState.selectedCustomer.id === customerId;

        const customerJson = JSON.stringify(customer)
            .replace(/\\/g, '\\\\')
            .replace(/'/g, "\\'")
            .replace(/"/g, '&quot;');

        return `
            <div class="customer-list-item ${isSelected ? 'selected' : ''}"
                 onclick='selectCustomerSafely(${customerId}, \`${customerJson}\`)'
                 tabindex="0"
                 role="option"
                 aria-selected="${isSelected}">
                <div class="customer-list-item-avatar">
                    ${customerName.charAt(0).toUpperCase()}
                </div>
                <div class="customer-list-item-info">
                    <div class="customer-list-item-name">${escapeHtml(customerName)}</div>
                    <div class="customer-list-item-details">
                        ${customerPhone ? escapeHtml(customerPhone) : ''}
                        ${customerEmail ? ` | ${escapeHtml(customerEmail)}` : ''}
                    </div>
                </div>
                ${customerTin ? `
                    <span class="customer-list-item-badge ${customerType === 'BUSINESS' ? 'vat-registered' : ''}">
                        TIN: ${escapeHtml(customerTin)}
                    </span>
                ` : ''}
            </div>
        `;
    }).join('');

    list.innerHTML = listHTML;

    if (dropdown) {
        dropdown.classList.add('show');
    }
}

window.selectCustomerSafely = function(customerId, customerJsonString) {
    try {
        const decodedJson = customerJsonString
            .replace(/&quot;/g, '"')
            .replace(/&#39;/g, "'");

        const customer = JSON.parse(decodedJson);
        selectCustomer(customer);
    } catch (error) {
        console.error('Error selecting customer:', error);
        fetchAndSelectCustomer(customerId);
    }
};

async function fetchAndSelectCustomer(customerId) {
    try {
        const response = await fetch(`/sales/customer/${customerId}/`, {
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        if (!response.ok) {
            throw new Error('Failed to fetch customer details');
        }

        const data = await response.json();
        const customer = data.customer || data;
        selectCustomer(customer);
    } catch (error) {
        console.error('Error fetching customer:', error);
        showError('Failed to load customer details');
    }
}

async function fetchAndSelectCustomerById(customerId) {
    try {
        const response = await fetch(`/customers/api/customers/${customerId}/`, {
            headers: {
                'Accept': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            }
        });

        if (!response.ok) {
            throw new Error(`Failed to fetch customer: ${response.status}`);
        }

        const data = await response.json();
        const customer = data.customer || data;

        console.log('✅ Customer loaded from URL:', customer);

        selectCustomer(customer);

        const searchTabBtn = document.getElementById('searchTabBtn');
        if (searchTabBtn) {
            new bootstrap.Tab(searchTabBtn).show();
        }

        showToast(`Customer ${customer.name} selected`, 'success');

        const cartSection = document.querySelector('.cart-section');
        if (cartSection && window.innerWidth > 768) {
            cartSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }

    } catch (error) {
        console.error('❌ Error loading customer from URL:', error);
        showError(`Failed to load customer: ${error.message}`);

        const url = new URL(window.location);
        url.searchParams.delete('customer_id');
        window.history.replaceState({}, '', url);
    }
}

// Continue in next part due to length...
console.log('✅ Sale Page Module Loaded - Part 1/3');
// ============================================
// SALE PAGE - PART 2: Customer & Cart Management
// ============================================

// ============================================
// SELECT CUSTOMER
// ============================================

window.selectCustomer = function(customer) {
    SaleState.selectedCustomer = customer;

    const customerId = document.getElementById('customerId');
    const customerName = document.getElementById('customerName');
    const customerDetails = document.getElementById('customerDetails');
    const customerTin = document.getElementById('customerTin');
    const customerDisplay = document.getElementById('customerDisplay');
    const customerDropdown = document.getElementById('customerDropdown');
    const customerAvatar = document.getElementById('customerAvatar');
    const customerTinBadge = document.getElementById('customerTinBadge');

    if (customerId) customerId.value = customer.id;
    if (customerTin) customerTin.value = customer.tin || '';

    if (customerName) {
        customerName.textContent = customer.name;
    }

    if (customerDetails) {
        customerDetails.innerHTML = `
            <small class="text-muted">
                ${customer.phone || ''}
                ${customer.email ? ' • ' + customer.email : ''}
                ${customer.tin ? ' • TIN: ' + customer.tin : ''}
            </small>
        `;
    }

    if (customerDisplay) {
        customerDisplay.style.display = 'flex';
    }

    if (customerDropdown) {
        customerDropdown.style.display = 'none';
    }

    if (customerAvatar) {
        customerAvatar.textContent = customer.name.charAt(0).toUpperCase();
    }

    if (customerTinBadge) {
        if (customer.tin) {
            customerTinBadge.textContent = `TIN: ${customer.tin}`;
            customerTinBadge.style.display = 'inline-block';
        } else {
            customerTinBadge.style.display = 'none';
        }
    }

    if (customer.credit_info) {
        currentCustomerCredit = {
            allowCredit: customer.credit_info.allow_credit,
            creditLimit: parseFloat(customer.credit_info.credit_limit),
            creditBalance: parseFloat(customer.credit_info.credit_balance),
            creditAvailable: parseFloat(customer.credit_info.credit_available),
            creditStatus: customer.credit_info.credit_status,
            hasOverdue: customer.credit_info.has_overdue,
            overdue_amount: parseFloat(customer.credit_info.overdue_amount || 0)
        };

        displayCustomerCreditInfo(customer.credit_info);
    } else {
        const creditInfoDiv = document.getElementById('customerCreditInfo');
        if (creditInfoDiv) {
            creditInfoDiv.style.display = 'none';
        }
    }

    const notesSection = document.getElementById('customerNotesSection');
    if (notesSection) {
        notesSection.style.display = 'block';
    }

    updateCreditAdjustmentVisibility();
    addToRecentCustomers(customer);
    showToast(`Selected customer: ${customer.name}`, 'success');
    validatePaymentMethod();
};

function displayCustomerCreditInfo(creditInfo) {
    const creditInfoDiv = document.getElementById('customerCreditInfo');
    const creditWarningsDiv = document.getElementById('creditWarnings');

    if (!creditInfo.allow_credit) {
        if (creditInfoDiv) creditInfoDiv.style.display = 'none';
        return;
    }

    if (creditInfoDiv) {
        creditInfoDiv.style.display = 'block';
    }

    const creditLimit = document.getElementById('creditLimit');
    const creditBalance = document.getElementById('creditBalance');
    const creditAvailable = document.getElementById('creditAvailable');
    const statusBadge = document.getElementById('creditStatusBadge');

    if (creditLimit) creditLimit.textContent = formatCurrency(creditInfo.credit_limit);
    if (creditBalance) creditBalance.textContent = formatCurrency(creditInfo.credit_balance);
    if (creditAvailable) creditAvailable.textContent = formatCurrency(creditInfo.credit_available);

    if (statusBadge) {
        statusBadge.textContent = creditInfo.credit_status;
        statusBadge.className = 'badge ';

        switch(creditInfo.credit_status) {
            case 'GOOD':
                statusBadge.classList.add('bg-success');
                break;
            case 'WARNING':
                statusBadge.classList.add('bg-warning');
                break;
            case 'SUSPENDED':
            case 'BLOCKED':
                statusBadge.classList.add('bg-danger');
                break;
            default:
                statusBadge.classList.add('bg-secondary');
        }
    }

    if (creditWarningsDiv) {
        creditWarningsDiv.innerHTML = '';

        if (creditInfo.has_overdue) {
            creditWarningsDiv.innerHTML += `
                <div class="credit-error">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    <strong>Overdue Payments:</strong> Customer has overdue invoices totaling
                    ${formatCurrency(creditInfo.overdue_amount)}
                </div>
            `;
        }

        if (creditInfo.credit_status === 'WARNING') {
            creditWarningsDiv.innerHTML += `
                <div class="credit-warning">
                    <i class="bi bi-exclamation-circle me-2"></i>
                    <strong>Warning:</strong> Customer is approaching credit limit
                </div>
            `;
        }

        if (creditInfo.credit_status === 'SUSPENDED' || creditInfo.credit_status === 'BLOCKED') {
            creditWarningsDiv.innerHTML += `
                <div class="credit-error">
                    <i class="bi bi-x-circle me-2"></i>
                    <strong>Credit ${creditInfo.credit_status}:</strong>
                    ${creditInfo.credit_message || 'Customer cannot make credit purchases'}
                </div>
            `;
        }
    }
}

window.removeCustomer = function() {
    SaleState.selectedCustomer = null;

    const customerId = document.getElementById('customerId');
    const customerTin = document.getElementById('customerTin');
    const customerDisplay = document.getElementById('customerDisplay');
    const creditInfoDiv = document.getElementById('customerCreditInfo');

    if (customerId) customerId.value = '';
    if (customerTin) customerTin.value = '';
    if (customerDisplay) customerDisplay.style.display = 'none';
    if (creditInfoDiv) creditInfoDiv.style.display = 'none';

    currentCustomerCredit = {
        allowCredit: false,
        creditLimit: 0,
        creditBalance: 0,
        creditAvailable: 0,
        creditStatus: '',
        hasOverdue: false
    };

    const notesSection = document.getElementById('customerNotesSection');
    if (notesSection) {
        notesSection.style.display = 'none';
    }

    const noteText = document.getElementById('saleNoteText');
    const noteImportant = document.getElementById('noteIsImportant');
    const noteCategory = document.getElementById('noteCategory');

    if (noteText) noteText.value = '';
    if (noteImportant) noteImportant.checked = false;
    if (noteCategory) noteCategory.value = 'GENERAL';

    const creditAdjustSection = document.getElementById('creditAdjustmentSection');
    if (creditAdjustSection) {
        creditAdjustSection.style.display = 'none';
    }

    showToast('Customer removed', 'warning');
    validatePaymentMethod();
};

window.clearCustomerSearch = function() {
    const customerSearch = document.getElementById('customerSearch');
    const customerDropdown = document.getElementById('customerDropdown');
    const searchError = document.getElementById('customerSearchError');

    if (customerSearch) {
        customerSearch.value = '';
        customerSearch.focus();
    }

    if (customerDropdown) {
        customerDropdown.classList.remove('show');
    }

    if (searchError) {
        searchError.style.display = 'none';
    }
};

window.loadRecentCustomers = async function() {
    const loading = document.getElementById('recentCustomersLoading');
    const list = document.getElementById('recentCustomersList');

    if (!list) return;

    const storeSelect = document.getElementById('storeSelect');
    if (!storeSelect || !storeSelect.value) {
        list.innerHTML = `
            <div class="text-center py-3">
                <i class="bi bi-shop" style="font-size: 2rem; opacity: 0.3;"></i>
                <p class="mt-2">Please select a branch first</p>
            </div>
        `;
        if (loading) loading.style.display = 'none';
        return;
    }

    const storeId = storeSelect.value;

    list.innerHTML = '';
    if (loading) loading.style.display = 'block';

    try {
        const response = await fetch(`/sales/recent-customers/?store_id=${storeId}`);
        const data = await response.json();

        if (loading) loading.style.display = 'none';

        if (data.customers && data.customers.length > 0) {
            SaleState.recentCustomers = data.customers;
            displayRecentCustomers(data.customers);
        } else {
            displayRecentCustomers([]);
        }
    } catch (error) {
        console.error('Error loading recent customers:', error);
        if (loading) loading.style.display = 'none';
        list.innerHTML = `
            <div class="text-center py-3">
                <i class="bi bi-exclamation-triangle text-danger" style="font-size: 2rem;"></i>
                <p class="mt-2 text-danger">Failed to load recent customers</p>
            </div>
        `;
    }
};

function displayRecentCustomers(customers) {
    const list = document.getElementById('recentCustomersList');
    if (!list) return;

    if (customers.length === 0) {
        list.innerHTML = `
            <div class="text-center py-3">
                <i class="bi bi-clock-history" style="font-size: 2rem; opacity: 0.3;"></i>
                <p class="mt-2">No recent customers</p>
            </div>
        `;
        return;
    }

    list.innerHTML = customers.map(customer => `
        <div class="customer-list-item" onclick='selectCustomer(${JSON.stringify(customer).replace(/'/g, "&#39;")})'>
            <div class="customer-list-item-avatar">
                ${customer.name.charAt(0).toUpperCase()}
            </div>
            <div class="customer-list-item-info">
                <div class="customer-list-item-name">${escapeHtml(customer.name)}</div>
                <div class="customer-list-item-details">
                    ${customer.phone || ''}
                    ${customer.last_purchase ? ` | Last: ${new Date(customer.last_purchase).toLocaleDateString()}` : ''}
                </div>
            </div>
        </div>
    `).join('');
}

function addToRecentCustomers(customer) {
    SaleState.recentCustomers = SaleState.recentCustomers.filter(c => c.id !== customer.id);
    SaleState.recentCustomers.unshift(customer);

    if (SaleState.recentCustomers.length > 10) {
        SaleState.recentCustomers = SaleState.recentCustomers.slice(0, 10);
    }

    if (SaleState.activeTab === 'recentTab') {
        displayRecentCustomers(SaleState.recentCustomers);
    }
}

// ============================================
// NEW CUSTOMER MODAL
// ============================================

window.showNewCustomerModal = function() {
    const modal = new bootstrap.Modal(document.getElementById('newCustomerModal'));
    modal.show();
};

window.saveNewCustomer = async function() {
    const form = document.getElementById('newCustomerForm');
    const saveBtn = document.getElementById('saveCustomerBtn');
    const saveText = document.getElementById('saveCustomerText');
    const saveLoading = document.getElementById('saveCustomerLoading');

    if (!form || !saveBtn || !saveText || !saveLoading) return;

    if (!form.checkValidity()) {
        form.reportValidity();
        return;
    }

    const storeSelect = document.getElementById('storeSelect');
    if (!storeSelect || !storeSelect.value) {
        showError('Please select a branch first before creating a customer');
        return;
    }

    saveText.style.display = 'none';
    saveLoading.style.display = 'inline-block';
    saveBtn.disabled = true;

    const formData = new FormData(form);
    const customerData = {
        name: formData.get('name'),
        phone: formData.get('phone'),
        email: formData.get('email'),
        tin: formData.get('tin'),
        address: formData.get('address'),
        store_id: parseInt(storeSelect.value)
    };

    try {
        const result = await offlineSaleManager.createCustomer(customerData);

        if (result.success) {
            selectCustomer(result.customer);
            bootstrap.Modal.getInstance(document.getElementById('newCustomerModal')).hide();
            form.reset();

            const message = result.offline ?
                'Customer saved offline! Will sync when online.' :
                'Customer created successfully!';

            showToast(message, 'success');
        } else {
            throw new Error(result.error || 'Failed to create customer');
        }
    } catch (error) {
        showError(error.message);
    } finally {
        saveText.style.display = 'inline';
        saveLoading.style.display = 'none';
        saveBtn.disabled = false;
    }
};

// ============================================
// ITEMS/PRODUCTS LOADING
// ============================================

function validateStoreSelection() {
    const storeSelect = document.getElementById('storeSelect');
    const storeId = storeSelect?.value;

    if (!storeId && SaleState.currentItemType !== 'service') {
        showToast('Please select a store to view products', 'warning');
    }
}

window.loadItems = async function() {
    const storeSelect = document.getElementById('storeSelect');
    const productSearchBar = document.getElementById('productSearchBar');

    if (!storeSelect || !productSearchBar) return;

    const storeId = storeSelect.value;
    const query = productSearchBar.value;

    if (!storeId && SaleState.currentItemType !== 'service') {
        showProductsEmpty();
        return;
    }

    showProductsLoading();

    try {
        // Use offline-capable search
        const data = await offlineSaleManager.searchItems(
            query,
            SaleState.currentItemType,
            storeId
        );

        if (data.items && data.items.length > 0) {
            SaleState.items = data.items;
            SaleState.totalItems = data.total || data.items.length;
            displayItems(data.items);
            updatePaginationInfo();
        } else {
            showProductsEmpty();
        }
    } catch (error) {
        console.error('Error loading items:', error);
        hideProductsLoading();
        showError('Failed to load items. Please try again.');
    }
};

function displayItems(items) {
    const grid = document.getElementById('productsGrid');
    if (!grid) return;

    hideProductsLoading();

    if (items.length === 0) {
        showProductsEmpty();
        return;
    }

    grid.innerHTML = items.map((item, index) => {
        const isProduct = item.item_type === 'PRODUCT';
        const outOfStock = isProduct && item.stock && item.stock.available <= 0;
        const lowStock = isProduct && item.stock && item.stock.available <= (item.stock.minimum_stock || 10);
        const shortcutNumber = index < 9 ? index + 1 : null;

        const isCached = item.sync_status === 'synced' && !offlineSaleManager.isOnline;

        return `
            <div class="product-card ${outOfStock ? 'out-of-stock' : ''}"
                 data-item-index="${index}"
                 data-sync-status="${item.sync_status || 'synced'}">
                ${shortcutNumber ? `<span class="shortcut-badge">${shortcutNumber}</span>` : ''}
                ${isCached ? `<span class="cached-indicator">📱 Cached</span>` : ''}

                ${item.discount_percentage > 0 ? `
                    <div class="product-discount-badge">
                        -${item.discount_percentage}%
                    </div>
                ` : ''}

                <div class="product-image-placeholder">
                    <i class="bi ${isProduct ? 'bi-box' : 'bi-gear'}"></i>
                </div>

                <div class="product-info">
                    <div class="d-flex justify-content-between align-items-start mb-2">
                        <h6 class="product-name">${escapeHtml(item.name)}</h6>
                        <span class="item-badge ${isProduct ? 'product-badge' : 'service-badge'}">
                            ${item.item_type}
                        </span>
                    </div>

                    <p class="product-sku text-muted">
                        ${item.code || item.sku || 'No code'}
                    </p>

                    <div class="product-price">
                        <span class="price-current">${formatCurrency(item.selling_price || item.unit_price || item.final_price)}</span>
                        ${item.original_price && item.original_price > (item.selling_price || item.unit_price) ? `
                            <span class="price-original">${formatCurrency(item.original_price)}</span>
                        ` : ''}
                    </div>

                    ${isProduct && item.stock ? `
                        <div class="product-stock">
                            <span class="stock-indicator ${outOfStock ? 'out-of-stock' : lowStock ? 'low-stock' : 'in-stock'}"></span>
                            <span>Stock: ${item.stock.available || item.quantity || 0} ${item.stock.unit || item.unit_of_measure || 'units'}</span>
                        </div>
                        ${lowStock && !outOfStock ? `
                            <div class="stock-warning">
                                <i class="bi bi-exclamation-triangle"></i> Low stock
                            </div>
                        ` : ''}
                    ` : ''}

                    ${!isProduct ? `
                        <div class="product-stock">
                            <span class="stock-indicator in-stock"></span>
                            <span>Service available</span>
                        </div>
                    ` : ''}
                </div>

                <div class="product-actions">
                    <button type="button" class="btn-add-to-cart"
                            onclick='addToCart(${JSON.stringify(item).replace(/'/g, "&#39;")})'
                            ${outOfStock ? 'disabled' : ''}
                            title="${outOfStock ? 'Out of stock' : 'Add to cart'}">
                        <i class="bi bi-cart-plus"></i>
                        ${outOfStock ? 'Out of Stock' : 'Add to Cart'}
                    </button>
                </div>
            </div>
        `;
    }).join('');

    const pagination = document.getElementById('productsPagination');
    if (pagination) {
        pagination.style.display = SaleState.totalItems > SaleState.itemsPerPage ? 'flex' : 'none';
    }
}

function showProductsLoading() {
    const productsGrid = document.getElementById('productsGrid');
    const productsEmpty = document.getElementById('productsEmpty');
    const productsPagination = document.getElementById('productsPagination');
    const productsLoading = document.getElementById('productsLoading');

    if (productsGrid) productsGrid.style.display = 'none';
    if (productsEmpty) productsEmpty.style.display = 'none';
    if (productsPagination) productsPagination.style.display = 'none';
    if (productsLoading) productsLoading.style.display = 'block';
}

function hideProductsLoading() {
    const productsGrid = document.getElementById('productsGrid');
    const productsLoading = document.getElementById('productsLoading');

    if (productsLoading) productsLoading.style.display = 'none';
    if (productsGrid) {
        productsGrid.style.display = 'grid';
    }
}

function showProductsEmpty() {
    const productsLoading = document.getElementById('productsLoading');
    const productsGrid = document.getElementById('productsGrid');
    const productsPagination = document.getElementById('productsPagination');
    const productsEmpty = document.getElementById('productsEmpty');

    if (productsLoading) productsLoading.style.display = 'none';
    if (productsGrid) productsGrid.style.display = 'none';
    if (productsPagination) productsPagination.style.display = 'none';
    if (productsEmpty) productsEmpty.style.display = 'block';
}

window.switchItemType = function(type) {
    SaleState.currentItemType = type;
    SaleState.currentPage = 1;

    document.querySelectorAll('[data-type]').forEach(btn => {
        const isActive = btn.dataset.type === type;
        btn.classList.toggle('active', isActive);
        btn.classList.toggle('btn-primary', isActive);
        btn.classList.toggle('btn-outline-primary', !isActive);
    });

    loadItems();
};

window.clearProductSearch = function() {
    const productSearchBar = document.getElementById('productSearchBar');
    if (productSearchBar) {
        productSearchBar.value = '';
        SaleState.currentPage = 1;
        loadItems();
    }
};

console.log('✅ Sale Page Module Loaded - Part 2/3');
// ============================================
// SALE PAGE - PART 3: Cart Management & Sale Completion
// ============================================

// ============================================
// CART MANAGEMENT
// ============================================

window.addToCart = function(item) {
    const existingIndex = SaleState.cart.findIndex(cartItem =>
        (item.item_type === 'PRODUCT' && cartItem.product_id === item.id) ||
        (item.item_type === 'SERVICE' && cartItem.service_id === item.id)
    );

    if (existingIndex >= 0) {
        updateCartItemQuantity(existingIndex, SaleState.cart[existingIndex].quantity + 1);
        showToast(`Updated quantity for ${item.name}`, 'success');
    } else {
        const cartItem = {
            item_type: item.item_type,
            product_id: item.item_type === 'PRODUCT' ? item.id : null,
            service_id: item.item_type === 'SERVICE' ? item.id : null,
            name: item.name,
            code: item.code,
            quantity: 1,
            unit_price: item.final_price || item.selling_price || item.unit_price,
            original_price: item.final_price || item.selling_price || item.unit_price,
            tax_rate: parseFloat(item.tax_rate) || 18,
            tax_code: item.tax_code || 'A',
            discount_percentage: item.discount_percentage || 0,
            discount_amount: 0,
            unit: item.unit_of_measure || 'pcs',
            stock_available: item.stock?.available || null,
            stock_unit: item.stock?.unit || null,
            price_override_reason: ''
        };

        SaleState.cart.push(cartItem);
        showToast(`Added ${item.name} to cart`, 'success');
    }

    updateCartDisplay();
};

window.updateCartItemQuantity = function(index, newQuantity) {
    const item = SaleState.cart[index];

    if (newQuantity < 1) {
        removeFromCart(index);
        return;
    }

    if (item.item_type === 'PRODUCT' && item.stock_available !== null) {
        if (newQuantity > item.stock_available) {
            showError(`Only ${item.stock_available} ${item.stock_unit} available in stock`);
            return;
        }
    }

    item.quantity = newQuantity;
    updateCartDisplay();
};

window.updateItemPrice = function(index, newPrice) {
    const item = SaleState.cart[index];

    if (!item) {
        showError('Item not found');
        return;
    }

    if (isNaN(newPrice) || newPrice < 0) {
        showError('Please enter a valid price');
        updateCartDisplay();
        return;
    }

    const priceDifference = Math.abs(newPrice - item.original_price);
    const percentChange = (priceDifference / item.original_price) * 100;

    if (percentChange > 20) {
        const direction = newPrice > item.original_price ? 'increased' : 'decreased';
        if (!confirm(
            `Price ${direction} by ${percentChange.toFixed(1)}%\n\n` +
            `Original: ${formatCurrency(item.original_price)}\n` +
            `New: ${formatCurrency(newPrice)}\n\n` +
            `Continue with this price?`
        )) {
            updateCartDisplay();
            return;
        }
    }

    item.unit_price = newPrice;
    console.log(`Price changed for ${item.name}: ${item.original_price} → ${newPrice}`);

    if (newPrice !== item.original_price) {
        const change = newPrice > item.original_price ? 'increased' : 'decreased';
        showToast(`Price ${change} for ${item.name}`, 'info');
    }

    updateCartDisplay();
};

window.resetItemPrice = function(index) {
    const item = SaleState.cart[index];

    if (!item) {
        showError('Item not found');
        return;
    }

    item.unit_price = item.original_price;
    showToast(`Price reset to original for ${item.name}`, 'info');
    updateCartDisplay();
};

window.removeFromCart = function(index) {
    const item = SaleState.cart[index];
    SaleState.cart.splice(index, 1);
    showToast(`Removed ${item.name} from cart`, 'warning');
    updateCartDisplay();
};

window.clearCart = function() {
    if (SaleState.cart.length === 0) return;

    if (confirm('Are you sure you want to clear the cart?')) {
        SaleState.cart = [];
        SaleState.discount = { type: 'percentage', value: 0 };
        updateCartDisplay();
        showToast('Cart cleared', 'warning');
    }
};

window.updateCartDisplay = function() {
    const cartItems = document.getElementById('cartItems');
    const cartCount = document.getElementById('cartCount');
    const cartSummary = document.getElementById('cartSummary');
    const discountSection = document.getElementById('discountSection');
    const clearCartBtn = document.getElementById('clearCartBtn');
    const completeSaleBtn = document.getElementById('completeSaleBtn');

    if (!cartItems || !cartCount) return;

    cartCount.textContent = SaleState.cart.length;

    if (SaleState.cart.length === 0) {
        cartItems.innerHTML = `
            <div class="cart-empty">
                <i class="bi bi-cart-x" style="font-size: 2rem;"></i>
                <p class="mt-2">Cart is empty</p>
                <p class="small text-muted">Add products or services from the left</p>
            </div>
        `;
        if (cartSummary) cartSummary.style.display = 'none';
        if (discountSection) discountSection.style.display = 'none';
        if (clearCartBtn) clearCartBtn.disabled = true;
        if (completeSaleBtn) completeSaleBtn.disabled = true;
        updateQuickStats();
        return;
    }

    if (clearCartBtn) clearCartBtn.disabled = false;

    cartItems.innerHTML = SaleState.cart.map((item, index) => {
        const itemTotal = calculateItemTotal(item);
        const isProduct = item.item_type === 'PRODUCT';
        const priceChanged = item.unit_price !== item.original_price;

        return `
            <div class="cart-item">
                <div class="cart-item-image">
                    <i class="bi ${isProduct ? 'bi-box' : 'bi-gear'}"></i>
                </div>

                <div class="cart-item-details">
                    <div class="cart-item-name">
                        <span>${escapeHtml(item.name)}</span>
                        <span class="cart-item-price">${formatCurrency(itemTotal.total)}</span>
                    </div>

                    <div class="cart-item-meta">
                        ${item.code ? `<span class="me-2">${item.code}</span>` : ''}
                        <span>${item.unit}</span>
                        ${isProduct && item.stock_available ? `
                            <span class="ms-2">Stock: ${item.stock_available}</span>
                        ` : ''}
                    </div>

                    <div class="mt-2">
                        <label class="form-label" style="font-size: 0.75rem;">Price per unit:</label>
                        <div class="input-group input-group-sm">
                            <input type="number"
                                   class="form-control"
                                   value="${item.unit_price}"
                                   min="0"
                                   step="0.01"
                                   onchange="updateItemPrice(${index}, parseFloat(this.value))"
                                   style="max-width: 120px;">
                            ${priceChanged ? `
                                <button class="btn btn-outline-secondary"
                                        type="button"
                                        onclick="resetItemPrice(${index})"
                                        title="Reset to original price">
                                    <i class="bi bi-arrow-counterclockwise"></i>
                                </button>
                            ` : ''}
                        </div>
                        ${priceChanged ? `
                            <small class="text-muted">
                                Original: ${formatCurrency(item.original_price)}
                                ${item.unit_price > item.original_price ?
                                    `<span class="text-success">(+${formatCurrency(item.unit_price - item.original_price)})</span>` :
                                    `<span class="text-warning">(-${formatCurrency(item.original_price - item.unit_price)})</span>`
                                }
                            </small>
                        ` : ''}
                    </div>

                    <div class="cart-item-controls">
                        <div class="qty-control">
                            <button class="qty-btn" type="button" onclick="updateCartItemQuantity(${index}, ${item.quantity - 1})">-</button>
                            <input type="number" class="qty-input"
                                   value="${item.quantity}"
                                   min="1"
                                   max="${item.stock_available || 9999}"
                                   onchange="updateCartItemQuantity(${index}, parseInt(this.value) || 1)">
                            <button class="qty-btn" type="button" onclick="updateCartItemQuantity(${index}, ${item.quantity + 1})">+</button>
                        </div>
                    </div>
                </div>

                <div class="cart-item-actions">
                    <button type="button" class="btn-remove-item"
                            onclick="removeFromCart(${index})"
                            title="Remove item">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            </div>
        `;
    }).join('');

    if (cartSummary) cartSummary.style.display = 'block';
    if (discountSection) discountSection.style.display = 'block';
    if (completeSaleBtn) completeSaleBtn.disabled = false;

    updateSummary();
    updateQuickStats();
};

function calculateItemTotal(item) {
    const subtotal = item.unit_price * item.quantity;
    const discountAmount = item.discount_amount || 0;
    const priceAfterDiscount = subtotal - discountAmount;

    let tax = 0;
    let taxableAmount = priceAfterDiscount;

    if (item.tax_rate > 0) {
        const taxMultiplier = item.tax_rate / 100;
        tax = (priceAfterDiscount / (1 + taxMultiplier)) * taxMultiplier;
        taxableAmount = priceAfterDiscount - tax;
    }

    const total = priceAfterDiscount;

    return {
        subtotal: subtotal,
        discount: discountAmount,
        taxableAmount: taxableAmount,
        tax: tax,
        total: total
    };
}

function updateSummary() {
    let subtotal = 0;
    let totalTax = 0;
    let totalDiscount = 0;

    SaleState.cart.forEach(item => {
        const itemTotal = calculateItemTotal(item);
        subtotal += itemTotal.subtotal;
        totalTax += itemTotal.tax;
        totalDiscount += itemTotal.discount;
    });

    let globalDiscount = 0;
    if (SaleState.discount.value > 0) {
        if (SaleState.discount.type === 'percentage') {
            globalDiscount = subtotal * (SaleState.discount.value / 100);
        } else {
            globalDiscount = Math.min(SaleState.discount.value, subtotal);
        }

        const discountedSubtotal = subtotal - globalDiscount;
        totalTax = 0;

        SaleState.cart.forEach(item => {
            if (item.tax_rate > 0) {
                const itemProportion = (item.unit_price * item.quantity) / subtotal;
                const itemDiscountedPrice = discountedSubtotal * itemProportion;
                const taxMultiplier = item.tax_rate / 100;
                const itemTax = (itemDiscountedPrice / (1 + taxMultiplier)) * taxMultiplier;
                totalTax += itemTax;
            }
        });

        subtotal = discountedSubtotal;
    }

    totalDiscount += globalDiscount;
    const total = subtotal;

    const summarySubtotal = document.getElementById('summarySubtotal');
    const summaryTax = document.getElementById('summaryTax');
    const summaryDiscount = document.getElementById('summaryDiscount');
    const summaryTotal = document.getElementById('summaryTotal');

    if (summarySubtotal) summarySubtotal.textContent = formatCurrency(subtotal);
    if (summaryTax) summaryTax.textContent = formatCurrency(totalTax);
    if (summaryDiscount) summaryDiscount.textContent = formatCurrency(totalDiscount);
    if (summaryTotal) summaryTotal.textContent = formatCurrency(total);

    const itemsData = document.getElementById('itemsData');
    const subtotalAmount = document.getElementById('subtotalAmount');
    const taxAmount = document.getElementById('taxAmount');
    const discountAmount = document.getElementById('discountAmount');
    const totalAmount = document.getElementById('totalAmount');
    const discountTypeField = document.getElementById('discountTypeField');

    if (itemsData) itemsData.value = JSON.stringify(SaleState.cart);
    if (subtotalAmount) subtotalAmount.value = subtotal.toFixed(2);
    if (taxAmount) taxAmount.value = totalTax.toFixed(2);
    if (discountAmount) discountAmount.value = totalDiscount.toFixed(2);
    if (totalAmount) totalAmount.value = total.toFixed(2);
    if (discountTypeField) discountTypeField.value = SaleState.discount.type;

    validatePaymentMethod();
}

function updateQuickStats() {
    const statsItems = document.getElementById('statsItems');
    const statsAvgPrice = document.getElementById('statsAvgPrice');

    if (!statsItems || !statsAvgPrice) return;

    if (SaleState.cart.length === 0) {
        statsItems.textContent = '0';
        statsAvgPrice.textContent = '0 UGX';
        return;
    }

    const totalItems = SaleState.cart.reduce((sum, item) => sum + item.quantity, 0);
    const avgPrice = SaleState.cart.length > 0 ?
        SaleState.cart.reduce((sum, item) => sum + item.unit_price, 0) / SaleState.cart.length : 0;

    statsItems.textContent = totalItems;
    statsAvgPrice.textContent = formatCurrency(avgPrice);
}

window.applyDiscount = function() {
    const discountType = document.getElementById('discountType')?.value;
    const discountValue = parseFloat(document.getElementById('discountValue')?.value) || 0;

    if (discountValue <= 0) {
        showError('Please enter a valid discount value');
        return;
    }

    SaleState.discount = {
        type: discountType,
        value: discountValue
    };

    updateSummary();
    showToast(`Applied ${discountValue}${discountType === 'percentage' ? '%' : ' UGX'} discount`, 'success');
};

// ============================================
// PAYMENT METHOD VALIDATION
// ============================================

window.validatePaymentMethod = function() {
    const paymentMethodSelect = document.getElementById('paymentMethod');
    const creditStatusDiv = document.getElementById('creditPaymentStatus');
    const creditLimitWarning = document.getElementById('creditLimitWarning');
    const creditLimitWarningText = document.getElementById('creditLimitWarningText');
    const completeSaleBtn = document.getElementById('completeSaleBtn');

    if (!paymentMethodSelect) return true;

    const paymentMethod = paymentMethodSelect.value;

    if (creditLimitWarning) creditLimitWarning.style.display = 'none';
    if (creditStatusDiv) creditStatusDiv.style.display = 'none';

    if (paymentMethod === 'CREDIT') {
        const customerId = document.getElementById('customerId')?.value;

        if (!customerId) {
            if (creditLimitWarning) {
                creditLimitWarning.style.display = 'block';
                if (creditLimitWarningText) {
                    creditLimitWarningText.textContent = 'Please select a customer for credit sales';
                }
            }
            if (completeSaleBtn) completeSaleBtn.disabled = true;
            updateCreditAdjustmentVisibility();
            return false;
        }

        if (!currentCustomerCredit.allowCredit) {
            if (creditLimitWarning) {
                creditLimitWarning.style.display = 'block';
                if (creditLimitWarningText) {
                    creditLimitWarningText.textContent = 'This customer is not authorized for credit purchases';
                }
            }
            if (completeSaleBtn) completeSaleBtn.disabled = true;
            updateCreditAdjustmentVisibility();
            return false;
        }

        if (currentCustomerCredit.creditStatus === 'SUSPENDED' ||
            currentCustomerCredit.creditStatus === 'BLOCKED') {
            if (creditLimitWarning) {
                creditLimitWarning.style.display = 'block';
                if (creditLimitWarningText) {
                    creditLimitWarningText.textContent = `Credit ${currentCustomerCredit.creditStatus}: Customer cannot make credit purchases`;
                }
            }
            if (completeSaleBtn) completeSaleBtn.disabled = true;
            return false;
        }

        if (currentCustomerCredit.hasOverdue) {
            if (creditLimitWarning) {
                creditLimitWarning.style.display = 'block';
                if (creditLimitWarningText) {
                    creditLimitWarningText.textContent = 'Customer has overdue invoices. Credit purchases not allowed.';
                }
            }
            if (completeSaleBtn) completeSaleBtn.disabled = true;
            return false;
        }

        const cartTotal = getCartTotal();
        if (cartTotal > currentCustomerCredit.creditAvailable) {
            if (creditLimitWarning) {
                creditLimitWarning.style.display = 'block';
                if (creditLimitWarningText) {
                    creditLimitWarningText.innerHTML = `
                        <strong>Credit Limit Exceeded!</strong><br>
                        Sale Total: ${formatCurrency(cartTotal)}<br>
                        Available Credit: ${formatCurrency(currentCustomerCredit.creditAvailable)}
                    `;
                }
            }
            if (completeSaleBtn) completeSaleBtn.disabled = true;
            return false;
        }

        if (creditStatusDiv) {
            creditStatusDiv.style.display = 'block';
        }
        if (completeSaleBtn) {
            completeSaleBtn.disabled = false;
        }
        return true;
    }

    if (completeSaleBtn) {
        const cartCount = parseInt(document.getElementById('cartCount')?.textContent || '0');
        completeSaleBtn.disabled = cartCount === 0;
    }
    return true;
};

function updateCreditAdjustmentVisibility() {
    const creditAdjustSection = document.getElementById('creditAdjustmentSection');
    const customerId = document.getElementById('customerId')?.value;
    const customerName = SaleState.selectedCustomer?.name;

    if (creditAdjustSection) {
        const shouldShow = customerId && customerName;

        if (shouldShow) {
            creditAdjustSection.style.display = 'block';
        } else {
            creditAdjustSection.style.display = 'none';
        }
    }
}

function getCartTotal() {
    const totalElement = document.getElementById('summaryTotal');
    if (!totalElement) return 0;

    const totalText = totalElement.textContent;
    const total = parseFloat(totalText.replace(/[^0-9.-]+/g, ''));
    return isNaN(total) ? 0 : total;
}

// ============================================
// DOCUMENT TYPE & DUE DATE
// ============================================

window.toggleDueDateSection = function() {
    const dueDateSection = document.getElementById('dueDateSection');
    const efrisRequirements = document.getElementById('efrisRequirements');
    const docTypeRadio = document.querySelector('input[name="document_type"]:checked');

    if (!docTypeRadio) return;

    const docType = docTypeRadio.value;
    const dueDateField = document.getElementById('dueDate');

    if (docType === 'INVOICE') {
        if (dueDateSection) dueDateSection.style.display = 'block';

        if (dueDateField) {
            const today = new Date();
            const dueDate = new Date(today);
            dueDate.setDate(dueDate.getDate() + 30);
            dueDateField.value = dueDate.toISOString().split('T')[0];
            dueDateField.required = true;
        }

        if (!SaleState.selectedCustomer) {
            showCustomerRequiredWarning();
        }

    } else if (docType === 'RECEIPT') {
        if (dueDateSection) dueDateSection.style.display = 'none';
        if (dueDateField) {
            dueDateField.value = '';
            dueDateField.required = false;
        }

        const warning = document.querySelector('.customer-required-warning');
        if (warning) {
            warning.remove();
        }
    }

    validateDocumentRequirements();
};

window.validateDocumentRequirements = function() {
    const docTypeRadio = document.querySelector('input[name="document_type"]:checked');
    if (!docTypeRadio) return;

    const docType = docTypeRadio.value;
    const customerRequired = docType !== 'RECEIPT';

    if (customerRequired && !SaleState.selectedCustomer) {
        showCustomerRequiredWarning();
    }

    if (docType === 'INVOICE' && !SaleState.selectedCustomer) {
        if (!document.querySelector('.customer-required-warning')) {
            const warning = document.createElement('div');
            warning.className = 'alert alert-warning customer-required-warning mt-2';
            warning.innerHTML = `
                <i class="bi bi-exclamation-triangle me-2"></i>
                <strong>Customer required for invoices:</strong>
                Invoices cannot be issued to "Walk-in Customer". Please select or create a customer.
            `;

            const customerSection = document.querySelector('.customer-section');
            if (customerSection && !customerSection.nextElementSibling?.classList.contains('customer-required-warning')) {
                customerSection.parentNode.insertBefore(warning, customerSection.nextSibling);
            }
        }

        const completeSaleBtn = document.getElementById('completeSaleBtn');
        if (completeSaleBtn) {
            completeSaleBtn.disabled = true;
            completeSaleBtn.title = 'Select a customer to proceed with invoice';
        }
    } else {
        const warning = document.querySelector('.customer-required-warning');
        if (warning) {
            warning.remove();
        }

        const completeSaleBtn = document.getElementById('completeSaleBtn');
        if (completeSaleBtn) {
            completeSaleBtn.disabled = SaleState.cart.length === 0;
            completeSaleBtn.title = '';
        }
    }
};

function showCustomerRequiredWarning() {
    if (!document.querySelector('.customer-required-general')) {
        const warning = document.createElement('div');
        warning.className = 'alert alert-info customer-required-general mt-2';
        warning.innerHTML = `
            <i class="bi bi-info-circle me-2"></i>
            <strong>Customer selection recommended:</strong>
            For better record keeping, please select or create a customer.
        `;

        const customerSection = document.querySelector('.customer-section');
        if (customerSection) {
            customerSection.parentNode.insertBefore(warning, customerSection.nextSibling);
        }
    }
}

console.log('✅ Sale Page Module Loaded - Part 3/3 - Complete!');
// ============================================
// SALE PAGE - FINAL: Sale Completion & Utilities
// ============================================

// ============================================
// COMPLETE SALE FUNCTION
// ============================================

window.completeSale = async function() {
    showLoading(true);

    try {
        // Validation
        if (SaleState.cart.length === 0) {
            throw new Error('Please add items to cart');
        }

        const storeSelect = document.getElementById('storeSelect');
        if (!storeSelect || !storeSelect.value) {
            throw new Error('Please select a store');
        }

        const docTypeRadio = document.querySelector('input[name="document_type"]:checked');
        if (!docTypeRadio) {
            throw new Error('Please select document type');
        }

        const docType = docTypeRadio.value;
        const dueDateField = document.getElementById('dueDate');

        if (docType === 'INVOICE') {
            if (!SaleState.selectedCustomer) {
                throw new Error('Customer is required for invoices. Please select or create a customer.');
            }

            if (!dueDateField || !dueDateField.value) {
                throw new Error('Due date is required for invoices');
            }
        }

        const paymentMethod = document.getElementById('paymentMethod')?.value;

        // Stock validation
        const stockErrors = [];
        for (const item of SaleState.cart) {
            if (item.item_type === 'PRODUCT' && item.stock_available !== null) {
                if (item.quantity > item.stock_available) {
                    stockErrors.push(`${item.name}: Only ${item.stock_available} available`);
                }
            }
        }

        if (stockErrors.length > 0) {
            showError(`Stock issues:\n${stockErrors.join('\n')}`);
            showLoading(false);
            return;
        }

        // Payment method validation
        if (paymentMethod === 'CREDIT') {
            if (!validatePaymentMethod()) {
                showError('Cannot complete credit sale. Please check credit limit and customer status.');
                showLoading(false);
                return;
            }

            const cartTotal = getCartTotal();
            const remainingCredit = currentCustomerCredit.creditAvailable - cartTotal;

            if (!confirm(`Confirm Credit Sale\n\n` +
                         `Amount: ${formatCurrency(cartTotal)}\n` +
                         `Current Balance: ${formatCurrency(currentCustomerCredit.creditBalance)}\n` +
                         `New Balance: ${formatCurrency(currentCustomerCredit.creditBalance + cartTotal)}\n` +
                         `Remaining Credit: ${formatCurrency(remainingCredit)}\n\n` +
                         `Proceed with credit sale?`)) {
                showLoading(false);
                return;
            }
        }

        // Prepare sale data
        const totalAmount = parseFloat(document.getElementById('totalAmount')?.value || 0);

        const saleData = {
            store_id: parseInt(storeSelect.value),
            customer_id: SaleState.selectedCustomer?.id || null,
            document_type: docType,
            payment_method: paymentMethod || 'CASH',
            currency: 'UGX',
            due_date: dueDateField?.value || null,
            subtotal: parseFloat(document.getElementById('subtotalAmount')?.value || 0),
            tax_amount: parseFloat(document.getElementById('taxAmount')?.value || 0),
            discount_amount: parseFloat(document.getElementById('discountAmount')?.value || 0),
            total_amount: totalAmount,
            status: docType === 'INVOICE' && paymentMethod === 'CREDIT' ? 'PENDING_PAYMENT' : 'COMPLETED',
            payment_status: paymentMethod === 'CREDIT' ? 'PENDING_PAYMENT' : 'PAID',
            transaction_type: 'SALE',
            notes: document.getElementById('saleNoteText')?.value || '',
        };

        // Add customer notes
        const noteIsImportant = document.getElementById('noteIsImportant')?.checked;
        const noteCategory = document.getElementById('noteCategory')?.value;

        if (saleData.notes) {
            saleData.note_is_important = noteIsImportant || false;
            saleData.note_category = noteCategory || 'GENERAL';
        }

        // Prepare sale items
        const saleItems = SaleState.cart.map(item => {
            const itemSubtotal = item.unit_price * item.quantity;
            const itemDiscount = item.discount_amount || 0;
            const priceAfterDiscount = itemSubtotal - itemDiscount;

            let tax = 0;
            let taxableAmount = priceAfterDiscount;

            if (item.tax_rate > 0) {
                const taxMultiplier = item.tax_rate / 100;
                tax = (priceAfterDiscount / (1 + taxMultiplier)) * taxMultiplier;
                taxableAmount = priceAfterDiscount - tax;
            }

            return {
                product_id: item.product_id || null,
                service_id: item.service_id || null,
                item_type: item.item_type || 'PRODUCT',
                quantity: item.quantity,
                unit_price: item.unit_price,
                total_price: priceAfterDiscount,
                tax_rate: item.tax_code || 'A',
                tax_amount: tax,
                discount: item.discount_percentage || 0,
                discount_amount: itemDiscount,
                description: item.name || '',
                unit_of_measure: item.unit || 'pcs'
            };
        });

        console.log('💰 Creating sale:', {
            documentType: docType,
            paymentMethod: paymentMethod,
            itemCount: saleItems.length,
            totalAmount: totalAmount,
            customer: SaleState.selectedCustomer?.name || 'Walk-in',
            offline: !offlineSaleManager.isOnline
        });

        // Create sale (offline-capable)
        const result = await offlineSaleManager.createSale(saleData, saleItems);

        if (result.success) {
            console.log('✅ Sale created successfully:', result.sale.id);

            // Clear cart
            SaleState.cart = [];
            SaleState.selectedCustomer = null;
            SaleState.discount = { type: 'percentage', value: 0 };

            // Reset form
            const discountValue = document.getElementById('discountValue');
            if (discountValue) discountValue.value = '';

            const noteText = document.getElementById('saleNoteText');
            if (noteText) noteText.value = '';

            const noteImportant = document.getElementById('noteIsImportant');
            if (noteImportant) noteImportant.checked = false;

            // Update UI
            updateCartDisplay();

            const notesSection = document.getElementById('customerNotesSection');
            if (notesSection) notesSection.style.display = 'none';

            // Success notification
            const message = result.offline ?
                '💾 Sale saved offline! Will sync when connection is restored.' :
                '✅ Sale completed successfully!';

            const toastType = result.offline ? 'warning' : 'success';
            showToast(message, toastType);

            if (result.offline) {
                showToast(`📱 Sale ID: ${result.sale.id}\nQueued for sync with priority 1`, 'info');
                setTimeout(() => offlineSaleManager.updateSyncManagementPanel(), 500);
            }

            if (keyboardNavigation.announce) {
                keyboardNavigation.announce(
                    `Sale completed. ${saleItems.length} items. Total ${formatCurrency(totalAmount)}`
                );
            }

            // Redirect to receipt
            if (result.sale.id && !result.offline) {
                setTimeout(() => {
                    const receiptUrl = `/sales/receipt/${result.sale.id}/`;
                    window.location.href = receiptUrl;
                }, 1500);
            } else if (result.offline) {
                showLoading(false);

                const viewOfflineReceipt = confirm(
                    'Sale saved offline successfully!\n\n' +
                    'Would you like to view a draft receipt?\n' +
                    '(Final receipt will be available after sync)'
                );

                if (viewOfflineReceipt) {
                    printOfflineDraftReceipt(result.sale, saleItems);
                }
            }

        } else {
            throw new Error(result.error || 'Failed to create sale');
        }

    } catch (error) {
        console.error('❌ Sale creation failed:', error);
        showLoading(false);

        let errorMessage = error.message;

        if (error.message.includes('Failed to fetch') || error.message.includes('NetworkError')) {
            errorMessage = 'Network error. Sale will be saved offline and synced later.';

            try {
                const saleData = {
                    store_id: parseInt(document.getElementById('storeSelect').value),
                    customer_id: SaleState.selectedCustomer?.id || null,
                    document_type: document.querySelector('input[name="document_type"]:checked')?.value,
                    payment_method: document.getElementById('paymentMethod')?.value || 'CASH',
                    currency: 'UGX',
                    total_amount: parseFloat(document.getElementById('totalAmount')?.value || 0),
                    status: 'COMPLETED',
                    payment_status: 'PAID',
                    transaction_type: 'SALE',
                    notes: document.getElementById('saleNoteText')?.value || '',
                };

                const saleItems = SaleState.cart.map(item => ({
                    product_id: item.product_id || null,
                    service_id: item.service_id || null,
                    item_type: item.item_type || 'PRODUCT',
                    quantity: item.quantity,
                    unit_price: item.unit_price,
                    total_price: item.unit_price * item.quantity,
                    description: item.name || ''
                }));

                const offlineResult = await offlineSaleManager.createSaleOffline(saleData, saleItems);

                if (offlineResult.success) {
                    showToast('Sale saved offline successfully! Will sync when online.', 'success');
                    SaleState.cart = [];
                    SaleState.selectedCustomer = null;
                    updateCartDisplay();
                    return;
                }
            } catch (offlineError) {
                console.error('Offline save also failed:', offlineError);
                errorMessage = 'Failed to save sale both online and offline. Please try again.';
            }
        }

        showError(errorMessage);
        showToast('Please review the error and try again', 'warning');
    }
};

// ============================================
// DRAFTS MANAGEMENT
// ============================================

window.checkForDrafts = function() {
    try {
        const drafts = JSON.parse(localStorage.getItem('sale_drafts') || '[]');
        if (drafts.length > 0) {
            SaleState.drafts = drafts;
            updateDraftsBadge();
        }
    } catch (error) {
        console.error('Error loading drafts:', error);
        localStorage.removeItem('sale_drafts');
        SaleState.drafts = [];
    }
};

function updateDraftsBadge() {
    const badge = document.getElementById('draftsBadge');
    if (badge) {
        badge.textContent = SaleState.drafts.length;
        badge.style.display = SaleState.drafts.length > 0 ? 'inline-block' : 'none';
    }
}

window.saveAsDraft = function(name = null) {
    if (SaleState.cart.length === 0) {
        showError('Cannot save empty cart as draft');
        return;
    }

    if (!name) {
        const draftName = prompt('Enter a name for this draft:',
            `Draft ${new Date().toLocaleString()}`);

        if (!draftName) {
            return;
        }

        if (draftName.trim() === '') {
            showError('Draft name cannot be empty');
            return;
        }

        name = draftName.trim();
    }

    const draft = {
        id: Date.now(),
        name: name,
        cart: SaleState.cart,
        customer: SaleState.selectedCustomer,
        storeId: document.getElementById('storeSelect')?.value,
        documentType: document.querySelector('input[name="document_type"]:checked')?.value,
        paymentMethod: document.getElementById('paymentMethod')?.value,
        dueDate: document.getElementById('dueDate')?.value,
        discount: SaleState.discount,
        totalAmount: parseFloat(document.getElementById('totalAmount')?.value || 0),
        itemCount: SaleState.cart.reduce((sum, item) => sum + item.quantity, 0),
        createdAt: new Date().toISOString(),
        updatedAt: new Date().toISOString()
    };

    try {
        const drafts = JSON.parse(localStorage.getItem('sale_drafts') || '[]');
        const existingIndex = drafts.findIndex(d => d.id === draft.id);

        if (existingIndex >= 0) {
            drafts[existingIndex] = draft;
            showToast(`Draft "${name}" updated successfully`, 'success');
        } else {
            drafts.push(draft);
            showToast(`Draft "${name}" saved successfully`, 'success');
        }

        drafts.sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));
        localStorage.setItem('sale_drafts', JSON.stringify(drafts));
        SaleState.drafts = drafts;
        updateDraftsBadge();

    } catch (error) {
        console.error('Error saving draft:', error);
        showError('Failed to save draft');
    }
};

window.showDraftsModal = function() {
    const modal = new bootstrap.Modal(document.getElementById('draftsModal'));
    modal.show();
};

// ============================================
// KEYBOARD TUTORIAL
// ============================================

window.closeKeyboardTutorial = function() {
    const tutorial = document.getElementById('keyboardTutorial');
    if (tutorial) {
        tutorial.classList.remove('show');
        localStorage.setItem('keyboardTutorialCompleted', 'true');
    }
};

window.toggleShortcutsHelp = function() {
    const help = document.getElementById('shortcutsHelp');
    if (help) {
        help.classList.toggle('show');
    }
};

// ============================================
// PRINT RECEIPT
// ============================================

window.printReceiptPreview = function() {
    if (SaleState.cart.length === 0) {
        showError('Cannot print empty cart');
        return;
    }

    const printWindow = window.open('', '_blank', 'width=800,height=600');

    if (!printWindow) {
        showError('Please allow popups to print receipt');
        return;
    }

    const storeSelect = document.getElementById('storeSelect');
    const storeName = storeSelect?.options[storeSelect.selectedIndex]?.text || 'Store';

    printWindow.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>Receipt Preview - Draft</title>
            <style>
                body { font-family: Arial, sans-serif; max-width: 80mm; margin: 0 auto; padding: 10mm; }
                .header { text-align: center; margin-bottom: 20px; border-bottom: 2px dashed #000; padding-bottom: 10px; }
                .draft-badge { background: #ff0000; color: white; padding: 5px 10px; font-weight: bold; display: inline-block; margin: 10px 0; }
                .items { margin: 15px 0; }
                .item { margin: 5px 0; display: flex; justify-content: space-between; }
                .total { border-top: 2px dashed #000; margin-top: 10px; padding-top: 10px; font-weight: bold; font-size: 1.2em; }
                @media print { .no-print { display: none; } }
            </style>
        </head>
        <body>
            <div class="header">
                <h2>${escapeHtml(storeName)}</h2>
                <div class="draft-badge">⚠️ DRAFT - NOT OFFICIAL</div>
            </div>
            <div class="items">
                ${SaleState.cart.map(item => `
                    <div class="item">
                        <span>${item.quantity}× ${escapeHtml(item.name)}</span>
                        <span>${formatCurrency(item.unit_price * item.quantity)}</span>
                    </div>
                `).join('')}
            </div>
            <div class="total">
                <div style="display: flex; justify-content: space-between;">
                    <span>TOTAL:</span>
                    <span>${formatCurrency(getCartTotal())} UGX</span>
                </div>
            </div>
            <div style="text-align: center; margin-top: 20px; font-size: 0.9em;">
                <p><strong>⚠️ DRAFT RECEIPT - NOT OFFICIAL</strong></p>
                <p>Complete the sale to generate an official receipt</p>
            </div>
            <div class="no-print" style="text-align: center; margin-top: 20px;">
                <button onclick="window.print()" style="padding: 10px 20px;">🖨️ Print</button>
                <button onclick="window.close()" style="padding: 10px 20px; margin-left: 10px;">✖️ Close</button>
            </div>
        </body>
        </html>
    `);

    printWindow.document.close();
};

function printOfflineDraftReceipt(sale, saleItems) {
    // Placeholder - implement full offline receipt
    console.log('Printing offline draft receipt:', sale.id);
    printReceiptPreview();
}

// ============================================
// CACHE CLEANUP
// ============================================

setInterval(() => {
    const now = Date.now();
    const maxAge = 5 * 60 * 1000; // 5 minutes

    for (const [key, value] of SaleState.searchCache.entries()) {
        if (now - value.timestamp > maxAge) {
            SaleState.searchCache.delete(key);
        }
    }
}, 60000); // Run every minute

// ============================================
// PAGINATION
// ============================================

function updatePaginationInfo() {
    const paginationInfo = document.getElementById('paginationInfo');
    if (!paginationInfo) return;

    const start = ((SaleState.currentPage - 1) * SaleState.itemsPerPage) + 1;
    const end = Math.min(SaleState.currentPage * SaleState.itemsPerPage, SaleState.totalItems);
    paginationInfo.textContent = `Showing ${start}-${end} of ${SaleState.totalItems} items`;
}

window.loadNextPage = function() {
    const totalPages = Math.ceil(SaleState.totalItems / SaleState.itemsPerPage);
    if (SaleState.currentPage < totalPages) {
        SaleState.currentPage++;
        loadItems();
    }
};

window.loadPreviousPage = function() {
    if (SaleState.currentPage > 1) {
        SaleState.currentPage--;
        loadItems();
    }
};

console.log('✅ Sale Page Complete - ALL MODULES LOADED');
console.log('🎉 Ready to process sales!');