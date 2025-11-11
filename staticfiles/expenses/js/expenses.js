// Expense Management JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Initialize tooltips
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });

    // File upload preview
    const fileInputs = document.querySelectorAll('input[type="file"]');
    fileInputs.forEach(input => {
        input.addEventListener('change', function(e) {
            const files = Array.from(e.target.files);
            const fileList = document.createElement('div');
            fileList.className = 'mt-2';

            files.forEach(file => {
                const fileItem = document.createElement('div');
                fileItem.className = 'alert alert-info alert-dismissible fade show';
                fileItem.innerHTML = `
                    <i class="bi bi-file-earmark me-2"></i>
                    ${file.name} (${(file.size / 1024).toFixed(2)} KB)
                    <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
                `;
                fileList.appendChild(fileItem);
            });

            const existingList = input.parentElement.querySelector('.file-list');
            if (existingList) {
                existingList.remove();
            }

            fileList.classList.add('file-list');
            input.parentElement.appendChild(fileList);
        });
    });

    // Confirmation dialogs
    const deleteButtons = document.querySelectorAll('.btn-delete-expense');
    deleteButtons.forEach(button => {
        button.addEventListener('click', function(e) {
            if (!confirm('Are you sure you want to delete this expense?')) {
                e.preventDefault();
            }
        });
    });

    // Auto-calculate tax
    const amountInput = document.querySelector('input[name="amount"]');
    const taxRateInput = document.querySelector('input[name="tax_rate"]');

    if (amountInput && taxRateInput) {
        const calculateTax = () => {
            const amount = parseFloat(amountInput.value) || 0;
            const taxRate = parseFloat(taxRateInput.value) || 0;
            const taxAmount = (amount * taxRate / 100).toFixed(2);
            const total = (amount + parseFloat(taxAmount)).toFixed(2);

            // Display calculated values
            const taxDisplay = document.getElementById('tax-amount-display');
            const totalDisplay = document.getElementById('total-amount-display');

            if (taxDisplay) taxDisplay.textContent = taxAmount;
            if (totalDisplay) totalDisplay.textContent = total;
        };

        amountInput.addEventListener('input', calculateTax);
        taxRateInput.addEventListener('input', calculateTax);
    }

    // Bulk selection
    const selectAllCheckbox = document.getElementById('select-all-expenses');
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function() {
            const checkboxes = document.querySelectorAll('.expense-checkbox');
            checkboxes.forEach(cb => cb.checked = this.checked);
        });
    }

    // Search functionality
    const searchInput = document.getElementById('expense-search');
    if (searchInput) {
        let searchTimeout;
        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                performSearch(this.value}, 500);
        });
    }
});

// Search expenses via AJAX
function performSearch(query) {
    if (query.length < 2) return;

    fetch(`/expenses/api/search/?q=${encodeURIComponent(query)}`)
        .then(response => response.json())
        .then(data => {
            displaySearchResults(data.results);
        })
        .catch(error => {
            console.error('Search error:', error);
        });
}

function displaySearchResults(results) {
    const resultsContainer = document.getElementById('search-results');
    if (!resultsContainer) return;

    if (results.length === 0) {
        resultsContainer.innerHTML = '<div class="alert alert-info">No results found</div>';
        return;
    }

    const html = results.map(expense => `
        <a href="${expense.url}" class="list-group-item list-group-item-action">
            <div class="d-flex justify-content-between align-items-center">
                <div>
                    <h6 class="mb-1">${expense.expense_number}</h6>
                    <p class="mb-0 small text-muted">${expense.title}</p>
                </div>
                <span class="badge bg-primary">${expense.amount} ${expense.currency}</span>
            </div>
        </a>
    `).join('');

    resultsContainer.innerHTML = html;
}

// Chart initialization
function initializeExpenseCharts() {
    // This would be called from templates with specific data
    console.log('Charts initialized');
}

// Export functionality
function exportExpenses(format) {
    const selectedIds = Array.from(document.querySelectorAll('.expense-checkbox:checked'))
        .map(cb => cb.value);

    if (selectedIds.length === 0) {
        alert('Please select at least one expense to export');
        return;
    }

    fetch('/expenses/api/bulk-action/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            action: 'export',
            expense_ids: selectedIds,
            format: format
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Export started. You will receive a notification when ready.');
        } else {
            alert('Export failed: ' + data.error);
        }
    });
}

// Bulk actions
function performBulkAction(action) {
    const selectedIds = Array.from(document.querySelectorAll('.expense-checkbox:checked'))
        .map(cb => cb.value);

    if (selectedIds.length === 0) {
        alert('Please select at least one expense');
        return;
    }

    if (!confirm(`Are you sure you want to ${action} ${selectedIds.length} expense(s)?`)) {
        return;
    }

    fetch('/expenses/api/bulk-action/', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            action: action,
            expense_ids: selectedIds
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(`Successfully processed ${data.processed} expense(s)`);
            location.reload();
        } else {
            alert('Action failed: ' + data.error);
        }
    });
}

// Quick approve from list
function quickApprove(expenseId) {
    if (!confirm('Are you sure you want to approve this expense?')) {
        return;
    }

    fetch(`/expenses/api/${expenseId}/quick-approve/`, {
        method: 'POST',
        headers: {
            'X-CSRFToken': getCookie('csrftoken')
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert(data.message);
            location.reload();
        } else {
            alert('Approval failed: ' + data.error);
        }
    });
}

// Utility: Get CSRF token
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

// Load budget utilization chart
function loadBudgetChart() {
    fetch('/expenses/api/budget-utilization/')
        .then(response => response.json())
        .then(data => {
            const ctx = document.getElementById('budgetChart');
            if (!ctx) return;

            new Chart(ctx.getContext('2d'), {
                type: 'bar',
                data: {
                    labels: data.budgets.map(b => b.category),
                    datasets: [{
                        label: 'Spent',
                        data: data.budgets.map(b => b.spent),
                        backgroundColor: data.budgets.map(b => b.color)
                    }, {
                        label: 'Budget',
                        data: data.budgets.map(b => b.budget),
                        backgroundColor: 'rgba(200, 200, 200, 0.3)'
                    }]
                },
                options: {
                    responsive: true,
                    scales: {
                        y: {
                            beginAtZero: true
                        }
                    }
                }
            });
        });
}

// Real-time updates via WebSocket
function initializeWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/expenses/`;

    try {
        const socket = new WebSocket(wsUrl);

        socket.onopen = function(e) {
            console.log('WebSocket connected');
        };

        socket.onmessage = function(event) {
            const data = JSON.parse(event.data);
            handleWebSocketMessage(data);
        };

        socket.onerror = function(error) {
            console.error('WebSocket error:', error);
        };

        socket.onclose = function(event) {
            console.log('WebSocket disconnected');
            // Attempt to reconnect after 5 seconds
            setTimeout(initializeWebSocket, 5000);
        };

        // Keep connection alive
        setInterval(() => {
            if (socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({type: 'ping'}));
            }
        }, 30000);

    } catch (error) {
        console.warn('WebSocket not available:', error);
    }
}

function handleWebSocketMessage(data) {
    switch(data.type) {
        case 'expense_update':
            showNotification(data.message, 'info');
            updateExpenseStatus(data.expense_id, data.status);
            break;
        case 'expense_comment':
            showNotification('New comment added', 'info');
            break;
        case 'notification':
            showNotification(data.message, data.notification_type);
            break;
    }
}

function showNotification(message, type = 'info') {
    const alertDiv = document.createElement('div');
    alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed top-0 end-0 m-3`;
    alertDiv.style.zIndex = '9999';
    alertDiv.innerHTML = `
        ${message}
        <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;

    document.body.appendChild(alertDiv);

    setTimeout(() => {
        alertDiv.remove();
    }, 5000);
}

function updateExpenseStatus(expenseId, newStatus) {
    const statusBadges = document.querySelectorAll(`[data-expense-id="${expenseId}"] .status-badge`);
    statusBadges.forEach(badge => {
        // Update badge based on new status
        badge.className = `badge bg-${getStatusColor(newStatus)}`;
        badge.textContent = newStatus;
    });
}

function getStatusColor(status) {
    const colors = {
        'DRAFT': 'secondary',
        'SUBMITTED': 'warning',
        'APPROVED': 'info',
        'REJECTED': 'danger',
        'PAID': 'success'
    };
    return colors[status] || 'secondary';
}

// Initialize on load
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initializeWebSocket);
} else {
    initializeWebSocket();
}
