from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from datetime import datetime


class WebSocketBroadcaster:
    """Utility class for broadcasting WebSocket messages"""

    def __init__(self):
        self.channel_layer = get_channel_layer()

    def _send(self, group_name, event_type, data):
        """Helper to send WebSocket message"""
        if not self.channel_layer:
            return
        async_to_sync(self.channel_layer.group_send)(
            group_name,
            {
                'type': event_type,
                'data': data
            }
        )

    def broadcast_dashboard_update(self, tenant_id=None):
        """Broadcast dashboard statistics update"""
        group_name = f"dashboard_{tenant_id or 'default'}"
        self._send(group_name, 'dashboard_update', {
            'timestamp': datetime.now().isoformat(),
            'message': 'Dashboard data updated'
        })

    def broadcast_stock_movement(self, movement, tenant_id=None):
        """Broadcast new stock movement"""
        group_name = f"dashboard_{tenant_id or 'default'}"

        # Find the latest stock level for that product in that store
        stock = movement.store.inventory.filter(product=movement.product).first()

        movement_data = {
            'id': movement.id,
            'product_name': movement.product.name,
            'product_sku': movement.product.sku,
            'movement_type': movement.movement_type,
            'movement_type_display': movement.get_movement_type_display(),
            'quantity': float(movement.quantity),
            'unit_of_measure': movement.product.unit_of_measure,
            'store_name': movement.store.name,
            'created_by': movement.created_by.get_full_name() or movement.created_by.username,
            'created_at': movement.created_at.isoformat(),
            'reference': movement.reference,
            'notes': movement.notes,
            'current_stock': float(stock.quantity) if stock else 0
        }

        self._send(group_name, 'stock_movement_created', movement_data)

    def broadcast_stock_alert(self, alert_type, product, stock, tenant_id=None):
        """Broadcast stock alert"""
        alerts_group = f"stock_alerts_{tenant_id or 'default'}"
        dashboard_group = f"dashboard_{tenant_id or 'default'}"

        alert_data = {
            'alert_type': alert_type,
            'product_name': product.name,
            'product_sku': product.sku,
            'store_name': stock.store.name,
            'current_quantity': float(stock.quantity),
            'reorder_level': float(stock.low_stock_threshold),
            'unit_of_measure': product.unit_of_measure,
            'timestamp': datetime.now().isoformat()
        }

        for group in [alerts_group, dashboard_group]:
            self._send(group, f'{alert_type}_alert', alert_data)

    def broadcast_import_progress(self, session_id, progress_data):
        """Broadcast import progress update"""
        group_name = f"import_{session_id}"
        self._send(group_name, 'import_progress_update', progress_data)

    def broadcast_import_log(self, session_id, log_entry):
        """Broadcast new import log entry"""
        group_name = f"import_{session_id}"
        log_data = {
            'id': log_entry.id,
            'level': log_entry.level,
            'message': log_entry.message,
            'row_number': log_entry.row_number,
            'details': log_entry.details,
            'timestamp': log_entry.timestamp.isoformat()
        }
        self._send(group_name, 'import_log_added', log_data)

    def broadcast_import_completion(self, session_id, final_stats):
        """Broadcast import completion"""
        group_name = f"import_{session_id}"
        self._send(group_name, 'import_completed', final_stats)

    def broadcast_import_failure(self, session_id, error_info):
        """Broadcast import failure"""
        group_name = f"import_{session_id}"
        self._send(group_name, 'import_failed', error_info)


# Global broadcaster instance
broadcaster = WebSocketBroadcaster()
