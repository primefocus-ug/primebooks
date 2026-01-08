/**
 * Main App Integration
 * Initialize offline system and handle UI updates
 */

import dbManager from './db-manager.js';
import authManager from './auth-manager.js';
import syncManager from './sync-manager.js';
import offlineDetector from './offline-detector.js';
import conflictResolver from './conflict-resolver.js';

class POSApp {
  constructor() {
    this.initialized = false;
  }

  /**
   * Initialize the entire offline system
   */
  async init() {
    console.log('Initializing POS Offline System...');

    try {
      // 1. Register Service Worker
      await this.registerServiceWorker();

      // 2. Initialize IndexedDB
      await dbManager.init();
      console.log('✓ IndexedDB initialized');

      // 3. Check authentication
      const isAuth = await authManager.isAuthenticated();
      if (!isAuth) {
        this.showLoginScreen();
        return;
      }

      // 4. Setup sync listeners
      this.setupSyncListeners();

      // 5. Setup offline detector listeners
      this.setupOfflineListeners();

      // 6. Check for pending syncs
      const queueStatus = await syncManager.getQueueStatus();
      if (queueStatus.pending > 0 && navigator.onLine) {
        console.log(`Found ${queueStatus.pending} items to sync`);
        syncManager.startSync();
      }

      // 7. Display storage info
      await this.displayStorageInfo();

      // 8. Setup periodic cleanup
      this.setupPeriodicCleanup();

      // 9. Setup background sync
      await this.setupBackgroundSync();

      this.initialized = true;
      console.log('✓ POS System ready (Offline-enabled)');

      // Show main app
      this.showMainApp();

    } catch (error) {
      console.error('Initialization error:', error);
      this.showError('Failed to initialize app: ' + error.message);
    }
  }

  /**
   * Register Service Worker
   */
  async registerServiceWorker() {
    if ('serviceWorker' in navigator) {
      try {
        const registration = await navigator.serviceWorker.register('/service-worker.js');
        console.log('✓ Service Worker registered:', registration.scope);

        // Listen for updates
        registration.addEventListener('updatefound', () => {
          console.log('New Service Worker version available');
        });

        // Handle messages from service worker
        navigator.serviceWorker.addEventListener('message', (event) => {
          if (event.data.type === 'BACKGROUND_SYNC') {
            syncManager.startSync();
          }
        });

        return registration;
      } catch (error) {
        console.error('Service Worker registration failed:', error);
      }
    }
  }

  /**
   * Setup background sync
   */
  async setupBackgroundSync() {
    if ('serviceWorker' in navigator && 'sync' in navigator.serviceWorker) {
      const registration = await navigator.serviceWorker.ready;

      try {
        await registration.sync.register('sync-pos-data');
        console.log('✓ Background sync registered');
      } catch (error) {
        console.warn('Background sync not available:', error);
      }
    }

    // Setup periodic sync if available
    if ('periodicSync' in navigator.serviceWorker) {
      const registration = await navigator.serviceWorker.ready;

      try {
        await registration.periodicSync.register('sync-pos-periodic', {
          minInterval: 12 * 60 * 60 * 1000 // 12 hours
        });
        console.log('✓ Periodic sync registered');
      } catch (error) {
        console.warn('Periodic sync not available:', error);
      }
    }
  }

  /**
   * Setup sync event listeners
   */
  setupSyncListeners() {
    syncManager.on((event, data) => {
      switch (event) {
        case 'sync_started':
          this.showSyncProgress(true);
          break;

        case 'sync_progress':
          this.updateSyncProgress(data);
          break;

        case 'sync_completed':
          this.showSyncProgress(false);
          this.showNotification('Sync completed',
            `${data.completed} items synced, ${data.failed} failed`);
          break;

        case 'sync_error':
          this.showSyncProgress(false);
          this.showError('Sync error: ' + data.message);
          break;
      }
    });
  }

  /**
   * Setup offline detector listeners
   */
  setupOfflineListeners() {
    offlineDetector.on((status) => {
      if (status === 'online') {
        this.showNotification('Back online', 'Syncing changes...');
      } else {
        this.showNotification('Working offline', 'Changes will sync when online', 'info');
      }
    });
  }

  /**
   * Display storage information
   */
  async displayStorageInfo() {
    const info = await dbManager.getStorageInfo();
    if (info) {
      console.log('Storage Info:', info);

      const el = document.getElementById('storage-info');
      if (el) {
        el.innerHTML = `
          <strong>Storage:</strong> ${info.usage} / ${info.quota}
          (${info.percentUsed}% used)
        `;
      }

      // Warn if storage is getting full
      if (parseFloat(info.percentUsed) > 80) {
        this.showWarning('Storage is running low. Consider clearing old data.');
      }
    }
  }

  /**
   * Setup periodic cleanup
   */
  setupPeriodicCleanup() {
    // Clean old sales every day
    setInterval(async () => {
      const deleted = await dbManager.cleanOldSales();
      if (deleted > 0) {
        console.log(`Cleaned ${deleted} old sales`);
      }
    }, 24 * 60 * 60 * 1000);

    // Clean resolved conflicts every week
    setInterval(async () => {
      const cleared = await conflictResolver.clearResolvedConflicts();
      if (cleared > 0) {
        console.log(`Cleared ${cleared} old conflicts`);
      }
    }, 7 * 24 * 60 * 60 * 1000);

    // Clean sync queue
    setInterval(async () => {
      await syncManager.cleanQueue();
    }, 24 * 60 * 60 * 1000);
  }

  /**
   * Show sync progress UI
   */
  showSyncProgress(show) {
    const el = document.getElementById('sync-progress');
    if (el) {
      el.style.display = show ? 'block' : 'none';
    }
  }

  /**
   * Update sync progress
   */
  updateSyncProgress(progress) {
    const el = document.getElementById('sync-progress');
    if (el) {
      const percent = (progress.completed / progress.total) * 100;
      el.innerHTML = `
        <div class="sync-bar">
          <div class="sync-bar-fill" style="width: ${percent}%"></div>
        </div>
        <div class="sync-text">
          Syncing ${progress.current}...
          (${progress.completed}/${progress.total})
        </div>
      `;
    }
  }

  /**
   * Show notification
   */
  showNotification(title, message, type = 'success') {
    const el = document.getElementById('notifications');
    if (el) {
      const notification = document.createElement('div');
      notification.className = `notification notification-${type}`;
      notification.innerHTML = `
        <strong>${title}</strong><br>
        ${message}
      `;

      el.appendChild(notification);

      setTimeout(() => {
        notification.remove();
      }, 5000);
    }

    console.log(`[${type.toUpperCase()}] ${title}: ${message}`);
  }

  /**
   * Show error
   */
  showError(message) {
    this.showNotification('Error', message, 'error');
  }

  /**
   * Show warning
   */
  showWarning(message) {
    this.showNotification('Warning', message, 'warning');
  }

  /**
   * Show login screen
   */
  showLoginScreen() {
    // Hide main app, show login
    document.getElementById('main-app')?.classList.add('hidden');
    document.getElementById('login-screen')?.classList.remove('hidden');
  }

  /**
   * Show main app
   */
  showMainApp() {
    // Show main app, hide login
    document.getElementById('login-screen')?.classList.add('hidden');
    document.getElementById('main-app')?.classList.remove('hidden');
  }

  /**
   * Handle login
   */
  async handleLogin(username, password) {
    try {
      const result = await authManager.smartLogin(username, password);

      if (result.success) {
        this.showNotification('Login successful',
          result.offline ? 'Logged in offline' : 'Logged in online');

        // Reload app
        await this.init();
      }
    } catch (error) {
      this.showError(error.message);
    }
  }

  /**
   * Handle logout
   */
  async handleLogout() {
    if (confirm('Logout? Unsynced changes will be preserved.')) {
      await authManager.logout();
      this.showLoginScreen();
    }
  }

  /**
   * Create a sale (offline-capable)
   */
  async createSale(saleData) {
    try {
      const user = await authManager.getCurrentUser();

      // Generate client-side ID
      const saleId = `sale_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;

      const sale = {
        id: saleId,
        ...saleData,
        created_by: user.id,
        created_at: new Date().toISOString(),
        sync_status: 'pending'
      };

      // Save to local database
      await dbManager.put('sales', sale, user.id);

      // Add to sync queue
      await syncManager.addToQueue('sales', 'create', sale, 1); // Priority 1 = highest

      this.showNotification('Sale created', 'Will sync when online');

      return sale;
    } catch (error) {
      this.showError('Failed to create sale: ' + error.message);
      throw error;
    }
  }

  /**
   * Update inventory (offline-capable)
   */
  async updateStock(productId, quantityChange, reason) {
    try {
      const user = await authManager.getCurrentUser();

      // Get current stock
      const stocks = await dbManager.getAll('stock', 'product_id', productId);
      let stock = stocks[0];

      if (!stock) {
        throw new Error('Stock record not found');
      }

      // Update quantity
      stock.quantity += quantityChange;
      stock.quantity_change = quantityChange; // Track the change

      // Save updated stock
      await dbManager.put('stock', stock, user.id);

      // Create stock movement record
      const movementId = `movement_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`;
      const movement = {
        id: movementId,
        product_id: productId,
        quantity: quantityChange,
        reason: reason,
        created_by: user.id,
        created_at: new Date().toISOString(),
        sync_status: 'pending'
      };

      await dbManager.put('stock_movements', movement, user.id);

      // Add both to sync queue
      await syncManager.addToQueue('stock', 'update', stock, 3);
      await syncManager.addToQueue('stock_movements', 'create', movement, 2);

      return { stock, movement };
    } catch (error) {
      this.showError('Failed to update stock: ' + error.message);
      throw error;
    }
  }

  /**
   * Get unsynced item count
   */
  async getUnsyncedCount() {
    const status = await syncManager.getQueueStatus();
    return status.pending;
  }

  /**
   * Manual sync trigger
   */
  async triggerSync() {
    if (!navigator.onLine) {
      this.showWarning('Cannot sync while offline');
      return;
    }

    try {
      await syncManager.manualSync();
    } catch (error) {
      this.showError('Sync failed: ' + error.message);
    }
  }

  /**
   * View conflicts
   */
  async showConflicts() {
    const conflicts = await conflictResolver.getManualConflicts();

    if (conflicts.length === 0) {
      this.showNotification('No conflicts', 'All data is synchronized');
      return;
    }

    // Display conflicts UI (implement based on your UI framework)
    console.log('Manual conflicts requiring resolution:', conflicts);
    // TODO: Show conflicts modal/page
  }
}

// Initialize app when DOM is ready
document.addEventListener('DOMContentLoaded', async () => {
  window.posApp = new POSApp();
  await window.posApp.init();
});

// Export for use in other modules
export default POSApp;