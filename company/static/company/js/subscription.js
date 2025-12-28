class SubscriptionManager {
    constructor() {
        this.currentPlan = null;
        this.selectedPlan = null;
        this.billingCycle = 'MONTHLY';
        this.limits = window.planLimits || {};

        this.init();
    }

    init() {
        this.setupPlanComparison();
        this.setupBillingCycleToggle();
        this.setupPlanSelection();
        this.setupRenewalHandler();
        this.setupCancellationHandler();
        this.loadUsageChart();
        this.updateLimitBadges();  // NEW
        this.startLimitMonitoring();  // NEW
    }

    /**
     * NEW: Update limit badges in real-time
     */
    updateLimitBadges() {
        // Update user limit badge
        if (this.limits.users) {
            const userBadge = document.getElementById('user-limit-badge');
            if (userBadge) {
                const percentage = (this.limits.users.current / this.limits.users.limit) * 100;
                userBadge.innerHTML = `${this.limits.users.current}/${this.limits.users.limit}`;

                // Update color based on usage
                userBadge.className = 'badge';
                if (percentage >= 100) {
                    userBadge.classList.add('bg-danger');
                } else if (percentage >= 80) {
                    userBadge.classList.add('bg-warning');
                } else {
                    userBadge.classList.add('bg-success');
                }
            }
        }

        // Update branch limit badge
        if (this.limits.branches) {
            const branchBadge = document.getElementById('branch-limit-badge');
            if (branchBadge) {
                const percentage = (this.limits.branches.current / this.limits.branches.limit) * 100;
                branchBadge.innerHTML = `${this.limits.branches.current}/${this.limits.branches.limit}`;

                branchBadge.className = 'badge';
                if (percentage >= 100) {
                    branchBadge.classList.add('bg-danger');
                } else if (percentage >= 80) {
                    branchBadge.classList.add('bg-warning');
                } else {
                    branchBadge.classList.add('bg-success');
                }
            }
        }

        // Update storage limit badge
        if (this.limits.storage) {
            const storageBadge = document.getElementById('storage-limit-badge');
            if (storageBadge) {
                const percentage = this.limits.storage.percentage;
                storageBadge.innerHTML = `${percentage.toFixed(1)}%`;

                storageBadge.className = 'badge';
                if (percentage >= 100) {
                    storageBadge.classList.add('bg-danger');
                } else if (percentage >= 80) {
                    storageBadge.classList.add('bg-warning');
                } else {
                    storageBadge.classList.add('bg-success');
                }
            }
        }
    }

    /**
     * NEW: Start monitoring limits every 30 seconds
     */
    startLimitMonitoring() {
        setInterval(() => {
            this.refreshLimits();
        }, 30000); // Check every 30 seconds
    }

    /**
     * NEW: Refresh limits from server
     */
    async refreshLimits() {
        try {
            const response = await fetch('/companies/subscription/limits/', {
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            if (response.ok) {
                const data = await response.json();
                this.limits = data.limits;
                this.updateLimitBadges();

                // Update window.planLimits for other scripts
                window.planLimits = data.limits;

                // Trigger custom event
                window.dispatchEvent(new CustomEvent('limitsUpdated', {
                    detail: this.limits
                }));
            }
        } catch (error) {
            console.error('Error refreshing limits:', error);
        }
    }

    /**
     * Plan Comparison
     */
    setupPlanComparison() {
        const compareBtn = document.getElementById('compare-plans-btn');
        if (compareBtn) {
            compareBtn.addEventListener('click', () => {
                this.showPlanComparison();
            });
        }
    }

    showPlanComparison() {
        const modal = new bootstrap.Modal(document.getElementById('plan-comparison-modal'));
        modal.show();
    }

    /**
     * Billing Cycle Toggle
     */
    setupBillingCycleToggle() {
        const toggles = document.querySelectorAll('[name="billing_cycle"]');

        toggles.forEach(toggle => {
            toggle.addEventListener('change', (e) => {
                this.billingCycle = e.target.value;
                this.updatePlanPrices();
            });
        });
    }

    updatePlanPrices() {
        document.querySelectorAll('.plan-card').forEach(card => {
            const planId = card.dataset.planId;
            const basePrice = parseFloat(card.dataset.basePrice);

            let displayPrice = basePrice;
            let periodText = '/month';
            let savings = 0;

            if (this.billingCycle === 'QUARTERLY') {
                displayPrice = basePrice * 3;
                periodText = '/quarter';
            } else if (this.billingCycle === 'YEARLY') {
                const yearlyPrice = basePrice * 12;
                savings = yearlyPrice * 0.1; // 10% discount
                displayPrice = yearlyPrice - savings;
                periodText = '/year';

                const discountBadge = card.querySelector('.discount-badge');
                if (discountBadge) {
                    discountBadge.textContent = `Save $${savings.toFixed(2)}`;
                    discountBadge.classList.remove('d-none');
                }
            } else {
                const discountBadge = card.querySelector('.discount-badge');
                if (discountBadge) {
                    discountBadge.classList.add('d-none');
                }
            }

            const priceEl = card.querySelector('.plan-price');
            if (priceEl) {
                priceEl.innerHTML = `
                    <span class="h2">$${displayPrice.toFixed(2)}</span>
                    <span class="text-muted">${periodText}</span>
                `;
            }
        });
    }

    /**
     * Plan Selection
     */
    setupPlanSelection() {
        document.querySelectorAll('.select-plan-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.preventDefault();

                const planId = btn.dataset.planId;
                const planName = btn.dataset.planName;
                const action = btn.dataset.action;

                if (action === 'current') {
                    this.showNotification('info', 'This is your current plan');
                    return;
                }

                this.selectedPlan = {
                    id: planId,
                    name: planName,
                    action: action
                };

                if (action === 'upgrade') {
                    this.showUpgradeConfirmation();
                } else if (action === 'downgrade') {
                    this.showDowngradeConfirmation();
                }
            });
        });
    }

    showUpgradeConfirmation() {
        const modal = document.getElementById('upgrade-confirmation-modal');
        if (!modal) return;

        document.getElementById('upgrade-plan-name').textContent = this.selectedPlan.name;
        document.getElementById('upgrade-billing-cycle').value = this.billingCycle;

        this.loadUpgradeCost();

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    async loadUpgradeCost() {
        const loader = document.getElementById('cost-breakdown-loader');
        const container = document.getElementById('cost-breakdown');

        if (loader) loader.classList.remove('d-none');
        if (container) container.classList.add('d-none');

        try {
            const response = await fetch(
                `/companies/subscription/upgrade/${this.selectedPlan.id}/?billing_cycle=${this.billingCycle}`,
                {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                }
            );

            if (!response.ok) {
                throw new Error('Failed to load cost breakdown');
            }

            const html = await response.text();

            // Extract cost data from the response
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');
            const costData = doc.querySelector('#cost-data');

            if (costData) {
                const breakdown = JSON.parse(costData.textContent);
                this.displayCostBreakdown(breakdown);
            }

        } catch (error) {
            console.error('Error loading upgrade cost:', error);
            if (container) {
                container.innerHTML = '<div class="alert alert-danger">Unable to load cost breakdown</div>';
            }
        } finally {
            if (loader) loader.classList.add('d-none');
            if (container) container.classList.remove('d-none');
        }
    }

    displayCostBreakdown(breakdown) {
        const container = document.getElementById('cost-breakdown');
        if (!container) return;

        container.innerHTML = `
            <div class="list-group">
                <div class="list-group-item d-flex justify-content-between">
                    <span>Plan Cost:</span>
                    <span class="fw-bold">$${breakdown.upgrade_cost.toFixed(2)}</span>
                </div>
                ${breakdown.setup_fee > 0 ? `
                    <div class="list-group-item d-flex justify-content-between">
                        <span>Setup Fee:</span>
                        <span class="fw-bold">$${breakdown.setup_fee.toFixed(2)}</span>
                    </div>
                ` : ''}
                ${breakdown.proration_credit > 0 ? `
                    <div class="list-group-item d-flex justify-content-between text-success">
                        <span>Prorated Credit:</span>
                        <span class="fw-bold">-$${breakdown.proration_credit.toFixed(2)}</span>
                    </div>
                ` : ''}
                <div class="list-group-item d-flex justify-content-between bg-light">
                    <span class="fw-bold">Total Due Today:</span>
                    <span class="h5 mb-0 text-primary">$${(breakdown.upgrade_cost + breakdown.setup_fee - breakdown.proration_credit).toFixed(2)}</span>
                </div>
            </div>
        `;
    }

    showDowngradeConfirmation() {
        const modal = document.getElementById('downgrade-confirmation-modal');
        if (!modal) return;

        document.getElementById('downgrade-plan-name').textContent = this.selectedPlan.name;

        this.validateDowngrade();

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    async validateDowngrade() {
        const loader = document.getElementById('downgrade-validation-loader');
        const issuesContainer = document.getElementById('downgrade-issues');
        const confirmBtn = document.getElementById('confirm-downgrade-btn');

        if (loader) loader.classList.remove('d-none');
        if (issuesContainer) issuesContainer.classList.add('d-none');

        try {
            const response = await fetch(
                `/companies/subscription/downgrade/${this.selectedPlan.id}/`,
                {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                }
            );

            const html = await response.text();
            const parser = new DOMParser();
            const doc = parser.parseFromString(html, 'text/html');

            // Extract issues from the response
            const issuesData = doc.querySelector('#downgrade-data');

            if (issuesData) {
                const data = JSON.parse(issuesData.textContent);

                if (data.can_downgrade) {
                    issuesContainer.innerHTML = `
                        <div class="alert alert-success">
                            <i class="bi bi-check-circle me-2"></i>
                            No issues found. You can proceed with the downgrade.
                        </div>
                    `;
                    confirmBtn.disabled = false;
                } else {
                    issuesContainer.innerHTML = `
                        <div class="alert alert-warning">
                            <strong><i class="bi bi-exclamation-triangle me-2"></i>Cannot downgrade yet</strong>
                            <p class="mb-2">Please resolve these issues first:</p>
                            <ul class="mb-0">
                                ${data.issues.map(issue => `
                                    <li class="mb-2">
                                        <strong>${issue.message}</strong><br>
                                        <small class="text-muted">${issue.action}</small>
                                    </li>
                                `).join('')}
                            </ul>
                        </div>
                    `;
                    confirmBtn.disabled = true;
                }

                // Show lost features
                if (data.lost_features && data.lost_features.length > 0) {
                    const featuresHtml = `
                        <div class="alert alert-info mt-3">
                            <strong><i class="bi bi-info-circle me-2"></i>Features you will lose:</strong>
                            <ul class="mt-2 mb-0">
                                ${data.lost_features.map(f => `<li>${f}</li>`).join('')}
                            </ul>
                        </div>
                    `;
                    issuesContainer.innerHTML += featuresHtml;
                }
            }

        } catch (error) {
            console.error('Error validating downgrade:', error);
            issuesContainer.innerHTML = `
                <div class="alert alert-danger">
                    <i class="bi bi-x-circle me-2"></i>
                    Unable to validate downgrade. Please try again.
                </div>
            `;
            confirmBtn.disabled = true;
        } finally {
            if (loader) loader.classList.add('d-none');
            if (issuesContainer) issuesContainer.classList.remove('d-none');
        }
    }

    /**
     * Confirm Actions
     */
    async confirmUpgrade() {
        const btn = document.getElementById('confirm-upgrade-btn');
        const paymentMethod = document.querySelector('[name="payment_method"]:checked')?.value;

        if (!paymentMethod) {
            this.showNotification('warning', 'Please select a payment method');
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Processing...';

        try {
            const formData = new FormData();
            formData.append('billing_cycle', this.billingCycle);
            formData.append('payment_method', paymentMethod);
            formData.append('csrfmiddlewaretoken', this.getCsrfToken());

            const response = await fetch(
                `/companies/subscription/upgrade/${this.selectedPlan.id}/`,
                {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                }
            );

            const data = await response.json();

            if (data.success) {
                this.showNotification('success', 'Plan upgraded successfully!');

                // Refresh limits immediately
                await this.refreshLimits();

                setTimeout(() => {
                    window.location.href = '/companies/subscription/dashboard/';
                }, 2000);
            } else {
                this.showNotification('error', data.message || 'Upgrade failed');
                btn.disabled = false;
                btn.innerHTML = 'Confirm Upgrade';
            }
        } catch (error) {
            console.error('Error upgrading plan:', error);
            this.showNotification('error', 'An error occurred');
            btn.disabled = false;
            btn.innerHTML = 'Confirm Upgrade';
        }
    }

    async confirmDowngrade() {
        const btn = document.getElementById('confirm-downgrade-btn');

        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Processing...';

        try {
            const formData = new FormData();
            formData.append('csrfmiddlewaretoken', this.getCsrfToken());

            const response = await fetch(
                `/companies/subscription/downgrade/${this.selectedPlan.id}/`,
                {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                }
            );

            const data = await response.json();

            if (data.success) {
                this.showNotification('success', 'Downgrade scheduled successfully');

                setTimeout(() => {
                    window.location.href = '/companies/subscription/dashboard/';
                }, 2000);
            } else {
                this.showNotification('error', data.message || 'Downgrade failed');
                btn.disabled = false;
                btn.innerHTML = 'Confirm Downgrade';
            }
        } catch (error) {
            console.error('Error downgrading plan:', error);
            this.showNotification('error', 'An error occurred');
            btn.disabled = false;
            btn.innerHTML = 'Confirm Downgrade';
        }
    }

    /**
     * Renewal Handler
     */
    setupRenewalHandler() {
        const renewBtn = document.getElementById('renew-subscription-btn');
        if (renewBtn) {
            renewBtn.addEventListener('click', () => {
                this.showRenewalModal();
            });
        }
    }

    showRenewalModal() {
        const modal = new bootstrap.Modal(document.getElementById('renewal-modal'));
        modal.show();
    }

    async confirmRenewal() {
        const btn = document.getElementById('confirm-renewal-btn');
        const billingCycle = document.getElementById('renewal-billing-cycle').value;
        const paymentMethod = document.querySelector('[name="renewal_payment_method"]:checked')?.value;

        if (!paymentMethod) {
            this.showNotification('warning', 'Please select a payment method');
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Processing...';

        try {
            const formData = new FormData();
            formData.append('billing_cycle', billingCycle);
            formData.append('payment_method', paymentMethod);
            formData.append('csrfmiddlewaretoken', this.getCsrfToken());

            const response = await fetch('/companies/subscription/renew/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const data = await response.json();

            if (data.success) {
                this.showNotification('success', 'Subscription renewed successfully!');

                setTimeout(() => {
                    window.location.reload();
                }, 2000);
            } else {
                this.showNotification('error', data.message || 'Renewal failed');
                btn.disabled = false;
                btn.innerHTML = 'Confirm Renewal';
            }
        } catch (error) {
            console.error('Error renewing subscription:', error);
            this.showNotification('error', 'An error occurred');
            btn.disabled = false;
            btn.innerHTML = 'Confirm Renewal';
        }
    }

    /**
     * Cancellation Handler
     */
    setupCancellationHandler() {
        const cancelBtn = document.getElementById('cancel-subscription-btn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', () => {
                this.showCancellationModal();
            });
        }
    }

    showCancellationModal() {
        const modal = new bootstrap.Modal(document.getElementById('cancellation-modal'));
        modal.show();
    }

    async confirmCancellation() {
        const btn = document.getElementById('confirm-cancellation-btn');
        const reason = document.getElementById('cancellation-reason').value;
        const immediate = document.getElementById('immediate-cancellation')?.checked || false;

        if (!reason.trim()) {
            this.showNotification('warning', 'Please provide a reason for cancellation');
            return;
        }

        btn.disabled = true;
        btn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Processing...';

        try {
            const formData = new FormData();
            formData.append('reason', reason);
            formData.append('immediate', immediate ? 'true' : 'false');
            formData.append('csrfmiddlewaretoken', this.getCsrfToken());

            const response = await fetch('/companies/subscription/cancel/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });

            const data = await response.json();

            if (data.success) {
                this.showNotification('success', 'Subscription cancelled');

                setTimeout(() => {
                    window.location.reload();
                }, 2000);
            } else {
                this.showNotification('error', data.message || 'Cancellation failed');
                btn.disabled = false;
                btn.innerHTML = 'Confirm Cancellation';
            }
        } catch (error) {
            console.error('Error cancelling subscription:', error);
            this.showNotification('error', 'An error occurred');
            btn.disabled = false;
            btn.innerHTML = 'Confirm Cancellation';
        }
    }

    /**
     * Usage Chart
     */
    loadUsageChart() {
        const canvas = document.getElementById('usage-chart');
        if (!canvas) return;

        const ctx = canvas.getContext('2d');

        const usersData = parseFloat(canvas.dataset.users || 0);
        const branchesData = parseFloat(canvas.dataset.branches || 0);
        const storageData = parseFloat(canvas.dataset.storage || 0);

        new Chart(ctx, {
            type: 'bar',
            data: {
                labels: ['Users', 'Branches', 'Storage'],
                datasets: [{
                    label: 'Usage %',
                    data: [usersData, branchesData, storageData],
                    backgroundColor: function(context) {
                        const value = context.parsed.y;
                        if (value >= 100) return 'rgba(220, 53, 69, 0.5)';
                        if (value >= 80) return 'rgba(255, 193, 7, 0.5)';
                        return 'rgba(25, 135, 84, 0.5)';
                    },
                    borderColor: function(context) {
                        const value = context.parsed.y;
                        if (value >= 100) return 'rgba(220, 53, 69, 1)';
                        if (value >= 80) return 'rgba(255, 193, 7, 1)';
                        return 'rgba(25, 135, 84, 1)';
                    },
                    borderWidth: 2
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        max: 100,
                        ticks: {
                            callback: function(value) {
                                return value + '%';
                            }
                        }
                    }
                },
                plugins: {
                    legend: {
                        display: false
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return context.parsed.y.toFixed(1) + '% used';
                            }
                        }
                    }
                }
            }
        });
    }

    /**
     * Utility Methods
     */
    getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
               document.querySelector('meta[name="csrf-token"]')?.content || '';
    }

    showNotification(type, message) {
        // Create toast notification
        const toastContainer = document.getElementById('toast-container') || this.createToastContainer();

        const toastId = 'toast-' + Date.now();
        const iconMap = {
            success: 'bi-check-circle-fill',
            error: 'bi-x-circle-fill',
            warning: 'bi-exclamation-triangle-fill',
            info: 'bi-info-circle-fill'
        };

        const bgMap = {
            success: 'bg-success',
            error: 'bg-danger',
            warning: 'bg-warning',
            info: 'bg-info'
        };

        const toastHtml = `
            <div id="${toastId}" class="toast align-items-center text-white ${bgMap[type]} border-0" role="alert">
                <div class="d-flex">
                    <div class="toast-body">
                        <i class="bi ${iconMap[type]} me-2"></i>
                        ${message}
                    </div>
                    <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
                </div>
            </div>
        `;

        toastContainer.insertAdjacentHTML('beforeend', toastHtml);

        const toastElement = document.getElementById(toastId);
        const toast = new bootstrap.Toast(toastElement, { delay: 5000 });
        toast.show();

        toastElement.addEventListener('hidden.bs.toast', () => {
            toastElement.remove();
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
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    window.subscriptionManager = new SubscriptionManager();

    // Setup event listeners for confirmation buttons
    const confirmUpgradeBtn = document.getElementById('confirm-upgrade-btn');
    if (confirmUpgradeBtn) {
        confirmUpgradeBtn.addEventListener('click', () => {
            window.subscriptionManager.confirmUpgrade();
        });
    }

    const confirmDowngradeBtn = document.getElementById('confirm-downgrade-btn');
    if (confirmDowngradeBtn) {
        confirmDowngradeBtn.addEventListener('click', () => {
            window.subscriptionManager.confirmDowngrade();
        });
    }

    const confirmRenewalBtn = document.getElementById('confirm-renewal-btn');
    if (confirmRenewalBtn) {
        confirmRenewalBtn.addEventListener('click', () => {
            window.subscriptionManager.confirmRenewal();
        });
    }

    const confirmCancellationBtn = document.getElementById('confirm-cancellation-btn');
    if (confirmCancellationBtn) {
        confirmCancellationBtn.addEventListener('click', () => {
            window.subscriptionManager.confirmCancellation();
        });
    }
});