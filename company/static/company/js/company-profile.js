// static/company/js/company-profile.js
/**
 * Company Profile Dynamic Functionality
 * Handles AJAX form submission, tab switching, and real-time updates
 */

class CompanyProfile {
    constructor() {
        this.companyId = document.querySelector('[data-company-id]')?.dataset.companyId;
        this.currentTab = new URLSearchParams(window.location.search).get('tab') || 'overview';
        this.autoRefreshInterval = null;
        this.formDirty = false;

        this.init();
    }

    init() {
        this.setupTabs();
        this.setupFormHandling();
        this.setupAutoRefresh();
        this.setupNotifications();
        this.loadTabContent(this.currentTab);
    }

    /**
     * Tab Management
     */
    setupTabs() {
        const tabLinks = document.querySelectorAll('[data-tab]');

        tabLinks.forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();

                // Check for unsaved changes
                if (this.formDirty && !confirm('You have unsaved changes. Are you sure you want to leave?')) {
                    return;
                }

                const tab = link.dataset.tab;
                this.switchTab(tab);
            });
        });

        // Handle browser back/forward
        window.addEventListener('popstate', (e) => {
            if (e.state && e.state.tab) {
                this.switchTab(e.state.tab, false);
            }
        });
    }

    switchTab(tab, pushState = true) {
        // Update active tab
        document.querySelectorAll('[data-tab]').forEach(link => {
            link.classList.remove('active');
        });
        document.querySelector(`[data-tab="${tab}"]`)?.classList.add('active');

        // Update URL without reload
        if (pushState) {
            const url = new URL(window.location);
            url.searchParams.set('tab', tab);
            window.history.pushState({tab: tab}, '', url);
        }

        this.currentTab = tab;
        this.loadTabContent(tab);
    }

    loadTabContent(tab) {
        const contentArea = document.getElementById('tab-content');
        if (!contentArea) return;

        // Show loading
        contentArea.innerHTML = '<div class="text-center py-5"><div class="spinner-border" role="status"></div></div>';

        // Load content via AJAX
        fetch(`/companies/profile/tab/${tab}/`, {
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        })
        .then(response => response.text())
        .then(html => {
            contentArea.innerHTML = html;

            // Re-initialize form handling for new content
            this.setupFormHandling();

            // Load dynamic data for specific tabs
            if (tab === 'overview') {
                this.loadQuickStats();
            } else if (tab === 'subscription') {
                this.loadUsageMetrics();
            }
        })
        .catch(error => {
            console.error('Error loading tab content:', error);
            contentArea.innerHTML = '<div class="alert alert-danger">Error loading content</div>';
        });
    }

    /**
     * Form Handling with AJAX
     */
    setupFormHandling() {
        const form = document.getElementById('company-settings-form');
        if (!form) return;

        // Track form changes
        form.addEventListener('input', () => {
            this.formDirty = true;
            this.showSaveButton();
        });

        // Handle form submission
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.saveCompanySettings();
        });

        // Save button
        const saveBtn = document.getElementById('save-company-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => {
                this.saveCompanySettings();
            });
        }
    }

    showSaveButton() {
        const saveBtn = document.getElementById('save-company-btn');
        if (saveBtn) {
            saveBtn.classList.remove('d-none');
            saveBtn.classList.add('btn-pulse'); // Add animation
        }
    }

    hideSaveButton() {
        const saveBtn = document.getElementById('save-company-btn');
        if (saveBtn) {
            saveBtn.classList.add('d-none');
            saveBtn.classList.remove('btn-pulse');
        }
    }

    async saveCompanySettings() {
        const form = document.getElementById('company-settings-form');
        if (!form) return;

        const formData = new FormData(form);
        const saveBtn = document.getElementById('save-company-btn');

        // Show loading state
        if (saveBtn) {
            saveBtn.disabled = true;
            saveBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';
        }

        try {
            const response = await fetch(`/companies/${this.companyId}/update/api/`, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': this.getCsrfToken()
                }
            });

            const data = await response.json();

            if (data.success) {
                this.showNotification('success', data.message || 'Settings saved successfully');
                this.formDirty = false;
                this.hideSaveButton();

                // Update display name if changed
                if (data.data && data.data.display_name) {
                    document.querySelectorAll('.company-name-display').forEach(el => {
                        el.textContent = data.data.display_name;
                    });
                }
            } else {
                this.showNotification('error', data.message || 'Failed to save settings');

                // Show field errors
                if (data.errors) {
                    this.showFormErrors(data.errors);
                }
            }
        } catch (error) {
            console.error('Error saving settings:', error);
            this.showNotification('error', 'An error occurred while saving');
        } finally {
            // Reset button state
            if (saveBtn) {
                saveBtn.disabled = false;
                saveBtn.innerHTML = '<i class="bi bi-check-lg me-2"></i>Save Changes';
            }
        }
    }

    showFormErrors(errors) {
        // Clear previous errors
        document.querySelectorAll('.invalid-feedback').forEach(el => el.remove());
        document.querySelectorAll('.is-invalid').forEach(el => el.classList.remove('is-invalid'));

        // Show new errors
        for (const [field, messages] of Object.entries(errors)) {
            const input = document.querySelector(`[name="${field}"]`);
            if (input) {
                input.classList.add('is-invalid');
                const errorDiv = document.createElement('div');
                errorDiv.className = 'invalid-feedback';
                errorDiv.textContent = messages.join(', ');
                input.parentNode.appendChild(errorDiv);
            }
        }
    }

    /**
     * Auto-refresh for dashboard stats
     */
    setupAutoRefresh() {
        if (this.currentTab === 'overview') {
            // Refresh every 30 seconds
            this.autoRefreshInterval = setInterval(() => {
                this.loadQuickStats();
                this.checkCompanyStatus();
            }, 30000);
        }
    }

    async loadQuickStats() {
        try {
            const response = await fetch('/companies/api/quick-stats/', {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const data = await response.json();

            if (data.success) {
                this.updateStatWidgets(data.stats);
            }
        } catch (error) {
            console.error('Error loading quick stats:', error);
        }
    }

    updateStatWidgets(stats) {
        // Update revenue
        this.updateWidget('revenue-30d', stats.revenue_period.total, true);
        this.updateWidget('sales-30d', stats.revenue_period.sales_count);
        this.updateWidget('avg-sale', stats.revenue_period.avg_sale, true);

        // Update today
        this.updateWidget('today-revenue', stats.today.revenue, true);
        this.updateWidget('today-sales', stats.today.sales);

        // Update employees
        this.updateWidget('total-employees', `${stats.employees.active}/${stats.employees.total}`);

        // Update branches
        this.updateWidget('total-branches', `${stats.branches.active}/${stats.branches.total}`);

        // Update inventory alerts
        const inventoryWidget = document.getElementById('inventory-alerts');
        if (inventoryWidget && stats.inventory.needs_attention > 0) {
            inventoryWidget.innerHTML = `
                <span class="badge bg-warning">
                    <i class="bi bi-exclamation-triangle me-1"></i>
                    ${stats.inventory.needs_attention} items need attention
                </span>
            `;
        }

        // Update storage
        this.updateProgressBar('storage-progress', stats.storage.percentage);
    }

    updateWidget(id, value, isCurrency = false) {
        const element = document.getElementById(id);
        if (!element) return;

        if (isCurrency) {
            element.textContent = this.formatCurrency(value);
        } else {
            element.textContent = value;
        }

        // Add animation
        element.classList.add('stat-update');
        setTimeout(() => element.classList.remove('stat-update'), 500);
    }

    updateProgressBar(id, percentage) {
        const progressBar = document.getElementById(id);
        if (!progressBar) return;

        progressBar.style.width = `${percentage}%`;
        progressBar.setAttribute('aria-valuenow', percentage);

        // Update color based on percentage
        progressBar.className = 'progress-bar';
        if (percentage >= 90) {
            progressBar.classList.add('bg-danger');
        } else if (percentage >= 75) {
            progressBar.classList.add('bg-warning');
        } else {
            progressBar.classList.add('bg-success');
        }
    }

    async checkCompanyStatus() {
        try {
            const response = await fetch('/companies/api/status/', {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const data = await response.json();

            if (data.success && data.status_changed) {
                // Reload page if status changed significantly
                this.showNotification('info', 'Company status updated. Refreshing...');
                setTimeout(() => window.location.reload(), 2000);
            }

            // Update status badge
            if (data.success) {
                this.updateStatusBadge(data);
            }
        } catch (error) {
            console.error('Error checking company status:', error);
        }
    }

    updateStatusBadge(statusData) {
        const badge = document.getElementById('company-status-badge');
        if (!badge) return;

        badge.className = 'badge';

        if (statusData.status === 'ACTIVE') {
            badge.classList.add('bg-success');
        } else if (statusData.status === 'TRIAL') {
            badge.classList.add('bg-info');
        } else if (statusData.status === 'SUSPENDED') {
            badge.classList.add('bg-warning');
        } else if (statusData.status === 'EXPIRED') {
            badge.classList.add('bg-danger');
        }

        badge.textContent = statusData.access_status_display;
    }

    /**
     * Usage Metrics for Subscription Tab
     */
    async loadUsageMetrics() {
        try {
            const response = await fetch('/companies/api/usage-metrics/', {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const data = await response.json();

            if (data.success) {
                this.updateUsageMetrics(data.metrics);
                this.showUsageWarnings(data.warnings);
            }
        } catch (error) {
            console.error('Error loading usage metrics:', error);
        }
    }

    updateUsageMetrics(metrics) {
        for (const [key, data] of Object.entries(metrics)) {
            // Update progress bars
            this.updateProgressBar(`${key}-progress`, data.percentage);

            // Update text
            const textEl = document.getElementById(`${key}-text`);
            if (textEl) {
                if (key === 'storage') {
                    textEl.textContent = `${data.current_gb}GB / ${data.limit_gb}GB`;
                } else {
                    textEl.textContent = `${data.current} / ${data.limit}`;
                }
            }

            // Add warning badge if over limit
            const container = document.getElementById(`${key}-container`);
            if (container && data.over_limit) {
                container.classList.add('border-danger');
            }
        }
    }

    showUsageWarnings(warnings) {
        const warningsContainer = document.getElementById('usage-warnings');
        if (!warningsContainer || warnings.length === 0) return;

        warningsContainer.innerHTML = '';

        warnings.forEach(warning => {
            const alertClass = warning.severity === 'critical' ? 'alert-danger' : 'alert-warning';
            const alert = document.createElement('div');
            alert.className = `alert ${alertClass} alert-dismissible fade show`;
            alert.innerHTML = `
                <i class="bi bi-exclamation-triangle-fill me-2"></i>
                <strong>${warning.category.toUpperCase()}:</strong> ${warning.message}
                <br><small>${warning.suggestion}</small>
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            warningsContainer.appendChild(alert);
        });
    }

    /**
     * Notifications
     */
    setupNotifications() {
        this.loadNotifications();

        // Refresh notifications every 2 minutes
        setInterval(() => this.loadNotifications(), 120000);
    }

    async loadNotifications() {
        try {
            const response = await fetch('/companies/api/notifications/', {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const data = await response.json();

            if (data.success) {
                this.updateNotificationBadge(data.unread_count);
                this.updateNotificationDropdown(data.notifications);
            }
        } catch (error) {
            console.error('Error loading notifications:', error);
        }
    }

    updateNotificationBadge(count) {
        const badge = document.getElementById('notification-badge');
        if (!badge) return;

        if (count > 0) {
            badge.textContent = count > 99 ? '99+' : count;
            badge.classList.remove('d-none');
        } else {
            badge.classList.add('d-none');
        }
    }

    updateNotificationDropdown(notifications) {
        const dropdown = document.getElementById('notifications-dropdown');
        if (!dropdown) return;

        if (notifications.length === 0) {
            dropdown.innerHTML = '<div class="dropdown-item text-muted">No notifications</div>';
            return;
        }

        dropdown.innerHTML = notifications.slice(0, 5).map(notif => `
            <div class="dropdown-item notification-item border-bottom" data-priority="${notif.priority}">
                <div class="d-flex align-items-start">
                    <i class="bi ${notif.icon} me-3 text-${notif.type}"></i>
                    <div class="flex-grow-1">
                        <strong class="d-block">${notif.title}</strong>
                        <small class="text-muted">${notif.message}</small>
                        ${notif.action ? `
                            <br><a href="${notif.action.url}" class="btn btn-sm btn-outline-primary mt-2">
                                ${notif.action.text}
                            </a>
                        ` : ''}
                    </div>
                </div>
            </div>
        `).join('');

        // Add "View all" link
        dropdown.innerHTML += `
            <div class="dropdown-item text-center">
                <a href="/companies/notifications/" class="btn btn-sm btn-link">View All Notifications</a>
            </div>
        `;
    }

    showNotification(type, message) {
        // Create toast notification
        const toastContainer = document.getElementById('toast-container') || this.createToastContainer();

        const typeColors = {
            'success': 'bg-success',
            'error': 'bg-danger',
            'warning': 'bg-warning',
            'info': 'bg-info'
        };

        const typeIcons = {
            'success': 'bi-check-circle',
            'error': 'bi-x-circle',
            'warning': 'bi-exclamation-triangle',
            'info': 'bi-info-circle'
        };

        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-white ${typeColors[type]} border-0`;
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <i class="bi ${typeIcons[type]} me-2"></i>${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;

        toastContainer.appendChild(toast);

        const bsToast = new bootstrap.Toast(toast, {
            autohide: true,
            delay: 5000
        });
        bsToast.show();

        // Remove from DOM after hidden
        toast.addEventListener('hidden.bs.toast', () => {
            toast.remove();
        });
    }

    createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
        return container;
    }

    /**
     * Utility Methods
     */
    getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    formatCurrency(amount) {
        return new Intl.NumberFormat('en-UG', {
            style: 'currency',
            currency: 'UGX',
            minimumFractionDigits: 0
        }).format(amount);
    }

    /**
     * Cleanup
     */
    destroy() {
        if (this.autoRefreshInterval) {
            clearInterval(this.autoRefreshInterval);
        }
    }
}

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    window.companyProfile = new CompanyProfile();
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
    if (window.companyProfile) {
        window.companyProfile.destroy();
    }
});