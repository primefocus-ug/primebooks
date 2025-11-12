$(document).ready(function() {
    // Initialize DataTable
    const table = $('#salesTable').DataTable({
        "paging": false,
        "searching": false,
        "info": false,
        "ordering": true,
        "columnDefs": [
            { "orderable": false, "targets": [0, 8] }
        ],
        "order": [[2, "desc"]]
    });

    // Custom search functionality
    $('#quickSearch').on('keyup', function() {
        table.search(this.value).draw();
    });

    // Row selection functionality
    let selectedSales = [];

    $('.row-select').on('change', function() {
        const saleId = $(this).val();
        if (this.checked) {
            selectedSales.push(saleId);
        } else {
            selectedSales = selectedSales.filter(id => id !== saleId);
        }
        updateBulkActions();
    });

    $('#selectAllRows').on('change', function() {
        const checked = this.checked;
        $('.row-select').prop('checked', checked);

        if (checked) {
            selectedSales = $('.row-select').map(function() {
                return this.value;
            }).get();
        } else {
            selectedSales = [];
        }
        updateBulkActions();
    });

    function updateBulkActions() {
        const count = selectedSales.length;
        if (count > 0) {
            $('#bulkActions').addClass('show');
            $('#selectedCount').text(`${count} item${count > 1 ? 's' : ''} selected`);
            $('#selectedSales').val(JSON.stringify(selectedSales));
        } else {
            $('#bulkActions').removeClass('show');
        }
    }

    // Filter form auto-submit
    $('#filterForm input, #filterForm select').on('change', function() {
        // Auto-submit after short delay
        clearTimeout(window.filterTimeout);
        window.filterTimeout = setTimeout(function() {
            $('#filterForm').submit();
        }, 300);
    });

    // Quick search with debounce
    let searchTimeout;
    $('#quickSearch').on('input', function() {
        clearTimeout(searchTimeout);
        const query = $(this).val();

        searchTimeout = setTimeout(function() {
            table.search(query).draw();
        }, 300);
    });

    // Column visibility toggle
    $('#columnToggle input[type="checkbox"]').on('change', function() {
        const column = table.column($(this).closest('li').index());
        column.visible(this.checked);
    });

    // Initialize tooltips
    $('[data-bs-toggle="tooltip"]').tooltip();
});

// Export functions
function exportData(format) {
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = '{% url "sales:bulk_actions" %}';

    const csrfToken = document.createElement('input');
    csrfToken.type = 'hidden';
    csrfToken.name = 'csrfmiddlewaretoken';
    csrfToken.value = $('[name=csrfmiddlewaretoken]').val();

    const action = document.createElement('input');
    action.type = 'hidden';
    action.name = 'action';
    action.value = `export_${format}`;

    const selectedSales = document.createElement('input');
    selectedSales.type = 'hidden';
    selectedSales.name = 'selected_sales';
    selectedSales.value = JSON.stringify($('.row-select:checked').map(function() {
        return this.value;
    }).get());

    form.appendChild(csrfToken);
    form.appendChild(action);
    form.appendChild(selectedSales);

    document.body.appendChild(form);
    form.submit();
    document.body.removeChild(form);
}

// Sale actions
function printReceipt(saleId) {
    window.open(`/sales/${saleId}/print-receipt/`, '_blank');
}

function fiscalizeSale(saleId) {
    if (confirm('Are you sure you want to fiscalize this sale?')) {
        showLoading();

        $.ajax({
            url: '{% url "sales:bulk_actions" %}',
            method: 'POST',
            data: {
                'csrfmiddlewaretoken': $('[name=csrfmiddlewaretoken]').val(),
                'action': 'fiscalize',
                'selected_sales': JSON.stringify([saleId])
            },
            success: function(response) {
                hideLoading();
                showNotification('Sale fiscalized successfully!', 'success');
                location.reload();
            },
            error: function() {
                hideLoading();
                showNotification('Error fiscalizing sale', 'error');
            }
        });
    }
}

function showRefundModal(saleId) {
    // Load sale details for refund
    $.get(`/sales/${saleId}/`, function(data) {
        // Populate refund modal with sale data
        $('#refundModal').modal('show');
        $('#refundModal').data('sale-id', saleId);
    });
}

function processRefund() {
    const saleId = $('#refundModal').data('sale-id');
    const formData = $('#refundForm').serialize();

    showLoading();

    $.ajax({
        url: `/sales/${saleId}/refund/`,
        method: 'POST',
        data: formData,
        success: function(response) {
            hideLoading();
            $('#refundModal').modal('hide');
            showNotification('Refund processed successfully!', 'success');
            location.reload();
        },
        error: function() {
            hideLoading();
            showNotification('Error processing refund', 'error');
        }
    });
}

function voidSale(saleId) {
    const reason = prompt('Please enter reason for voiding this sale:');
    if (reason) {
        showLoading();

        $.ajax({
            url: `/sales/${saleId}/void/`,
            method: 'POST',
            data: {
                'csrfmiddlewaretoken': $('[name=csrfmiddlewaretoken]').val(),
                'void_reason': reason
            },
            success: function(response) {
                hideLoading();
                showNotification('Sale voided successfully!', 'success');
                location.reload();
            },
            error: function() {
                hideLoading();
                showNotification('Error voiding sale', 'error');
            }
        });
    }
}

function duplicateSale(saleId) {
    if (confirm('Create a new sale based on this one?')) {
        window.location.href = `/sales/create/?duplicate=${saleId}`;
    }
}

function emailReceipt(saleId) {
    const email = prompt('Enter email address:');
    if (email) {
        showLoading();

        $.ajax({
            url: `/sales/${saleId}/email-receipt/`,
            method: 'POST',
            data: {
                'csrfmiddlewaretoken': $('[name=csrfmiddlewaretoken]').val(),
                'email': email
            },
            success: function(response) {
                hideLoading();
                showNotification('Receipt sent successfully!', 'success');
            },
            error: function() {
                hideLoading();
                showNotification('Error sending receipt', 'error');
            }
        });
    }
}

function refreshTable() {
    location.reload();
}

function clearSelection() {
    $('.row-select').prop('checked', false);
    $('#selectAllRows').prop('checked', false);
    selectedSales = [];
    $('#bulkActions').removeClass('show');
}

// Load quick sale modal content
$('#quickSaleModal').on('show.bs.modal', function() {
    $.get('{% url "sales:quick_sale" %}', function(data) {
        $('#quickSaleContent').html(data);
    });
});

// Save filters functionality
$('#saveFilters').on('click', function() {
    const filters = $('#filterForm').serialize();
    localStorage.setItem('salesFilters', filters);
    showNotification('Filters saved!', 'success');
});

// Load saved filters on page load
$(document).ready(function() {
    const savedFilters = localStorage.getItem('salesFilters');
    if (savedFilters) {
        // Parse and apply saved filters
        const params = new URLSearchParams(savedFilters);
        params.forEach((value, key) => {
            $(`#filterForm [name="${key}"]`).val(value);
        });
    }
});