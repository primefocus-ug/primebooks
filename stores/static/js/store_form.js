function toggleEFRISFields(useCompany) {
    const storeFields = document.querySelectorAll('.store-efris-field');
    const copyCheckbox = document.getElementById('id_copy_from_company');

    storeFields.forEach(field => {
        if (useCompany) {
            field.closest('.form-group')?.classList.add('d-none');
            field.disabled = true;
        } else {
            field.closest('.form-group')?.classList.remove('d-none');
            field.disabled = false;
        }
    });

    // Show/hide copy checkbox
    if (copyCheckbox) {
        if (useCompany) {
            copyCheckbox.closest('.form-group')?.classList.add('d-none');
        } else {
            copyCheckbox.closest('.form-group')?.classList.remove('d-none');
        }
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    const useCompanyCheckbox = document.getElementById('id_use_company_efris');
    if (useCompanyCheckbox) {
        toggleEFRISFields(useCompanyCheckbox.checked);
        useCompanyCheckbox.addEventListener('change', function() {
            toggleEFRISFields(this.checked);
        });
    }
});