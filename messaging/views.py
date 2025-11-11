from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser
from django.db.models import Q, Count, Max, Prefetch, F
from django.utils import timezone
from django.core.files.base import ContentFile
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.http import HttpResponse
import os
import json
from django.contrib.auth import get_user_model
import logging
from django.middleware.csrf import get_token
from django.views.decorators.csrf import ensure_csrf_cookie
from django.utils.decorators import method_decorator

from .models import (
    Conversation, ConversationParticipant, Message,
    MessageAttachment, MessageReaction, EncryptionKeyManager
)
from .serializers import (
    ConversationSerializer, MessageSerializer, CreateConversationSerializer,
    CreateMessageSerializer, AddParticipantSerializer, SearchMessagesSerializer,
    ConversationParticipantSerializer, UserSearchSerializer
)
from .services import EncryptionService, MessageIntegrityService, TenantMessagingService
from .permissions import IsConversationParticipant, CanDeleteMessage, CanModifyConversation

User = get_user_model()
logger = logging.getLogger(__name__)

@method_decorator(ensure_csrf_cookie, name='dispatch')
class ConversationViewSet(viewsets.ModelViewSet):
    serializer_class = ConversationSerializer
    permission_classes = [IsAuthenticated]

    def list(self, request, *args, **kwargs):
        # Ensure CSRF token is sent
        get_token(request)
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        from django.db import models
        user = self.request.user

        # Base queryset - user's conversations in this tenant
        queryset = Conversation.objects.filter(
            participants__user=user,
            participants__is_active=True,
            is_active=True
        ).select_related(
            'created_by'
        ).prefetch_related(
            'participants__user'
        ).annotate(
            last_message_at=Max('messages__created_at')
        ).distinct().order_by('-last_message_at')

        # Filter by archived status
        include_archived = self.request.query_params.get('archived', 'false').lower() == 'true'
        if not include_archived:
            queryset = queryset.filter(archived_at__isnull=True)

        # Filter by type
        conv_type = self.request.query_params.get('type')
        if conv_type:
            queryset = queryset.filter(conversation_type=conv_type)

        # Search by name or participant
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(participants__user__username__icontains=search) |
                Q(participants__user__first_name__icontains=search) |
                Q(participants__user__last_name__icontains=search)
            ).distinct()

        return queryset

    def create(self, request):
        """
        Create new conversation

        TENANT-AWARE: Creates conversation in current tenant
        CROSS-TENANT: Only SaaS admins can create cross-tenant conversations

        Body:
        {
            "conversation_type": "direct|group|channel|department|broadcast",
            "name": "Optional for group/channel/department",
            "description": "Optional",
            "participant_ids": [1, 2, 3],
            "is_cross_tenant": false  // SaaS admin only
        }
        """
        serializer = CreateConversationSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        # Check cross-tenant permission
        is_cross_tenant = serializer.validated_data.get('is_cross_tenant', False)
        if is_cross_tenant and not TenantMessagingService.can_create_cross_tenant_conversation(request.user):
            return Response(
                {'error': 'Only SaaS administrators can create cross-tenant conversations'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            # Create conversation
            conversation = Conversation.objects.create(
                conversation_type=serializer.validated_data['conversation_type'],
                name=serializer.validated_data.get('name', ''),
                description=serializer.validated_data.get('description', ''),
                created_by=request.user,
                is_cross_tenant=is_cross_tenant
            )

            # Get all participants (including creator)
            participant_ids = serializer.validated_data['participant_ids']
            participants = list(
                User.objects.filter(id__in=participant_ids, is_active=True)
            )

            # Add creator if not in list
            if request.user not in participants:
                participants.append(request.user)

            # Initialize encryption keys
            EncryptionService.create_conversation_with_keys(
                conversation,
                participants
            )

            # Create participant records
            participant_records = []
            encrypted_keys = json.loads(conversation.encrypted_symmetric_key)

            for user in participants:
                encrypted_key = encrypted_keys[str(user.id)]

                is_creator = (user == request.user)
                participant_records.append(
                    ConversationParticipant(
                        conversation=conversation,
                        user=user,
                        encrypted_conversation_key=encrypted_key,
                        is_admin=is_creator,
                        can_add_participants=is_creator,
                        can_remove_participants=is_creator
                    )
                )

            ConversationParticipant.objects.bulk_create(participant_records)

            # Notify participants via WebSocket
            channel_layer = get_channel_layer()
            for participant in participants:
                if participant != request.user:
                    async_to_sync(channel_layer.group_send)(
                        f'user_{participant.id}',
                        {
                            'type': 'notification',
                            'notification_type': 'new_conversation',
                            'title': 'New Conversation',
                            'body': f'{request.user.get_full_name() or request.user.username} added you to a conversation',
                            'data': {'conversation_id': conversation.id}
                        }
                    )

            logger.info(f"User {request.user.id} created conversation {conversation.id}")

            return Response(
                ConversationSerializer(conversation, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.error(f"Error creating conversation: {e}")
            return Response(
                {'error': 'Failed to create conversation'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=True, methods=['post'])
    def add_participants(self, request, pk=None):
        """
        Add participants to conversation

        Requires: can_add_participants permission

        Body:
        {
            "user_ids": [4, 5],
            "can_send_messages": true,
            "is_admin": false
        }
        """
        conversation = self.get_object()

        # Check permission
        participant = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user,
            can_add_participants=True,
            is_active=True
        ).first()

        if not participant:
            return Response(
                {'error': 'You do not have permission to add participants'},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = AddParticipantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get users (only active users in current tenant)
        users = User.objects.filter(
            id__in=serializer.validated_data['user_ids'],
            is_active=True
        )

        # For non-SaaS admins, ensure users are in same company
        if not getattr(request.user, 'is_saas_admin', False):
            users = users.filter(company=request.user.company)

        added_users = []
        for user in users:
            # Check if already participant
            if ConversationParticipant.objects.filter(
                    conversation=conversation,
                    user=user
            ).exists():
                continue

            # Add encryption key for user
            encrypted_key = EncryptionService.add_participant_keys(
                conversation,
                user
            )

            # Create participant record
            ConversationParticipant.objects.create(
                conversation=conversation,
                user=user,
                encrypted_conversation_key=encrypted_key,
                can_send_messages=serializer.validated_data['can_send_messages'],
                is_admin=serializer.validated_data['is_admin']
            )

            added_users.append(user)

            # Notify user
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'user_{user.id}',
                {
                    'type': 'notification',
                    'notification_type': 'added_to_conversation',
                    'title': 'Added to Conversation',
                    'body': f'{request.user.get_full_name() or request.user.username} added you to {conversation.name or "a conversation"}',
                    'data': {'conversation_id': conversation.id}
                }
            )

        logger.info(f"Added {len(added_users)} participants to conversation {conversation.id}")

        return Response({
            'message': f'Added {len(added_users)} participant(s)',
            'added_users': [u.id for u in added_users],
            'conversation': ConversationSerializer(
                conversation,
                context={'request': request}
            ).data
        })

    @action(detail=True, methods=['post'])
    def remove_participant(self, request, pk=None):
        """
        Remove participant from conversation

        Requires: can_remove_participants permission

        Body:
        {
            "user_id": 4
        }
        """
        conversation = self.get_object()
        user_id = request.data.get('user_id')

        if not user_id:
            return Response(
                {'error': 'user_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check permission
        requester = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user,
            can_remove_participants=True,
            is_active=True
        ).first()

        if not requester:
            return Response(
                {'error': 'You do not have permission to remove participants'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Can't remove yourself using this endpoint
        if int(user_id) == request.user.id:
            return Response(
                {'error': 'Use the leave endpoint to remove yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Remove participant (soft delete)
        removed_count = ConversationParticipant.objects.filter(
            conversation=conversation,
            user_id=user_id
        ).update(
            is_active=False,
            left_at=timezone.now()
        )

        if removed_count > 0:
            logger.info(f"User {request.user.id} removed user {user_id} from conversation {conversation.id}")

            # Notify removed user
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'user_{user_id}',
                {
                    'type': 'notification',
                    'notification_type': 'removed_from_conversation',
                    'title': 'Removed from Conversation',
                    'body': f'You were removed from {conversation.name or "a conversation"}',
                    'data': {'conversation_id': conversation.id}
                }
            )

        return Response({'message': 'Participant removed successfully'})

    @action(detail=True, methods=['post'])
    def leave(self, request, pk=None):
        """
        Leave conversation
        """
        conversation = self.get_object()

        ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user
        ).update(
            is_active=False,
            left_at=timezone.now()
        )

        logger.info(f"User {request.user.id} left conversation {conversation.id}")

        return Response({'message': 'Successfully left conversation'})

    @action(detail=True, methods=['post'])
    def archive(self, request, pk=None):
        """
        Archive conversation (admin only)
        """
        conversation = self.get_object()

        # Check if user is admin
        is_admin = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user,
            is_admin=True,
            is_active=True
        ).exists()

        if not is_admin and not request.user.is_superuser:
            return Response(
                {'error': 'Only admins can archive conversations'},
                status=status.HTTP_403_FORBIDDEN
            )

        conversation.archived_at = timezone.now()
        conversation.save()

        logger.info(f"User {request.user.id} archived conversation {conversation.id}")

        return Response({'message': 'Conversation archived successfully'})

    @action(detail=True, methods=['post'])
    def unarchive(self, request, pk=None):
        """
        Unarchive conversation (admin only)
        """
        conversation = self.get_object()

        # Check if user is admin
        is_admin = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user,
            is_admin=True,
            is_active=True
        ).exists()

        if not is_admin and not request.user.is_superuser:
            return Response(
                {'error': 'Only admins can unarchive conversations'},
                status=status.HTTP_403_FORBIDDEN
            )

        conversation.archived_at = None
        conversation.save()

        logger.info(f"User {request.user.id} unarchived conversation {conversation.id}")

        return Response({'message': 'Conversation unarchived successfully'})

    @action(detail=True, methods=['get'])
    def participants(self, request, pk=None):
        """
        Get all participants in conversation
        """
        conversation = self.get_object()

        participants = ConversationParticipant.objects.filter(
            conversation=conversation,
            is_active=True
        ).select_related('user')

        serializer = ConversationParticipantSerializer(
            participants,
            many=True,
            context={'request': request}
        )

        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def search_users(self, request):
        """
        Search users to add to conversations

        TENANT-AWARE: Only searches users in current tenant

        Query params:
        - q: Search term
        - limit: Max results (default 20)
        """
        search_term = request.query_params.get('q', '')
        limit = int(request.query_params.get('limit', 20))

        if len(search_term) < 2:
            return Response([])

        users = TenantMessagingService.search_users_for_conversation(
            search_term,
            request.user,
            limit
        )

        serializer = UserSearchSerializer(users, many=True)
        return Response(serializer.data)

@method_decorator(ensure_csrf_cookie, name='dispatch')
class MessageViewSet(viewsets.ModelViewSet):
    serializer_class = MessageSerializer
    permission_classes = [IsAuthenticated]  # Remove IsConversationParticipant from here
    parser_classes = [MultiPartParser, FormParser]

    def list(self, request, *args, **kwargs):
        # Ensure CSRF token is sent
        get_token(request)
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        conversation_id = self.request.query_params.get('conversation_id')

        if not conversation_id:
            return Message.objects.none()

        # Verify user has access to conversation
        has_access = ConversationParticipant.objects.filter(
            conversation_id=conversation_id,
            user=self.request.user,
            is_active=True
        ).exists()

        if not has_access:
            return Message.objects.none()

        queryset = Message.objects.filter(
            conversation_id=conversation_id,
            is_deleted=False
        ).select_related(
            'sender',
            'reply_to__sender'
        ).prefetch_related(
            'attachments',
            'reactions__user',
            'read_receipts__user',
            'mentioned_users'
        ).order_by('-created_at')

        # Pagination
        limit = int(self.request.query_params.get('limit', 50))
        before = self.request.query_params.get('before')
        after = self.request.query_params.get('after')

        if before:
            queryset = queryset.filter(id__lt=before)
        elif after:
            queryset = queryset.filter(id__gt=after)

        return queryset[:limit]

    def list(self, request):
        """
        Get messages with decryption
        """
        conversation_id = request.query_params.get('conversation_id')
        if not conversation_id:
            return Response(
                {'error': 'conversation_id required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get conversation key
        try:
            conversation = Conversation.objects.get(id=conversation_id)
            conversation_key = EncryptionService.get_conversation_key(
                conversation,
                request.user
            )

            # Attach key to request for serializer
            request.conversation_key = conversation_key

        except (Conversation.DoesNotExist, PermissionError) as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_403_FORBIDDEN
            )

        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)

        return Response(serializer.data)

    def create(self, request):
        """
        Send new message

        Body (multipart/form-data):
        {
            "conversation_id": 1,
            "content": "Message text",
            "reply_to": 123,  // Optional
            "mentioned_user_ids": [1, 2],  // Optional
            "attachments": [file1, file2]  // Optional
        }
        """
        serializer = CreateMessageSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)

        conversation_id = serializer.validated_data['conversation_id']
        content = serializer.validated_data['content']
        reply_to_id = serializer.validated_data.get('reply_to')
        mentioned_user_ids = serializer.validated_data.get('mentioned_user_ids', [])

        try:
            # Get conversation and verify access
            conversation = Conversation.objects.get(id=conversation_id, is_active=True)

            # Check if user can send messages
            participant = ConversationParticipant.objects.filter(
                conversation=conversation,
                user=request.user,
                is_active=True
            ).first()

            if not participant:
                return Response(
                    {'error': 'You are not a participant in this conversation'},
                    status=status.HTTP_403_FORBIDDEN
                )

            if not participant.can_send_messages:
                return Response(
                    {'error': 'You do not have permission to send messages'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Get conversation key
            conversation_key = EncryptionService.get_conversation_key(
                conversation,
                request.user
            )

            # Encrypt message
            encrypted_content, iv = EncryptionService.encrypt_message_content(
                content,
                conversation_key
            )

            # Calculate hash
            message_hash = MessageIntegrityService.calculate_hash(content)

            # Create message
            message = Message.objects.create(
                conversation=conversation,
                sender=request.user,
                encrypted_content=encrypted_content,
                encrypted_iv=iv,
                message_hash=message_hash,
                message_type='file' if request.FILES else 'text',
                reply_to_id=reply_to_id
            )

            # Add mentioned users
            if mentioned_user_ids:
                mentioned_users = User.objects.filter(
                    id__in=mentioned_user_ids,
                    conversation_memberships__conversation=conversation,
                    conversation_memberships__is_active=True
                )
                message.mentioned_users.set(mentioned_users)

            # Handle attachments
            if request.FILES:
                for file in request.FILES.getlist('attachments'):
                    self._save_encrypted_attachment(
                        message,
                        file,
                        conversation_key
                    )

            # Update conversation timestamp
            conversation.updated_at = timezone.now()
            conversation.save(update_fields=['updated_at'])

            # Get current schema for async tasks
            from django.db import connection
            current_schema = connection.schema_name

            # Update search index (async)
            from .tasks import update_search_index
            update_search_index.delay(message.id, content, current_schema)

            # Broadcast to WebSocket
            channel_layer = get_channel_layer()
            request.conversation_key = conversation_key
            message_data = MessageSerializer(
                message,
                context={'request': request}
            ).data

            async_to_sync(channel_layer.group_send)(
                f'conversation_{conversation_id}',
                {
                    'type': 'new_message',
                    'message': message_data,
                    'conversation_id': conversation_id
                }
            )

            # Send notifications to offline users (async)
            from .tasks import send_message_notifications
            send_message_notifications.delay(message.id, current_schema)

            logger.info(f"User {request.user.id} sent message {message.id} in conversation {conversation_id}")

            return Response(message_data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error creating message: {e}")
            return Response(
                {'error': 'Failed to send message'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _save_encrypted_attachment(self, message, file, conversation_key):
        """Save encrypted file attachment"""
        try:
            # Read file data
            file_data = file.read()

            # Encrypt file
            encrypted_data, iv = EncryptionService.encrypt_file(
                file_data,
                conversation_key
            )

            # Encrypt metadata
            encrypted_filename, _ = EncryptionService.encrypt_metadata(
                file.name,
                conversation_key
            )
            encrypted_size, _ = EncryptionService.encrypt_metadata(
                str(file.size),
                conversation_key
            )

            # Save encrypted file
            attachment = MessageAttachment(
                message=message,
                encrypted_filename=encrypted_filename,
                encrypted_file_size=encrypted_size,
                file_type=file.content_type,
                encrypted_iv=iv
            )

            # Generate unique filename
            ext = os.path.splitext(file.name)[1]
            filename = f'{message.id}_{timezone.now().timestamp()}{ext}'

            attachment.encrypted_file.save(
                filename,
                ContentFile(encrypted_data),
                save=False
            )

            attachment.save()

            logger.info(f"Saved encrypted attachment {attachment.id} for message {message.id}")
            return attachment

        except Exception as e:
            logger.error(f"Error saving attachment: {e}")
            raise

    @action(detail=True, methods=['get'])
    def download_attachment(self, request, pk=None):
        """
        Download decrypted attachment

        Args:
            pk: MessageAttachment ID
        """
        try:
            attachment = MessageAttachment.objects.select_related(
                'message__conversation'
            ).get(id=pk)

            # Verify access
            has_access = ConversationParticipant.objects.filter(
                conversation=attachment.message.conversation,
                user=request.user,
                is_active=True
            ).exists()

            if not has_access:
                return Response(
                    {'error': 'Access denied'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Get conversation key
            conversation_key = EncryptionService.get_conversation_key(
                attachment.message.conversation,
                request.user
            )

            # Read encrypted file
            with attachment.encrypted_file.open('rb') as f:
                encrypted_data = f.read()

            # Decrypt file
            decrypted_data = EncryptionService.decrypt_file(
                encrypted_data,
                attachment.encrypted_iv,
                conversation_key
            )

            # Decrypt filename
            filename = EncryptionService.decrypt_metadata(
                attachment.encrypted_filename,
                attachment.encrypted_iv,
                conversation_key
            )

            # Return file
            response = HttpResponse(
                decrypted_data,
                content_type=attachment.file_type
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'

            logger.info(f"User {request.user.id} downloaded attachment {attachment.id}")
            return response

        except MessageAttachment.DoesNotExist:
            return Response(
                {'error': 'Attachment not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error downloading attachment: {e}")
            return Response(
                {'error': 'Failed to download attachment'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def search(self, request):
        """
        Search messages

        TENANT-AWARE: Only searches in accessible conversations

        Body:
        {
            "query": "search term",
            "conversation_id": 1,  // Optional
            "from_date": "2025-01-01",  // Optional
            "to_date": "2025-12-31",  // Optional
            "sender_id": 5  // Optional
        }
        """
        serializer = SearchMessagesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        from .tasks import search_messages
        results = search_messages(
            request.user.id,
            serializer.validated_data
        )

        return Response(results)

    @action(detail=True, methods=['post'])
    def react(self, request, pk=None):
        """
        Add/remove emoji reaction to message

        Body:
        {
            "emoji": "👍",
            "action": "add"  // or "remove"
        }
        """
        message = self.get_object()
        emoji = request.data.get('emoji')
        action = request.data.get('action', 'add')

        if not emoji:
            return Response(
                {'error': 'emoji is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if action == 'add':
            MessageReaction.objects.get_or_create(
                message=message,
                user=request.user,
                emoji=emoji
            )
        else:
            MessageReaction.objects.filter(
                message=message,
                user=request.user,
                emoji=emoji
            ).delete()

        # Broadcast reaction
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'conversation_{message.conversation_id}',
            {
                'type': 'message_reaction',
                'message_id': message.id,
                'user_id': request.user.id,
                'username': request.user.username,
                'emoji': emoji,
                'action': action
            }
        )

        return Response({'message': 'Reaction updated'})

    @action(detail=True, methods=['post'])
    def pin(self, request, pk=None):
        """
        Pin/unpin message (admin only)
        """
        message = self.get_object()

        # Check if user is admin
        is_admin = ConversationParticipant.objects.filter(
            conversation=message.conversation,
            user=request.user,
            is_admin=True,
            is_active=True
        ).exists()

        if not is_admin and not request.user.is_superuser:
            return Response(
                {'error': 'Only admins can pin messages'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Toggle pin
        if message.is_pinned:
            message.is_pinned = False
            message.pinned_at = None
            message.pinned_by = None
            action = 'unpinned'
        else:
            message.is_pinned = True
            message.pinned_at = timezone.now()
            message.pinned_by = request.user
            action = 'pinned'

        message.save()

        logger.info(f"User {request.user.id} {action} message {message.id}")

        return Response({'message': f'Message {action} successfully'})