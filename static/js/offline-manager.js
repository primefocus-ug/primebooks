// ============================================
// OFFLINE MANAGER MODULE
// ============================================

import dbManager from './db-manager.js';
import authManager from './auth-manager.js';
import syncManager from './sync-manager.js';
import offlineDetector from './offline-detector.js';
import djangoAPIAdapter from './django-api-adapter.js';

class OfflineSaleManager {
    constructor() {
        this.isInitialized = false;
        this.currentUser = null;
        this.isOnline = true;
    }

    async init() {
        console.log('🔌 Initializing Offline Sale Manager...');

        try {
            // Initialize database
            await dbManager.init();

            // Get current user
            this.currentUser = await authManager.getCurrentUser();

            if (!this.currentUser) {
                console.warn('No authenticated user for offline mode');
                return false;
            }

            // Setup offline detector
            this.setupOfflineDetection();

            // Setup sync listeners
            this.setupSyncListeners();

            // Load cached data
            await this.loadCachedData();

            // Check for pending syncs
            await this.checkPendingSync();

            this.isInitialized = true;
            console.log('✅ Offline Sale Manager Ready');

            return true;

        } catch (error) {
            console.error('❌ Offline initialization failed:', error);
            this.showToast('Offline mode unavailable. You must be online.', 'warning');
            return false;
        }
    }

    setupOfflineDetection() {
        offlineDetector.on((status) => {
            this.isOnline = (status === 'online');
            this.updateUIForConnectionStatus();

            if (status === 'online') {
                console.log('📡 Back online - triggering sync');
                syncManager.startSync();
            }
        });

        this.isOnline = offlineDetector.getStatus().online;
        this.updateUIForConnectionStatus();
    }

    setupSyncListeners() {
        syncManager.on((event, data) => {
            switch (event) {
                case 'sync_started':
                    this.showSyncProgress(true);
                    break;
                case 'sync_progress':
                    this.updateSyncProgress(data);
                    break;
                case 'sync_completed':
                    this.showSyncProgress(false);
                    this.showToast(`Sync complete: ${data.completed} items synced`, 'success');
                    break;
                case 'sync_error':
                    this.showSyncProgress(false);
                    this.showToast('Sync error occurred', 'error');
                    break;
            }
        });
    }

    updateUIForConnectionStatus() {
        const statusIndicator = document.getElementById('connectionStatus');
        const offlineBanner = document.getElementById('offlineBanner');

        if (statusIndicator) {
            statusIndicator.className = `connection-status ${this.isOnline ? 'online' : 'offline'}`;
            statusIndicator.innerHTML = this.isOnline ?
                '<i class="bi bi-wifi"></i> Online' :
                '<i class="bi bi-wifi-off"></i> Offline';
        }

        if (offlineBanner) {
            offlineBanner.style.display = this.isOnline ? 'none' : 'block';
        }

        document.body.classList.toggle('offline-mode', !this.isOnline);
        document.body.classList.toggle('online-mode', this.isOnline);
    }

    async loadCachedData() {
        try {
            // Load products/services from IndexedDB
            const products = await dbManager.getAll('products');
            const services = await dbManager.getAll('services');

            console.log(`📦 Loaded ${products.length} products, ${services.length} services from cache`);

            // Load customers
            const customers = await dbManager.getAll('customers');
            console.log(`👥 Loaded ${customers.length} customers from cache`);

            // Load stores
            const stores = await dbManager.getAll('stores');
            console.log(`🏪 Loaded ${stores.length} stores from cache`);

        } catch (error) {
            console.error('Error loading cached data:', error);
        }
    }

    async checkPendingSync() {
        const queueStatus = await syncManager.getQueueStatus();

        if (queueStatus.pending > 0) {
            const badge = document.getElementById('pendingSyncBadge');
            if (badge) {
                badge.textContent = queueStatus.pending;
                badge.style.display = 'inline-block';
            }

            this.showToast(`${queueStatus.pending} items pending sync`, 'info');

            if (this.isOnline) {
                syncManager.startSync();
            }
        }
    }

    showSyncProgress(show) {
        const progressBar = document.getElementById('syncProgress');
        if (progressBar) {
            progressBar.style.display = show ? 'block' : 'none';
        }
    }

    updateSyncProgress(data) {
        const progressBar = document.getElementById('syncProgress');
        if (progressBar && data.total > 0) {
            const percent = (data.completed / data.total) * 100;
            progressBar.innerHTML = `
                <div class="progress">
                    <div class="progress-bar" role="progressbar"
                         style="width: ${percent}%"
                         aria-valuenow="${percent}"
                         aria-valuemin="0"
                         aria-valuemax="100">
                        ${data.completed}/${data.total}
                    </div>
                </div>
                <div class="sync-text">Syncing ${data.current}...</div>
            `;
        }
    }

    // ============================================
    // OFFLINE SALE CREATION
    // ============================================

    async createSaleOffline(saleData, saleItems) {
        console.log('💾 Creating sale offline...');

        try {
            // Prepare sale for offline creation
            const preparedSale = djangoAPIAdapter.prepareForOfflineCreation(
                'sales',
                saleData,
                this.currentUser.id
            );

            // Add sale items
            preparedSale.items = saleItems;

            // Save to IndexedDB
            await dbManager.put('sales', preparedSale, this.currentUser.id);

            // Save sale items
            for (const item of saleItems) {
                const itemId = djangoAPIAdapter.generateClientId('sale_item');
                await dbManager.put('sale_items', {
                    id: itemId,
                    sale_id: preparedSale.id,
                    ...item,
                    sync_status: 'pending'
                });
            }

            // Update local stock
            await this.updateLocalStock(saleItems);

            // Add to sync queue with highest priority
            await syncManager.addToQueue('sales', 'create', preparedSale, 1);

            console.log('✅ Sale saved offline:', preparedSale.id);

            return {
                success: true,
                sale: preparedSale,
                offline: true
            };

        } catch (error) {
            console.error('❌ Offline sale creation failed:', error);
            throw error;
        }
    }

    async updateLocalStock(saleItems) {
        for (const item of saleItems) {
            if (item.item_type === 'PRODUCT' && item.product_id) {
                try {
                    // Get current stock
                    const stocks = await dbManager.getAll('stock', 'product_id', item.product_id);
                    const stock = stocks[0];

                    if (stock) {
                        // Reduce quantity
                        stock.quantity -= item.quantity;
                        stock.quantity_change = -item.quantity;

                        await dbManager.put('stock', stock, this.currentUser.id);

                        // Create stock movement
                        const movementId = djangoAPIAdapter.generateClientId('stock_movement');
                        await dbManager.put('stock_movements', {
                            id: movementId,
                            product_id: item.product_id,
                            store_id: stock.store_id,
                            movement_type: 'SALE',
                            quantity: -item.quantity,
                            reference: 'Sale (Offline)',
                            created_by_id: this.currentUser.id,
                            created_at: new Date().toISOString(),
                            sync_status: 'pending'
                        });

                        // Add to sync queue
                        await syncManager.addToQueue('stock', 'update', stock, 3);
                    }
                } catch (error) {
                    console.error('Error updating local stock:', error);
                }
            }
        }
    }

    // ============================================
    // ONLINE SALE CREATION
    // ============================================

    async createSaleOnline(saleData, saleItems) {
        console.log('🌐 Creating sale online...');

        try {
            const token = await authManager.getToken();

            // Prepare data for Django API
            const apiData = djangoAPIAdapter.prepareSaleForDjango(saleData, saleItems);

            // Send to server
            const response = await fetch('/api/sales/sales/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify(apiData)
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(djangoAPIAdapter.handleDjangoError(errorData));
            }

            const responseData = await response.json();

            // Cache the sale locally
            const transformedSale = djangoAPIAdapter.transformFromDjango('sales', responseData);
            await dbManager.put('sales', transformedSale, this.currentUser.id);

            console.log('✅ Sale created online:', responseData.id);

            return {
                success: true,
                sale: responseData,
                offline: false
            };

        } catch (error) {
            console.error('❌ Online sale creation failed:', error);

            // If network error, fall back to offline
            if (!navigator.onLine || error.message.includes('Failed to fetch')) {
                console.log('📡 Network error, falling back to offline mode');
                return await this.createSaleOffline(saleData, saleItems);
            }

            throw error;
        }
    }

    // ============================================
    // SMART SALE CREATION
    // ============================================

    async createSale(saleData, saleItems) {
        if (this.isOnline) {
            try {
                return await this.createSaleOnline(saleData, saleItems);
            } catch (error) {
                console.warn('Online creation failed, trying offline:', error);
                return await this.createSaleOffline(saleData, saleItems);
            }
        } else {
            return await this.createSaleOffline(saleData, saleItems);
        }
    }

    // ============================================
    // SEARCH PRODUCTS/SERVICES (Offline-capable)
    // ============================================

    async searchItems(query, itemType = 'all', storeId) {
        if (this.isOnline) {
            try {
                const token = await authManager.getToken();
                const params = new URLSearchParams({
                    q: query,
                    item_type: itemType,
                    store_id: storeId
                });

                const response = await fetch(`/sales/search-items/?${params}`, {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });

                if (response.ok) {
                    const data = await response.json();

                    // Cache results
                    if (data.items) {
                        await this.cacheItems(data.items);
                    }

                    return data;
                }
            } catch (error) {
                console.warn('Online search failed, using cache:', error);
            }
        }

        // Fallback to cached data
        return await this.searchItemsOffline(query, itemType, storeId);
    }

    async searchItemsOffline(query, itemType, storeId) {
        console.log('🔍 Searching items offline...');

        let items = [];

        // Search products
        if (itemType === 'all' || itemType === 'product') {
            const products = await dbManager.getAll('products');
            const filtered = products.filter(p => {
                const matchesQuery = !query ||
                    p.name.toLowerCase().includes(query.toLowerCase()) ||
                    p.sku?.toLowerCase().includes(query.toLowerCase());
                const matchesStore = !storeId || this.productBelongsToStore(p, storeId);
                return matchesQuery && matchesStore && p.is_active;
            });
            items.push(...filtered.map(p => ({ ...p, item_type: 'PRODUCT' })));
        }

        // Search services
        if (itemType === 'all' || itemType === 'service') {
            const services = await dbManager.getAll('services');
            const filtered = services.filter(s => {
                const matchesQuery = !query ||
                    s.name.toLowerCase().includes(query.toLowerCase()) ||
                    s.code?.toLowerCase().includes(query.toLowerCase());
                return matchesQuery && s.is_active;
            });
            items.push(...filtered.map(s => ({ ...s, item_type: 'SERVICE' })));
        }

        return { items: items.slice(0, 20), total: items.length };
    }

    productBelongsToStore(product, storeId) {
        // Simplified - implement based on your stock model
        return true;
    }

    async cacheItems(items) {
        for (const item of items) {
            if (item.item_type === 'PRODUCT') {
                await dbManager.put('products', item);
            } else if (item.item_type === 'SERVICE') {
                await dbManager.put('services', item);
            }
        }
    }

    // ============================================
    // SEARCH CUSTOMERS (Offline-capable)
    // ============================================

    async searchCustomers(query, storeId) {
        if (this.isOnline) {
            try {
                const token = await authManager.getToken();
                const params = new URLSearchParams({
                    q: query,
                    store_id: storeId
                });

                const response = await fetch(`/sales/customer-search/?${params}`, {
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });

                if (response.ok) {
                    const data = await response.json();

                    // Cache customers
                    if (data.customers) {
                        for (const customer of data.customers) {
                            await dbManager.put('customers', customer);
                        }
                    }

                    return data;
                }
            } catch (error) {
                console.warn('Online customer search failed, using cache:', error);
            }
        }

        return await this.searchCustomersOffline(query, storeId);
    }

    async searchCustomersOffline(query, storeId) {
        console.log('🔍 Searching customers offline...');

        const customers = await dbManager.getAll('customers');

        const filtered = customers.filter(c => {
            const matchesQuery = !query ||
                c.name.toLowerCase().includes(query.toLowerCase()) ||
                c.phone?.includes(query) ||
                c.email?.toLowerCase().includes(query.toLowerCase());
            const matchesStore = !storeId || c.store_id === parseInt(storeId);
            return matchesQuery && matchesStore && c.is_active;
        });

        return { customers: filtered.slice(0, 10) };
    }

    // ============================================
    // CREATE CUSTOMER (Offline-capable)
    // ============================================

    async createCustomer(customerData) {
        if (this.isOnline) {
            try {
                const token = await authManager.getToken();

                const response = await fetch('/sales/create_customer_ajax/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`,
                        'X-CSRFToken': this.getCookie('csrftoken')
                    },
                    body: JSON.stringify(customerData)
                });

                if (response.ok) {
                    const data = await response.json();
                    await dbManager.put('customers', data.customer);
                    return data;
                }
            } catch (error) {
                console.warn('Online customer creation failed, saving offline:', error);
            }
        }

        return await this.createCustomerOffline(customerData);
    }

    async createCustomerOffline(customerData) {
        const customer = djangoAPIAdapter.prepareForOfflineCreation(
            'customers',
            customerData,
            this.currentUser.id
        );

        await dbManager.put('customers', customer, this.currentUser.id);
        await syncManager.addToQueue('customers', 'create', customer, 6);

        return { success: true, customer, offline: true };
    }

    // ============================================
    // UTILITY METHODS
    // ============================================

    getCookie(name) {
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
    }

    showToast(message, type = 'info') {
        // Use global showToast if available
        if (window.showToast) {
            window.showToast(message, type);
        } else {
            console.log(`[${type.toUpperCase()}] ${message}`);
        }
    }

    async updateSyncManagementPanel() {
        if (!this.isInitialized) return;

        try {
            const queueStatus = await syncManager.getQueueStatus();

            const panel = document.getElementById('syncManagementPanel');
            const pendingCount = document.getElementById('pendingCount');
            const failedCount = document.getElementById('failedCount');
            const totalBadge = document.getElementById('totalPendingBadge');

            if (queueStatus.total > 0) {
                if (panel) panel.style.display = 'block';
                if (pendingCount) pendingCount.textContent = queueStatus.pending;
                if (failedCount) failedCount.textContent = queueStatus.failed;
                if (totalBadge) {
                    totalBadge.textContent = queueStatus.total;
                    totalBadge.style.display = 'inline-block';
                }
            } else {
                if (panel) panel.style.display = 'none';
            }
        } catch (error) {
            console.error('Error updating sync panel:', error);
        }
    }
}

// Export singleton instance
const offlineSaleManager = new OfflineSaleManager();
export default offlineSaleManager;