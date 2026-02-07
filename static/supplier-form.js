/**
 * Supplier form specific logic
 */

import { FormValidator } from './form-base.js';

class SupplierFormHandler {
    constructor() {
        this.form = $('#supplierForm');
        this.validator = new FormValidator('#supplierForm');
        this.init();
    }

    init() {
        this.initializeValidation();
    }

    initializeValidation() {
        this.form.on('submit', (e) => {
            this.validator.clearErrors();

            // Name validation
            if (!$('#id_name').val().trim()) {
                this.validator.addError('#id_name', 'Supplier name is required');
            }

            // Phone validation
            if (!$('#id_phone').val().trim()) {
                this.validator.addError('#id_phone', 'Phone number is required');
            }

            // Email validation (if provided)
            const email = $('#id_email').val().trim();
            if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
                this.validator.addError('#id_email', 'Please enter a valid email address');
            }

            if (!this.validator.isValid()) {
                e.preventDefault();
                this.validator.showErrors();
                return false;
            }
        });
    }
}

// Initialize supplier form
function initializeSupplierForm() {
    if ($('#supplierForm').length) {
        new SupplierFormHandler();
    }
}

export { initializeSupplierForm };