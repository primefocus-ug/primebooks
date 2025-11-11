from django.utils import timezone
from django.db import models, connection
from django_tenants.utils import get_public_schema_name
import logging
from .models import Notification, Announcement
from django.utils import timezone
from django.db.models import Q


logger = logging.getLogger(__name__)


def notifications_context(request):
    """
    Context processor for notifications.
    Only queries tenant-specific models when in a tenant schema.
    """
    public_schema = get_public_schema_name()
    current_schema = connection.schema_name

    # Default empty notifications
    notifications = []

    # Only query tenant data if we're NOT in public schema
    if current_schema and current_schema != public_schema:
        try:
            # Import here to avoid import errors when tables don't exist
            from inventory.models import Stock
            from accounts.models import CustomUser

            # Low stock items
            try:
                low_stock_items = Stock.objects.filter(
                    quantity__lte=models.F('low_stock_threshold')
                ).count()

                if low_stock_items > 0:
                    notifications.append({
                        'message': f'{low_stock_items} item{"s" if low_stock_items != 1 else ""} below reorder level',
                        'icon': 'bi bi-exclamation-triangle',
                        'url': '/inventory/stock/'
                    })
            except Exception as stock_error:
                logger.debug(f"Could not query stock in schema '{current_schema}': {stock_error}")

            # New users registered in last 24h
            try:
                new_users_count = CustomUser.objects.filter(
                    date_joined__gte=timezone.now() - timezone.timedelta(days=1)
                ).count()

                if new_users_count > 0:
                    notifications.append({
                        'message': f'{new_users_count} new user{"s" if new_users_count != 1 else ""} registered',
                        'icon': 'bi bi-person-plus',
                        'url': '/accounts/users/'
                    })
            except Exception as user_error:
                logger.debug(f"Could not query users in schema '{current_schema}': {user_error}")

        except Exception as e:
            # Log but don't break the view
            logger.warning(
                f"Error in notifications context processor for schema '{current_schema}': {e}"
            )

    # System update notification (always available, not tenant-specific)
    # Only add if user is authenticated and is staff
    if hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff:
        notifications.append({
            'message': 'System update available',
            'icon': 'bi bi-info-circle',
            'url': '/system/updates/'
        })

    return {
        'notifications': notifications,
        'notifications_count': len(notifications)
    }



def notification_context(request):
    """Add notification data to all templates"""
    context = {}

    if request.user.is_authenticated:
        # Unread notification count
        context['unread_notifications_count'] = Notification.objects.filter(
            recipient=request.user,
            is_read=False
        ).count()

        # Active announcements
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

    return context