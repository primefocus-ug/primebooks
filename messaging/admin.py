from django.contrib import admin
from .models import (
    Conversation, ConversationParticipant, Message,
    MessageAttachment, EncryptionKeyManager
)


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ['id', 'conversation_type', 'name', 'created_by', 'created_at', 'is_cross_tenant']
    list_filter = ['conversation_type', 'is_active', 'is_cross_tenant']
    search_fields = ['name', 'created_by__username']
    readonly_fields = ['encrypted_symmetric_key', 'created_at', 'updated_at']


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ['id', 'conversation', 'sender', 'message_type', 'created_at', 'is_deleted']
    list_filter = ['message_type', 'is_deleted', 'is_edited']
    search_fields = ['sender__username']
    readonly_fields = ['encrypted_content', 'encrypted_iv', 'message_hash', 'created_at']

    def has_delete_permission(self, request, obj=None):
        # Only super admins can permanently delete
        return request.user.is_superuser


@admin.register(EncryptionKeyManager)
class EncryptionKeyManagerAdmin(admin.ModelAdmin):
    list_display = ['user', 'key_version', 'key_created_at']
    readonly_fields = ['public_key', 'encrypted_private_key', 'key_created_at']

    def has_add_permission(self, request):
        return False  # Keys auto-generated

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
