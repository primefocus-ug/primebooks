"""support_widget/admin.py"""
from django.contrib import admin
from .models import (
    SupportWidgetConfig, VisitorSession, ChatMessage,
    FAQ, AgentProfile, CallSession, CallRecording,
)


@admin.register(SupportWidgetConfig)
class WidgetConfigAdmin(admin.ModelAdmin):
    list_display  = ('widget_title', 'brand_color', 'is_active', 'updated_at')
    fieldsets = (
        ('Branding', {'fields': ('widget_title', 'brand_color', 'logo', 'greeting_message')}),
        ('Availability', {'fields': ('is_active', 'business_hours_message', 'offline_email')}),
        ('Call Recording', {'fields': ('call_recording_notice',)}),
    )


class ChatMessageInline(admin.TabularInline):
    model        = ChatMessage
    extra        = 0
    readonly_fields = ('sender', 'agent_user', 'body', 'created_at')
    can_delete   = False


@admin.register(VisitorSession)
class VisitorSessionAdmin(admin.ModelAdmin):
    list_display  = ('visitor_name', 'visitor_email', 'status', 'assigned_agent', 'created_at')
    list_filter   = ('status',)
    search_fields = ('visitor_name', 'visitor_email', 'session_token')
    readonly_fields = ('session_token', 'created_at', 'updated_at')
    inlines       = [ChatMessageInline]


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display  = ('question', 'is_active', 'sort_order')
    list_editable = ('is_active', 'sort_order')
    search_fields = ('question', 'keywords')


@admin.register(AgentProfile)
class AgentProfileAdmin(admin.ModelAdmin):
    list_display  = ('user', 'display_name', 'status', 'accept_calls', 'last_seen')
    list_editable = ('status', 'accept_calls')


@admin.register(CallSession)
class CallSessionAdmin(admin.ModelAdmin):
    list_display  = ('call_room_id', 'session', 'agent', 'status', 'duration_display', 'created_at')
    list_filter   = ('status',)
    readonly_fields = ('call_room_id', 'created_at', 'duration_secs')


@admin.register(CallRecording)
class CallRecordingAdmin(admin.ModelAdmin):
    list_display  = ('call', 'file_size', 'created_at')
    readonly_fields = ('file_size', 'created_at')