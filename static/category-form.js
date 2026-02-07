/**
 * Category form with EFRIS integration
 */

import { FormValidator, debounce, showSuccessMessage, showErrorMessage, getCookie } from './form-base.js';

class EFRISCategorySelector {
    constructor() {
        this.selectedCategory = null;
        this.currentResults = [];
        this.categoryTree = [];
        this.recentCategories = JSON.parse(localStorage.getItem('efris_recent_categories') || '[]');
        this.init();
    }

    init() {
        this.initializeEventListeners();
        this.loadCategoryTree();
        this.populateQuickAccess();
        this.populateAZScroller();
        this.preSelectExistingCategory();
    }

    initializeEventListeners() {
        $('#efrisSearchInput').on('input', debounce(() => {
            this.handleSearch();
        }, 300));

        $('#efrisSearchInput').on('keypress', (e) => {
            if (e.which === 13) {
                e.preventDefault();
                this.handleSearch();
            }
        });
    }

    async loadCategoryTree() {
        $('#treeLoading').addClass('show');

        try {
            const response = await $.ajax({
                url: `/${window.LANGUAGE_PREFIX}/inventory/efris/category-tree/`,
                method: 'GET',
                data: {
                    type: $('#id_category_type').val() || 'product'
                }
            });

            if (response.success) {
                this.categoryTree = response.tree || [];
                this.renderCategoryTree();
            } else {
                throw new Error(response.error || 'Failed to load categories');
            }
        } catch (error) {
            console.error('Failed to load category tree:', error);
            $('#categoryTree').html(`
                <div class="efris-empty">
                    <i class="fas fa-exclamation-triangle"></i>
                    <div>Failed to load categories</div>
                </div>
            `);
        } finally {
            $('#treeLoading').removeClass('show');
        }
    }

    renderCategoryTree() {
        const treeContainer = $('#categoryTree');
        treeContainer.empty();

        if (this.categoryTree.length === 0) {
            treeContainer.html(`
                <div class="efris-empty">
                    <i class="fas fa-folder-open"></i>
                    <div>No categories found</div>
                </div>
            `);
            return;
        }

        this.categoryTree.forEach(node => {
            treeContainer.append(this.renderNode(node));
        });
    }

    renderNode(node, level = 0) {
        const hasChildren = node.has_children || (node.children && node.children.length > 0);
        const isLeaf = node.is_leaf || false;

        const nodeElement = $(`
            <div class="tree-node">
                <div class="tree-node-content" 
                     data-node-id="${node.id}" 
                     data-has-children="${hasChildren}" 
                     data-is-leaf="${isLeaf}"
                     role="button"
                     tabindex="0"
                     aria-expanded="false">
                    <div class="tree-node-icon">
                        <i class="fas fa-${hasChildren ? 'folder' : (isLeaf ? 'file' : 'folder')}" 
                           aria-hidden="true"></i>
                    </div>
                    <div class="tree-node-text">${node.name}</div>
                </div>
                ${hasChildren ? `<div class="tree-node-children" id="children-${node.id}" style="display:none;" role="group"></div>` : ''}
            </div>
        `);

        nodeElement.find('.tree-node-content').on('click', (e) => {
            e.stopPropagation();
            this.handleNodeClick(node, nodeElement, isLeaf, hasChildren);
        });

        // Keyboard navigation
        nodeElement.find('.tree-node-content').on('keypress', (e) => {
            if (e.which === 13 || e.which === 32) {
                e.preventDefault();
                this.handleNodeClick(node, nodeElement, isLeaf, hasChildren);
            }
        });

        return nodeElement;
    }

    handleNodeClick(node, nodeElement, isLeaf, hasChildren) {
        if (isLeaf) {
            this.loadCategoryResults(node.id, node.name);
        } else if (hasChildren) {
            this.toggleNode(node, nodeElement);
        } else {
            this.loadCategoryResults(node.id, node.name);
        }
    }

    async toggleNode(node, nodeElement) {
        const childrenContainer = nodeElement.find('.tree-node-children').first();
        const icon = nodeElement.find('.tree-node-content .tree-node-icon i').first();
        const nodeContent = nodeElement.find('.tree-node-content').first();

        if (childrenContainer.length === 0) return;

        const isExpanded = nodeContent.attr('aria-expanded') === 'true';

        if (childrenContainer.children().length === 0) {
            // Load children
            icon.removeClass('fa-folder').addClass('fa-spinner fa-spin');

            try {
                await this.loadNodeChildren(node.id, childrenContainer);
                icon.removeClass('fa-spinner fa-spin').addClass('fa-folder-open');
                childrenContainer.slideDown(200);
                nodeContent.attr('aria-expanded', 'true');
            } catch (error) {
                icon.removeClass('fa-spinner fa-spin').addClass('fa-folder');
                showErrorMessage('Failed to load subcategories');
            }
        } else {
            // Toggle visibility
            if (isExpanded) {
                childrenContainer.slideUp(200);
                icon.removeClass('fa-folder-open').addClass('fa-folder');
                nodeContent.attr('aria-expanded', 'false');
            } else {
                childrenContainer.slideDown(200);
                icon.removeClass('fa-folder').addClass('fa-folder-open');
                nodeContent.attr('aria-expanded', 'true');
            }
        }
    }

    async loadNodeChildren(nodeId, container) {
        const response = await $.ajax({
            url: '/${window.LANGUAGE_PREFIX}/inventory/efris/category-children/',
            method: 'GET',
            data: {
                parent_id: nodeId,
                type: $('#id_category_type').val() || 'product'
            }
        });

        if (response.children && response.children.length > 0) {
            response.children.forEach(child => {
                container.append(this.renderNode(child, 1));
            });
        }

        return response;
    }

    async handleSearch() {
        const query = $('#efrisSearchInput').val().trim();

        if (query.length < 2) {
            this.showEmptyState('Type at least 2 characters to search');
            return;
        }

        $('#resultsLoading').addClass('show');
        $('#emptyResults').hide();

        try {
            const response = await $.ajax({
                url: '/inventory/efris/search-enhanced/',
                method: 'GET',
                data: {
                    q: query,
                    type: $('#id_category_type').val() || 'product',
                    limit: 100
                }
            });

            this.currentResults = response.results || [];
            this.renderResults(`Search Results (${response.total_count || 0} found)`);
        } catch (error) {
            console.error('Search failed:', error);
            this.showEmptyState('Search failed. Please try again.');
        } finally {
            $('#resultsLoading').removeClass('show');
        }
    }

    async loadCategoryResults(categoryId, categoryName) {
        $('#resultsLoading').addClass('show');
        $('#emptyResults').hide();

        try {
            const response = await $.ajax({
                url: '/${window.LANGUAGE_PREFIX}/inventory/efris/category-results/',
                method: 'GET',
                data: {
                    category_id: categoryId,
                    type: $('#id_category_type').val() || 'product'
                }
            });

            if (response.success) {
                this.currentResults = response.results || [];
                this.renderResults(categoryName);
            } else {
                throw new Error('Failed to load results');
            }
        } catch (error) {
            console.error('Failed to load category results:', error);
            this.showEmptyState('Failed to load categories');
        } finally {
            $('#resultsLoading').removeClass('show');
        }
    }

    renderResults(title) {
        $('#resultsTitle').text(title);
        $('#resultsCount').text(`(${this.currentResults.length} items)`);

        const resultsContainer = $('#categoryResults');
        resultsContainer.empty();

        if (this.currentResults.length === 0) {
            this.showEmptyState('No categories found');
            return;
        }

        this.currentResults.forEach(category => {
            const resultItem = $(`
                <div class="category-result-item" 
                     data-category-code="${category.code}"
                     role="button"
                     tabindex="0"
                     aria-label="Select category ${category.code} - ${category.name}">
                    <div class="category-code">${category.code}</div>
                    <div class="category-name">${category.name}</div>
                    <div class="category-badges" aria-label="Category properties">
                        ${this.renderBadges(category)}
                    </div>
                </div>
            `);

            resultItem.on('click', () => {
                this.selectCategory(category);
            });

            resultItem.on('keypress', (e) => {
                if (e.which === 13 || e.which === 32) {
                    e.preventDefault();
                    this.selectCategory(category);
                }
            });

            resultsContainer.append(resultItem);
        });
    }

    renderBadges(category) {
        let badges = '';

        if (category.is_exempt) {
            badges += '<span class="badge bg-warning text-dark">Exempt</span>';
        }
        if (category.is_zero_rate) {
            badges += '<span class="badge bg-info">Zero Rate</span>';
        }
        if (category.excisable) {
            badges += '<span class="badge bg-danger">Excisable</span>';
        }
        if (!category.is_exempt && !category.is_zero_rate) {
            badges += `<span class="badge bg-success">VAT ${category.rate || '18'}%</span>`;
        }

        return badges;
    }

    selectCategory(category) {
        this.selectedCategory = category;

        // Update selected display
        $('#selectedCategoryCode').text(category.code);
        $('#selectedCategoryName').text(category.name);
        $('#selectedCategoryBadges').html(this.renderBadges(category));
        $('#selectedCategoryDisplay').addClass('show');

        // Update hidden field
        $('#efris_commodity_category_code').val(category.code);

        // Update UI
        $('.category-result-item').removeClass('selected').attr('aria-selected', 'false');
        $(`.category-result-item[data-category-code="${category.code}"]`)
            .addClass('selected')
            .attr('aria-selected', 'true');

        // Add to recent categories
        this.addToRecentCategories(category);

        // Scroll to top
        $('html, body').animate({ scrollTop: 0 }, 500);

        showSuccessMessage(`EFRIS category selected: ${category.code}`);
    }

    addToRecentCategories(category) {
        // Remove if already exists
        this.recentCategories = this.recentCategories.filter(c => c.code !== category.code);

        // Add to beginning
        this.recentCategories.unshift(category);

        // Keep only last 5
        this.recentCategories = this.recentCategories.slice(0, 5);

        // Save to localStorage
        localStorage.setItem('efris_recent_categories', JSON.stringify(this.recentCategories));

        // Update UI
        this.populateQuickAccess();
    }

    populateQuickAccess() {
        const recentContainer = $('#recentCategories');
        recentContainer.empty();

        this.recentCategories.forEach(category => {
            const item = $(`
                <div class="quick-access-item recent" 
                     data-category-code="${category.code}"
                     role="button"
                     tabindex="0"
                     aria-label="Recent: ${category.code}">
                    <i class="fas fa-history me-1" aria-hidden="true"></i>
                    ${category.code}
                </div>
            `);

            item.on('click', () => {
                this.selectCategory(category);
                $('#efrisSearchInput').val('');
            });

            item.on('keypress', (e) => {
                if (e.which === 13 || e.which === 32) {
                    e.preventDefault();
                    this.selectCategory(category);
                    $('#efrisSearchInput').val('');
                }
            });

            recentContainer.append(item);
        });

        // Load popular categories
        this.loadPopularCategories();
    }

    async loadPopularCategories() {
        try {
            const response = await $.ajax({
                url: '/inventory/efris/popular-categories/',
                method: 'GET',
                data: {
                    type: $('#id_category_type').val() || 'product',
                    limit: 5
                }
            });

            const popularContainer = $('#popularCategories');
            popularContainer.empty();

            response.results.forEach(category => {
                const item = $(`
                    <div class="quick-access-item popular" 
                         data-category-code="${category.code}"
                         role="button"
                         tabindex="0"
                         aria-label="Popular: ${category.code}">
                        <i class="fas fa-star me-1" aria-hidden="true"></i>
                        ${category.code}
                    </div>
                `);

                item.on('click', () => {
                    this.selectCategory(category);
                    $('#efrisSearchInput').val('');
                });

                item.on('keypress', (e) => {
                    if (e.which === 13 || e.which === 32) {
                        e.preventDefault();
                        this.selectCategory(category);
                        $('#efrisSearchInput').val('');
                    }
                });

                popularContainer.append(item);
            });
        } catch (error) {
            console.error('Failed to load popular categories:', error);
        }
    }

    populateAZScroller() {
        const scroller = $('.az-scroller');
        scroller.empty();

        'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('').forEach(letter => {
            const letterElement = $(`
                <div class="az-letter" 
                     data-letter="${letter}"
                     role="button"
                     tabindex="0"
                     aria-label="Jump to ${letter}">
                    ${letter}
                </div>
            `);

            letterElement.on('click', () => {
                this.jumpToLetter(letter);
            });

            letterElement.on('keypress', (e) => {
                if (e.which === 13 || e.which === 32) {
                    e.preventDefault();
                    this.jumpToLetter(letter);
                }
            });

            scroller.append(letterElement);
        });
    }

    jumpToLetter(letter) {
        const resultsContainer = $('#categoryResults');
        const targetItem = resultsContainer.find(`.category-code:contains("${letter}")`).first();

        if (targetItem.length) {
            resultsContainer.animate({
                scrollTop: targetItem.offset().top - resultsContainer.offset().top + resultsContainer.scrollTop() - 50
            }, 500);
        }
    }

    showEmptyState(message) {
        $('#categoryResults').html(`
            <div class="efris-empty" role="status">
                <i class="fas fa-inbox" aria-hidden="true"></i>
                <div>${message}</div>
            </div>
        `);
    }

    preSelectExistingCategory() {
        const existingCode = $('#efris_commodity_category_code').val();

        if (existingCode) {
            // Fetch category details and select it
            $.ajax({
                url: '/inventory/api/efris/category-by-code/',
                method: 'GET',
                data: { code: existingCode },
                success: (response) => {
                    if (response.category) {
                        this.selectCategory(response.category);
                    }
                }
            });
        }
    }

    clearSelection() {
        this.selectedCategory = null;
        $('#selectedCategoryDisplay').removeClass('show');
        $('#efris_commodity_category_code').val('');
        $('.category-result-item').removeClass('selected').attr('aria-selected', 'false');
        $('#efrisSearchInput').val('').focus();
    }
}

class CategoryFormHandler {
    constructor() {
        this.form = $('#categoryForm');
        this.validator = new FormValidator('#categoryForm');
        this.efrisSelector = null;
        this.init();
    }

    init() {
        this.initializeGenerators();
        this.initializeEFRIS();
        this.initializeValidation();
        this.loadStatistics();
    }

    initializeGenerators() {
        $('#generateCategoryCode').on('click', (e) => {
            e.preventDefault();
            this.generateCategoryCode();
        });
    }

    generateCategoryCode() {
        const categoryName = $('#id_name').val().trim();
        const categoryType = $('#id_category_type').val();

        if (!categoryName) {
            showErrorMessage('Please enter category name first');
            $('#id_name').focus();
            return;
        }

        if (!categoryType) {
            showErrorMessage('Please select category type first');
            $('#id_category_type').focus();
            return;
        }

        const typePrefix = categoryType === 'service' ? 'SVC' : 'PRD';
        const namePrefix = categoryName.substring(0, 3).toUpperCase().replace(/[^A-Z0-9]/g, '');
        const randomSuffix = Math.floor(Math.random() * 1000).toString().padStart(3, '0');

        const generatedCode = `${typePrefix}-${namePrefix}-${randomSuffix}`;

        $('#id_code').val(generatedCode).removeClass('is-invalid');
        showSuccessMessage('Category code generated successfully');
    }

    initializeEFRIS() {
        if ($('#efrisSearchInput').length) {
            this.efrisSelector = new EFRISCategorySelector();

            // Handle category type changes
            $('#id_category_type').on('change', () => {
                if (this.efrisSelector) {
                    this.efrisSelector.clearSelection();
                    this.efrisSelector.loadCategoryTree();
                    this.efrisSelector.populateQuickAccess();
                }
            });
        }
    }

    initializeValidation() {
        $('#validateCategoryBtn').on('click', (e) => {
            e.preventDefault();
            this.validateForm(true);
        });

        this.form.on('submit', (e) => {
            if (!this.validateForm(false)) {
                e.preventDefault();
                return false;
            }
        });
    }

    validateForm(showSuccess) {
        this.validator.clearErrors();

        // Category type validation
        if (!$('#id_category_type').val()) {
            this.validator.addError('#id_category_type', 'Category type is required');
        }

        // Name validation
        if (!$('#id_name').val().trim()) {
            this.validator.addError('#id_name', 'Category name is required');
        }

        // EFRIS category validation
        if ($('#efris_commodity_category_code').length && !$('#efris_commodity_category_code').val()) {
            this.validator.errors.push({
                field: '#efris_commodity_category_code',
                message: 'EFRIS commodity category is required'
            });
            $('#selectedCategoryDisplay').addClass('border-danger');
        }

        // Auto-sync validation
        if ($('#id_efris_auto_sync').is(':checked') && !$('#efris_commodity_category_code').val()) {
            this.validator.errors.push({
                field: '#id_efris_auto_sync',
                message: 'EFRIS commodity category is required when auto-sync is enabled'
            });
        }

        if (!this.validator.isValid()) {
            this.validator.showErrors();
            return false;
        }

        if (showSuccess) {
            showSuccessMessage('Validation passed! Category is ready to be saved.');
        }

        return true;
    }

    async loadStatistics() {
        try {
            const response = await $.ajax({
                url: '/inventory/api/efris-categories/stats/',
                method: 'GET'
            });

            $('#stat-products').text(response.usable_products.toLocaleString());
            $('#stat-services').text(response.usable_services.toLocaleString());
            $('#stat-exempt').text(response.exempt_categories.toLocaleString());
            $('#stat-zero').text(response.zero_rate_categories.toLocaleString());
        } catch (error) {
            console.error('Failed to load EFRIS statistics:', error);
            $('#efris-stats-container').html('<p class="text-muted">Statistics unavailable</p>');
        }
    }
}

// Global function for clearing selection (called from template)
window.clearEFRISSelection = function() {
    if (window.categoryFormHandler && window.categoryFormHandler.efrisSelector) {
        window.categoryFormHandler.efrisSelector.clearSelection();
    }
};

// Initialize category form
function initializeCategoryForm() {
    if ($('#categoryForm').length) {
        window.categoryFormHandler = new CategoryFormHandler();
    }
}

export { initializeCategoryForm };