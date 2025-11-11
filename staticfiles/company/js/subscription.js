// static/company/js/subscription.js
/**
 * Subscription Management Interface
 * Handles plan upgrades, downgrades, renewals, and cancellations
 */

class SubscriptionManager {
    constructor() {
        this.currentPlan = null;
        this.selectedPlan = null;
        this.billingCycle = 'MONTHLY';

        this.init();
    }

    init() {
        this.setupPlanComparison();
        this.setupBillingCycleToggle();
        this.setupPlanSelection();
        this.setupRenewalHandler();
        this.setupCancellationHandler();
        this.loadUsageChart();
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

            if (this.billingCycle === 'QUARTERLY') {
                displayPrice = basePrice * 3;
                periodText = '/quarter';
            } else if (this.billingCycle === 'YEARLY') {
                displayPrice = basePrice * 12;
                periodText = '/year';

                // Show discount
                const discount = displayPrice * 0.1; // 10% discount
                displayPrice -= discount;

                const discountBadge = card.querySelector('.discount-badge');
                if (discountBadge) {
                    discountBadge.classList.remove('d-none');
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
                const action = btn.dataset.action; // upgrade, downgrade, current

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

        // Populate modal
        document.getElementById('upgrade-plan-name').textContent = this.selectedPlan.name;
        document.getElementById('upgrade-billing-cycle').value = this.billingCycle;

        // Load cost breakdown
        this.loadUpgradeCost();

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    async loadUpgradeCost() {
        try {
            const response = await fetch(
                `/companies/subscription/upgrade/${this.selectedPlan.id}/cost/?billing_cycle=${this.billingCycle}`,
                {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                }
            );

            const data = await response.json();

            if (data.success) {
                this.displayCostBreakdown(data.breakdown);
            }
        } catch (error) {
            console.error('Error loading upgrade cost:', error);
        }
    }

    displayCostBreakdown(breakdown) {
        const container = document.getElementById('cost-breakdown');
        if (!container) return;

        container.innerHTML = `
            <div class="mb-2">
                <span>Plan Cost:</span>
                <span class="float-end">$${breakdown.plan_cost.toFixed(2)}</span>
            </div>
            ${breakdown.setup_fee > 0 ? `
                <div class="mb-2">
                    <span>Setup Fee:</span>
                    <span class="float-end">$${breakdown.setup_fee.toFixed(2)}</span>
                </div>
            ` : ''}
            ${breakdown.proration_credit > 0 ? `
                <div class="mb-2 text-success">
                    <span>Prorated Credit:</span>
                    <span class="float-end">-$${breakdown.proration_credit.toFixed(2)}</span>
                </div>
            ` : ''}
            <hr>
            <div class="fw-bold">
                <span>Total Due:</span>
                <span class="float-end">$${breakdown.total.toFixed(2)}</span>
            </div>
        `;
    }

    showDowngradeConfirmation() {
        const modal = document.getElementById('downgrade-confirmation-modal');
        if (!modal) return;

        // Populate modal
        document.getElementById('downgrade-plan-name').textContent = this.selectedPlan.name;

        // Load downgrade validation
        this.validateDowngrade();

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    async validateDowngrade() {
        try {
            const response = await fetch(
                `/companies/subscription/downgrade/${this.selectedPlan.id}/validate/`,
                {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                }
            );

            const data = await response.json();

            const issuesContainer = document.getElementById('downgrade-issues');
            const confirmBtn = document.getElementById('confirm-downgrade-btn');

            if (data.can_downgrade) {
                issuesContainer.innerHTML = '<div class="alert alert-success">No issues found. You can proceed with the downgrade.</div>';
                confirmBtn.disabled = false;
            } else {
                issuesContainer.innerHTML = `
                    <div class="alert alert-warning">
                        <strong>Cannot downgrade yet. Please resolve these issues:</strong>
                        <ul class="mt-2 mb-0">
                            ${data.issues.map(issue => `
                                <li>${issue.message}<br><small class="text-muted">${issue.action}</small></li>
                            `).join('')}
                        </ul>
                    </div>
                `;
                confirmBtn.disabled = true;
            }

            // Show lost features
            if (data.lost_features && data.lost_features.length > 0) {
                document.getElementById('lost-features').innerHTML = `
                    <div class="alert alert-info">
                        <strong>Features you will lose:</strong>
                        <ul class="mt-2 mb-0">
                            ${data.lost_features.map(f => `<li>${f}</li>`).join('')}
                        </ul>
                    </div>
                `;
            }
        } catch (error) {
            console.error('Error validating downgrade:', error);
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

        // Show loading
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

                // Redirect after 2 seconds
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
        const immediate = document.getElementById('immediate-cancellation').checked;

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

        // Get data from data attributes
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
                    backgroundColor: [
                        'rgba(54, 162, 235, 0.5)',
                        'rgba(255, 206, 86, 0.5)',
                        'rgba(75, 192, 192, 0.5)'
                    ],
                    borderColor: [
                        'rgba(54, 162, 235, 1)',
                        'rgba(255, 206, 86, 1)',
                        'rgba(75, 192, 192, 1)'
                    ],
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
                    }
                }
            }
        });
    }

    /**
     * Utility Methods
     */
    getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    showNotification(type, message) {
        // Reuse the notification system from company-profile.js
        if (window.companyProfile) {
            window.companyProfile.showNotification(type, message);
        } else {
            alert(message);
        }
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