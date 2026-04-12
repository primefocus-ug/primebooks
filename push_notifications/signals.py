import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings

logger = logging.getLogger(__name__)


def apply_role_push_defaults(user, role):
    """
    When a role is assigned to a user, create UserPushPreference records
    for all notification types that role has as defaults.
    Skips types the user already has a preference for (preserves overrides).
    """
    from .models import RoleNotificationDefault, UserPushPreference

    defaults = RoleNotificationDefault.objects.filter(
        role=role
    ).select_related('notification_type')

    for default in defaults:
        UserPushPreference.objects.get_or_create(
            user=user,
            notification_type=default.notification_type,
            defaults={'enabled': True}
        )
        # get_or_create means existing preferences are never overwritten


def handle_sale_created(sale):
    """Hook for sale_created event."""
    from .tasks import notify_event
    notify_event(
        notification_type_code='sale_created',
        title='New Sale Created',
        body=f"Sale #{sale.id} — {getattr(sale, 'total', '')}",
        url=f"/sales/{sale.id}/",
    )


# Example: hook into your Sale model
# Add more hooks here as you add notification types
try:
    from sales.models import Sale

    @receiver(post_save, sender=Sale)
    def on_sale_created(sender, instance, created, **kwargs):
        if not created:
            return
        from django.db import connection
        if connection.schema_name == 'public':
            return
        handle_sale_created(instance)

except ImportError:
    pass