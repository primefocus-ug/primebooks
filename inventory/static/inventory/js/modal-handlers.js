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
        // Footer "Save" button triggers form submit — this is the primary entry point.
        // The form's own submit event does the actual work.
        this.getSaveButton().on('click', (e) => {
            e.preventDefault();
            this.form.trigger('submit');
        });

        // Handle form submit (covers both button click and Enter key)
        this.form.on('submit', (e) => {
            e.preventDefault();
            this.submit();
        });

        // Enter key inside inputs submits the form
        this.form.find('input, textarea').on('keypress', (e) => {
            if (e.which === 13 && !e.shiftKey && !$(e.target).is('textarea')) {
                e.preventDefault();
                this.form.trigger('submit');
            }
        });

        // Clear form when modal closes
        this.modal.on('hidden.bs.modal', () => {
            this.reset();
        });
    }

    // Subclasses can override this to return the correct footer button
    getSaveButton() {
        return this.modal.find('.btn-primary');
    }

    validate() {
        // Override in subclass with field-specific rules
        return true;
    }

    submit() {
        this.validator.clearErrors();

        if (!this.validate()) {
            this.validator.showErrors();
            return;
        }

        const formData = this.getFormData();
        const $saveBtn = this.getSaveButton();
        const originalHtml = $saveBtn.html();

        $saveBtn.prop('disabled', true).html(
            '<i class="fas fa-spinner fa-spin"></i> Saving...'
        );

        $.ajax({
            url: this.submitUrl,
            type: 'POST',
            data: formData,
            dataType: 'json',
            success: (response) => this.handleSuccess(response),
            error: (xhr) => this.handleError(xhr),
            complete: () => {
                $saveBtn.prop('disabled', false).html(originalHtml);
            }
        });
    }

    getFormData() {
        // Serialize all form fields and inject the CSRF token
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
            const label = this.itemType.charAt(0).toUpperCase() + this.itemType.slice(1);

            // Add the newly created item as a selected option in the main form select
            const newOption = new Option(item.name, item.id, true, true);
            this.select.append(newOption).trigger('change');

            // Close the modal
            const modalInstance = bootstrap.Modal.getInstance(this.modal[0]);
            if (modalInstance) {
                modalInstance.hide();
            }

            this.reset();
            showSuccessMessage(`${label} "${item.name}" created successfully!`);
        } else {
            showErrorMessage(response.message || `Failed to create ${this.itemType}.`);
        }
    }

    handleError(xhr) {
        console.error(`${this.itemType} save error:`, xhr.status, xhr.responseText);

        if (xhr.responseJSON) {
            const json = xhr.responseJSON;

            if (json.errors) {
                // Field-level validation errors returned by the server
                Object.entries(json.errors).forEach(([field, messages]) => {
                    this.validator.addError(`#${field}`, messages.join(', '));
                });
                this.validator.showErrors();
                return;
            }

            if (json.message) {
                showErrorMessage(json.message);
                return;
            }
        }

        showErrorMessage(`Error creating ${this.itemType}. Please try again.`);
    }

    reset() {
        this.form[0].reset();
        this.validator.clearErrors();
    }
}

// ── Category ─────────────────────────────────────────────────────────────────

class CategoryModalHandler extends ModalFormHandler {
    init() {
        super.init();

        // Auto-generate category code from name
        $('#generateCategoryCodeModal').on('click', () => {
            const name = $('#categoryName').val().trim();
            if (!name) {
                showErrorMessage('Enter a category name first.');
                return;
            }
            const code = name
                .toUpperCase()
                .replace(/[^A-Z0-9\s]/g, '')
                .split(/\s+/)
                .map(w => w.substring(0, 3))
                .join('-');
            $('#categoryCode').val(code);
        });
    }

    getSaveButton() {
        return $('#saveCategoryBtn');
    }

    validate() {
        const name = $('#categoryName').val().trim();
        const categoryType = $('#categoryType').val();

        if (!name) {
            this.validator.addError('#categoryName', 'Category name is required.');
        }
        if (!categoryType) {
            this.validator.addError('#categoryType', 'Category type is required.');
        }

        return this.validator.isValid();
    }
}

// ── Supplier ──────────────────────────────────────────────────────────────────

class SupplierModalHandler extends ModalFormHandler {
    getSaveButton() {
        return $('#saveSupplierBtn');
    }

    validate() {
        const name = $('#supplierName').val().trim();
        const phone = $('#supplierPhone').val().trim();
        const email = $('#supplierEmail').val().trim();

        if (!name) {
            this.validator.addError('#supplierName', 'Supplier name is required.');
        }
        if (!phone) {
            this.validator.addError('#supplierPhone', 'Phone number is required.');
        }
        if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
            this.validator.addError('#supplierEmail', 'Please enter a valid email address.');
        }

        return this.validator.isValid();
    }
}

// ── Initializer ───────────────────────────────────────────────────────────────

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