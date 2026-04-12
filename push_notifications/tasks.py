import json
import logging
from celery import shared_task
from django.conf import settings
from pywebpush import webpush, WebPushException

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_push_to_user(self, user_id, title, body, url='/', icon=None, notification_type_code=None):
    """
    Send a push notification to all active subscriptions of a user.
    Only sends if user has this notification type enabled.
    """
    from .models import PushSubscription, UserPushPreference, PushNotificationType

    # Check user preference if notification type is specified
    if notification_type_code:
        try:
            notif_type = PushNotificationType.objects.get(code=notification_type_code, is_active=True)
            pref = UserPushPreference.objects.filter(
                user_id=user_id,
                notification_type=notif_type
            ).first()
            # If preference exists and is disabled, skip silently
            if pref and not pref.enabled:
                return
            # If no preference exists at all, also skip (not subscribed to this type)
            if not pref:
                return
        except PushNotificationType.DoesNotExist:
            logger.warning(f"PushNotificationType '{notification_type_code}' not found")
            return

    subscriptions = PushSubscription.objects.filter(user_id=user_id, is_active=True)

    for subscription in subscriptions:
        try:
            webpush(
                subscription_info={
                    "endpoint": subscription.endpoint,
                    "keys": {
                        "p256dh": subscription.p256dh,
                        "auth": subscription.auth,
                    }
                },
                data=json.dumps({
                    "title": title,
                    "body": body,
                    "url": url,
                    "icon": icon or "/static/favicon/web-app-manifest-192x192.png",
                    "notification_type": notification_type_code or "default",
                }),
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{settings.VAPID_CLAIMS_EMAIL}"}
            )
            subscription.last_used_at = __import__('django.utils.timezone', fromlist=['timezone']).timezone.now()
            subscription.save(update_fields=['last_used_at'])

        except WebPushException as e:
            if e.response and e.response.status_code == 410:
                # Subscription expired — deactivate it
                subscription.is_active = False
                subscription.save(update_fields=['is_active'])
                logger.info(f"Deactivated expired subscription for user {user_id}")
            else:
                logger.error(f"Push failed for user {user_id}: {e}")
                try:
                    raise self.retry(exc=e)
                except self.MaxRetriesExceededError:
                    logger.error(f"Max retries exceeded for push to user {user_id}")


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
    Helper to call from signals/views. Finds all users subscribed
    to the given notification type and sends them a push.
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
    if user_ids:
        send_push_to_users_with_type.delay(
            user_ids, title, body, url, icon, notification_type_code
        )