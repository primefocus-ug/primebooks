class InventoryWebSocketManager {
    constructor() {
        this.connections = new Map();
        this.reconnectAttempts = new Map();
        this.maxReconnectAttempts = 5;
        this.reconnectDelay = 1000; // Start with 1 second
        this.maxReconnectDelay = 30000; // Max 30 seconds
    }

    /**
     * Connect to a WebSocket endpoint
     */
    connect(name, url, options = {}) {
        if (this.connections.has(name)) {
            console.warn(`WebSocket connection '${name}' already exists`);
            return this.connections.get(name);
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}${url}`;

        console.log(`Connecting to WebSocket: ${name} at ${wsUrl}`);

        const socket = new WebSocket(wsUrl);
        const connection = {
            socket: socket,
            name: name,
            url: wsUrl,
            options: options,
            isConnected: false,
            reconnectTimer: null
        };

        this.setupEventHandlers(connection);
        this.connections.set(name, connection);
        this.reconnectAttempts.set(name, 0);

        return connection;
    }

    /**
     * Setup WebSocket event handlers
     */
    setupEventHandlers(connection) {
        const { socket, name, options } = connection;

        socket.onopen = (event) => {
            console.log(`WebSocket '${name}' connected`);
            connection.isConnected = true;
            this.reconnectAttempts.set(name, 0);

            if (options.onOpen) {
                options.onOpen(event);
            }

            // Send initial message if specified
            if (options.initialMessage) {
                this.send(name, options.initialMessage);
            }
        };

        socket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                console.log(`WebSocket '${name}' message:`, data);

                if (options.onMessage) {
                    options.onMessage(data);
                }

                // Handle specific message types
                this.handleMessage(name, data);

            } catch (error) {
                console.error(`Error parsing WebSocket message from '${name}':`, error);
            }
        };

        socket.onclose = (event) => {
            console.log(`WebSocket '${name}' closed:`, event.code, event.reason);
            connection.isConnected = false;

            if (options.onClose) {
                options.onClose(event);
            }

            // Attempt to reconnect if not explicitly closed
            if (event.code !== 1000 && options.autoReconnect !== false) {
                this.scheduleReconnect(name);
            }
        };

        socket.onerror = (error) => {
            console.error(`WebSocket '${name}' error:`, error);

            if (options.onError) {
                options.onError(error);
            }
        };
    }

    /**
     * Handle incoming WebSocket messages
     */
    handleMessage(connectionName, data) {
        const { type } = data;

        // Dispatch custom events for different message types
        const eventName = `websocket:${connectionName}:${type}`;
        const customEvent = new CustomEvent(eventName, { detail: data });
        document.dispatchEvent(customEvent);
    }

    /**
     * Send message through WebSocket
     */
    send(name, message) {
        const connection = this.connections.get(name);

        if (!connection) {
            console.error(`WebSocket connection '${name}' not found`);
            return false;
        }

        if (!connection.isConnected) {
            console.error(`WebSocket connection '${name}' is not connected`);
            return false;
        }

        try {
            const messageStr = typeof message === 'string' ? message : JSON.stringify(message);
            connection.socket.send(messageStr);
            return true;
        } catch (error) {
            console.error(`Error sending message through WebSocket '${name}':`, error);
            return false;
        }
    }

    /**
     * Schedule reconnection attempt
     */
    scheduleReconnect(name) {
        const attempts = this.reconnectAttempts.get(name) || 0;

        if (attempts >= this.maxReconnectAttempts) {
            console.error(`Max reconnection attempts reached for WebSocket '${name}'`);
            return;
        }

        const delay = Math.min(this.reconnectDelay * Math.pow(2, attempts), this.maxReconnectDelay);
        console.log(`Scheduling reconnection for '${name}' in ${delay}ms (attempt ${attempts + 1})`);

        const connection = this.connections.get(name);
        if (connection.reconnectTimer) {
            clearTimeout(connection.reconnectTimer);
        }

        connection.reconnectTimer = setTimeout(() => {
            this.reconnect(name);
        }, delay);
    }

    /**
     * Reconnect to WebSocket
     */
    reconnect(name) {
        const connection = this.connections.get(name);
        if (!connection) {
            return;
        }

        console.log(`Attempting to reconnect WebSocket '${name}'`);
        this.reconnectAttempts.set(name, this.reconnectAttempts.get(name) + 1);

        // Close existing connection
        if (connection.socket) {
            connection.socket.close();
        }

        // Create new connection
        const newSocket = new WebSocket(connection.url);
        connection.socket = newSocket;
        connection.isConnected = false;

        this.setupEventHandlers(connection);
    }

    /**
     * Disconnect WebSocket
     */
    disconnect(name) {
        const connection = this.connections.get(name);
        if (!connection) {
            return;
        }

        console.log(`Disconnecting WebSocket '${name}'`);

        if (connection.reconnectTimer) {
            clearTimeout(connection.reconnectTimer);
        }

        if (connection.socket) {
            connection.socket.close(1000, 'Manually disconnected');
        }

        this.connections.delete(name);
        this.reconnectAttempts.delete(name);
    }

    /**
     * Disconnect all WebSockets
     */
    disconnectAll() {
        for (const name of this.connections.keys()) {
            this.disconnect(name);
        }
    }

    /**
     * Check if WebSocket is connected
     */
    isConnected(name) {
        const connection = this.connections.get(name);
        return connection && connection.isConnected;
    }

    /**
     * Get connection status
     */
    getStatus(name) {
        const connection = this.connections.get(name);
        if (!connection) {
            return 'not_found';
        }

        switch (connection.socket.readyState) {
            case WebSocket.CONNECTING:
                return 'connecting';
            case WebSocket.OPEN:
                return 'open';
            case WebSocket.CLOSING:
                return 'closing';
            case WebSocket.CLOSED:
                return 'closed';
            default:
                return 'unknown';
        }
    }
}

// Create global instance
window.inventoryWS = new InventoryWebSocketManager();

// Import Progress WebSocket Handler
class ImportProgressHandler {
    constructor(sessionId) {
        this.sessionId = sessionId;
        this.connectionName = `import_${sessionId}`;
        this.progressBar = null;
        this.statusElement = null;
        this.messageElement = null;
        this.logContainer = null;
    }

    connect() {
        const url = `/ws/inventory/import/${this.sessionId}/`;

        window.inventoryWS.connect(this.connectionName, url, {
            onOpen: () => {
                console.log('Import progress WebSocket connected');
                this.updateStatus('Connected', 'info');
            },
            onMessage: (data) => {
                this.handleMessage(data);
            },
            onClose: () => {
                console.log('Import progress WebSocket disconnected');
                this.updateStatus('Disconnected', 'warning');
            },
            onError: (error) => {
                console.error('Import progress WebSocket error:', error);
                this.updateStatus('Connection Error', 'danger');
            },
            autoReconnect: true
        });

        // Request initial status
        setTimeout(() => {
            this.requestStatus();
        }, 1000);
    }

    handleMessage(data) {
        switch (data.type) {
            case 'import_status':
                this.updateProgress(data.data);
                break;
            case 'progress_update':
                this.updateProgress(data.data);
                break;
            case 'import_completed':
                this.handleCompletion(data.data);
                break;
            case 'import_error':
                this.handleError(data.data);
                break;
            case 'import_log_update':
                this.addLogEntry(data.data);
                break;
        }
    }

    updateProgress(data) {
        const { progress_percentage, status, processed_rows, total_rows } = data;

        if (this.progressBar) {
            this.progressBar.style.width = `${progress_percentage || 0}%`;
            this.progressBar.setAttribute('aria-valuenow', progress_percentage || 0);
            this.progressBar.textContent = `${Math.round(progress_percentage || 0)}%`;
        }

        if (this.statusElement) {
            this.statusElement.textContent = status || 'Processing';
        }

        if (this.messageElement && processed_rows && total_rows) {
            this.messageElement.textContent = `Processed ${processed_rows} of ${total_rows} rows`;
        }
    }

    handleCompletion(data) {
        this.updateStatus('Import Completed', 'success');
        this.updateProgress({ progress_percentage: 100 });

        if (this.messageElement) {
            this.messageElement.innerHTML = `
                <strong>Import completed successfully!</strong><br>
                ${data.summary || ''}
            `;
        }

        // Show success notification
        this.showNotification('Import completed successfully!', 'success');

        // Refresh page or redirect after a delay
        setTimeout(() => {
            if (confirm('Import completed! Refresh the page to see results?')) {
                window.location.reload();
            }
        }, 2000);
    }

    handleError(data) {
        this.updateStatus('Import Failed', 'danger');

        if (this.messageElement) {
            this.messageElement.innerHTML = `
                <strong>Import failed:</strong><br>
                ${data.error || data.message || 'Unknown error occurred'}
            `;
        }

        this.showNotification('Import failed. Please check the logs for details.', 'error');
    }

    addLogEntry(data) {
        if (!this.logContainer) {
            return;
        }

        const logEntry = document.createElement('div');
        logEntry.className = `alert alert-${this.getLogLevelClass(data.level)} alert-sm mb-1`;

        const timestamp = new Date(data.timestamp).toLocaleTimeString();
        logEntry.innerHTML = `
            <small class="text-muted">[${timestamp}]</small>
            <strong>${data.level.toUpperCase()}:</strong>
            ${data.message}
            ${data.row_number ? ` (Row ${data.row_number})` : ''}
        `;

        this.logContainer.appendChild(logEntry);
        this.logContainer.scrollTop = this.logContainer.scrollHeight;

        // Limit log entries to prevent memory issues
        while (this.logContainer.children.length > 100) {
            this.logContainer.removeChild(this.logContainer.firstChild);
        }
    }

    getLogLevelClass(level) {
        const classes = {
            'info': 'info',
            'warning': 'warning',
            'error': 'danger',
            'success': 'success'
        };
        return classes[level] || 'secondary';
    }

    updateStatus(status, type) {
        if (this.statusElement) {
            this.statusElement.textContent = status;
            this.statusElement.className = `badge badge-${type}`;
        }
    }

    showNotification(message, type) {
        // You can integrate with your notification system here
        if (typeof toastr !== 'undefined') {
            toastr[type](message);
        } else if (typeof Swal !== 'undefined') {
            Swal.fire({
                title: type === 'success' ? 'Success' : 'Error',
                text: message,
                icon: type === 'success' ? 'success' : 'error'
            });
        } else {
            alert(message);
        }
    }

    requestStatus() {
        window.inventoryWS.send(this.connectionName, {
            type: 'get_status'
        });
    }

    cancelImport() {
        if (confirm('Are you sure you want to cancel this import?')) {
            window.inventoryWS.send(this.connectionName, {
                type: 'cancel_import'
            });
        }
    }

    disconnect() {
        window.inventoryWS.disconnect(this.connectionName);
    }

    // Initialize DOM elements
    init(elements = {}) {
        this.progressBar = elements.progressBar || document.getElementById('import-progress-bar');
        this.statusElement = elements.statusElement || document.getElementById('import-status');
        this.messageElement = elements.messageElement || document.getElementById('import-message');
        this.logContainer = elements.logContainer || document.getElementById('import-logs');

        this.connect();
    }
}

// Dashboard WebSocket Handler
class DashboardHandler {
    constructor() {
        this.connectionName = 'dashboard';
        this.statsContainer = null;
        this.alertsContainer = null;
        this.movementsContainer = null;
    }

    connect() {
        window.inventoryWS.connect(this.connectionName, '/ws/inventory/dashboard/', {
            onOpen: () => {
                console.log('Dashboard WebSocket connected');
                this.requestDashboardData();
            },
            onMessage: (data) => {
                this.handleMessage(data);
            },
            autoReconnect: true,
            initialMessage: {
                type: 'get_dashboard_data'
            }
        });
    }

    handleMessage(data) {
        switch (data.type) {
            case 'dashboard_data':
                this.updateDashboardStats(data.data);
                break;
            case 'stock_alerts':
                this.updateStockAlerts(data.data);
                break;
            case 'low_stock_alert':
                this.handleLowStockAlert(data.data);
                break;
            case 'movement_notification':
                this.handleMovementNotification(data.data);
                break;
            case 'stock_update':
                this.handleStockUpdate(data.data);
                break;
            case 'dashboard_update':
                this.updateDashboardStats(data.data);
                break;
            case 'efris_status_update':
                this.handleEfrisUpdate(data.data);
                break;
            case 'bulk_operation_completed':
                this.handleBulkOperation(data.data);
                break;
        }
    }

    updateDashboardStats(stats) {
        // Update product stats
        this.updateElement('total-products', stats.products?.total);
        this.updateElement('low-stock-count', stats.products?.low_stock);
        this.updateElement('out-of-stock-count', stats.products?.out_of_stock);

        // Update movement stats
        this.updateElement('movements-today', stats.movements?.today);
        this.updateElement('movements-week', stats.movements?.this_week);

        // Update stock value
        if (stats.value?.total_stock_value) {
            this.updateElement('stock-value', this.formatCurrency(stats.value.total_stock_value));
        }

        // Update timestamp
        if (stats.timestamp) {
            this.updateElement('last-updated', this.formatTimestamp(stats.timestamp));
        }
    }

    updateStockAlerts(alerts) {
        if (!this.alertsContainer) return;

        this.alertsContainer.innerHTML = '';

        if (!alerts || alerts.length === 0) {
            this.alertsContainer.innerHTML = '<p class="text-muted">No stock alerts</p>';
            return;
        }

        alerts.forEach(alert => {
            const alertElement = this.createAlertElement(alert);
            this.alertsContainer.appendChild(alertElement);
        });
    }

    createAlertElement(alert) {
        const div = document.createElement('div');
        div.className = `alert alert-${alert.status === 'critical' ? 'danger' : 'warning'} alert-sm mb-2`;

                        div.innerHTML = `
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <strong>${alert.product_name}</strong> (${alert.product_sku})<br>
                    <small>Store: ${alert.store_name}</small>
                </div>
                <div class="text-right">
                    <span class="badge badge-${alert.status === 'critical' ? 'danger' : 'warning'}">
                        ${alert.current_stock} / ${alert.reorder_level}
                    </span>
                </div>
            </div>
        `;

        return div;
    }

    handleLowStockAlert(data) {
        // Show notification for new low stock alerts
        this.showNotification(`Low stock alert: ${data.product_name} at ${data.store_name}`, 'warning');

        // Update alerts display
        this.requestStockAlerts();
    }

    handleMovementNotification(data) {
        // Add to recent movements if container exists
        if (this.movementsContainer) {
            const movementElement = this.createMovementElement(data);
            this.movementsContainer.insertBefore(movementElement, this.movementsContainer.firstChild);

            // Keep only latest 10 movements
            while (this.movementsContainer.children.length > 10) {
                this.movementsContainer.removeChild(this.movementsContainer.lastChild);
            }
        }

        // Show notification for significant movements
        if (Math.abs(data.quantity) >= 10) {
            this.showNotification(`Stock movement: ${data.movement_type_display} of ${data.quantity} ${data.unit_of_measure} - ${data.product_name}`, 'info');
        }
    }

    createMovementElement(movement) {
        const div = document.createElement('div');
        div.className = 'list-group-item list-group-item-action py-2';

        const timeAgo = this.formatTimeAgo(new Date(movement.created_at));
        const isInbound = ['PURCHASE', 'RETURN', 'TRANSFER_IN'].includes(movement.movement_type);
        const quantityClass = isInbound ? 'text-success' : 'text-danger';
        const quantityIcon = isInbound ? '+' : '-';

        div.innerHTML = `
            <div class="d-flex justify-content-between align-items-start">
                <div class="flex-grow-1">
                    <h6 class="mb-1">${movement.product_name}</h6>
                    <p class="mb-1 small text-muted">${movement.movement_type_display} at ${movement.store_name}</p>
                    <small class="text-muted">${timeAgo} by ${movement.created_by}</small>
                </div>
                <div class="text-right">
                    <span class="badge badge-pill ${quantityClass.replace('text-', 'badge-')}"">
                        ${quantityIcon}${Math.abs(movement.quantity)} ${movement.unit_of_measure}
                    </span>
                </div>
            </div>
        `;

        return div;
    }

    handleStockUpdate(data) {
        // Show notification for significant stock changes
        if (data.action === 'updated' && Math.abs(data.new_quantity - data.old_quantity) >= 5) {
            const change = data.new_quantity - data.old_quantity;
            const changeText = change > 0 ? `increased by ${change}` : `decreased by ${Math.abs(change)}`;
            this.showNotification(`Stock ${changeText}: ${data.product_name} at ${data.store_name}`, 'info');
        }
    }

    handleEfrisUpdate(data) {
        this.showNotification(`EFRIS status updated: ${data.product_name} - ${data.efris_status}`, 'info');
    }

    handleBulkOperation(data) {
        this.showNotification(data.message || `Bulk operation completed. ${data.success_count} items affected.`, 'success');
    }

    updateElement(id, value) {
        const element = document.getElementById(id);
        if (element && value !== undefined && value !== null) {
            element.textContent = value;
        }
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'UGX',
            minimumFractionDigits: 0,
            maximumFractionDigits: 0
        }).format(amount);
    }

    formatTimestamp(timestamp) {
        return new Date(timestamp).toLocaleString();
    }

    formatTimeAgo(date) {
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);

        if (diffMins < 1) return 'just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;
        return date.toLocaleDateString();
    }

    showNotification(message, type) {
        // Integration with notification systems
        if (typeof toastr !== 'undefined') {
            toastr[type === 'warning' ? 'warning' : type === 'error' ? 'error' : 'info'](message);
        } else {
            // Fallback to browser notification
            if ('Notification' in window && Notification.permission === 'granted') {
                new Notification('Inventory Update', {
                    body: message,
                    icon: '/static/images/inventory-icon.png'
                });
            }
        }
    }

    requestDashboardData() {
        window.inventoryWS.send(this.connectionName, {
            type: 'get_dashboard_data'
        });
    }

    requestStockAlerts() {
        window.inventoryWS.send(this.connectionName, {
            type: 'subscribe_alerts'
        });
    }

    init(elements = {}) {
        this.statsContainer = elements.statsContainer || document.getElementById('dashboard-stats');
        this.alertsContainer = elements.alertsContainer || document.getElementById('stock-alerts');
        this.movementsContainer = elements.movementsContainer || document.getElementById('recent-movements');

        this.connect();
    }
}

// Stock Levels WebSocket Handler
class StockLevelsHandler {
    constructor() {
        this.connectionName = 'stock_levels';
        this.tableBody = null;
        this.currentFilter = null;
    }

    connect(storeFilter = null) {
        let url = '/ws/inventory/stock-levels/';
        if (storeFilter) {
            url += `?store=${storeFilter}`;
            this.currentFilter = storeFilter;
        }

        window.inventoryWS.connect(this.connectionName, url, {
            onOpen: () => {
                console.log('Stock levels WebSocket connected');
                this.requestStockLevels();
            },
            onMessage: (data) => {
                this.handleMessage(data);
            },
            autoReconnect: true
        });
    }

    handleMessage(data) {
        switch (data.type) {
            case 'stock_levels':
                this.updateStockLevels(data.data);
                break;
            case 'stock_level_update':
                this.updateSingleStock(data.data);
                break;
        }
    }

    updateStockLevels(stockData) {
        if (!this.tableBody) return;

        this.tableBody.innerHTML = '';

        stockData.forEach(stock => {
            const row = this.createStockRow(stock);
            this.tableBody.appendChild(row);
        });
    }

    updateSingleStock(stock) {
        if (!this.tableBody) return;

        // Find existing row
        const existingRow = this.tableBody.querySelector(`tr[data-stock-id="${stock.id}"]`);

        if (existingRow) {
            // Update existing row
            const newRow = this.createStockRow(stock);
            existingRow.replaceWith(newRow);

            // Highlight the updated row
            newRow.classList.add('table-warning');
            setTimeout(() => {
                newRow.classList.remove('table-warning');
            }, 2000);
        } else {
            // Add new row
            const newRow = this.createStockRow(stock);
            this.tableBody.insertBefore(newRow, this.tableBody.firstChild);

            // Highlight new row
            newRow.classList.add('table-success');
            setTimeout(() => {
                newRow.classList.remove('table-success');
            }, 2000);
        }
    }

    createStockRow(stock) {
        const row = document.createElement('tr');
        row.setAttribute('data-stock-id', stock.id);

        // Determine status class
        let statusClass = 'success';
        let statusText = 'In Stock';

        if (stock.quantity === 0) {
            statusClass = 'danger';
            statusText = 'Out of Stock';
        } else if (stock.quantity <= stock.low_stock_threshold) {
            statusClass = 'warning';
            statusText = 'Low Stock';
        }

        const lastUpdated = stock.last_updated ?
            new Date(stock.last_updated).toLocaleString() : 'Never';

        row.innerHTML = `
            <td>
                <strong>${stock.product_name}</strong><br>
                <small class="text-muted">${stock.product_sku}</small>
            </td>
            <td>${stock.store_name}</td>
            <td class="text-right">
                <span class="badge badge-${statusClass}">${stock.quantity} ${stock.unit_of_measure}</span>
            </td>
            <td class="text-right">${stock.low_stock_threshold} ${stock.unit_of_measure}</td>
            <td>
                <span class="badge badge-${statusClass}">${statusText}</span>
            </td>
            <td class="text-muted small">${lastUpdated}</td>
            <td>
                <div class="btn-group btn-group-sm">
                    <button class="btn btn-outline-primary btn-sm" onclick="adjustStock(${stock.id})">
                        Adjust
                    </button>
                    <button class="btn btn-outline-info btn-sm" onclick="viewHistory(${stock.id})">
                        History
                    </button>
                </div>
            </td>
        `;

        return row;
    }

    filterByStore(storeId) {
        // Disconnect current connection
        window.inventoryWS.disconnect(this.connectionName);

        // Reconnect with new filter
        this.connect(storeId);
    }

    requestStockLevels() {
        window.inventoryWS.send(this.connectionName, {
            type: 'get_stock_levels'
        });
    }

    init(elements = {}) {
        this.tableBody = elements.tableBody || document.querySelector('#stock-levels-table tbody');
        this.connect();
    }
}

// Utility functions for global use
window.adjustStock = function(stockId) {
    // You can implement a modal or redirect to adjustment page
    window.location.href = `/inventory/stock/adjust/?stock_id=${stockId}`;
};

window.viewHistory = function(stockId) {
    // You can implement a modal or redirect to history page
    window.location.href = `/inventory/stock/${stockId}/history/`;
};

// Page-specific initialization
document.addEventListener('DOMContentLoaded', function() {
    // Initialize WebSocket connections based on page
    const page = document.body.getAttribute('data-page');

    switch (page) {
        case 'dashboard':
            const dashboardHandler = new DashboardHandler();
            dashboardHandler.init();
            break;

        case 'stock-levels':
            const stockHandler = new StockLevelsHandler();
            stockHandler.init();

            // Add store filter functionality
            const storeFilter = document.getElementById('store-filter');
            if (storeFilter) {
                storeFilter.addEventListener('change', function() {
                    stockHandler.filterByStore(this.value);
                });
            }
            break;

        case 'import-progress':
            const sessionId = document.body.getAttribute('data-session-id');
            if (sessionId) {
                window.importHandler = new ImportProgressHandler(sessionId);
                window.importHandler.init();
            }
            break;
    }

    // Request notification permission
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
});

// Cleanup on page unload
window.addEventListener('beforeunload', function() {
    window.inventoryWS.disconnectAll();
});

// Export classes for use in other scripts
window.InventoryWebSocketManager = InventoryWebSocketManager;
window.ImportProgressHandler = ImportProgressHandler;
window.DashboardHandler = DashboardHandler;
window.StockLevelsHandler = StockLevelsHandler;