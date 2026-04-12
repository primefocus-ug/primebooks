from django.contrib import admin
from .models import (
    PushNotificationType,
    RoleNotificationDefault,
    UserPushPreference,
    PushSubscription
)


@admin.register(PushNotificationType)
class PushNotificationTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'icon', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'code', 'description')
    ordering = ('name',)


@admin.register(RoleNotificationDefault)
class RoleNotificationDefaultAdmin(admin.ModelAdmin):
    list_display = ('role', 'notification_type')
    list_filter = ('role', 'notification_type')
    search_fields = ('role__name', 'notification_type__name')


@admin.register(UserPushPreference)
class UserPushPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'notification_type', 'enabled', 'updated_at')
    list_filter = ('enabled', 'notification_type')
    search_fields = ('user__username', 'notification_type__name')
    list_editable = ('enabled',)


@admin.register(PushSubscription)
class PushSubscriptionAdmin(admin.ModelAdmin):
    list_display = ('user', 'short_endpoint', 'is_active', 'created_at', 'last_used_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('user__username', 'endpoint', 'user_agent')
    readonly_fields = ('id', 'created_at', 'last_used_at')

    def short_endpoint(self, obj):
        return f"{obj.endpoint[:50]}..."
    short_endpoint.short_description = "Endpoint"