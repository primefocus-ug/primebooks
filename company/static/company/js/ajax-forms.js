class AjaxFormHandler {
    constructor(formId, options = {}) {
        this.form = document.getElementById(formId);
        this.options = {
            onSuccess: options.onSuccess || this.defaultSuccess,
            onError: options.onError || this.defaultError,
            onValidationError: options.onValidationError || this.defaultValidationError,
            beforeSubmit: options.beforeSubmit || null,
            ...options
        };

        if (this.form) {
            this.init();
        }
    }

    init() {
        this.form.addEventListener('submit', (e) => this.handleSubmit(e));
    }

    async handleSubmit(e) {
        e.preventDefault();

        // Before submit callback
        if (this.options.beforeSubmit && !this.options.beforeSubmit()) {
            return;
        }

        const submitBtn = this.form.querySelector('[type="submit"]');
        const originalText = submitBtn.innerHTML;

        // Show loading state
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Saving...';

        // Clear previous errors
        this.clearErrors();

        try {
            const formData = new FormData(this.form);
            const response = await fetch(this.form.action, {
                method: this.form.method,
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': this.getCsrfToken()
                }
            });

            const data = await response.json();

            if (response.ok && data.success) {
                this.options.onSuccess(data);
            } else {
                if (data.errors) {
                    this.options.onValidationError(data.errors);
                } else {
                    this.options.onError(data.message || 'An error occurred');
                }
            }
        } catch (error) {
            console.error('Form submission error:', error);
            this.options.onError('Network error occurred');
        } finally {
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalText;
        }
    }

    clearErrors() {
        this.form.querySelectorAll('.invalid-feedback').forEach(el => el.remove());
        this.form.querySelectorAll('.is-invalid').forEach(el => el.classList.remove('is-invalid'));
    }

    showFieldError(fieldName, message) {
        const field = this.form.querySelector(`[name="${fieldName}"]`);
        if (field) {
            field.classList.add('is-invalid');
            const errorDiv = document.createElement('div');
            errorDiv.className = 'invalid-feedback';
            errorDiv.textContent = message;
            field.parentNode.appendChild(errorDiv);
        }
    }

    getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    defaultSuccess(data) {
        this.showNotification('success', data.message || 'Saved successfully');
        if (data.redirect) {
            setTimeout(() => window.location.href = data.redirect, 1500);
        }
    }

    defaultError(message) {
        this.showNotification('error', message);
    }

    defaultValidationError(errors) {
        for (const [field, messages] of Object.entries(errors)) {
            this.showFieldError(field, Array.isArray(messages) ? messages.join(', ') : messages);
        }
        this.showNotification('warning', 'Please fix the errors below');
    }

    showNotification(type, message) {
        // Reuse notification system from company-profile.js
        if (window.companyProfile) {
            window.companyProfile.showNotification(type, message);
        } else {
            alert(message);
        }
    }
}

// Export for use in other scripts
window.AjaxFormHandler = AjaxFormHandler;


"""


################################################################################
# INSTRUCTIONS FOR COPYING
################################################################################
"""
COPY INSTRUCTIONS:
==================

1. Copy FILE 2 (ajax-forms.js) to:
   static/company/js/ajax-forms.js

2. Copy FILE 3 (billing_service.py) to:
   company/services/billing_service.py

3. Copy FILE 4 (notification_service.py) to:
   company/services/notification_service.py

4. For the HTML templates, they already exist as separate artifacts:
   - team.html → artifact: team_tab_template
   - branches.html → artifact: branches_tab_template
   - efris.html → artifact: efris_tab_template
   - activity.html → artifact: activity_tab_template
   - plans.html → artifact: subscription_plans_template

5. company/views.py - Keep your existing old views.py file as is.
   The new modular structure is in company/views/ folder.

That's it! All files are now available.
"""