/**
 * Base form utilities and helpers
 */

// CSRF Token Helper
function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
        const cookies = document.cookie.split(';');
        for (let i = 0; i < cookies.length; i++) {
            const cookie = cookies[i].trim();
            if (cookie.substring(0, name.length + 1) === (name + '=')) {
                cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                break;
            }
        }
    }
    return cookieValue;
}

// Success Message Helper
function showSuccessMessage(message) {
    const alertHtml = `
        <div class="alert alert-success alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3" 
             style="z-index: 9999;" role="alert" aria-live="polite">
            <i class="fas fa-check-circle"></i> ${escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>`;

    $('body').append(alertHtml);

    setTimeout(() => {
        $('.alert-success').fadeOut(() => {
            $(this).remove();
        });
    }, 3000);
}

// Error Message Helper
function showErrorMessage(message) {
    const alertHtml = `
        <div class="alert alert-danger alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3" 
             style="z-index: 9999;" role="alert" aria-live="assertive">
            <i class="fas fa-exclamation-circle"></i> ${escapeHtml(message)}
            <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
        </div>`;

    $('body').append(alertHtml);

    setTimeout(() => {
        $('.alert-danger').fadeOut(function() {
            $(this).remove();
        });
    }, 5000);
}

// HTML Escape Function
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, m => map[m]);
}

// Debounce Helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// Form Validation Helper
class FormValidator {
    constructor(formId) {
        this.form = $(formId);
        this.errors = [];
    }

    clearErrors() {
        this.errors = [];
        $('.form-control, .form-select').removeClass('is-invalid');
        $('.invalid-feedback').remove();
        $('.alert-danger').remove();
    }

    addError(fieldId, message) {
        this.errors.push({ field: fieldId, message: message });
        $(fieldId).addClass('is-invalid');

        if (!$(fieldId).next('.invalid-feedback').length) {
            $(fieldId).after(`<div class="invalid-feedback d-block">${escapeHtml(message)}</div>`);
        }
    }

    showErrors() {
        if (this.errors.length === 0) return;

        const errorHtml = `
            <div class="alert alert-danger alert-dismissible fade show" role="alert">
                <h6 class="alert-heading">
                    <i class="fas fa-exclamation-circle"></i> Please fix the following errors:
                </h6>
                <ul class="mb-0">
                    ${this.errors.map(e => `<li>${escapeHtml(e.message)}</li>`).join('')}
                </ul>
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
            </div>`;

        this.form.prepend(errorHtml);
        $('html, body').animate({ scrollTop: 0 }, 500);
    }

    isValid() {
        return this.errors.length === 0;
    }
}

// Initialize Select2 globally
function initializeSelect2() {
    $('.select2').each(function() {
        if ($(this).data('select2')) {
            $(this).select2('destroy');
        }
    });

    $('.select2').select2({
        theme: 'bootstrap-5',
        width: '100%',
        dropdownAutoWidth: true
    });
}

// Initialize Tooltips
function initializeTooltips() {
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
}

export {
    getCookie,
    showSuccessMessage,
    showErrorMessage,
    escapeHtml,
    debounce,
    FormValidator,
    initializeSelect2,
    initializeTooltips
};