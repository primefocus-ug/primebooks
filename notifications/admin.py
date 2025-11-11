from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from .models import Notification, NotificationPreference, Announcement, NotificationBatch


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'recipient', 'notification_type',
        'is_read_badge', 'priority', 'created_at'
    ]
    list_filter = [
        'notification_type', 'is_read', 'is_emailed',
        'priority', 'created_at'
    ]
    search_fields = ['title', 'message', 'recipient__username', 'recipient__email']
    readonly_fields = ['created_at', 'updated_at', 'read_at', 'emailed_at']
    date_hierarchy = 'created_at'

    fieldsets = (
        (_('Recipient'), {
            'fields': ('recipient', 'sender')
        }),
        (_('Content'), {
            'fields': ('notification_type', 'title', 'message', 'action_url', 'action_text')
        }),
        (_('Status'), {
            'fields': ('is_read', 'read_at', 'is_emailed', 'emailed_at')
        }),
        (_('Settings'), {
            'fields': ('priority', 'expires_at', 'metadata')
        }),
        (_('Related Object'), {
            'fields': ('content_type', 'object_id'),
            'classes': ('collapse',)
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

    actions = ['mark_as_read', 'mark_as_unread', 'delete_selected']

    def is_read_badge(self, obj):
        if obj.is_read:
            return format_html(
                '<span style="color: green;">✓ Read</span>'
            )
        return format_html(
            '<span style="color: orange;">● Unread</span>'
        )

    is_read_badge.short_description = _('Status')

    def mark_as_read(self, request, queryset):
        count = 0
        for notification in queryset:
            notification.mark_as_read()
            count += 1
        self.message_user(request, f'{count} notifications marked as read.')

    mark_as_read.short_description = _('Mark selected as read')

    def mark_as_unread(self, request, queryset):
        count = 0
        for notification in queryset:
            notification.mark_as_unread()
            count += 1
        self.message_user(request, f'{count} notifications marked as unread.')

    mark_as_unread.short_description = _('Mark selected as unread')


@admin.register(NotificationPreference)
class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'email_on_expense_approved', 'push_enabled',
        'digest_frequency', 'updated_at'
    ]
    list_filter = ['push_enabled', 'digest_frequency']
    search_fields = ['user__username', 'user__email']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'announcement_type', 'is_active',
        'priority', 'start_date', 'end_date'
    ]
    list_filter = ['announcement_type', 'is_active', 'show_on_dashboard', 'created_at']
    search_fields = ['title', 'message']
    readonly_fields = ['created_at', 'updated_at']
    filter_horizontal = ['dismissed_by']

    fieldsets = (
        (_('Content'), {
            'fields': ('title', 'message', 'announcement_type')
        }),
        (_('Schedule'), {
            'fields': ('start_date', 'end_date', 'is_active')
        }),
        (_('Display'), {
            'fields': ('priority', 'show_on_dashboard', 'is_dismissible')
        }),
        (_('Action'), {
            'fields': ('action_url', 'action_text')
        }),
        (_('Tracking'), {
            'fields': ('created_by', 'dismissed_by'),
            'classes': ('collapse',)
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )


@admin.register(NotificationBatch)
class NotificationBatchAdmin(admin.ModelAdmin):
    list_display = [
        'batch_type', 'sent_at', 'recipient_count',
        'success_count', 'failure_count', 'status'
    ]
    list_filter = ['batch_type', 'status', 'sent_at']
    search_fields = ['batch_type', 'error_message']
    readonly_fields = ['sent_at']