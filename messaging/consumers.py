from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.cache import cache
from django.utils import timezone
from django_tenants.utils import schema_context
import json
import logging

logger = logging.getLogger(__name__)


class MessagingConsumer(AsyncWebsocketConsumer):
    """
    Main WebSocket consumer for messaging

    TENANT-AWARE: All operations respect tenant boundaries
    Handles all real-time messaging features
    """

    async def connect(self):
        """
        Handle WebSocket connection

        TENANT-AWARE: Stores tenant schema for this connection
        """
        self.user = self.scope['user']

        print(f"DEBUG: User attempting connection: {self.user}")
        print(f"DEBUG: Is anonymous: {self.user.is_anonymous}")

        # Reject unauthenticated users
        if self.user.is_anonymous:
            print("DEBUG: Rejecting anonymous user")
            await self.close(code=4001)
            return

        # Check if user has active access
        has_access = await self.check_user_access()
        print(f"DEBUG: User has access: {has_access}")
        if not has_access:
            print("DEBUG: Rejecting due to no access")
            await self.close(code=4003)  # Forbidden - subscription expired
            return

        # Store tenant schema (from scope set by middleware)
        tenant = self.scope.get('tenant')
        print(f"DEBUG: Tenant from scope: {tenant}")

        self.schema_name = tenant.schema_name if tenant else 'public'
        print(f"DEBUG: Schema name set to: {self.schema_name}")

        # User's personal channel for notifications
        self.user_group = f'user_{self.user.id}'

        # Join user's personal group
        await self.channel_layer.group_add(
            self.user_group,
            self.channel_name
        )

        await self.accept()
        print(f"DEBUG: Connection accepted for user {self.user.id}")


        # Mark user as online
        await self.set_user_online(True)

        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'user_id': self.user.id,
            'timestamp': timezone.now().isoformat(),
            'tenant': self.schema_name
        }))

        # Send pending notifications
        await self.send_pending_notifications()

        logger.info(f"User {self.user.id} connected to messaging in tenant {self.schema_name}")

    async def disconnect(self, close_code):
        """
        Handle WebSocket disconnection
        """
        # Check if connection was fully established
        if not hasattr(self, 'schema_name'):
            # Connection was rejected before completion
            return

        # Mark user as offline
        await self.set_user_online(False)

        # Leave all groups
        if hasattr(self, 'user_group'):
            await self.channel_layer.group_discard(
                self.user_group,
                self.channel_name
            )

        # Leave all conversation groups
        conversations = await self.get_user_conversations()
        for conv_id in conversations:
            await self.channel_layer.group_discard(
                f'conversation_{conv_id}',
                self.channel_name
            )

        logger.info(f"User {self.user.id} disconnected from tenant {self.schema_name}")

    async def receive(self, text_data):
        """
        Handle incoming WebSocket messages

        TENANT-AWARE: All operations execute within tenant schema
        """
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            # Route to appropriate handler
            handlers = {
                'join_conversation': self.handle_join_conversation,
                'leave_conversation': self.handle_leave_conversation,
                'typing': self.handle_typing_indicator,
                'mark_read': self.handle_mark_read,
                'reaction': self.handle_reaction,
                'delete_message': self.handle_delete_message,
                'pin_message': self.handle_pin_message,
            }

            handler = handlers.get(message_type)
            if handler:
                await handler(data)
            else:
                await self.send_error(f'Unknown message type: {message_type}')

        except json.JSONDecodeError:
            await self.send_error('Invalid JSON')
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")
            await self.send_error(f'Error processing message: {str(e)}')

    # ========== Handler Methods ==========

    async def handle_join_conversation(self, data):
        """
        Join a conversation group to receive real-time updates

        TENANT-AWARE: Verifies access within tenant
        """
        conversation_id = data.get('conversation_id')

        # Verify access
        has_access = await self.verify_conversation_access(conversation_id)
        if not has_access:
            await self.send_error('Access denied to conversation')
            return

        # Join conversation group
        conversation_group = f'conversation_{conversation_id}'
        await self.channel_layer.group_add(
            conversation_group,
            self.channel_name
        )

        # Send confirmation
        await self.send(text_data=json.dumps({
            'type': 'joined_conversation',
            'conversation_id': conversation_id
        }))

        # Notify others user joined
        await self.channel_layer.group_send(
            conversation_group,
            {
                'type': 'user_joined',
                'user_id': self.user.id,
                'username': self.user.username,
                'full_name': self.user.get_full_name() or self.user.username,
                'conversation_id': conversation_id
            }
        )

        logger.debug(f"User {self.user.id} joined conversation {conversation_id}")

    async def handle_leave_conversation(self, data):
        """
        Leave a conversation group
        """
        conversation_id = data.get('conversation_id')
        conversation_group = f'conversation_{conversation_id}'

        await self.channel_layer.group_discard(
            conversation_group,
            self.channel_name
        )

        # Notify others
        await self.channel_layer.group_send(
            conversation_group,
            {
                'type': 'user_left',
                'user_id': self.user.id,
                'username': self.user.username,
                'conversation_id': conversation_id
            }
        )

        logger.debug(f"User {self.user.id} left conversation {conversation_id}")

    async def handle_typing_indicator(self, data):
        """
        Handle typing indicator

        Uses Redis cache with TTL for ephemeral state
        """
        conversation_id = data.get('conversation_id')
        is_typing = data.get('is_typing', False)

        # Verify access
        has_access = await self.verify_conversation_access(conversation_id)
        if not has_access:
            return

        # Store in Redis with TTL
        cache_key = f'typing_{self.schema_name}_{conversation_id}_{self.user.id}'
        if is_typing:
            cache.set(cache_key, True, 5)  # 5 seconds TTL
        else:
            cache.delete(cache_key)

        # Broadcast to conversation
        await self.channel_layer.group_send(
            f'conversation_{conversation_id}',
            {
                'type': 'typing_indicator',
                'user_id': self.user.id,
                'username': self.user.username,
                'full_name': self.user.get_full_name() or self.user.username,
                'is_typing': is_typing,
                'conversation_id': conversation_id
            }
        )

    async def handle_mark_read(self, data):
        """
        Mark messages as read

        TENANT-AWARE: Creates read receipts in correct tenant
        """
        conversation_id = data.get('conversation_id')
        message_ids = data.get('message_ids', [])

        # Create read receipts
        created_count = await self.create_read_receipts(conversation_id, message_ids)

        # Broadcast read receipts
        await self.channel_layer.group_send(
            f'conversation_{conversation_id}',
            {
                'type': 'read_receipts',
                'user_id': self.user.id,
                'username': self.user.username,
                'message_ids': message_ids,
                'conversation_id': conversation_id
            }
        )

        # Update last_read_at
        await self.update_last_read(conversation_id)

        logger.debug(f"User {self.user.id} marked {created_count} messages as read")

    async def handle_reaction(self, data):
        """
        Handle emoji reaction
        """
        message_id = data.get('message_id')
        emoji = data.get('emoji')
        action = data.get('action', 'add')  # add or remove

        conversation_id = await self.get_message_conversation(message_id)
        if not conversation_id:
            await self.send_error('Message not found')
            return

        # Verify access
        has_access = await self.verify_conversation_access(conversation_id)
        if not has_access:
            return

        # Add or remove reaction
        if action == 'add':
            await self.add_reaction(message_id, emoji)
        else:
            await self.remove_reaction(message_id, emoji)

        # Broadcast to conversation
        await self.channel_layer.group_send(
            f'conversation_{conversation_id}',
            {
                'type': 'message_reaction',
                'message_id': message_id,
                'user_id': self.user.id,
                'username': self.user.username,
                'emoji': emoji,
                'action': action
            }
        )

    async def handle_delete_message(self, data):
        """
        Handle message deletion (admin/sender only)
        """
        message_id = data.get('message_id')

        # Check if user can delete
        can_delete = await self.can_delete_message(message_id)
        if not can_delete:
            await self.send_error('Permission denied')
            return

        conversation_id = await self.delete_message(message_id)

        # Broadcast deletion
        await self.channel_layer.group_send(
            f'conversation_{conversation_id}',
            {
                'type': 'message_deleted',
                'message_id': message_id,
                'deleted_by': self.user.id,
                'deleted_by_username': self.user.username
            }
        )

        logger.info(f"User {self.user.id} deleted message {message_id}")

    async def handle_pin_message(self, data):
        """
        Handle message pinning (admin only)
        """
        message_id = data.get('message_id')

        # Check if user is admin
        can_pin = await self.can_pin_message(message_id)
        if not can_pin:
            await self.send_error('Only admins can pin messages')
            return

        conversation_id, is_pinned = await self.toggle_pin_message(message_id)

        # Broadcast pin status
        await self.channel_layer.group_send(
            f'conversation_{conversation_id}',
            {
                'type': 'message_pinned',
                'message_id': message_id,
                'is_pinned': is_pinned,
                'pinned_by': self.user.id,
                'pinned_by_username': self.user.username
            }
        )

    # ========== Broadcast Handlers ==========

    async def new_message(self, event):
        """
        Send new message to client
        """
        await self.send(text_data=json.dumps({
            'type': 'new_message',
            'message': event['message'],
            'conversation_id': event['conversation_id']
        }))

    async def typing_indicator(self, event):
        """
        Send typing indicator to client
        """
        # Don't send own typing indicator back
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type': 'typing',
                'user_id': event['user_id'],
                'username': event['username'],
                'full_name': event['full_name'],
                'is_typing': event['is_typing'],
                'conversation_id': event['conversation_id']
            }))

    async def read_receipts(self, event):
        """
        Send read receipt update to client
        """
        await self.send(text_data=json.dumps({
            'type': 'read_receipt',
            'user_id': event['user_id'],
            'username': event['username'],
            'message_ids': event['message_ids'],
            'conversation_id': event['conversation_id']
        }))

    async def message_reaction(self, event):
        """
        Send reaction update to client
        """
        await self.send(text_data=json.dumps({
            'type': 'reaction',
            'message_id': event['message_id'],
            'user_id': event['user_id'],
            'username': event['username'],
            'emoji': event['emoji'],
            'action': event['action']
        }))

    async def message_deleted(self, event):
        """
        Send message deletion notification
        """
        await self.send(text_data=json.dumps({
            'type': 'message_deleted',
            'message_id': event['message_id'],
            'deleted_by': event['deleted_by'],
            'deleted_by_username': event['deleted_by_username']
        }))

    async def message_pinned(self, event):
        """
        Send message pinned notification
        """
        await self.send(text_data=json.dumps({
            'type': 'message_pinned',
            'message_id': event['message_id'],
            'is_pinned': event['is_pinned'],
            'pinned_by': event['pinned_by'],
            'pinned_by_username': event['pinned_by_username']
        }))

    async def user_joined(self, event):
        """
        Notify when user joins conversation
        """
        if event['user_id'] != self.user.id:
            await self.send(text_data=json.dumps({
                'type': 'user_joined',
                'user_id': event['user_id'],
                'username': event['username'],
                'full_name': event['full_name'],
                'conversation_id': event['conversation_id']
            }))

    async def user_left(self, event):
        """
        Notify when user leaves conversation
        """
        await self.send(text_data=json.dumps({
            'type': 'user_left',
            'user_id': event['user_id'],
            'username': event['username'],
            'conversation_id': event['conversation_id']
        }))

    async def notification(self, event):
        """
        Send notification to user
        """
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'notification_type': event['notification_type'],
            'title': event['title'],
            'body': event['body'],
            'data': event.get('data', {})
        }))

    # ========== Helper Methods (Database Operations) ==========

    async def send_error(self, message):
        """Send error message to client"""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'message': message
        }))

    @database_sync_to_async
    def check_user_access(self):
        """
        Check if user has active access to the system

        TENANT-AWARE: Checks company subscription status
        """
        if not self.user.is_active:
            return False

        # SaaS admins always have access
        if getattr(self.user, 'is_saas_admin', False):
            return True

        # Check company access
        if hasattr(self.user, 'company') and self.user.company:
            return self.user.company.has_active_access

        return True

    @database_sync_to_async
    def verify_conversation_access(self, conversation_id):
        """
        Verify user has access to conversation

        TENANT-AWARE: Checks within tenant schema
        """
        from .models import ConversationParticipant

        # SaaS admins can access any conversation
        if getattr(self.user, 'is_saas_admin', False):
            return True

        with schema_context(self.schema_name):
            return ConversationParticipant.objects.filter(
                conversation_id=conversation_id,
                user=self.user,
                is_active=True
            ).exists()

    @database_sync_to_async
    def get_user_conversations(self):
        """Get list of conversation IDs user is in"""
        from .models import ConversationParticipant

        with schema_context(self.schema_name):
            return list(
                ConversationParticipant.objects.filter(
                    user=self.user,
                    is_active=True
                ).values_list('conversation_id', flat=True)
            )

    @database_sync_to_async
    def create_read_receipts(self, conversation_id, message_ids):
        """Create read receipts for messages"""
        from .models import Message, MessageReadReceipt

        with schema_context(self.schema_name):
            messages = Message.objects.filter(
                id__in=message_ids,
                conversation_id=conversation_id,
                is_deleted=False
            ).exclude(sender=self.user)

            receipts = [
                MessageReadReceipt(message=msg, user=self.user)
                for msg in messages
            ]

            MessageReadReceipt.objects.bulk_create(
                receipts,
                ignore_conflicts=True
            )

            return len(receipts)

    @database_sync_to_async
    def update_last_read(self, conversation_id):
        """Update participant's last_read_at timestamp"""
        from .models import ConversationParticipant

        with schema_context(self.schema_name):
            ConversationParticipant.objects.filter(
                conversation_id=conversation_id,
                user=self.user
            ).update(last_read_at=timezone.now())

    @database_sync_to_async
    def get_message_conversation(self, message_id):
        """Get conversation ID for a message"""
        from .models import Message

        with schema_context(self.schema_name):
            try:
                message = Message.objects.get(id=message_id)
                return message.conversation_id
            except Message.DoesNotExist:
                return None

    @database_sync_to_async
    def add_reaction(self, message_id, emoji):
        """Add emoji reaction to message"""
        from .models import MessageReaction

        with schema_context(self.schema_name):
            MessageReaction.objects.get_or_create(
                message_id=message_id,
                user=self.user,
                emoji=emoji
            )

    @database_sync_to_async
    def remove_reaction(self, message_id, emoji):
        """Remove emoji reaction from message"""
        from .models import MessageReaction

        with schema_context(self.schema_name):
            MessageReaction.objects.filter(
                message_id=message_id,
                user=self.user,
                emoji=emoji
            ).delete()

    @database_sync_to_async
    def can_delete_message(self, message_id):
        """Check if user can delete message"""
        from .models import Message, ConversationParticipant

        with schema_context(self.schema_name):
            # SaaS/Super admins can delete anything
            if getattr(self.user, 'is_saas_admin', False) or self.user.is_superuser:
                return True

            try:
                message = Message.objects.get(id=message_id)

                # Sender can delete their own messages
                if message.sender == self.user:
                    return True

                # Check if user is conversation admin
                is_admin = ConversationParticipant.objects.filter(
                    conversation=message.conversation,
                    user=self.user,
                    is_admin=True,
                    is_active=True
                ).exists()

                return is_admin
            except Message.DoesNotExist:
                return False

    @database_sync_to_async
    def delete_message(self, message_id):
        """Soft delete message"""
        from .models import Message

        with schema_context(self.schema_name):
            message = Message.objects.get(id=message_id)
            message.is_deleted = True
            message.deleted_at = timezone.now()
            message.deleted_by = self.user
            message.save()
            return message.conversation_id

    @database_sync_to_async
    def can_pin_message(self, message_id):
        """Check if user can pin message"""
        from .models import Message, ConversationParticipant

        with schema_context(self.schema_name):
            # SaaS/Super admins can pin anything
            if getattr(self.user, 'is_saas_admin', False) or self.user.is_superuser:
                return True

            try:
                message = Message.objects.get(id=message_id)

                # Check if user is conversation admin
                is_admin = ConversationParticipant.objects.filter(
                    conversation=message.conversation,
                    user=self.user,
                    is_admin=True,
                    is_active=True
                ).exists()

                return is_admin
            except Message.DoesNotExist:
                return False

    @database_sync_to_async
    def toggle_pin_message(self, message_id):
        """Toggle message pin status"""
        from .models import Message

        with schema_context(self.schema_name):
            message = Message.objects.get(id=message_id)

            if message.is_pinned:
                message.is_pinned = False
                message.pinned_at = None
                message.pinned_by = None
            else:
                message.is_pinned = True
                message.pinned_at = timezone.now()
                message.pinned_by = self.user

            message.save()
            return message.conversation_id, message.is_pinned

    @database_sync_to_async
    def set_user_online(self, is_online):
        """Set user online status in cache"""
        # Guard against missing schema_name
        if not hasattr(self, 'schema_name'):
            return

        cache_key = f'user_online_{self.schema_name}_{self.user.id}'
        if is_online:
            cache.set(cache_key, True, 300)  # 5 minutes TTL
        else:
            cache.delete(cache_key)

    async def send_pending_notifications(self):
        """Send any pending notifications to user"""
        notifications = await self.get_pending_notifications()

        for notification in notifications:
            await self.send(text_data=json.dumps({
                'type': 'notification',
                'notification_type': notification['type'],
                'title': notification['title'],
                'body': notification['body'],
                'data': notification.get('data', {})
            }))

    @database_sync_to_async
    def get_pending_notifications(self):
        """Get pending notifications for user"""
        # Integrate with your notification system
        # For now, return empty list
        return []

    async def system_announcement(self, event):
        await self.send(text_data=json.dumps({
            'type': 'system_announcement',
            'announcement': event['announcement']
        }))


