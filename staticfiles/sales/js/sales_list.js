// Wait for DOM and jQuery to be ready
$(document).ready(function() {
    console.log('Sales list JavaScript loaded');

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

    // ===== ROW SELECTION FUNCTIONALITY =====
    window.selectedSales = [];

    // Individual row selection
    $(document).on('change', '.row-select', function() {
        const saleId = $(this).val();
        if (this.checked) {
            if (!window.selectedSales.includes(saleId)) {
                window.selectedSales.push(saleId);
            }
        } else {
            window.selectedSales = window.selectedSales.filter(id => id !== saleId);
        }
        updateBulkActions();
        updateSelectAllCheckbox();
    });

    // Select all rows
    $('#selectAllRows, #selectAll').on('change', function() {
        const checked = this.checked;
        $('.row-select').prop('checked', checked);

        if (checked) {
            window.selectedSales = $('.row-select').map(function() {
                return this.value;
            }).get();
        } else {
            window.selectedSales = [];
        }
        updateBulkActions();
    });

    function updateSelectAllCheckbox() {
        const totalCheckboxes = $('.row-select').length;
        const checkedCheckboxes = $('.row-select:checked').length;

        $('#selectAllRows, #selectAll').prop('checked', totalCheckboxes === checkedCheckboxes && totalCheckboxes > 0);
    }

    function updateBulkActions() {
        const count = window.selectedSales.length;
        if (count > 0) {
            $('#bulkActions').addClass('show');
            $('#selectedCount').text(`${count} item${count > 1 ? 's' : ''} selected`);
            $('#selectedSales').val(JSON.stringify(window.selectedSales));
        } else {
            $('#bulkActions').removeClass('show');
        }
    }

    // ===== COLUMN VISIBILITY TOGGLE =====
    $('#columnToggle input[type="checkbox"]').each(function(index) {
        $(this).data('column-index', index + 1);
    });

    $(document).on('change', '#columnToggle input[type="checkbox"]', function() {
        const columnIndex = $(this).data('column-index');
        const column = table.column(columnIndex);
        column.visible(this.checked);
    });

    // Filter form auto-submit
    $('#filterForm input, #filterForm select').on('change', function() {
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

    // Initialize tooltips
    if (typeof bootstrap !== 'undefined') {
        const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
        tooltipTriggerList.map(function (tooltipTriggerEl) {
            return new bootstrap.Tooltip(tooltipTriggerEl);
        });
    }

    // Save filters functionality
    $(document).on('click', '#saveFilters', function(e) {
        e.preventDefault();
        const filters = $('#filterForm').serialize();
        localStorage.setItem('salesFilters', filters);
        showNotification('Filters saved successfully!', 'success');
    });

    // Load saved filters on page load
    const savedFilters = localStorage.getItem('salesFilters');
    if (savedFilters) {
        const params = new URLSearchParams(savedFilters);
        params.forEach((value, key) => {
            $(`#filterForm [name="${key}"]`).val(value);
        });
    }
});

// ===== UTILITY FUNCTIONS (Global scope) =====
function getCsrfToken() {
    return $('[name=csrfmiddlewaretoken]').val() ||
           document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
           '';
}

function showLoading() {
    if ($('#loadingOverlay').length === 0) {
        $('body').append(`
            <div id="loadingOverlay" style="
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0,0,0,0.5);
                display: flex;
                align-items: center;
                justify-content: center;
                z-index: 9999;
            ">
                <div class="spinner-border text-light" role="status" style="width: 3rem; height: 3rem;">
                    <span class="visually-hidden">Loading...</span>
                </div>
            </div>
        `);
    }
}

function hideLoading() {
    $('#loadingOverlay').remove();
}

function showNotification(message, type = 'info') {
    $('.notification-toast').remove();

    const bgClass = {
        'success': 'bg-success',
        'error': 'bg-danger',
        'warning': 'bg-warning',
        'info': 'bg-info'
    }[type] || 'bg-info';

    const icon = {
        'success': 'fa-check-circle',
        'error': 'fa-exclamation-circle',
        'warning': 'fa-exclamation-triangle',
        'info': 'fa-info-circle'
    }[type] || 'fa-info-circle';

    const notification = $(`
        <div class="notification-toast position-fixed top-0 end-0 m-3 p-3 ${bgClass} text-white rounded shadow-lg" 
             style="z-index: 10000; min-width: 250px; animation: slideInRight 0.3s ease-out;">
            <div class="d-flex align-items-center">
                <i class="fas ${icon} me-2"></i>
                <span>${message}</span>
                <button type="button" class="btn-close btn-close-white ms-auto" onclick="$(this).parent().parent().remove()"></button>
            </div>
        </div>
    `);

    $('body').append(notification);

    setTimeout(() => {
        notification.fadeOut(300, function() {
            $(this).remove();
        });
    }, 5000);
}

// Add CSS animation
if (!document.getElementById('notification-animations')) {
    $('head').append(`
        <style id="notification-animations">
            @keyframes slideInRight {
                from {
                    transform: translateX(100%);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
        </style>
    `);
}

// ===== EXPORT FUNCTIONS =====
function exportData(format) {
    console.log('Export function called for format:', format);

    const selectedSales = $('.row-select:checked').map(function() {
        return this.value;
    }).get();

    if (selectedSales.length === 0) {
        if (!confirm('No sales selected. Export all filtered sales?')) {
            return;
        }
    }

    const form = document.createElement('form');
    form.method = 'POST';
    form.action = window.location.pathname;

    const csrfToken = document.createElement('input');
    csrfToken.type = 'hidden';
    csrfToken.name = 'csrfmiddlewaretoken';
    csrfToken.value = getCsrfToken();
    form.appendChild(csrfToken);

    const actionInput = document.createElement('input');
    actionInput.type = 'hidden';
    actionInput.name = 'action';
    actionInput.value = `export_${format}`;
    form.appendChild(actionInput);

    if (selectedSales.length > 0) {
        const selectedInput = document.createElement('input');
        selectedInput.type = 'hidden';
        selectedInput.name = 'selected_sales';
        selectedInput.value = JSON.stringify(selectedSales);
        form.appendChild(selectedInput);
    }

    $('#exportFiltersForm input').each(function() {
        if ($(this).val()) {
            const input = document.createElement('input');
            input.type = 'hidden';
            input.name = $(this).attr('name');
            input.value = $(this).val();
            form.appendChild(input);
        }
    });

    document.body.appendChild(form);
    form.submit();
    document.body.removeChild(form);

    showNotification(`Preparing ${format.toUpperCase()} export...`, 'info');
}

// ===== PRINT FUNCTIONS =====
function printReceipt(saleId) {
    const printOptions = `
        <div class="modal fade" id="printOptionsModal" tabindex="-1">
            <div class="modal-dialog modal-dialog-centered">
                <div class="modal-content">
                    <div class="modal-header">
                        <h5 class="modal-title">
                            <i class="fas fa-print me-2"></i>Print Options
                        </h5>
                        <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
                    </div>
                    <div class="modal-body">
                        <div class="d-grid gap-3">
                            <button class="btn btn-primary btn-lg" onclick="printReceiptDirect(${saleId})">
                                <i class="fas fa-print me-2"></i>
                                Print Receipt (Direct)
                            </button>
                            <button class="btn btn-outline-primary btn-lg" onclick="downloadReceiptPDF(${saleId})">
                                <i class="fas fa-file-pdf me-2"></i>
                                Download PDF Receipt
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    `;

    $('#printOptionsModal').remove();
    $('body').append(printOptions);

    const modal = new bootstrap.Modal(document.getElementById('printOptionsModal'));
    modal.show();

    $('#printOptionsModal').on('hidden.bs.modal', function () {
        $(this).remove();
    });
}

function printReceiptDirect(saleId) {
    $('#printOptionsModal').modal('hide');

    const printWindow = window.open(`/sales/${saleId}/print-receipt/`, '_blank');

    if (printWindow) {
        printWindow.onload = function() {
            setTimeout(function() {
                printWindow.print();
            }, 500);
        };
    } else {
        showNotification('Please allow popups to print receipts', 'warning');
    }
}

function downloadReceiptPDF(saleId) {
    $('#printOptionsModal').modal('hide');
    showLoading();

    const downloadUrl = `/sales/${saleId}/print-receipt/?format=pdf`;

    fetch(downloadUrl)
        .then(response => {
            if (!response.ok) throw new Error('Download failed');
            return response.blob();
        })
        .then(blob => {
            hideLoading();

            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.style.display = 'none';
            a.href = url;
            a.download = `receipt_${saleId}.pdf`;

            document.body.appendChild(a);
            a.click();

            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);

            showNotification('Receipt downloaded successfully!', 'success');
        })
        .catch(error => {
            hideLoading();
            console.error('Download error:', error);
            showNotification('Error downloading receipt. Opening in new tab instead...', 'warning');
            window.open(downloadUrl, '_blank');
        });
}

// ===== OTHER SALE ACTIONS =====
function fiscalizeSale(saleId) {
    if (confirm('Are you sure you want to fiscalize this sale?')) {
        showLoading();

        $.ajax({
            url: `/sales/${saleId}/fiscalize/`,
            method: 'POST',
            data: {
                'csrfmiddlewaretoken': getCsrfToken()
            },
            success: function(response) {
                hideLoading();
                showNotification('Sale fiscalized successfully!', 'success');
                setTimeout(() => location.reload(), 1500);
            },
            error: function(xhr) {
                hideLoading();
                const errorMsg = xhr.responseJSON?.error || 'Error fiscalizing sale';
                showNotification(errorMsg, 'error');
            }
        });
    }
}

function showRefundModal(saleId) {
    $.get(`/sales/${saleId}/`, function(data) {
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
            setTimeout(() => location.reload(), 1500);
        },
        error: function(xhr) {
            hideLoading();
            const errorMsg = xhr.responseJSON?.error || 'Error processing refund';
            showNotification(errorMsg, 'error');
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
                'csrfmiddlewaretoken': getCsrfToken(),
                'void_reason': reason
            },
            success: function(response) {
                hideLoading();
                showNotification('Sale voided successfully!', 'success');
                setTimeout(() => location.reload(), 1500);
            },
            error: function(xhr) {
                hideLoading();
                const errorMsg = xhr.responseJSON?.error || 'Error voiding sale';
                showNotification(errorMsg, 'error');
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
    if (email && validateEmail(email)) {
        showLoading();

        $.ajax({
            url: `/sales/${saleId}/send-receipt/`,
            method: 'POST',
            data: {
                'csrfmiddlewaretoken': getCsrfToken(),
                'email': email
            },
            success: function(response) {
                hideLoading();
                showNotification('Receipt sent successfully!', 'success');
            },
            error: function(xhr) {
                hideLoading();
                const errorMsg = xhr.responseJSON?.error || 'Error sending receipt';
                showNotification(errorMsg, 'error');
            }
        });
    } else if (email) {
        showNotification('Invalid email address', 'error');
    }
}

function validateEmail(email) {
    const re = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return re.test(email);
}

function refreshTable() {
    showLoading();
    location.reload();
}

function clearSelection() {
    $('.row-select').prop('checked', false);
    $('#selectAllRows, #selectAll').prop('checked', false);
    window.selectedSales = [];
    $('#bulkActions').removeClass('show');
}