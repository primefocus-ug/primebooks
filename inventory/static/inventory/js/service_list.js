$(document).ready(function() {
    'use strict';

    // ============================================
    // CONFIGURATION - Get URLs from data attributes
    // ============================================

    const urlConfig = document.getElementById('urls-config');
    const URLS = {
        datatable: urlConfig ? urlConfig.dataset.datatableUrl : '/inventory/api/services/datatable/',
        create: urlConfig ? urlConfig.dataset.createUrl : '/inventory/services/add/',
        update: (id) => `/inventory/services/${id}/edit/`,
        delete: (id) => `/inventory/services/${id}/delete/`,
        detail: (id) => `/inventory/services/${id}/`,
        bulkActions: '/inventory/api/services/bulk-actions/',
        efrisSync: (id) => `/inventory/api/services/${id}/efris-sync/`,
        categoryDetail: (id) => `/inventory/api/categories/${id}/`,
    };

    console.log('Datatable URL:', URLS.datatable); // Debug log

    let selectedServices = [];
    let servicesTable;
    let deleteServiceId = null;

    // ============================================
    // DATATABLES INITIALIZATION
    // ============================================

    function initializeDataTable() {
        servicesTable = $('#servicesTable').DataTable({
            processing: true,
            serverSide: true,
            ajax: {
                url: URLS.datatable,
                type: 'GET',
                data: function(d) {
                    // Add filter parameters to match your Django view
                    d.search = $('#id_search').val();
                    d.category = $('#id_category').val();
                    d.tax_rate = $('#id_tax_rate').val();
                    d.efris_status = $('#id_efris_status').val();
                    d.is_active = $('#id_is_active').val();

                    console.log('DataTables request data:', d);
                },
                dataSrc: function (json) {
                    console.log('DataTables response:', json);
                    if (json.error) {
                        console.error('Server error:', json.error);
                        showAlert('Error loading services: ' + json.error, 'danger');
                        return [];
                    }
                    return json.data;
                },
                error: function(xhr, error, thrown) {
                    console.error('DataTables AJAX error:', error, thrown);
                    console.error('Response:', xhr.responseText);
                    showAlert('Error loading services data. Please check console for details.', 'danger');
                }
            },
            columns: [
                {
                    data: null,
                    orderable: false,
                    searchable: false,
                    render: function(data, type, row) {
                        return `<input type="checkbox" class="form-check-input service-checkbox table-checkbox" data-id="${row.id}">`;
                    }
                },
                {
                    data: 'name',
                    render: function(data) {
                        return data || '-';
                    }
                },
                {
                    data: 'code',
                    render: function(data) {
                        return data || '-';
                    }
                },
                {
                    data: 'category',
                    render: function(data) {
                        return data || '-';
                    }
                },
                {
                    data: 'unit_price',
                    className: 'text-end',
                    render: function(data) {
                        return data || '-';
                    }
                },
                {
                    data: 'final_price',
                    className: 'text-end',
                    render: function(data) {
                        return data || '-';
                    }
                },
                {
                    data: 'efris_status',
                    orderable: false,
                    searchable: false,
                    render: function(data) {
                        return data || '-';
                    }
                },
                {
                    data: 'status',
                    orderable: false,
                    searchable: false,
                    render: function(data) {
                        return data || '-';
                    }
                },
                {
                    data: 'actions',
                    orderable: false,
                    searchable: false,
                    className: 'text-center',
                    render: function(data) {
                        return data || 'No actions available';
                    }
                }
            ],
            order: [[1, 'asc']],
            pageLength: 25,
            lengthMenu: [[10, 25, 50, 100], [10, 25, 50, 100]],
            responsive: true,
            language: {
                processing: '<i class="bi bi-hourglass-split"></i> Loading...',
                emptyTable: 'No services found',
                zeroRecords: 'No matching services found',
                info: 'Showing _START_ to _END_ of _TOTAL_ entries',
                infoEmpty: 'Showing 0 to 0 of 0 entries',
                infoFiltered: '(filtered from _MAX_ total entries)',
                lengthMenu: 'Show _MENU_ entries',
                loadingRecords: 'Loading...',
                search: 'Search:',
                paginate: {
                    first: 'First',
                    last: 'Last',
                    next: 'Next',
                    previous: 'Previous'
                }
            },
            drawCallback: function() {
                // Reinitialize tooltips
                $('[data-bs-toggle="tooltip"]').tooltip();

                // Update checkbox states
                updateCheckboxStates();
            },
            initComplete: function() {
                console.log('DataTable initialized successfully');
            }
        });
    }

    // ============================================
    // FILTER HANDLING
    // ============================================

    function initializeFilters() {
        // Apply filters when form values change
        $('#id_search, #id_category, #id_tax_rate, #id_efris_status, #id_is_active').on('change keyup', function() {
            servicesTable.ajax.reload();
        });

        // Clear filters
        $('#clearFilters').on('click', function() {
            $('#filterForm')[0].reset();
            servicesTable.ajax.reload();
        });

        // Enter key in search field
        $('#id_search').on('keypress', function(e) {
            if (e.which === 13) {
                servicesTable.ajax.reload();
                e.preventDefault();
            }
        });
    }

    // ============================================
    // CHECKBOX SELECTION
    // ============================================

    function initializeCheckboxes() {
        // Select all checkbox
        $('#selectAllServices').on('change', function() {
            const isChecked = $(this).prop('checked');
            $('.service-checkbox:visible').prop('checked', isChecked);
            updateSelectedServices();
        });

        // Individual checkbox change
        $(document).on('change', '.service-checkbox', function() {
            updateSelectedServices();
        });
    }

    function updateSelectedServices() {
        selectedServices = [];
        $('.service-checkbox:checked').each(function() {
            selectedServices.push($(this).data('id'));
        });

        // Enable/disable bulk actions button
        $('#bulkActionsBtn').prop('disabled', selectedServices.length === 0);

        // Update select all checkbox state
        const visibleCheckboxes = $('.service-checkbox:visible').length;
        const checkedCheckboxes = $('.service-checkbox:checked:visible').length;
        $('#selectAllServices').prop('checked', checkedCheckboxes === visibleCheckboxes && visibleCheckboxes > 0);
        $('#selectAllServices').prop('indeterminate', checkedCheckboxes > 0 && checkedCheckboxes < visibleCheckboxes);
    }

    function updateCheckboxStates() {
        $('.service-checkbox').each(function() {
            const id = $(this).data('id');
            $(this).prop('checked', selectedServices.includes(id));
        });
        updateSelectedServices();
    }

    // ============================================
    // SERVICE MODAL HANDLING
    // ============================================

    function initializeModals() {
        // Add Service button
        $('#addServiceBtn').on('click', function() {
            loadServiceForm(URLS.create, 'Add Service');
        });

        // Edit Service button
        $(document).on('click', '.edit-service', function(e) {
            e.preventDefault();
            const serviceId = $(this).data('id');
            loadServiceForm(URLS.update(serviceId), 'Edit Service');
        });

        // Delete Service button
        $(document).on('click', '.delete-service', function(e) {
            e.preventDefault();
            deleteServiceId = $(this).data('id');
            $('#deleteModal').modal('show');
        });

        // Confirm delete
        $('#confirmDeleteBtn').on('click', function() {
            if (!deleteServiceId) return;

            const $btn = $(this);
            const originalText = $btn.html();

            $btn.prop('disabled', true).html('<i class="bi bi-hourglass-split"></i> Deleting...');

            $.ajax({
                url: URLS.delete(deleteServiceId),
                type: 'POST',
                headers: {
                    'X-CSRFToken': getCSRFToken()
                },
                success: function(response) {
                    if (response.success) {
                        showAlert('Service deleted successfully', 'success');
                        $('#deleteModal').modal('hide');
                        servicesTable.ajax.reload(null, false);
                    } else {
                        showAlert(response.error || 'Error deleting service', 'danger');
                    }
                },
                error: function(xhr) {
                    showAlert('Error deleting service. Please try again.', 'danger');
                },
                complete: function() {
                    $btn.prop('disabled', false).html(originalText);
                    deleteServiceId = null;
                }
            });
        });

        // Modal hidden event
        $('#serviceModal').on('hidden.bs.modal', function() {
            $('#serviceModalBody').html('');
        });
    }

    // ============================================
    // LOAD SERVICE FORM
    // ============================================

    function loadServiceForm(url, title) {
        $('#modalTitle').text(title);
        $('#serviceModalBody').html(`
            <div class="text-center py-4">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <p class="mt-2">Loading form...</p>
            </div>
        `);
        $('#serviceModal').modal('show');

        $.ajax({
            url: url,
            type: 'GET',
            success: function(response) {
                $('#serviceModalBody').html(response);
                initializeServiceForm();
            },
            error: function(xhr) {
                showAlert('Error loading form. Please try again.', 'danger');
                $('#serviceModal').modal('hide');
            }
        });
    }

    // ============================================
    // INITIALIZE SERVICE FORM
    // ============================================

    function initializeServiceForm() {
        const $form = $('#serviceModalBody').find('form');

        // Initialize EFRIS category validation
        const categorySelect = $('#id_category');
        if (categorySelect.length) {
            categorySelect.on('change', function() {
                const categoryId = $(this).val();
                if (categoryId) {
                    validateEFRISCategory(categoryId);
                } else {
                    $('#efris-validation-message').remove();
                }
            });

            // Trigger change on load if category is preselected
            if (categorySelect.val()) {
                categorySelect.trigger('change');
            }
        }

        // Form submission
        $form.on('submit', function(e) {
            e.preventDefault();
            submitServiceForm($(this));
        });

        // Price calculations
        $('#id_unit_price, #id_discount_percentage').on('input', function() {
            calculateFinalPrice();
        });

        // Tax rate changes
        $('#id_tax_rate').on('change', function() {
            toggleExciseDutyField();
        });

        // Initialize form state
        calculateFinalPrice();
        toggleExciseDutyField();
    }

    // ============================================
    // VALIDATE EFRIS CATEGORY
    // ============================================

    function validateEFRISCategory(categoryId) {
        $.ajax({
            url: URLS.categoryDetail(categoryId),
            type: 'GET',
            success: function(data) {
                const validationDiv = $('#efris-validation-message');
                validationDiv.remove();

                let message = '';
                let alertClass = '';

                if (!data.efris_commodity_category_code) {
                    message = '⚠️ This category does not have an EFRIS commodity category assigned.';
                    alertClass = 'alert-warning';
                } else if (!data.efris_is_leaf_node) {
                    message = '❌ This category\'s EFRIS commodity category is not a leaf node. Services cannot use non-leaf nodes.';
                    alertClass = 'alert-danger';
                } else if (data.category_type !== 'service') {
                    message = '❌ This is not a service category. Please select a service category.';
                    alertClass = 'alert-danger';
                } else {
                    message = `✅ Valid EFRIS Category: ${data.efris_commodity_category_name}`;
                    alertClass = 'alert-success';
                }

                const alertHtml = `
                    <div id="efris-validation-message" class="alert ${alertClass} mt-2">
                        ${message}
                    </div>
                `;

                $('#id_category').closest('.mb-3').append(alertHtml);
            },
            error: function() {
                console.error('Failed to validate EFRIS category');
            }
        });
    }

    // ============================================
    // CALCULATE FINAL PRICE
    // ============================================

    function calculateFinalPrice() {
        const unitPrice = parseFloat($('#id_unit_price').val()) || 0;
        const discount = parseFloat($('#id_discount_percentage').val()) || 0;
        const finalPrice = unitPrice - (unitPrice * discount / 100);

        let priceDisplay = $('#final-price-display');
        if (priceDisplay.length === 0) {
            priceDisplay = $('<div id="final-price-display" class="alert alert-info mt-2"></div>');
            $('#id_discount_percentage').closest('.mb-3').after(priceDisplay);
        }

        priceDisplay.html(`<strong>Final Price:</strong> UGX ${finalPrice.toLocaleString('en-UG', {minimumFractionDigits: 2})}`);
    }

    // ============================================
    // TOGGLE EXCISE DUTY FIELD
    // ============================================

    function toggleExciseDutyField() {
        const taxRate = $('#id_tax_rate').val();
        const exciseDutyGroup = $('#id_excise_duty_rate').closest('.mb-3');

        if (taxRate === 'E') {
            exciseDutyGroup.show();
            $('#id_excise_duty_rate').prop('required', true);
        } else {
            exciseDutyGroup.hide();
            $('#id_excise_duty_rate').prop('required', false);
            $('#id_excise_duty_rate').val('0');
        }
    }

    // ============================================
    // SUBMIT SERVICE FORM
    // ============================================

    function submitServiceForm($form) {
        const submitBtn = $form.find('[type="submit"]');
        const originalBtnText = submitBtn.html();

        submitBtn.prop('disabled', true).html('<i class="bi bi-hourglass-split"></i> Saving...');

        // Clear previous errors
        $('.is-invalid').removeClass('is-invalid');
        $('.invalid-feedback').remove();
        $('.alert-danger').remove();

        const formData = new FormData($form[0]);

        $.ajax({
            url: $form.attr('action'),
            type: 'POST',
            data: formData,
            processData: false,
            contentType: false,
            headers: {
                'X-CSRFToken': getCSRFToken()
            },
            success: function(response) {
                if (response.success) {
                    showAlert(response.message || 'Service saved successfully', 'success');
                    $('#serviceModal').modal('hide');
                    servicesTable.ajax.reload(null, false);
                } else {
                    displayFormErrors(response.errors || {});
                }
            },
            error: function(xhr) {
                if (xhr.status === 400 && xhr.responseJSON) {
                    displayFormErrors(xhr.responseJSON.errors || {});
                } else {
                    showAlert('Error saving service. Please try again.', 'danger');
                }
            },
            complete: function() {
                submitBtn.prop('disabled', false).html(originalBtnText);
            }
        });
    }

    // ============================================
    // DISPLAY FORM ERRORS
    // ============================================

    function displayFormErrors(errors) {
        for (const [field, messages] of Object.entries(errors)) {
            const $field = $(`#id_${field}`);

            if ($field.length) {
                $field.addClass('is-invalid');
                const errorHtml = `<div class="invalid-feedback">${Array.isArray(messages) ? messages.join(', ') : messages}</div>`;
                $field.after(errorHtml);
            } else if (field === 'non_field_errors' || field === '__all__') {
                const errorHtml = `<div class="alert alert-danger">${Array.isArray(messages) ? messages.join('<br>') : messages}</div>`;
                $('#serviceModalBody form').prepend(errorHtml);
            }
        }

        // Scroll to first error
        const firstError = $('.is-invalid').first();
        if (firstError.length) {
            firstError[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    // ============================================
    // BULK ACTIONS
    // ============================================

    function initializeBulkActions() {
        $('.bulk-action').on('click', function(e) {
            e.preventDefault();

            if (selectedServices.length === 0) {
                showAlert('Please select at least one service.', 'warning');
                return;
            }

            const action = $(this).data('action');
            const actionText = $(this).text().trim();

            // Confirm dangerous actions
            if (action === 'delete') {
                if (!confirm(`Are you sure you want to delete ${selectedServices.length} service(s)? This action cannot be undone.`)) {
                    return;
                }
            }

            performBulkAction(action, actionText);
        });
    }

    function performBulkAction(action, actionText) {
        $.ajax({
            url: URLS.bulkActions,
            type: 'POST',
            data: {
                action: action,
                service_ids: selectedServices.join(',')
            },
            headers: {
                'X-CSRFToken': getCSRFToken()
            },
            success: function(response) {
                if (response.success) {
                    showAlert(response.message || `Bulk action completed successfully`, 'success');
                    selectedServices = [];
                    $('#selectAllServices').prop('checked', false);
                    servicesTable.ajax.reload(null, false);
                } else {
                    showAlert(response.error || 'Bulk action failed', 'danger');
                }
            },
            error: function(xhr) {
                showAlert('Error performing bulk action. Please try again.', 'danger');
            }
        });
    }

    // ============================================
    // UTILITY FUNCTIONS
    // ============================================

    function showAlert(message, type = 'info') {
        // Remove existing alerts
        $('.alert-dismissible').alert('close');

        const alertHtml = `
            <div class="alert alert-${type} alert-dismissible fade show" role="alert">
                <i class="bi ${getAlertIcon(type)} me-2"></i>
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;

        $('.main-content').prepend(alertHtml);

        // Auto-dismiss after 5 seconds (except for danger alerts)
        if (type !== 'danger') {
            setTimeout(function() {
                $('.alert').alert('close');
            }, 5000);
        }

        // Scroll to top
        $('html, body').animate({ scrollTop: 0 }, 300);
    }

    function getAlertIcon(type) {
        const icons = {
            success: 'bi-check-circle-fill',
            danger: 'bi-exclamation-triangle-fill',
            warning: 'bi-exclamation-triangle-fill',
            info: 'bi-info-circle-fill'
        };
        return icons[type] || 'bi-info-circle-fill';
    }

    function getCSRFToken() {
        return $('[name=csrfmiddlewaretoken]').val() || getCookie('csrftoken');
    }

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

    // ============================================
    // INITIALIZATION
    // ============================================

    function initialize() {
        initializeDataTable();
        initializeFilters();
        initializeCheckboxes();
        initializeModals();
        initializeBulkActions();

        // Setup CSRF for AJAX
        $.ajaxSetup({
            beforeSend: function(xhr, settings) {
                if (!this.crossDomain) {
                    xhr.setRequestHeader("X-CSRFToken", getCSRFToken());
                }
            }
        });

        console.log('Service management initialized');
    }

    // Start the application
    initialize();
});