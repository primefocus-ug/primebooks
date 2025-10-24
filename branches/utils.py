from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import json


class WebSocketNotifier:
    """Utility class for sending WebSocket notifications."""

    def __init__(self):
        self.channel_layer = get_channel_layer()

    def send_branch_update(self, branch_id, data, update_type='branch_update'):
        """Send update to branch analytics group."""
        if not self.channel_layer:
            return

        try:
            async_to_sync(self.channel_layer.group_send)(
                f'branch_analytics_{branch_id}',
                {
                    'type': update_type,
                    'data': data
                }
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Branch WebSocket notification failed: {e}')

    def send_store_update(self, store_id, data, update_type='store_update'):
        """Send update to store analytics group."""
        if not self.channel_layer:
            return

        try:
            async_to_sync(self.channel_layer.group_send)(
                f'store_analytics_{store_id}',
                {
                    'type': update_type,
                    'data': data
                }
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Store WebSocket notification failed: {e}')

    def send_performance_alert(self, branch_id, alert_data, severity='info'):
        """Send performance alert to branch."""
        if not self.channel_layer:
            return

        try:
            async_to_sync(self.channel_layer.group_send)(
                f'branch_analytics_{branch_id}',
                {
                    'type': 'performance_alert',
                    'data': alert_data,
                    'severity': severity
                }
            )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f'Performance alert WebSocket failed: {e}')


# Singleton instance
websocket_notifier = WebSocketNotifier()
