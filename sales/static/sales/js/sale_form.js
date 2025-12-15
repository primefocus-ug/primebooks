/**
* Sale Form JavaScript
            */

class SaleForm {
constructor() {
this.items = [];
this.selectedStore = null;
this.selectedCustomer = null;
this.documentType = 'RECEIPT';

this.init();
}

init() {
this.initDocumentTypeSelection();
this.initStoreSelection();
this.initCustomerSearch();
this.initItemSearch();
this.initEventListeners();
this.initCalculations();
}

initDocumentTypeSelection() {
document.querySelectorAll('.document-badge').forEach(badge => {
badge.addEventListener('click', () => {
this.setDocumentType(badge.dataset.type);
});
});
}

setDocumentType(type) {
this.documentType = type;
document.querySelectorAll('.document-badge').forEach(b => b.classList.remove('active'));
document.querySelector(`[data-type="${type}"]`).classList.add('active');
document.getElementById('documentType').value = type;

// Show/hide invoice fields
const invoiceFields = document.getElementById('invoiceFields');
if (type === 'INVOICE') {
invoiceFields.classList.remove('d-none');
// Validate customer requirement
this.validateCustomerRequirement();
} else {
invoiceFields.classList.add('d-none');
}

this.updateActionButtons();
}

initStoreSelection() {
const storeSelect = document.getElementById('store');
if (storeSelect) {
storeSelect.addEventListener('change', () => {
this.selectedStore = storeSelect.value;
const option = storeSelect.options[storeSelect.selectedIndex];
this.updateCurrency(option.dataset.currency);
this.updateEFRISStatus(option.dataset.efrisEnabled === 'true');
this.validateForm();
});
}
}

updateCurrency(currency) {
document.querySelectorAll('.currency-display').forEach(el => {
el.textContent = currency;
});
}

updateEFRISStatus(enabled) {
const indicators = document.querySelectorAll('.efris-indicator');
indicators.forEach(indicator => {
indicator.classList.toggle('d-none', !enabled);
});
}

initCustomerSearch() {
const searchInput = document.getElementById('customerSearch');
const resultsDiv = document.getElementById('customerResults');

if (searchInput && resultsDiv) {
searchInput.addEventListener('input', this.debounce(async () => {
const query = searchInput.value.trim();
if (query.length < 2) {
resultsDiv.style.display = 'none';
return;
}

try {
const response = await fetch(`/api/customers/search/?q=${encodeURIComponent(query)}`);
const customers = await response.json();

resultsDiv.innerHTML = '';
if (customers.length === 0) {
const noResults = document.createElement('div');
noResults.className = 'search-result-item text-muted';
noResults.textContent = 'No customers found';
resultsDiv.appendChild(noResults);
} else {
customers.forEach(customer => {
const item = this.createCustomerResultItem(customer);
resultsDiv.appendChild(item);
});
}
resultsDiv.style.display = 'block';
} catch (error) {
console.error('Error searching customers:', error);
}
}, 300));

// Close results when clicking outside
document.addEventListener('click', (e) => {
if (!e.target.closest('.search-input-wrapper')) {
resultsDiv.style.display = 'none';
}
});
}
}

createCustomerResultItem(customer) {
    const div = document.createElement('div');
div.className = 'search-result-item';
div.dataset.id = customer.id;
div.innerHTML = `
                <strong>${customer.name}</strong><br>
                                          <small class="text-muted">
${customer.phone || ''}
${customer.email ? '• ' + customer.email : ''}
</small>
`;

div.addEventListener('click', () => {
    this.selectCustomer(customer);
});

return div;
}

selectCustomer(customer) {
this.selectedCustomer = customer.id;
document.getElementById('customer').value = customer.id;
document.getElementById('customerSearch').value = customer.name;
document.getElementById('customerResults').style.display = 'none';
this.validateForm();
}

initItemSearch() {
const searchInput = document.getElementById('itemSearch');
const resultsDiv = document.getElementById('itemResults');

if (searchInput && resultsDiv) {
searchInput.addEventListener('input', this.debounce(async () => {
const query = searchInput.value.trim();
const storeId = document.getElementById('store').value;

if (query.length < 2 || !storeId) {
resultsDiv.style.display = 'none';
return;
}

try {
const response = await fetch(`/api/items/search/?q=${encodeURIComponent(query)}&store=${storeId}`);
const items = await response.json();

resultsDiv.innerHTML = '';
if (items.length === 0) {
const noResults = document.createElement('div');
noResults.className = 'search-result-item text-muted';
noResults.textContent = 'No items found';
resultsDiv.appendChild(noResults);
} else {
items.forEach(item => {
const itemElement = this.createItemResultItem(item);
resultsDiv.appendChild(itemElement);
});
}
resultsDiv.style.display = 'block';
} catch (error) {
console.error('Error searching items:', error);
}
}, 300));
}
}

createItemResultItem(item) {
    const div = document.createElement('div');
div.className = 'search-result-item';
div.dataset.id = item.id;
div.dataset.type = item.type;
div.dataset.name = item.name;
div.dataset.price = item.price;
div.dataset.stock = item.stock || 0;

let stockBadge = '';
if (item.type === 'PRODUCT') {
    let stockClass = 'stock-available';
if (item.stock <= 0) stockClass = 'stock-out';
else if (item.stock < 10) stockClass = 'stock-low';

stockBadge = `<span class="stock-indicator ${stockClass}">${item.stock} in stock</span>`;
}

div.innerHTML = `
                <div class="d-flex justify-content-between align-items-center">
<div>
<strong>${item.name}</strong><br>
<small class="text-muted">${item.code || ''} • ${window.formatCurrency(item.price)}</small>
</div>
${stockBadge}
</div>
`;

div.addEventListener('click', () => {
    this.selectItemForAddition(item);
});

return div;
}

selectItemForAddition(item) {
document.getElementById('selectedItemId').value = item.id;
document.getElementById('selectedItemType').value = item.type;
document.getElementById('selectedItemName').textContent = item.name;
document.getElementById('itemUnitPrice').value = item.price;
document.getElementById('itemQuantity').value = 1;
document.getElementById('itemDiscount').value = 0;

document.getElementById('itemForm').classList.remove('d-none');
document.getElementById('addSelectedItem').disabled = false;

// Show stock warning if applicable
if (item.type === 'PRODUCT') {
const stock = parseInt(item.stock);
if (stock <= 0) {
this.showStockWarning(item.name, 0);
} else if (stock < 10) {
this.showStockWarning(item.name, stock);
}
}
}

addItemToSale() {
const item = {
    id: document.getElementById('selectedItemId').value,
    type: document.getElementById('selectedItemType').value,
    name: document.getElementById('selectedItemName').textContent,
    quantity: parseInt(document.getElementById('itemQuantity').value),
    unit_price: parseFloat(document.getElementById('itemUnitPrice').value),
    tax_rate: document.getElementById('itemTaxRate').value,
    discount: parseFloat(document.getElementById('itemDiscount').value) || 0
};

this.items.push(item);
this.updateItemsTable();
this.calculateTotals();

// Reset modal
document.getElementById('itemForm').classList.add('d-none');
document.getElementById('addSelectedItem').disabled = true;
document.getElementById('itemSearch').value = '';
document.getElementById('itemResults').innerHTML = '';

// Close modal
const modal = bootstrap.Modal.getInstance(document.getElementById('addItemModal'));
if (modal) modal.hide();
}

updateItemsTable() {
const tbody = document.getElementById('itemsTableBody');
tbody.innerHTML = '';

this.items.forEach((item, index) => {
    const row = this.createItemTableRow(item, index);
tbody.appendChild(row);
});

this.updateItemsDataField();
}

createItemTableRow(item, index) {
const row = document.createElement('tr');
row.className = 'item-row';

const total = item.quantity * item.unit_price;
const discountAmount = total * (item.discount / 100);
const netAmount = total - discountAmount;

row.innerHTML = `
<td>
<strong>${item.name}</strong><br>
<small class="text-muted">${item.type} • ${item.id}</small>
</td>
<td>
<input type="number"
class="form-control form-control-sm"
value="${item.quantity}"
min="1"
data-index="${index}"
onchange="saleForm.updateItemQuantity(${index}, this.value)">
</td>
<td>
<div class="input-group input-group-sm">
<span class="input-group-text">${document.querySelector('.currency-display')?.textContent || 'UGX'}</span>
<input type="number"
class="form-control"
value="${item.unit_price.toFixed(2)}"
data-index="${index}"
onchange="saleForm.updateItemPrice(${index}, this.value)">
</div>
</td>
<td>
<select class="form-select form-select-sm"
data-index="${index}"
onchange="saleForm.updateItemTaxRate(${index}, this.value)">
${this.getTaxRateOptions(item.tax_rate)}
</select>
</td>
<td>
<input type="number"
class="form-control form-control-sm"
value="${item.discount.toFixed(2)}"
min="0"
max="100"
step="0.01"
data-index="${index}"
onchange="saleForm.updateItemDiscount(${index}, this.value)">
</td>
<td class="fw-semibold">
${window.formatCurrency(netAmount)}
</td>
<td>
<button type="button"
class="btn btn-sm btn-outline-danger"
onclick="saleForm.removeItem(${index})">
<i class="bi bi-trash"></i>
</button>
</td>
`;

return row;
}

getTaxRateOptions(selectedRate) {
const taxRates = window.TAX_RATES || {
    'A': 'Standard (18%)',
    'B': 'Zero (0%)',
    'C': 'Exempt',
    'D': 'Deemed (18%)',
    'E': 'Excise Duty'
};

let options = '';
for (const [code, label] of Object.entries(taxRates)) {
options += `<option value="${code}" ${code === selectedRate ? 'selected' : ''}>${label}</option>`;
}
return options;
}

updateItemQuantity(index, quantity) {
this.items[index].quantity = parseInt(quantity);
this.updateItemsTable();
this.calculateTotals();
}

updateItemPrice(index, price) {
this.items[index].unit_price = parseFloat(price);
this.updateItemsTable();
this.calculateTotals();
}

updateItemTaxRate(index, taxRate) {
this.items[index].tax_rate = taxRate;
this.calculateTotals();
}

updateItemDiscount(index, discount) {
this.items[index].discount = parseFloat(discount);
this.updateItemsTable();
this.calculateTotals();
}

removeItem(index) {
this.items.splice(index, 1);
this.updateItemsTable();
this.calculateTotals();
}

updateItemsDataField() {
document.getElementById('itemsData').value = JSON.stringify(this.items);
}

initCalculations() {
// Calculate totals when discount changes
document.getElementById('discount_amount')?.addEventListener('input', () => {
    this.calculateTotals();
});

// Initial calculation
this.calculateTotals();
}

calculateTotals() {
let subtotal = 0;
let totalTax = 0;
let totalDiscount = 0;

this.items.forEach(item => {
    const itemTotal = item.quantity * item.unit_price;
const itemDiscount = itemTotal * (item.discount / 100);
const netAmount = itemTotal - itemDiscount;

subtotal += itemTotal;
totalDiscount += itemDiscount;

// Calculate tax
if (item.tax_rate === 'A' || item.tax_rate === 'D') {
    totalTax += netAmount / 1.18 * 0.18;
} else if (item.tax_rate === 'E') {
// Excise duty - would need product-specific rate
totalTax += netAmount * 0.1; // Example 10%
}
});

const additionalDiscount = parseFloat(document.getElementById('discount_amount')?.value) || 0;
totalDiscount += additionalDiscount;

const total = subtotal + totalTax - totalDiscount;

// Update displays
const currency = document.querySelector('.currency-display')?.textContent || 'UGX';
document.getElementById('subtotalDisplay').textContent = window.formatCurrency(subtotal, currency);
document.getElementById('taxDisplay').textContent = window.formatCurrency(totalTax, currency);
document.getElementById('discountDisplay').textContent = `-${window.formatCurrency(totalDiscount, currency)}`;
document.getElementById('totalDisplay').textContent = window.formatCurrency(total, currency);
}

initEventListeners() {
// Add item button
document.getElementById('addSelectedItem')?.addEventListener('click', () => {
    this.addItemToSale();
});

// Preview button
document.getElementById('previewBtn')?.addEventListener('click', () => {
    this.showPreview();
});

// Save draft button
document.getElementById('saveDraftBtn')?.addEventListener('click', () => {
    this.saveAsDraft();
});

// Complete sale button
document.getElementById('completeBtn')?.addEventListener('click', () => {
    this.completeSale();
});
}

validateForm() {
let isValid = true;
let errors = [];

// Check store
if (!this.selectedStore) {
errors.push('Please select a store');
isValid = false;
}

// Check customer for invoices
    if (this.documentType === 'INVOICE' && !this.selectedCustomer) {
    errors.push('Customer is required for invoices');
    isValid = false;
    }

// Check items
if (this.items.length === 0) {
errors.push('Please add at least one item');
isValid = false;
}

// Check stock availability for products
    this.items.forEach(item => {
    if (item.type === 'PRODUCT' && item.stock && item.stock < item.quantity) {
    errors.push(`Insufficient stock for ${item.name}`);
isValid = false;
}
});

return { isValid, errors };
}

async showPreview() {
const validation = this.validateForm();
if (!validation.isValid) {
this.showErrors(validation.errors);
return;
}

// Submit form for preview
const form = document.getElementById('saleForm');
const formData = new FormData(form);
formData.append('action', 'preview');

try {
const response = await fetch(form.action, {
method: 'POST',
body: formData,
headers: {
    'X-CSRFToken': window.csrfToken
}
});

const html = await response.text();
document.getElementById('previewContent').innerHTML = html;

const modal = new bootstrap.Modal(document.getElementById('previewModal'));
modal.show();
} catch (error) {
    console.error('Error showing preview:', error);
this.showError('Error loading preview');
}
}

async saveAsDraft() {
const validation = this.validateForm();
if (!validation.isValid) {
this.showErrors(validation.errors);
return;
}

const form = document.getElementById('saleForm');
const formData = new FormData(form);
formData.append('action', 'save_draft');

try {
const response = await fetch(form.action, {
method: 'POST',
body: formData,
headers: {
    'X-CSRFToken': window.csrfToken
}
});

const data = await response.json();
if (data.success) {
    this.showSuccess('Draft saved successfully');
if (data.redirect_url) {
    setTimeout(() => {
    window.location.href = data.redirect_url;
}, 1000);
}
} else {
    this.showError(data.error);
}
} catch (error) {
    console.error('Error saving draft:', error);
this.showError('Error saving draft');
}
}

async completeSale() {
if (!confirm('Are you sure you want to complete this sale? This action cannot be undone.')) {
return;
}

const validation = this.validateForm();
if (!validation.isValid) {
this.showErrors(validation.errors);
return;
}

const form = document.getElementById('saleForm');
const formData = new FormData(form);
formData.append('action', 'complete');

try {
const response = await fetch(form.action, {
method: 'POST',
body: formData,
headers: {
    'X-CSRFToken': window.csrfToken
}
});

const data = await response.json();
if (data.success) {
    this.showSuccess('Sale completed successfully');
if (data.redirect_url) {
    setTimeout(() => {
    window.location.href = data.redirect_url;
}, 1000);
}
} else {
    this.showError(data.error);
}
} catch (error) {
    console.error('Error completing sale:', error);
this.showError('Error completing sale');
}
}

showErrors(errors) {
errors.forEach(error => {
    this.showError(error);
});
}

showError(message) {
this.showAlert(message, 'danger');
}

showSuccess(message) {
this.showAlert(message, 'success');
}

showAlert(message, type) {
const alertDiv = document.createElement('div');
alertDiv.className = `alert alert-${type} alert-dismissible fade show`;
alertDiv.innerHTML = `
${message}
<button type="button" class="btn-close" data-bs-dismiss="alert"></button>
`;

const container = document.querySelector('.sale-create-container');
if (container) {
container.prepend(alertDiv);

setTimeout(() => {
const closeBtn = alertDiv.querySelector('.btn-close');
if (closeBtn) closeBtn.click();
}, 5000);
}
}

showStockWarning(productName, stock) {
let message = '';
if (stock <= 0) {
message = `Product "${productName}" is out of stock!`;
this.showAlert(message, 'danger');
} else {
message = `Low stock for "${productName}": ${stock} units remaining`;
this.showAlert(message, 'warning');
}
}

updateActionButtons() {
const completeBtn = document.getElementById('completeBtn');
if (completeBtn) {
if (this.documentType === 'INVOICE') {
completeBtn.textContent = 'Create Invoice';
} else if (this.documentType === 'PROFORMA') {
completeBtn.textContent = 'Create Proforma';
} else if (this.documentType === 'ESTIMATE') {
completeBtn.textContent = 'Create Estimate';
} else {
completeBtn.textContent = 'Complete Sale';
}
}
}

validateCustomerRequirement() {
const customerField = document.getElementById('customer');
if (this.documentType === 'INVOICE' && !customerField.value) {
customerField.setCustomValidity('Customer is required for invoices');
} else {
customerField.setCustomValidity('');
}
}

debounce(func, wait) {
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
}

// Initialize sale form
document.addEventListener('DOMContentLoaded', () => {
if (document.getElementById('saleForm')) {
window.saleForm = new SaleForm();
}
});



=====================calculations.js=====================
/**
* Tax and Calculation Functions
                      */

class TaxCalculator {
constructor() {
this.taxRates = {
'A': 0.18, // Standard VAT
'B': 0.00, // Zero rate
'C': 0.00, // Exempt
'D': 0.18, // Deemed
'E': null  // Excise (product specific)
};
}

calculateItemTotal(item) {
    const quantity = parseFloat(item.quantity) || 0;
const unitPrice = parseFloat(item.unit_price) || 0;
return quantity * unitPrice;
}

calculateDiscountAmount(total, discountPercentage) {
const discount = parseFloat(discountPercentage) || 0;
return total * (discount / 100);
}

calculateTaxAmount(netAmount, taxRateCode, exciseRate = 0) {
const taxRate = this.getTaxRate(taxRateCode, exciseRate);
if (taxRate === null) return 0;

// Tax is included in price, so we need to extract it
return netAmount / (1 + taxRate) * taxRate;
}

getTaxRate(taxRateCode, exciseRate = 0) {
if (taxRateCode === 'E') {
return exciseRate / 100;
}
return this.taxRates[taxRateCode] || 0;
}

calculateItemBreakdown(item, exciseRate = 0) {
const total = this.calculateItemTotal(item);
const discountAmount = this.calculateDiscountAmount(total, item.discount);
const netAmount = total - discountAmount;
const taxAmount = this.calculateTaxAmount(netAmount, item.tax_rate, exciseRate);
const taxableAmount = netAmount - taxAmount;

return {
    total: total,
    discount: discountAmount,
    net: netAmount,
    tax: taxAmount,
    taxable: taxableAmount
};
}

calculateSaleTotals(items, globalDiscount = 0) {
let subtotal = 0;
let totalDiscount = 0;
let totalTax = 0;

items.forEach(item => {
    const breakdown = this.calculateItemBreakdown(item);

subtotal += breakdown.total;
totalDiscount += breakdown.discount;
totalTax += breakdown.tax;
});

// Apply global discount
const globalDiscountAmount = parseFloat(globalDiscount) || 0;
totalDiscount += globalDiscountAmount;

const grandTotal = subtotal + totalTax - totalDiscount;

return {
    subtotal: subtotal,
    discount: totalDiscount,
    tax: totalTax,
    total: grandTotal
};
}
}

// Rounding functions
const roundToTwo = (num) => {
return Math.round((num + Number.EPSILON) * 100) / 100;
};

const roundToNearest = (num, nearest = 0.01) => {
return Math.round(num / nearest) * nearest;
};

// Currency formatting
const formatCurrency = (amount, currency = 'UGX', locale = 'en-UG') => {
return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
}).format(amount);
};

// Percentage formatting
const formatPercentage = (value) => {
return `${parseFloat(value).toFixed(2)}%`;
};

// Stock calculations
const calculateStockValue = (quantity, unitCost) => {
return quantity * unitCost;
};

const calculateProfitMargin = (sellingPrice, costPrice) => {
if (costPrice === 0) return 0;
return ((sellingPrice - costPrice) / costPrice) * 100;
};

// Discount calculations
const calculateDiscountPercentage = (originalPrice, discountedPrice) => {
if (originalPrice === 0) return 0;
return ((originalPrice - discountedPrice) / originalPrice) * 100;
};

const calculateDiscountedPrice = (originalPrice, discountPercentage) => {
return originalPrice * (1 - discountPercentage / 100);
};

// Tax inclusive/exclusive calculations
const calculateTaxInclusivePrice = (priceExcludingTax, taxRate) => {
return priceExcludingTax * (1 + taxRate);
};

const calculateTaxExclusivePrice = (priceIncludingTax, taxRate) => {
return priceIncludingTax / (1 + taxRate);
};

// Batch calculations
const calculateBatchTotals = (items, callback) => {
const totals = {
    quantity: 0,
    value: 0,
    tax: 0,
    discount: 0
};

items.forEach(item => {
    totals.quantity += parseFloat(item.quantity) || 0;
totals.value += (parseFloat(item.unit_price) || 0) * (parseFloat(item.quantity) || 0);

if (callback) {
    const result = callback(item);
Object.keys(result).forEach(key => {
    totals[key] = (totals[key] || 0) + (result[key] || 0);
});
}
});

return totals;
};

// Export functions
window.TaxCalculator = TaxCalculator;
window.roundToTwo = roundToTwo;
window.roundToNearest = roundToNearest;
window.formatCurrency = formatCurrency;
window.formatPercentage = formatPercentage;
window.calculateStockValue = calculateStockValue;
window.calculateProfitMargin = calculateProfitMargin;
window.calculateDiscountPercentage = calculateDiscountPercentage;
window.calculateDiscountedPrice = calculateDiscountedPrice;
window.calculateTaxInclusivePrice = calculateTaxInclusivePrice;
window.calculateTaxExclusivePrice = calculateTaxExclusivePrice;
window.calculateBatchTotals = calculateBatchTotals;