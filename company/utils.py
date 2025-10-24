from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.utils import timezone


class WebSocketUtils:
    """Utility class for WebSocket operations"""

    def __init__(self):
        self.channel_layer = get_channel_layer()

    def send_company_notification(self, company_id, notification_type, message, data=None):
        """Send notification to company dashboard"""
        try:
            async_to_sync(self.channel_layer.group_send)(
                f'company_dashboard_{company_id}',
                {
                    'type': 'dashboard_update',
                    'data': {
                        'notification_type': notification_type,
                        'message': message,
                        'data': data or {},
                        'timestamp': timezone.now().isoformat()
                    }
                }
            )
        except Exception as e:
            print(f"Error sending company notification: {e}")

    def send_branch_update(self, branch_id, update_type, data):
        """Send update to branch analytics consumers"""
        try:
            async_to_sync(self.channel_layer.group_send)(
                f'branch_analytics_{branch_id}',
                {
                    'type': 'analytics_update',
                    'data': {
                        'update_type': update_type,
                        'data': data,
                        'timestamp': timezone.now().isoformat()
                    }
                }
            )
        except Exception as e:
            print(f"Error sending branch update: {e}")

    def broadcast_system_alert(self, company_id, alert_level, message):
        """Broadcast system-wide alerts"""
        try:
            async_to_sync(self.channel_layer.group_send)(
                f'company_dashboard_{company_id}',
                {
                    'type': 'alert_notification',
                    'alert_type': 'system',
                    'alert_level': alert_level,
                    'message': message,
                    'timestamp': timezone.now().isoformat()
                }
            )
        except Exception as e:
            print(f"Error broadcasting system alert: {e}")
