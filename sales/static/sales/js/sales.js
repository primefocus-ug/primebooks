
/**
* Sales Application Main JavaScript
                         */

class SalesApp {
constructor() {
this.initEventListeners();
this.initWebSocket();
this.initRealTimeUpdates();
}

initEventListeners() {
// Initialize tooltips
const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
tooltipTriggerList.map(function (tooltipTriggerEl) {
return new bootstrap.Tooltip(tooltipTriggerEl);
});

// Initialize popovers
const popoverTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="popover"]'));
popoverTriggerList.map(function (popoverTriggerEl) {
return new bootstrap.Popover(popoverTriggerEl);
});

// Form validation
const forms = document.querySelectorAll('.needs-validation');
Array.from(forms).forEach(form => {
form.addEventListener('submit', event => {
if (!form.checkValidity()) {
    event.preventDefault();
event.stopPropagation();
}
form.classList.add('was-validated');
}, false);
});
}

initWebSocket() {
                // WebSocket for real-time updates
if (typeof WebSocket !== 'undefined') {
const storeId = document.querySelector('[data-store-id]')?.dataset.storeId;
if (storeId) {
this.salesSocket = new WebSocket(
    'ws://' + window.location.host + '/ws/sales/' + storeId + '/'
);

this.salesSocket.onmessage = (e) => {
    const data = JSON.parse(e.data);
this.handleWebSocketMessage(data);
};

this.salesSocket.onclose = () => {
    console.log('Sales WebSocket closed');
// Attempt to reconnect after 5 seconds
setTimeout(() => this.initWebSocket(), 5000);
};
}
}
}

handleWebSocketMessage(data) {
    switch (data.type) {
    case 'sale_update': \
this.handleSaleUpdate(data.message);
break;
case 'stock_update':
this.handleStockUpdate(data.message);
break;
case 'efris_update':
this.handleEFRISUpdate(data.message);
break;
}
}

handleSaleUpdate(message) {
                          // Update sales list if on sales page
if (window.location.pathname.includes('/sales/')) {
this.updateSalesList(message);
}

// Show notification
this.showNotification('New Sale', `Sale ${message.invoice_number} completed`, 'success');
}

handleStockUpdate(message) {
                           // Update stock indicators
const stockIndicators = document.querySelectorAll(`[data-product-id="${message.product_id}"]`);
stockIndicators.forEach(indicator => {
    indicator.textContent = message.new_stock;
indicator.className = `stock-indicator ${this.getStockClass(message.new_stock)}`;
});
}

handleEFRISUpdate(message) {
if (message.success) {
this.showNotification('EFRIS Update', `Sale ${message.invoice_number} fiscalized`, 'info');
} else {
this.showNotification('EFRIS Error', message.error, 'danger');
}
}

updateSalesList(sale) {
                      // This would update the sales list table without page reload
                                                                             // Implementation depends on your table structure
}

getStockClass(stock) {
if (stock <= 0) return 'stock-out-of-stock';
if (stock < 10) return 'stock-low-stock';
return 'stock-in-stock';
}

showNotification(title, message, type) {
// Create notification element
const notification = document.createElement('div');
notification.className = `toast align-items-center text-white bg-${type} border-0`;
notification.setAttribute('role', 'alert');
notification.setAttribute('aria-live', 'assertive');
notification.setAttribute('aria-atomic', 'true');

notification.innerHTML = `
<div class="d-flex">
<div class="toast-body">
<strong>${title}</strong><br>
${message}
</div>
<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
</div>
`;

// Add to notification container
const container = document.getElementById('notificationContainer');
if (!container) {
// Create container if it doesn't exist
const newContainer = document.createElement('div');
newContainer.id = 'notificationContainer';
newContainer.className = 'toast-container position-fixed bottom-0 end-0 p-3';
newContainer.style.zIndex = '9999';
document.body.appendChild(newContainer);
container = newContainer;
}

container.appendChild(notification);

// Initialize and show toast
const toast = new bootstrap.Toast(notification);
toast.show();

// Remove after hide
notification.addEventListener('hidden.bs.toast', () => {
    notification.remove();
});
}

initRealTimeUpdates() {
// Poll for updates if WebSocket not available
if (!this.salesSocket || this.salesSocket.readyState !== WebSocket.OPEN) {
setInterval(() => this.pollForUpdates(), 30000); // Every 30 seconds
}
}

pollForUpdates() {
fetch('/api/sales/updates/')
.then(response => response.json())
.then(data => {
    data.updates.forEach(update => {
        this.handleWebSocketMessage(update);
});
})
.catch(error => console.error('Error polling for updates:', error));
}
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
window.salesApp = new SalesApp();
});

// Utility functions
window.formatCurrency = (amount, currency = 'UGX') => {
return new Intl.NumberFormat('en-UG', {
    style: 'currency',
    currency: currency
}).format(amount);
};

window.getTaxRateLabel = (code) => {
const taxRates = {
    'A': 'Standard (18%)',
    'B': 'Zero (0%)',
    'C': 'Exempt',
    'D': 'Deemed (18%)',
    'E': 'Excise Duty'
};
return taxRates[code] || code;
};

window.validateStock = async (productId, storeId, quantity) => {
try {
const response = await fetch(`/api/stock/check/${productId}/${storeId}/`);
const data = await response.json();
return {
    available: data.stock,
    sufficient: data.stock >= quantity,
    message: data.stock >= quantity
? 'Sufficient stock available'
: `Insufficient stock. Available: ${data.stock}`
};
} catch (error) {
console.error('Error checking stock:', error);
return { available: 0, sufficient: false, message: 'Error checking stock' };
}
};

// Export functionality
window.exportSalesData = (format, filters) => {
    const queryString = new URLSearchParams(filters).toString();
window.location.href = `/sales/export/${format}/?${queryString}`;
};

// Print functionality
window.printSale = (saleId, type = 'receipt') => {
    const url = `/sales/${saleId}/print/${type}/`;
const printWindow = window.open(url, '_blank');
printWindow.focus();
};

// EFRIS verification
window.verifyEFRIS = (invoiceNumber, verificationCode) => {
    const url = `https://efris.ura.go.ug/efrisweb/faces/index.jsf?invoiceNo=${invoiceNumber}&anticode=${verificationCode}`;
window.open(url, '_blank');
};

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
// Ctrl/Cmd + N for new sale
    if ((e.ctrlKey || e.metaKey) && e.key === 'n') {
    e.preventDefault();
    const newSaleBtn = document.querySelector('a[href*="/sales/create/"]');
    if (newSaleBtn) newSaleBtn.click();
    }

// Ctrl/Cmd + F for search
    if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
    e.preventDefault();
    const searchInput = document.querySelector('input[type="search"]');
    if (searchInput) searchInput.focus();
    }

// Esc to close modals
if (e.key === 'Escape') {
const modals = document.querySelectorAll('.modal.show');
modals.forEach(modal => {
const modalInstance = bootstrap.Modal.getInstance(modal);
if (modalInstance) modalInstance.hide();
});
}
});

