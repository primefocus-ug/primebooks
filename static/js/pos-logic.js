import dbManager from './db-manager.js';
import authManager from './auth-manager.js';
import syncManager from './sync-manager.js';
import djangoAPIAdapter from './django-api-adapter.js';
import offlineDetector from './offline-detector.js';

class POSLogic {
  constructor() {
    this.currentStore = null;
    this.currentUser = null;
    this.cart = [];
  }

  /**
   * Initialize POS Logic
   */
  async initialize() {
    try {
      // Get current user
      this.currentUser = await authManager.getCurrentUser();

      // Get default store
      this.currentStore = await this.getDefaultStore();

      // Load initial data
      await this.loadProducts();
      await this.loadCustomers();

      console.log('POS Logic initialized');
      return true;

    } catch (error) {
      console.error('Failed to initialize POS:', error);
      throw error;
    }
  }

  /**
   * Get default store for current user
   */
  async getDefaultStore() {
    try {
      // Try to get from metadata
      const metadata = await dbManager.get('metadata', 'default_store');
      if (metadata && metadata.value) {
        return await dbManager.get('stores', metadata.value);
      }

      // Fallback: get first available store
      const stores = await dbManager.getAll('stores');
      return stores[0];

    } catch (error) {
      console.error('Failed to get default store:', error);
      return null;
    }
  }

  /**
   * Load products from IndexedDB
   */
  async loadProducts() {
    try {
      const products = await dbManager.getAll('products');
      return products.filter(p => p.is_active);
    } catch (error) {
      console.error('Failed to load products:', error);
      return [];
    }
  }

  /**
   * Load customers
   */
  async loadCustomers() {
    try {
      return await dbManager.getAll('customers');
    } catch (error) {
      console.error('Failed to load customers:', error);
      return [];
    }
  }

  /**
   * Search products by name or SKU
   */
  async searchProducts(query) {
    try {
      const allProducts = await this.loadProducts();
      const searchTerm = query.toLowerCase();

      return allProducts.filter(product =>
        product.name.toLowerCase().includes(searchTerm) ||
        product.sku.toLowerCase().includes(searchTerm) ||
        (product.barcode && product.barcode.toLowerCase().includes(searchTerm))
      );
    } catch (error) {
      console.error('Product search failed:', error);
      return [];
    }
  }

  /**
   * Get product with stock information
   */
  async getProductWithStock(productId) {
    try {
      const product = await dbManager.get('products', productId);
      const stocks = await dbManager.getAll('stock', 'product_id', productId);
      const storeStock = stocks.find(s => s.store_id === this.currentStore.id);

      return {
        ...product,
        available_quantity: storeStock ? parseFloat(storeStock.quantity) : 0,
        is_low_stock: storeStock ? storeStock.quantity <= storeStock.low_stock_threshold : false,
      };
    } catch (error) {
      console.error('Failed to get product with stock:', error);
      return null;
    }
  }

  /**
   * Add item to cart
   */
  addToCart(item) {
    // Check if item already in cart
    const existingIndex = this.cart.findIndex(i =>
      i.product_id === item.product_id || i.service_id === item.service_id
    );

    if (existingIndex !== -1) {
      // Update quantity
      this.cart[existingIndex].quantity += item.quantity;
      this.cart[existingIndex].total_price =
        this.cart[existingIndex].quantity * this.cart[existingIndex].unit_price;
    } else {
      // Add new item
      this.cart.push({
        ...item,
        total_price: item.unit_price * item.quantity
      });
    }

    this.updateCartUI();
    return this.cart;
  }

  /**
   * Remove item from cart
   */
  removeFromCart(index) {
    this.cart.splice(index, 1);
    this.updateCartUI();
  }

  /**
   * Clear cart
   */
  clearCart() {
    this.cart = [];
    this.updateCartUI();
  }

  /**
   * Calculate cart totals
   */
  calculateCartTotals() {
    let subtotal = 0;
    let tax = 0;
    let discount = 0;

    this.cart.forEach(item => {
      subtotal += parseFloat(item.total_price);
      tax += parseFloat(item.tax_amount || 0);
      discount += parseFloat(item.discount_amount || 0);
    });

    return {
      subtotal,
      tax,
      discount,
      total: subtotal - discount
    };
  }

  /**
   * Create a sale (works offline)
   */
  async createSale(options = {}) {
    try {
      if (this.cart.length === 0) {
        throw new Error('Cart is empty');
      }

      const totals = this.calculateCartTotals();

      // Prepare sale data
      const saleData = djangoAPIAdapter.prepareForOfflineCreation('sales', {
        store_id: this.currentStore.id,
        customer_id: options.customer_id || null,
        document_type: options.document_type || 'RECEIPT',
        payment_method: options.payment_method || 'CASH',
        currency: 'UGX',

        // Amounts
        subtotal: totals.subtotal,
        tax_amount: totals.tax,
        discount_amount: totals.discount,
        total_amount: totals.total,

        // Status
        status: options.document_type === 'INVOICE' ? 'PENDING_PAYMENT' : 'COMPLETED',
        payment_status: options.document_type === 'INVOICE' ? 'PENDING' : 'PAID',
        transaction_type: 'SALE',

        // Optional
        notes: options.notes || '',
        due_date: options.due_date || null,
      }, this.currentUser.id);

      // Save sale to IndexedDB
      await dbManager.put('sales', saleData, this.currentUser.id);

      // Save sale items
      for (const item of this.cart) {
        const saleItem = {
          id: djangoAPIAdapter.generateClientId('saleitem'),
          sale_id: saleData.id,
          product_id: item.product_id || null,
          service_id: item.service_id || null,
          item_type: item.type === 'service' ? 'SERVICE' : 'PRODUCT',
          quantity: item.quantity,
          unit_price: item.unit_price,
          total_price: item.total_price,
          tax_rate: item.tax_rate || 'A',
          tax_amount: item.tax_amount || 0,
          discount: item.discount_percentage || 0,
          discount_amount: item.discount_amount || 0,
          description: item.name,
          sync_status: 'pending',
          created_at: new Date().toISOString(),
        };

        await dbManager.put('sale_items', saleItem, this.currentUser.id);
      }

      // Queue for sync (priority 1 = highest)
      await syncManager.addToQueue('sales', 'create', saleData, 1);

      // Clear cart
      this.clearCart();

      // Show success message
      this.showNotification('Sale created successfully', 'success');

      return saleData;

    } catch (error) {
      console.error('Failed to create sale:', error);
      this.showNotification('Failed to create sale: ' + error.message, 'error');
      throw error;
    }
  }

  /**
   * Create customer (works offline)
   */
  async createCustomer(customerData) {
    try {
      // Validate
      if (!customerData.name || !customerData.phone) {
        throw new Error('Name and phone are required');
      }

      if (customerData.customer_type === 'BUSINESS' && !customerData.tin) {
        throw new Error('TIN is required for business customers');
      }

      const customer = djangoAPIAdapter.prepareForOfflineCreation('customers', {
        customer_id: djangoAPIAdapter.generateClientId('customer'),
        customer_type: customerData.customer_type || 'INDIVIDUAL',
        name: customerData.name,
        store_id: this.currentStore.id,
        email: customerData.email || null,
        phone: customerData.phone,
        tin: customerData.tin || null,
        nin: customerData.nin || null,
        physical_address: customerData.physical_address || null,
        credit_limit: customerData.credit_limit || 0,
        allow_credit: customerData.allow_credit || false,
        is_active: true,
      }, this.currentUser.id);

      // Save to IndexedDB
      await dbManager.put('customers', customer, this.currentUser.id);

      // Queue for sync
      await syncManager.addToQueue('customers', 'create', customer, 6);

      this.showNotification('Customer created successfully', 'success');

      return customer;

    } catch (error) {
      console.error('Failed to create customer:', error);
      this.showNotification('Failed to create customer: ' + error.message, 'error');
      throw error;
    }
  }

  /**
   * Adjust stock (works offline)
   */
  async adjustStock(productId, quantityChange, reason) {
    try {
      // Get current stock
      const stocks = await dbManager.getAll('stock', 'product_id', productId);
      let stock = stocks.find(s => s.store_id === this.currentStore.id);

      if (!stock) {
        throw new Error('Stock record not found');
      }

      // Update quantity
      const oldQuantity = parseFloat(stock.quantity);
      stock.quantity = oldQuantity + parseFloat(quantityChange);
      stock.last_updated = new Date().toISOString();

      // Save updated stock
      await dbManager.put('stock', stock, this.currentUser.id);

      // Create stock movement
      const movement = djangoAPIAdapter.prepareForOfflineCreation('stock_movements', {
        product_id: productId,
        store_id: this.currentStore.id,
        movement_type: 'ADJUSTMENT',
        quantity: quantityChange,
        reference: `ADJ-${Date.now()}`,
        notes: reason || 'Stock adjustment',
        synced_to_efris: false,
      }, this.currentUser.id);

      await dbManager.put('stock_movements', movement, this.currentUser.id);

      // Queue for sync
      await syncManager.addToQueue('stock', 'update', stock, 3);
      await syncManager.addToQueue('stock_movements', 'create', movement, 2);

      this.showNotification(
        `Stock adjusted: ${oldQuantity} → ${stock.quantity}`,
        'success'
      );

      return { stock, movement };

    } catch (error) {
      console.error('Failed to adjust stock:', error);
      this.showNotification('Failed to adjust stock: ' + error.message, 'error');
      throw error;
    }
  }

  /**
   * Get sales report
   */
  async getSalesReport(startDate, endDate) {
    try {
      const allSales = await dbManager.getAll('sales');

      // Filter by date range and store
      const filteredSales = allSales.filter(sale => {
        const saleDate = new Date(sale.created_at);
        const inDateRange = saleDate >= new Date(startDate) &&
                           saleDate <= new Date(endDate);
        const inStore = sale.store_id === this.currentStore.id;

        return inDateRange && inStore;
      });

      // Calculate totals
      const report = {
        totalSales: filteredSales.length,
        totalRevenue: filteredSales.reduce((sum, sale) =>
          sum + parseFloat(sale.total_amount), 0
        ),
        paidSales: filteredSales.filter(s => s.payment_status === 'PAID').length,
        pendingSales: filteredSales.filter(s => s.payment_status === 'PENDING').length,
        byDocumentType: {},
      };

      report.averageSale = report.totalRevenue / report.totalSales || 0;

      // Group by document type
      filteredSales.forEach(sale => {
        if (!report.byDocumentType[sale.document_type]) {
          report.byDocumentType[sale.document_type] = { count: 0, revenue: 0 };
        }
        report.byDocumentType[sale.document_type].count++;
        report.byDocumentType[sale.document_type].revenue +=
          parseFloat(sale.total_amount);
      });

      return report;

    } catch (error) {
      console.error('Failed to generate sales report:', error);
      return null;
    }
  }

  /**
   * Get sync status
   */
  async getSyncStatus() {
    try {
      return await syncManager.getQueueStatus();
    } catch (error) {
      console.error('Failed to get sync status:', error);
      return { pending: 0, failed: 0, total: 0 };
    }
  }

  /**
   * Trigger manual sync
   */
  async triggerSync() {
    if (!navigator.onLine) {
      this.showNotification('Cannot sync while offline', 'warning');
      return false;
    }

    try {
      await syncManager.manualSync();
      this.showNotification('Sync completed successfully', 'success');
      return true;
    } catch (error) {
      this.showNotification('Sync failed: ' + error.message, 'error');
      return false;
    }
  }

  /**
   * Update cart UI
   */
  updateCartUI() {
    const event = new CustomEvent('cart-updated', {
      detail: {
        cart: this.cart,
        totals: this.calculateCartTotals()
      }
    });
    window.dispatchEvent(event);
  }

  /**
   * Show notification
   */
  showNotification(message, type = 'info') {
    const event = new CustomEvent('show-notification', {
      detail: { message, type }
    });
    window.dispatchEvent(event);
  }
}

// Create and export singleton instance
const posLogic = new POSLogic();
export default posLogic;