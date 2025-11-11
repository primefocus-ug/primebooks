// Dashboard WebSocket Manager
class DashboardWebSocket {
    constructor() {
        this.socket = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        this.reconnectInterval = 5000; // 5 seconds
        this.isConnected = false;
        this.messageHandlers = new Map();
        
        this.init();
    }
    
    init() {
        this.connect();
        this.setupMessageHandlers();
        this.setupConnectionIndicator();
    }
    
    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/inventory/dashboard/`;
        
        try {
            this.socket = new WebSocket(wsUrl);
            
            this.socket.onopen = (event) => {
                console.log('Dashboard WebSocket connected');
                this.isConnected = true;
                this.reconnectAttempts = 0;
                this.updateConnectionStatus(true);
                this.requestInitialData();
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
                console.log('Dashboard WebSocket disconnected');
                this.isConnected = false;
                this.updateConnectionStatus(false);
                this.handleReconnect();
            };
            
            this.socket.onerror = (error) => {
                console.error('Dashboard WebSocket error:', error);
                this.updateConnectionStatus(false);
            };
            
        } catch (error) {
            console.error('Error creating WebSocket connection:', error);
            this.handleReconnect();
        }
    }
    
    handleReconnect() {
        if (this.reconnectAttempts < this.maxReconnectAttempts) {
            this.reconnectAttempts++;
            console.log(`Attempting to reconnect... (${this.reconnectAttempts}/${this.maxReconnectAttempts})`);
            
            setTimeout(() => {
                this.connect();
            }, this.reconnectInterval);
        } else {
            console.error('Max reconnection attempts reached');
            this.showConnectionError();
        }
    }
    
    handleMessage(data) {
        const handler = this.messageHandlers.get(data.type);
        if (handler) {
            handler(data.data);
        } else {
            console.warn('No handler for message type:', data.type);
        }
    }
    
    setupMessageHandlers() {
        this.messageHandlers.set('dashboard_stats', (data) => {
            this.updateDashboardStats(data);
        });
        
        this.messageHandlers.set('recent_movements', (data) => {
            this.updateRecentMovements(data);
        });
        
        this.messageHandlers.set('top_products', (data) => {
            this.updateTopProducts(data);
        });
        
        this.messageHandlers.set('stock_alerts', (data) => {
            this.updateStockAlerts(data);
        });
        
        this.messageHandlers.set('dashboard_update', (data) => {
            this.refreshDashboard();
            this.showNotification('Dashboard updated', 'info');
        });
        
        this.messageHandlers.set('stock_movement_created', (data) => {
            this.addNewMovement(data);
            this.showNotification(`New ${data.movement_type_display}: ${data.product_name}`, 'success');
        });
        
        this.messageHandlers.set('stock_alert', (data) => {
            this.handleStockAlert(data);
        });
        
        this.messageHandlers.set('low_stock_alert', (data) => {
            this.showStockAlert(data, 'warning');
        });
        
        this.messageHandlers.set('out_of_stock_alert', (data) => {
            this.showStockAlert(data, 'danger');
        });
    }
    
    requestInitialData() {
        if (this.isConnected) {
            this.send({ type: 'refresh_dashboard' });
        }
    }
    
    send(message) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(message));
        } else {
            console.warn('WebSocket not connected, cannot send message');
        }
    }
    
    updateDashboardStats(data) {
        // Update stat cards
        $('#total-products-count').text(data.total_products || 0);
        $('#total-categories-count').text(data.total_categories || 0);
        $('#total-suppliers-count').text(data.total_suppliers || 0);
        $('#stock-value-amount').text(`UGX ${Number(data.stock_value || 0).toLocaleString()}`);
        
        // Update alert counts
        this.updateAlertCounts(data.low_stock_items || 0, data.out_of_stock_items || 0);
        
        // Update chart if exists
        if (window.stockStatusChart && data.total_products) {
            const inStock = data.total_products - data.low_stock_items - data.out_of_stock_items;
            window.stockStatusChart.data.datasets[0].data = [
                inStock,
                data.low_stock_items,
                data.out_of_stock_items
            ];
            window.stockStatusChart.update('none');
        }
        
        // Update timestamp
        const timestamp = new Date(data.timestamp).toLocaleString();
        $('#last-updated').text(`Last updated: ${timestamp}`);
    }
    
    updateAlertCounts(lowStock, outOfStock) {
        const $lowStockCard = $('.low-stock-alert');
        const $outOfStockCard = $('.out-of-stock-alert');
        
        if (lowStock > 0) {
            $lowStockCard.find('.alert-count').text(lowStock);
            $lowStockCard.show();
        } else {
            $lowStockCard.hide();
        }
        
        if (outOfStock > 0) {
            $outOfStockCard.find('.alert-count').text(outOfStock);
            $outOfStockCard.show();
        } else {
            $outOfStockCard.hide();
        }
    }
    
    updateRecentMovements(movements) {
        const $tbody = $('#recent-movements-table tbody');
        $tbody.empty();
        
        if (movements.length === 0) {
            $tbody.append(`
                <tr>
                    <td colspan="6" class="text-center text-muted">
                        <i class="fas fa-exchange-alt fa-2x mb-2"></i>
                        <p>No recent movements</p>
                    </td>
                </tr>
            `);
            return;
        }
        
        movements.forEach(movement => {
            const badgeClass = this.getMovementBadgeClass(movement.movement_type);
            const quantityClass = this.getQuantityClass(movement.movement_type);
            const quantityPrefix = this.getQuantityPrefix(movement.movement_type);
            
            const row = `
                <tr>
                    <td>${new Date(movement.created_at).toLocaleString()}</td>
                    <td>
                        <strong>${movement.product_name}</strong><br>
                        <small class="text-muted">${movement.product_sku}</small>
                    </td>
                    <td>
                        <span class="badge ${badgeClass}">${movement.movement_type_display}</span>
                    </td>
                    <td>
                        <span class="${quantityClass}">${quantityPrefix}${movement.quantity}</span>
                        ${movement.unit_of_measure}
                    </td>
                    <td>${movement.store_name}</td>
                    <td>${movement.created_by}</td>
                </tr>
            `;
            $tbody.append(row);
        });
    }
    
    updateTopProducts(products) {
        const $container = $('#top-products-list');
        $container.empty();
        
        if (products.length === 0) {
            $container.append(`
                <div class="text-center text-muted">
                    <i class="fas fa-inbox fa-3x mb-3"></i>
                    <p>No product activity yet</p>
                </div>
            `);
            return;
        }
        
        products.forEach(product => {
            const item = `
                <div class="list-group-item d-flex justify-content-between align-items-center border-0 px-0">
                    <div>
                        <h6 class="mb-1">${product.name}</h6>
                        <small class="text-muted">${product.sku}</small>
                    </div>
                    <span class="badge bg-primary rounded-pill">${product.total_movements} movements</span>
                </div>
            `;
            $container.append(item);
        });
    }
    
    addNewMovement(movement) {
        const $tbody = $('#recent-movements-table tbody');
        const badgeClass = this.getMovementBadgeClass(movement.movement_type);
        const quantityClass = this.getQuantityClass(movement.movement_type);
        const quantityPrefix = this.getQuantityPrefix(movement.movement_type);
        
        const row = `
            <tr class="table-success animate-fade-in">
                <td>${new Date(movement.created_at).toLocaleString()}</td>
                <td>
                    <strong>${movement.product_name}</strong><br>
                    <small class="text-muted">${movement.product_sku}</small>
                </td>
                <td>
                    <span class="badge ${badgeClass}">${movement.movement_type_display}</span>
                </td>
                <td>
                    <span class="${quantityClass}">${quantityPrefix}${movement.quantity}</span>
                    ${movement.unit_of_measure}
                </td>
                <td>${movement.store_name}</td>
                <td>${movement.created_by}</td>
            </tr>
        `;
        
        // Add to top and remove highlight after animation
        $tbody.prepend(row);
        setTimeout(() => {
            $tbody.find('tr:first').removeClass('table-success');
        }, 2000);
        
        // Keep only latest 10 movements
        $tbody.find('tr:gt(9)').remove();
    }
    
    handleStockAlert(data) {
        if (data.alert_type === 'low_stock') {
            this.showStockAlert(data, 'warning');
        } else if (data.alert_type === 'out_of_stock') {
            this.showStockAlert(data, 'danger');
        }
    }
    
    showStockAlert(data, type) {
        const icon = type === 'danger' ? 'times-circle' : 'exclamation-triangle';
        const title = type === 'danger' ? 'Out of Stock' : 'Low Stock';
        const message = `${data.product_name} at ${data.store_name}`;
        
        this.showNotification(`${title}: ${message}`, type, icon);
        
        // Update alert counters
        this.send({ type: 'get_alerts' });
    }
    
    showNotification(message, type = 'info', icon = null) {
        const iconClass = icon || this.getNotificationIcon(type);
        const alertClass = `alert-${type}`;
        
        const notification = `
            <div class="alert ${alertClass} alert-dismissible fade show animate-slide-in" role="alert">
                <i class="fas fa-${iconClass} me-2"></i>
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;
        
        $('#notifications-container').append(notification);
        
        // Auto-dismiss after 5 seconds
        setTimeout(() => {
            $('#notifications-container .alert:first').alert('close');
        }, 5000);
    }
    
    refreshDashboard() {
        if (this.isConnected) {
            this.send({ type: 'refresh_dashboard' });
            this.send({ type: 'get_recent_movements' });
            this.send({ type: 'get_top_products' });
        }
    }
    
    setupConnectionIndicator() {
        // Add connection status indicator to the page
        if ($('#ws-status').length === 0) {
            $('body').prepend(`
                <div id="ws-status" class="position-fixed top-0 end-0 p-2" style="z-index: 9999;">
                    <div class="badge bg-secondary">
                        <i class="fas fa-circle me-1"></i>
                        <span class="status-text">Connecting...</span>
                    </div>
                </div>
            `);
        }
    }
    
    updateConnectionStatus(connected) {
        const $status = $('#ws-status');
        const $badge = $status.find('.badge');
        const $text = $status.find('.status-text');
        const $icon = $status.find('i');
        
        if (connected) {
            $badge.removeClass('bg-danger bg-warning bg-secondary').addClass('bg-success');
            $icon.removeClass('fa-times fa-exclamation-triangle fa-circle').addClass('fa-circle');
            $text.text('Connected');
            
            // Hide after 3 seconds
            setTimeout(() => {
                $status.fadeOut();
            }, 3000);
        } else {
            $badge.removeClass('bg-success bg-secondary').addClass('bg-danger');
            $icon.removeClass('fa-circle fa-exclamation-triangle').addClass('fa-times');
            $text.text('Disconnected');
            $status.show();
        }
    }
    
    showConnectionError() {
        this.showNotification('Connection lost. Please refresh the page.', 'danger', 'exclamation-triangle');
    }
    
    // Utility methods
    getMovementBadgeClass(type) {
        const classes = {
            'PURCHASE': 'bg-success',
            'SALE': 'bg-primary',
            'RETURN': 'bg-info',
            'ADJUSTMENT': 'bg-warning',
            'TRANSFER_IN': 'bg-success',
            'TRANSFER_OUT': 'bg-secondary'
        };
        return classes[type] || 'bg-secondary';
    }
    
    getQuantityClass(type) {
        const inTypes = ['PURCHASE', 'RETURN', 'TRANSFER_IN'];
        return inTypes.includes(type) ? 'text-success' : 'text-danger';
    }
    
    getQuantityPrefix(type) {
        const inTypes = ['PURCHASE', 'RETURN', 'TRANSFER_IN'];
        return inTypes.includes(type) ? '+' : '-';
    }
    
    getNotificationIcon(type) {
        const icons = {
            'success': 'check-circle',
            'danger': 'exclamation-triangle',
            'warning': 'exclamation-triangle',
            'info': 'info-circle'
        };
        return icons[type] || 'info-circle';
    }
    
    // Public methods
    disconnect() {
        if (this.socket) {
            this.socket.close();
        }
    }
    
    requestRefresh() {
        this.refreshDashboard();
    }
}

// Import Progress WebSocket Manager
class ImportProgressWebSocket {
    constructor(sessionId) {
        this.sessionId = sessionId;
        this.socket = null;
        this.isConnected = false;
        this.messageHandlers = new Map();
        
        this.init();
    }
    
    init() {
        this.connect();
        this.setupMessageHandlers();
    }
    
    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/inventory/import/${this.sessionId}/`;
        
        try {
            this.socket = new WebSocket(wsUrl);
            
            this.socket.onopen = () => {
                console.log('Import progress WebSocket connected');
                this.isConnected = true;
                this.send({ type: 'get_status' });
            };
            
            this.socket.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    this.handleMessage(data);
                } catch (error) {
                    console.error('Error parsing WebSocket message:', error);
                }
            };
            
            this.socket.onclose = () => {
                console.log('Import progress WebSocket disconnected');
                this.isConnected = false;
            };
            
            this.socket.onerror = (error) => {
                console.error('Import progress WebSocket error:', error);
            };
            
        } catch (error) {
            console.error('Error creating import WebSocket connection:', error);
        }
    }
    
    setupMessageHandlers() {
        this.messageHandlers.set('import_status', (data) => {
            this.updateImportStatus(data);
        });
        
        this.messageHandlers.set('progress_update', (data) => {
            this.updateProgress(data);
        });
        
        this.messageHandlers.set('log_added', (data) => {
            this.addLogEntry(data);
        });
        
        this.messageHandlers.set('import_completed', (data) => {
            this.handleImportCompleted(data);
        });
        
        this.messageHandlers.set('import_failed', (data) => {
            this.handleImportFailed(data);
        });
    }
    
    handleMessage(data) {
        const handler = this.messageHandlers.get(data.type);
        if (handler) {
            handler(data.data);
        }
    }
    
    send(message) {
        if (this.socket && this.socket.readyState === WebSocket.OPEN) {
            this.socket.send(JSON.stringify(message));
        }
    }
    
    updateImportStatus(data) {
        // Update progress bar
        const progress = data.total_rows > 0 ? (data.processed_rows / data.total_rows) * 100 : 0;
        $('#import-progress').css('width', `${progress}%`).attr('aria-valuenow', progress);
        $('#import-progress-text').text(`${Math.round(progress)}%`);
        
        // Update statistics
        $('#total-rows').text(data.total_rows);
        $('#processed-rows').text(data.processed_rows);
        $('#created-count').text(data.created_count);
        $('#updated-count').text(data.updated_count);
        $('#skipped-count').text(data.skipped_count);
        $('#error-count').text(data.error_count);
        $('#success-rate').text(`${Math.round(data.success_rate)}%`);
        
        // Update status badge
        this.updateStatusBadge(data.status);
    }
    
    updateProgress(data) {
        this.updateImportStatus(data);
    }
    
    addLogEntry(data) {
        const $logContainer = $('#import-logs');
        const levelClass = this.getLogLevelClass(data.level);
        const timestamp = new Date(data.timestamp).toLocaleString();
        
        const logEntry = `
            <div class="alert ${levelClass} py-2 mb-1 animate-fade-in">
                <small class="text-muted">${timestamp}</small>
                ${data.row_number ? `<span class="badge bg-secondary ms-2">Row ${data.row_number}</span>` : ''}
                <div>${data.message}</div>
            </div>
        `;
        
        $logContainer.prepend(logEntry);
        
        // Keep only latest 50 log entries
        $logContainer.find('.alert:gt(49)').remove();
        
        // Auto-scroll to top
        $logContainer.scrollTop(0);
    }
    
    handleImportCompleted(data) {
        this.updateImportStatus(data);
        $('#import-status').removeClass('badge-warning').addClass('badge-success').text('Completed');
        
        // Show completion message
        this.showMessage('Import completed successfully!', 'success');
        
        // Enable refresh button
        $('#refresh-dashboard-btn').prop('disabled', false);
    }
    
    handleImportFailed(data) {
        $('#import-status').removeClass('badge-warning').addClass('badge-danger').text('Failed');
        
        // Show error message
        this.showMessage(`Import failed: ${data.error_message}`, 'danger');
    }
    
    updateStatusBadge(status) {
        const $badge = $('#import-status');
        $badge.removeClass('badge-warning badge-success badge-danger badge-secondary');
        
        switch (status) {
            case 'pending':
                $badge.addClass('badge-secondary').text('Pending');
                break;
            case 'processing':
                $badge.addClass('badge-warning').text('Processing');
                break;
            case 'completed':
                $badge.addClass('badge-success').text('Completed');
                break;
            case 'failed':
                $badge.addClass('badge-danger').text('Failed');
                break;
        }
    }
    
    getLogLevelClass(level) {
        const classes = {
            'info': 'alert-info',
            'warning': 'alert-warning',
            'error': 'alert-danger',
            'success': 'alert-success'
        };
        return classes[level] || 'alert-info';
    }
    
    showMessage(message, type) {
        const alertClass = `alert-${type}`;
        const alert = `
            <div class="alert ${alertClass} alert-dismissible fade show" role="alert">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;
        
        $('#import-messages').append(alert);
    }
    
    disconnect() {
        if (this.socket) {
            this.socket.close();
        }
    }
}

// Initialize WebSocket connections when document is ready
$(document).ready(function() {
    // Initialize dashboard WebSocket
    if (typeof window.dashboardWS === 'undefined') {
        window.dashboardWS = new DashboardWebSocket();
    }
    
    // Add manual refresh functionality
    $('#refresh-dashboard').on('click', function() {
        window.dashboardWS.requestRefresh();
        $(this).prop('disabled', true);
        setTimeout(() => {
            $(this).prop('disabled', false);
        }, 2000);
    });
    
    // Add notifications container if it doesn't exist
    if ($('#notifications-container').length === 0) {
        $('body').prepend('<div id="notifications-container" class="position-fixed top-0 start-50 translate-middle-x" style="z-index: 9998; margin-top: 20px;"></div>');
    }
});

// Clean up on page unload
$(window).on('beforeunload', function() {
    if (window.dashboardWS) {
        window.dashboardWS.disconnect();
    }
    if (window.importProgressWS) {
        window.importProgressWS.disconnect();
    }
});

// CSS animations
const style = document.createElement('style');
style.textContent = `
    .animate-fade-in {
        animation: fadeIn 0.5s ease-in;
    }
    
    .animate-slide-in {
        animation: slideIn 0.3s ease-out;
    }
    
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    
    @keyframes slideIn {
        from { transform: translateY(-20px); opacity: 0; }
        to { transform: translateY(0); opacity: 1; }
    }
`;
document.head.appendChild(style);