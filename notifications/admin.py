from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import (
    Notification, NotificationPreference, Announcement,
    NotificationCategory, NotificationTemplate, NotificationBatch,
    NotificationLog, NotificationRule
)


@admin.register(NotificationCategory)
class NotificationCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'category_type', 'icon', 'color', 'is_active', 'sort_order']
    list_filter = ['is_active', 'category_type']
    search_fields = ['name', 'description']
    prepopulated_fields = {'slug': ('name',)}
    ordering = ['sort_order', 'name']


@admin.register(NotificationTemplate)
class NotificationTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'event_type', 'category', 'priority', 'channels_display', 'is_active']
    list_filter = ['is_active', 'priority', 'category', 'send_in_app', 'send_email', 'send_sms', 'send_push']
    search_fields = ['name', 'event_type', 'title_template', 'message_template']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'event_type', 'category', 'is_active')
        }),
        ('Message Templates', {
            'fields': ('title_template', 'message_template', 'action_text', 'action_url_template')
        }),
        ('Channels', {
            'fields': ('send_in_app', 'send_email', 'send_sms', 'send_push')
        }),
        ('Email Settings', {
            'fields': ('email_subject_template', 'email_body_template'),
            'classes': ('collapse',)
        }),
        ('Priority', {
            'fields': ('priority',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def channels_display(self, obj):
        channels = []
        if obj.send_in_app:
            channels.append('In-App')
        if obj.send_email:
            channels.append('Email')
        if obj.send_sms:
            channels.append('SMS')
        if obj.send_push:
            channels.append('Push')
        return ', '.join(channels) if channels else 'None'

    channels_display.short_description = 'Channels'


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'recipient', 'notification_type', 'priority',
        'category', 'is_read', 'is_sent', 'created_at'
    ]
    list_filter = [
        'notification_type', 'priority', 'is_read', 'is_sent',
        'is_dismissed', 'category', 'created_at'
    ]
    search_fields = ['title', 'message', 'recipient__email', 'recipient__first_name', 'recipient__last_name']
    readonly_fields = [
        'created_at', 'read_at', 'sent_at', 'email_sent_at',
        'sms_sent_at', 'push_sent_at', 'dismissed_at'
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Recipient', {
            'fields': ('recipient',)
        }),
        ('Classification', {
            'fields': ('category', 'template', 'notification_type', 'priority')
        }),
        ('Content', {
            'fields': ('title', 'message', 'action_text', 'action_url')
        }),
        ('Related Object', {
            'fields': ('content_type', 'object_id'),
            'classes': ('collapse',)
        }),
        ('Status', {
            'fields': (
                'is_read', 'read_at', 'is_sent', 'sent_at',
                'is_dismissed', 'dismissed_at', 'expires_at'
            )
        }),
        ('Delivery Channels', {
            'fields': (
                'sent_via_email', 'email_sent_at',
                'sent_via_sms', 'sms_sent_at',
                'sent_via_push', 'push_sent_at'
            ),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('metadata', 'tenant_id'),
            'classes': ('collapse',)
        }),
    )

    actions = ['mark_as_read', 'mark_as_unread', 'send_notifications']

    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True, read_at=timezone.now())
        self.message_user(request, f'{updated} notification(s) marked as read.')

    mark_as_read.short_description = 'Mark selected as read'

    def mark_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False, read_at=None)
        self.message_user(request, f'{updated} notification(s) marked as unread.')

    mark_as_unread.short_description = 'Mark selected as unread'


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'announcement_type', 'priority', 'is_active',
        'start_date', 'end_date', 'created_by', 'dismissed_count'
    ]
    list_filter = ['is_active', 'announcement_type', 'is_dismissible', 'show_on_dashboard', 'start_date']
    search_fields = ['title', 'message']
    readonly_fields = ['created_at', 'updated_at', 'dismissed_count']
    date_hierarchy = 'start_date'

    fieldsets = (
        ('Content', {
            'fields': ('title', 'message', 'announcement_type')
        }),
        ('Scheduling', {
            'fields': ('start_date', 'end_date', 'is_active')
        }),
        ('Display Options', {
            'fields': ('is_dismissible', 'show_on_dashboard', 'priority')
        }),
        ('Action', {
            'fields': ('action_text', 'action_url'),
            'classes': ('collapse',)
        }),
        ('Tracking', {
            'fields': ('created_by', 'dismissed_count'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def dismissed_count(self, obj):
        return obj.dismissed_by.count()

    dismissed_count.short_description = 'Dismissed By'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'email_enabled', 'sms_enabled', 'push_enabled',
        'in_app_enabled', 'digest_enabled', 'dnd_enabled'
    ]
    list_filter = [
        'email_enabled', 'sms_enabled', 'push_enabled',
        'in_app_enabled', 'digest_enabled', 'dnd_enabled'
    ]
    search_fields = ['user__email', 'user__first_name', 'user__last_name']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Global Settings', {
            'fields': ('email_enabled', 'sms_enabled', 'push_enabled', 'in_app_enabled')
        }),
        ('Quiet Hours', {
            'fields': ('quiet_hours_enabled', 'quiet_hours_start', 'quiet_hours_end'),
            'classes': ('collapse',)
        }),
        ('Digest', {
            'fields': ('digest_enabled', 'digest_frequency'),
            'classes': ('collapse',)
        }),
        ('Do Not Disturb', {
            'fields': ('dnd_enabled', 'dnd_until'),
            'classes': ('collapse',)
        }),
        ('Advanced', {
            'fields': ('category_preferences', 'event_preferences'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(NotificationBatch)
class NotificationBatchAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'template', 'status', 'recipient_count',
        'sent_count', 'failed_count', 'scheduled_for', 'created_at'
    ]
    list_filter = ['status', 'scheduled_for', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = [
        'recipient_count', 'sent_count', 'failed_count',
        'created_at', 'started_at', 'completed_at'
    ]
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'template')
        }),
        ('Recipients', {
            'fields': ('recipients', 'recipient_count')
        }),
        ('Context Data', {
            'fields': ('context_data',),
            'classes': ('collapse',)
        }),
        ('Scheduling', {
            'fields': ('scheduled_for', 'status')
        }),
        ('Progress', {
            'fields': ('sent_count', 'failed_count'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_by', 'created_at', 'started_at', 'completed_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ['notification', 'channel', 'status', 'sent_at', 'delivered_at', 'retry_count']
    list_filter = ['channel', 'status', 'sent_at']
    search_fields = ['notification__title', 'error_message']
    readonly_fields = ['created_at', 'sent_at', 'delivered_at', 'opened_at', 'clicked_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Notification', {
            'fields': ('notification', 'channel', 'status')
        }),
        ('Delivery', {
            'fields': ('sent_at', 'delivered_at', 'opened_at', 'clicked_at')
        }),
        ('Error Handling', {
            'fields': ('error_message', 'retry_count', 'max_retries'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('metadata',),
            'classes': ('collapse',)
        }),
    )


@admin.register(NotificationRule)
class NotificationRuleAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'trigger_model', 'trigger_event', 'template',
        'recipient_type', 'is_active', 'triggered_count'
    ]
    list_filter = ['is_active', 'trigger_event', 'recipient_type', 'throttle_enabled']
    search_fields = ['name', 'description', 'trigger_model']
    readonly_fields = ['triggered_count', 'last_triggered_at', 'created_at', 'updated_at']

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'description', 'is_active')
        }),
        ('Trigger', {
            'fields': ('trigger_model', 'trigger_event', 'conditions')
        }),
        ('Notification', {
            'fields': ('template',)
        }),
        ('Recipients', {
            'fields': ('recipient_type', 'specific_users', 'user_roles')
        }),
        ('Throttling', {
            'fields': ('throttle_enabled', 'throttle_minutes'),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('triggered_count', 'last_triggered_at'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )