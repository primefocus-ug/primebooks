/**
 * Messaging Client for Django Messaging System
 * Handles WebSocket connections, API calls, and real-time messaging
 */

class MessagingClient {
    constructor(apiBaseUrl = '/api/messaging') {
        this.apiBaseUrl = apiBaseUrl;
        this.ws = null;
        this.currentConversationId = null;
        this.typingTimeout = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
        
        // Event callbacks
        this.onNewMessage = null;
        this.onTyping = null;
        this.onReadReceipt = null;
        this.onReaction = null;
        this.onConnectionChange = null;
        this.onError = null;
        
        // Get CSRF token
        this.csrfToken = this.getCookie('csrftoken');
        
        // Initialize WebSocket
        this.connectWebSocket();
    }
    
    getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
    
    // WebSocket Methods
    connectWebSocket() {
        const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${wsProtocol}//${window.location.host}/ws/messaging/`;
        
        this.ws = new WebSocket(wsUrl);
        
        this.ws.onopen = () => {
            console.log('[MessagingClient] WebSocket connected');
            this.reconnectAttempts = 0;
            if (this.onConnectionChange) {
                this.onConnectionChange(true);
            }
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };
        
        this.ws.onclose = () => {
            console.log('[MessagingClient] WebSocket disconnected');
            if (this.onConnectionChange) {
                this.onConnectionChange(false);
            }
            
            // Try to reconnect
            if (this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                setTimeout(() => {
                    console.log(`[MessagingClient] Reconnecting... (attempt ${this.reconnectAttempts})`);
                    this.connectWebSocket();
                }, 3000);
            }
        };
        
        this.ws.onerror = (error) => {
            console.error('[MessagingClient] WebSocket error:', error);
            if (this.onError) {
                this.onError('Connection error');
            }
        };
    }
    
    handleWebSocketMessage(data) {
        console.log('[MessagingClient] Received:', data);
        
        switch (data.type) {
            case 'connection_established':
                console.log('[MessagingClient] Connection established');
                break;
                
            case 'new_message':
                if (this.onNewMessage) {
                    this.onNewMessage(data.message, data.conversation_id);
                }
                break;
                
            case 'typing':
                if (this.onTyping) {
                    this.onTyping(data);
                }
                break;
                
            case 'read_receipt':
                if (this.onReadReceipt) {
                    this.onReadReceipt(data);
                }
                break;
                
            case 'reaction':
                if (this.onReaction) {
                    this.onReaction(data);
                }
                break;
                
            case 'message_deleted':
                console.log('[MessagingClient] Message deleted:', data.message_id);
                break;
                
            case 'user_joined':
            case 'user_left':
                console.log(`[MessagingClient] ${data.type}:`, data.username);
                break;
                
            case 'notification':
                console.log('[MessagingClient] Notification:', data);
                break;
                
            case 'error':
                console.error('[MessagingClient] Error:', data.message);
                if (this.onError) {
                    this.onError(data.message);
                }
                break;
        }
    }
    
    sendWebSocketMessage(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(data));
        } else {
            console.error('[MessagingClient] WebSocket not connected');
            if (this.onError) {
                this.onError('Not connected to messaging server');
            }
        }
    }
    
    // API Methods
    async apiCall(endpoint, options = {}) {
        const url = `${this.apiBaseUrl}${endpoint}`;
        const headers = {
            'X-CSRFToken': this.csrfToken,
            ...options.headers
        };
        
        // Don't set Content-Type for FormData
        if (!(options.body instanceof FormData)) {
            headers['Content-Type'] = 'application/json';
        }
        
        try {
            const response = await fetch(url, {
                ...options,
                headers
            });
            
            if (!response.ok) {
                const error = await response.json().catch(() => ({
                    error: `HTTP ${response.status}: ${response.statusText}`
                }));
                throw new Error(error.error || error.detail || 'Request failed');
            }
            
            return await response.json();
        } catch (error) {
            console.error('[MessagingClient] API Error:', error);
            if (this.onError) {
                this.onError(error.message);
            }
            throw error;
        }
    }
    
    // Conversation Methods
    async getConversations(search = '') {
        const params = search ? `?search=${encodeURIComponent(search)}` : '';
        return await this.apiCall(`/conversations/${params}`);
    }
    
    async createConversation(data) {
        return await this.apiCall('/conversations/', {
            method: 'POST',
            body: JSON.stringify(data)
        });
    }
    
    async joinConversation(conversationId) {
        this.currentConversationId = conversationId;
        
        // Send join message via WebSocket
        this.sendWebSocketMessage({
            type: 'join_conversation',
            conversation_id: conversationId
        });
        
        // Load messages
        return await this.getMessages(conversationId);
    }
    
    async leaveConversation(conversationId) {
        this.sendWebSocketMessage({
            type: 'leave_conversation',
            conversation_id: conversationId
        });
        
        if (this.currentConversationId === conversationId) {
            this.currentConversationId = null;
        }
    }
    
    // Message Methods
    async getMessages(conversationId, limit = 50, before = null) {
        let url = `/messages/?conversation_id=${conversationId}&limit=${limit}`;
        if (before) {
            url += `&before=${before}`;
        }
        return await this.apiCall(url);
    }
    
    async sendMessage(conversationId, content, options = {}) {
        const formData = new FormData();
        formData.append('conversation_id', conversationId);
        formData.append('content', content);
        
        if (options.replyTo) {
            formData.append('reply_to', options.replyTo);
        }
        
        if (options.mentionedUsers && options.mentionedUsers.length > 0) {
            options.mentionedUsers.forEach(userId => {
                formData.append('mentioned_user_ids', userId);
            });
        }
        
        if (options.attachments && options.attachments.length > 0) {
            options.attachments.forEach(file => {
                formData.append('attachments', file);
            });
        }
        
        return await this.apiCall('/messages/', {
            method: 'POST',
            body: formData
        });
    }
    
    async deleteMessage(messageId) {
        this.sendWebSocketMessage({
            type: 'delete_message',
            message_id: messageId
        });
    }
    
    async reactToMessage(messageId, emoji, action = 'add') {
        this.sendWebSocketMessage({
            type: 'reaction',
            message_id: messageId,
            emoji: emoji,
            action: action
        });
    }
    
    // Typing Indicators
    startTyping(conversationId) {
        if (this.typingTimeout) {
            clearTimeout(this.typingTimeout);
        }
        
        this.sendWebSocketMessage({
            type: 'typing',
            conversation_id: conversationId,
            is_typing: true
        });
        
        // Auto-stop typing after 5 seconds
        this.typingTimeout = setTimeout(() => {
            this.stopTyping(conversationId);
        }, 5000);
    }
    
    stopTyping(conversationId) {
        if (this.typingTimeout) {
            clearTimeout(this.typingTimeout);
            this.typingTimeout = null;
        }
        
        this.sendWebSocketMessage({
            type: 'typing',
            conversation_id: conversationId,
            is_typing: false
        });
    }
    
    // Read Receipts
    markMessagesAsRead(conversationId, messageIds) {
        this.sendWebSocketMessage({
            type: 'mark_read',
            conversation_id: conversationId,
            message_ids: messageIds
        });
    }
    
    // Search
    async searchMessages(query, filters = {}) {
        return await this.apiCall('/messages/search/', {
            method: 'POST',
            body: JSON.stringify({
                query,
                ...filters
            })
        });
    }
    
    // User Search
    async searchUsers(query, limit = 20) {
        return await this.apiCall(`/conversations/search_users/?q=${encodeURIComponent(query)}&limit=${limit}`);
    }
    
    // Cleanup
    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
}

// Make it globally available
window.MessagingClient = MessagingClient;