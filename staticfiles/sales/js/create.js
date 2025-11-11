// Sale creation state
let saleItems = [];
let selectedCustomer = null;
let selectedProduct = null;
let itemCounter = 0;

$(document).ready(function() {
    initializeSaleForm();
    setupEventListeners();
    loadDraftData();
});

function initializeSaleForm() {
    // Initialize customer search
    setupCustomerSearch();

    // Initialize product search
    setupProductSearch();

    // Auto-save every 30 seconds
    setInterval(autoSave, 30000);

    updateSummary();
}

function setupEventListeners() {
    // Store change handler
    $('#id_store').change(function() {
        const storeId = $(this).val();
        if (storeId) {
            loadStoreSuggestions(storeId);
        }
    });

    // Payment method change
    $('#id_payment_method').change(function() {
        updatePaymentFields();
    });

    // Discount amount change
    $('#id_discount_amount').on('input', function() {
        updateSummary();
    });

    // Payment amount change
    $('#paymentAmount').on('input', function() {
        updateCompleteButton();
    });

    // Item quantity/price changes
    $(document).on('input', '.quantity-input, .price-input, .discount-input', function() {
        updateItemTotal($(this).closest('.item-row'));
        updateSummary();
    });

    // Form submission
    $('#saleForm').submit(function(e) {
        e.preventDefault();
        completeSale();
    });
}

function setupCustomerSearch() {
    let searchTimeout;
    $('#id_customer_search').on('input', function() {
        clearTimeout(searchTimeout);
        const query = $(this).val();

        searchTimeout = setTimeout(function() {
            if (query.length > 2) {
                searchCustomers(query);
            } else {
                $('#customerSuggestions').hide();
            }
        }, 300);
    });
}

function setupProductSearch() {
    let searchTimeout;
    $('#productSearch').on('input', function() {
        clearTimeout(searchTimeout);
        const query = $(this).val();

        searchTimeout = setTimeout(function() {
            if (query.length > 2) {
                searchProducts(query);
            } else {
                $('#productSuggestions').hide();
                resetAddItemForm();
            }
        }, 300);
    });
}

function searchCustomers(query) {
    const storeId = $('#id_store').val();
    if (!storeId) {
        showNotification('Please select a store first', 'warning');
        return;
    }

    $.ajax({
        url: '{% url "sales:customer_search" %}',
        data: { q: query, store_id: storeId },
        success: function(response) {
            displayCustomerSuggestions(response.customers);
        },
        error: function() {
            showNotification('Error searching customers', 'error');
        }
    });
}

function displayCustomerSuggestions(customers) {
    const container = $('#customerSuggestions');

    if (customers.length === 0) {
        container.hide();
        return;
    }

    let html = '';
    customers.forEach(customer => {
        html += `
            <div class="customer-suggestion" onclick="selectCustomer(${customer.id}, '${customer.name}', '${customer.phone}', '${customer.email || ''}')">
                <div class="d-flex justify-content-between align-items-center">
                    <div>
                        <div class="fw-bold">${customer.name}</div>
                        <small class="text-muted">${customer.phone}</small>
                    </div>
                    <i class="fas fa-user-check text-success"></i>
                </div>
            </div>
        `;
    });

    container.html(html).show();
}

function selectCustomer(id, name, phone, email) {
    selectedCustomer = { id, name, phone, email };

    $('#id_customer').val(id);
    $('#id_customer_search').val(name);
    $('#customerSuggestions').hide();

    // Show selected customer
    $('#customerAvatar').text(name.charAt(0).toUpperCase());
    $('#customerName').text(name);
    $('#customerPhone').text(phone);
    $('#selectedCustomer').addClass('show');

    showNotification(`Customer ${name} selected`, 'success');
}

function removeCustomer() {
    selectedCustomer = null;
    $('#id_customer').val('');
    $('#id_customer_search').val('');
    $('#selectedCustomer').removeClass('show');
    showNotification('Customer removed', 'info');
}

function searchProducts(query) {
    const storeId = $('#id_store').val();
    if (!storeId) {
        showNotification('Please select a store first', 'warning');
        return;
    }

    $.ajax({
        url: '{% url "sales:product_search" %}',
        data: { q: query, store_id: storeId },
        success: function(response) {
            displayProductSuggestions(response.products);
        },
        error: function() {
            showNotification('Error searching products', 'error');
        }
    });
}

function displayProductSuggestions(products) {
    const container = $('#productSuggestions');

    if (products.length === 0) {
        container.hide();
        return;
    }

    let html = '';
    products.forEach(product => {
        html += `
            <div class="product-suggestion" onclick="selectProduct(${product.id}, '${product.name}', '${product.sku}', ${product.price}, '${product.stock}')">
                <div class="product-image">
                    <i class="fas fa-cube"></i>
                </div>
                <div class="product-details">
                    <h6>${product.name}</h6>
                    <small>SKU: ${product.sku} | Stock: ${product.stock}</small>
                </div>
                <div class="product-price">${formatCurrency(product.price)}</div>
            </div>
        `;
    });

    container.html(html).show();
}

function selectProduct(id, name, sku, price, stock) {
    selectedProduct = { id, name, sku, price, stock };

    $('#productSearch').val(name);
    $('#itemPrice').val(price);
    $('#productSuggestions').hide();
    $('#addItemBtn').prop('disabled', false);

    // Check stock
    if (parseFloat(stock) <= 0) {
        showNotification('Product is out of stock', 'warning');
        $('#addItemBtn').prop('disabled', true);
    }

    // Focus quantity input
    $('#itemQuantity').focus().select();
}

function resetAddItemForm() {
    selectedProduct = null;
    $('#productSearch').val('');
    $('#itemQuantity').val(1);
    $('#itemPrice').val('');
    $('#itemTaxRate').val('A');
    $('#itemDiscount').val('');
    $('#addItemBtn').prop('disabled', true);
}

function addItem() {
    if (!selectedProduct) {
        showNotification('Please select a product first', 'warning');
        return;
    }

    const quantity = parseFloat($('#itemQuantity').val()) || 1;
    const price = parseFloat($('#itemPrice').val()) || 0;
    const taxRate = $('#itemTaxRate').val();
    const discount = parseFloat($('#itemDiscount').val()) || 0;

    if (quantity <= 0) {
        showNotification('Quantity must be greater than 0', 'warning');
        return;
    }

    if (price <= 0) {
        showNotification('Price must be greater than 0', 'warning');
        return;
    }

    // Check for duplicate items
    const existingItem = saleItems.find(item => item.productId === selectedProduct.id);
    if (existingItem) {
        existingItem.quantity += quantity;
        updateItemRow(existingItem);
    } else {
        const newItem = {
            id: ++itemCounter,
            productId: selectedProduct.id,
            productName: selectedProduct.name,
            productSku: selectedProduct.sku,
            quantity: quantity,
            unitPrice: price,
            taxRate: taxRate,
            discount: discount,
            lineTotal: (quantity * price) - discount
        };

        saleItems.push(newItem);
        addItemRow(newItem);
    }

    updateSummary();
    resetAddItemForm();

    // Show items list if hidden
    if ($('#itemsList').is(':hidden')) {
        $('#itemsList').show();
        $('#emptyItemsMessage').hide();
    }

    showNotification(`${selectedProduct.name} added to sale`, 'success');
}

function addItemRow(item) {
    const html = `
        <div class="item-row" data-item-id="${item.id}">
            <div class="item-number">${saleItems.length}</div>
            <div>
                <div class="item-name">${item.productName}</div>
                <div class="item-sku">SKU: ${item.productSku}</div>
            </div>
            <div>
                <input type="number" class="form-control quantity-input" value="${item.quantity}"
                       min="0.001" step="0.001" data-item-id="${item.id}">
            </div>
            <div>
                <input type="number" class="form-control price-input" value="${item.unitPrice}"
                       min="0" step="0.01" data-item-id="${item.id}">
            </div>
            <div>
                <select class="form-select tax-rate-select" data-item-id="${item.id}">
                    <option value="A" ${item.taxRate === 'A' ? 'selected' : ''}>18%</option>
                    <option value="B" ${item.taxRate === 'B' ? 'selected' : ''}>12%</option>
                    <option value="C" ${item.taxRate === 'C' ? 'selected' : ''}>0%</option>
                </select>
            </div>
            <div class="line-total">${formatCurrency(item.lineTotal)}</div>
            <div>
                <button type="button" class="remove-item" onclick="removeItem(${item.id})">
                    <i class="fas fa-trash"></i>
                </button>
            </div>
        </div>
    `;

    $('#itemsList').append(html);
}

function updateItemRow(item) {
    const row = $(`.item-row[data-item-id="${item.id}"]`);
    row.find('.quantity-input').val(item.quantity);
    row.find('.line-total').text(formatCurrency(item.lineTotal));
}

function removeItem(itemId) {
    if (confirm('Remove this item from the sale?')) {
        saleItems = saleItems.filter(item => item.id !== itemId);
        $(`.item-row[data-item-id="${itemId}"]`).remove();

        // Update item numbers
        $('.item-row .item-number').each(function(index) {
            if (index > 0) { // Skip header row
                $(this).text(index);
            }
        });

        updateSummary();

        // Hide items list if empty
        if (saleItems.length === 0) {
            $('#itemsList').hide();
            $('#emptyItemsMessage').show();
        }

        showNotification('Item removed from sale', 'info');
    }
}

function updateItemTotal(row) {
    const itemId = parseInt(row.find('.quantity-input').data('item-id'));
    const item = saleItems.find(i => i.id === itemId);

    if (item) {
        item.quantity = parseFloat(row.find('.quantity-input').val()) || 0;
        item.unitPrice = parseFloat(row.find('.price-input').val()) || 0;
        item.taxRate = row.find('.tax-rate-select').val();
        item.lineTotal = (item.quantity * item.unitPrice) - (item.discount || 0);

        row.find('.line-total').text(formatCurrency(item.lineTotal));
    }
}

function updateSummary() {
    const itemCount = saleItems.length;
    const subtotal = saleItems.reduce((sum, item) => sum + item.lineTotal, 0);
    const discountAmount = parseFloat($('#id_discount_amount').val()) || 0;
    const taxableAmount = subtotal - discountAmount;
    const tax = taxableAmount * 0.18; // 18% VAT
    const total = taxableAmount + tax;

    // Update summary panel
    $('#summaryItemCount').text(itemCount);
    $('#summarySubtotal').text(formatCurrency(subtotal));
    $('#summaryTax').text(formatCurrency(tax));
    $('#summaryDiscount').text(formatCurrency(discountAmount));
    $('#summaryTotal').text(formatCurrency(total));

    // Update item count badge
    $('#itemCount').text(itemCount);

    // Update floating total (mobile)
    $('#floatingTotalAmount').text(formatCurrency(total));

    // Update complete button
    updateCompleteButton();

    // Auto-suggest payment amount
    $('#paymentAmount').attr('placeholder', formatCurrency(total));
}

function updateCompleteButton() {
    const hasItems = saleItems.length > 0;
    const hasStore = $('#id_store').val() !== '';
    const hasPaymentMethod = $('#id_payment_method').val() !== '';

    const canComplete = hasItems && hasStore && hasPaymentMethod;
    $('#completeSaleBtn').prop('disabled', !canComplete);
}

function updatePaymentFields() {
    const paymentMethod = $('#id_payment_method').val();

    // Show/hide payment reference field based on method
    if (paymentMethod === 'MOBILE_MONEY' || paymentMethod === 'BANK_TRANSFER') {
        $('#paymentReference').closest('.mb-3').show();
        $('#paymentReference').attr('required', true);
    } else {
        $('#paymentReference').closest('.mb-3').hide();
        $('#paymentReference').attr('required', false);
    }
}

function completeSale() {
    if (saleItems.length === 0) {
        showNotification('Please add at least one item to the sale', 'warning');
        return;
    }

    if (!$('#id_store').val()) {
        showNotification('Please select a store', 'warning');
        return;
    }

    if (!$('#id_payment_method').val()) {
        showNotification('Please select a payment method', 'warning');
        return;
    }

    showLoading();

    // Prepare form data
    const formData = {
        store: $('#id_store').val(),
        customer: selectedCustomer ? selectedCustomer.id : null,
        transaction_type: $('#id_transaction_type').val(),
        document_type: $('#id_document_type').val(),
        payment_method: $('#id_payment_method').val(),
        currency: $('#id_currency').val(),
        discount_amount: $('#id_discount_amount').val() || 0,
        notes: $('#id_notes').val(),
        items_data: JSON.stringify(saleItems),
        payment_amount: $('#paymentAmount').val() || null,
        payment_reference: $('#paymentReference').val() || null
    };

    $.ajax({
        url: '{% url "sales:create_sale" %}',
        method: 'POST',
        data: formData,
        headers: {
            'X-CSRFToken': $('[name=csrfmiddlewaretoken]').val()
        },
        success: function(response) {
            hideLoading();

            if (response.success || !response.error) {
                showNotification('Sale created successfully!', 'success');

                // Ask if user wants to print receipt
                if (confirm('Sale created successfully! Print receipt?')) {
                    window.open(`/sales/${response.sale_id || 'latest'}/print-receipt/`, '_blank');
                }

                // Redirect to sales list or create new sale
                if (confirm('Create another sale?')) {
                    resetForm();
                } else {
                    window.location.href = '{% url "sales:sales_list" %}';
                }
            } else {
                showNotification(response.error || 'Error creating sale', 'error');
            }
        },
        error: function(xhr) {
            hideLoading();
            const errorMsg = xhr.responseJSON?.error || 'Error creating sale. Please try again.';
            showNotification(errorMsg, 'error');
        }
    });
}

function saveDraft() {
    const draftData = {
        customer: selectedCustomer,
        items: saleItems,
        formData: {
            store: $('#id_store').val(),
            transaction_type: $('#id_transaction_type').val(),
            document_type: $('#id_document_type').val(),
            payment_method: $('#id_payment_method').val(),
            discount_amount: $('#id_discount_amount').val(),
            notes: $('#id_notes').val()
        },
        timestamp: new Date().toISOString()
    };

    localStorage.setItem('saleDraft', JSON.stringify(draftData));
    showNotification('Draft saved locally', 'success');
    updateAutoSaveStatus();
}

function loadDraftData() {
    const draftData = localStorage.getItem('saleDraft');
    if (draftData && confirm('Load saved draft?')) {
        try {
            const data = JSON.parse(draftData);

            // Load form data
            Object.keys(data.formData).forEach(key => {
                $(`#id_${key}`).val(data.formData[key]);
            });

            // Load customer
            if (data.customer) {
                selectCustomer(data.customer.id, data.customer.name, data.customer.phone, data.customer.email);
            }

            // Load items
            saleItems = data.items || [];
            saleItems.forEach(item => {
                addItemRow(item);
            });

            if (saleItems.length > 0) {
                $('#itemsList').show();
                $('#emptyItemsMessage').hide();
            }

            updateSummary();
            showNotification('Draft loaded successfully', 'success');
        } catch (e) {
            showNotification('Error loading draft', 'error');
        }
    }
}

function previewSale() {
    if (saleItems.length === 0) {
        showNotification('Please add items to preview the sale', 'warning');
        return;
    }

    const subtotal = saleItems.reduce((sum, item) => sum + item.lineTotal, 0);
    const discountAmount = parseFloat($('#id_discount_amount').val()) || 0;
    const tax = (subtotal - discountAmount) * 0.18;
    const total = subtotal + tax - discountAmount;

    let itemsHtml = '';
    saleItems.forEach((item, index) => {
        itemsHtml += `
            <tr>
                <td>${index + 1}</td>
                <td>${item.productName}<br><small class="text-muted">SKU: ${item.productSku}</small></td>
                <td>${item.quantity}</td>
                <td>${formatCurrency(item.unitPrice)}</td>
                <td>${formatCurrency(item.lineTotal)}</td>
            </tr>
        `;
    });

    const previewHtml = `
        <div class="row">
            <div class="col-md-6">
                <h6>Sale Information</h6>
                <table class="table table-sm">
                    <tr><td>Store:</td><td>${$('#id_store option:selected').text()}</td></tr>
                    <tr><td>Customer:</td><td>${selectedCustomer ? selectedCustomer.name : 'Walk-in Customer'}</td></tr>
                    <tr><td>Payment Method:</td><td>${$('#id_payment_method option:selected').text()}</td></tr>
                </table>
            </div>
            <div class="col-md-6">
                <h6>Summary</h6>
                <table class="table table-sm">
                    <tr><td>Subtotal:</td><td>${formatCurrency(subtotal)}</td></tr>
                    <tr><td>Tax:</td><td>${formatCurrency(tax)}</td></tr>
                    <tr><td>Discount:</td><td>${formatCurrency(discountAmount)}</td></tr>
                    <tr class="fw-bold"><td>Total:</td><td>${formatCurrency(total)}</td></tr>
                </table>
            </div>
        </div>

        <div class="mt-4">
            <h6>Items (${saleItems.length})</h6>
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>#</th>
                        <th>Product</th>
                        <th>Qty</th>
                        <th>Unit Price</th>
                        <th>Total</th>
                    </tr>
                </thead>
                <tbody>
                    ${itemsHtml}
                </tbody>
            </table>
        </div>
    `;

    $('#previewContent').html(previewHtml);
    $('#previewModal').modal('show');
}

function autoSave() {
    if (saleItems.length > 0) {
        saveDraft();
    }
}

function updateAutoSaveStatus() {
    const now = new Date();
    $('#autoSaveStatus').html(`
        <i class="fas fa-cloud-upload-alt me-1"></i>
        Auto-saved at ${now.toLocaleTimeString()}
    `);
}

function resetForm() {
    // Reset all form fields
    $('#saleForm')[0].reset();

    // Reset state
    saleItems = [];
    selectedCustomer = null;
    selectedProduct = null;
    itemCounter = 0;

    // Reset UI
    $('#selectedCustomer').removeClass('show');
    $('#itemsList').hide().find('.item-row:not(:first)').remove();
    $('#emptyItemsMessage').show();
    resetAddItemForm();
    updateSummary();

    // Clear draft
    localStorage.removeItem('saleDraft');

    showNotification('Form reset', 'info');
}

function saveNewCustomer() {
    const formData = $('#newCustomerForm').serialize() + '&store=' + $('#id_store').val();

    $.ajax({
        url: '/customers/create/',
        method: 'POST',
        data: formData,
        headers: {
            'X-CSRFToken': $('[name=csrfmiddlewaretoken]').val()
        },
        success: function(response) {
            if (response.success) {
                selectCustomer(response.customer.id, response.customer.name, response.customer.phone, response.customer.email || '');
                $('#newCustomerModal').modal('hide');
                $('#newCustomerForm')[0].reset();
                showNotification('Customer created and selected!', 'success');
            } else {
                showNotification('Error creating customer', 'error');
            }
        },
        error: function() {
            showNotification('Error creating customer', 'error');
        }
    });
}

function loadStoreSuggestions(storeId) {
    // Load frequently bought together suggestions for the selected store
    $.ajax({
        url: `/sales/store-suggestions/?store_id=${storeId}`,
        success: function(response) {
            if (response.suggestions && response.suggestions.length > 0) {
                let suggestionsHtml = '';
                response.suggestions.forEach(product => {
                    suggestionsHtml += `
                        <span class="suggested-item" onclick="quickAddSuggestion(${product.id}, '${product.name}', ${product.price})">
                            ${product.name}
                        </span>
                    `;
                });
                $('#suggestedItems').html(suggestionsHtml);
                $('#itemSuggestions').addClass('show');
            }
        }
    });
}

function quickAddSuggestion(productId, productName, productPrice) {
    selectedProduct = { id: productId, name: productName, price: productPrice, sku: 'AUTO', stock: 999 };
    $('#itemPrice').val(productPrice);
    addItem();
}

function openBarcodeScanner() {
    // Simulate barcode scanner
    const barcode = prompt('Enter barcode (or scan):');
    if (barcode) {
        $('#productSearch').val(barcode).trigger('input');
    }
}

function formatCurrency(amount) {
    return new Intl.NumberFormat('en-UG', {
        style: 'currency',
        currency: 'UGX',
        minimumFractionDigits: 0
    }).format(amount || 0);
}

// Initialize on page load
$(document).ready(function() {
    // Focus first field
    $('#id_store').focus();

    // Initialize select2 for better dropdowns
    if ($.fn.select2) {
        $('#id_store, #id_transaction_type, #id_document_type, #id_payment_method').select2({
            theme: 'bootstrap-5'
        });
    }
});

// Keyboard shortcuts
$(document).keydown(function(e) {
    if (e.ctrlKey || e.metaKey) {
        switch (e.key) {
            case 's':
                e.preventDefault();
                saveDraft();
                break;
            case 'Enter':
                e.preventDefault();
                if (!$('#completeSaleBtn').prop('disabled')) {
                    completeSale();
                }
                break;
        }
    }

    if (e.key === 'F2') {
        e.preventDefault();
        $('#productSearch').focus();
    }
});

// Warn before leaving with unsaved changes
$(window).on('beforeunload', function() {
    if (saleItems.length > 0) {
        return 'You have unsaved items in your sale. Are you sure you want to leave?';
    }
});