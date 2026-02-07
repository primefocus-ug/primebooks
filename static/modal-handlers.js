/**
 * Modal form handlers for quick category and supplier creation
 */

import { getCookie, showSuccessMessage, showErrorMessage, FormValidator } from './form-base.js';

class ModalFormHandler {
    constructor(modalId, formId, submitUrl, selectId, itemType) {
        this.modal = $(`#${modalId}`);
        this.form = $(`#${formId}`);
        this.submitUrl = submitUrl;
        this.select = $(`#${selectId}`);
        this.itemType = itemType;
        this.validator = new FormValidator(`#${formId}`);

        this.init();
    }

    init() {
        // Handle form submission
        this.form.on('submit', (e) => {
            e.preventDefault();
            this.submit();
        });

        // Handle Enter key
        this.form.find('input, textarea').on('keypress', (e) => {
            if (e.which === 13 && !e.shiftKey && !$(e.target).is('textarea')) {
                e.preventDefault();
                this.submit();
            }
        });

        // Clear form when modal closes
        this.modal.on('hidden.bs.modal', () => {
            this.reset();
        });
    }

    validate() {
        this.validator.clearErrors();
        // Override in subclass
        return true;
    }

    submit() {
        if (!this.validate()) {
            this.validator.showErrors();
            return;
        }

        const formData = this.getFormData();
        const $saveBtn = this.modal.find('.btn-primary');
        const originalText = $saveBtn.html();

        // Show loading state
        $saveBtn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Saving...');

        $.ajax({
            url: this.submitUrl,
            type: 'POST',
            data: formData,
            dataType: 'json',
            success: (response) => this.handleSuccess(response),
            error: (xhr) => this.handleError(xhr),
            complete: () => {
                $saveBtn.prop('disabled', false).html(originalText);
            }
        });
    }

    getFormData() {
        const formData = this.form.serializeArray().reduce((obj, item) => {
            obj[item.name] = item.value;
            return obj;
        }, {});
        formData.csrfmiddlewaretoken = getCookie('csrftoken');
        return formData;
    }

    handleSuccess(response) {
        if (response.success) {
            const item = response[this.itemType];

            // Add new option to select
            const newOption = new Option(item.name, item.id, true, true);
            this.select.append(newOption).trigger('change');

            // Hide modal
            const modalInstance = bootstrap.Modal.getInstance(this.modal[0]);
            if (modalInstance) {
                modalInstance.hide();
            }

            // Reset form
            this.reset();

            // Show success message
            showSuccessMessage(`${this.itemType.charAt(0).toUpperCase() + this.itemType.slice(1)} "${item.name}" created successfully!`);
        } else {
            showErrorMessage(response.message || `Failed to create ${this.itemType}`);
        }
    }

    handleError(xhr) {
        console.error(`${this.itemType} save error:`, xhr.responseText);

        let errorMessage = `Error creating ${this.itemType}`;

        if (xhr.responseJSON && xhr.responseJSON.message) {
            errorMessage = xhr.responseJSON.message;
        } else if (xhr.responseJSON && xhr.responseJSON.errors) {
            // Handle field-specific errors
            const errors = xhr.responseJSON.errors;
            Object.keys(errors).forEach(field => {
                this.validator.addError(`#${field}`, errors[field].join(', '));
            });
            this.validator.showErrors();
            return;
        }

        showErrorMessage(errorMessage);
    }

    reset() {
        this.form[0].reset();
        this.validator.clearErrors();
    }
}

class CategoryModalHandler extends ModalFormHandler {
    validate() {
        this.validator.clearErrors();

        const name = $('#categoryName').val().trim();
        const categoryType = $('#categoryType').val();

        if (!name) {
            this.validator.addError('#categoryName', 'Category name is required');
        }

        if (!categoryType) {
            this.validator.addError('#categoryType', 'Category type is required');
        }

        return this.validator.isValid();
    }
}

class SupplierModalHandler extends ModalFormHandler {
    validate() {
        this.validator.clearErrors();

        const name = $('#supplierName').val().trim();
        const phone = $('#supplierPhone').val().trim();
        const email = $('#supplierEmail').val().trim();

        if (!name) {
            this.validator.addError('#supplierName', 'Supplier name is required');
        }

        if (!phone) {
            this.validator.addError('#supplierPhone', 'Phone number is required');
        }

        if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            this.validator.addError('#supplierEmail', 'Please enter a valid email address');
        }

        return this.validator.isValid();
    }
}

// Initialize modal handlers
function initializeModalHandlers(categoryCreateUrl, supplierCreateUrl) {
    new CategoryModalHandler(
        'addCategoryModal',
        'categoryQuickForm',
        categoryCreateUrl,
        'id_category',
        'category'
    );

    new SupplierModalHandler(
        'addSupplierModal',
        'supplierQuickForm',
        supplierCreateUrl,
        'id_supplier',
        'supplier'
    );
}

export { initializeModalHandlers };