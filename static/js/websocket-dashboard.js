class CompanyDashboardWebSocket {
    constructor(companyId, options = {}) {
        this.companyId = companyId;
        this.options = {
            reconnectInterval: 5000,
            maxReconnectAttempts: 10,
            pingInterval: 30000,
            ...options
        };

        this.ws = null;
        this.reconnectAttempts = 0;
        this.isConnected = false;
        this.pingTimer = null;
        this.reconnectTimer = null;

        this.eventHandlers = {
            'initial_data': this.handleInitialData.bind(this),
            'metrics_update': this.handleMetricsUpdate.bind(this),
            'dashboard_update': this.handleDashboardUpdate.bind(this),
            'branch_update': this.handleBranchUpdate.bind(this),
            'alert': this.handleAlert.bind(this),
            'branch_analytics': this.handleBranchAnalytics.bind(this),
            'performance_update': this.handlePerformanceUpdate.bind(this),
            'error': this.handleError.bind(this),
            'pong': this.handlePong.bind(this)
        };

        this.init();
    }

    init() {
        this.connect();
        this.setupHeartbeat();
        this.bindEvents();
    }

    connect() {
        if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
            return;
        }

        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/company/${this.companyId}/dashboard/`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = this.onOpen.bind(this);
        this.ws.onmessage = this.onMessage.bind(this);
        this.ws.onclose = this.onClose.bind(this);
        this.ws.onerror = this.onError.bind(this);

        this.showConnectionStatus('connecting');
    }

    onOpen(event) {
        console.log('WebSocket connected to company dashboard');
        this.isConnected = true;
        this.reconnectAttempts = 0;
        this.showConnectionStatus('connected');

        // Start ping/pong heartbeat
        this.startHeartbeat();

        // Trigger custom event
        this.dispatchCustomEvent('websocket:connected', { companyId: this.companyId });
    }

    onMessage(event) {
        try {
            const data = JSON.parse(event.data);
            const messageType = data.type;

            if (this.eventHandlers[messageType]) {
                this.eventHandlers[messageType](data);
            } else {
                console.warn('Unknown message type:', messageType, data);
            }

        } catch (error) {
            console.error('Error parsing WebSocket message:', error, event.data);
        }
    }

    onClose(event) {
        console.log('WebSocket connection closed', event.code, event.reason);
        this.isConnected = false;
        this.stopHeartbeat();
        this.showConnectionStatus('disconnected');

        // Attempt to reconnect unless it was a clean close
        if (event.code !== 1000) {
            this.scheduleReconnect();
        }

        this.dispatchCustomEvent('websocket:disconnected', {
            companyId: this.companyId,
            code: event.code,
            reason: event.reason
        });
    }

    onError(event) {
        console.error('WebSocket error:', event);
        this.showConnectionStatus('error');
        this.dispatchCustomEvent('websocket:error', { companyId: this.companyId, error: event });
    }

    scheduleReconnect() {
        if (this.reconnectAttempts >= this.options.maxReconnectAttempts) {
            console.log('Max reconnection attempts reached');
            this.showConnectionStatus('failed');
            return;
        }

        this.reconnectAttempts++;
        const delay = Math.min(this.options.reconnectInterval * this.reconnectAttempts, 30000);

        console.log(`Attempting to reconnect in ${delay}ms (attempt ${this.reconnectAttempts})`);
        this.showConnectionStatus('reconnecting', this.reconnectAttempts);

        this.reconnectTimer = setTimeout(() => {
            this.connect();
        }, delay);
    }

    setupHeartbeat() {
        this.startHeartbeat();
    }

    startHeartbeat() {
        this.stopHeartbeat();
        this.pingTimer = setInterval(() => {
            if (this.isConnected && this.ws.readyState === WebSocket.OPEN) {
                this.send({ type: 'ping', timestamp: new Date().toISOString() });
            }
        }, this.options.pingInterval);
    }

    stopHeartbeat() {
        if (this.pingTimer) {
            clearInterval(this.pingTimer);
            this.pingTimer = null;
        }
    }

    send(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else {
            console.warn('WebSocket not connected, cannot send:', data);
        }
    }

    // Message Handlers
    handleInitialData(data) {
        console.log('Received initial dashboard data:', data.data);
        this.updateDashboardMetrics(data.data);
        this.showToast('Dashboard connected', 'success');
    }

    handleMetricsUpdate(data) {
        console.log('Received metrics update:', data.data);
        this.updateRealTimeMetrics(data.data);
        this.updateLastRefreshTime(data.timestamp);
    }

    handleDashboardUpdate(data) {
        console.log('Dashboard update:', data.data);

        const updateData = data.data;

        switch (updateData.event_type) {
            case 'new_sale':
                this.handleNewSale(updateData);
                break;
            case 'device_activity':
                this.handleDeviceActivity(updateData);
                break;
            case 'branch_action':
                this.handleBranchAction(updateData);
                break;
            case 'employee_joined':
                this.handleEmployeeJoined(updateData);
                break;
            case 'metrics_refresh':
                this.updateDashboardMetrics(updateData);
                break;
            default:
                console.log('Unhandled dashboard update:', updateData);
        }
    }

    handleBranchUpdate(data) {
        console.log('Branch update:', data);
        this.updateBranchInTable(data.branch_id, data.data);
    }

    handleAlert(data) {
        console.log('Alert received:', data);
        this.showAlert(data.alert_type, data.message, data.data);
    }

    handleBranchAnalytics(data) {
        console.log('Branch analytics:', data);
        this.updateBranchAnalyticsModal(data.branch_id, data.data);
    }

    handlePerformanceUpdate(data) {
        console.log('Performance update:', data);
        this.updatePerformanceMetrics(data.data);
    }

    handleError(data) {
        console.error('WebSocket error message:', data.message);
        this.showToast(data.message, 'error');
    }

    handlePong(data) {
        // Heartbeat response - connection is alive
        console.debug('Pong received');
    }

    // Event-specific handlers
    handleNewSale(data) {
        // Update today's sales counter
        this.incrementTodaySales(data.amount);

        // Add to recent activities
        this.addRecentActivity({
            type: 'sale',
            icon: 'bi-currency-dollar',
            description: `Sale of ${this.formatCurrency(data.amount)} at ${data.store_name}`,
            time: 'Just now',
            timestamp: data.timestamp
        });

        // Show notification
        this.showToast(`New sale: ${this.formatCurrency(data.amount)} at ${data.store_name}`, 'success');

        // Trigger chart update if visible
        this.requestChartUpdate();
    }

    handleDeviceActivity(data) {
        this.addRecentActivity({
            type: 'device',
            icon: 'bi-phone',
            description: `${data.user_name} ${data.action.toLowerCase()} at ${data.store_name}`,
            time: 'Just now',
            timestamp: data.timestamp
        });
    }

    handleBranchAction(data) {
        this.showToast(data.message, 'info');
    }

    handleEmployeeJoined(data) {
        this.addRecentActivity({
            type: 'employee',
            icon: 'bi-person-plus',
            description: `${data.user_name} joined the team`,
            time: 'Just now',
            timestamp: data.timestamp
        });

        this.showToast(`${data.user_name} has joined the company`, 'info');
    }

    // UI Update Methods
    updateDashboardMetrics(data) {
        // Update overview cards
        this.updateElement('#total-branches', data.total_branches);
        this.updateElement('#active-branches', data.active_branches);
        this.updateElement('#total-employees', data.total_employees);
        this.updateElement('#active-employees', data.active_employees);

        if (data.total_revenue_30d !== undefined) {
            this.updateElement('#total-revenue', this.formatCurrency(data.total_revenue_30d));
        }

        if (data.total_sales_30d !== undefined) {
            this.updateElement('#total-sales', data.total_sales_30d);
        }
    }

    updateRealTimeMetrics(data) {
        // Update real-time metrics
        if (data.today_revenue !== undefined) {
            this.updateElement('#today-revenue', this.formatCurrency(data.today_revenue));
        }

        if (data.today_sales_count !== undefined) {
            this.updateElement('#today-sales', data.today_sales_count);
        }

        // Update inventory alerts
        if (data.inventory_alerts) {
            this.updateInventoryAlerts(data.inventory_alerts);
        }

        // Update active users
        if (data.active_users_count !== undefined) {
            this.updateElement('#active-users', data.active_users_count);
        }

        // Update recent activities
        if (data.recent_activities) {
            this.updateRecentActivities(data.recent_activities);
        }
    }

    updateBranchInTable(branchId, data) {
        const row = document.querySelector(`tr[data-branch-id="${branchId}"]`);
        if (row) {
            // Update branch-specific data in the table
            if (data.event_type === 'branch_updated') {
                // Update branch name, status, etc.
                const nameCell = row.querySelector('.branch-name');
                if (nameCell && data.branch_name) {
                    nameCell.textContent = data.branch_name;
                }
            }
        }
    }

    updateBranchAnalyticsModal(branchId, data) {
        const modal = document.getElementById('branchAnalyticsModal');
        const modalContent = document.getElementById('branchAnalyticsContent');

        if (modal && modalContent && modal.classList.contains('show')) {
            // Update the modal with new analytics data
            this.renderBranchAnalyticsData(data, modalContent);
        }
    }

    updatePerformanceMetrics(data) {
        // Update overall performance score
        if (data.overall_performance_score !== undefined) {
            this.updateElement('#overall-performance', data.overall_performance_score + '%');

            // Update performance circle if exists
            const circle = document.querySelector('.performance-circle');
            if (circle) {
                circle.style.setProperty('--percentage', data.overall_performance_score);
                const text = circle.querySelector('.performance-text');
                if (text) {
                    text.textContent = data.overall_performance_score + '%';
                }
            }
        }

        // Update top performing branches
        if (data.top_performing_branches) {
            this.updateTopPerformingBranches(data.top_performing_branches);
        }
    }

    updateInventoryAlerts(alerts) {
        const alertsContainer = document.getElementById('inventory-alerts');
        if (alertsContainer) {
            let alertsHtml = '';

            if (alerts.low_stock_items > 0) {
                alertsHtml += `
                    <div class="alert alert-warning d-flex align-items-center" role="alert">
                        <i class="bi bi-exclamation-triangle me-2"></i>
                        <div><strong>${alerts.low_stock_items}</strong> items running low on stock</div>
                    </div>
                `;
            }

            if (alerts.out_of_stock_items > 0) {
                alertsHtml += `
                    <div class="alert alert-danger d-flex align-items-center" role="alert">
                        <i class="bi bi-x-circle me-2"></i>
                        <div><strong>${alerts.out_of_stock_items}</strong> items out of stock</div>
                    </div>
                `;
            }

            alertsContainer.innerHTML = alertsHtml;
        }
    }

    updateRecentActivities(activities) {
        const container = document.getElementById('recent-activities');
        if (!container) return;

        const activitiesHtml = activities.map(activity => `
            <div class="activity-item d-flex align-items-start mb-3">
                <div class="activity-icon me-3">
                    <i class="${this.getActivityIcon(activity.type)} text-primary"></i>
                </div>
                <div class="flex-grow-1">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <span class="text-muted">${activity.description}</span>
                        </div>
                        <small class="text-muted">${this.formatTimeAgo(activity.timestamp)}</small>
                    </div>
                    ${activity.store_name ? `<small class="text-muted"><i class="bi bi-geo-alt me-1"></i>${activity.store_name}</small>` : ''}
                </div>
            </div>
        `).join('');

        container.innerHTML = activitiesHtml;
    }

    addRecentActivity(activity) {
        const container = document.getElementById('recent-activities');
        if (!container) return;

        const activityHtml = `
            <div class="activity-item d-flex align-items-start mb-3 new-activity">
                <div class="activity-icon me-3">
                    <i class="${activity.icon} text-primary"></i>
                </div>
                <div class="flex-grow-1">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <span class="text-muted">${activity.description}</span>
                        </div>
                        <small class="text-muted">${activity.time}</small>
                    </div>
                </div>
            </div>
        `;

        container.insertAdjacentHTML('afterbegin', activityHtml);

        // Highlight new activity
        setTimeout(() => {
            const newActivity = container.querySelector('.new-activity');
            if (newActivity) {
                newActivity.classList.remove('new-activity');
            }
        }, 3000);

        // Remove old activities if too many
        const activities = container.querySelectorAll('.activity-item');
        if (activities.length > 10) {
            activities[activities.length - 1].remove();
        }
    }

    incrementTodaySales(amount) {
        const revenueElement = document.getElementById('today-revenue');
        const salesElement = document.getElementById('today-sales');

        if (revenueElement) {
            const currentRevenue = this.parseFormattedCurrency(revenueElement.textContent);
            const newRevenue = currentRevenue + amount;
            revenueElement.textContent = this.formatCurrency(newRevenue);
        }

        if (salesElement) {
            const currentSales = parseInt(salesElement.textContent) || 0;
            salesElement.textContent = currentSales + 1;
        }
    }

    requestChartUpdate() {
        // Trigger chart updates if they exist
        const event = new CustomEvent('dashboard:updateCharts', {
            detail: { companyId: this.companyId }
        });
        document.dispatchEvent(event);
    }

    // Utility Methods
    updateElement(selector, value) {
        const element = document.querySelector(selector);
        if (element) {
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

    parseFormattedCurrency(text) {
        return parseFloat(text.replace(/[^\d.-]/g, '')) || 0;
    }

    formatTimeAgo(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diffMs = now - date;
        const diffMins = Math.floor(diffMs / 60000);
        const diffHours = Math.floor(diffMs / 3600000);
        const diffDays = Math.floor(diffMs / 86400000);

        if (diffMins < 1) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        return `${diffDays}d ago`;
    }

    getActivityIcon(type) {
        const icons = {
            'sale': 'bi-currency-dollar',
            'device_activity': 'bi-phone',
            'employee': 'bi-person-badge',
            'branch': 'bi-diagram-3',
            'inventory': 'bi-box-seam'
        };
        return icons[type] || 'bi-circle-fill';
    }

    showConnectionStatus(status, attempt = 0) {
        const statusElement = document.getElementById('websocket-status');
        if (!statusElement) return;

        const statusConfig = {
            'connecting': { text: 'Connecting...', class: 'text-warning', icon: 'bi-arrow-repeat' },
            'connected': { text: 'Connected', class: 'text-success', icon: 'bi-wifi' },
            'disconnected': { text: 'Disconnected', class: 'text-secondary', icon: 'bi-wifi-off' },
            'reconnecting': { text: `Reconnecting... (${attempt})`, class: 'text-warning', icon: 'bi-arrow-clockwise' },
            'error': { text: 'Connection Error', class: 'text-danger', icon: 'bi-exclamation-triangle' },
            'failed': { text: 'Connection Failed', class: 'text-danger', icon: 'bi-x-circle' }
        };

        const config = statusConfig[status] || statusConfig['disconnected'];

        statusElement.innerHTML = `
            <i class="${config.icon} ${config.class} me-1"></i>
            <small class="${config.class}">${config.text}</small>
        `;
    }

    showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-white bg-${type} border-0`;
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'assertive');
        toast.setAttribute('aria-atomic', 'true');

        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;

        const toastContainer = document.getElementById('toast-container') || (() => {
            const container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            document.body.appendChild(container);
            return container;
        })();

        toastContainer.appendChild(toast);
        const bsToast = new bootstrap.Toast(toast, { delay: 5000 });
        bsToast.show();

        toast.addEventListener('hidden.bs.toast', () => {
            toast.remove();
        });
    }

    showAlert(alertType, message, data = {}) {
        // Create alert based on type
        const alertClass = this.getAlertClass(alertType);
        const alertIcon = this.getAlertIcon(alertType);

        // Show toast notification
        this.showToast(message, this.getToastType(alertType));

        // Update alerts section if exists
        const alertsSection = document.getElementById('alerts-section');
        if (alertsSection) {
            const alertElement = document.createElement('div');
            alertElement.className = `alert ${alertClass} alert-dismissible fade show`;
            alertElement.innerHTML = `
                <i class="${alertIcon} me-2"></i>
                <strong>${this.getAlertTitle(alertType)}</strong> ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;

            alertsSection.insertAdjacentElement('afterbegin', alertElement);

            // Auto-dismiss after 10 seconds
            setTimeout(() => {
                if (alertElement.parentNode) {
                    alertElement.remove();
                }
            }, 10000);
        }
    }

    getAlertClass(alertType) {
        const classes = {
            'low_stock': 'alert-warning',
            'out_of_stock': 'alert-danger',
            'branch_inactive': 'alert-warning',
            'critical_inventory': 'alert-danger',
            'system': 'alert-info'
        };
        return classes[alertType] || 'alert-info';
    }

    getAlertIcon(alertType) {
        const icons = {
            'low_stock': 'bi-exclamation-triangle',
            'out_of_stock': 'bi-x-circle',
            'branch_inactive': 'bi-building-exclamation',
            'critical_inventory': 'bi-box-seam',
            'system': 'bi-info-circle'
        };
        return icons[alertType] || 'bi-bell';
    }

    getAlertTitle(alertType) {
        const titles = {
            'low_stock': 'Low Stock Alert',
            'out_of_stock': 'Out of Stock',
            'branch_inactive': 'Branch Alert',
            'critical_inventory': 'Critical Inventory',
            'system': 'System Alert'
        };
        return titles[alertType] || 'Alert';
    }

    getToastType(alertType) {
        const types = {
            'low_stock': 'warning',
            'out_of_stock': 'danger',
            'branch_inactive': 'warning',
            'critical_inventory': 'danger',
            'system': 'info'
        };
        return types[alertType] || 'info';
    }

    updateLastRefreshTime(timestamp) {
        const element = document.getElementById('last-refresh-time');
        if (element) {
            const date = new Date(timestamp);
            element.textContent = `Last updated: ${date.toLocaleTimeString()}`;
        }
    }

    bindEvents() {
        // Bind custom event listeners
        document.addEventListener('dashboard:requestBranchAnalytics', (event) => {
            this.send({
                type: 'request_branch_analytics',
                branch_id: event.detail.branchId
            });
        });

        document.addEventListener('dashboard:requestPerformanceUpdate', () => {
            this.send({ type: 'request_performance_update' });
        });

        // Handle page visibility changes
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.stopHeartbeat();
            } else {
                this.startHeartbeat();
            }
        });

        // Handle window beforeunload
        window.addEventListener('beforeunload', () => {
            this.disconnect();
        });
    }

    dispatchCustomEvent(eventName, detail) {
        const event = new CustomEvent(eventName, { detail });
        document.dispatchEvent(event);
    }

    disconnect() {
        if (this.ws) {
            this.ws.close(1000, 'Client disconnect');
        }
        this.stopHeartbeat();
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
        }
    }

    // Public API methods
    requestBranchAnalytics(branchId) {
        this.send({
            type: 'request_branch_analytics',
            branch_id: branchId
        });
    }

    requestPerformanceUpdate() {
        this.send({ type: 'request_performance_update' });
    }
}

// Branch Analytics WebSocket Handler
class BranchAnalyticsWebSocket {
    constructor(branchId) {
        this.branchId = branchId;
        this.ws = null;
        this.isConnected = false;

        this.connect();
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws/branch/${this.branchId}/analytics/`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('Branch analytics WebSocket connected');
            this.isConnected = true;
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleMessage(data);
        };

        this.ws.onclose = () => {
            console.log('Branch analytics WebSocket closed');
            this.isConnected = false;
        };

        this.ws.onerror = (error) => {
            console.error('Branch analytics WebSocket error:', error);
        };
    }

    handleMessage(data) {
        switch (data.type) {
            case 'initial_analytics':
                this.updateBranchAnalytics(data.data);
                break;
            case 'analytics_update':
                this.updateRealTimeBranchMetrics(data.data);
                break;
        }
    }

    updateBranchAnalytics(data) {
        // Update branch analytics display
        const event = new CustomEvent('branch:analyticsUpdate', {
            detail: { branchId: this.branchId, data }
        });
        document.dispatchEvent(event);
    }

    updateRealTimeBranchMetrics(data) {
        // Update real-time metrics
        const event = new CustomEvent('branch:metricsUpdate', {
            detail: { branchId: this.branchId, data }
        });
        document.dispatchEvent(event);
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
        }
    }
}

// Enhanced Chart Updates with WebSocket Integration
class DashboardChartManager {
    constructor(companyDashboard) {
        this.dashboard = companyDashboard;
        this.charts = {};
        this.setupEventListeners();
    }

    setupEventListeners() {
        document.addEventListener('dashboard:updateCharts', (event) => {
            this.updateAllCharts();
        });

        document.addEventListener('websocket:connected', () => {
            // Request initial chart data when connected
            this.requestChartData();
        });
    }

    requestChartData() {
        // Request updated chart data via WebSocket
        this.dashboard.send({
            type: 'request_chart_data',
            charts: Object.keys(this.charts)
        });
    }

    updateAllCharts() {
        Object.values(this.charts).forEach(chart => {
            if (chart && typeof chart.update === 'function') {
                chart.update();
            }
        });
    }

    registerChart(name, chartInstance) {
        this.charts[name] = chartInstance;
    }

    updateChartData(chartName, newData) {
        const chart = this.charts[chartName];
        if (chart) {
            chart.data = newData;
            chart.update();
        }
    }
}

// Integration with existing template JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Initialize WebSocket connection if company ID is available
    const companyElement = document.querySelector('[data-company-id]');
    if (companyElement) {
        const companyId = companyElement.dataset.companyId;

        // Create WebSocket connection
        window.companyDashboard = new CompanyDashboardWebSocket(companyId, {
            reconnectInterval: 3000,
            maxReconnectAttempts: 15,
            pingInterval: 25000
        });

        // Initialize chart manager
        window.chartManager = new DashboardChartManager(window.companyDashboard);

        // Handle branch analytics button clicks
        document.addEventListener('click', function(event) {
            if (event.target.matches('[data-branch-analytics]') || event.target.closest('[data-branch-analytics]')) {
                event.preventDefault();
                const button = event.target.matches('[data-branch-analytics]') ? event.target : event.target.closest('[data-branch-analytics]');
                const branchId = button.dataset.branchId;

                if (branchId) {
                    // Request branch analytics via WebSocket
                    window.companyDashboard.requestBranchAnalytics(branchId);
                }
            }
        });

        // Add WebSocket status indicator to header
        const headerElement = document.querySelector('.page-header, .breadcrumb');
        if (headerElement) {
            const statusIndicator = document.createElement('div');
            statusIndicator.id = 'websocket-status';
            statusIndicator.className = 'ms-3';
            headerElement.appendChild(statusIndicator);
        }
    }

    // Enhanced branch analytics modal function
    window.showBranchAnalytics = function(branchId) {
        const modal = new bootstrap.Modal(document.getElementById('branchAnalyticsModal'));
        const modalContent = document.getElementById('branchAnalyticsContent');

        // Show loading spinner
        modalContent.innerHTML = `
            <div class="text-center py-5">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `;

        modal.show();

        // Request analytics via WebSocket if available
        if (window.companyDashboard) {
            window.companyDashboard.requestBranchAnalytics(branchId);
        } else {
            // Fallback to HTTP request
            fetch(`/branches/${branchId}/analytics/`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
            })
            .then(response => response.json())
            .then(data => {
                renderBranchAnalytics(data, modalContent);
            })
            .catch(error => {
                console.error('Error loading branch analytics:', error);
                modalContent.innerHTML = `
                    <div class="alert alert-danger">
                        <i class="bi bi-exclamation-triangle me-2"></i>
                        Failed to load branch analytics. Please try again.
                    </div>
                `;
            });
        }
    };

    // Listen for WebSocket branch analytics responses
    document.addEventListener('websocket:branchAnalytics', function(event) {
        const modalContent = document.getElementById('branchAnalyticsContent');
        if (modalContent && document.getElementById('branchAnalyticsModal').classList.contains('show')) {
            renderBranchAnalytics(event.detail.data, modalContent);
        }
    });
});

// Utility function to add CSS animations for real-time updates
function addUpdateAnimation(element) {
    element.classList.add('data-updated');
    setTimeout(() => {
        element.classList.remove('data-updated');
    }, 1000);
}

// Add CSS for update animations
const style = document.createElement('style');
style.textContent = `
    .data-updated {
        animation: pulse-update 1s ease-in-out;
    }

    @keyframes pulse-update {
        0% { background-color: rgba(40, 167, 69, 0.2); }
        50% { background-color: rgba(40, 167, 69, 0.4); }
        100% { background-color: transparent; }
    }

    .new-activity {
        animation: slide-in 0.3s ease-out;
        background-color: rgba(13, 110, 253, 0.1);
    }

    @keyframes slide-in {
        from {
            opacity: 0;
            transform: translateX(-20px);
        }
        to {
            opacity: 1;
            transform: translateX(0);
        }
    }

    #websocket-status {
        font-size: 0.8rem;
    }

    .toast-container {
        z-index: 9999;
    }
`;
document.head.appendChild(style);