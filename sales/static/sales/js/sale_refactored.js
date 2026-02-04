/**
 * ============================================
 * SALES PAGE - FIXED JAVASCRIPT
 * ============================================
 * FIXES:
 * 1. EFRIS customer creation now works properly
 * 2. Page no longer grays out after EFRIS query
 * 3. "Use This" properly saves customer to DB
 * 4. Customer persists through sale completion
 * 5. Removed unnecessary browser popups
 * 6. Better error handling
 * ============================================
 */

(function() {
    'use strict';

    // ============================================
    // CONSTANTS & CONFIGURATION
    // ============================================
    const CONFIG = {
        CACHE_MAX_AGE: 2 * 60 * 1000,
        DEBOUNCE_DELAY: 300,
        ITEMS_PER_PAGE: 20,
        MIN_SEARCH_LENGTH: 2,
        CACHE_CLEANUP_INTERVAL: 60000,
        MIN_SALE_AMOUNT: 1000,
        PRICE_CHANGE_THRESHOLD: 20
    };

    const ENDPOINTS = {
        CUSTOMER_SEARCH: '/sales/customer-search/',
        CUSTOMER_CREATE: '/sales/create_customer_ajax/',
        CUSTOMER_DETAIL: '/en/customers/api/customers/',
        ITEMS_SEARCH: '/sales/search-items/',
        RECENT_CUSTOMERS: '/sales/recent-customers/',
        EFRIS_QUERY: '/en/efris/taxpayer-query/',
        CREDIT_ADJUST: '/en/customers/api/customers/{id}/adjust-credit/'
    };

    // ============================================
    // UTILITY FUNCTIONS MODULE
    // ============================================
    const Utils = {
        getCSRFToken() {
            const cookieValue = document.cookie
                .split('; ')
                .find(row => row.startsWith('csrftoken='))
                ?.split('=')[1];

            if (cookieValue) return cookieValue;

            const metaTag = document.querySelector('meta[name="csrf-token"]');
            if (metaTag) return metaTag.getAttribute('content');

            const hiddenInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
            if (hiddenInput) return hiddenInput.value;

            console.error('CSRF token not found');
            return null;
        },

        escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = String(text);
            return div.innerHTML;
        },

        formatCurrency(amount) {
            return new Intl.NumberFormat('en-UG', {
                style: 'currency',
                currency: 'UGX',
                minimumFractionDigits: 0,
                maximumFractionDigits: 0
            }).format(amount || 0);
        },

        debounce(func, delay = CONFIG.DEBOUNCE_DELAY) {
            let timeout;
            let controller;

            return function executedFunction(...args) {
                if (controller) {
                    controller.abort();
                }

                clearTimeout(timeout);

                timeout = setTimeout(() => {
                    controller = new AbortController();
                    func.call(this, ...args, controller);
                }, delay);
            };
        },

        safeJsonParse(str, fallback = null) {
            try {
                return JSON.parse(str);
            } catch (e) {
                console.error('JSON parse error:', e);
                return fallback;
            }
        },

        toBoolean(value) {
            if (typeof value === 'boolean') return value;
            if (typeof value === 'number') return value === 1;
            if (typeof value === 'string') {
                const lower = value.toLowerCase();
                return lower === 'true' || lower === '1' || lower === 'yes';
            }
            return Boolean(value);
        },

        getElement(id) {
            const element = document.getElementById(id);
            if (!element) {
                console.warn(`Element not found: ${id}`);
            }
            return element;
        },

        toggleElement(element, show) {
            if (!element) return;
            element.style.display = show ? 'block' : 'none';
        },

        isValidEmail(email) {
            return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
        },

        isValidTIN(tin) {
            return /^\d{10}$/.test(tin);
        }
    };

    // ============================================
    // TOAST NOTIFICATION SYSTEM
    // ============================================
    const Toast = {
        container: null,

        init() {
            this.container = Utils.getElement('toast-container') ||
                           document.querySelector('.toast-container');

            if (!this.container) {
                this.container = document.createElement('div');
                this.container.className = 'toast-container';
                document.body.appendChild(this.container);
            }
        },

        show(message, type = 'info') {
            if (!this.container) this.init();

            const icons = {
                success: 'bi-check-circle-fill',
                error: 'bi-exclamation-circle-fill',
                warning: 'bi-exclamation-triangle-fill',
                info: 'bi-info-circle-fill'
            };

            const colors = {
                success: 'text-success',
                error: 'text-danger',
                warning: 'text-warning',
                info: 'text-info'
            };

            const toast = document.createElement('div');
            toast.className = `toast toast-${type}`;
            toast.innerHTML = `
                <i class="bi ${icons[type]} ${colors[type]}"></i>
                <span>${Utils.escapeHtml(message)}</span>
            `;

            this.container.appendChild(toast);

            requestAnimationFrame(() => {
                toast.classList.add('show');
            });

            setTimeout(() => {
                toast.classList.remove('show');
                setTimeout(() => {
                    if (toast.parentNode === this.container) {
                        this.container.removeChild(toast);
                    }
                }, 300);
            }, 5000);
        }
    };

    // ============================================
    // LOADING OVERLAY
    // ============================================
    const Loading = {
        overlay: null,

        init() {
            this.overlay = Utils.getElement('loadingOverlay');
        },

        show() {
            if (this.overlay) {
                this.overlay.style.display = 'flex';
            }
        },

        hide() {
            if (this.overlay) {
                this.overlay.style.display = 'none';
            }
        }
    };

    // ============================================
    // ERROR HANDLER
    // ============================================
    const ErrorHandler = {
        modal: null,
        modalContent: null,

        init() {
            this.modal = Utils.getElement('errorModal');
            this.modalContent = Utils.getElement('errorModalContent');
        },

        show(message, details = null) {
            console.error('Error:', message, details);

            if (this.modal && this.modalContent) {
                this.modalContent.innerHTML = `
                    <div class="alert alert-danger">
                        <i class="bi bi-exclamation-triangle me-2"></i>
                        ${Utils.escapeHtml(message)}
                        ${details ? `<hr><small>${Utils.escapeHtml(details)}</small>` : ''}
                    </div>
                `;

                const bsModal = new bootstrap.Modal(this.modal);
                bsModal.show();
            } else {
                Toast.show(message, 'error');
            }
        },

        handleApiError(error, context = '') {
            let message = error.message || 'An error occurred';

            if (error.message?.includes('Failed to fetch') ||
                error.message?.includes('NetworkError')) {
                message = 'Network error. Please check your connection.';
            } else if (error.message?.includes('CSRF')) {
                message = 'Session expired. Please refresh the page.';
            } else if (error.message?.includes('login')) {
                message = 'Please log in again.';
            }

            this.show(context ? `${context}: ${message}` : message);
        }
    };

    // ============================================
    // CACHE MANAGER
    // ============================================
    class CacheManager {
        constructor(maxSize = 100) {
            this.cache = new Map();
            this.maxSize = maxSize;
        }

        set(key, value) {
            if (this.cache.size >= this.maxSize) {
                const firstKey = this.cache.keys().next().value;
                this.cache.delete(firstKey);
            }

            this.cache.set(key, {
                data: value,
                timestamp: Date.now()
            });
        }

        get(key, maxAge = CONFIG.CACHE_MAX_AGE) {
            const cached = this.cache.get(key);

            if (!cached) return null;

            const age = Date.now() - cached.timestamp;

            if (age > maxAge) {
                this.cache.delete(key);
                return null;
            }

            return cached.data;
        }

        clear() {
            this.cache.clear();
        }

        cleanup(maxAge = CONFIG.CACHE_MAX_AGE) {
            const now = Date.now();

            for (const [key, value] of this.cache.entries()) {
                if (now - value.timestamp > maxAge) {
                    this.cache.delete(key);
                }
            }
        }
    }

    // ============================================
    // STATE MANAGER
    // ============================================
    const State = {
        cart: [],
        items: [],
        currentPage: 1,
        itemsPerPage: CONFIG.ITEMS_PER_PAGE,
        totalItems: 0,
        selectedCustomer: null,
        currentItemType: 'all',
        discount: { type: 'percentage', value: 0 },
        recentCustomers: [],
        drafts: [],
        activeTab: 'searchTab',
        cartModified: false, // Track if cart has been modified

        customerCredit: {
            allowCredit: false,
            creditLimit: 0,
            creditBalance: 0,
            creditAvailable: 0,
            creditStatus: 'NONE',
            hasOverdue: false,
            overdueAmount: 0
        },

        reset() {
            this.cart = [];
            this.selectedCustomer = null;
            this.discount = { type: 'percentage', value: 0 };
            this.cartModified = false;
        },

        setCustomer(customer) {
            this.selectedCustomer = customer;

            if (customer && customer.credit_info) {
                this.customerCredit = {
                    allowCredit: Utils.toBoolean(customer.credit_info.allow_credit),
                    creditLimit: parseFloat(customer.credit_info.credit_limit) || 0,
                    creditBalance: parseFloat(customer.credit_info.credit_balance) || 0,
                    creditAvailable: parseFloat(customer.credit_info.credit_available) || 0,
                    creditStatus: customer.credit_info.credit_status || 'NONE',
                    hasOverdue: Utils.toBoolean(customer.credit_info.has_overdue),
                    overdueAmount: parseFloat(customer.credit_info.overdue_amount) || 0
                };
            } else {
                this.customerCredit = {
                    allowCredit: false,
                    creditLimit: 0,
                    creditBalance: 0,
                    creditAvailable: 0,
                    creditStatus: 'NONE',
                    hasOverdue: false,
                    overdueAmount: 0
                };
            }
        },

        clearCustomer() {
            this.selectedCustomer = null;
            this.customerCredit = {
                allowCredit: false,
                creditLimit: 0,
                creditBalance: 0,
                creditAvailable: 0,
                creditStatus: 'NONE',
                hasOverdue: false,
                overdueAmount: 0
            };
        }
    };

    // ============================================
    // API SERVICE
    // ============================================
    const API = {
        cache: new CacheManager(),

        async request(url, options = {}) {
            const defaultOptions = {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': Utils.getCSRFToken()
                },
                credentials: 'same-origin'
            };

            const mergedOptions = {
                ...defaultOptions,
                ...options,
                headers: {
                    ...defaultOptions.headers,
                    ...options.headers
                }
            };

            if (!(options.body instanceof FormData) && options.method === 'POST') {
                mergedOptions.headers['Content-Type'] = 'application/json';
            }

            const response = await fetch(url, mergedOptions);

            const contentType = response.headers.get('content-type');

            if (!contentType?.includes('application/json')) {
                const text = await response.text();

                if (text.includes('<html') || text.includes('<!DOCTYPE')) {
                    if (text.toLowerCase().includes('login')) {
                        throw new Error('Session expired. Please log in again.');
                    }
                    throw new Error('Server error. Expected JSON but received HTML.');
                }

                throw new Error(`Invalid response type: ${contentType || 'unknown'}`);
            }

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || data.message || `Request failed: ${response.status}`);
            }

            return data;
        },

        async searchCustomers(query, storeId, signal) {
            const cacheKey = `customers-${query}-${storeId}`;
            const cached = this.cache.get(cacheKey);

            if (cached) return cached;

            const url = `${ENDPOINTS.CUSTOMER_SEARCH}?q=${encodeURIComponent(query)}&store_id=${storeId}`;
            const data = await this.request(url, { signal });

            let customers = [];
            if (Array.isArray(data)) {
                customers = data;
            } else if (data.customers && Array.isArray(data.customers)) {
                customers = data.customers;
            } else if (data.results && Array.isArray(data.results)) {
                customers = data.results;
            }

            this.cache.set(cacheKey, customers);
            return customers;
        },

        async getCustomer(customerId) {
            const url = `${ENDPOINTS.CUSTOMER_DETAIL}${customerId}/`;
            const data = await this.request(url);
            return data.customer || data;
        },

        async createCustomer(formData) {
            const data = await this.request(ENDPOINTS.CUSTOMER_CREATE, {
                method: 'POST',
                body: formData
            });

            if (!data.success) {
                throw new Error(data.error || 'Failed to create customer');
            }

            return data.customer;
        },

        async searchItems(params) {
            const queryString = new URLSearchParams(params).toString();
            const cacheKey = `items-${queryString}`;
            const cached = this.cache.get(cacheKey);

            if (cached) return cached;

            const url = `${ENDPOINTS.ITEMS_SEARCH}?${queryString}`;
            const data = await this.request(url);

            this.cache.set(cacheKey, data);
            return data;
        },

        async getRecentCustomers(storeId) {
            const url = `${ENDPOINTS.RECENT_CUSTOMERS}?store_id=${storeId}`;
            const data = await this.request(url);
            return data.customers || [];
        },

        async queryEFRIS(tin) {
            const formData = new FormData();
            formData.append('tin', tin);

            const data = await this.request(ENDPOINTS.EFRIS_QUERY, {
                method: 'POST',
                body: formData
            });

            if (!data.success) {
                throw new Error(data.error || 'Taxpayer not found');
            }

            return data.taxpayer;
        },

        async adjustCredit(customerId, adjustmentData) {
            const url = ENDPOINTS.CREDIT_ADJUST.replace('{id}', customerId);
            const formData = new FormData();

            Object.entries(adjustmentData).forEach(([key, value]) => {
                formData.append(key, value);
            });

            const data = await this.request(url, {
                method: 'POST',
                body: formData
            });

            if (!data.success) {
                throw new Error(data.error || 'Failed to adjust credit');
            }

            return data.customer_credit;
        }
    };

    // ============================================
    // CUSTOMER MODULE - FIXED
    // ============================================
    const CustomerModule = {
        searchController: null,
        searchTimeout: null,

        init() {
            this.attachEventListeners();
        },

        attachEventListeners() {
            const searchInput = Utils.getElement('customerSearch');
            if (searchInput) {
                searchInput.addEventListener('input', Utils.debounce((e) => {
                    this.handleSearch(e.target.value);
                }));

                searchInput.addEventListener('focus', () => {
                    if (searchInput.value.trim().length >= CONFIG.MIN_SEARCH_LENGTH) {
                        this.showDropdown();
                    }
                });
            }

            ['searchTabBtn', 'recentTabBtn', 'efrisTabBtn'].forEach(btnId => {
                const btn = Utils.getElement(btnId);
                if (btn) {
                    btn.addEventListener('click', (e) => {
                        this.handleTabSwitch(btnId.replace('Btn', ''));
                    });
                }
            });

            const newCustomerForm = Utils.getElement('newCustomerForm');
            if (newCustomerForm) {
                newCustomerForm.addEventListener('submit', (e) => {
                    e.preventDefault();
                    this.createCustomer();
                });
            }

            const efrisQueryBtn = Utils.getElement('efrisQueryBtn');
            if (efrisQueryBtn) {
                efrisQueryBtn.addEventListener('click', () => {
                    this.queryEFRIS();
                });
            }

            document.addEventListener('click', (e) => {
                const customerSection = document.querySelector('.customer-section, .pos-customer-card');
                const dropdown = Utils.getElement('customerDropdown');

                if (!customerSection?.contains(e.target) && dropdown) {
                    dropdown.classList.remove('show');
                }
            });
        },

        async handleSearch(query, controller) {
            const searchLoading = Utils.getElement('customerSearchLoading');
            const searchError = Utils.getElement('customerSearchError');
            const dropdown = Utils.getElement('customerDropdown');

            Utils.toggleElement(searchError, false);

            if (query.length < CONFIG.MIN_SEARCH_LENGTH) {
                if (dropdown) dropdown.classList.remove('show');
                return;
            }

            const storeId = Utils.getElement('storeSelect')?.value;
            if (!storeId) {
                if (searchError) {
                    searchError.textContent = 'Please select a branch first';
                    Utils.toggleElement(searchError, true);
                }
                return;
            }

            Utils.toggleElement(searchLoading, true);

            try {
                const customers = await API.searchCustomers(query, storeId, controller?.signal);
                this.displayCustomerList(customers);
            } catch (error) {
                if (error.name !== 'AbortError') {
                    if (searchError) {
                        searchError.textContent = `Search failed: ${error.message}`;
                        Utils.toggleElement(searchError, true);
                    }
                }
            } finally {
                Utils.toggleElement(searchLoading, false);
            }
        },

        displayCustomerList(customers) {
            const list = Utils.getElement('customerList');
            const dropdown = Utils.getElement('customerDropdown');

            if (!list) return;

            if (!customers || customers.length === 0) {
                list.innerHTML = `
                    <div class="text-center py-3">
                        <i class="bi bi-person-x" style="font-size: 2rem; opacity: 0.3;"></i>
                        <p class="mt-2 mb-0">No customers found</p>
                    </div>
                `;
                if (dropdown) dropdown.classList.add('show');
                return;
            }

            list.innerHTML = customers.map(customer => {
                const isSelected = State.selectedCustomer?.id === customer.id;

                return `
                    <div class="customer-list-item ${isSelected ? 'selected' : ''}"
                         data-customer-id="${customer.id}"
                         tabindex="0"
                         role="option">
                        <div class="customer-list-item-avatar">
                            ${customer.name.charAt(0).toUpperCase()}
                        </div>
                        <div class="customer-list-item-info">
                            <div class="customer-list-item-name">${Utils.escapeHtml(customer.name)}</div>
                            <div class="customer-list-item-details">
                                ${customer.phone ? Utils.escapeHtml(customer.phone) : ''}
                                ${customer.email ? ` | ${Utils.escapeHtml(customer.email)}` : ''}
                            </div>
                        </div>
                        ${customer.tin ? `
                            <span class="customer-list-item-badge">
                                TIN: ${Utils.escapeHtml(customer.tin)}
                            </span>
                        ` : ''}
                    </div>
                `;
            }).join('');

            list.querySelectorAll('.customer-list-item').forEach((item, index) => {
                item.addEventListener('click', () => {
                    this.selectCustomer(customers[index]);
                });
            });

            if (dropdown) dropdown.classList.add('show');
        },

        selectCustomer(customer) {
            console.log('✅ Selecting customer:', customer);

            State.setCustomer(customer);
            this.updateCustomerDisplay();
            this.hideDropdown();

            const notesSection = Utils.getElement('customerNotesSection');
            Utils.toggleElement(notesSection, true);

            CreditModule.updateAdjustmentVisibility();
            PaymentModule.validate();

            Toast.show(`Selected: ${customer.name}`, 'success');
        },

        updateCustomerDisplay() {
            const customer = State.selectedCustomer;

            const customerIdField = Utils.getElement('customerId');
            const customerTinField = Utils.getElement('customerTin');

            if (customerIdField) customerIdField.value = customer?.id || '';
            if (customerTinField) customerTinField.value = customer?.tin || '';

            const display = Utils.getElement('customerDisplay');
            const name = Utils.getElement('customerName');
            const details = Utils.getElement('customerDetails');
            const avatar = Utils.getElement('customerAvatar');
            const tinBadge = Utils.getElement('customerTinBadge');

            if (customer) {
                Utils.toggleElement(display, true);

                if (name) name.textContent = customer.name;
                if (avatar) avatar.textContent = customer.name.charAt(0).toUpperCase();

                if (details) {
                    details.innerHTML = `
                        <small class="text-muted">
                            ${customer.phone || ''}
                            ${customer.email ? ' • ' + customer.email : ''}
                            ${customer.tin ? ' • TIN: ' + customer.tin : ''}
                        </small>
                    `;
                }

                if (tinBadge) {
                    if (customer.tin) {
                        tinBadge.textContent = `TIN: ${customer.tin}`;
                        Utils.toggleElement(tinBadge, true);
                    } else {
                        Utils.toggleElement(tinBadge, false);
                    }
                }

                CreditModule.displayInfo();
            } else {
                Utils.toggleElement(display, false);
            }
        },

        clearCustomer() {
            State.clearCustomer();
            this.updateCustomerDisplay();

            const notesSection = Utils.getElement('customerNotesSection');
            Utils.toggleElement(notesSection, false);

            const noteText = Utils.getElement('saleNoteText');
            const noteImportant = Utils.getElement('noteIsImportant');
            const noteCategory = Utils.getElement('noteCategory');

            if (noteText) noteText.value = '';
            if (noteImportant) noteImportant.checked = false;
            if (noteCategory) noteCategory.value = 'GENERAL';

            CreditModule.updateAdjustmentVisibility();
            PaymentModule.validate();

            Toast.show('Customer removed', 'warning');
        },

        showDropdown() {
            const dropdown = Utils.getElement('customerDropdown');
            if (dropdown && dropdown.querySelector('.customer-list-item')) {
                dropdown.classList.add('show');
            }
        },

        hideDropdown() {
            const dropdown = Utils.getElement('customerDropdown');
            if (dropdown) dropdown.classList.remove('show');
        },

        handleTabSwitch(tabName) {
            State.activeTab = tabName;

            if (tabName === 'recentTab') {
                this.loadRecentCustomers();
            }
        },

        async loadRecentCustomers() {
            const loading = Utils.getElement('recentCustomersLoading');
            const list = Utils.getElement('recentCustomersList');

            if (!list) return;

            const storeId = Utils.getElement('storeSelect')?.value;

            if (!storeId) {
                list.innerHTML = `
                    <div class="text-center py-3">
                        <i class="bi bi-shop" style="font-size: 2rem; opacity: 0.3;"></i>
                        <p class="mt-2 mb-0">Please select a branch first</p>
                    </div>
                `;
                return;
            }

            Utils.toggleElement(loading, true);

            try {
                const customers = await API.getRecentCustomers(storeId);
                State.recentCustomers = customers;
                this.displayRecentCustomers(customers);
            } catch (error) {
                list.innerHTML = `
                    <div class="text-center py-3">
                        <i class="bi bi-exclamation-triangle text-danger" style="font-size: 2rem;"></i>
                        <p class="mt-2 mb-0 text-danger">Failed to load recent customers</p>
                    </div>
                `;
                ErrorHandler.handleApiError(error, 'Load recent customers');
            } finally {
                Utils.toggleElement(loading, false);
            }
        },

        displayRecentCustomers(customers) {
            const list = Utils.getElement('recentCustomersList');
            if (!list) return;

            if (!customers || customers.length === 0) {
                list.innerHTML = `
                    <div class="text-center py-3">
                        <i class="bi bi-clock-history" style="font-size: 2rem; opacity: 0.3;"></i>
                        <p class="mt-2 mb-0">No recent customers</p>
                    </div>
                `;
                return;
            }

            list.innerHTML = customers.map(customer => `
                <div class="customer-list-item" data-customer-id="${customer.id}">
                    <div class="customer-list-item-avatar">
                        ${customer.name.charAt(0).toUpperCase()}
                    </div>
                    <div class="customer-list-item-info">
                        <div class="customer-list-item-name">${Utils.escapeHtml(customer.name)}</div>
                        <div class="customer-list-item-details">
                            ${customer.phone || ''}
                            ${customer.last_purchase ? ` | Last: ${new Date(customer.last_purchase).toLocaleDateString()}` : ''}
                        </div>
                    </div>
                </div>
            `).join('');

            list.querySelectorAll('.customer-list-item').forEach((item, index) => {
                item.addEventListener('click', () => {
                    this.selectCustomer(customers[index]);
                });
            });
        },

        async createCustomer() {
            const form = Utils.getElement('newCustomerForm');
            const saveBtn = Utils.getElement('saveCustomerBtn');
            const saveText = Utils.getElement('saveCustomerText');
            const saveLoading = Utils.getElement('saveCustomerLoading');

            if (!form || !form.checkValidity()) {
                form?.reportValidity();
                return;
            }

            const storeId = Utils.getElement('storeSelect')?.value;
            if (!storeId) {
                ErrorHandler.show('Please select a branch first');
                return;
            }

            Utils.toggleElement(saveText, false);
            Utils.toggleElement(saveLoading, true);
            if (saveBtn) saveBtn.disabled = true;

            try {
                const formData = new FormData(form);
                formData.append('store_id', storeId);

                const customer = await API.createCustomer(formData);

                this.selectCustomer(customer);

                const modal = bootstrap.Modal.getInstance(Utils.getElement('newCustomerModal'));
                if (modal) modal.hide();

                form.reset();
                Toast.show('Customer created successfully', 'success');
            } catch (error) {
                ErrorHandler.handleApiError(error, 'Create customer');
            } finally {
                Utils.toggleElement(saveText, true);
                Utils.toggleElement(saveLoading, false);
                if (saveBtn) saveBtn.disabled = false;
            }
        },

        // ============================================
        // FIXED EFRIS METHODS
        // ============================================
        async queryEFRIS() {
            const tinInput = Utils.getElement('taxpayerTIN');
            const queryBtn = Utils.getElement('efrisQueryBtn');
            const queryLoading = Utils.getElement('efrisQueryLoading');
            const results = Utils.getElement('efrisQueryResults');
            const errorDiv = Utils.getElement('efrisError');
            const errorMessage = Utils.getElement('efrisErrorMessage');

            if (!tinInput) return;

            const tin = tinInput.value.trim();

            Utils.toggleElement(errorDiv, false);
            Utils.toggleElement(results, false);

            if (!tin) {
                ErrorHandler.show('Please enter TIN');
                return;
            }

            if (!Utils.isValidTIN(tin)) {
                ErrorHandler.show('Please enter a valid 10-digit TIN');
                return;
            }

            if (queryBtn) queryBtn.disabled = true;
            Utils.toggleElement(queryLoading, true);

            try {
                const taxpayer = await API.queryEFRIS(tin);

                // FIX: Don't show "Taxpayer found" as error
                this.displayEFRISResults(taxpayer);

                // Clear loading state properly
                Utils.toggleElement(queryLoading, false);
                if (queryBtn) queryBtn.disabled = false;

            } catch (error) {
                Utils.toggleElement(queryLoading, false);
                if (queryBtn) queryBtn.disabled = false;

                if (errorDiv && errorMessage) {
                    errorMessage.textContent = error.message;
                    Utils.toggleElement(errorDiv, true);
                }

                // Don't use modal for EFRIS errors, just show in the error div
                Toast.show(error.message, 'error');
            }
        },

        displayEFRISResults(taxpayer) {
            const results = Utils.getElement('efrisQueryResults');
            if (!results) return;

            // Store taxpayer data in a way that preserves it
            const taxpayerData = {
                legal_name: taxpayer.legal_name || taxpayer.name,
                tin: taxpayer.tin,
                taxpayer_type: taxpayer.taxpayer_type,
                address: taxpayer.address || '',
                phone: taxpayer.phone || '',
                email: taxpayer.email || ''
            };

            results.innerHTML = `
                <div class="card mt-3">
                    <div class="card-body">
                        <h6>${Utils.escapeHtml(taxpayerData.legal_name)}</h6>
                        <p class="mb-1"><strong>TIN:</strong> ${Utils.escapeHtml(taxpayerData.tin)}</p>
                        <p class="mb-1"><strong>Type:</strong> ${Utils.escapeHtml(taxpayerData.taxpayer_type)}</p>
                        ${taxpayerData.address ? `<p class="mb-1"><strong>Address:</strong> ${Utils.escapeHtml(taxpayerData.address)}</p>` : ''}
                        ${taxpayerData.phone ? `<p class="mb-1"><strong>Phone:</strong> ${Utils.escapeHtml(taxpayerData.phone)}</p>` : ''}
                        ${taxpayerData.email ? `<p class="mb-3"><strong>Email:</strong> ${Utils.escapeHtml(taxpayerData.email)}</p>` : ''}
                        <div class="d-flex gap-2">
                            <button type="button" class="btn btn-success btn-sm flex-fill"
                                    id="createFromEfrisBtn">
                                <i class="bi bi-person-plus me-1"></i> Create Customer
                            </button>
                            <button type="button" class="btn btn-outline-primary btn-sm flex-fill"
                                    id="useEfrisBtn">
                                <i class="bi bi-check-circle me-1"></i> Use This
                            </button>
                        </div>
                    </div>
                </div>
            `;

            Utils.toggleElement(results, true);

            // Attach event handlers with preserved data
            const createBtn = document.getElementById('createFromEfrisBtn');
            const useBtn = document.getElementById('useEfrisBtn');

            if (createBtn) {
                createBtn.addEventListener('click', () => {
                    this.createCustomerFromEFRIS(taxpayerData);
                });
            }

            if (useBtn) {
                useBtn.addEventListener('click', () => {
                    this.useEFRISTaxpayer(taxpayerData);
                });
            }
        },

        // FIX: "Use This" now creates customer in DB if not exists
        async useEFRISTaxpayer(taxpayer) {
            console.log('🔄 Using EFRIS taxpayer:', taxpayer);

            Loading.show();

            try {
                const storeId = Utils.getElement('storeSelect')?.value;
                if (!storeId) {
                    throw new Error('Please select a branch first');
                }

                // FIX: Create customer in database first
                const formData = new FormData();
                formData.append('name', taxpayer.legal_name);
                formData.append('tin', taxpayer.tin);
                formData.append('phone', taxpayer.phone || taxpayer.tin.slice(-9));
                formData.append('email', taxpayer.email || '');
                formData.append('address', taxpayer.address || '');
                formData.append('from_efris', 'true');
                formData.append('store_id', storeId);

                console.log('📤 Creating customer from EFRIS data...');

                const customer = await API.createCustomer(formData);

                console.log('✅ Customer created:', customer);

                // Select the created customer
                this.selectCustomer(customer);

                // Clean up EFRIS UI
                const results = Utils.getElement('efrisQueryResults');
                const tinInput = Utils.getElement('taxpayerTIN');

                Utils.toggleElement(results, false);
                if (tinInput) tinInput.value = '';

                // Switch to search tab
                const searchTab = Utils.getElement('searchTabBtn');
                if (searchTab) {
                    new bootstrap.Tab(searchTab).show();
                }

                Toast.show('Customer added from EFRIS', 'success');

            } catch (error) {
                console.error('❌ Error using EFRIS taxpayer:', error);
                ErrorHandler.handleApiError(error, 'Add customer from EFRIS');
            } finally {
                Loading.hide();
            }
        },

        async createCustomerFromEFRIS(taxpayer) {
            console.log('📝 Creating customer from EFRIS:', taxpayer);

            Loading.show();

            try {
                const storeId = Utils.getElement('storeSelect')?.value;
                if (!storeId) {
                    throw new Error('Please select a branch first');
                }

                const formData = new FormData();
                formData.append('name', taxpayer.legal_name);
                formData.append('tin', taxpayer.tin);
                formData.append('phone', taxpayer.phone || taxpayer.tin.slice(-9));
                formData.append('email', taxpayer.email || '');
                formData.append('address', taxpayer.address || '');
                formData.append('from_efris', 'true');
                formData.append('store_id', storeId);

                const customer = await API.createCustomer(formData);

                console.log('✅ Customer created from EFRIS:', customer);

                this.selectCustomer(customer);

                // Clean up EFRIS UI
                const results = Utils.getElement('efrisQueryResults');
                const tinInput = Utils.getElement('taxpayerTIN');

                Utils.toggleElement(results, false);
                if (tinInput) tinInput.value = '';

                // Switch to search tab
                const searchTab = Utils.getElement('searchTabBtn');
                if (searchTab) {
                    new bootstrap.Tab(searchTab).show();
                }

                Toast.show('Customer created from EFRIS successfully', 'success');

            } catch (error) {
                console.error('❌ Error creating customer from EFRIS:', error);
                ErrorHandler.handleApiError(error, 'Create customer from EFRIS');
            } finally {
                Loading.hide();
            }
        }
    };

    // ============================================
    // CREDIT MODULE
    // ============================================
    const CreditModule = {
        init() {
            this.attachEventListeners();
        },

        attachEventListeners() {
            const adjustmentType = Utils.getElement('creditAdjustmentType');
            if (adjustmentType) {
                adjustmentType.addEventListener('change', () => {
                    this.updateHint();
                });
            }

            const modal = Utils.getElement('creditAdjustmentModal');
            if (modal) {
                modal.addEventListener('click', (e) => {
                    if (e.target.matches('[data-action="submit-credit-adjustment"]')) {
                        this.submitAdjustment();
                    }
                });
            }
        },

        displayInfo() {
            const creditInfo = State.customerCredit;
            const creditInfoDiv = Utils.getElement('customerCreditInfo');

            if (!creditInfo.allowCredit) {
                Utils.toggleElement(creditInfoDiv, false);
                return;
            }

            Utils.toggleElement(creditInfoDiv, true);

            const creditLimit = Utils.getElement('creditLimit');
            const creditBalance = Utils.getElement('creditBalance');
            const creditAvailable = Utils.getElement('creditAvailable');
            const statusBadge = Utils.getElement('creditStatusBadge');

            if (creditLimit) creditLimit.textContent = Utils.formatCurrency(creditInfo.creditLimit);
            if (creditBalance) creditBalance.textContent = Utils.formatCurrency(creditInfo.creditBalance);
            if (creditAvailable) creditAvailable.textContent = Utils.formatCurrency(creditInfo.creditAvailable);

            if (statusBadge) {
                statusBadge.textContent = creditInfo.creditStatus;
                statusBadge.className = 'badge ';

                const statusClasses = {
                    'GOOD': 'bg-success',
                    'WARNING': 'bg-warning',
                    'SUSPENDED': 'bg-danger',
                    'BLOCKED': 'bg-danger'
                };

                statusBadge.classList.add(statusClasses[creditInfo.creditStatus] || 'bg-secondary');
            }

            this.displayWarnings();
        },

        displayWarnings() {
            const creditInfo = State.customerCredit;
            const warningsDiv = Utils.getElement('creditWarnings');

            if (!warningsDiv) return;

            let warnings = '';

            if (creditInfo.hasOverdue) {
                warnings += `
                    <div class="credit-error">
                        <i class="bi bi-exclamation-triangle me-2"></i>
                        <strong>Overdue Payments:</strong> Customer has overdue invoices totaling
                        ${Utils.formatCurrency(creditInfo.overdueAmount)}
                    </div>
                `;
            }

            if (creditInfo.creditStatus === 'WARNING') {
                warnings += `
                    <div class="credit-warning">
                        <i class="bi bi-exclamation-circle me-2"></i>
                        <strong>Warning:</strong> Customer is approaching credit limit
                    </div>
                `;
            }

            if (creditInfo.creditStatus === 'SUSPENDED' || creditInfo.creditStatus === 'BLOCKED') {
                warnings += `
                    <div class="credit-error">
                        <i class="bi bi-x-circle me-2"></i>
                        <strong>Credit ${creditInfo.creditStatus}:</strong>
                        Customer cannot make credit purchases
                    </div>
                `;
            }

            warningsDiv.innerHTML = warnings;
        },

        updateAdjustmentVisibility() {
            const adjustSection = Utils.getElement('creditAdjustmentSection');
            const customerId = Utils.getElement('customerId')?.value;

            if (adjustSection) {
                Utils.toggleElement(adjustSection, !!customerId);

                if (customerId && State.selectedCustomer) {
                    this.updateAdjustmentModal();
                }
            }
        },

        updateAdjustmentModal() {
            const customer = State.selectedCustomer;
            const creditInfo = State.customerCredit;

            if (!customer) return;

            const customerName = Utils.getElement('creditAdjustCustomerName');
            const currentLimit = Utils.getElement('creditAdjustCurrentLimit');
            const currentBalance = Utils.getElement('creditAdjustCurrentBalance');
            const availableCredit = Utils.getElement('creditAdjustAvailable');

            if (customerName) customerName.textContent = customer.name;
            if (currentLimit) currentLimit.textContent = Utils.formatCurrency(creditInfo.creditLimit);
            if (currentBalance) currentBalance.textContent = Utils.formatCurrency(creditInfo.creditBalance);
            if (availableCredit) availableCredit.textContent = Utils.formatCurrency(creditInfo.creditAvailable);

            this.updateHint();
        },

        updateHint() {
            const adjustmentType = Utils.getElement('creditAdjustmentType');
            const hintText = Utils.getElement('creditAdjustmentHint');

            if (!adjustmentType || !hintText) return;

            const type = adjustmentType.value;
            const creditInfo = State.customerCredit;

            const hints = {
                'SET_LIMIT': `Current limit: ${Utils.formatCurrency(creditInfo.creditLimit)}. Enter new limit.`,
                'INCREASE_LIMIT': `Current limit: ${Utils.formatCurrency(creditInfo.creditLimit)}. Enter amount to add.`,
                'DECREASE_LIMIT': `Current limit: ${Utils.formatCurrency(creditInfo.creditLimit)}. Enter amount to subtract.`,
                'ADD_BALANCE': `Current balance: ${Utils.formatCurrency(creditInfo.creditBalance)}. Enter amount to add.`,
                'REDUCE_BALANCE': `Current balance: ${Utils.formatCurrency(creditInfo.creditBalance)}. Enter amount to subtract.`
            };

            hintText.textContent = hints[type] || '';
        },

        async submitAdjustment() {
            const customerId = Utils.getElement('customerId')?.value;

            if (!customerId) {
                ErrorHandler.show('No customer selected');
                return;
            }

            const adjustmentType = Utils.getElement('creditAdjustmentType')?.value;
            const amount = parseFloat(Utils.getElement('creditAdjustmentAmount')?.value) || 0;
            const reason = Utils.getElement('creditAdjustmentReason')?.value?.trim();

            if (!adjustmentType) {
                ErrorHandler.show('Please select adjustment type');
                return;
            }

            if (amount <= 0) {
                ErrorHandler.show('Please enter a valid amount');
                return;
            }

            if (!reason) {
                ErrorHandler.show('Please provide a reason for this adjustment');
                return;
            }

            const btnText = Utils.getElement('creditAdjustBtnText');
            const btnLoading = Utils.getElement('creditAdjustBtnLoading');
            const submitBtn = document.querySelector('[data-action="submit-credit-adjustment"]');

            Utils.toggleElement(btnText, false);
            Utils.toggleElement(btnLoading, true);
            if (submitBtn) submitBtn.disabled = true;

            try {
                const adjustmentData = {
                    adjustment_type: adjustmentType,
                    amount: amount.toString(),
                    reason: reason
                };

                const updatedCredit = await API.adjustCredit(customerId, adjustmentData);

                State.customerCredit = {
                    allowCredit: Utils.toBoolean(updatedCredit.allow_credit),
                    creditLimit: parseFloat(updatedCredit.credit_limit) || 0,
                    creditBalance: parseFloat(updatedCredit.credit_balance) || 0,
                    creditAvailable: parseFloat(updatedCredit.credit_available) || 0,
                    creditStatus: updatedCredit.credit_status || 'NONE',
                    hasOverdue: Utils.toBoolean(updatedCredit.has_overdue),
                    overdueAmount: parseFloat(updatedCredit.overdue_amount) || 0
                };

                this.displayInfo();
                this.updateAdjustmentModal();

                const modal = bootstrap.Modal.getInstance(Utils.getElement('creditAdjustmentModal'));
                if (modal) modal.hide();

                const form = Utils.getElement('creditAdjustmentForm');
                if (form) form.reset();

                Toast.show('Credit adjustment applied successfully', 'success');

                PaymentModule.validate();

            } catch (error) {
                ErrorHandler.handleApiError(error, 'Credit adjustment');
            } finally {
                Utils.toggleElement(btnText, true);
                Utils.toggleElement(btnLoading, false);
                if (submitBtn) submitBtn.disabled = false;
            }
        }
    };

    // ============================================
    // CART MODULE
    // ============================================
    const CartModule = {
        init() {
            this.attachEventListeners();
        },

        attachEventListeners() {
            const cartItems = Utils.getElement('cartItems');
            if (cartItems) {
                cartItems.addEventListener('click', (e) => {
                    const target = e.target;

                    if (target.matches('.qty-btn')) {
                        const index = parseInt(target.dataset.index);
                        const delta = parseInt(target.dataset.delta);
                        const currentQty = State.cart[index]?.quantity || 1;
                        this.updateQuantity(index, currentQty + delta);
                    }

                    if (target.matches('.btn-remove-item') || target.closest('.btn-remove-item')) {
                        const btn = target.closest('.btn-remove-item');
                        const index = parseInt(btn.dataset.index);
                        this.removeItem(index);
                    }

                    if (target.matches('[data-action="reset-price"]')) {
                        const index = parseInt(target.dataset.index);
                        this.resetPrice(index);
                    }
                });

                cartItems.addEventListener('change', (e) => {
                    const target = e.target;

                    if (target.matches('.qty-input')) {
                        const index = parseInt(target.dataset.index);
                        const newQty = parseInt(target.value) || 1;
                        this.updateQuantity(index, newQty);
                    }

                    if (target.matches('[data-action="update-price"]')) {
                        const index = parseInt(target.dataset.index);
                        const newPrice = parseFloat(target.value) || 0;
                        this.updatePrice(index, newPrice);
                    }
                });
            }

            const clearBtn = Utils.getElement('clearCartBtn');
            if (clearBtn) {
                clearBtn.addEventListener('click', () => this.clear());
            }
        },

        addItem(item) {
            const existingIndex = State.cart.findIndex(cartItem =>
                (item.item_type === 'PRODUCT' && cartItem.product_id === item.id) ||
                (item.item_type === 'SERVICE' && cartItem.service_id === item.id)
            );

            if (existingIndex >= 0) {
                this.updateQuantity(existingIndex, State.cart[existingIndex].quantity + 1);
                Toast.show(`Updated quantity for ${item.name}`, 'success');
            } else {
                const cartItem = {
                    item_type: item.item_type,
                    product_id: item.item_type === 'PRODUCT' ? item.id : null,
                    service_id: item.item_type === 'SERVICE' ? item.id : null,
                    name: item.name,
                    code: item.code,
                    quantity: 1,
                    unit_price: item.final_price,
                    original_price: item.final_price,
                    tax_rate: parseFloat(item.tax_rate) || 18,
                    tax_code: item.tax_code || 'A',
                    discount_percentage: item.discount_percentage || 0,
                    discount_amount: 0,
                    unit: item.unit_of_measure || 'pcs',
                    stock_available: item.stock?.available || null,
                    stock_unit: item.stock?.unit || null
                };

                State.cart.push(cartItem);
                Toast.show(`Added ${item.name} to cart`, 'success');
            }

            State.cartModified = true;
            this.render();
        },

        updateQuantity(index, newQuantity) {
            const item = State.cart[index];
            if (!item) return;

            if (newQuantity < 1) {
                this.removeItem(index);
                return;
            }

            if (item.item_type === 'PRODUCT' && item.stock_available !== null) {
                if (newQuantity > item.stock_available) {
                    ErrorHandler.show(`Only ${item.stock_available} ${item.stock_unit} available`);
                    return;
                }
            }

            item.quantity = newQuantity;
            State.cartModified = true;
            this.render();
        },

        updatePrice(index, newPrice) {
            const item = State.cart[index];
            if (!item) return;

            if (isNaN(newPrice) || newPrice < 0) {
                ErrorHandler.show('Please enter a valid price');
                this.render();
                return;
            }

            const priceDifference = Math.abs(newPrice - item.original_price);
            const percentChange = (priceDifference / item.original_price) * 100;

            if (percentChange > CONFIG.PRICE_CHANGE_THRESHOLD) {
                const direction = newPrice > item.original_price ? 'increased' : 'decreased';

                if (!confirm(
                    `Price ${direction} by ${percentChange.toFixed(1)}%\n\n` +
                    `Original: ${Utils.formatCurrency(item.original_price)}\n` +
                    `New: ${Utils.formatCurrency(newPrice)}\n\n` +
                    `Continue?`
                )) {
                    this.render();
                    return;
                }
            }

            item.unit_price = newPrice;

            if (newPrice !== item.original_price) {
                const change = newPrice > item.original_price ? 'increased' : 'decreased';
                Toast.show(`Price ${change} for ${item.name}`, 'info');
            }

            State.cartModified = true;
            this.render();
        },

        resetPrice(index) {
            const item = State.cart[index];
            if (!item) return;

            item.unit_price = item.original_price;
            Toast.show(`Price reset for ${item.name}`, 'info');
            State.cartModified = true;
            this.render();
        },

        removeItem(index) {
            const item = State.cart[index];
            State.cart.splice(index, 1);
            Toast.show(`Removed ${item.name}`, 'warning');
            State.cartModified = true;
            this.render();
        },

        clear() {
            if (State.cart.length === 0) return;

            if (confirm('Clear all items from cart?')) {
                State.cart = [];
                State.discount = { type: 'percentage', value: 0 };
                State.cartModified = false;
                this.render();
                Toast.show('Cart cleared', 'warning');
            }
        },

        calculateItemTotal(item) {
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

            return {
                subtotal,
                discount: discountAmount,
                taxableAmount,
                tax,
                total: priceAfterDiscount
            };
        },

        render() {
            const cartItems = Utils.getElement('cartItems');
            const cartCount = Utils.getElement('cartCount');
            const cartSummary = Utils.getElement('cartSummary');
            const discountSection = Utils.getElement('discountSection');
            const clearBtn = Utils.getElement('clearCartBtn');
            const completeBtn = Utils.getElement('completeSaleBtn');

            if (!cartItems) return;

            if (cartCount) cartCount.textContent = State.cart.length;

            if (State.cart.length === 0) {
                cartItems.innerHTML = `
                    <div class="cart-empty">
                        <i class="bi bi-cart-x cart-empty-icon"></i>
                        <p class="mt-2">Cart is empty</p>
                        <p class="small text-muted">Add products or services</p>
                    </div>
                `;

                Utils.toggleElement(cartSummary, false);
                Utils.toggleElement(discountSection, false);
                if (clearBtn) clearBtn.disabled = true;
                if (completeBtn) completeBtn.disabled = true;

                this.updateStats();
                return;
            }

            if (clearBtn) clearBtn.disabled = false;

            cartItems.innerHTML = State.cart.map((item, index) => {
                const itemTotal = this.calculateItemTotal(item);
                const priceChanged = item.unit_price !== item.original_price;

                return `
                    <div class="cart-item">
                        <div class="cart-item-icon">
                            <i class="bi ${item.item_type === 'PRODUCT' ? 'bi-box' : 'bi-gear'}"></i>
                        </div>
                        <div class="cart-item-details">
                            <div class="cart-item-name">
                                <span>${Utils.escapeHtml(item.name)}</span>
                                <span class="cart-item-price">${Utils.formatCurrency(itemTotal.total)}</span>
                            </div>
                            <div class="cart-item-meta">
                                ${item.code ? `${Utils.escapeHtml(item.code)} • ` : ''}${Utils.escapeHtml(item.unit)}
                            </div>
                            <div class="cart-item-controls">
                                <div class="qty-control">
                                    <button class="qty-btn" type="button" data-index="${index}" data-delta="-1">−</button>
                                    <input type="number" class="qty-input"
                                           value="${item.quantity}"
                                           min="1"
                                           data-index="${index}">
                                    <button class="qty-btn" type="button" data-index="${index}" data-delta="1">+</button>
                                </div>
                                <button type="button" class="btn-remove-item" data-index="${index}">
                                    <i class="bi bi-trash"></i>
                                </button>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');

            Utils.toggleElement(cartSummary, true);
            Utils.toggleElement(discountSection, true);
            if (completeBtn) completeBtn.disabled = false;

            this.updateSummary();
            this.updateStats();
        },

        updateSummary() {
            let subtotal = 0;
            let totalTax = 0;
            let totalDiscount = 0;

            State.cart.forEach(item => {
                const itemTotal = this.calculateItemTotal(item);
                subtotal += itemTotal.subtotal;
                totalTax += itemTotal.tax;
                totalDiscount += itemTotal.discount;
            });

            if (State.discount.value > 0) {
                let globalDiscount = 0;

                if (State.discount.type === 'percentage') {
                    globalDiscount = subtotal * (State.discount.value / 100);
                } else {
                    globalDiscount = Math.min(State.discount.value, subtotal);
                }

                totalDiscount += globalDiscount;
                subtotal -= globalDiscount;

                totalTax = 0;
                State.cart.forEach(item => {
                    if (item.tax_rate > 0) {
                        const itemProportion = (item.unit_price * item.quantity) / (subtotal + totalDiscount);
                        const itemDiscounted = subtotal * itemProportion;
                        const taxMultiplier = item.tax_rate / 100;
                        totalTax += (itemDiscounted / (1 + taxMultiplier)) * taxMultiplier;
                    }
                });
            }

            const total = subtotal;

            const summarySubtotal = Utils.getElement('summarySubtotal');
            const summaryTax = Utils.getElement('summaryTax');
            const summaryDiscount = Utils.getElement('summaryDiscount');
            const summaryTotal = Utils.getElement('summaryTotal');

            if (summarySubtotal) summarySubtotal.textContent = Utils.formatCurrency(subtotal);
            if (summaryTax) summaryTax.textContent = Utils.formatCurrency(totalTax);
            if (summaryDiscount) summaryDiscount.textContent = Utils.formatCurrency(totalDiscount);
            if (summaryTotal) summaryTotal.textContent = Utils.formatCurrency(total);

            const itemsData = Utils.getElement('itemsData');
            const subtotalAmount = Utils.getElement('subtotalAmount');
            const taxAmount = Utils.getElement('taxAmount');
            const discountAmount = Utils.getElement('discountAmount');
            const totalAmount = Utils.getElement('totalAmount');
            const discountTypeField = Utils.getElement('discountTypeField');

            if (itemsData) itemsData.value = JSON.stringify(State.cart);
            if (subtotalAmount) subtotalAmount.value = subtotal.toFixed(2);
            if (taxAmount) taxAmount.value = totalTax.toFixed(2);
            if (discountAmount) discountAmount.value = totalDiscount.toFixed(2);
            if (totalAmount) totalAmount.value = total.toFixed(2);
            if (discountTypeField) discountTypeField.value = State.discount.type;

            PaymentModule.validate();
        },

        updateStats() {
            const statsItems = Utils.getElement('statsItems');
            const statsAvgPrice = Utils.getElement('statsAvgPrice');

            if (!statsItems || !statsAvgPrice) return;

            if (State.cart.length === 0) {
                if (statsItems) statsItems.textContent = '0';
                if (statsAvgPrice) statsAvgPrice.textContent = '0 UGX';
                return;
            }

            const totalItems = State.cart.reduce((sum, item) => sum + item.quantity, 0);
            const avgPrice = State.cart.reduce((sum, item) => sum + item.unit_price, 0) / State.cart.length;

            if (statsItems) statsItems.textContent = totalItems;
            if (statsAvgPrice) statsAvgPrice.textContent = Utils.formatCurrency(avgPrice);
        },

        getTotal() {
            const totalElement = Utils.getElement('summaryTotal');
            if (!totalElement) return 0;

            const totalText = totalElement.textContent;
            const total = parseFloat(totalText.replace(/[^0-9.-]+/g, ''));
            return isNaN(total) ? 0 : total;
        }
    };

    // ============================================
    // ITEMS MODULE
    // ============================================
    const ItemsModule = {
        init() {
            this.attachEventListeners();
        },

        attachEventListeners() {
            const searchBar = Utils.getElement('productSearchBar');
            if (searchBar) {
                searchBar.addEventListener('input', Utils.debounce(() => {
                    State.currentPage = 1;
                    this.load();
                }));
            }

            const storeSelect = Utils.getElement('storeSelect');
            if (storeSelect) {
                storeSelect.addEventListener('change', () => {
                    State.currentPage = 1;
                    this.load();

                    if (State.selectedCustomer) {
                        CustomerModule.clearCustomer();
                        Toast.show('Customer cleared. Select customer for this branch.', 'info');
                    }
                });
            }

            document.querySelectorAll('[data-type]').forEach(btn => {
                btn.addEventListener('click', (e) => {
                    const type = e.currentTarget.dataset.type;
                    this.switchType(type);
                });
            });

            const grid = Utils.getElement('productsGrid');
            if (grid) {
                grid.addEventListener('click', (e) => {
                    const addBtn = e.target.closest('[data-action="add-to-cart"]');
                    if (addBtn) {
                        const itemData = Utils.safeJsonParse(addBtn.dataset.item);
                        if (itemData) {
                            CartModule.addItem(itemData);
                        }
                    }
                });
            }
        },

        async load() {
            const storeId = Utils.getElement('storeSelect')?.value;
            const searchBar = Utils.getElement('productSearchBar');
            const query = searchBar?.value || '';

            if (!storeId && State.currentItemType !== 'service') {
                this.showEmpty();
                return;
            }

            this.showLoading();

            try {
                const params = {
                    store_id: storeId,
                    q: query,
                    item_type: State.currentItemType,
                    page: State.currentPage,
                    limit: State.itemsPerPage
                };

                const data = await API.searchItems(params);

                if (data.items && data.items.length > 0) {
                    State.items = data.items;
                    State.totalItems = data.total || data.items.length;
                    this.display(data.items);
                } else {
                    this.showEmpty();
                }
            } catch (error) {
                ErrorHandler.handleApiError(error, 'Load items');
                this.showEmpty();
            }
        },

        display(items) {
            const grid = Utils.getElement('productsGrid');
            if (!grid) return;

            this.hideLoading();

            grid.innerHTML = items.map(item => {
                const isProduct = item.item_type === 'PRODUCT';
                const outOfStock = isProduct && item.stock?.available <= 0;
                const itemJson = JSON.stringify(item).replace(/"/g, '&quot;');

                return `
                    <div class="product-card ${outOfStock ? 'out-of-stock' : ''}">
                        ${item.discount_percentage > 0 ? `
                            <div class="discount-badge">-${item.discount_percentage}%</div>
                        ` : ''}

                        <span class="product-badge ${isProduct ? 'product' : 'service'}">
                            ${item.item_type}
                        </span>

                        <div class="product-image">
                            <i class="bi ${isProduct ? 'bi-box' : 'bi-gear'}"></i>
                        </div>

                        <div class="product-info">
                            <h6 class="product-name">${Utils.escapeHtml(item.name)}</h6>

                            <div class="product-price">
                                ${Utils.formatCurrency(item.final_price)}
                            </div>

                            ${isProduct && item.stock ? `
                                <div class="product-stock">
                                    <span class="stock-dot ${outOfStock ? 'out-of-stock' : item.stock.available <= 10 ? 'low-stock' : 'in-stock'}"></span>
                                    <span>Stock: ${item.stock.available}</span>
                                </div>
                            ` : ''}

                            <button type="button" class="btn-add-product"
                                    data-action="add-to-cart"
                                    data-item="${itemJson}"
                                    ${outOfStock ? 'disabled' : ''}>
                                <i class="bi bi-cart-plus"></i>
                                ${outOfStock ? 'Out of Stock' : 'Add'}
                            </button>
                        </div>
                    </div>
                `;
            }).join('');
        },

        switchType(type) {
            State.currentItemType = type;
            State.currentPage = 1;

            document.querySelectorAll('[data-type]').forEach(btn => {
                const isActive = btn.dataset.type === type;
                btn.classList.toggle('active', isActive);
                btn.classList.toggle('pos-tab', true);
            });

            this.load();
        },

        showLoading() {
            Utils.toggleElement(Utils.getElement('productsLoading'), true);
            Utils.toggleElement(Utils.getElement('productsGrid'), false);
            Utils.toggleElement(Utils.getElement('productsEmpty'), false);
        },

        hideLoading() {
            Utils.toggleElement(Utils.getElement('productsLoading'), false);
            Utils.toggleElement(Utils.getElement('productsGrid'), true);
        },

        showEmpty() {
            this.hideLoading();
            Utils.toggleElement(Utils.getElement('productsGrid'), false);
            Utils.toggleElement(Utils.getElement('productsEmpty'), true);
        }
    };

    // ============================================
    // PAYMENT MODULE
    // ============================================
    const PaymentModule = {
        init() {
            this.attachEventListeners();
        },

        attachEventListeners() {
            const paymentSelect = Utils.getElement('paymentMethod');
            if (paymentSelect) {
                paymentSelect.addEventListener('change', () => {
                    this.validate();
                    CreditModule.updateAdjustmentVisibility();
                });
            }

            document.querySelectorAll('input[name="document_type"]').forEach(radio => {
                radio.addEventListener('change', (e) => {
                    this.handleDocTypeChange(e.target.value);
                });
            });
        },

        validate() {
            const paymentSelect = Utils.getElement('paymentMethod');
            if (!paymentSelect) return true;

            const paymentMethod = paymentSelect.value;
            const creditStatusDiv = Utils.getElement('creditPaymentStatus');
            const creditWarning = Utils.getElement('creditLimitWarning');
            const creditWarningText = Utils.getElement('creditLimitWarningText');
            const completeBtn = Utils.getElement('completeSaleBtn');

            Utils.toggleElement(creditStatusDiv, false);
            Utils.toggleElement(creditWarning, false);

            if (paymentMethod === 'CREDIT') {
                const docTypeRadio = document.querySelector('input[name="document_type"]:checked');
                if (docTypeRadio?.value === 'RECEIPT') {
                    const invoiceRadio = Utils.getElement('docInvoice');
                    if (invoiceRadio) {
                        invoiceRadio.checked = true;
                        this.handleDocTypeChange('INVOICE');
                        Toast.show('Switched to Invoice (required for credit)', 'info');
                    }
                }

                const customerId = Utils.getElement('customerId')?.value;

                if (!customerId) {
                    if (creditWarning && creditWarningText) {
                        creditWarningText.textContent = 'Please select a customer for credit sales';
                        Utils.toggleElement(creditWarning, true);
                    }
                    if (completeBtn) completeBtn.disabled = true;
                    return false;
                }

                const credit = State.customerCredit;

                if (!credit.allowCredit) {
                    if (creditWarning && creditWarningText) {
                        creditWarningText.textContent = 'Customer not authorized for credit';
                        Utils.toggleElement(creditWarning, true);
                    }
                    if (completeBtn) completeBtn.disabled = true;
                    return false;
                }

                if (credit.creditStatus === 'SUSPENDED' || credit.creditStatus === 'BLOCKED') {
                    if (creditWarning && creditWarningText) {
                        creditWarningText.textContent = `Credit ${credit.creditStatus}: Cannot make credit purchases`;
                        Utils.toggleElement(creditWarning, true);
                    }
                    if (completeBtn) completeBtn.disabled = true;
                    return false;
                }

                if (credit.hasOverdue) {
                    if (creditWarning && creditWarningText) {
                        creditWarningText.textContent = 'Customer has overdue invoices';
                        Utils.toggleElement(creditWarning, true);
                    }
                    if (completeBtn) completeBtn.disabled = true;
                    return false;
                }

                const cartTotal = CartModule.getTotal();
                if (cartTotal > credit.creditAvailable) {
                    if (creditWarning && creditWarningText) {
                        creditWarningText.innerHTML = `
                            <strong>Credit Limit Exceeded!</strong><br>
                            Sale: ${Utils.formatCurrency(cartTotal)}<br>
                            Available: ${Utils.formatCurrency(credit.creditAvailable)}
                        `;
                        Utils.toggleElement(creditWarning, true);
                    }
                    if (completeBtn) completeBtn.disabled = true;
                    return false;
                }

                Utils.toggleElement(creditStatusDiv, true);
                if (completeBtn) completeBtn.disabled = false;
                return true;
            }

            if (completeBtn) {
                completeBtn.disabled = State.cart.length === 0;
            }
            return true;
        },

        handleDocTypeChange(docType) {
            const dueDateSection = Utils.getElement('dueDateSection');
            const dueDateField = Utils.getElement('dueDate');

            if (docType === 'INVOICE') {
                Utils.toggleElement(dueDateSection, true);

                if (dueDateField) {
                    const dueDate = new Date();
                    dueDate.setDate(dueDate.getDate() + 30);
                    dueDateField.value = dueDate.toISOString().split('T')[0];
                    dueDateField.required = true;
                }

                if (!State.selectedCustomer) {
                    Toast.show('Customer required for invoices', 'warning');
                }
            } else {
                Utils.toggleElement(dueDateSection, false);
                if (dueDateField) {
                    dueDateField.value = '';
                    dueDateField.required = false;
                }
            }
        }
    };

    // ============================================
    // SALE COMPLETION - FIXED
    // ============================================
    const SaleModule = {
        init() {
            this.attachEventListeners();
        },

        attachEventListeners() {
            const completeBtn = Utils.getElement('completeSaleBtn');
            if (completeBtn) {
                completeBtn.addEventListener('click', () => this.complete());
            }

            const form = Utils.getElement('createSaleForm');
            if (form) {
                form.addEventListener('submit', (e) => {
                    e.preventDefault();
                    this.complete();
                });
            }
        },

        async complete() {
            Loading.show();

            try {
                if (State.cart.length === 0) {
                    throw new Error('Please add items to cart');
                }

                const storeId = Utils.getElement('storeSelect')?.value;
                if (!storeId) {
                    throw new Error('Please select a branch');
                }

                const docType = document.querySelector('input[name="document_type"]:checked')?.value;
                if (!docType) {
                    throw new Error('Please select document type');
                }

                if (docType === 'INVOICE') {
                    if (!State.selectedCustomer) {
                        throw new Error('Customer required for invoices');
                    }

                    const dueDateField = Utils.getElement('dueDate');
                    if (!dueDateField?.value) {
                        throw new Error('Due date required for invoices');
                    }
                }

                const paymentMethod = Utils.getElement('paymentMethod')?.value;
                if (paymentMethod === 'CREDIT') {
                    if (!PaymentModule.validate()) {
                        throw new Error('Credit validation failed');
                    }

                    const cartTotal = CartModule.getTotal();
                    if (!confirm(
                        `Confirm Credit Sale\n\n` +
                        `Amount: ${Utils.formatCurrency(cartTotal)}\n` +
                        `Proceed?`
                    )) {
                        Loading.hide();
                        return;
                    }
                }

                for (const item of State.cart) {
                    if (item.item_type === 'PRODUCT' && item.stock_available !== null) {
                        if (item.quantity > item.stock_available) {
                            throw new Error(`${item.name}: Only ${item.stock_available} available`);
                        }
                    }
                }

                const noteText = Utils.getElement('saleNoteText')?.value?.trim();
                const noteImportant = Utils.getElement('noteIsImportant')?.checked;
                const noteCategory = Utils.getElement('noteCategory')?.value;

                const saleNoteField = Utils.getElement('saleNote');
                const noteImportantField = Utils.getElement('noteIsImportantField');
                const noteCategoryField = Utils.getElement('noteCategoryField');

                if (saleNoteField) saleNoteField.value = noteText || '';
                if (noteImportantField) noteImportantField.value = noteImportant ? '1' : '0';
                if (noteCategoryField) noteCategoryField.value = noteCategory || 'GENERAL';

                // FIX: Mark cart as not modified before submit to prevent popup
                State.cartModified = false;

                const form = Utils.getElement('createSaleForm');
                if (form) {
                    form.submit();
                } else {
                    throw new Error('Form not found');
                }

            } catch (error) {
                Loading.hide();
                ErrorHandler.show(error.message);
            }
        }
    };

    // ============================================
    // KEYBOARD SHORTCUTS
    // ============================================
    const Shortcuts = {
        init() {
            document.addEventListener('keydown', (e) => {
                if (e.target.matches('input, textarea, select')) {
                    if (e.key === 'Escape') {
                        e.target.blur();
                    }
                    return;
                }

                switch(e.key) {
                    case 'F1':
                        e.preventDefault();
                        Utils.getElement('productSearchBar')?.focus();
                        break;

                    case 'F2':
                        e.preventDefault();
                        Utils.getElement('customerSearch')?.focus();
                        break;

                    case 'F3':
                        e.preventDefault();
                        const completeBtn = Utils.getElement('completeSaleBtn');
                        if (completeBtn && !completeBtn.disabled) {
                            SaleModule.complete();
                        }
                        break;

                    case 'Escape':
                        const dropdown = Utils.getElement('customerDropdown');
                        if (dropdown?.classList.contains('show')) {
                            dropdown.classList.remove('show');
                        }
                        break;
                }
            });
        }
    };

    // ============================================
    // CACHE CLEANUP
    // ============================================
    let cleanupInterval;

    function startCacheCleanup() {
        cleanupInterval = setInterval(() => {
            API.cache.cleanup();
        }, CONFIG.CACHE_CLEANUP_INTERVAL);
    }

    function stopCacheCleanup() {
        if (cleanupInterval) {
            clearInterval(cleanupInterval);
        }
    }

    // ============================================
    // INITIALIZATION
    // ============================================
    function init() {
        console.log('🚀 Initializing Sales Page...');

        Toast.init();
        Loading.init();
        ErrorHandler.init();
        CustomerModule.init();
        CreditModule.init();
        CartModule.init();
        ItemsModule.init();
        PaymentModule.init();
        SaleModule.init();
        Shortcuts.init();

        startCacheCleanup();

        const storeId = Utils.getElement('storeSelect')?.value;
        if (storeId) {
            ItemsModule.load();
        }

        const urlParams = new URLSearchParams(window.location.search);
        const customerIdFromUrl = urlParams.get('customer_id');

        if (customerIdFromUrl) {
            handleCustomerFromUrl(customerIdFromUrl);
        }

        // FIX: Only warn on page leave if cart has been modified
        window.addEventListener('beforeunload', (e) => {
            if (State.cartModified && State.cart.length > 0) {
                const message = 'You have unsaved changes in your cart.';
                e.returnValue = message;
                return message;
            }
        });

        window.addEventListener('unload', () => {
            stopCacheCleanup();
        });

        console.log('✅ Sales Page Initialized');
    }

    async function handleCustomerFromUrl(customerId) {
        try {
            Toast.show('Loading customer...', 'info');
            const customer = await API.getCustomer(customerId);
            CustomerModule.selectCustomer(customer);

            const url = new URL(window.location);
            url.searchParams.delete('customer_id');
            window.history.replaceState({}, '', url);
        } catch (error) {
            ErrorHandler.handleApiError(error, 'Load customer from URL');
        }
    }

    // ============================================
    // EXPOSE GLOBAL API
    // ============================================
    window.SalesApp = {
        selectCustomer: (customer) => CustomerModule.selectCustomer(customer),
        removeCustomer: () => CustomerModule.clearCustomer(),
        createCustomer: () => CustomerModule.createCustomer(),
        addToCart: (item) => CartModule.addItem(item),
        clearCart: () => CartModule.clear(),
        loadItems: () => ItemsModule.load(),
        switchItemType: (type) => ItemsModule.switchType(type),
        completeSale: () => SaleModule.complete(),
        formatCurrency: Utils.formatCurrency,
        escapeHtml: Utils.escapeHtml
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();