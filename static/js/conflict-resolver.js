/**
 * Conflict Resolver
 * Handles conflicts with different strategies per entity type
 * - Sales: Last-write-wins
 * - Inventory: Merge changes
 * - Products/Categories: Server-wins
 */

import dbManager from './db-manager.js';

class ConflictResolver {
  constructor() {
    this.strategies = {
      'sales': 'last-write-wins',
      'stock_movements': 'last-write-wins',
      'stock': 'merge',
      'products': 'server-wins',
      'categories': 'server-wins',
      'services': 'server-wins',
      'customers': 'merge',
      'stores': 'server-wins'
    };
  }

  /**
   * Main conflict handler
   */
  async handleConflict(entityType, localData, serverData) {
    const strategy = this.strategies[entityType] || 'manual';

    console.log(`Conflict detected for ${entityType}, using strategy: ${strategy}`);

    // Log conflict for tracking
    await this.logConflict(entityType, localData, serverData);

    switch (strategy) {
      case 'last-write-wins':
        return await this.lastWriteWins(entityType, localData, serverData);

      case 'server-wins':
        return await this.serverWins(entityType, localData, serverData);

      case 'merge':
        return await this.mergeChanges(entityType, localData, serverData);

      case 'manual':
        return await this.manualResolution(entityType, localData, serverData);

      default:
        return await this.manualResolution(entityType, localData, serverData);
    }
  }

  /**
   * Last-write-wins strategy
   * Compare timestamps and keep the most recent
   */
  async lastWriteWins(entityType, localData, serverData) {
    const localTime = new Date(localData.updated_at).getTime();
    const serverTime = new Date(serverData.updated_at).getTime();

    if (localTime > serverTime) {
      // Local is newer, keep trying to sync
      console.log(`Local ${entityType} is newer, will retry sync`);
      return { resolved: false, action: 'retry' };
    } else {
      // Server is newer, accept server version
      console.log(`Server ${entityType} is newer, accepting server version`);
      await dbManager.put(entityType, {
        ...serverData,
        sync_status: 'synced'
      });
      return { resolved: true, action: 'accepted_server' };
    }
  }

  /**
   * Server-wins strategy
   * Always accept server version (for products, categories, etc.)
   */
  async serverWins(entityType, localData, serverData) {
    console.log(`Server-wins: accepting server version for ${entityType}`);

    await dbManager.put(entityType, {
      ...serverData,
      sync_status: 'synced'
    });

    return { resolved: true, action: 'accepted_server' };
  }

  /**
   * Merge changes strategy
   * Intelligently merge local and server changes (for inventory, stock)
   */
  async mergeChanges(entityType, localData, serverData) {
    console.log(`Merging changes for ${entityType}`);

    let mergedData = { ...serverData };

    // Entity-specific merge logic
    if (entityType === 'stock') {
      mergedData = await this.mergeStock(localData, serverData);
    } else if (entityType === 'customers') {
      mergedData = await this.mergeCustomers(localData, serverData);
    } else {
      // Generic merge: take non-null fields from both
      mergedData = this.genericMerge(localData, serverData);
    }

    // Save merged version
    await dbManager.put(entityType, {
      ...mergedData,
      sync_status: 'synced',
      updated_at: new Date().toISOString()
    });

    return { resolved: true, action: 'merged', data: mergedData };
  }

  /**
   * Merge stock levels intelligently
   * Handle concurrent stock changes from multiple users
   */
  async mergeStock(localData, serverData) {
    const localQty = localData.quantity || 0;
    const serverQty = serverData.quantity || 0;
    const localChange = localData.quantity_change || 0;

    // If we have a record of what changed locally, apply that change to server value
    if (localChange !== 0) {
      const mergedQty = serverQty + localChange;

      return {
        ...serverData,
        quantity: Math.max(0, mergedQty), // Don't go negative
        last_merge: new Date().toISOString(),
        merge_note: `Local change of ${localChange} applied to server quantity`
      };
    }

    // Otherwise, take the higher quantity (conservative approach)
    return {
      ...serverData,
      quantity: Math.max(localQty, serverQty),
      last_merge: new Date().toISOString()
    };
  }

  /**
   * Merge customer data
   */
  async mergeCustomers(localData, serverData) {
    // Take most recent non-null values
    return {
      ...serverData,
      // Keep local updates if they're more recent
      phone: this.getMostRecent(localData.phone, serverData.phone,
                                 localData.updated_at, serverData.updated_at),
      email: this.getMostRecent(localData.email, serverData.email,
                                localData.updated_at, serverData.updated_at),
      address: this.getMostRecent(localData.address, serverData.address,
                                  localData.updated_at, serverData.updated_at),
      last_merge: new Date().toISOString()
    };
  }

  /**
   * Generic merge for unknown types
   */
  genericMerge(localData, serverData) {
    const merged = { ...serverData };

    // For each field in local data, if it's newer, use it
    for (const key in localData) {
      if (key === 'id' || key === 'sync_status') continue;

      if (localData[key] !== null && localData[key] !== undefined) {
        // Simple heuristic: if local has a value and server doesn't, use local
        if (!serverData[key]) {
          merged[key] = localData[key];
        }
      }
    }

    merged.last_merge = new Date().toISOString();
    return merged;
  }

  /**
   * Helper: get most recent value
   */
  getMostRecent(localValue, serverValue, localTime, serverTime) {
    if (!localValue) return serverValue;
    if (!serverValue) return localValue;

    return new Date(localTime) > new Date(serverTime) ? localValue : serverValue;
  }

  /**
   * Manual resolution - store for user to resolve
   */
  async manualResolution(entityType, localData, serverData) {
    console.log(`Manual resolution required for ${entityType}`);

    // Keep both versions for user to choose
    await this.logConflict(entityType, localData, serverData, true);

    return { resolved: false, action: 'manual_required' };
  }

  /**
   * Log conflict to database
   */
  async logConflict(entityType, localData, serverData, requiresManual = false) {
    const conflict = {
      entity_type: entityType,
      entity_id: localData.id,
      local_data: localData,
      server_data: serverData,
      resolved: false,
      requires_manual: requiresManual,
      created_at: new Date().toISOString(),
      resolution: null
    };

    await dbManager.put('conflict_log', conflict);
  }

  /**
   * Get all unresolved conflicts
   */
  async getUnresolvedConflicts() {
    return await dbManager.getAll('conflict_log', 'resolved', false);
  }

  /**
   * Get conflicts requiring manual resolution
   */
  async getManualConflicts() {
    const allConflicts = await dbManager.getAll('conflict_log', 'resolved', false);
    return allConflicts.filter(c => c.requires_manual);
  }

  /**
   * Manually resolve a conflict
   */
  async resolveManually(conflictId, chosenVersion, mergedData = null) {
    const conflict = await dbManager.get('conflict_log', conflictId);
    if (!conflict) {
      throw new Error('Conflict not found');
    }

    let finalData;

    if (chosenVersion === 'local') {
      finalData = conflict.local_data;
    } else if (chosenVersion === 'server') {
      finalData = conflict.server_data;
    } else if (chosenVersion === 'merged' && mergedData) {
      finalData = mergedData;
    } else {
      throw new Error('Invalid resolution choice');
    }

    // Update the entity with chosen version
    await dbManager.put(conflict.entity_type, {
      ...finalData,
      sync_status: 'synced',
      resolved_at: new Date().toISOString()
    });

    // Mark conflict as resolved
    conflict.resolved = true;
    conflict.resolution = {
      chosen: chosenVersion,
      resolved_at: new Date().toISOString(),
      final_data: finalData
    };

    await dbManager.put('conflict_log', conflict);

    return { resolved: true, data: finalData };
  }

  /**
   * Get conflict statistics
   */
  async getConflictStats() {
    const allConflicts = await dbManager.getAll('conflict_log');

    const stats = {
      total: allConflicts.length,
      resolved: allConflicts.filter(c => c.resolved).length,
      unresolved: allConflicts.filter(c => !c.resolved).length,
      manual: allConflicts.filter(c => c.requires_manual && !c.resolved).length,
      byType: {}
    };

    // Count by entity type
    allConflicts.forEach(c => {
      if (!stats.byType[c.entity_type]) {
        stats.byType[c.entity_type] = { total: 0, resolved: 0 };
      }
      stats.byType[c.entity_type].total++;
      if (c.resolved) {
        stats.byType[c.entity_type].resolved++;
      }
    });

    return stats;
  }

  /**
   * Clear old resolved conflicts (cleanup)
   */
  async clearResolvedConflicts(daysOld = 30) {
    const cutoffDate = new Date();
    cutoffDate.setDate(cutoffDate.getDate() - daysOld);

    const allConflicts = await dbManager.getAll('conflict_log');
    let cleared = 0;

    for (const conflict of allConflicts) {
      if (conflict.resolved && new Date(conflict.created_at) < cutoffDate) {
        await dbManager.delete('conflict_log', conflict.id);
        cleared++;
      }
    }

    return cleared;
  }
}

// Export singleton instance
const conflictResolver = new ConflictResolver();
export default conflictResolver;