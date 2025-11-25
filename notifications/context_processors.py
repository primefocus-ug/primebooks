import logging
from django.db import connection
from django.utils import timezone
from django.db.models import Q
from django.db import models
from django_tenants.utils import get_public_schema_name

logger = logging.getLogger(__name__)


def notifications_context(request):
    """
    Schema-safe notifications context processor.
    Handles both public and tenant users.
    CRITICAL: Only queries tenant-specific models when in a tenant schema.
    """
    public_schema = get_public_schema_name()
    current_schema = connection.schema_name

    # Default empty context
    context = {
        'unread_notifications_count': 0,
        'recent_notifications': [],
        'active_announcements': [],
        'has_unread_notifications': False,
        'low_stock_alert': 0,
        'new_users_count': 0,
        'system_notifications': [],
    }

    # Only query tenant data if we're NOT in public schema and user is authenticated
    if request.user.is_authenticated and current_schema and current_schema != public_schema:
        try:
            # Import here to avoid issues when tables don't exist
            from notifications.models import Notification, Announcement
            from inventory.models import Stock
            from accounts.models import CustomUser

            # Unread notifications count
            try:
                context['unread_notifications_count'] = Notification.objects.filter(
                    recipient=request.user,
                    is_read=False,
                    is_dismissed=False
                ).count()
                context['has_unread_notifications'] = context['unread_notifications_count'] > 0
            except Exception as notification_count_error:
                logger.debug(f"Could not get unread notifications count: {notification_count_error}")

            # Recent notifications (limited to 5 for dropdown)
            try:
                context['recent_notifications'] = Notification.objects.filter(
                    recipient=request.user,
                    is_dismissed=False
                ).select_related('category').order_by('-created_at')[:5]
            except Exception as recent_notifications_error:
                logger.debug(f"Could not get recent notifications: {recent_notifications_error}")

            # Active announcements
            try:
                now = timezone.now()
                context['active_announcements'] = Announcement.objects.filter(
                    is_active=True,
                    start_date__lte=now,
                    show_on_dashboard=True
                ).filter(
                    Q(end_date__isnull=True) | Q(end_date__gte=now)
                ).exclude(
                    dismissed_by=request.user
                ).order_by('-priority', '-created_at')[:3]
            except Exception as announcements_error:
                logger.debug(f"Could not get active announcements: {announcements_error}")

            # Low stock items
            try:
                context['low_stock_alert'] = Stock.objects.filter(
                    quantity__lte=models.F('low_stock_threshold')
                ).count()
            except Exception as stock_error:
                logger.debug(f"Could not get low stock alerts: {stock_error}")

            # New users in last 24h
            try:
                context['new_users_count'] = CustomUser.objects.filter(
                    date_joined__gte=timezone.now() - timezone.timedelta(days=1)
                ).count()
            except Exception as users_error:
                logger.debug(f"Could not get new users count: {users_error}")

        except Exception as e:
            # Log but don't break the view
            logger.warning(
                f"Error in notifications context processor for schema '{current_schema}': {e}"
            )

    # System update notification (optional, global) - works in both public and tenant schemas
    if request.user.is_authenticated and request.user.is_staff:
        context['system_notifications'] = [{
            'message': 'System update available',
            'icon': 'bi bi-info-circle',
            'url': '/system/updates/'
        }]

    return context


def notification_preferences_context(request):
    """
    Schema-safe notification preferences context processor.
    """
    public_schema = get_public_schema_name()
    current_schema = connection.schema_name

    # Default empty context
    context = {
        'notification_preferences': None,
        'notifications_enabled': True,  # Default to enabled if we can't determine
    }

    # Only query tenant data if we're NOT in public schema and user is authenticated
    if request.user.is_authenticated and current_schema and current_schema != public_schema:
        try:
            # Import here to avoid issues when tables don't exist
            from notifications.models import NotificationPreference

            try:
                prefs, created = NotificationPreference.objects.get_or_create(
                    user=request.user
                )
                context.update({
                    'notification_preferences': prefs,
                    'notifications_enabled': prefs.in_app_enabled,
                })
            except Exception as prefs_error:
                logger.debug(f"Could not get notification preferences: {prefs_error}")

        except Exception as e:
            # Log but don't break the view
            logger.warning(
                f"Error in notification preferences context processor for schema '{current_schema}': {e}"
            )

    return context