/**
 * Product form specific logic
 */

import { FormValidator, debounce, showSuccessMessage } from './form-base.js';

class ProductFormHandler {
    constructor() {
        this.form = $('#productForm');
        this.validator = new FormValidator('#productForm');
        this.init();
    }

    init() {
        this.initializeCalculations();
        this.initializeGenerators();
        this.initializeCategorySync();
        this.initializeExportFields();
        this.initializePieceUnitFields();
        this.initializeValidation();
    }

    initializeCalculations() {
        const updateCalculations = () => {
            const costPrice = parseFloat($('#id_cost_price').val()) || 0;
            const sellingPrice = parseFloat($('#id_selling_price').val()) || 0;
            const discountPercentage = parseFloat($('#id_discount_percentage').val()) || 0;
            const taxRate = $('#id_tax_rate').val();

            const profit = sellingPrice - costPrice;
            const profitMargin = costPrice > 0 ? ((profit / costPrice) * 100) : 0;
            const discountAmount = (discountPercentage / 100) * sellingPrice;
            const finalPrice = sellingPrice - discountAmount;

            let taxPercentage = 0;
            if (['A', 'D', 'E'].includes(taxRate)) {
                taxPercentage = 18;
            }
            const taxAmount = (taxPercentage / 100) * finalPrice;

            // Update UI (if elements exist)
            this.updateCalculationDisplay({
                profitMargin,
                profit,
                finalPrice,
                taxAmount
            });
        };

        $('#id_cost_price, #id_selling_price, #id_discount_percentage, #id_tax_rate')
            .on('input change', debounce(updateCalculations, 300));

        // Initial calculation
        updateCalculations();
    }

    updateCalculationDisplay(values) {
        const { profitMargin, profit, finalPrice, taxAmount } = values;

        if ($('#profitMargin').length) {
            $('#profitMargin').text(`${profitMargin.toFixed(2)}%`)
                .removeClass('text-success text-warning text-danger')
                .addClass(
                    profitMargin < 10 ? 'text-danger' :
                    profitMargin < 20 ? 'text-warning' : 'text-success'
                );
        }

        if ($('#profitAmount').length) {
            $('#profitAmount').text(`UGX ${profit.toLocaleString('en-UG', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            })}`);
        }

        if ($('#finalPrice').length) {
            $('#finalPrice').text(`UGX ${finalPrice.toLocaleString('en-UG', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            })}`);
        }

        if ($('#taxAmount').length) {
            $('#taxAmount').text(`UGX ${taxAmount.toLocaleString('en-UG', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2
            })}`);
        }
    }

    initializeGenerators() {
        // SKU Generator
        $('#generateSku').on('click', (e) => {
            e.preventDefault();
            this.generateSKU();
        });

        // Barcode Generator
        $('#generateBarcode').on('click', (e) => {
            e.preventDefault();
            this.generateBarcode();
        });
    }

    generateSKU() {
        const productName = $('#id_name').val().trim();
        const categoryText = $('#id_category option:selected').text();

        if (!productName) {
            showErrorMessage('Please enter product name first');
            $('#id_name').focus();
            return;
        }

        let sku = '';

        // Category prefix
        if (categoryText && categoryText !== '---------') {
            sku = categoryText.substring(0, 3).toUpperCase().replace(/[^A-Z0-9]/g, '') + '-';
        }

        // Product name prefix
        sku += productName.substring(0, 3).toUpperCase().replace(/[^A-Z0-9]/g, '') + '-';

        // Random suffix
        sku += Math.floor(Math.random() * 10000).toString().padStart(4, '0');

        $('#id_sku').val(sku).removeClass('is-invalid');
        showSuccessMessage('SKU generated successfully');
    }

    generateBarcode() {
        const sku = $('#id_sku').val().trim();

        if (!sku) {
            showErrorMessage('Please enter or generate SKU first');
            $('#id_sku').focus();
            return;
        }

        // EAN-13 format: 890-001-XXXXX-C
        const prefix = '890';
        const company = '001';
        const productPart = sku.replace(/[^0-9]/g, '').padStart(5, '0').substring(0, 5);
        const partial = prefix + company + productPart;

        // Calculate check digit
        let sum = 0;
        for (let i = 0; i < partial.length; i++) {
            sum += parseInt(partial[i]) * (i % 2 === 0 ? 1 : 3);
        }
        const checkDigit = (10 - (sum % 10)) % 10;
        const barcode = partial + checkDigit;

        $('#id_barcode').val(barcode).removeClass('is-invalid');
        showSuccessMessage('Barcode generated successfully');
    }

    initializeCategorySync() {
        $('#id_category').on('change', () => {
            const categoryId = $('#id_category').val();

            if (!categoryId) {
                this.updateEFRISCategoryDisplay('Will be inherited from selected category');
                return;
            }

            // Fetch category details
            $.ajax({
                url: `/inventory/api/category/${categoryId}/`,
                method: 'GET',
                success: (response) => {
                    if (response.efris_commodity_category) {
                        const category = response.efris_commodity_category;
                        this.updateEFRISCategoryDisplay(
                            `<strong>${category.code}</strong> - ${category.name}`
                        );
                    } else {
                        this.updateEFRISCategoryDisplay(
                            '<span class="text-warning"><i class="fas fa-exclamation-triangle"></i> Category has no EFRIS classification</span>'
                        );
                    }
                },
                error: () => {
                    this.updateEFRISCategoryDisplay('Error loading category details');
                }
            });
        });
    }

    updateEFRISCategoryDisplay(html) {
        if ($('#efrisCategoryText').length) {
            $('#efrisCategoryText').html(html);
        }
    }

    initializeExportFields() {
        const toggleExportFields = () => {
            const isExport = $('#id_is_export_product').is(':checked');

            if (isExport) {
                $('.export-field').addClass('border-info');
                $('#id_hs_code, #id_efris_customs_measure_unit').attr('required', true);

                if ($('#exportWarning').length === 0) {
                    const warning = $(`
                        <div id="exportWarning" class="alert alert-info mt-2" role="alert">
                            <i class="fas fa-info-circle"></i>
                            <strong>Export Product:</strong> Ensure HS Code and Customs Measure Unit are filled.
                        </div>
                    `);
                    warning.insertAfter($('#id_is_export_product').closest('.form-check'));
                }
            } else {
                $('.export-field').removeClass('border-info');
                $('#id_hs_code, #id_efris_customs_measure_unit').removeAttr('required');
                $('#exportWarning').remove();
            }

            this.checkExportReadiness();
        };

        $('#id_is_export_product').on('change', toggleExportFields);
        $('#id_hs_code, #id_efris_customs_measure_unit').on('change blur', () => {
            this.checkExportReadiness();
        });

        // Initialize
        toggleExportFields();
    }

    checkExportReadiness() {
        const hsCode = $('#id_hs_code').val();
        const customsUnit = $('#id_efris_customs_measure_unit').val();
        const isExport = $('#id_is_export_product').is(':checked');

        if (isExport && hsCode && customsUnit) {
            if (!$('#id_is_export_ready').is(':checked')) {
                $('#id_is_export_ready').prop('checked', true);
                showSuccessMessage('Product marked as export ready!');
            }
        } else if ($('#id_is_export_ready').is(':checked') && isExport) {
            $('#id_is_export_ready').prop('checked', false);
        }
    }

    initializePieceUnitFields() {
        const togglePieceUnitFields = () => {
            const isEnabled = $('#id_efris_has_piece_unit').is(':checked');

            if (isEnabled) {
                $('#pieceUnitFields').slideDown(300);
                $('#id_efris_piece_measure_unit, #id_efris_piece_unit_price').attr('required', true);
            } else {
                $('#pieceUnitFields').slideUp(300);
                $('#id_efris_piece_measure_unit, #id_efris_piece_unit_price').removeAttr('required');
            }
        };

        $('#id_efris_has_piece_unit').on('change', togglePieceUnitFields);

        // Initialize
        togglePieceUnitFields();
    }

    initializeValidation() {
        this.form.on('submit', (e) => {
            this.validator.clearErrors();

            // Basic validations
            if (!$('#id_name').val().trim()) {
                this.validator.addError('#id_name', 'Product name is required');
            }

            if (!$('#id_sku').val().trim()) {
                this.validator.addError('#id_sku', 'SKU is required');
            }

            if (!$('#id_category').val()) {
                this.validator.addError('#id_category', 'Category is required');
            }

            const costPrice = parseFloat($('#id_cost_price').val()) || 0;
            const sellingPrice = parseFloat($('#id_selling_price').val()) || 0;

            if (costPrice <= 0) {
                this.validator.addError('#id_cost_price', 'Cost price must be greater than 0');
            }

            if (sellingPrice <= 0) {
                this.validator.addError('#id_selling_price', 'Selling price must be greater than 0');
            }

            if (costPrice > sellingPrice) {
                this.validator.addError('#id_cost_price', 'Cost price cannot exceed selling price');
                this.validator.addError('#id_selling_price', 'Selling price must be greater than cost price');
            }

            // Export validations
            const isExport = $('#id_is_export_product').is(':checked');
            if (isExport) {
                if (!$('#id_hs_code').val()) {
                    this.validator.addError('#id_hs_code', 'HS Code is required for export products');
                }

                if (!$('#id_efris_customs_measure_unit').val()) {
                    this.validator.addError('#id_efris_customs_measure_unit', 'Customs measure unit is required for export products');
                }
            }

            // Piece unit validations
            const hasPieceUnit = $('#id_efris_has_piece_unit').is(':checked');
            if (hasPieceUnit) {
                if (!$('#id_efris_piece_measure_unit').val()) {
                    this.validator.addError('#id_efris_piece_measure_unit', 'Piece measure unit is required');
                }

                const piecePrice = parseFloat($('#id_efris_piece_unit_price').val());
                if (!piecePrice || piecePrice <= 0) {
                    this.validator.addError('#id_efris_piece_unit_price', 'Piece unit price must be greater than 0');
                }
            }

            if (!this.validator.isValid()) {
                e.preventDefault();
                this.validator.showErrors();
                return false;
            }
        });
    }
}

// Initialize product form
function initializeProductForm() {
    if ($('#productForm').length) {
        new ProductFormHandler();
    }
}

export { initializeProductForm };