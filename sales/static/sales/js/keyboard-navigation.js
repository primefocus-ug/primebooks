// ============================================
// KEYBOARD NAVIGATION MODULE
// ============================================

class KeyboardNavigation {
    constructor() {
        this.enabled = true;
        this.mode = 'normal'; // normal, products, customers, cart, modal, form
        this.selectedIndex = -1;
        this.formFieldIndex = -1;
        this.currentModal = null;
        this.history = [];

        // All interactive elements
        this.focusableSelectors = [
            'button:not([disabled])',
            'a[href]',
            'input:not([disabled])',
            'select:not([disabled])',
            'textarea:not([disabled])',
            '[tabindex]:not([tabindex="-1"])',
            '.product-card:not(.out-of-stock)',
            '.customer-list-item',
            '.cart-item',
            '.draft-item'
        ];

        this.shortcuts = this.initializeShortcuts();
    }

    initializeShortcuts() {
        return {
            // === MAIN NAVIGATION (F-Keys) ===
            'F1': { action: 'focusProductSearch', description: 'Product Search', category: 'Navigation' },
            'F2': { action: 'focusCustomerSearch', description: 'Customer Search', category: 'Navigation' },
            'F3': { action: 'completeSale', description: 'Complete Sale', category: 'Actions' },
            'F4': { action: 'toggleDocumentType', description: 'Toggle Receipt/Invoice', category: 'Settings' },
            'F5': { action: 'toggleItemType', description: 'Toggle All/Products/Services', category: 'Filters' },
            'F6': { action: 'cyclePaymentMethod', description: 'Cycle Payment Method', category: 'Settings' },
            'F7': { action: 'openDiscountDialog', description: 'Apply Discount', category: 'Actions' },
            'F8': { action: 'saveAsDraft', description: 'Save Draft', category: 'Actions' },
            'F9': { action: 'openDraftsModal', description: 'View Drafts', category: 'Actions' },
            'F10': { action: 'printPreview', description: 'Print Preview', category: 'Actions' },
            'F11': { action: 'openNewCustomerModal', description: 'New Customer', category: 'Actions' },
            'F12': { action: 'clearCart', description: 'Clear Cart', category: 'Actions' },

            // === CONTROL SHORTCUTS ===
            'Ctrl+S': { action: 'saveAsDraft', description: 'Save Draft', category: 'Quick Actions' },
            'Ctrl+P': { action: 'printPreview', description: 'Print', category: 'Quick Actions' },
            'Ctrl+N': { action: 'openNewCustomerModal', description: 'New Customer', category: 'Quick Actions' },
            'Ctrl+D': { action: 'openDiscountDialog', description: 'Discount', category: 'Quick Actions' },
            'Ctrl+K': { action: 'clearCart', description: 'Clear Cart', category: 'Quick Actions' },
            'Ctrl+Enter': { action: 'completeSale', description: 'Complete Sale', category: 'Quick Actions' },
            'Ctrl+F': { action: 'focusProductSearch', description: 'Find Products', category: 'Quick Actions' },
            'Ctrl+C': { action: 'focusCustomerSearch', description: 'Find Customer', category: 'Quick Actions' },
            'Ctrl+B': { action: 'focusStoreSelect', description: 'Change Branch', category: 'Quick Actions' },

            // === NAVIGATION KEYS ===
            'ArrowUp': { action: 'navigateUp', description: 'Move Up', category: 'Navigation' },
            'ArrowDown': { action: 'navigateDown', description: 'Move Down', category: 'Navigation' },
            'ArrowLeft': { action: 'navigateLeft', description: 'Move Left / Previous Page', category: 'Navigation' },
            'ArrowRight': { action: 'navigateRight', description: 'Move Right / Next Page', category: 'Navigation' },
            'Home': { action: 'navigateHome', description: 'First Item', category: 'Navigation' },
            'End': { action: 'navigateEnd', description: 'Last Item', category: 'Navigation' },

            // === ACTION KEYS ===
            'Enter': { action: 'selectConfirm', description: 'Select / Confirm', category: 'Actions' },
            'Space': { action: 'selectConfirm', description: 'Select / Add to Cart', category: 'Actions' },
            'Escape': { action: 'cancel', description: 'Cancel / Close / Back', category: 'Actions' },
            'Delete': { action: 'removeItem', description: 'Remove Item', category: 'Actions' },

            // === QUANTITY ADJUSTMENT ===
            '+': { action: 'increaseQuantity', description: 'Increase Quantity', category: 'Cart' },
            '=': { action: 'increaseQuantity', description: 'Increase Quantity', category: 'Cart' },
            '-': { action: 'decreaseQuantity', description: 'Decrease Quantity', category: 'Cart' },

            // === QUICK SELECT (Number Keys) ===
            '1': { action: 'quickSelect', description: 'Quick Select Item 1', category: 'Quick Select' },
            '2': { action: 'quickSelect', description: 'Quick Select Item 2', category: 'Quick Select' },
            '3': { action: 'quickSelect', description: 'Quick Select Item 3', category: 'Quick Select' },
            '4': { action: 'quickSelect', description: 'Quick Select Item 4', category: 'Quick Select' },
            '5': { action: 'quickSelect', description: 'Quick Select Item 5', category: 'Quick Select' },
            '6': { action: 'quickSelect', description: 'Quick Select Item 6', category: 'Quick Select' },
            '7': { action: 'quickSelect', description: 'Quick Select Item 7', category: 'Quick Select' },
            '8': { action: 'quickSelect', description: 'Quick Select Item 8', category: 'Quick Select' },
            '9': { action: 'quickSelect', description: 'Quick Select Item 9', category: 'Quick Select' },

            // === SPECIAL KEYS ===
            '?': { action: 'toggleHelp', description: 'Show/Hide Help', category: 'Help' },
            'c': { action: 'switchToCart', description: 'Focus Cart', category: 'Navigation' },
            'p': { action: 'switchToProducts', description: 'Focus Products', category: 'Navigation' },
            'u': { action: 'switchToCustomer', description: 'Focus Customer', category: 'Navigation' }
        };
    }

    init() {
        console.log('⌨️ Initializing Keyboard Navigation...');
        this.attachGlobalListeners();
        this.setupVisualIndicators();
        this.updateHelpPanel();
        this.enableAccessibilityFeatures();
        console.log('✅ Keyboard Navigation Ready - Press ? for help');
    }

    attachGlobalListeners() {
        document.addEventListener('keydown', (e) => {
            if (!this.enabled) return;

            if (this.isTypingInField(e.target)) {
                if (e.key === 'Escape' || e.key === 'Enter' ||
                    (e.ctrlKey && ['s', 'p', 'n'].includes(e.key.toLowerCase()))) {
                    this.handleShortcut(e);
                }
                return;
            }

            this.handleShortcut(e);
        });

        document.addEventListener('focusin', (e) => {
            this.updateCurrentContext(e.target);
        });

        document.addEventListener('keydown', (e) => {
            if (e.ctrlKey && ['s', 'p', 'f'].includes(e.key.toLowerCase())) {
                e.preventDefault();
            }
        });
    }

    handleShortcut(e) {
        const shortcutKey = this.getShortcutKey(e);
        const shortcut = this.shortcuts[shortcutKey];

        if (shortcut) {
            e.preventDefault();
            e.stopPropagation();
            console.log('🎯 Executing:', shortcut.action);
            this.executeAction(shortcut.action, e);
            return true;
        }

        return false;
    }

    getShortcutKey(e) {
        const parts = [];
        if (e.ctrlKey) parts.push('Ctrl');
        if (e.shiftKey) parts.push('Shift');
        if (e.altKey) parts.push('Alt');

        const key = e.key;
        const specialKeys = [
            'F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12',
            'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight',
            'Enter', 'Escape', 'Tab', 'Delete', 'Backspace', 'Space',
            'Home', 'End', 'PageUp', 'PageDown'
        ];

        if (specialKeys.includes(key)) {
            parts.push(key);
            return parts.join('+');
        }

        parts.push(key);
        return parts.join('+');
    }

    isTypingInField(element) {
        return element.tagName === 'INPUT' ||
               element.tagName === 'TEXTAREA' ||
               element.tagName === 'SELECT' ||
               element.isContentEditable;
    }

    updateCurrentContext(element) {
        if (element.closest('.products-grid-container')) {
            this.mode = 'products';
        } else if (element.closest('.customer-section')) {
            this.mode = 'customers';
        } else if (element.closest('.cart-section')) {
            this.mode = 'cart';
        } else if (element.closest('.modal.show')) {
            this.mode = 'modal';
            this.currentModal = element.closest('.modal.show');
        } else if (element.tagName === 'INPUT' || element.tagName === 'SELECT' || element.tagName === 'TEXTAREA') {
            this.mode = 'form';
        } else {
            this.mode = 'normal';
        }

        this.updateModeIndicator();
    }

    executeAction(action, event) {
        const actionMap = {
            focusProductSearch: () => this.focusProductSearch(),
            focusCustomerSearch: () => this.focusCustomerSearch(),
            completeSale: () => window.completeSale?.(),
            saveAsDraft: () => window.saveAsDraft?.(),
            printPreview: () => window.printReceiptPreview?.(),
            clearCart: () => window.clearCart?.(),
            openNewCustomerModal: () => window.showNewCustomerModal?.(),
            openDraftsModal: () => window.showDraftsModal?.(),
            openDiscountDialog: () => this.openDiscountDialog(),
            toggleDocumentType: () => this.toggleDocumentType(),
            navigateUp: () => this.navigate(-1, 'vertical'),
            navigateDown: () => this.navigate(1, 'vertical'),
            navigateLeft: () => this.navigate(-1, 'horizontal'),
            navigateRight: () => this.navigate(1, 'horizontal'),
            navigateHome: () => this.navigateToEdge('first'),
            navigateEnd: () => this.navigateToEdge('last'),
            selectConfirm: () => this.selectConfirm(),
            quickSelect: () => this.quickSelect(event.key),
            increaseQuantity: () => this.adjustQuantity(1),
            decreaseQuantity: () => this.adjustQuantity(-1),
            removeItem: () => this.removeSelectedItem(),
            switchToCart: () => this.switchToSection('cart'),
            switchToProducts: () => this.switchToSection('products'),
            switchToCustomer: () => this.switchToSection('customer'),
            cancel: () => this.handleCancel(),
            toggleHelp: () => this.toggleHelp()
        };

        const handler = actionMap[action];
        if (handler) {
            try {
                handler();
            } catch (error) {
                console.error('Error executing action:', action, error);
            }
        }
    }

    focusProductSearch() {
        const searchBar = document.getElementById('productSearchBar');
        if (searchBar) {
            searchBar.focus();
            searchBar.select();
            this.mode = 'products';
            this.selectedIndex = -1;
        }
    }

    focusCustomerSearch() {
        const searchTabBtn = document.getElementById('searchTabBtn');
        if (searchTabBtn) {
            const tab = new bootstrap.Tab(searchTabBtn);
            tab.show();
        }

        setTimeout(() => {
            const customerSearch = document.getElementById('customerSearch');
            if (customerSearch) {
                customerSearch.focus();
                customerSearch.select();
                this.mode = 'customers';
                this.selectedIndex = -1;
            }
        }, 100);
    }

    navigate(direction, orientation) {
        if (this.mode === 'products') {
            this.navigateProducts(direction, orientation);
        } else if (this.mode === 'customers') {
            this.navigateCustomers(direction);
        } else if (this.mode === 'cart') {
            this.navigateCart(direction);
        }
    }

    navigateProducts(direction, orientation) {
        const products = document.querySelectorAll('.product-card:not(.out-of-stock)');
        if (products.length === 0) return;

        products.forEach(p => p.classList.remove('keyboard-selected'));

        if (orientation === 'horizontal') {
            const grid = document.querySelector('.products-grid-container');
            const gridWidth = grid ? grid.offsetWidth : 0;
            const cardWidth = products[0] ? products[0].offsetWidth : 200;
            const columns = Math.floor(gridWidth / cardWidth) || 5;

            if (this.selectedIndex < 0) this.selectedIndex = 0;
            this.selectedIndex += direction * columns;
        } else {
            this.selectedIndex += direction;
        }

        if (this.selectedIndex < 0) this.selectedIndex = products.length - 1;
        if (this.selectedIndex >= products.length) this.selectedIndex = 0;

        const selected = products[this.selectedIndex];
        if (selected) {
            selected.classList.add('keyboard-selected');
            selected.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    navigateCustomers(direction) {
        const customers = document.querySelectorAll('.customer-list-item');
        if (customers.length === 0) return;

        customers.forEach(c => c.classList.remove('keyboard-selected'));

        this.selectedIndex += direction;
        if (this.selectedIndex < 0) this.selectedIndex = customers.length - 1;
        if (this.selectedIndex >= customers.length) this.selectedIndex = 0;

        const selected = customers[this.selectedIndex];
        if (selected) {
            selected.classList.add('keyboard-selected');
            selected.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }

    navigateCart(direction) {
        const items = document.querySelectorAll('.cart-item');
        if (items.length === 0) return;

        items.forEach(i => i.classList.remove('keyboard-selected'));

        this.selectedIndex += direction;
        if (this.selectedIndex < 0) this.selectedIndex = items.length - 1;
        if (this.selectedIndex >= items.length) this.selectedIndex = 0;

        const selected = items[this.selectedIndex];
        if (selected) {
            selected.classList.add('keyboard-selected');
            selected.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    }

    setupVisualIndicators() {
        this.addShortcutBadges();
        this.createModeIndicator();
    }

    addShortcutBadges() {
        const observer = new MutationObserver(() => {
            const products = document.querySelectorAll('.product-card:not(.out-of-stock)');
            products.forEach((product, index) => {
                if (index < 9 && !product.querySelector('.shortcut-badge')) {
                    const badge = document.createElement('span');
                    badge.className = 'shortcut-badge';
                    badge.textContent = index + 1;
                    product.style.position = 'relative';
                    product.insertBefore(badge, product.firstChild);
                }
            });
        });

        const productsGrid = document.getElementById('productsGrid');
        if (productsGrid) {
            observer.observe(productsGrid, { childList: true, subtree: true });
        }
    }

    createModeIndicator() {
        if (document.getElementById('keyboardModeIndicator')) return;

        const indicator = document.createElement('div');
        indicator.id = 'keyboardModeIndicator';
        indicator.innerHTML = `
            <div style="display: flex; align-items: center; gap: 8px;">
                <i class="bi bi-keyboard"></i>
                <span id="keyboardModeText">NORMAL</span>
            </div>
        `;
        document.body.appendChild(indicator);
    }

    updateModeIndicator() {
        const text = document.getElementById('keyboardModeText');
        if (text) {
            text.textContent = this.mode.toUpperCase();
        }
    }

    updateHelpPanel() {
        // Group shortcuts by category
        const grouped = {};
        Object.entries(this.shortcuts).forEach(([key, shortcut]) => {
            const category = shortcut.category || 'Other';
            if (!grouped[category]) grouped[category] = [];
            grouped[category].push({ key, ...shortcut });
        });

        let html = '<h6><i class="bi bi-keyboard me-2"></i>Keyboard Shortcuts</h6><ul class="list-unstyled">';

        Object.entries(grouped).forEach(([category, shortcuts]) => {
            html += `<li><strong>${category}</strong><ul>`;
            shortcuts.forEach(shortcut => {
                html += `<li><kbd>${shortcut.key}</kbd> - ${shortcut.description}</li>`;
            });
            html += '</ul></li>';
        });

        html += '</ul>';

        const helpPanel = document.getElementById('shortcutsHelp');
        if (helpPanel) {
            helpPanel.innerHTML = html;
        }
    }

    toggleHelp() {
        const help = document.getElementById('shortcutsHelp');
        if (help) {
            help.classList.toggle('show');
        }
    }

    enableAccessibilityFeatures() {
        if (!document.getElementById('ariaLiveRegion')) {
            const liveRegion = document.createElement('div');
            liveRegion.id = 'ariaLiveRegion';
            liveRegion.setAttribute('role', 'status');
            liveRegion.setAttribute('aria-live', 'polite');
            liveRegion.setAttribute('aria-atomic', 'true');
            liveRegion.style.position = 'absolute';
            liveRegion.style.left = '-10000px';
            liveRegion.style.width = '1px';
            liveRegion.style.height = '1px';
            liveRegion.style.overflow = 'hidden';
            document.body.appendChild(liveRegion);
        }
    }

    announce(message) {
        const liveRegion = document.getElementById('ariaLiveRegion');
        if (liveRegion) {
            liveRegion.textContent = message;
        }
    }

    // Additional helper methods
    selectConfirm() {
        if (this.mode === 'products' && this.selectedIndex >= 0) {
            const products = document.querySelectorAll('.product-card:not(.out-of-stock)');
            const selected = products[this.selectedIndex];
            if (selected) {
                const btn = selected.querySelector('.btn-add-to-cart');
                if (btn && !btn.disabled) btn.click();
            }
        } else if (this.mode === 'customers' && this.selectedIndex >= 0) {
            const customers = document.querySelectorAll('.customer-list-item');
            const selected = customers[this.selectedIndex];
            if (selected) selected.click();
        }
    }

    quickSelect(key) {
        const number = key === '0' ? 10 : parseInt(key);
        const index = number - 1;

        if (this.mode === 'products' || this.mode === 'normal') {
            const products = document.querySelectorAll('.product-card:not(.out-of-stock)');
            if (index >= 0 && index < products.length) {
                const btn = products[index].querySelector('.btn-add-to-cart');
                if (btn && !btn.disabled) btn.click();
            }
        }
    }

    adjustQuantity(delta) {
        if (this.mode !== 'cart') return;
        if (this.selectedIndex < 0) return;

        // Call global updateCartItemQuantity if available
        if (window.SaleState && window.SaleState.cart[this.selectedIndex]) {
            const currentQty = window.SaleState.cart[this.selectedIndex].quantity;
            window.updateCartItemQuantity?.(this.selectedIndex, currentQty + delta);
        }
    }

    removeSelectedItem() {
        if (this.mode !== 'cart') return;
        if (this.selectedIndex >= 0) {
            window.removeFromCart?.(this.selectedIndex);
        }
    }

    switchToSection(section) {
        this.selectedIndex = -1;
        document.querySelectorAll('.keyboard-selected').forEach(el => {
            el.classList.remove('keyboard-selected');
        });

        switch(section) {
            case 'products':
                this.mode = 'products';
                this.focusProductSearch();
                break;
            case 'cart':
                this.mode = 'cart';
                const cartItems = document.querySelectorAll('.cart-item');
                if (cartItems.length > 0) {
                    this.selectedIndex = 0;
                    this.navigateCart(0);
                }
                break;
            case 'customer':
                this.mode = 'customers';
                this.focusCustomerSearch();
                break;
        }
    }

    handleCancel() {
        const openModals = document.querySelectorAll('.modal.show');
        if (openModals.length > 0) {
            openModals.forEach(modal => {
                const bsModal = bootstrap.Modal.getInstance(modal);
                if (bsModal) bsModal.hide();
            });
            return;
        }

        if (document.activeElement && this.isTypingInField(document.activeElement)) {
            document.activeElement.blur();
        }
    }

    navigateToEdge(edge) {
        if (this.mode === 'products') {
            const products = document.querySelectorAll('.product-card:not(.out-of-stock)');
            if (products.length === 0) return;

            products.forEach(p => p.classList.remove('keyboard-selected'));
            this.selectedIndex = edge === 'first' ? 0 : products.length - 1;

            const selected = products[this.selectedIndex];
            selected.classList.add('keyboard-selected');
            selected.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }

    openDiscountDialog() {
        const discountSection = document.getElementById('discountSection');
        if (discountSection) {
            discountSection.style.display = 'block';
            setTimeout(() => {
                const discountValue = document.getElementById('discountValue');
                if (discountValue) {
                    discountValue.focus();
                    discountValue.select();
                }
            }, 100);
        }
    }

    toggleDocumentType() {
        const receipt = document.getElementById('docReceipt');
        const invoice = document.getElementById('docInvoice');

        if (receipt && invoice) {
            if (receipt.checked) {
                invoice.checked = true;
                invoice.dispatchEvent(new Event('change'));
            } else {
                receipt.checked = true;
                receipt.dispatchEvent(new Event('change'));
            }
        }
    }
}

// Export singleton instance
const keyboardNavigation = new KeyboardNavigation();
export default keyboardNavigation;