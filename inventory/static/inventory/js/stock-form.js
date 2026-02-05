/**
 * Stock form specific logic
 */

import { FormValidator, debounce, showSuccessMessage, showErrorMessage, getCookie } from './form-base.js';

class StockFormHandler {
    constructor() {
        this.form = $('#stockForm');
        this.validator = new FormValidator('#stockForm');
        this.init();
    }

    init() {
        this.initializeProductChange();
        this.initializeStoreChange();
        this.initializeCalculations();
        this.initializeValidation();
        this.initializePhysicalCount();

        // Initial calculation if editing
        if ($('#id_product').val()) {
            setTimeout(() => {
                this.updateStockCalculations();
            }, 500);
        }
    }

    initializeProductChange() {
        $('#id_product').on('change', () => {
            const productId = $('#id_product').val();

            if (!productId) {
                this.resetProductInfo();
                return;
            }

            // Fetch product details
            $.ajax({
                url: `/inventory/api/product/${productId}/`,
                method: 'GET',
                success: (response) => {
                    this.updateProductInfo(response);
                    this.checkDuplicate();
                },
                error: () => {
                    showErrorMessage('Failed to load product details');
                }
            });
        });
    }

    updateProductInfo(product) {
        const unit = product.unit_of_measure || 'Units';

        // Update unit labels
        $('#quantityUnit, #thresholdUnit, #reorderUnit').text(unit);

        // Set default threshold if not set
        if (!$('#id_low_stock_threshold').val()) {
            $('#id_low_stock_threshold').val(product.min_stock_level || 5);
        }

        this.updateStockCalculations();
    }

    resetProductInfo() {
        $('#quantityUnit, #thresholdUnit, #reorderUnit').text('Units');
        this.updateStockCalculations();
    }

    initializeStoreChange() {
        $('#id_store').on('change', () => {
            this.checkDuplicate();
        });
    }

    checkDuplicate() {
        const productId = $('#id_product').val();
        const storeId = $('#id_store').val();
        const isEditing = $('#stockForm').data('editing') === 'true';

        if (!productId || !storeId || isEditing) {
            $('#duplicateWarning').addClass('d-none');
            return;
        }

        // Check for existing stock record
        $.ajax({
            url: '/inventory/api/stock/check-duplicate/',
            method: 'GET',
            data: {
                product_id: productId,
                store_id: storeId
            },
            success: (response) => {
                if (response.exists) {
                    $('#duplicateWarning')
                        .removeClass('d-none')
                        .html(`
                            <i class="fas fa-exclamation-triangle"></i>
                            <strong>Warning:</strong> A stock record already exists for 
                            <strong>${response.product_name}</strong> at 
                            <strong>${response.store_name}</strong>.
                        `);
                } else {
                    $('#duplicateWarning').addClass('d-none');
                }
            }
        });
    }

    initializeCalculations() {
        $('#id_quantity, #id_low_stock_threshold, #id_reorder_quantity')
            .on('input change', debounce(() => {
                this.updateStockCalculations();
            }, 300));
    }

    updateStockCalculations() {
        const quantity = parseFloat($('#id_quantity').val()) || 0;
        const threshold = parseFloat($('#id_low_stock_threshold').val()) || 0;
        const reorderQty = parseFloat($('#id_reorder_quantity').val()) || 0;

        // Calculate status
        const { status, statusClass, percentage } = this.calculateStockStatus(quantity, threshold);

        // Update status display
        this.updateStatusDisplay(status, statusClass, quantity, percentage);

        // Calculate days until reorder
        this.updateDaysUntilReorder(quantity, threshold, reorderQty);

        // Calculate stock value
        this.updateStockValue(quantity);
    }

    calculateStockStatus(quantity, threshold) {
        let status = 'Unknown';
        let statusClass = 'secondary';
        let percentage = 0;

        if (threshold > 0) {
            percentage = Math.min(100, Math.max(0, (quantity / threshold) * 100));

            if (quantity === 0) {
                status = 'Out of Stock';
                statusClass = 'danger';
            } else if (quantity <= threshold) {
                status = 'Low Stock';
                statusClass = 'warning';
            } else if (quantity <= threshold * 2) {
                status = 'Medium Stock';
                statusClass = 'info';
            } else {
                status = 'Good Stock';
                statusClass = 'success';
            }
        }

        return { status, statusClass, percentage };
    }

    updateStatusDisplay(status, statusClass, quantity, percentage) {
        // Update status badge
        $('#stockStatus').html(`<span class="badge bg-${statusClass}">${status}</span>`);

        // Update quantity
        $('#stockLevel').text(quantity.toFixed(3));

        // Update progress bar
        $('#stockProgressBar')
            .css('width', `${percentage}%`)
            .attr('aria-valuenow', percentage)
            .removeClass('bg-success bg-warning bg-danger bg-info')
            .addClass(`bg-${statusClass}`);

        $('#stockProgressText').text(`${percentage.toFixed(0)}%`);
    }

    updateDaysUntilReorder(quantity, threshold, reorderQty) {
        let daysUntilReorder = '-';

        if (quantity > threshold && reorderQty > 0) {
            // Simple estimation: assume 1 unit per day usage
            const dailyUsage = 1;
            daysUntilReorder = Math.floor((quantity - threshold) / dailyUsage);
        }

        $('#daysUntilReorder').text(daysUntilReorder);
    }

    updateStockValue(quantity) {
        const productId = $('#id_product').val();

        if (!productId) {
            $('#stockValue').text('UGX 0');
            return;
        }

        $.ajax({
            url: `/inventory/api/product/${productId}/`,
            method: 'GET',
            success: (response) => {
                const costPrice = parseFloat(response.cost_price) || 0;
                const stockValue = quantity * costPrice;

                $('#stockValue').text(`UGX ${stockValue.toLocaleString('en-UG', {
                    minimumFractionDigits: 2,
                    maximumFractionDigits: 2
                })}`);
            }
        });
    }

    initializeValidation() {
        this.form.on('submit', (e) => {
            this.validator.clearErrors();

            // Product validation (only for new records)
            const isEditing = this.form.data('editing') === 'true';
            if (!isEditing && !$('#id_product').val()) {
                this.validator.addError('#id_product', 'Product is required');
            }

            // Store validation (only for new records)
            if (!isEditing && !$('#id_store').val()) {
                this.validator.addError('#id_store', 'Store is required');
            }

            // Quantity validation
            const quantity = parseFloat($('#id_quantity').val());
            if (isNaN(quantity) || quantity < 0) {
                this.validator.addError('#id_quantity', 'Quantity must be a non-negative number');
            }

            // Threshold validation
            const threshold = parseFloat($('#id_low_stock_threshold').val());
            if (isNaN(threshold) || threshold < 0) {
                this.validator.addError('#id_low_stock_threshold', 'Low stock threshold must be a non-negative number');
            }

            // Reorder quantity validation
            const reorderQty = parseFloat($('#id_reorder_quantity').val());
            if (isNaN(reorderQty) || reorderQty < 0) {
                this.validator.addError('#id_reorder_quantity', 'Reorder quantity must be a non-negative number');
            }

            // Duplicate check
            if (!$('#duplicateWarning').hasClass('d-none')) {
                showErrorMessage('A stock record already exists for this product and store combination');
                e.preventDefault();
                return false;
            }

            if (!this.validator.isValid()) {
                e.preventDefault();
                this.validator.showErrors();
                return false;
            }
        });
    }

    initializePhysicalCount() {
        // Physical count modal is initialized globally
        // but we can add additional handlers here if needed
    }
}

// Physical Count Modal Handler
class PhysicalCountHandler {
    static showModal(stockId, currentQuantity) {
        const modalHtml = `
            <div class="modal fade" id="physicalCountModal" tabindex="-1" aria-labelledby="physicalCountModalLabel" aria-hidden="true">
                <div class="modal-dialog">
                    <div class="modal-content">
                        <div class="modal-header">
                            <h5 class="modal-title" id="physicalCountModalLabel">
                                <i class="fas fa-clipboard-check"></i> Record Physical Count
                            </h5>
                            <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                        </div>
                        <div class="modal-body">
                            <div class="alert alert-info" role="alert">
                                <i class="fas fa-info-circle"></i> 
                                Current System Quantity: <strong>${currentQuantity}</strong> units
                            </div>
                            <form id="physicalCountForm">
                                <div class="mb-3">
                                    <label for="countedQuantity" class="form-label">
                                        Counted Quantity <span class="text-danger">*</span>
                                    </label>
                                    <input type="number" 
                                           class="form-control" 
                                           id="countedQuantity" 
                                           step="0.001" 
                                           min="0" 
                                           required
                                           aria-required="true">
                                </div>
                                <div class="mb-3">
                                    <label for="countNotes" class="form-label">Notes (Optional)</label>
                                    <textarea class="form-control" 
                                              id="countNotes" 
                                              rows="3"
                                              aria-describedby="countNotesHelp"></textarea>
                                    <small id="countNotesHelp" class="form-text text-muted">
                                        Add any notes about the physical count
                                    </small>
                                </div>
                            </form>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                                <i class="fas fa-times"></i> Cancel
                            </button>
                            <button type="button" class="btn btn-primary" onclick="submitPhysicalCount(${stockId})">
                                <i class="fas fa-save"></i> Save Count
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // Remove existing modal
        $('#physicalCountModal').remove();

        // Add new modal
        $('body').append(modalHtml);

        // Show modal
        const modal = new bootstrap.Modal(document.getElementById('physicalCountModal'));
        modal.show();

        // Focus on quantity input
        $('#physicalCountModal').on('shown.bs.modal', () => {
            $('#countedQuantity').focus();
        });
    }

    static submit(stockId) {
        const countedQuantity = $('#countedQuantity').val();
        const notes = $('#countNotes').val();

        // Validation
        if (!countedQuantity || parseFloat(countedQuantity) < 0) {
            showErrorMessage('Please enter a valid counted quantity');
            $('#countedQuantity').addClass('is-invalid');
            return;
        }

        // Show loading state
        const $saveBtn = $('#physicalCountModal .btn-primary');
        const originalText = $saveBtn.html();
        $saveBtn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Saving...');

        $.ajax({
            url: `/inventory/api/stock/${stockId}/physical-count/`,
            method: 'POST',
            data: {
                counted_quantity: countedQuantity,
                notes: notes,
                csrfmiddlewaretoken: getCookie('csrftoken')
            },
            success: (response) => {
                if (response.success) {
                    showSuccessMessage('Physical count recorded successfully!');

                    // Hide modal
                    const modal = bootstrap.Modal.getInstance(document.getElementById('physicalCountModal'));
                    modal.hide();

                    // Reload page to show updated data
                    setTimeout(() => {
                        location.reload();
                    }, 1000);
                } else {
                    showErrorMessage(response.message || 'Failed to record count');
                }
            },
            error: (xhr) => {
                console.error('Physical count error:', xhr);
                showErrorMessage('Error recording physical count. Please try again.');
            },
            complete: () => {
                $saveBtn.prop('disabled', false).html(originalText);
            }
        });
    }
}

// EFRIS Sync Handler
class EFRISSyncHandler {
    static sync(stockId) {
        if (!confirm('Sync this stock record to EFRIS?')) {
            return;
        }

        const $btn = $(`button[onclick="syncToEFRIS(${stockId})"]`);
        const originalText = $btn.html();
        $btn.prop('disabled', true).html('<i class="fas fa-spinner fa-spin"></i> Syncing...');

        $.ajax({
            url: `/inventory/api/stock/${stockId}/efris-sync/`,
            method: 'POST',
            data: {
                csrfmiddlewaretoken: getCookie('csrftoken')
            },
            success: (response) => {
                if (response.success) {
                    showSuccessMessage('Successfully synced to EFRIS!');
                    setTimeout(() => {
                        location.reload();
                    }, 1000);
                } else {
                    showErrorMessage(response.message || 'Failed to sync to EFRIS');
                }
            },
            error: (xhr) => {
                console.error('EFRIS sync error:', xhr);
                showErrorMessage('Error syncing to EFRIS. Please try again.');
            },
            complete: () => {
                $btn.prop('disabled', false).html(originalText);
            }
        });
    }
}

// Global functions (for onclick handlers in template)
window.recordPhysicalCount = function(stockId) {
    const currentQuantity = $('#id_quantity').val() || 0;
    PhysicalCountHandler.showModal(stockId, currentQuantity);
};

window.submitPhysicalCount = function(stockId) {
    PhysicalCountHandler.submit(stockId);
};

window.syncToEFRIS = function(stockId) {
    EFRISSyncHandler.sync(stockId);
};

// Initialize stock form
function initializeStockForm() {
    if ($('#stockForm').length) {
        new StockFormHandler();
    }
}

export { initializeStockForm };