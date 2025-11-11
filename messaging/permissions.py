from rest_framework import permissions
from .models import ConversationParticipant


class IsConversationParticipant(permissions.BasePermission):
    """
    Check if user is participant in conversation

    TENANT-AWARE: Verifies access within tenant boundaries
    """
    message = "You are not a participant in this conversation"

    def has_permission(self, request, view):
        """Check basic authentication"""
        return request.user and request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        """
        Check if user is participant

        Works for both Conversation and Message objects
        """
        # Get conversation from object
        if hasattr(obj, 'conversation'):
            # It's a Message or MessageAttachment
            conversation = obj.conversation
        else:
            # It's a Conversation
            conversation = obj

        # Check if user is active participant
        is_participant = ConversationParticipant.objects.filter(
            conversation=conversation,
            user=request.user,
            is_active=True
        ).exists()

        # SaaS admins can access any conversation
        if not is_participant and getattr(request.user, 'is_saas_admin', False):
            return True

        return is_participant


class CanDeleteMessage(permissions.BasePermission):
    """
    Check if user can delete messages

    Rules:
    - SaaS admins can delete any message
    - Super admins can delete any message in their tenant
    - Company admins can delete any message in their tenant
    - Conversation admins can delete messages in their conversations
    - Message senders can delete their own messages
    """
    message = "You do not have permission to delete this message"

    def has_object_permission(self, request, view, obj):
        """Check deletion permission"""
        user = request.user

        # SaaS admin can delete anything
        if getattr(user, 'is_saas_admin', False):
            return True

        # Super admin can delete anything in tenant
        if user.is_superuser:
            return True

        # Company admin can delete anything in tenant
        if getattr(user, 'company_admin', False):
            return True

        # Check if user is conversation admin
        is_conv_admin = ConversationParticipant.objects.filter(
            conversation=obj.conversation,
            user=user,
            is_admin=True,
            is_active=True
        ).exists()

        if is_conv_admin:
            return True

        # User can delete their own messages
        if obj.sender == user:
            return True

        return False


class CanModifyConversation(permissions.BasePermission):
    """
    Check if user can modify conversation settings

    Rules:
    - SaaS admins can modify any conversation
    - Super admins can modify conversations in their tenant
    - Company admins can modify conversations in their tenant
    - Conversation admins can modify their conversations
    - Conversation creator can modify their conversation
    """
    message = "You do not have permission to modify this conversation"

    def has_object_permission(self, request, view, obj):
        """Check modification permission"""
        user = request.user

        # SaaS admin can modify anything
        if getattr(user, 'is_saas_admin', False):
            return True

        # Super admin can modify anything in tenant
        if user.is_superuser:
            return True

        # Company admin can modify anything in tenant
        if getattr(user, 'company_admin', False):
            return True

        # Conversation creator can modify
        if obj.created_by == user:
            return True

        # Check if user is conversation admin
        is_conv_admin = ConversationParticipant.objects.filter(
            conversation=obj,
            user=user,
            is_admin=True,
            is_active=True
        ).exists()

        return is_conv_admin


class CanAddParticipants(permissions.BasePermission):
    """
    Check if user can add participants to conversation

    Rules:
    - SaaS admins can add anyone to any conversation
    - Conversation admins can add participants
    - Users with can_add_participants permission can add
    """
    message = "You do not have permission to add participants"

    def has_object_permission(self, request, view, obj):
        """Check add permission"""
        user = request.user

        # SaaS admin can add anyone
        if getattr(user, 'is_saas_admin', False):
            return True

        # Check participant permissions
        participant = ConversationParticipant.objects.filter(
            conversation=obj,
            user=user,
            is_active=True
        ).first()

        if not participant:
            return False

        return participant.can_add_participants or participant.is_admin


class CanRemoveParticipants(permissions.BasePermission):
    """
    Check if user can remove participants from conversation

    Rules:
    - SaaS admins can remove anyone from any conversation
    - Conversation admins can remove participants
    - Users with can_remove_participants permission can remove
    - Users can remove themselves (leave)
    """
    message = "You do not have permission to remove participants"

    def has_object_permission(self, request, view, obj):
        """Check remove permission"""
        user = request.user

        # SaaS admin can remove anyone
        if getattr(user, 'is_saas_admin', False):
            return True

        # Check if trying to remove self (always allowed)
        target_user_id = request.data.get('user_id')
        if target_user_id and int(target_user_id) == user.id:
            return True

        # Check participant permissions
        participant = ConversationParticipant.objects.filter(
            conversation=obj,
            user=user,
            is_active=True
        ).first()

        if not participant:
            return False

        return participant.can_remove_participants or participant.is_admin


class CanSendMessages(permissions.BasePermission):
    """
    Check if user can send messages in conversation

    Rules:
    - SaaS admins can send messages anywhere
    - Active participants with can_send_messages permission
    """
    message = "You do not have permission to send messages in this conversation"

    def has_object_permission(self, request, view, obj):
        """Check send permission"""
        user = request.user

        # SaaS admin can send anywhere
        if getattr(user, 'is_saas_admin', False):
            return True

        # Check participant permissions
        participant = ConversationParticipant.objects.filter(
            conversation=obj,
            user=user,
            is_active=True
        ).first()

        if not participant:
            return False

        return participant.can_send_messages


class IsMessageSender(permissions.BasePermission):
    """
    Check if user is the sender of the message

    Used for edit/update operations
    """
    message = "You can only edit your own messages"

    def has_object_permission(self, request, view, obj):
        """Check if user is sender"""
        return obj.sender == request.user


class IsTenantUser(permissions.BasePermission):
    """
    Check if user belongs to current tenant

    TENANT-AWARE: Ensures user access is within tenant boundaries
    """
    message = "Access denied for this tenant"

    def has_permission(self, request, view):
        """Check tenant access"""
        user = request.user

        # SaaS admins can access all tenants
        if getattr(user, 'is_saas_admin', False):
            return True

        # Check if user has active access
        if not user.is_active:
            return False

        # Check if user's company has active access
        if hasattr(user, 'company'):
            return user.company.has_active_access

        return True


class CanAccessCrossTenant(permissions.BasePermission):
    """
    Check if user can access cross-tenant conversations

    Only SaaS admins can access cross-tenant features
    """
    message = "Cross-tenant access is restricted to SaaS administrators"

    def has_permission(self, request, view):
        """Check cross-tenant permission"""
        return getattr(request.user, 'is_saas_admin', False)

    def has_object_permission(self, request, view, obj):
        """Check if user can access this cross-tenant conversation"""
        # If it's not cross-tenant, allow normal permission checks
        if hasattr(obj, 'is_cross_tenant') and not obj.is_cross_tenant:
            return True

        # For cross-tenant conversations, only SaaS admins
        return getattr(request.user, 'is_saas_admin', False)


class CanManageConversationSettings(permissions.BasePermission):
    """
    Check if user can manage conversation settings
    (retention, notifications, etc.)
    """
    message = "You do not have permission to manage conversation settings"

    def has_object_permission(self, request, view, obj):
        """Check settings management permission"""
        user = request.user

        # SaaS admin can manage all settings
        if getattr(user, 'is_saas_admin', False):
            return True

        # Only admins can change settings
        is_admin = ConversationParticipant.objects.filter(
            conversation=obj,
            user=user,
            is_admin=True,
            is_active=True
        ).exists()

        return is_admin