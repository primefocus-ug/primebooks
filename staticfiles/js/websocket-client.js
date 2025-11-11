
class BranchAnalyticsWebSocket {
    constructor(branchId, options = {}) {
        this.branchId = branchId;
        this.socket = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = options.maxReconnectAttempts || 5;
        this.reconnectDelay = options.reconnectDelay || 1000;
        this.isConnected = false;
        this.eventHandlers = {};
        this.heartbeatInterval = null;
        this.lastHeartbeat = null;

        // Connection state callbacks
        this.onConnected = options.onConnected || (() => {});
        this.onDisconnected = options.onDisconnected || (() => {});
        this.onError = options.onError || ((error) => console.error('WebSocket error:', error));

        this.init();
    }

    init() {
        this.connect();
        this.setupHeartbeat();
    }

    connect() {
        try {
            // Determine WebSocket protocol based on current page protocol
            const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${wsProtocol}//${window.location.host}/ws/branch/${this.branchId}/analytics/`;

            console.log('Connecting to WebSocket:', wsUrl);

            this.socket = new WebSocket(wsUrl);
            this.setupEventListeners();

        } catch (error) {
            console.error('WebSocket connection error:', error);
            this.handleReconnection();
        }
    }

    setupEventListeners() {
        this.socket.onopen = (event) => {
            console.log('WebSocket connected');
            this.isConnected = true;
            this.reconnectAttempts = 0;
            this.onConnected(event);
            this.showConnectionStatus('connected');
        };

        this.socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);
            } catch (error) {
                console.error('Error parsing WebSocket message:', error);
            }
        };

        this.socket.onclose = (event) => {
            console.log('WebSocket closed:', event.code, event.reason);
            this.isConnected = false;
            this.onDisconnected(event);
            this.showConnectionStatus('disconnected');

            // Handle reconnection for unexpected closures
            if (event.code !== 1000) { // 1000 is normal closure
                this.handleReconnection();
            }
        };

        this.socket.onerror = (error) => {
            console.error('WebSocket error:', error);
            this.onError(error);
            this.showConnectionStatus('error');
        };
    }

    handleMessage(data) {
        console.log('WebSocket message received:', data.type, data);

        switch (data.type) {
            case 'initial_data':
                this.handleInitialData(data.data);
                break;
            case 'analytics_update':
                this.handleAnalyticsUpdate(data.data);
                break;
            case 'branch_update':
                this.handleBranchUpdate(data.data);
                break;
            case 'store_update':
                this.handleStoreUpdate(data.data);
                break;
            case 'sale_created':
                this.handleSaleCreated(data.data);
                break;
            case 'performance_alert':
                this.handlePerformanceAlert(data.data, data.severity);
                break;
            case 'error':
                this.handleError(data.message);
                break;
            case 'subscription_confirmed':
                this.handleSubscriptionConfirmed(data.store_id);
                break;
            default:
                // Trigger custom event handlers
                this.triggerEventHandler(data.type, data);
        }

        // Update last heartbeat
        this.lastHeartbeat = new Date();
    }

    handleInitialData(data) {
        console.log('Received initial data:', data);
        this.updateMetrics(data.metrics);
        this.updateStorePerformance(data.stores);
        this.triggerEventHandler('initial_data', data);
    }

    handleAnalyticsUpdate(data) {
        console.log('Analytics update received:', data);
        this.updateMetrics(data.metrics);
        if (data.stores) {
            this.updateStorePerformance(data.stores);
        }
        this.triggerEventHandler('analytics_update', data);
        this.showNotification('Analytics updated', 'info', 2000);
    }

    handleBranchUpdate(data) {
        console.log('Branch update received:', data);
        this.triggerEventHandler('branch_update', data);
    }

    handleStoreUpdate(data) {
        console.log('Store update received:', data);
        this.updateStoreDisplay(data);
        this.triggerEventHandler('store_update', data);
    }

    handleSaleCreated(data) {
        console.log('New sale created:', data);
        this.showSaleNotification(data);
        this.updateSaleCounters(data);
        this.triggerEventHandler('sale_created', data);

        // Request updated analytics after new sale
        setTimeout(() => {
            this.requestUpdate();
        }, 1000);
    }

    handlePerformanceAlert(data, severity = 'info') {
        console.log('Performance alert:', data, severity);
        this.showAlert(data, severity);
        this.triggerEventHandler('performance_alert', { data, severity });
    }

    handleError(message) {
        console.error('WebSocket error message:', message);
        this.showNotification(message, 'error');
        this.triggerEventHandler('error', message);
    }

    handleSubscriptionConfirmed(storeId) {
        console.log('Subscription confirmed for store:', storeId);
        this.triggerEventHandler('subscription_confirmed', storeId);
    }

    handleReconnection() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1); // Exponential backoff

            console.log(`Attempting to reconnect (${this.reconnectAttempts}/${this.maxReconnectAttempts}) in ${delay}ms`);
            this.showConnectionStatus('reconnecting');

            setTimeout(() => {
                this.connect();
            }, delay);
        } else {
            console.error('Max reconnection attempts reached');
            this.showConnectionStatus('failed');
            this.showNotification('Connection lost. Please refresh the page.', 'error', 0);
        }
    }

    setupHeartbeat() {
        this.heartbeatInterval = setInterval(() => {
            if (this.isConnected) {
                this.send({ type: 'ping' });

                // Check if we've received a response recently
                if (this.lastHeartbeat && (new Date() - this.lastHeartbeat) > 60000) {
                    console.warn('No heartbeat response, connection may be stale');
                    this.reconnect();
                }
            }
        }, 30000); // Send ping every 30 seconds
    }

    // Public methods
    send(data) {
        if (this.isConnected && this.socket.readyState === WebSocket.OPEN) {
            try {
                this.socket.send(JSON.stringify(data));
                return true;
            } catch (error) {
                console.error('Error sending WebSocket message:', error);
                return false;
            }
        } else {
            console.warn('WebSocket not connected, cannot send message');
            return false;
        }
    }

    requestUpdate() {
        return this.send({ type: 'request_update' });
    }

    subscribeToStore(storeId) {
        return this.send({
            type: 'subscribe_store',
            store_id: storeId
        });
    }

    unsubscribeFromStore(storeId) {
        return this.send({
            type: 'unsubscribe_store',
            store_id: storeId
        });
    }

    reconnect() {
        if (this.socket) {
            this.socket.close();
        }
        this.isConnected = false;
        this.reconnectAttempts = 0;
        this.connect();
    }

    disconnect() {
        this.isConnected = false;
        if (this.heartbeatInterval) {
            clearInterval(this.heartbeatInterval);
        }
        if (this.socket) {
            this.socket.close(1000, 'Manual disconnect');
        }
    }

    // Event handler management
    on(eventType, handler) {
        if (!this.eventHandlers[eventType]) {
            this.eventHandlers[eventType] = [];
        }
        this.eventHandlers[eventType].push(handler);
    }

    off(eventType, handler) {
        if (this.eventHandlers[eventType]) {
            const index = this.eventHandlers[eventType].indexOf(handler);
            if (index > -1) {
                this.eventHandlers[eventType].splice(index, 1);
            }
        }
    }

    triggerEventHandler(eventType, data) {
        if (this.eventHandlers[eventType]) {
            this.eventHandlers[eventType].forEach(handler => {
                try {
                    handler(data);
                } catch (error) {
                    console.error('Error in event handler:', error);
                }
            });
        }
    }

    // UI update methods
    updateMetrics(metrics) {
        if (!metrics) return;

        // Update revenue
        const revenueElement = document.getElementById('totalRevenue');
        if (revenueElement && metrics.total_revenue !== undefined) {
            const formattedRevenue = this.formatCurrency(metrics.total_revenue);
            this.animateValueChange(revenueElement, formattedRevenue + ' UGX');
        }

        // Update sales count
        const salesElement = document.getElementById('totalSales');
        if (salesElement && metrics.total_sales !== undefined) {
            this.animateValueChange(salesElement, metrics.total_sales.toLocaleString());
        }

        // Update customers
        const customersElement = document.getElementById('totalCustomers');
        if (customersElement && metrics.total_customers !== undefined) {
            this.animateValueChange(customersElement, metrics.total_customers.toLocaleString());
        }

        // Update products
        const productsElement = document.getElementById('totalProducts');
        if (productsElement && metrics.total_products !== undefined) {
            this.animateValueChange(productsElement, metrics.total_products.toLocaleString());
        }

        // Update low stock count
        const lowStockElement = document.getElementById('lowStockCount');
        if (lowStockElement && metrics.low_stock_items !== undefined) {
            this.animateValueChange(lowStockElement, metrics.low_stock_items);

            // Add warning if low stock items increased
            if (metrics.low_stock_items > 0) {
                lowStockElement.classList.add('text-warning');
            }
        }
    }

    updateStorePerformance(stores) {
        if (!stores || !Array.isArray(stores)) return;

        stores.forEach(store => {
            // Update store sales count
            const salesCountElement = document.querySelector(`.store-sales-count[data-store-id="${store.id}"]`);
            if (salesCountElement) {
                this.animateValueChange(salesCountElement, store.sales || 0);
            }

            // Update store performance score
            const performanceScoreElement = document.querySelector(`.store-performance-score[data-store-id="${store.id}"]`);
            if (performanceScoreElement && store.performance_score !== undefined) {
                performanceScoreElement.textContent = `${store.performance_score}%`;
            }

            // Update performance bar
            const performanceBarElement = document.querySelector(`.store-performance-bar[data-store-id="${store.id}"]`);
            if (performanceBarElement && store.performance_score !== undefined) {
                performanceBarElement.style.width = `${store.performance_score}%`;
                performanceBarElement.className = `progress-bar store-performance-bar ${this.getPerformanceClass(store.performance_score)}`;
            }
        });
    }

    updateStoreDisplay(storeData) {
        const storeCard = document.querySelector(`.store-card[data-store-id="${storeData.store_id || storeData.id}"]`);
        if (!storeCard) return;

        // Update active status
        if (storeData.is_active !== undefined) {
            const statusBadge = storeCard.querySelector('.badge.bg-success, .badge.bg-secondary');
            if (statusBadge) {
                if (storeData.is_active) {
                    statusBadge.className = 'badge bg-success';
                    statusBadge.innerHTML = '<i class="bi bi-check-circle me-1"></i>Active';
                } else {
                    statusBadge.className = 'badge bg-secondary';
                    statusBadge.innerHTML = '<i class="bi bi-pause-circle me-1"></i>Inactive';
                }
            }
        }

        // Update EFRIS status
        if (storeData.efris_enabled !== undefined) {
            let efrisBadge = storeCard.querySelector('.badge.bg-info');
            if (storeData.efris_enabled && !efrisBadge) {
                // Add EFRIS badge
                const statusContainer = storeCard.querySelector('.store-status');
                if (statusContainer) {
                    efrisBadge = document.createElement('span');
                    efrisBadge.className = 'badge bg-info ms-1';
                    efrisBadge.innerHTML = '<i class="bi bi-shield-check me-1"></i>EFRIS';
                    statusContainer.appendChild(efrisBadge);
                }
            } else if (!storeData.efris_enabled && efrisBadge) {
                // Remove EFRIS badge
                efrisBadge.remove();
            }
        }
    }

    updateSaleCounters(saleData) {
        // Update quick stats
        const monthlySalesElement = document.getElementById('monthlySales');
        if (monthlySalesElement) {
            const currentValue = parseInt(monthlySalesElement.textContent) || 0;
            this.animateValueChange(monthlySalesElement, currentValue + 1);
        }

        // Update store-specific sales count
        const storeSalesElement = document.querySelector(`.store-sales-count[data-store-id="${saleData.store_id}"]`);
        if (storeSalesElement) {
            const currentValue = parseInt(storeSalesElement.textContent) || 0;
            this.animateValueChange(storeSalesElement, currentValue + 1);
        }
    }

    // Notification and UI helper methods
    showSaleNotification(saleData) {
        const message = `New sale: ${this.formatCurrency(saleData.total_amount)} UGX at ${saleData.store_name}`;
        this.showNotification(message, 'success', 5000);

        // Add visual effect to store card
        const storeCard = document.querySelector(`.store-card[data-store-id="${saleData.store_id}"]`);
        if (storeCard) {
            storeCard.classList.add('sale-flash');
            setTimeout(() => {
                storeCard.classList.remove('sale-flash');
            }, 2000);
        }
    }

    showAlert(alertData, severity = 'info') {
        let alertClass = 'alert-info';
        let alertIcon = 'info-circle';

        switch (severity) {
            case 'error':
            case 'danger':
                alertClass = 'alert-danger';
                alertIcon = 'exclamation-triangle';
                break;
            case 'warning':
                alertClass = 'alert-warning';
                alertIcon = 'exclamation-triangle';
                break;
            case 'success':
                alertClass = 'alert-success';
                alertIcon = 'check-circle';
                break;
        }

        let message = '';
        if (alertData.alert_type === 'low_stock') {
            message = `Low stock alert: ${alertData.product_name} at ${alertData.store_name} (${alertData.quantity} remaining)`;
        } else {
            message = alertData.message || JSON.stringify(alertData);
        }

        this.showNotification(message, severity, 8000);
    }

    showNotification(message, type = 'info', duration = 5000) {
        // Create notification element
        const notification = document.createElement('div');
        notification.className = `alert alert-${type === 'error' ? 'danger' : type} alert-dismissible fade show position-fixed`;
        notification.style.cssText = 'top: 20px; right: 20px; z-index: 1060; min-width: 300px; max-width: 500px;';

        const iconMap = {
            success: 'check-circle',
            error: 'exclamation-triangle',
            warning: 'exclamation-triangle',
            info: 'info-circle'
        };

        notification.innerHTML = `
            <div class="d-flex align-items-center">
                <i class="bi bi-${iconMap[type] || iconMap.info} me-2"></i>
                <div class="flex-grow-1">${message}</div>
            </div>
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        document.body.appendChild(notification);

        // Auto-remove after duration (if duration > 0)
        if (duration > 0) {
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
            }, duration);
        }
    }

    showConnectionStatus(status) {
        let statusElement = document.getElementById('websocket-status');

        if (!statusElement) {
            // Create status indicator
            statusElement = document.createElement('div');
            statusElement.id = 'websocket-status';
            statusElement.className = 'position-fixed';
            statusElement.style.cssText = 'top: 10px; left: 10px; z-index: 1070;';
            document.body.appendChild(statusElement);
        }

        const statusConfig = {
            connected: {
                class: 'badge bg-success',
                icon: 'wifi',
                text: 'Connected'
            },
            disconnected: {
                class: 'badge bg-secondary',
                icon: 'wifi-off',
                text: 'Disconnected'
            },
            reconnecting: {
                class: 'badge bg-warning',
                icon: 'arrow-repeat',
                text: 'Reconnecting...'
            },
            error: {
                class: 'badge bg-danger',
                icon: 'exclamation-triangle',
                text: 'Connection Error'
            },
            failed: {
                class: 'badge bg-danger',
                icon: 'x-circle',
                text: 'Connection Failed'
            }
        };

        const config = statusConfig[status] || statusConfig.disconnected;
        statusElement.className = `position-fixed ${config.class}`;
        statusElement.innerHTML = `<i class="bi bi-${config.icon} me-1"></i>${config.text}`;

        // Hide status indicator after a delay for successful connections
        if (status === 'connected') {
            setTimeout(() => {
                if (statusElement && statusElement.parentNode) {
                    statusElement.style.opacity = '0.5';
                    setTimeout(() => {
                        if (statusElement && statusElement.parentNode) {
                            statusElement.style.display = 'none';
                        }
                    }, 2000);
                }
            }, 3000);
        } else {
            statusElement.style.display = 'block';
            statusElement.style.opacity = '1';
        }
    }

    // Utility methods
    animateValueChange(element, newValue) {
        if (!element) return;

        element.classList.add('value-updated');
        element.textContent = newValue;

        setTimeout(() => {
            element.classList.remove('value-updated');
        }, 1000);
    }

    formatCurrency(amount) {
        if (typeof amount !== 'number') amount = parseFloat(amount) || 0;
        return new Intl.NumberFormat('en-UG', {
            minimumFractionDigits: 0,
            maximumFractionDigits: 0
        }).format(amount);
    }

    getPerformanceClass(score) {
        if (score >= 80) return 'bg-success';
        if (score >= 60) return 'bg-info';
        if (score >= 40) return 'bg-warning';
        return 'bg-danger';
    }
}

// CSS animations for WebSocket updates
const websocketStyles = `
<style>
.value-updated {
    animation: valueFlash 1s ease-in-out;
}

@keyframes valueFlash {
    0% { background-color: rgba(40, 167, 69, 0.3); }
    100% { background-color: transparent; }
}

.sale-flash {
    animation: saleFlash 2s ease-in-out;
    transform: scale(1.02);
}

@keyframes saleFlash {
    0%, 100% {
        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        transform: scale(1);
    }
    50% {
        box-shadow: 0 8px 25px rgba(40, 167, 69, 0.3);
        transform: scale(1.02);
    }
}

#websocket-status {
    transition: all 0.3s ease;
}

.connection-pulse {
    animation: connectionPulse 2s infinite;
}

@keyframes connectionPulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

.realtime-indicator {
    display: inline-flex;
    align-items: center;
    font-size: 0.75rem;
    color: #28a745;
    margin-left: 8px;
}

.realtime-indicator::before {
    content: '';
    width: 6px;
    height: 6px;
    background-color: #28a745;
    border-radius: 50%;
    margin-right: 4px;
    animation: realtimePulse 1.5s infinite;
}

@keyframes realtimePulse {
    0%, 100% { opacity: 1; transform: scale(1); }
    50% { opacity: 0.5; transform: scale(0.8); }
}
</style>
`;

// Inject CSS styles
document.head.insertAdjacentHTML('beforeend', websocketStyles);

// Integration with existing branch analytics code
function initializeWebSocketConnection(branchId) {
    // Create WebSocket connection
    const wsClient = new BranchAnalyticsWebSocket(branchId, {
        maxReconnectAttempts: 5,
        reconnectDelay: 1000,
        onConnected: () => {
            console.log('Branch analytics WebSocket connected');
            addRealtimeIndicators();
        },
        onDisconnected: () => {
            console.log('Branch analytics WebSocket disconnected');
            removeRealtimeIndicators();
        },
        onError: (error) => {
            console.error('Branch analytics WebSocket error:', error);
        }
    });

    // Set up event handlers
    wsClient.on('analytics_update', (data) => {
        // Update charts if they exist
        if (window.revenueChart && data.revenue_data) {
            updateRevenueChart(data.revenue_data);
        }
        if (window.storePerformanceChart && data.store_performance) {
            updateStorePerformanceChart(data.store_performance);
        }
    });

    wsClient.on('sale_created', (data) => {
        // Play notification sound (optional)
        playNotificationSound();

        // Update performance table
        setTimeout(() => {
            loadAnalyticsData();
        }, 2000);
    });

    wsClient.on('performance_alert', ({ data, severity }) => {
        // Handle different types of alerts
        if (data.alert_type === 'low_stock') {
            updateLowStockIndicators();
        }
    });

    // Store reference globally for cleanup
    window.branchWebSocket = wsClient;

    return wsClient;
}

function addRealtimeIndicators() {
    // Add real-time indicators to metric cards
    const metricCards = document.querySelectorAll('.metric-card h3');
    metricCards.forEach(card => {
        if (!card.querySelector('.realtime-indicator')) {
            const indicator = document.createElement('span');
            indicator.className = 'realtime-indicator';
            indicator.innerHTML = 'LIVE';
            card.appendChild(indicator);
        }
    });
}

function removeRealtimeIndicators() {
    const indicators = document.querySelectorAll('.realtime-indicator');
    indicators.forEach(indicator => indicator.remove());
}

function playNotificationSound() {
    // Optional: Play a subtle notification sound
    try {
        const audio = new Audio('data:audio/wav;base64,UklGRnoGAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQoGAACBhYqFbF1fdJivrJBhNjVgodDbq2EcBj+a2/LDciUFLIHO8tiJNwgZaLvt559NEAxQp+PwtmMcBjiR1/LMeSwFJHfH8N2QQAoUXrTp66hVFApGn+L1w20fAzuE0fPTgjMGTH7J8eKZSgwOVo3h8bBnGgU2jdXzzn0vBSF+zO/eizEHLIjU9M18MAUiebX34ao3Bz57x+3cmj0IGFOW2/C2aCIGOIbS89lnKwUtgMrw3IU2Bi+C0fHeijMGGFqR2+7aizgIMXvE8NyGMwcwdM3v44c0BjN5zO3clz8JHlqN2/LgjjYHL3vL7t+DKwQvaL/u5WwgBDmE0PPYeSgENozR8+CKMwYtg8rx3IM0BiJ/y+7ckTUGJHfH8N+GOAkeWI3c8+CJOAkxecfu3rA4Bi55zOvdlj0JIFqN2/LgjjYG');
        audio.volume = 0.1;
        audio.play().catch(() => {}); // Ignore play errors
    } catch (e) {
        // Ignore audio errors
    }
}

function updateLowStockIndicators() {
    // Update low stock count and add visual indicators
    setTimeout(() => {
        loadAnalyticsData();
    }, 1000);
}

// Cleanup function
function cleanupWebSocket() {
    if (window.branchWebSocket) {
        window.branchWebSocket.disconnect();
        window.branchWebSocket = null;
    }
}

// Auto-cleanup on page unload
window.addEventListener('beforeunload', cleanupWebSocket);

// Export for use in templates
window.BranchAnalyticsWebSocket = BranchAnalyticsWebSocket;
window.initializeWebSocketConnection = initializeWebSocketConnection;
window.cleanupWebSocket = cleanupWebSocket;