/**
 * Sync Manager - Handles offline queue and synchronization
 * Priority order: Sales -> Stock Movements -> Inventory -> Others
 */

import dbManager from './db-manager.js';
import authManager from './auth-manager.js';
import conflictResolver from './conflict-resolver.js';
import djangoAPIAdapter from './django-api-adapter.js';

class SyncManager {
  constructor() {
    this.isSyncing = false;
    this.syncProgress = {
      total: 0,
      completed: 0,
      failed: 0,
      current: null
    };
    this.listeners = [];
    this.apiBaseUrl = '/api'; // Adjust to your Django API
  }

  /**
   * Add item to sync queue
   */
  async addToQueue(entityType, operation, data, priority = 5) {
    const queueItem = {
      entity_type: entityType,
      operation: operation, // 'create', 'update', 'delete'
      data: data,
      priority: priority, // 1 = highest, 10 = lowest
      status: 'pending',
      created_at: new Date().toISOString(),
      retry_count: 0,
      error: null
    };

    await dbManager.put('sync_queue', queueItem);

    // Trigger sync if online
    if (navigator.onLine && !this.isSyncing) {
      this.startSync();
    }
  }

  /**
   * Get priority for entity type (sales = highest)
   */
  getPriorityForEntity(entityType) {
    const priorities = {
      'sales': 1,
      'stock_movements': 2,
      'stock': 3,
      'products': 4,
      'categories': 5,
      'customers': 6,
      'services': 7,
      'stores': 8
    };
    return priorities[entityType] || 5;
  }

  /**
   * Start synchronization process
   */
  async startSync() {
    if (this.isSyncing) {
      console.log('Sync already in progress');
      return;
    }

    if (!navigator.onLine) {
      console.log('Cannot sync while offline');
      return;
    }

    this.isSyncing = true;
    this.notifyListeners('sync_started');

    try {
      // Get all pending items
      const pendingItems = await dbManager.getAll('sync_queue', 'status', 'pending');

      // Sort by priority (sales first)
      pendingItems.sort((a, b) => a.priority - b.priority);

      this.syncProgress.total = pendingItems.length;
      this.syncProgress.completed = 0;
      this.syncProgress.failed = 0;

      console.log(`Starting sync of ${pendingItems.length} items`);

      // Process each item
      for (const item of pendingItems) {
        await this.syncItem(item);
      }

      // After all syncs, fetch updates from server
      await this.fetchServerUpdates();

      this.notifyListeners('sync_completed', this.syncProgress);

    } catch (error) {
      console.error('Sync error:', error);
      this.notifyListeners('sync_error', error);
    } finally {
      this.isSyncing = false;
    }
  }

  /**
   * Sync individual item
   */
  async syncItem(item) {
    this.syncProgress.current = `${item.entity_type} (${item.operation})`;
    this.notifyListeners('sync_progress', this.syncProgress);

    try {
      const token = await authManager.getToken();
      const endpoint = this.getEndpointForEntity(item.entity_type);

      let response;

      switch (item.operation) {
        case 'create':
          response = await this.createOnServer(endpoint, item.data, token);
          break;
        case 'update':
          response = await this.updateOnServer(endpoint, item.data, token);
          break;
        case 'delete':
          response = await this.deleteOnServer(endpoint, item.data.id, token);
          break;
      }

      // Handle conflicts
      if (response.conflict) {
        await conflictResolver.handleConflict(item.entity_type, item.data, response.serverData);
        this.syncProgress.failed++;
      } else {
        // Update local data with server response
        if (response.data && item.operation !== 'delete') {
          await dbManager.put(item.entity_type, {
            ...response.data,
            sync_status: 'synced'
          });
        }

        // Remove from queue
        await dbManager.delete('sync_queue', item.id);
        this.syncProgress.completed++;
      }

    } catch (error) {
      console.error(`Failed to sync ${item.entity_type}:`, error);

      // Update retry count
      item.retry_count++;
      item.error = error.message;
      item.status = item.retry_count >= 3 ? 'failed' : 'pending';

      await dbManager.put('sync_queue', item);
      this.syncProgress.failed++;
    }
  }

  /**
   * Create on server
   */
  async createOnServer(endpoint, data, token) {
    // Transform data to Django format
    const entityType = this.getEntityTypeFromEndpoint(endpoint);
    const djangoData = djangoAPIAdapter.transformToDjango(entityType, data);

    const response = await fetch(`${this.apiBaseUrl}${endpoint}/`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(djangoData)
    });

    if (response.status === 409) {
      // Conflict detected
      const serverData = await response.json();
      return { conflict: true, serverData };
    }

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      const errorMessage = djangoAPIAdapter.handleDjangoError(errorData);
      throw new Error(errorMessage || `Server error: ${response.status}`);
    }

    const responseData = await response.json();
    // Transform response back to our format
    return { data: djangoAPIAdapter.transformFromDjango(entityType, responseData) };
  }

  /**
   * Update on server
   */
  async updateOnServer(endpoint, data, token) {
    const response = await fetch(`${this.apiBaseUrl}${endpoint}/${data.id}/`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${token}`
      },
      body: JSON.stringify(data)
    });

    if (response.status === 409) {
      // Conflict detected
      const serverData = await response.json();
      return { conflict: true, serverData };
    }

    if (!response.ok) {
      throw new Error(`Server error: ${response.status}`);
    }

    return { data: await response.json() };
  }

  /**
   * Delete on server
   */
  async deleteOnServer(endpoint, id, token) {
    const response = await fetch(`${this.apiBaseUrl}${endpoint}/${id}/`, {
      method: 'DELETE',
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });

    if (!response.ok && response.status !== 404) {
      throw new Error(`Server error: ${response.status}`);
    }

    return { data: null };
  }

  /**
   * Fetch updates from server (pull changes made by other users)
   */
  async fetchServerUpdates() {
    const token = await authManager.getToken();
    const lastSync = await this.getLastSyncTime();

    // Fetch updates for each entity type
    const entities = ['products', 'categories', 'stock', 'services',
                     'customers', 'stores', 'stock_movements'];

    for (const entity of entities) {
      try {
        const endpoint = this.getEndpointForEntity(entity);
        const response = await fetch(
          `${this.apiBaseUrl}${endpoint}/?updated_since=${lastSync}`,
          {
            headers: { 'Authorization': `Bearer ${token}` }
          }
        );

        if (response.ok) {
          const data = await response.json();

          // Bulk update local database
          if (data.results && data.results.length > 0) {
            await dbManager.bulkPut(entity, data.results);
            console.log(`Fetched ${data.results.length} updates for ${entity}`);
          }
        }
      } catch (error) {
        console.error(`Failed to fetch ${entity} updates:`, error);
      }
    }

    // Update last sync time
    await this.setLastSyncTime();
  }

  /**
   * Get last sync timestamp
   */
  async getLastSyncTime() {
    const metadata = await dbManager.get('metadata', 'last_sync');
    return metadata ? metadata.value : new Date(0).toISOString();
  }

  /**
   * Set last sync timestamp
   */
  async setLastSyncTime() {
    await dbManager.put('metadata', {
      key: 'last_sync',
      value: new Date().toISOString()
    });
  }

  /**
   * Get API endpoint for entity type
   */
  getEndpointForEntity(entityType) {
    const endpoints = {
      'products': '/inventory/products',
      'categories': '/inventory/categories',
      'stock': '/inventory/stock',
      'services': '/inventory/services',
      'stock_movements': '/inventory/stock-movements',
      'sales': '/sales/sales',
      'customers': '/customers/customers',
      'stores': '/stores/stores'
    };
    return endpoints[entityType] || `/${entityType}`;
  }

  /**
   * Get entity type from endpoint (reverse lookup)
   */
  getEntityTypeFromEndpoint(endpoint) {
    const endpointMap = {
      '/inventory/products': 'product',
      '/inventory/categories': 'category',
      '/inventory/stock': 'stock',
      '/inventory/services': 'service',
      '/inventory/stock-movements': 'stock_movements',
      '/sales/sales': 'sales',
      '/customers/customers': 'customers',
      '/stores/stores': 'stores'
    };
    return endpointMap[endpoint] || 'unknown';
  }

  /**
   * Get sync queue status
   */
  async getQueueStatus() {
    const pending = await dbManager.count('sync_queue', 'status', 'pending');
    const failed = await dbManager.count('sync_queue', 'status', 'failed');

    return {
      pending,
      failed,
      total: pending + failed
    };
  }

  /**
   * Retry failed items
   */
  async retryFailed() {
    const failedItems = await dbManager.getAll('sync_queue', 'status', 'failed');

    for (const item of failedItems) {
      item.status = 'pending';
      item.retry_count = 0;
      await dbManager.put('sync_queue', item);
    }

    if (navigator.onLine) {
      await this.startSync();
    }
  }

  /**
   * Clear completed/old items from queue
   */
  async cleanQueue() {
    // This is already handled by removing items after successful sync
    // But we can add cleanup for very old failed items
    const sevenDaysAgo = new Date();
    sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

    const allItems = await dbManager.getAll('sync_queue');
    let cleaned = 0;

    for (const item of allItems) {
      if (item.status === 'failed' && new Date(item.created_at) < sevenDaysAgo) {
        await dbManager.delete('sync_queue', item.id);
        cleaned++;
      }
    }

    return cleaned;
  }

  /**
   * Subscribe to sync events
   */
  on(callback) {
    this.listeners.push(callback);
  }

  /**
   * Notify all listeners
   */
  notifyListeners(event, data) {
    this.listeners.forEach(callback => {
      try {
        callback(event, data);
      } catch (error) {
        console.error('Listener error:', error);
      }
    });
  }

  /**
   * Manual sync trigger
   */
  async manualSync() {
    if (!navigator.onLine) {
      throw new Error('Cannot sync while offline');
    }
    await this.startSync();
  }
}

// Export singleton instance
const syncManager = new SyncManager();
export default syncManager;