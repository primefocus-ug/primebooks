import logging
import threading
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django.db import connection
from django_tenants.utils import schema_context

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# FIREBASE INITIALISATION
# Guarded by a lock so concurrent Celery workers don't double-initialise.
# ─────────────────────────────────────────────────────────────────────────────

import firebase_admin
from firebase_admin import credentials, messaging

_firebase_app = None
_firebase_lock = threading.Lock()


def _get_firebase_app():
    global _firebase_app
    if _firebase_app is None:
        with _firebase_lock:
            # Double-checked locking: re-test after acquiring the lock.
            if _firebase_app is None:
                cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
                _firebase_app = firebase_admin.initialize_app(cred)
    return _firebase_app


# ─────────────────────────────────────────────────────────────────────────────
# INTERNAL HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_current_schema():
    """Safely return the current DB schema name (django-tenants only)."""
    return getattr(connection, 'schema_name', None)


def _do_fcm_push(subscription, payload: dict) -> bool:
    """
    Send a single FCM push message to one device token.
    Returns True on success.
    Raises messaging.UnregisteredError if the token is expired/invalid
    (caller should deactivate the subscription).
    Raises other exceptions for transient failures (caller may retry).
    """
    _get_firebase_app()  # ensure initialised

    notification_type = payload.get('notification_type', 'default')

    message = messaging.Message(
        notification=messaging.Notification(
            title=payload.get('title', 'PrimeBooks'),
            body=payload.get('body', ''),
        ),
        data={
            # All values must be strings for FCM data payload
            'url':               payload.get('url', '/'),
            'notification_type': notification_type,
            'icon':              payload.get('icon', ''),
        },
        webpush=messaging.WebpushConfig(
            notification=messaging.WebpushNotification(
                icon=payload.get('icon', '/static/favicon/web-app-manifest-192x192.png'),
                badge='/static/favicon/favicon-96x96.png',
                vibrate=[200, 100, 200],
                tag=notification_type,
                renotify=True,
                custom_data={
                    'url': payload.get('url', '/'),
                    'sound': notification_type,
                },
            ),
            fcm_options=messaging.WebpushFCMOptions(
                link=payload.get('url', '/'),
            ),
        ),
        token=subscription.fcm_token,
    )

    messaging.send(message)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# CORE TASK: send to a single user
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_push_to_user(
    self,
    user_id,
    title,
    body,
    url='/',
    icon=None,
    notification_type_code=None,
    schema_name=None,
):
    """
    Send a push notification to every active FCM subscription of a single user.

    schema_name MUST be passed — Celery workers start in the public schema so
    we cannot infer it from the connection inside the task.
    """
    if not schema_name:
        logger.error(
            f"send_push_to_user called without schema_name for user {user_id} — skipping"
        )
        return {'success': False, 'reason': 'missing schema_name'}

    with schema_context(schema_name):
        from .models import PushSubscription, UserPushPreference, PushNotificationType

        # ── 1. Respect per-user notification preference ───────────────────────
        if notification_type_code:
            try:
                notif_type = PushNotificationType.objects.get(
                    code=notification_type_code,
                    is_active=True,
                )
            except PushNotificationType.DoesNotExist:
                logger.warning(
                    f"PushNotificationType '{notification_type_code}' not found "
                    f"or inactive in schema '{schema_name}' — skipping user {user_id}"
                )
                return {'success': False, 'reason': 'notification_type_not_found'}

            pref = UserPushPreference.objects.filter(
                user_id=user_id,
                notification_type=notif_type,
            ).first()

            if pref is None:
                logger.debug(
                    f"No UserPushPreference for user {user_id} / "
                    f"'{notification_type_code}' in '{schema_name}' — skipping"
                )
                return {'success': False, 'reason': 'no_preference'}

            if not pref.enabled:
                logger.debug(
                    f"Preference disabled for user {user_id} / "
                    f"'{notification_type_code}' — skipping"
                )
                return {'success': False, 'reason': 'preference_disabled'}

        # ── 2. Fetch active subscriptions with a valid FCM token ──────────────
        subscriptions = list(
            PushSubscription.objects.filter(
                user_id=user_id,
                is_active=True,
            ).exclude(fcm_token='')
        )

        if not subscriptions:
            logger.debug(
                f"No active FCM subscription for user {user_id} in '{schema_name}'"
            )
            return {'success': False, 'reason': 'no_active_subscription'}

        payload = {
            'title':             title,
            'body':              body,
            'url':               url,
            'icon':              icon or '/static/favicon/web-app-manifest-192x192.png',
            'notification_type': notification_type_code or 'default',
        }

        sent = 0
        failed = 0
        transient_errors = []

        # ── 3. Send to every subscription ─────────────────────────────────────
        for sub in subscriptions:
            try:
                _do_fcm_push(sub, payload)

                sub.last_used_at = timezone.now()
                sub.save(update_fields=['last_used_at'])

                logger.info(
                    f"FCM push sent → user={user_id} type='{notification_type_code}' "
                    f"schema='{schema_name}' token={sub.fcm_token[:40]}…"
                )
                sent += 1

            except (messaging.UnregisteredError, messaging.SenderIdMismatchError) as exc:
                # Token is permanently invalid — deactivate and don't retry.
                sub.is_active = False
                sub.save(update_fields=['is_active'])
                logger.info(
                    f"Deactivated invalid FCM token {sub.id} for user {user_id} "
                    f"({type(exc).__name__})"
                )
                failed += 1

            except Exception as exc:
                # Transient failure — record it but finish the loop first so we
                # don't re-send to already-successful subscriptions on retry.
                logger.error(
                    f"FCM error for user {user_id} sub {sub.id}: {exc}",
                    exc_info=True,
                )
                failed += 1
                transient_errors.append(exc)

        # Retry the whole task only if ALL sends failed transiently (nothing
        # succeeded, and at least one transient error occurred). This avoids
        # duplicate sends to subscriptions that already delivered.
        if transient_errors and sent == 0:
            try:
                raise self.retry(exc=transient_errors[-1])
            except self.MaxRetriesExceededError:
                logger.error(
                    f"Max retries exceeded for FCM push to user {user_id}"
                )

        return {
            'success': sent > 0,
            'sent': sent,
            'failed': failed,
            'user_id': user_id,
            'schema': schema_name,
        }


# ─────────────────────────────────────────────────────────────────────────────
# FAN-OUT TASK: send to many users
# ─────────────────────────────────────────────────────────────────────────────

@shared_task
def send_push_to_users_with_type(
    user_ids,
    title,
    body,
    url='/',
    icon=None,
    notification_type_code=None,
    schema_name=None,
):
    """Fan out individual send_push_to_user tasks for a list of user IDs."""
    for user_id in user_ids:
        send_push_to_user.delay(
            user_id=user_id,
            title=title,
            body=body,
            url=url,
            icon=icon,
            notification_type_code=notification_type_code,
            schema_name=schema_name,
        )

    logger.info(
        f"Queued FCM push for {len(user_ids)} user(s) "
        f"type='{notification_type_code}' schema='{schema_name}'"
    )
    return {'queued': len(user_ids)}


# ─────────────────────────────────────────────────────────────────────────────
# HELPER: notify all eligible users for an event type
# ─────────────────────────────────────────────────────────────────────────────

def notify_event(
    notification_type_code: str,
    title: str,
    body: str,
    url: str = '/',
    icon: str = None,
):
    """
    Collect all users who should receive this notification type, then fan-out.

    IMPORTANT — this function MUST be called while Django is already operating
    in the correct tenant schema (e.g. inside a signal that fired on a tenant
    model save, or inside `with schema_context(schema_name):`).
    """
    from .models import UserPushPreference, PushNotificationType, PushSubscription

    schema_name = _get_current_schema()

    if not schema_name or schema_name == 'public':
        logger.warning(
            f"notify_event('{notification_type_code}') called from public schema "
            f"or no schema — skipping"
        )
        return

    # ── Auto-provision notification type if missing ───────────────────────────
    try:
        notif_type, created = PushNotificationType.objects.get_or_create(
            code=notification_type_code,
            defaults={
                'name':        notification_type_code.replace('_', ' ').title(),
                'description': f'Auto-created for event: {notification_type_code}',
                'is_active':   True,
            },
        )
        if created:
            logger.info(
                f"Auto-created PushNotificationType '{notification_type_code}' "
                f"in schema '{schema_name}'"
            )
        elif not notif_type.is_active:
            logger.debug(
                f"PushNotificationType '{notification_type_code}' is inactive — skipping"
            )
            return
    except Exception as exc:
        logger.error(
            f"Failed to get/create PushNotificationType '{notification_type_code}': {exc}",
            exc_info=True,
        )
        return

    # ── Auto-provision preferences for users who have subscriptions ───────────
    try:
        subscribed_user_ids = set(
            PushSubscription.objects.filter(is_active=True).exclude(fcm_token='')
            .values_list('user_id', flat=True)
            .distinct()
        )

        existing_pref_user_ids = set(
            UserPushPreference.objects.filter(
                notification_type=notif_type,
            ).values_list('user_id', flat=True)
        )

        missing_user_ids = subscribed_user_ids - existing_pref_user_ids
        if missing_user_ids:
            prefs_to_create = [
                UserPushPreference(
                    user_id=uid,
                    notification_type=notif_type,
                    enabled=True,
                )
                for uid in missing_user_ids
            ]
            UserPushPreference.objects.bulk_create(
                prefs_to_create,
                ignore_conflicts=True,
            )
            logger.info(
                f"Auto-provisioned UserPushPreference for {len(missing_user_ids)} "
                f"user(s) in schema '{schema_name}' for type '{notification_type_code}'"
            )
    except Exception as exc:
        logger.warning(
            f"Could not auto-provision preferences for '{notification_type_code}': {exc}"
        )

    # ── Collect eligible user IDs ─────────────────────────────────────────────
    try:
        user_ids = list(
            UserPushPreference.objects.filter(
                notification_type=notif_type,
                enabled=True,
                user__is_active=True,
            )
            .values_list('user_id', flat=True)
            .distinct()
        )
    except Exception as exc:
        logger.error(
            f"Failed to query UserPushPreference for '{notification_type_code}': {exc}",
            exc_info=True,
        )
        return

    if not user_ids:
        logger.debug(
            f"notify_event: no enabled subscribers for '{notification_type_code}' "
            f"in schema '{schema_name}'"
        )
        return

    # ── Cross-check: only send to users who have active FCM subscriptions ──────
    subscribed_ids = list(
        PushSubscription.objects.filter(
            user_id__in=user_ids,
            is_active=True,
        ).exclude(fcm_token='')
        .values_list('user_id', flat=True)
        .distinct()
    )

    if not subscribed_ids:
        logger.debug(
            f"notify_event: {len(user_ids)} user(s) have preferences but no active "
            f"FCM subscriptions for '{notification_type_code}' in '{schema_name}'"
        )
        return

    logger.info(
        f"notify_event: dispatching '{notification_type_code}' to "
        f"{len(subscribed_ids)} user(s) in schema '{schema_name}'"
    )

    send_push_to_users_with_type.delay(
        subscribed_ids,
        title,
        body,
        url,
        icon,
        notification_type_code,
        schema_name,
    )


# ─────────────────────────────────────────────────────────────────────────────
# MAINTENANCE TASK: clean up dead subscriptions
# ─────────────────────────────────────────────────────────────────────────────

@shared_task
def cleanup_inactive_subscriptions(schema_name=None):
    """
    Remove PushSubscription rows that have been inactive for more than 90 days.
    Safe to run as a periodic Celery beat task across all tenants.
    """
    from django_tenants.utils import get_tenant_model

    cutoff = timezone.now() - timezone.timedelta(days=90)

    if schema_name:
        schemas = [schema_name]
    else:
        with schema_context('public'):
            schemas = list(
                get_tenant_model().objects
                .exclude(schema_name='public')
                .values_list('schema_name', flat=True)
            )

    total_deleted = 0

    for s in schemas:
        try:
            with schema_context(s):
                from .models import PushSubscription
                deleted, _ = PushSubscription.objects.filter(
                    is_active=False,
                    last_used_at__lt=cutoff,
                ).delete()
                if deleted:
                    logger.info(
                        f"cleanup_inactive_subscriptions: removed {deleted} "
                        f"stale subscriptions from '{s}'"
                    )
                total_deleted += deleted
        except Exception as exc:
            logger.error(
                f"cleanup_inactive_subscriptions failed for schema '{s}': {exc}"
            )

    return {'deleted': total_deleted, 'schemas_processed': len(schemas)}


# ─────────────────────────────────────────────────────────────────────────────
# TEST HELPER
# ─────────────────────────────────────────────────────────────────────────────

@shared_task
def send_test_push(user_id, schema_name):
    """
    Trigger from a Django view or the shell to verify end-to-end delivery.
    Runs send_push_to_user directly (synchronously within this worker).

    Usage (Django shell):
        from push_notifications.tasks import send_test_push
        send_test_push.delay(user_id=1, schema_name='your_tenant_schema')
    """
    return send_push_to_user(
        user_id=user_id,
        title='PrimeBooks Test 🔔',
        body='Push notifications are working correctly!',
        url='/',
        icon='/static/favicon/web-app-manifest-192x192.png',
        notification_type_code=None,
        schema_name=schema_name,
    )