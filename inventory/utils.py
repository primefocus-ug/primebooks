import json
from typing import Optional, Dict, Any
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone
from .models import Stock, StockMovement, ImportSession


class WebSocketNotifier:
    """Utility class for sending WebSocket notifications"""

    def __init__(self):
        self.channel_layer = get_channel_layer()

    def _send_group_message(self, group_name: str, message_type: str, data: Dict[str, Any]) -> None:
        if not self.channel_layer:
            return
        async_to_sync(self.channel_layer.group_send)(
            group_name,
            {
                'type': message_type,
                'data': data
            }
        )

    def send_dashboard_update(self, user_id: int, data: Dict[str, Any]) -> None:
        """Send dashboard update to a specific user group."""
        group_name = f"dashboard_{user_id}"
        self._send_group_message(group_name, 'dashboard_update', data)

    def send_stock_alert(self, user_id: int, alert_data: Dict[str, Any]) -> None:
        """Send stock alert to a specific user group."""
        group_name = f"dashboard_{user_id}"
        self._send_group_message(group_name, 'stock_alert', alert_data)

    def send_import_progress(self, session_id: int, progress_data: Dict[str, Any]) -> None:
        """Send import progress update to the import session group."""
        group_name = f"import_{session_id}"
        self._send_group_message(group_name, 'import_progress', progress_data)

    def send_import_log(self, session_id: int, log_data: Dict[str, Any]) -> None:
        """Send new import log entry."""
        group_name = f"import_{session_id}"
        self._send_group_message(group_name, 'import_log', log_data)

    def send_import_complete(self, session_id: int, completion_data: Dict[str, Any]) -> None:
        """Send import completion notification."""
        group_name = f"import_{session_id}"
        self._send_group_message(group_name, 'import_complete', completion_data)

    def send_import_error(self, session_id: int, error_data: Dict[str, Any]) -> None:
        """Send import error notification."""
        group_name = f"import_{session_id}"
        self._send_group_message(group_name, 'import_error', error_data)

    def send_stock_update(self, product_id: int, store_id: int, stock_data: Dict[str, Any]) -> None:
        """Send stock level update to product and store groups."""
        self._send_group_message(f"product_{product_id}", 'stock_update', stock_data)
        self._send_group_message(f"stock_store_{store_id}", 'stock_update', stock_data)

    def send_stock_movement(self, movement_id: int, movement_data: Dict[str, Any]) -> None:
        """Send new stock movement notification to relevant groups and dashboard."""
        try:
            movement = StockMovement.objects.select_related(
                'product', 'store', 'created_by'
            ).get(id=movement_id)

            self._send_group_message(f"product_{movement.product.id}", 'stock_movement', movement_data)
            self._send_group_message(f"stock_store_{movement.store.id}", 'stock_movement', movement_data)

            # Send dashboard update to movement creator
            self.send_dashboard_update(movement.created_by.id, {
                'type': 'new_movement',
                'movement': movement_data
            })

        except StockMovement.DoesNotExist:
            pass

    def send_low_stock_alert(self, stock_id: int) -> None:
        """Send low stock alert to product and store groups."""
        try:
            stock = Stock.objects.select_related('product', 'store').get(id=stock_id)

            alert_data = {
                'product_id': stock.product.id,
                'product_name': stock.product.name,
                'product_sku': stock.product.sku,
                'store_id': stock.store.id,
                'store_name': stock.store.name,
                'current_quantity': float(stock.quantity),
                'reorder_level': float(stock.low_stock_threshold),
                'unit_of_measure': getattr(stock.product, 'unit_of_measure', ''),
                'status': getattr(stock, 'status', ''),
                'timestamp': timezone.now().isoformat()
            }

            self._send_group_message(f"product_{stock.product.id}", 'low_stock_alert', alert_data)
            self._send_group_message(f"stock_store_{stock.store.id}", 'low_stock_alert', alert_data)

        except Stock.DoesNotExist:
            pass


# Global notifier instance
notifier = WebSocketNotifier()


# Convenience functions for calling notifier methods

def notify_dashboard_update(user_id: int, update_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    notifier.send_dashboard_update(user_id, {
        'type': update_type,
        'data': data or {},
        'timestamp': timezone.now().isoformat()
    })


def notify_stock_change(product_id: int, store_id: int, old_quantity: float, new_quantity: float) -> None:
    try:
        stock = Stock.objects.select_related('product', 'store').get(
            product_id=product_id,
            store_id=store_id
        )

        stock_data = {
            'product_id': product_id,
            'product_name': stock.product.name,
            'product_sku': stock.product.sku,
            'store_id': store_id,
            'store_name': stock.store.name,
            'old_quantity': float(old_quantity),
            'new_quantity': float(new_quantity),
            'unit_of_measure': getattr(stock.product, 'unit_of_measure', ''),
            'status': getattr(stock, 'status', ''),
            'timestamp': timezone.now().isoformat()
        }

        notifier.send_stock_update(product_id, store_id, stock_data)

        if stock.status in ['low_stock', 'out_of_stock']:
            notifier.send_low_stock_alert(stock.id)

    except Stock.DoesNotExist:
        pass


def notify_movement_created(movement_id: int) -> None:
    try:
        movement = StockMovement.objects.select_related(
            'product', 'store', 'created_by'
        ).get(id=movement_id)

        movement_data = {
            'id': movement.id,
            'product_id': movement.product.id,
            'product_name': movement.product.name,
            'product_sku': movement.product.sku,
            'store_id': movement.store.id,
            'store_name': movement.store.name,
            'movement_type': movement.movement_type,
            'movement_type_display': movement.get_movement_type_display(),
            'quantity': float(movement.quantity),
            'unit_of_measure': getattr(movement.product, 'unit_of_measure', ''),
            'reference': movement.reference or '',
            'notes': movement.notes or '',
            'created_at': movement.created_at.isoformat(),
            'created_by': movement.created_by.get_full_name() or movement.created_by.username
        }

        notifier.send_stock_movement(movement_id, movement_data)

    except StockMovement.DoesNotExist:
        pass


def notify_import_update(session_id: int, update_type: str, data: Optional[Dict[str, Any]] = None) -> None:
    try:
        session = ImportSession.objects.get(id=session_id)

        base_data = {
            'session_id': session_id,
            'status': session.status,
            'processed_rows': session.processed_rows,
            'total_rows': session.total_rows,
            'created_count': session.created_count,
            'updated_count': session.updated_count,
            'error_count': session.error_count,
            'success_rate': session.success_rate,
            'timestamp': timezone.now().isoformat()
        }

        if data:
            base_data.update(data)

        if update_type == 'progress':
            notifier.send_import_progress(session_id, base_data)
        elif update_type == 'complete':
            notifier.send_import_complete(session_id, base_data)
        elif update_type == 'error':
            notifier.send_import_error(session_id, base_data)

    except ImportSession.DoesNotExist:
        pass
