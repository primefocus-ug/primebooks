import json
import logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from pywebpush import webpush, WebPushException
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)


def _get_user_schema(user_id):
    """
    Get the tenant schema for a user.
    Must be called outside schema_context since it looks up the user's company.
    """
    from django.contrib.auth import get_user_model
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
        return user.company.schema_name
    except (User.DoesNotExist, AttributeError):
        return None


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_push_to_user(self, user_id, title, body, url='/', icon=None, notification_type_code=None):
    """
    Send a push notification to all active subscriptions of a user.
    Wraps all DB access in the correct tenant schema_context so Celery
    workers (which start in public schema) query the right tables.
    """
    schema = _get_user_schema(user_id)
    if not schema:
        logger.warning(f"Could not determine schema for user {user_id} — skipping push")
        return

    with schema_context(schema):
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
                logger.warning(f"PushNotificationType '{notification_type_code}' not found in schema '{schema}'")
                return

        # ── Send to all active subscriptions ─────────────────────────────────
        subscriptions = PushSubscription.objects.filter(user_id=user_id, is_active=True)

        if not subscriptions.exists():
            logger.debug(f"No active subscriptions for user {user_id} in schema '{schema}'")
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
                logger.info(f"Push sent to user {user_id} [{notification_type_code}] in schema '{schema}'")

            except WebPushException as e:
                if e.response and e.response.status_code == 410:
                    # Subscription expired — deactivate it
                    subscription.is_active = False
                    subscription.save(update_fields=['is_active'])
                    logger.info(f"Deactivated expired subscription for user {user_id}")
                else:
                    logger.error(f"Push failed for user {user_id} in schema '{schema}': {e}")
                    try:
                        raise self.retry(exc=e)
                    except self.MaxRetriesExceededError:
                        logger.error(f"Max retries exceeded for push to user {user_id}")

            except Exception as e:
                logger.error(f"Unexpected error sending push to user {user_id}: {e}", exc_info=True)


@shared_task
def send_push_to_users_with_type(user_ids, title, body, url='/', icon=None, notification_type_code=None):
    """
    Fan out push notifications to multiple users.
    Each user gets an individual task so one failure doesn't block others.
    """
    for user_id in user_ids:
        send_push_to_user.delay(user_id, title, body, url, icon, notification_type_code)


def notify_event(notification_type_code, title, body, url='/', icon=None):
    """
    Helper called from signals/views.
    Finds all users subscribed to the given notification type and sends them a push.
    Must be called from within the correct schema context (signals always are).
    """
    from .models import UserPushPreference

    user_ids = list(
        UserPushPreference.objects.filter(
            notification_type__code=notification_type_code,
            notification_type__is_active=True,
            enabled=True,
            user__is_active=True,
        ).values_list('user_id', flat=True).distinct()
    )

    if not user_ids:
        logger.debug(f"notify_event: no subscribers for '{notification_type_code}'")
        return

    logger.info(f"notify_event: sending '{notification_type_code}' to {len(user_ids)} user(s)")
    send_push_to_users_with_type.delay(
        user_ids, title, body, url, icon, notification_type_code
    )