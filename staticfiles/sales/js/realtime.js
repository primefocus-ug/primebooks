class CartWebSocket {
    constructor(cartId) {
        this.cartId = cartId;
        this.socket = new WebSocket(
            `ws://${window.location.host}/ws/cart/${cartId}/`
        );

        this.socket.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.type === 'cart_update') {
                this.handleCartUpdate(data.message);
            }
        };

        this.socket.onclose = (e) => {
            console.error('Cart socket closed unexpectedly');
            setTimeout(() => this.reconnect(), 5000);
        };
    }

    handleCartUpdate(message) {
        // Update subtotal, total, and item count
        $('.cart-subtotal').text(message.subtotal);
        $('.cart-total').text(message.total_amount);
        $('.cart-item-count').text(message.item_count);
        
        // Show notification
        this.showNotification('Cart Updated', 'Your cart has been updated');
    }

    showNotification(title, message) {
        if (Notification.permission === 'granted') {
            new Notification(title, { body: message });
        } else if (Notification.permission !== 'denied') {
            Notification.requestPermission().then(permission => {
                if (permission === 'granted') {
                    new Notification(title, { body: message });
                }
            });
        }
    }

    reconnect() {
        console.log('Attempting to reconnect to cart WebSocket...');
        this.socket = new WebSocket(
            `ws://${window.location.host}/ws/cart/${this.cartId}/`
        );
    }
}

class SalesDashboardWebSocket {
    constructor(companyId) {
        this.companyId = companyId;
        this.socket = new WebSocket(
            `ws://${window.location.host}/ws/sales/${companyId}/`
        );

        this.socket.onmessage = (e) => {
            const data = JSON.parse(e.data);
            if (data.type === 'sale_update') {
                this.handleSaleUpdate(data.message);
            }
        };

        this.socket.onclose = (e) => {
            console.error('Sales socket closed unexpectedly');
            setTimeout(() => this.reconnect(), 5000);
        };
    }

    handleSaleUpdate(message) {
        // Refresh DataTable if it exists
        if (window.SalesDataTable) {
            window.SalesDataTable.ajax.reload(null, false);
        }
        
        // Show notification
        this.showNotification('New Sale', `Sale #${message.invoice_number} for ${message.total_amount}`);
        
        // Play sound
        this.playNotificationSound();
    }

    showNotification(title, message) {
        if (Notification.permission === 'granted') {
            new Notification(title, { body: message });
        } else if (Notification.permission !== 'denied') {
            Notification.requestPermission().then(permission => {
                if (permission === 'granted') {
                    new Notification(title, { body: message });
                }
            });
        }
    }

    playNotificationSound() {
        const audio = new Audio('/static/sales/sounds/notification.mp3');
        audio.play().catch(e => console.log('Audio playback failed:', e));
    }

    reconnect() {
        console.log('Attempting to reconnect to sales WebSocket...');
        this.socket = new WebSocket(
            `ws://${window.location.host}/ws/sales/${this.companyId}/`
        );
    }
}

// Initialize WebSockets when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    const cartId = document.body.getAttribute('data-cart-id');
    const companyId = document.body.getAttribute('data-company-id');
    
    if (cartId) {
        window.cartSocket = new CartWebSocket(cartId);
    }
    
    if (companyId && window.location.pathname.includes('sales')) {
        window.salesSocket = new SalesDashboardWebSocket(companyId);
        
        // Request notification permission
        if (Notification.permission !== 'granted') {
            Notification.requestPermission();
        }
    }
});