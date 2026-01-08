async function queryEFRISTaxpayer() {
    const tinInput = document.getElementById('taxpayerTIN');
    const queryBtn = document.getElementById('efrisQueryBtn');
    const queryLoading = document.getElementById('efrisQueryLoading');
    const results = document.getElementById('efrisQueryResults');
    const errorDiv = document.getElementById('efrisError');
    const errorMessage = document.getElementById('efrisErrorMessage');

    if (!tinInput || !queryBtn) {
        console.error('EFRIS elements not found');
        return;
    }

    const tin = tinInput.value.trim();

    // Clear previous errors
    if (errorDiv) errorDiv.style.display = 'none';

    if (!tin) {
        showError('Please enter TIN');
        return;
    }

    const tinRegex = /^\d{10}$/;
    if (!tinRegex.test(tin)) {
        showError('Please enter a valid 10-digit TIN');
        return;
    }

    queryBtn.disabled = true;
    if (queryLoading) queryLoading.style.display = 'block';
    if (results) results.style.display = 'none';

    try {
        // ✅ FIX 1: Get CSRF token from form (like Document 3)
        const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]')?.value;
        
        if (!csrfToken) {
            throw new Error('CSRF token missing. Please refresh the page.');
        }

        const formData = new FormData();
        formData.append('tin', tin);

        // ✅ FIX 2: Use Django URL template tag
        const response = await fetch('{% url "efris:taxpayer_query" %}', {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': csrfToken,
                'X-Requested-With': 'XMLHttpRequest'
            },
            credentials: 'same-origin'
        });

        if (!response.ok) {
            const errorText = await response.text();
            throw new Error(`HTTP ${response.status}: ${response.statusText}\n${errorText}`);
        }

        const data = await response.json();

        if (data.success && data.taxpayer) {
            displayEFRISResults(data.taxpayer);
        } else {
            throw new Error(data.error || 'Taxpayer not found in EFRIS system');
        }
    } catch (error) {
        console.error('EFRIS query error:', error);
        
        // Show error in both places
        if (errorDiv && errorMessage) {
            errorMessage.textContent = error.message;
            errorDiv.style.display = 'block';
        }
        showError(`EFRIS query failed: ${error.message}`);
    } finally {
        queryBtn.disabled = false;
        if (queryLoading) queryLoading.style.display = 'none';
    }
}

function displayEFRISResults(taxpayer) {
    const results = document.getElementById('efrisQueryResults');
    if (!results) return;

    results.innerHTML = `
        <div class="card mt-3">
            <div class="card-body">
                <h6 class="card-title">${escapeHtml(taxpayer.legal_name || taxpayer.name)}</h6>
                <p class="mb-1"><strong>TIN:</strong> ${escapeHtml(taxpayer.tin)}</p>
                <p class="mb-1"><strong>Type:</strong> ${escapeHtml(taxpayer.taxpayer_type || 'N/A')}</p>
                ${taxpayer.address ? `<p class="mb-1"><strong>Address:</strong> ${escapeHtml(taxpayer.address)}</p>` : ''}
                ${taxpayer.phone ? `<p class="mb-1"><strong>Phone:</strong> ${escapeHtml(taxpayer.phone)}</p>` : ''}
                ${taxpayer.email ? `<p class="mb-3"><strong>Email:</strong> ${escapeHtml(taxpayer.email)}</p>` : ''}
                
                <div class="d-flex gap-2">
                    <button type="button" class="btn btn-success btn-sm flex-fill"
                            onclick='createCustomerFromEFRIS(${JSON.stringify(taxpayer).replace(/'/g, "&#39;")})'>
                        <i class="bi bi-person-plus me-1"></i> Create Customer
                    </button>
                    <button type="button" class="btn btn-outline-primary btn-sm flex-fill"
                            onclick='selectEFRISTaxpayer(${JSON.stringify(taxpayer).replace(/'/g, "&#39;")})'>
                        <i class="bi bi-check-circle me-1"></i> Use This
                    </button>
                </div>
            </div>
        </div>
    `;

    results.style.display = 'block';
}

function selectEFRISTaxpayer(taxpayer) {
    const customer = {
        id: null,
        name: taxpayer.legal_name || taxpayer.name,
        phone: taxpayer.phone || taxpayer.tin.slice(-9),
        email: taxpayer.email || '',
        tin: taxpayer.tin,
        from_efris: true
    };

    selectCustomer(customer);
    
    // Hide EFRIS results
    const efrisResults = document.getElementById('efrisQueryResults');
    const taxpayerTIN = document.getElementById('taxpayerTIN');
    if (efrisResults) efrisResults.style.display = 'none';
    if (taxpayerTIN) taxpayerTIN.value = '';

    // Switch back to search tab
    const searchTab = document.querySelector('[data-bs-target="#searchTab"]');
    if (searchTab) {
        new bootstrap.Tab(searchTab).show();
    }
    
    showSuccess(`Selected taxpayer: ${customer.name}`);
}

async function createCustomerFromEFRIS(taxpayer) {
    const formData = new FormData();
    formData.append('name', taxpayer.legal_name || taxpayer.name);
    formData.append('tin', taxpayer.tin);
    formData.append('phone', taxpayer.phone || taxpayer.tin.slice(-9));
    formData.append('email', taxpayer.email || '');
    formData.append('address', taxpayer.address || '');
    formData.append('from_efris', 'true');

    try {
        // ✅ FIX: Use the correct URL (same as create customer)
        const response = await fetch('{% url "sales:create_customer_ajax" %}', {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value
            }
        });

        const data = await response.json();

        if (data.success) {
            selectCustomer(data.customer);
            
            // Hide EFRIS results
            const efrisResults = document.getElementById('efrisQueryResults');
            const taxpayerTIN = document.getElementById('taxpayerTIN');
            if (efrisResults) efrisResults.style.display = 'none';
            if (taxpayerTIN) taxpayerTIN.value = '';

            // Switch to search tab
            const searchTab = document.querySelector('[data-bs-target="#searchTab"]');
            if (searchTab) {
                new bootstrap.Tab(searchTab).show();
            }

            showSuccess('Customer created from EFRIS successfully');
        } else {
            throw new Error(data.error || 'Failed to create customer');
        }
    } catch (error) {
        showError(error.message);
    }
}

// Helper function for escaping HTML (if not already present)
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}