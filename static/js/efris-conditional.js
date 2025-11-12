// Dynamically show/hide EFRIS elements based on global setting
document.addEventListener('DOMContentLoaded', function() {
    const efrisEnabled = window.EFRIS_ENABLED || false;
    
    // Hide elements with .efris-only class if EFRIS is disabled
    if (!efrisEnabled) {
        document.querySelectorAll('.efris-only').forEach(el => {
            el.style.display = 'none';
        });
        
        // Remove EFRIS menu items
        document.querySelectorAll('[data-efris-required="true"]').forEach(el => {
            el.remove();
        });
        
        // Disable EFRIS form fields
        document.querySelectorAll('input[name*="efris"], select[name*="efris"]').forEach(field => {
            field.disabled = true;
            field.closest('.form-group')?.style.display = 'none';
        });
    } else {
        // Show EFRIS elements
        document.querySelectorAll('.efris-only').forEach(el => {
            el.style.display = '';
        });
    }
    
    // Update help text dynamically
    document.querySelectorAll('.efris-help').forEach(el => {
        const efrisText = el.dataset.efrisText;
        const defaultText = el.dataset.defaultText;
        el.textContent = efrisEnabled ? efrisText : defaultText;
    });
});