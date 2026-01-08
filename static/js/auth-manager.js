/**
 * Authentication Manager with Offline Support
 * Handles online login, offline authentication, and session management
 */

import dbManager from './db-manager.js';

class AuthManager {
  constructor() {
    this.currentUser = null;
    this.sessionDuration = 24 * 60 * 60 * 1000; // 24 hours in milliseconds
    this.apiBaseUrl = '/api'; // Adjust to your Django API endpoint
  }

  /**
   * Online login - must be online for initial authentication
   */
  async login(username, password) {
    try {
      const response = await fetch(`${this.apiBaseUrl}/auth/login/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ username, password })
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.message || 'Login failed');
      }

      const data = await response.json();

      // Cache user data and credentials for offline use
      await this.cacheAuthData(data, password);

      this.currentUser = data.user;
      return {
        success: true,
        user: data.user,
        token: data.token
      };

    } catch (error) {
      if (!navigator.onLine) {
        throw new Error('You must be online for initial login');
      }
      throw error;
    }
  }

  /**
   * Offline login using cached credentials
   */
  async offlineLogin(username, password) {
    await dbManager.init();

    // Get cached auth data
    const cachedAuth = await dbManager.get('auth_cache', 'credentials');

    if (!cachedAuth) {
      throw new Error('No cached credentials. Please login online first.');
    }

    // Check if session expired
    const now = new Date().getTime();
    if (now > cachedAuth.expires_at) {
      throw new Error('Offline session expired. Please login online.');
    }

    // Verify credentials match (using simple comparison - in production use proper hashing)
    const hashedPassword = await this.hashPassword(password);

    if (cachedAuth.username === username && cachedAuth.password === hashedPassword) {
      // Extend session
      await this.extendSession();

      this.currentUser = cachedAuth.user;
      return {
        success: true,
        user: cachedAuth.user,
        offline: true
      };
    } else {
      throw new Error('Invalid credentials');
    }
  }

  /**
   * Smart login - tries online first, falls back to offline
   */
  async smartLogin(username, password) {
    if (navigator.onLine) {
      try {
        return await this.login(username, password);
      } catch (error) {
        // If online login fails due to network, try offline
        console.warn('Online login failed, attempting offline login', error);
        return await this.offlineLogin(username, password);
      }
    } else {
      return await this.offlineLogin(username, password);
    }
  }

  /**
   * Cache authentication data for offline use
   */
  async cacheAuthData(authData, password) {
    const expiresAt = new Date().getTime() + this.sessionDuration;
    const hashedPassword = await this.hashPassword(password);

    const cacheData = {
      key: 'credentials',
      username: authData.user.username,
      password: hashedPassword,
      user: authData.user,
      token: authData.token,
      expires_at: expiresAt,
      cached_at: new Date().toISOString()
    };

    await dbManager.put('auth_cache', cacheData);

    // Also cache current user separately
    await dbManager.put('auth_cache', {
      key: 'current_user',
      user: authData.user,
      expires_at: expiresAt
    });
  }

  /**
   * Extend offline session
   */
  async extendSession() {
    const cachedAuth = await dbManager.get('auth_cache', 'credentials');
    if (cachedAuth) {
      cachedAuth.expires_at = new Date().getTime() + this.sessionDuration;
      await dbManager.put('auth_cache', cachedAuth);
    }
  }

  /**
   * Check if user is authenticated (online or offline)
   */
  async isAuthenticated() {
    if (this.currentUser) {
      return true;
    }

    // Check cached session
    const currentUserCache = await dbManager.get('auth_cache', 'current_user');
    if (currentUserCache) {
      const now = new Date().getTime();
      if (now <= currentUserCache.expires_at) {
        this.currentUser = currentUserCache.user;
        return true;
      }
    }

    return false;
  }

  /**
   * Get current user
   */
  async getCurrentUser() {
    if (this.currentUser) {
      return this.currentUser;
    }

    const currentUserCache = await dbManager.get('auth_cache', 'current_user');
    if (currentUserCache) {
      const now = new Date().getTime();
      if (now <= currentUserCache.expires_at) {
        this.currentUser = currentUserCache.user;
        return this.currentUser;
      }
    }

    return null;
  }

  /**
   * Logout - clear cached data
   */
  async logout() {
    this.currentUser = null;

    // Clear auth cache
    await dbManager.clear('auth_cache');

    // Optionally clear all offline data
    // await dbManager.deleteDatabase();
  }

  /**
   * Get authentication token for API requests
   */
  async getToken() {
    const cachedAuth = await dbManager.get('auth_cache', 'credentials');
    return cachedAuth ? cachedAuth.token : null;
  }

  /**
   * Simple password hashing (use bcrypt or similar in production)
   */
  async hashPassword(password) {
    const msgBuffer = new TextEncoder().encode(password);
    const hashBuffer = await crypto.subtle.digest('SHA-256', msgBuffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }

  /**
   * Check session expiry time remaining
   */
  async getSessionTimeRemaining() {
    const cachedAuth = await dbManager.get('auth_cache', 'credentials');
    if (!cachedAuth) return 0;

    const now = new Date().getTime();
    const remaining = cachedAuth.expires_at - now;
    return remaining > 0 ? remaining : 0;
  }

  /**
   * Format time remaining as human readable
   */
  formatTimeRemaining(milliseconds) {
    const hours = Math.floor(milliseconds / (1000 * 60 * 60));
    const minutes = Math.floor((milliseconds % (1000 * 60 * 60)) / (1000 * 60));
    return `${hours}h ${minutes}m`;
  }
}

// Export singleton instance
const authManager = new AuthManager();
export default authManager;