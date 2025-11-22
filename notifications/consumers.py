import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from django_tenants.utils import schema_context
import logging

logger = logging.getLogger(__name__)


class NotificationConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time notifications with tenant support
    """

    async def connect(self):
        """Connect to WebSocket with tenant context"""
        try:
            self.user = self.scope['user']

            # Only authenticated users can connect
            if not self.user.is_authenticated:
                await self.close()
                return

            # Get tenant schema from scope or user
            self.schema_name = await self.get_tenant_schema()
            if not self.schema_name:
                logger.error(f"Could not determine tenant schema for user {self.user.id}")
                await self.close()
                return

            # Join notification group for this user (schema-aware)
            self.group_name = f'notifications_{self.schema_name}_{self.user.id}'

            await self.channel_layer.group_add(
                self.group_name,
                self.channel_name
            )

            await self.accept()

            # Send initial unread count within tenant schema
            unread_count = await self.get_unread_count()
            await self.send(text_data=json.dumps({
                'type': 'unread_count',
                'count': unread_count,
                'schema_name': self.schema_name
            }))

            logger.info(f"WebSocket connected for user {self.user.id} in tenant {self.schema_name}")

        except Exception as e:
            logger.error(f"WebSocket connection error: {e}", exc_info=True)
            await self.close()

    async def disconnect(self, close_code):
        """Disconnect from WebSocket"""
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(
                self.group_name,
                self.channel_name
            )
            logger.info(f"WebSocket disconnected for user {self.user.id}")

    @database_sync_to_async
    def get_tenant_schema(self):
        """Get tenant schema name from various sources"""
        try:
            # Priority 1: Get schema from scope (set by middleware)
            if 'tenant' in self.scope and self.scope['tenant']:
                return self.scope['tenant'].schema_name

            # Priority 2: Get from user if user has tenant relationship
            if hasattr(self.user, 'tenant') and self.user.tenant:
                return self.user.tenant.schema_name

            # Priority 3: Get from user's company/profile
            if hasattr(self.user, 'company') and self.user.company:
                return self.user.company.schema_name

            if hasattr(self.user, 'staff_profile') and self.user.staff_profile:
                if hasattr(self.user.staff_profile, 'company'):
                    return self.user.staff_profile.company.schema_name

            # Priority 4: Get from session
            session = self.scope.get('session', {})
            if 'schema_name' in session:
                return session['schema_name']

            # Priority 5: Get from URL/headers if available
            headers = dict(self.scope.get('headers', []))
            tenant_header = headers.get(b'x-tenant-schema', b'').decode('utf-8')
            if tenant_header:
                return tenant_header

            logger.warning(f"Could not determine tenant schema for user {self.user.id}")
            return None

        except Exception as e:
            logger.error(f"Error getting tenant schema: {e}", exc_info=True)
            return None

    async def receive(self, text_data):
        """Receive message from WebSocket"""
        try:
            data = json.loads(text_data)
            action = data.get('action')

            if action == 'mark_as_read':
                notification_id = data.get('notification_id')
                success = await self.mark_notification_as_read(notification_id)

                if success:
                    # Send updated unread count
                    unread_count = await self.get_unread_count()
                    await self.send(text_data=json.dumps({
                        'type': 'unread_count',
                        'count': unread_count
                    }))
                    await self.send(text_data=json.dumps({
                        'type': 'marked_as_read',
                        'notification_id': notification_id,
                        'success': True
                    }))
                else:
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'Failed to mark notification as read'
                    }))

            elif action == 'mark_all_as_read':
                count = await self.mark_all_as_read()
                await self.send(text_data=json.dumps({
                    'type': 'marked_all_as_read',
                    'count': count,
                    'success': True
                }))

                # Send updated unread count
                unread_count = await self.get_unread_count()
                await self.send(text_data=json.dumps({
                    'type': 'unread_count',
                    'count': unread_count
                }))

            elif action == 'dismiss':
                notification_id = data.get('notification_id')
                success = await self.dismiss_notification(notification_id)

                if success:
                    await self.send(text_data=json.dumps({
                        'type': 'dismissed',
                        'notification_id': notification_id,
                        'success': True
                    }))

                    # Send updated unread count
                    unread_count = await self.get_unread_count()
                    await self.send(text_data=json.dumps({
                        'type': 'unread_count',
                        'count': unread_count
                    }))
                else:
                    await self.send(text_data=json.dumps({
                        'type': 'error',
                        'message': 'Failed to dismiss notification'
                    }))

            elif action == 'get_unread_count':
                unread_count = await self.get_unread_count()
                await self.send(text_data=json.dumps({
                    'type': 'unread_count',
                    'count': unread_count
                }))

            elif action == 'ping':
                # Heartbeat to keep connection alive
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': timezone.now().isoformat()
                }))

            else:
                await self.send(text_data=json.dumps({
                    'type': 'error',
                    'message': f'Unknown action: {action}'
                }))

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON'
            }))
        except Exception as e:
            logger.error(f"Error in receive: {e}", exc_info=True)
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': str(e)
            }))

    async def notification_message(self, event):
        """Receive notification from group"""
        try:
            notification = event['notification']

            # Send notification to WebSocket
            await self.send(text_data=json.dumps({
                'type': 'new_notification',
                'notification': notification
            }))

            # Send updated unread count
            unread_count = await self.get_unread_count()
            await self.send(text_data=json.dumps({
                'type': 'unread_count',
                'count': unread_count
            }))

        except Exception as e:
            logger.error(f"Error in notification_message: {e}", exc_info=True)

    @database_sync_to_async
    def get_unread_count(self):
        """Get unread notification count within tenant schema"""
        from .models import Notification

        try:
            with schema_context(self.schema_name):
                return Notification.objects.filter(
                    recipient=self.user,
                    is_read=False,
                    is_dismissed=False
                ).count()
        except Exception as e:
            logger.error(f"Error getting unread count: {e}", exc_info=True)
            return 0

    @database_sync_to_async
    def mark_notification_as_read(self, notification_id):
        """Mark notification as read within tenant schema"""
        from .models import Notification

        try:
            with schema_context(self.schema_name):
                notification = Notification.objects.get(
                    id=notification_id,
                    recipient=self.user
                )
                notification.mark_as_read()
                return True
        except Notification.DoesNotExist:
            logger.warning(f"Notification {notification_id} not found for user {self.user.id}")
            return False
        except Exception as e:
            logger.error(f"Error marking notification as read: {e}", exc_info=True)
            return False

    @database_sync_to_async
    def mark_all_as_read(self):
        """Mark all notifications as read within tenant schema"""
        from .models import Notification

        try:
            with schema_context(self.schema_name):
                count = Notification.objects.filter(
                    recipient=self.user,
                    is_read=False
                ).update(
                    is_read=True,
                    read_at=timezone.now()
                )
                return count
        except Exception as e:
            logger.error(f"Error marking all as read: {e}", exc_info=True)
            return 0

    @database_sync_to_async
    def dismiss_notification(self, notification_id):
        """Dismiss notification within tenant schema"""
        from .models import Notification

        try:
            with schema_context(self.schema_name):
                notification = Notification.objects.get(
                    id=notification_id,
                    recipient=self.user
                )
                notification.dismiss()
                return True
        except Notification.DoesNotExist:
            logger.warning(f"Notification {notification_id} not found for user {self.user.id}")
            return False
        except Exception as e:
            logger.error(f"Error dismissing notification: {e}", exc_info=True)
            return False