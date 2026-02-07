class PlanLimitsChecker {
    constructor() {
        this.limits = window.planLimits || {};
        this.init();
    }

    init() {
        this.checkButtonStates();
        this.addEventListeners();
        this.setupRealTimeValidation();
        this.listenForLimitUpdates();
    }

    /**
     * Check and update button states based on limits
     */
    checkButtonStates() {
        // Disable "Add User" buttons if limit reached
        if (this.limits.users && this.limits.users.exceeded) {
            this.disableButtons('.add-user-btn', 'user');
        } else {
            this.enableButtons('.add-user-btn');
        }

        // Disable "Add Branch" buttons if limit reached
        if (this.limits.branches && this.limits.branches.exceeded) {
            this.disableButtons('.add-branch-btn', 'branch');
        } else {
            this.enableButtons('.add-branch-btn');
        }

        // REMOVED: showLimitWarnings() - no more automatic banners on every page
    }

    disableButtons(selector, type) {
        document.querySelectorAll(selector).forEach(btn => {
            btn.disabled = true;
            btn.classList.add('disabled');
            btn.setAttribute('data-bs-toggle', 'tooltip');
            btn.setAttribute('data-bs-placement', 'top');
            btn.title = `${type.charAt(0).toUpperCase() + type.slice(1)} limit reached. Please upgrade your plan.`;

            // Initialize Bootstrap tooltip
            new bootstrap.Tooltip(btn);
        });
    }

    enableButtons(selector) {
        document.querySelectorAll(selector).forEach(btn => {
            btn.disabled = false;
            btn.classList.remove('disabled');
            btn.removeAttribute('data-bs-toggle');
            btn.removeAttribute('data-bs-placement');
            btn.title = '';
        });
    }

    /**
     * Show warning banner (now only called when attempting an action near limit)
     */
    showWarningBanner(type, percentage) {
        const bannerId = `limit-warning-${type}`;

        // Don't show if already exists
        if (document.getElementById(bannerId)) return;

        const messages = {
            user: `You're using ${percentage.toFixed(0)}% of your user limit (${this.limits.users.current}/${this.limits.users.limit})`,
            branch: `You're using ${percentage.toFixed(0)}% of your branch limit (${this.limits.branches.current}/${this.limits.branches.limit})`,
            storage: `You're using ${percentage.toFixed(0)}% of your storage limit`
        };

        const banner = document.createElement('div');
        banner.id = bannerId;
        banner.className = `alert alert-${percentage >= 100 ? 'danger' : 'warning'} alert-dismissible fade show`;
        banner.innerHTML = `
            <i class="bi bi-exclamation-triangle me-2"></i>
            <strong>Limit Warning:</strong> ${messages[type]}
            <a href="/companies/subscription/plans/" class="alert-link ms-2">Upgrade Plan</a>
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        const container = document.querySelector('.container-fluid') || document.querySelector('.container');
        if (container) {
            container.insertBefore(banner, container.firstChild);
        }
    }

    /**
     * Add form submission interceptors
     */
    addEventListeners() {
        // Intercept user creation forms
        document.querySelectorAll('form[data-requires="user-slot"]').forEach(form => {
            form.addEventListener('submit', (e) => {
                if (this.limits.users && this.limits.users.exceeded) {
                    e.preventDefault();
                    this.showLimitDialog('user');
                } else if (this.limits.users) {
                    // Show warning if approaching limit (80%+) but allow to proceed
                    const percentage = (this.limits.users.current / this.limits.users.limit) * 100;
                    if (percentage >= 80) {
                        this.showWarningBanner('user', percentage);
                    }
                }
            });
        });

        // Intercept branch creation forms
        document.querySelectorAll('form[data-requires="branch-slot"]').forEach(form => {
            form.addEventListener('submit', (e) => {
                if (this.limits.branches && this.limits.branches.exceeded) {
                    e.preventDefault();
                    this.showLimitDialog('branch');
                } else if (this.limits.branches) {
                    // Show warning if approaching limit (80%+) but allow to proceed
                    const percentage = (this.limits.branches.current / this.limits.branches.limit) * 100;
                    if (percentage >= 80) {
                        this.showWarningBanner('branch', percentage);
                    }
                }
            });
        });

        // Add click interceptors for add buttons
        document.querySelectorAll('.add-user-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                if (this.limits.users && this.limits.users.exceeded) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.showLimitDialog('user');
                }
            });
        });

        document.querySelectorAll('.add-branch-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                if (this.limits.branches && this.limits.branches.exceeded) {
                    e.preventDefault();
                    e.stopPropagation();
                    this.showLimitDialog('branch');
                }
            });
        });
    }

    /**
     * Real-time validation for form inputs
     */
    setupRealTimeValidation() {
        // Monitor file uploads for storage limit
        document.querySelectorAll('input[type="file"]').forEach(input => {
            input.addEventListener('change', (e) => {
                if (this.limits.storage && this.limits.storage.exceeded) {
                    e.preventDefault();
                    input.value = '';
                    this.showLimitDialog('storage');
                }
            });
        });
    }

    /**
     * Listen for limit updates from subscription manager
     */
    listenForLimitUpdates() {
        window.addEventListener('limitsUpdated', (e) => {
            this.limits = e.detail;
            this.checkButtonStates();
        });
    }

    /**
     * Show upgrade dialog
     */
    showLimitDialog(type) {
        const messages = {
            user: {
                title: 'User Limit Reached',
                body: `You have reached your user limit (${this.limits.users?.current}/${this.limits.users?.limit}). Please upgrade your plan to add more users.`,
                icon: 'bi-people'
            },
            branch: {
                title: 'Branch Limit Reached',
                body: `You have reached your branch limit (${this.limits.branches?.current}/${this.limits.branches?.limit}). Please upgrade your plan to add more branches.`,
                icon: 'bi-building'
            },
            storage: {
                title: 'Storage Limit Reached',
                body: `You have reached your storage limit (${this.limits.storage?.percentage.toFixed(1)}% used). Please upgrade your plan for more storage.`,
                icon: 'bi-hdd'
            }
        };

        const config = messages[type];

        // Create modal if it doesn't exist
        let modal = document.getElementById('limit-exceeded-modal');
        if (!modal) {
            modal = this.createLimitModal();
        }

        // Update modal content
        document.getElementById('limit-modal-title').innerHTML = `
            <i class="${config.icon} me-2"></i>${config.title}
        `;
        document.getElementById('limit-modal-body').textContent = config.body;

        // Show modal
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    createLimitModal() {
        const modalHtml = `
            <div class="modal fade" id="limit-exceeded-modal" tabindex="-1">
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content">
                        <div class="modal-header bg-warning text-dark">
                            <h5 class="modal-title" id="limit-modal-title"></h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <p id="limit-modal-body"></p>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Cancel</button>
                            <a href="/companies/subscription/plans/" class="btn btn-primary">
                                <i class="bi bi-arrow-up-circle me-2"></i>View Upgrade Options
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        `;

        document.body.insertAdjacentHTML('beforeend', modalHtml);
        return document.getElementById('limit-exceeded-modal');
    }

    /**
     * Get current limit status
     */
    getLimitStatus(type) {
        if (!this.limits[type]) return null;

        const limit = this.limits[type];
        const percentage = type === 'storage'
            ? limit.percentage
            : (limit.current / limit.limit) * 100;

        return {
            current: limit.current,
            limit: limit.limit,
            available: limit.available,
            percentage: percentage,
            exceeded: limit.exceeded,
            status: percentage >= 100 ? 'exceeded' : percentage >= 80 ? 'warning' : 'ok'
        };
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    window.planLimitsChecker = new PlanLimitsChecker();
});

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = PlanLimitsChecker;
}