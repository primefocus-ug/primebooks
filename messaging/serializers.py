from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
import logging
from .models import (
    Conversation, ConversationParticipant, Message,
    MessageAttachment, MessageReaction, MessageReadReceipt,
    EncryptionKeyManager
)
from .services import EncryptionService, TenantMessagingService

User = get_user_model()
logger = logging.getLogger(__name__)


class UserBasicSerializer(serializers.ModelSerializer):
    """
    Basic user info for messaging

    TENANT-AWARE: Includes company info for cross-tenant conversations
    """
    full_name = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()
    user_type_display = serializers.CharField(source='get_user_type_display', read_only=True)
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'full_name',
            'first_name', 'last_name', 'user_type_display',
            'company_name', 'is_active', 'avatar_url'
        ]

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_company_name(self, obj):
        """Include company name for cross-tenant awareness"""
        if hasattr(obj, 'company') and obj.company:
            return obj.company.display_name
        return None

    def get_avatar_url(self, obj):
        if obj.avatar:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.avatar.url)
        return None


class UserSearchSerializer(serializers.ModelSerializer):
    """Serializer for user search results"""
    full_name = serializers.SerializerMethodField()
    company_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'full_name', 'email', 'company_name']

    def get_full_name(self, obj):
        return obj.get_full_name() or obj.username

    def get_company_name(self, obj):
        if hasattr(obj, 'company') and obj.company:
            return obj.company.display_name
        return None


class MessageAttachmentSerializer(serializers.ModelSerializer):
    """Serializer for file attachments"""
    decrypted_filename = serializers.SerializerMethodField()
    decrypted_size = serializers.SerializerMethodField()
    download_url = serializers.SerializerMethodField()
    is_image = serializers.SerializerMethodField()

    class Meta:
        model = MessageAttachment
        fields = [
            'id', 'decrypted_filename', 'decrypted_size',
            'file_type', 'download_url', 'uploaded_at',
            'is_image', 'thumbnail'
        ]

    def get_decrypted_filename(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'conversation_key'):
            try:
                return EncryptionService.decrypt_metadata(
                    obj.encrypted_filename,
                    obj.encrypted_iv,
                    request.conversation_key
                )
            except Exception:
                return '[Encrypted]'
        return '[Encrypted]'

    def get_decrypted_size(self, obj):
        request = self.context.get('request')
        if request and hasattr(request, 'conversation_key'):
            try:
                size_bytes = int(EncryptionService.decrypt_metadata(
                    obj.encrypted_file_size,
                    obj.encrypted_iv,
                    request.conversation_key
                ))
                # Format size
                if size_bytes < 1024:
                    return f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    return f"{size_bytes / 1024:.1f} KB"
                else:
                    return f"{size_bytes / (1024 * 1024):.1f} MB"
            except Exception:
                return '0 B'
        return '0 B'

    def get_download_url(self, obj):
        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(
                f'/api/messaging/messages/{obj.id}/download_attachment/'
            )
        return None

    def get_is_image(self, obj):
        """Check if attachment is an image"""
        image_types = ['image/jpeg', 'image/png', 'image/gif', 'image/webp']
        return obj.file_type in image_types


class MessageReactionSerializer(serializers.ModelSerializer):
    """Serializer for emoji reactions"""
    user = UserBasicSerializer(read_only=True)

    class Meta:
        model = MessageReaction
        fields = ['id', 'user', 'emoji', 'created_at']


class MessageReadReceiptSerializer(serializers.ModelSerializer):
    """Serializer for read receipts"""
    user = UserBasicSerializer(read_only=True)

    class Meta:
        model = MessageReadReceipt
        fields = ['id', 'user', 'read_at']


class MessageSerializer(serializers.ModelSerializer):
    """
    Main message serializer with decryption

    TENANT-AWARE: Decrypts messages using conversation keys
    """
    sender = UserBasicSerializer(read_only=True)
    decrypted_content = serializers.SerializerMethodField()
    attachments = MessageAttachmentSerializer(many=True, read_only=True)
    reactions = MessageReactionSerializer(many=True, read_only=True)
    read_receipts = MessageReadReceiptSerializer(many=True, read_only=True)
    reply_to_message = serializers.SerializerMethodField()
    mentioned_users = UserBasicSerializer(many=True, read_only=True)
    is_read_by_me = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()
    can_delete = serializers.SerializerMethodField()
    reaction_summary = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            'id', 'conversation', 'sender', 'decrypted_content',
            'message_type', 'is_edited', 'edited_at', 'is_deleted',
            'attachments', 'reactions', 'read_receipts', 'reply_to',
            'reply_to_message', 'mentioned_users', 'created_at',
            'is_read_by_me', 'can_edit', 'can_delete', 'is_pinned',
            'pinned_at', 'pinned_by', 'reaction_summary'
        ]
        read_only_fields = [
            'id', 'sender', 'created_at', 'is_edited',
            'edited_at', 'is_pinned', 'pinned_at', 'pinned_by'
        ]

    def get_decrypted_content(self, obj):
        """Decrypt message content"""
        request = self.context.get('request')

        # Don't decrypt deleted messages
        if obj.is_deleted:
            return '[Message deleted]'

        # Decrypt if we have the conversation key
        if request and hasattr(request, 'conversation_key'):
            try:
                return Message.decrypt_message(
                    obj.encrypted_content,
                    obj.encrypted_iv,
                    request.conversation_key
                )
            except Exception:
                return '[Decryption failed]'

        return '[Encrypted]'

    def get_reply_to_message(self, obj):
        """Get replied message info"""
        if obj.reply_to and not obj.reply_to.is_deleted:
            return {
                'id': obj.reply_to.id,
                'sender': UserBasicSerializer(
                    obj.reply_to.sender,
                    context=self.context
                ).data,
                'preview': self.get_decrypted_content(obj.reply_to)[:100],
                'created_at': obj.reply_to.created_at
            }
        return None

    def get_is_read_by_me(self, obj):
        """Check if current user has read this message"""
        request = self.context.get('request')
        if request and request.user:
            return MessageReadReceipt.objects.filter(
                message=obj,
                user=request.user
            ).exists()
        return False

    def get_can_edit(self, obj):
        """Check if current user can edit this message"""
        request = self.context.get('request')
        if not request or not request.user:
            return False

        # Only sender can edit
        if obj.sender != request.user:
            return False

        # Can't edit deleted messages
        if obj.is_deleted:
            return False

        # Can only edit within 15 minutes
        time_limit = timezone.now() - timedelta(minutes=15)
        return obj.created_at > time_limit

    def get_can_delete(self, obj):
        """Check if current user can delete this message"""
        request = self.context.get('request')
        if not request or not request.user:
            return False

        user = request.user

        # Super admins can delete anything
        if user.is_superuser or getattr(user, 'is_saas_admin', False):
            return True

        # Conversation admins can delete
        is_conv_admin = ConversationParticipant.objects.filter(
            conversation=obj.conversation,
            user=user,
            is_admin=True,
            is_active=True
        ).exists()

        if is_conv_admin:
            return True

        # Sender can delete their own messages
        return obj.sender == user

    def get_reaction_summary(self, obj):
        """Get aggregated reaction counts"""
        from django.db.models import Count

        reactions = obj.reactions.values('emoji').annotate(
            count=Count('id')
        ).order_by('-count')

        return [
            {
                'emoji': r['emoji'],
                'count': r['count']
            }
            for r in reactions
        ]


class CreateMessageSerializer(serializers.Serializer):
    """Serializer for creating new messages"""
    conversation_id = serializers.IntegerField()
    content = serializers.CharField(max_length=10000)
    reply_to = serializers.IntegerField(required=False, allow_null=True)
    mentioned_user_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=True
    )
    attachments = serializers.ListField(
        child=serializers.FileField(),
        required=False,
        allow_empty=True
    )

    def validate_conversation_id(self, value):
        """Verify conversation exists and user has access"""
        user = self.context['request'].user

        try:
            conversation = Conversation.objects.get(id=value, is_active=True)
        except Conversation.DoesNotExist:
            raise serializers.ValidationError("Conversation not found")

        # Check participation and permission
        participant = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=user,
            is_active=True
        ).first()

        if not participant:
            raise serializers.ValidationError(
                "You are not a participant in this conversation"
            )

        if not participant.can_send_messages:
            raise serializers.ValidationError(
                "You don't have permission to send messages in this conversation"
            )

        # Store for later use in create view
        self.context['conversation'] = conversation
        self.context['participant'] = participant

        return value

    def validate_reply_to(self, value):
        """Validate reply_to message exists"""
        if value:
            try:
                Message.objects.get(id=value, is_deleted=False)
            except Message.DoesNotExist:
                raise serializers.ValidationError("Reply message not found")
        return value

    def validate_mentioned_user_ids(self, value):
        """Validate mentioned users exist and are in conversation"""
        if value:
            conversation_id = self.initial_data.get('conversation_id')
            if conversation_id:
                valid_users = ConversationParticipant.objects.filter(
                    conversation_id=conversation_id,
                    user_id__in=value,
                    is_active=True
                ).count()

                if valid_users != len(value):
                    raise serializers.ValidationError(
                        "Some mentioned users are not in this conversation"
                    )

        return value


class ConversationParticipantSerializer(serializers.ModelSerializer):
    """Serializer for conversation participants"""
    user = UserBasicSerializer(read_only=True)
    unread_count = serializers.IntegerField(source='get_unread_count', read_only=True)

    class Meta:
        model = ConversationParticipant
        fields = [
            'id', 'user', 'is_admin', 'can_send_messages',
            'can_add_participants', 'can_remove_participants',
            'joined_at', 'last_read_at', 'is_muted',
            'email_notifications', 'push_notifications',
            'unread_count', 'display_name'
        ]


class ConversationSerializer(serializers.ModelSerializer):
    """
    Main conversation serializer

    TENANT-AWARE: Includes cross-tenant indicators
    """
    participants = ConversationParticipantSerializer(many=True, read_only=True)
    created_by = UserBasicSerializer(read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    participant_count = serializers.SerializerMethodField()
    my_permissions = serializers.SerializerMethodField()
    is_archived = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            'id', 'conversation_type', 'name', 'description',
            'participants', 'created_by', 'created_at', 'updated_at',
            'last_message', 'unread_count', 'participant_count',
            'is_cross_tenant', 'tenant_schemas', 'my_permissions',
            'is_archived', 'archived_at', 'message_retention_days'
        ]
        read_only_fields = [
            'id', 'created_by', 'created_at', 'updated_at',
            'is_cross_tenant', 'tenant_schemas'
        ]

    def get_last_message(self, obj):
        """Get the most recent message"""
        try:
            last_msg = Message.objects.filter(
                conversation=obj,
                is_deleted=False
            ).select_related('sender').order_by('-created_at').first()

            if last_msg:
                # Return simplified message data to avoid circular issues
                return {
                    'id': last_msg.id,
                    'sender': {
                        'id': last_msg.sender.id,
                        'username': last_msg.sender.username,
                        'full_name': last_msg.sender.get_full_name()
                    },
                    'preview': '[Encrypted]',  # Don't decrypt here for performance
                    'created_at': last_msg.created_at,
                    'message_type': last_msg.message_type
                }
        except Exception as e:
            logger.error(f"Error getting last message: {e}")
        return None

    def get_unread_count(self, obj):
        """Get unread count for current user"""
        request = self.context.get('request')
        if request and request.user:
            participant = obj.participants.filter(
                user=request.user,
                is_active=True
            ).first()
            if participant:
                return participant.get_unread_count()
        return 0

    def get_participant_count(self, obj):
        """Count active participants"""
        return obj.participants.filter(is_active=True).count()

    def get_my_permissions(self, obj):
        """Get current user's permissions in this conversation"""
        request = self.context.get('request')
        if request and request.user:
            participant = obj.participants.filter(
                user=request.user,
                is_active=True
            ).first()

            if participant:
                return {
                    'can_send_messages': participant.can_send_messages,
                    'can_add_participants': participant.can_add_participants,
                    'can_remove_participants': participant.can_remove_participants,
                    'is_admin': participant.is_admin,
                }

        return {
            'can_send_messages': False,
            'can_add_participants': False,
            'can_remove_participants': False,
            'is_admin': False,
        }

    def get_is_archived(self, obj):
        """Check if conversation is archived"""
        return obj.archived_at is not None


class CreateConversationSerializer(serializers.Serializer):
    """Serializer for creating conversations"""
    conversation_type = serializers.ChoiceField(
        choices=['direct', 'group', 'channel', 'department', 'broadcast']
    )
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    participant_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1
    )
    is_cross_tenant = serializers.BooleanField(default=False)

    def validate_participant_ids(self, value):
        """Validate participants exist and are active"""
        user = self.context['request'].user

        # For non-SaaS admins, ensure users are in same company
        if not getattr(user, 'is_saas_admin', False):
            users = User.objects.filter(
                id__in=value,
                is_active=True,
                company=user.company
            )
        else:
            users = User.objects.filter(id__in=value, is_active=True)

        if users.count() != len(value):
            raise serializers.ValidationError(
                "Some users not found or not accessible"
            )

        return value

    def validate_is_cross_tenant(self, value):
        """Only saas_admin can create cross-tenant conversations"""
        if value:
            user = self.context['request'].user
            if not TenantMessagingService.can_create_cross_tenant_conversation(user):
                raise serializers.ValidationError(
                    "Only SaaS administrators can create cross-tenant conversations"
                )
        return value

    def validate(self, attrs):
        """Additional validation"""
        conv_type = attrs['conversation_type']
        name = attrs.get('name')

        # Group, channel, department, broadcast need names
        if conv_type in ['group', 'channel', 'department', 'broadcast'] and not name:
            raise serializers.ValidationError({
                'name': f'{conv_type.title()} conversations must have a name'
            })

        # Direct messages must have exactly 2 participants (including sender)
        if conv_type == 'direct':
            if len(attrs['participant_ids']) != 1:
                raise serializers.ValidationError({
                    'participant_ids': 'Direct conversations must have exactly 1 other participant'
                })

        return attrs


class AddParticipantSerializer(serializers.Serializer):
    """Add participants to conversation"""
    user_ids = serializers.ListField(
        child=serializers.IntegerField(),
        min_length=1
    )
    can_send_messages = serializers.BooleanField(default=True)
    is_admin = serializers.BooleanField(default=False)

    def validate_user_ids(self, value):
        """Validate users exist and are active"""
        users = User.objects.filter(id__in=value, is_active=True)
        if users.count() != len(value):
            raise serializers.ValidationError("Some users not found")
        return value


class SearchMessagesSerializer(serializers.Serializer):
    """Search parameters"""
    query = serializers.CharField(max_length=500)
    conversation_id = serializers.IntegerField(required=False, allow_null=True)
    from_date = serializers.DateTimeField(required=False, allow_null=True)
    to_date = serializers.DateTimeField(required=False, allow_null=True)
    sender_id = serializers.IntegerField(required=False, allow_null=True)