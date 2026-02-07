/**
 * Main initialization file for inventory forms
 */

import {
    initializeSelect2,
    initializeTooltips
} from './form-base.js';

import { initializeModalHandlers } from './modal-handlers.js';
import { initializeProductForm } from './product-form.js';
import { initializeCategoryForm } from './category-form.js';
import { initializeStockForm } from './stock-form.js';
import { initializeSupplierForm } from './supplier-form.js';

// Main initialization
$(document).ready(function() {
    console.log('Inventory forms initializing...');

    // Initialize global components
    initializeSelect2();
    initializeTooltips();

    // Get URLs from data attributes
    const categoryCreateUrl = $('body').data('category-create-url');
    const supplierCreateUrl = $('body').data('supplier-create-url');

    // Initialize modal handlers
    if (categoryCreateUrl && supplierCreateUrl) {
        initializeModalHandlers(categoryCreateUrl, supplierCreateUrl);
    }

    // Initialize specific forms based on what's present
    initializeProductForm();
    initializeCategoryForm();
    initializeStockForm();
    initializeSupplierForm();

    // Prevent double submission
    $('form').on('submit', function() {
        const $form = $(this);
        if ($form.data('submitted')) {
            return false;
        }
        $form.data('submitted', true);
    });

    // Reset form submission flag on error
    $(document).ajaxError(function() {
        $('form').data('submitted', false);
    });

    console.log('Inventory forms initialized');
});