document.addEventListener('DOMContentLoaded', function() {
    // EFRIS fields toggle
    const efrisEnabled = document.getElementById('{{ form.efris_enabled.id_for_label }}');
    const efrisFields = document.getElementById('efris-fields');
    
    function toggleEfrisFields() {
        if (efrisEnabled && efrisEnabled.checked) {
            efrisFields.style.display = 'block';
        } else {
            efrisFields.style.display = 'none';
        }
    }
    
    if (efrisEnabled) {
        efrisEnabled.addEventListener('change', toggleEfrisFields);
        toggleEfrisFields(); // Initial state
    }
    
    // Form validation
    const form = document.getElementById('companyForm');
    if (form) {
        form.addEventListener('submit', function(e) {
            let isValid = true;
            const requiredFields = form.querySelectorAll('[required]');
            
            requiredFields.forEach(field => {
                if (!field.value.trim()) {
                    field.classList.add('is-invalid');
                    isValid = false;
                } else {
                    field.classList.remove('is-invalid');
                }
            });
            
            if (!isValid) {
                e.preventDefault();
                // Show first tab with error
                const firstError = form.querySelector('.is-invalid');
                if (firstError) {
                    const tabPane = firstError.closest('.tab-pane');
                    if (tabPane) {
                        const tabId = tabPane.id;
                        const tabButton = document.querySelector(`button[data-bs-target="#${tabId}"]`);
                        if (tabButton) {
                            tabButton.click();
                        }
                    }
                    firstError.focus();
                }
                
                window.scrollTo({ top: 0, behavior: 'smooth' });
            }
        });
    }
    
    // Branch Formset Management
    const branchFormset = document.getElementById('branch-formset');
    if (branchFormset) {
        const addBranchButton = document.getElementById('add-branch');
        const totalBranches = document.getElementById('id_branches-TOTAL_FORMS');
        const emptyBranchForm = document.getElementById('empty-branch-form').innerHTML;
        
        addBranchButton.addEventListener('click', function() {
            const formIdx = parseInt(totalBranches.value);
            const newForm = emptyBranchForm
                .replace(/__prefix__/g, formIdx)
                .replace('<span class="form-counter"></span>', formIdx + 1);
            
            branchFormset.insertAdjacentHTML('beforeend', newForm);
            totalBranches.value = formIdx + 1;
            
            // Add event listener to new remove button
            const newFormElement = branchFormset.lastElementChild;
            const removeButton = newFormElement.querySelector('.remove-branch');
            removeButton.addEventListener('click', function() {
                const deleteField = newFormElement.querySelector('[name*="DELETE"]');
                if (deleteField) {
                    deleteField.checked = true;
                    newFormElement.style.display = 'none';
                } else {
                    newFormElement.remove();
                }
            });
        });
        
        // Add event listeners to existing remove buttons
        document.querySelectorAll('.remove-branch').forEach(button => {
            button.addEventListener('click', function() {
                const form = this.closest('.branch-form');
                const deleteField = form.querySelector('[name*="DELETE"]');
                if (deleteField) {
                    deleteField.checked = true;
                    form.style.display = 'none';
                } else {
                    form.remove();
                }
            });
        });
    }
    
    // Employee Formset Management
    const employeeFormset = document.getElementById('employee-formset');
    if (employeeFormset) {
        const addEmployeeButton = document.getElementById('add-employee');
        const totalEmployees = document.getElementById('id_employees-TOTAL_FORMS');
        const emptyEmployeeForm = document.getElementById('empty-employee-form').innerHTML;
        
        addEmployeeButton.addEventListener('click', function() {
            const formIdx = parseInt(totalEmployees.value);
            const newForm = emptyEmployeeForm
                .replace(/__prefix__/g, formIdx)
                .replace('<span class="form-counter"></span>', formIdx + 1);
            
            employeeFormset.insertAdjacentHTML('beforeend', newForm);
            totalEmployees.value = formIdx + 1;
            
            // Add event listener to new remove button
            const newFormElement = employeeFormset.lastElementChild;
            const removeButton = newFormElement.querySelector('.remove-employee');
            removeButton.addEventListener('click', function() {
                const deleteField = newFormElement.querySelector('[name*="DELETE"]');
                if (deleteField) {
                    deleteField.checked = true;
                    newFormElement.style.display = 'none';
                } else {
                    newFormElement.remove();
                }
            });
        });
        
        // Add event listeners to existing remove buttons
        document.querySelectorAll('.remove-employee').forEach(button => {
            button.addEventListener('click', function() {
                const form = this.closest('.employee-form');
                const deleteField = form.querySelector('[name*="DELETE"]');
                if (deleteField) {
                    deleteField.checked = true;
                    form.style.display = 'none';
                } else {
                    form.remove();
                }
            });
        });
    }
    
    // Auto-save draft (optional)
    let saveTimeout;
    if (form) {
        const formInputs = form.querySelectorAll('input, textarea, select');
        
        formInputs.forEach(input => {
            input.addEventListener('input', function() {
                clearTimeout(saveTimeout);
                saveTimeout = setTimeout(saveDraft, 2000);
            });
        });
        
        function saveDraft() {
            // Save form data to localStorage
            const formData = new FormData(form);
            const data = {};
            for (let [key, value] of formData.entries()) {
                data[key] = value;
            }
            localStorage.setItem('company_form_draft', JSON.stringify(data));
            
            // Show save indicator
            const saveIndicator = document.createElement('div');
            saveIndicator.className = 'position-fixed top-0 end-0 m-3 alert alert-success alert-dismissible fade show';
            saveIndicator.style.zIndex = '9999';
            saveIndicator.innerHTML = `
                <i class="bi bi-check-circle me-2"></i>
                {% trans "Draft saved" %}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            `;
            document.body.appendChild(saveIndicator);
            
            setTimeout(() => {
                saveIndicator.remove();
            }, 2000);
        }
        
        // Load draft on page load
        if (!{{ object|yesno:'true,false' }}) {
            const savedDraft = localStorage.getItem('company_form_draft');
            if (savedDraft) {
                const data = JSON.parse(savedDraft);
                Object.keys(data).forEach(key => {
                    const field = form.querySelector(`[name="${key}"]`);
                    if (field && field.type !== 'file') {
                        field.value = data[key];
                    }
                });
            }
        }
        
        // Clear draft on successful submit
        form.addEventListener('submit', function() {
            localStorage.removeItem('company_form_draft');
        });
    }
});