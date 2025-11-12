class PlanLimitsChecker {
    constructor() {
        this.limits = window.planLimits || {};
        this.init();
    }

    init() {
        this.checkButtonStates();
        this.addEventListeners();
    }

    checkButtonStates() {
        // Disable "Add User" buttons if limit reached
        if (this.limits.users && this.limits.users.exceeded) {
            document.querySelectorAll('.add-user-btn').forEach(btn => {
                btn.disabled = true;
                btn.title = 'User limit reached. Please upgrade your plan.';
                btn.classList.add('disabled');
            });
        }

        // Disable "Add Branch" buttons if limit reached
        if (this.limits.branches && this.limits.branches.exceeded) {
            document.querySelectorAll('.add-branch-btn').forEach(btn => {
                btn.disabled = true;
                btn.title = 'Branch limit reached. Please upgrade your plan.';
                btn.classList.add('disabled');
            });
        }
    }

    addEventListeners() {
        // Intercept form submissions that would exceed limits
        document.querySelectorAll('form[data-requires="user-slot"]').forEach(form => {
            form.addEventListener('submit', (e) => {
                if (this.limits.users && this.limits.users.exceeded) {
                    e.preventDefault();
                    this.showLimitDialog('user');
                }
            });
        });

        document.querySelectorAll('form[data-requires="branch-slot"]').forEach(form => {
            form.addEventListener('submit', (e) => {
                if (this.limits.branches && this.limits.branches.exceeded) {
                    e.preventDefault();
                    this.showLimitDialog('branch');
                }
            });
        });
    }

    showLimitDialog(type) {
        const messages = {
            user: 'You have reached your user limit. Please upgrade your plan to add more users.',
            branch: 'You have reached your branch limit. Please upgrade your plan to add more branches.',
            storage: 'You have reached your storage limit. Please upgrade your plan for more storage.'
        };

        if (confirm(`${messages[type]}\n\nWould you like to view upgrade options?`)) {
            window.location.href = '/companies/subscription/plans/';
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    window.planLimitsChecker = new PlanLimitsChecker();
});
