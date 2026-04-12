import json
import logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from pywebpush import webpush, WebPushException
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_push_to_user(self, user_id, title, body, url='/', icon=None, notification_type_code=None, schema_name=None):
    """
    Send a push notification to all active subscriptions of a user.
    schema_name must be passed explicitly — Celery workers start in public
    schema so we cannot look it up inside the task.
    """
    if not schema_name:
        logger.error(f"send_push_to_user called without schema_name for user {user_id} — skipping")
        return

    with schema_context(schema_name):
        from .models import PushSubscription, UserPushPreference, PushNotificationType

        # ── Check user preference if notification type is specified ──────────
        if notification_type_code:
            try:
                notif_type = PushNotificationType.objects.get(
                    code=notification_type_code, is_active=True
                )
                pref = UserPushPreference.objects.filter(
                    user_id=user_id,
                    notification_type=notif_type
                ).first()

                if not pref:
                    logger.debug(f"No preference for user {user_id} / {notification_type_code} — skipping")
                    return

                if not pref.enabled:
                    logger.debug(f"Preference disabled for user {user_id} / {notification_type_code} — skipping")
                    return

            except PushNotificationType.DoesNotExist:
                logger.warning(f"PushNotificationType '{notification_type_code}' not found in schema '{schema_name}'")
                return

        # ── Send to all active subscriptions ─────────────────────────────────
        subscriptions = PushSubscription.objects.filter(user_id=user_id, is_active=True)

        if not subscriptions.exists():
            logger.debug(f"No active subscriptions for user {user_id} in schema '{schema_name}'")
            return

        for subscription in subscriptions:
            try:
                webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {
                            "p256dh": subscription.p256dh,
                            "auth":   subscription.auth,
                        }
                    },
                    data=json.dumps({
                        "title":             title,
                        "body":              body,
                        "url":               url,
                        "icon":              icon or "/static/favicon/web-app-manifest-192x192.png",
                        "notification_type": notification_type_code or "default",
                    }),
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIMS_EMAIL}"}
                )

                subscription.last_used_at = timezone.now()
                subscription.save(update_fields=['last_used_at'])
                logger.info(f"Push sent to user {user_id} [{notification_type_code}] schema='{schema_name}'")

            except WebPushException as e:
                if e.response and e.response.status_code == 410:
                    subscription.is_active = False
                    subscription.save(update_fields=['is_active'])
                    logger.info(f"Deactivated expired subscription for user {user_id}")
                else:
                    logger.error(f"Push failed for user {user_id} in schema '{schema_name}': {e}")
                    try:
                        raise self.retry(exc=e)
                    except self.MaxRetriesExceededError:
                        logger.error(f"Max retries exceeded for push to user {user_id}")

            except Exception as e:
                logger.error(f"Unexpected error sending push to user {user_id}: {e}", exc_info=True)


@shared_task
def send_push_to_users_with_type(user_ids, title, body, url='/', icon=None, notification_type_code=None, schema_name=None):
    """
    Fan out push notifications to multiple users in the same schema.
    """
    for user_id in user_ids:
        send_push_to_user.delay(
            user_id, title, body, url, icon,
            notification_type_code, schema_name
        )


def notify_event(notification_type_code, title, body, url='/', icon=None):
    """
    Helper called from signals/views — always runs inside the correct
    tenant schema context so we can read schema_name from the connection.
    """
    from django.db import connection
    from .models import UserPushPreference

    schema_name = connection.schema_name

    if schema_name == 'public':
        logger.warning(f"notify_event called from public schema — skipping '{notification_type_code}'")
        return

    user_ids = list(
        UserPushPreference.objects.filter(
            notification_type__code=notification_type_code,
            notification_type__is_active=True,
            enabled=True,
            user__is_active=True,
        ).values_list('user_id', flat=True).distinct()
    )

    if not user_ids:
        logger.debug(f"notify_event: no subscribers for '{notification_type_code}' in schema '{schema_name}'")
        return

    logger.info(f"notify_event: sending '{notification_type_code}' to {len(user_ids)} user(s) in schema '{schema_name}'")

    send_push_to_users_with_type.delay(
        user_ids, title, body, url, icon,
        notification_type_code, schema_name
    )