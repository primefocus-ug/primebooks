/**
 * Service List Management
 * Handles AJAX operations, sorting, pagination, and filtering for services
 */

(function() {
    'use strict';

    // Configuration
    const CONFIG = {
        datatableUrl: document.getElementById('urls-config')?.dataset.datatableUrl || '',
        createUrl: document.getElementById('urls-config')?.dataset.createUrl || '',
        debounceDelay: 300,
        defaultPageSize: 25
    };

    // State management
    const state = {
        currentPage: 1,
        pageSize: CONFIG.defaultPageSize,
        sortColumn: 'name',
        sortOrder: 'asc',
        filters: {
            search: '',
            category: '',
            tax_rate: '',
            efris_status: '',
            is_active: ''
        },
        selectedServices: new Set(),
        loading: false
    };

    // DOM Elements
    const elements = {
        servicesTable: document.getElementById('servicesTable'),
        servicesTableBody: document.getElementById('servicesTableBody'),
        loadingOverlay: document.getElementById('loadingOverlay'),
        pagination: document.getElementById('pagination'),
        entriesInfo: document.getElementById('entriesInfo'),
        pageSize: document.getElementById('pageSize'),
        selectAllServices: document.getElementById('selectAllServices'),
        bulkActionsBtn: document.getElementById('bulkActionsBtn'),
        addServiceBtn: document.getElementById('addServiceBtn'),
        serviceModal: document.getElementById('serviceModal'),
        deleteModal: document.getElementById('deleteModal'),
        confirmDeleteBtn: document.getElementById('confirmDeleteBtn'),
        clearFilters: document.getElementById('clearFilters'),
        filterForm: document.getElementById('filterForm')
    };

    // Utility Functions
    const utils = {
        debounce: function(func, wait) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func(...args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        },

        showLoading: function() {
            if (elements.loadingOverlay) {
                elements.loadingOverlay.style.display = 'flex';
            }
            state.loading = true;
        },

        hideLoading: function() {
            if (elements.loadingOverlay) {
                elements.loadingOverlay.style.display = 'none';
            }
            state.loading = false;
        },

        showToast: function(message, type = 'success') {
            // Using Bootstrap Toast or simple alert
            if (typeof bootstrap !== 'undefined' && bootstrap.Toast) {
                const toastHtml = `
                    <div class="toast align-items-center text-white bg-${type}" role="alert" aria-live="assertive" aria-atomic="true">
                        <div class="d-flex">
                            <div class="toast-body">${message}</div>
                            <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
                        </div>
                    </div>
                `;
                const toastContainer = document.querySelector('.toast-container') || createToastContainer();
                toastContainer.insertAdjacentHTML('beforeend', toastHtml);
                const toastElement = toastContainer.lastElementChild;
                const toast = new bootstrap.Toast(toastElement);
                toast.show();
                toastElement.addEventListener('hidden.bs.toast', () => toastElement.remove());
            } else {
                alert(message);
            }
        },

        getCookie: function(name) {
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
        },

        formatCurrency: function(amount) {
            return new Intl.NumberFormat('en-US', {
                style: 'currency',
                currency: 'UGX',
                minimumFractionDigits: 0
            }).format(amount);
        },

        getUrlWithParams: function(baseUrl, params) {
            const url = new URL(baseUrl, window.location.origin);
            Object.keys(params).forEach(key => {
                if (params[key] !== '' && params[key] !== null && params[key] !== undefined) {
                    url.searchParams.append(key, params[key]);
                }
            });
            return url.toString();
        }
    };

    // Create toast container if it doesn't exist
    function createToastContainer() {
        const container = document.createElement('div');
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
        return container;
    }

    // API Functions
    const api = {
        fetchServices: async function() {
            const params = {
                page: state.currentPage,
                page_size: state.pageSize,
                ordering: state.sortOrder === 'desc' ? `-${state.sortColumn}` : state.sortColumn,
                ...state.filters
            };

            const url = utils.getUrlWithParams(CONFIG.datatableUrl, params);

            try {
                const response = await fetch(url, {
                    method: 'GET',
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                const data = await response.json();
                return data;
            } catch (error) {
                console.error('Error fetching services:', error);
                utils.showToast('Error loading services. Please try again.', 'danger');
                throw error;
            }
        },

        loadServiceForm: async function(serviceId = null) {
            const url = serviceId
                ? `/inventory/services/${serviceId}/edit/`
                : CONFIG.createUrl;

            try {
                const response = await fetch(url, {
                    headers: {
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                return await response.text();
            } catch (error) {
                console.error('Error loading form:', error);
                utils.showToast('Error loading form. Please try again.', 'danger');
                throw error;
            }
        },

        deleteService: async function(serviceId) {
            try {
                const response = await fetch(`/inventory/services/${serviceId}/delete/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': utils.getCookie('csrftoken'),
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                return await response.json();
            } catch (error) {
                console.error('Error deleting service:', error);
                throw error;
            }
        },

        bulkAction: async function(action, serviceIds) {
            try {
                const response = await fetch('/inventory/api/services/bulk-actions/', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': utils.getCookie('csrftoken'),
                        'X-Requested-With': 'XMLHttpRequest'
                    },
                    body: JSON.stringify({
                        action: action,
                        service_ids: Array.from(serviceIds)
                    })
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                return await response.json();
            } catch (error) {
                console.error('Error performing bulk action:', error);
                throw error;
            }
        },

        efrisSync: async function(serviceId) {
            try {
                const response = await fetch(`/inventory/api/services/${serviceId}/efris-sync/`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': utils.getCookie('csrftoken'),
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });

                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }

                return await response.json();
            } catch (error) {
                console.error('Error syncing with EFRIS:', error);
                throw error;
            }
        }
    };

    // Render Functions
    const render = {
        servicesTable: function(data) {
            if (!data.results || data.results.length === 0) {
                elements.servicesTableBody.innerHTML = `
                    <tr>
                        <td colspan="9" class="text-center text-muted py-4">
                            <i class="bi bi-inbox fs-1 d-block mb-2"></i>
                            No services found
                        </td>
                    </tr>
                `;
                return;
            }

            const rows = data.results.map(service => this.serviceRow(service)).join('');
            elements.servicesTableBody.innerHTML = rows;
        },

        serviceRow: function(service) {
            const isChecked = state.selectedServices.has(service.id) ? 'checked' : '';
            const efrisEnabled = document.querySelector('[data-efris-enabled]') !== null;

            return `
                <tr data-service-id="${service.id}">
                    <td>
                        <input type="checkbox" class="form-check-input table-checkbox service-checkbox"
                               value="${service.id}" ${isChecked}>
                    </td>
                    <td>
                        <strong>${service.name}</strong>
                        ${service.description ? `<br><small class="text-muted">${service.description}</small>` : ''}
                    </td>
                    <td><code>${service.code || 'N/A'}</code></td>
                    <td>${service.category_display || 'N/A'}</td>
                    <td>${utils.formatCurrency(service.unit_price)}</td>
                    <td>
                        <strong>${utils.formatCurrency(service.final_price)}</strong>
                        ${service.tax_rate > 0 ? `<br><small class="text-muted">Tax: ${service.tax_rate}%</small>` : ''}
                    </td>
                    ${efrisEnabled ? `
                    <td>
                        ${this.efrisStatusBadge(service)}
                    </td>
                    ` : ''}
                    <td>
                        ${service.is_active
                            ? '<span class="badge bg-success">Active</span>'
                            : '<span class="badge bg-secondary">Inactive</span>'}
                    </td>
                    <td>
                        <div class="btn-group btn-group-sm action-buttons" role="group">
                            <a href="/inventory/services/${service.id}/"
                               class="btn btn-outline-primary" title="View">
                                <i class="bi bi-eye"></i>
                            </a>
                            <button type="button" class="btn btn-outline-secondary edit-service-btn"
                                    data-service-id="${service.id}" title="Edit">
                                <i class="bi bi-pencil"></i>
                            </button>
                            ${efrisEnabled && !service.efris_uploaded ? `
                            <button type="button" class="btn btn-outline-info sync-efris-btn"
                                    data-service-id="${service.id}" title="Sync to EFRIS">
                                <i class="bi bi-cloud-arrow-up"></i>
                            </button>
                            ` : ''}
                            <button type="button" class="btn btn-outline-danger delete-service-btn"
                                    data-service-id="${service.id}" title="Delete">
                                <i class="bi bi-trash"></i>
                            </button>
                        </div>
                    </td>
                </tr>
            `;
        },

        efrisStatusBadge: function(service) {
            if (!service.enable_efris_sync) {
                return '<span class="badge bg-secondary">Disabled</span>';
            }
            if (service.efris_uploaded) {
                return `
                    <span class="badge bg-success">
                        <i class="bi bi-cloud-check"></i> Synced
                    </span>
                `;
            }
            return `
                <span class="badge bg-warning">
                    <i class="bi bi-clock"></i> Pending
                </span>
            `;
        },

        pagination: function(data) {
            if (!data.count || data.count <= state.pageSize) {
                elements.pagination.innerHTML = '';
                return;
            }

            const totalPages = Math.ceil(data.count / state.pageSize);
            const currentPage = state.currentPage;

            let paginationHtml = '';

            // Previous button
            paginationHtml += `
                <li class="page-item ${currentPage === 1 ? 'disabled' : ''}">
                    <a class="page-link" href="#" data-page="${currentPage - 1}">Previous</a>
                </li>
            `;

            // Page numbers
            const maxVisiblePages = 5;
            let startPage = Math.max(1, currentPage - Math.floor(maxVisiblePages / 2));
            let endPage = Math.min(totalPages, startPage + maxVisiblePages - 1);

            if (endPage - startPage < maxVisiblePages - 1) {
                startPage = Math.max(1, endPage - maxVisiblePages + 1);
            }

            if (startPage > 1) {
                paginationHtml += `<li class="page-item"><a class="page-link" href="#" data-page="1">1</a></li>`;
                if (startPage > 2) {
                    paginationHtml += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
                }
            }

            for (let i = startPage; i <= endPage; i++) {
                paginationHtml += `
                    <li class="page-item ${i === currentPage ? 'active' : ''}">
                        <a class="page-link" href="#" data-page="${i}">${i}</a>
                    </li>
                `;
            }

            if (endPage < totalPages) {
                if (endPage < totalPages - 1) {
                    paginationHtml += `<li class="page-item disabled"><span class="page-link">...</span></li>`;
                }
                paginationHtml += `<li class="page-item"><a class="page-link" href="#" data-page="${totalPages}">${totalPages}</a></li>`;
            }

            // Next button
            paginationHtml += `
                <li class="page-item ${currentPage === totalPages ? 'disabled' : ''}">
                    <a class="page-link" href="#" data-page="${currentPage + 1}">Next</a>
                </li>
            `;

            elements.pagination.innerHTML = paginationHtml;
        },

        entriesInfo: function(data) {
            if (!data.count) {
                elements.entriesInfo.textContent = 'Showing 0 to 0 of 0 entries';
                return;
            }

            const start = (state.currentPage - 1) * state.pageSize + 1;
            const end = Math.min(state.currentPage * state.pageSize, data.count);
            elements.entriesInfo.textContent = `Showing ${start} to ${end} of ${data.count} entries`;
        },

        updateStatistics: function(data) {
            if (data.statistics) {
                const stats = data.statistics;

                if (document.getElementById('totalServicesCount')) {
                    document.getElementById('totalServicesCount').textContent = stats.total || 0;
                }
                if (document.getElementById('activeServicesCount')) {
                    document.getElementById('activeServicesCount').textContent = stats.active || 0;
                }
                if (document.getElementById('efrisSyncedCount')) {
                    document.getElementById('efrisSyncedCount').textContent = stats.efris_synced || 0;
                }
                if (document.getElementById('pendingUploadCount')) {
                    document.getElementById('pendingUploadCount').textContent = stats.pending_upload || 0;
                }
            }
        }
    };

    // Event Handlers
    const handlers = {
        loadServices: async function() {
            if (state.loading) return;

            utils.showLoading();
            try {
                const data = await api.fetchServices();
                render.servicesTable(data);
                render.pagination(data);
                render.entriesInfo(data);
                render.updateStatistics(data);
            } catch (error) {
                console.error('Error loading services:', error);
            } finally {
                utils.hideLoading();
            }
        },

        handleSort: function(column) {
            if (state.sortColumn === column) {
                state.sortOrder = state.sortOrder === 'asc' ? 'desc' : 'asc';
            } else {
                state.sortColumn = column;
                state.sortOrder = 'asc';
            }

            // Update sort icons
            document.querySelectorAll('.sortable').forEach(th => {
                th.classList.remove('sort-asc', 'sort-desc');
            });

            const sortedHeader = document.querySelector(`[data-column="${column}"]`);
            if (sortedHeader) {
                sortedHeader.classList.add(`sort-${state.sortOrder}`);
            }

            state.currentPage = 1;
            this.loadServices();
        },

        handlePageChange: function(page) {
            page = parseInt(page);
            if (page < 1 || isNaN(page)) return;

            state.currentPage = page;
            this.loadServices();
            window.scrollTo({ top: 0, behavior: 'smooth' });
        },

        handlePageSizeChange: function(newSize) {
            state.pageSize = parseInt(newSize);
            state.currentPage = 1;
            this.loadServices();
        },

        handleFilterChange: function() {
            state.filters.search = document.getElementById('id_search')?.value || '';
            state.filters.category = document.getElementById('id_category')?.value || '';
            state.filters.tax_rate = document.getElementById('id_tax_rate')?.value || '';
            state.filters.efris_status = document.getElementById('id_efris_status')?.value || '';
            state.filters.is_active = document.getElementById('id_is_active')?.value || '';

            state.currentPage = 1;
            this.loadServices();
        },

        handleClearFilters: function() {
            document.getElementById('id_search').value = '';
            document.getElementById('id_category').value = '';
            document.getElementById('id_tax_rate').value = '';
            document.getElementById('id_efris_status').value = '';
            document.getElementById('id_is_active').value = '';

            state.filters = {
                search: '',
                category: '',
                tax_rate: '',
                efris_status: '',
                is_active: ''
            };

            state.currentPage = 1;
            this.loadServices();
        },

        handleSelectAll: function(checked) {
            document.querySelectorAll('.service-checkbox').forEach(checkbox => {
                checkbox.checked = checked;
                const serviceId = parseInt(checkbox.value);
                if (checked) {
                    state.selectedServices.add(serviceId);
                } else {
                    state.selectedServices.delete(serviceId);
                }
            });
            this.updateBulkActionsButton();
        },

        handleServiceSelect: function(serviceId, checked) {
            if (checked) {
                state.selectedServices.add(serviceId);
            } else {
                state.selectedServices.delete(serviceId);
            }

            // Update "select all" checkbox
            const allCheckboxes = document.querySelectorAll('.service-checkbox');
            const checkedCheckboxes = document.querySelectorAll('.service-checkbox:checked');
            elements.selectAllServices.checked = allCheckboxes.length === checkedCheckboxes.length;
            elements.selectAllServices.indeterminate = checkedCheckboxes.length > 0 && allCheckboxes.length !== checkedCheckboxes.length;

            this.updateBulkActionsButton();
        },

        updateBulkActionsButton: function() {
            if (elements.bulkActionsBtn) {
                elements.bulkActionsBtn.disabled = state.selectedServices.size === 0;
            }
        },

        handleBulkAction: async function(action) {
            if (state.selectedServices.size === 0) {
                utils.showToast('Please select at least one service', 'warning');
                return;
            }

            const actionMessages = {
                activate: 'activate',
                deactivate: 'deactivate',
                enable_efris: 'enable EFRIS sync for',
                disable_efris: 'disable EFRIS sync for',
                mark_for_upload: 'mark for upload',
                delete: 'delete'
            };

            const message = actionMessages[action] || 'perform action on';

            if (action === 'delete') {
                if (!confirm(`Are you sure you want to delete ${state.selectedServices.size} service(s)? This action cannot be undone.`)) {
                    return;
                }
            } else {
                if (!confirm(`Are you sure you want to ${message} ${state.selectedServices.size} service(s)?`)) {
                    return;
                }
            }

            utils.showLoading();
            try {
                const result = await api.bulkAction(action, state.selectedServices);
                utils.showToast(result.message || 'Bulk action completed successfully', 'success');
                state.selectedServices.clear();
                elements.selectAllServices.checked = false;
                await this.loadServices();
            } catch (error) {
                utils.showToast('Error performing bulk action. Please try again.', 'danger');
            } finally {
                utils.hideLoading();
            }
        },

        handleAddService: async function() {
            try {
                const formHtml = await api.loadServiceForm();
                document.getElementById('serviceModalBody').innerHTML = formHtml;
                document.getElementById('modalTitle').textContent = 'Add Service';

                const modal = new bootstrap.Modal(elements.serviceModal);
                modal.show();

                // Initialize form handler
                this.initializeServiceForm();
            } catch (error) {
                utils.showToast('Error loading service form', 'danger');
            }
        },

        handleEditService: async function(serviceId) {
            try {
                const formHtml = await api.loadServiceForm(serviceId);
                document.getElementById('serviceModalBody').innerHTML = formHtml;
                document.getElementById('modalTitle').textContent = 'Edit Service';

                const modal = new bootstrap.Modal(elements.serviceModal);
                modal.show();

                // Initialize form handler
                this.initializeServiceForm(serviceId);
            } catch (error) {
                utils.showToast('Error loading service form', 'danger');
            }
        },

        initializeServiceForm: function(serviceId = null) {
            const form = document.querySelector('#serviceModalBody form');
            if (!form) return;

            form.addEventListener('submit', async (e) => {
                e.preventDefault();

                const formData = new FormData(form);
                const url = serviceId
                    ? `/inventory/services/${serviceId}/edit/`
                    : CONFIG.createUrl;

                try {
                    const response = await fetch(url, {
                        method: 'POST',
                        body: formData,
                        headers: {
                            'X-CSRFToken': utils.getCookie('csrftoken'),
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    });

                    const result = await response.json();

                    if (result.success) {
                        utils.showToast(result.message || 'Service saved successfully', 'success');
                        bootstrap.Modal.getInstance(elements.serviceModal).hide();
                        await handlers.loadServices();
                    } else {
                        // Display form errors
                        if (result.errors) {
                            Object.keys(result.errors).forEach(field => {
                                const input = form.querySelector(`[name="${field}"]`);
                                if (input) {
                                    const errorDiv = document.createElement('div');
                                    errorDiv.className = 'invalid-feedback d-block';
                                    errorDiv.textContent = result.errors[field].join(', ');
                                    input.classList.add('is-invalid');
                                    input.parentNode.appendChild(errorDiv);
                                }
                            });
                        }
                        utils.showToast(result.message || 'Error saving service', 'danger');
                    }
                } catch (error) {
                    console.error('Error saving service:', error);
                    utils.showToast('Error saving service. Please try again.', 'danger');
                }
            });
        },

        handleDeleteService: function(serviceId) {
            const modal = new bootstrap.Modal(elements.deleteModal);
            modal.show();

            // Remove previous event listeners
            const newConfirmBtn = elements.confirmDeleteBtn.cloneNode(true);
            elements.confirmDeleteBtn.parentNode.replaceChild(newConfirmBtn, elements.confirmDeleteBtn);
            elements.confirmDeleteBtn = newConfirmBtn;

            elements.confirmDeleteBtn.addEventListener('click', async () => {
                try {
                    await api.deleteService(serviceId);
                    utils.showToast('Service deleted successfully', 'success');
                    modal.hide();
                    await handlers.loadServices();
                } catch (error) {
                    utils.showToast('Error deleting service. Please try again.', 'danger');
                }
            });
        },

        handleEfrisSync: async function(serviceId) {
            if (!confirm('Are you sure you want to sync this service to EFRIS?')) {
                return;
            }

            try {
                const result = await api.efrisSync(serviceId);
                utils.showToast(result.message || 'Service synced to EFRIS successfully', 'success');
                await this.loadServices();
            } catch (error) {
                utils.showToast('Error syncing to EFRIS. Please try again.', 'danger');
            }
        }
    };

    // Initialize event listeners
    function initEventListeners() {
        // Page size change
        if (elements.pageSize) {
            elements.pageSize.addEventListener('change', (e) => {
                handlers.handlePageSizeChange(e.target.value);
            });
        }

        // Sortable headers
        document.querySelectorAll('.sortable').forEach(header => {
            header.addEventListener('click', () => {
                const column = header.dataset.column;
                handlers.handleSort(column);
            });
        });

        // Pagination
        if (elements.pagination) {
            elements.pagination.addEventListener('click', (e) => {
                e.preventDefault();
                if (e.target.tagName === 'A' && e.target.dataset.page) {
                    handlers.handlePageChange(e.target.dataset.page);
                }
            });
        }

        // Filter inputs with debounce
        const debouncedFilter = utils.debounce(() => handlers.handleFilterChange(), CONFIG.debounceDelay);

        ['id_search', 'id_category', 'id_tax_rate', 'id_efris_status', 'id_is_active'].forEach(id => {
            const element = document.getElementById(id);
            if (element) {
                element.addEventListener('input', debouncedFilter);
                element.addEventListener('change', debouncedFilter);
            }
        });

        // Clear filters
        if (elements.clearFilters) {
            elements.clearFilters.addEventListener('click', () => {
                handlers.handleClearFilters();
            });
        }

        // Select all checkbox
        if (elements.selectAllServices) {
            elements.selectAllServices.addEventListener('change', (e) => {
                handlers.handleSelectAll(e.target.checked);
            });
        }

        // Service table events (using event delegation)
        if (elements.servicesTableBody) {
            elements.servicesTableBody.addEventListener('change', (e) => {
                if (e.target.classList.contains('service-checkbox')) {
                    const serviceId = parseInt(e.target.value);
                    handlers.handleServiceSelect(serviceId, e.target.checked);
                }
            });

            elements.servicesTableBody.addEventListener('click', (e) => {
                const target = e.target.closest('button');
                if (!target) return;

                const serviceId = parseInt(target.dataset.serviceId);

                if (target.classList.contains('edit-service-btn')) {
                    handlers.handleEditService(serviceId);
                } else if (target.classList.contains('delete-service-btn')) {
                    handlers.handleDeleteService(serviceId);
                } else if (target.classList.contains('sync-efris-btn')) {
                    handlers.handleEfrisSync(serviceId);
                }
            });
        }

        // Add service button
        if (elements.addServiceBtn) {
            elements.addServiceBtn.addEventListener('click', () => {
                handlers.handleAddService();
            });
        }

        // Bulk actions
        document.querySelectorAll('.bulk-action').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const action = link.dataset.action;
                handlers.handleBulkAction(action);
            });
        });
    }

    // Initialize
    function init() {
        if (!CONFIG.datatableUrl) {
            console.error('Datatable URL not configured');
            return;
        }

        initEventListeners();
        handlers.loadServices();
    }

    // Start when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();