/**
 * IndexedDB Manager with Multi-Tenant Isolation
 * Handles database operations for offline POS system
 */

class DBManager {
  constructor() {
    this.db = null;
    this.dbName = null;
    this.dbVersion = 1;
    this.tenantId = this.extractTenantFromSubdomain();
  }

  /**
   * Extract tenant ID from subdomain
   * e.g., tenant123.yourdomain.com -> tenant123
   */
  extractTenantFromSubdomain() {
    const hostname = window.location.hostname;
    const parts = hostname.split('.');

    // For localhost testing, use a default tenant
    if (hostname === 'localhost' || hostname === '127.0.0.1') {
      return 'localhost_tenant';
    }

    // Extract subdomain as tenant ID
    return parts[0];
  }

  /**
   * Initialize database for current tenant
   */
  async init() {
    if (!this.tenantId) {
      throw new Error('Tenant ID could not be determined');
    }

    this.dbName = `pos_${this.tenantId}`;

    return new Promise((resolve, reject) => {
      const request = indexedDB.open(this.dbName, this.dbVersion);

      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        this.db = request.result;
        resolve(this.db);
      };

      request.onupgradeneeded = (event) => {
        const db = event.target.result;

        // INVENTORY APP STORES
        if (!db.objectStoreNames.contains('products')) {
          const products = db.createObjectStore('products', { keyPath: 'id' });
          products.createIndex('category_id', 'category_id', { unique: false });
          products.createIndex('sku', 'sku', { unique: true });
          products.createIndex('updated_at', 'updated_at', { unique: false });
          products.createIndex('sync_status', 'sync_status', { unique: false });
        }

        if (!db.objectStoreNames.contains('categories')) {
          const categories = db.createObjectStore('categories', { keyPath: 'id' });
          categories.createIndex('name', 'name', { unique: false });
          categories.createIndex('updated_at', 'updated_at', { unique: false });
        }

        if (!db.objectStoreNames.contains('stock')) {
          const stock = db.createObjectStore('stock', { keyPath: 'id' });
          stock.createIndex('product_id', 'product_id', { unique: false });
          stock.createIndex('store_id', 'store_id', { unique: false });
          stock.createIndex('updated_at', 'updated_at', { unique: false });
        }

        if (!db.objectStoreNames.contains('services')) {
          const services = db.createObjectStore('services', { keyPath: 'id' });
          services.createIndex('name', 'name', { unique: false });
          services.createIndex('updated_at', 'updated_at', { unique: false });
        }

        if (!db.objectStoreNames.contains('stock_movements')) {
          const movements = db.createObjectStore('stock_movements', { keyPath: 'id' });
          movements.createIndex('product_id', 'product_id', { unique: false });
          movements.createIndex('created_at', 'created_at', { unique: false });
          movements.createIndex('sync_status', 'sync_status', { unique: false });
        }

        // SALES APP STORES
        if (!db.objectStoreNames.contains('sales')) {
          const sales = db.createObjectStore('sales', { keyPath: 'id' });
          sales.createIndex('created_at', 'created_at', { unique: false });
          sales.createIndex('customer_id', 'customer_id', { unique: false });
          sales.createIndex('store_id', 'store_id', { unique: false });
          sales.createIndex('sync_status', 'sync_status', { unique: false });
          sales.createIndex('created_by_id', 'created_by_id', { unique: false });
          sales.createIndex('document_number', 'document_number', { unique: false });
          sales.createIndex('document_type', 'document_type', { unique: false });
          sales.createIndex('payment_status', 'payment_status', { unique: false });
          sales.createIndex('status', 'status', { unique: false });
        }

        // CUSTOMERS & STORES
        if (!db.objectStoreNames.contains('customers')) {
          const customers = db.createObjectStore('customers', { keyPath: 'id' });
          customers.createIndex('email', 'email', { unique: false });
          customers.createIndex('phone', 'phone', { unique: false });
          customers.createIndex('updated_at', 'updated_at', { unique: false });
        }

        if (!db.objectStoreNames.contains('stores')) {
          const stores = db.createObjectStore('stores', { keyPath: 'id' });
          stores.createIndex('name', 'name', { unique: false });
        }

        // SYNC & CONFLICT MANAGEMENT
        if (!db.objectStoreNames.contains('sync_queue')) {
          const queue = db.createObjectStore('sync_queue', { keyPath: 'id', autoIncrement: true });
          queue.createIndex('entity_type', 'entity_type', { unique: false });
          queue.createIndex('priority', 'priority', { unique: false });
          queue.createIndex('created_at', 'created_at', { unique: false });
          queue.createIndex('status', 'status', { unique: false });
        }

        if (!db.objectStoreNames.contains('conflict_log')) {
          const conflicts = db.createObjectStore('conflict_log', { keyPath: 'id', autoIncrement: true });
          conflicts.createIndex('entity_type', 'entity_type', { unique: false });
          conflicts.createIndex('entity_id', 'entity_id', { unique: false });
          conflicts.createIndex('resolved', 'resolved', { unique: false });
          conflicts.createIndex('created_at', 'created_at', { unique: false });
        }

        // AUTHENTICATION CACHE
        if (!db.objectStoreNames.contains('auth_cache')) {
          const auth = db.createObjectStore('auth_cache', { keyPath: 'key' });
          auth.createIndex('expires_at', 'expires_at', { unique: false });
        }

        // METADATA
        if (!db.objectStoreNames.contains('metadata')) {
          db.createObjectStore('metadata', { keyPath: 'key' });
        }
      };
    });
  }

  /**
   * Generic add/update operation with version tracking
   */
  async put(storeName, data, userId = null) {
    if (!this.db) await this.init();

    const timestamp = new Date().toISOString();
    const enrichedData = {
      ...data,
      updated_at: timestamp,
      updated_by: userId,
      version: (data.version || 0) + 1,
      sync_status: data.sync_status || 'pending'
    };

    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction([storeName], 'readwrite');
      const store = transaction.objectStore(storeName);
      const request = store.put(enrichedData);

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Get single record by ID
   */
  async get(storeName, id) {
    if (!this.db) await this.init();

    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction([storeName], 'readonly');
      const store = transaction.objectStore(storeName);
      const request = store.get(id);

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Get all records from a store
   */
  async getAll(storeName, indexName = null, query = null) {
    if (!this.db) await this.init();

    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction([storeName], 'readonly');
      const store = transaction.objectStore(storeName);

      let request;
      if (indexName && query) {
        const index = store.index(indexName);
        request = index.getAll(query);
      } else {
        request = store.getAll();
      }

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Delete record
   */
  async delete(storeName, id) {
    if (!this.db) await this.init();

    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction([storeName], 'readwrite');
      const store = transaction.objectStore(storeName);
      const request = store.delete(id);

      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Clear all data from a store
   */
  async clear(storeName) {
    if (!this.db) await this.init();

    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction([storeName], 'readwrite');
      const store = transaction.objectStore(storeName);
      const request = store.clear();

      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Count records in a store
   */
  async count(storeName, indexName = null, query = null) {
    if (!this.db) await this.init();

    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction([storeName], 'readonly');
      const store = transaction.objectStore(storeName);

      let request;
      if (indexName && query) {
        const index = store.index(indexName);
        request = index.count(query);
      } else {
        request = store.count();
      }

      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Bulk operation for better performance
   */
  async bulkPut(storeName, dataArray, userId = null) {
    if (!this.db) await this.init();

    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction([storeName], 'readwrite');
      const store = transaction.objectStore(storeName);
      const timestamp = new Date().toISOString();

      let completed = 0;
      const errors = [];

      dataArray.forEach((data, index) => {
        const enrichedData = {
          ...data,
          updated_at: timestamp,
          updated_by: userId,
          version: (data.version || 0) + 1,
          sync_status: data.sync_status || 'synced'
        };

        const request = store.put(enrichedData);

        request.onsuccess = () => {
          completed++;
          if (completed === dataArray.length) {
            if (errors.length > 0) {
              reject({ completed, errors });
            } else {
              resolve(completed);
            }
          }
        };

        request.onerror = () => {
          errors.push({ index, error: request.error });
          completed++;
          if (completed === dataArray.length) {
            reject({ completed: completed - errors.length, errors });
          }
        };
      });
    });
  }

  /**
   * Clean old sales (keep only last 60 days)
   */
  async cleanOldSales() {
    if (!this.db) await this.init();

    const sixtyDaysAgo = new Date();
    sixtyDaysAgo.setDate(sixtyDaysAgo.getDate() - 60);
    const cutoffDate = sixtyDaysAgo.toISOString();

    return new Promise((resolve, reject) => {
      const transaction = this.db.transaction(['sales'], 'readwrite');
      const store = transaction.objectStore(storeName);
      const index = store.index('created_at');
      const range = IDBKeyRange.upperBound(cutoffDate);
      const request = index.openCursor(range);

      let deleted = 0;

      request.onsuccess = (event) => {
        const cursor = event.target.result;
        if (cursor) {
          // Only delete if synced
          if (cursor.value.sync_status === 'synced') {
            cursor.delete();
            deleted++;
          }
          cursor.continue();
        } else {
          resolve(deleted);
        }
      };

      request.onerror = () => reject(request.error);
    });
  }

  /**
   * Get database info and storage estimate
   */
  async getStorageInfo() {
    if (navigator.storage && navigator.storage.estimate) {
      const estimate = await navigator.storage.estimate();
      const usage = estimate.usage;
      const quota = estimate.quota;
      const percentUsed = (usage / quota) * 100;

      return {
        usage: this.formatBytes(usage),
        quota: this.formatBytes(quota),
        percentUsed: percentUsed.toFixed(2),
        available: this.formatBytes(quota - usage),
        tenantId: this.tenantId,
        dbName: this.dbName
      };
    }
    return null;
  }

  formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
  }

  /**
   * Close database connection
   */
  close() {
    if (this.db) {
      this.db.close();
      this.db = null;
    }
  }

  /**
   * Delete entire database (for logout/cleanup)
   */
  async deleteDatabase() {
    this.close();
    return new Promise((resolve, reject) => {
      const request = indexedDB.deleteDatabase(this.dbName);
      request.onsuccess = () => resolve();
      request.onerror = () => reject(request.error);
    });
  }
}

// Export singleton instance
const dbManager = new DBManager();
export default dbManager;