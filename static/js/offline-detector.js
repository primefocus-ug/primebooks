/**
 * Offline Detector & Network Status Monitor
 * Monitors connection status and triggers sync when online
 */

import syncManager from './sync-manager.js';

class OfflineDetector {
  constructor() {
    this.isOnline = navigator.onLine;
    this.listeners = [];
    this.lastOnlineCheck = Date.now();
    this.checkInterval = null;
    this.init();
  }

  /**
   * Initialize event listeners
   */
  init() {
    // Listen to browser online/offline events
    window.addEventListener('online', () => this.handleOnline());
    window.addEventListener('offline', () => this.handleOffline());

    // Periodic connection check (backup for unreliable online/offline events)
    this.startPeriodicCheck();

    // Check on visibility change (when user returns to tab)
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) {
        this.checkConnection();
      }
    });

    // Initial check
    this.checkConnection();
  }

  /**
   * Handle online event
   */
  async handleOnline() {
    console.log('Connection restored');
    this.isOnline = true;
    this.lastOnlineCheck = Date.now();

    this.notifyListeners('online');
    this.updateUI(true);

    // Trigger sync after coming online
    setTimeout(() => {
      syncManager.startSync();
    }, 1000); // Small delay to ensure connection is stable
  }

  /**
   * Handle offline event
   */
  handleOffline() {
    console.log('Connection lost');
    this.isOnline = false;

    this.notifyListeners('offline');
    this.updateUI(false);
  }

  /**
   * Actively check connection (more reliable than events)
   */
  async checkConnection() {
    try {
      // Try to fetch a small resource from your server
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 5000);

      const response = await fetch('/api/health/', {
        method: 'HEAD',
        cache: 'no-store',
        signal: controller.signal
      });

      clearTimeout(timeoutId);

      const wasOffline = !this.isOnline;
      this.isOnline = response.ok;
      this.lastOnlineCheck = Date.now();

      // If we just came back online
      if (wasOffline && this.isOnline) {
        this.handleOnline();
      }

      return this.isOnline;

    } catch (error) {
      const wasOnline = this.isOnline;
      this.isOnline = false;

      // If we just went offline
      if (wasOnline && !this.isOnline) {
        this.handleOffline();
      }

      return false;
    }
  }

  /**
   * Start periodic connection checking
   */
  startPeriodicCheck() {
    // Check every 30 seconds
    this.checkInterval = setInterval(() => {
      this.checkConnection();
    }, 30000);
  }

  /**
   * Stop periodic checking
   */
  stopPeriodicCheck() {
    if (this.checkInterval) {
      clearInterval(this.checkInterval);
      this.checkInterval = null;
    }
  }

  /**
   * Get current connection status
   */
  getStatus() {
    return {
      online: this.isOnline,
      lastCheck: this.lastOnlineCheck,
      timeSinceCheck: Date.now() - this.lastOnlineCheck
    };
  }

  /**
   * Update UI based on connection status
   */
  updateUI(isOnline) {
    // Update status indicator
    const statusEl = document.getElementById('connection-status');
    if (statusEl) {
      statusEl.className = isOnline ? 'online' : 'offline';
      statusEl.textContent = isOnline ? 'Online' : 'Offline';
      statusEl.title = isOnline ?
        'Connected to server' :
        'Working offline - changes will sync when online';
    }

    // Show/hide offline banner
    const bannerEl = document.getElementById('offline-banner');
    if (bannerEl) {
      bannerEl.style.display = isOnline ? 'none' : 'block';
    }

    // Update body class for CSS styling
    document.body.classList.toggle('offline-mode', !isOnline);
    document.body.classList.toggle('online-mode', isOnline);
  }

  /**
   * Subscribe to connection events
   */
  on(callback) {
    this.listeners.push(callback);
  }

  /**
   * Unsubscribe from events
   */
  off(callback) {
    this.listeners = this.listeners.filter(cb => cb !== callback);
  }

  /**
   * Notify all listeners
   */
  notifyListeners(status) {
    this.listeners.forEach(callback => {
      try {
        callback(status);
      } catch (error) {
        console.error('Listener error:', error);
      }
    });
  }

  /**
   * Force connection check
   */
  async forceCheck() {
    return await this.checkConnection();
  }

  /**
   * Cleanup
   */
  destroy() {
    this.stopPeriodicCheck();
    window.removeEventListener('online', this.handleOnline);
    window.removeEventListener('offline', this.handleOffline);
    this.listeners = [];
  }
}

// Export singleton instance
const offlineDetector = new OfflineDetector();
export default offlineDetector;