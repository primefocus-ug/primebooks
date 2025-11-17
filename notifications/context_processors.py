import logging
from django.db import connection
from django.utils import timezone
from django.db.models import Q
from django.db import  models
from django_tenants.utils import get_public_schema_name

logger = logging.getLogger(__name__)

def notifications_context(request):
    """
    Schema-safe notifications context processor.
    Handles both public and tenant users.
    """
    context = {}

    public_schema = get_public_schema_name()
    current_schema = connection.schema_name

    # Default values
    context['unread_notifications_count'] = 0
    context['active_announcements'] = []
    context['low_stock_alert'] = 0
    context['new_users_count'] = 0

    # If user is authenticated
    if request.user.is_authenticated:
        # Public schema: skip tenant-specific queries
        if current_schema == public_schema:
            # You can add public-specific notifications here if needed
            context['public_notifications'] = []
        else:
            # Tenant schema: safe to query tenant models
            try:
                from inventory.models import Stock
                from accounts.models import CustomUser
                from notifications.models import Notification, Announcement

                # Unread notifications
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

                # Low stock items
                context['low_stock_alert'] = Stock.objects.filter(
                    quantity__lte=models.F('low_stock_threshold')
                ).count()

                # New users in last 24h
                context['new_users_count'] = CustomUser.objects.filter(
                    date_joined__gte=timezone.now() - timezone.timedelta(days=1)
                ).count()

            except Exception as tenant_error:
                logger.warning(
                    f"Error in notifications context processor for schema '{current_schema}': {tenant_error}"
                )

    # System update notification (optional, global)
    if hasattr(request, 'user') and request.user.is_authenticated and request.user.is_staff:
        context.setdefault('system_notifications', []).append({
            'message': 'System update available',
            'icon': 'bi bi-info-circle',
            'url': '/system/updates/'
        })

    return context
