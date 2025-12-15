// Store Admin Custom JavaScript
document.addEventListener('DOMContentLoaded', function() {
    // Toggle EFRIS fields based on use_company_efris
    const useCompanyEfrisField = document.querySelector('[name="use_company_efris"]');
    const efrisOverrideFields = document.querySelectorAll('.field-store_efris_client_id, .field-store_efris_api_key, .field-store_efris_private_key, .field-store_efris_public_certificate, .field-store_efris_key_password, .field-store_efris_certificate_fingerprint, .field-store_efris_is_production, .field-store_efris_integration_mode, .field-store_auto_fiscalize_sales, .field-store_auto_sync_products, .field-store_efris_is_active, .field-store_efris_last_sync');

    function toggleEfrisFields() {
        const useCompany = useCompanyEfrisField ? useCompanyEfrisField.checked : true;

        efrisOverrideFields.forEach(field => {
            if (useCompany) {
                field.style.opacity = '0.6';
                field.style.pointerEvents = 'none';
            } else {
                field.style.opacity = '1';
                field.style.pointerEvents = 'auto';
            }
        });
    }

    if (useCompanyEfrisField) {
        useCompanyEfrisField.addEventListener('change', toggleEfrisFields);
        toggleEfrisFields(); // Initial state
    }

    // Add copy buttons for certificate fields
    const copyButtons = document.querySelectorAll('.copy-button');
    copyButtons.forEach(button => {
        button.addEventListener('click', function() {
            const targetId = this.getAttribute('data-target');
            const targetElement = document.getElementById(targetId);

            if (targetElement) {
                const textToCopy = targetElement.value || targetElement.textContent;

                navigator.clipboard.writeText(textToCopy).then(() => {
                    const originalText = this.innerHTML;
                    this.innerHTML = '<i class="bi bi-check"></i> Copied!';
                    this.classList.add('btn-success');

                    setTimeout(() => {
                        this.innerHTML = originalText;
                        this.classList.remove('btn-success');
                    }, 2000);
                }).catch(err => {
                    console.error('Failed to copy text: ', err);
                });
            }
        });
    });
});