# ============================================================
# sales/tasks_price_control.py  (new file)
# ============================================================
# Add to CELERY_IMPORTS or just ensure this file is auto-discovered
# via your existing celery app (it will be if sales is in INSTALLED_APPS
# and you use autodiscover_tasks).
# ============================================================

import logging
from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Helper: get all admin users for the current tenant ───────────────────────

def _get_tenant_admins(store):
    """
    Return QuerySet of active company_admin users for the store's company.
    Works inside a tenant schema context (django-tenants).
    """
    from accounts.models import CustomUser
    return CustomUser.objects.filter(
        company=store.company,
        company_admin=True,
        is_active=True,
        is_hidden=False,
    ).select_related('company')


# ── Main task ─────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def notify_admins_price_reduction(self, request_id, schema_name):
    """
    Async task fired when a PriceReductionRequest is created.
    Sends:
        1. Email to every tenant admin
        2. Firebase push to every tenant admin

    Args:
        request_id  : UUID string of the PriceReductionRequest
        schema_name : tenant schema name (for django-tenants context)
    """
    try:
        # ── Set tenant context ────────────────────────────────────────────
        from django_tenants.utils import schema_context
        with schema_context(schema_name):
            _run_notify(request_id)

    except Exception as exc:
        logger.error(f'notify_admins_price_reduction failed for {request_id}: {exc}', exc_info=True)
        raise self.retry(exc=exc)


def _run_notify(request_id):
    from sales.models import PriceReductionRequest

    try:
        req = PriceReductionRequest.objects.select_related(
            'employee', 'store', 'store__company'
        ).get(id=request_id)
    except PriceReductionRequest.DoesNotExist:
        logger.warning(f'PriceReductionRequest {request_id} not found — skipping notify')
        return

    if req.status != PriceReductionRequest.STATUS_PENDING:
        logger.info(f'Request {request_id} is no longer PENDING — skipping notify')
        return

    admins = _get_tenant_admins(req.store)
    if not admins.exists():
        logger.warning(f'No admins found for store {req.store_id} — skipping notify')
        return

    email_ok = _send_emails(req, admins)
    push_ok  = _send_firebase_push(req, admins)

    # Update flags
    update_fields = ['updated_at']
    if email_ok:
        req.email_sent = True
        update_fields.append('email_sent')
    if push_ok:
        req.push_sent = True
        update_fields.append('push_sent')
    req.save(update_fields=update_fields)


# ── Email ─────────────────────────────────────────────────────────────────────

def _send_emails(req, admins):
    """Send approval-request email to all admins. Returns True if at least one sent."""
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    from django.conf import settings as django_settings

    approve_url = _build_approval_url(req, 'approve')
    reject_url  = _build_approval_url(req, 'reject')

    subject = (
        f'[{req.store.company.name}] Price reduction approval needed — '
        f'{req.item_name} ({req.reduction_pct}% off)'
    )

    context = {
        'req':         req,
        'approve_url': approve_url,
        'reject_url':  reject_url,
        'company':     req.store.company,
    }

    # Plain-text fallback (always works even without template)
    text_body = (
        f'Price Reduction Approval Request\n\n'
        f'Employee : {req.employee.get_full_name() or req.employee.email}\n'
        f'Store    : {req.store.name}\n'
        f'Item     : {req.item_name}\n'
        f'Original : {req.store.company.currency if hasattr(req.store.company, "currency") else ""} {req.original_price}\n'
        f'Requested: {req.requested_price} ({req.reduction_pct}% reduction)\n'
        f'Quantity : {req.quantity}\n'
        f'Note     : {req.employee_note or "None"}\n\n'
        f'APPROVE: {approve_url}\n'
        f'REJECT : {reject_url}\n\n'
        f'This request expires in 30 minutes.'
    )

    # Try HTML template — fall back silently to plain text if missing
    try:
        html_body = render_to_string('sales/emails/price_reduction_request.html', context)
    except Exception:
        html_body = None

    from_email = getattr(django_settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com')
    recipient_list = list(admins.values_list('email', flat=True))

    sent = False
    try:
        send_mail(
            subject=subject,
            message=text_body,
            html_message=html_body,
            from_email=from_email,
            recipient_list=recipient_list,
            fail_silently=False,
        )
        logger.info(f'Price reduction email sent to {recipient_list} for request {req.id}')
        sent = True
    except Exception as e:
        logger.error(f'Email send failed for request {req.id}: {e}')

    return sent


def _build_approval_url(req, action):
    """Build an absolute URL for approve/reject action links in email."""
    from django.conf import settings as django_settings
    base = getattr(django_settings, 'SITE_BASE_URL', 'https://yourdomain.com')
    return f'{base}/sales/price-reduction-requests/{req.id}/{action}/?token={req.id}'


# ── Firebase Push ─────────────────────────────────────────────────────────────

def _send_firebase_push(req, admins):
    """
    Send Firebase Cloud Messaging push notification to all admin devices.
    Reads FCM tokens from each admin's metadata['fcm_tokens'] list.
    Returns True if at least one push was attempted without error.
    """
    import requests
    from django.conf import settings as django_settings

    # ── REPLACE THIS with your actual Firebase project credentials ────────
    FCM_SERVER_KEY = getattr(django_settings, 'FIREBASE_SERVER_KEY', 'YOUR_FIREBASE_SERVER_KEY')
    FCM_URL        = 'https://fcm.googleapis.com/fcm/send'
    # ─────────────────────────────────────────────────────────────────────

    tokens = []
    for admin in admins:
        # Store FCM tokens in user.metadata['fcm_tokens'] = [token1, token2, ...]
        # These are registered from the frontend service worker (see firebase_init.js)
        fcm_tokens = admin.metadata.get('fcm_tokens', [])
        tokens.extend(fcm_tokens)

    if not tokens:
        logger.info(f'No FCM tokens found for admins of store {req.store_id}')
        return False

    payload = {
        'registration_ids': tokens,
        'notification': {
            'title': f'Price approval needed — {req.store.name}',
            'body': (
                f'{req.employee.get_full_name() or req.employee.email} wants to sell '
                f'{req.item_name} at {req.requested_price} '
                f'(was {req.original_price}, {req.reduction_pct}% off)'
            ),
            'icon':  '/static/img/logo_192.png',   # replace with your actual icon path
            'click_action': f'/sales/price-reduction-requests/?status=PENDING',
        },
        'data': {
            'request_id':     str(req.id),
            'type':           'price_reduction_request',
            'cart_item_key':  req.cart_item_key,
            'item_name':      req.item_name,
            'original_price': str(req.original_price),
            'requested_price':str(req.requested_price),
            'employee_name':  req.employee.get_full_name() or req.employee.email,
            'store_id':       str(req.store_id),
        },
    }

    headers = {
        'Authorization': f'key={FCM_SERVER_KEY}',
        'Content-Type': 'application/json',
    }

    try:
        resp = requests.post(FCM_URL, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        logger.info(f'FCM push sent for request {req.id}: {result}')

        # Clean up invalid tokens from admin.metadata
        _cleanup_invalid_fcm_tokens(admins, tokens, result.get('results', []))
        return True
    except Exception as e:
        logger.error(f'FCM push failed for request {req.id}: {e}')
        return False


def _cleanup_invalid_fcm_tokens(admins, tokens, results):
    """Remove tokens FCM says are invalid/unregistered."""
    invalid_tokens = set()
    for token, result in zip(tokens, results):
        if result.get('error') in ('InvalidRegistration', 'NotRegistered'):
            invalid_tokens.add(token)

    if not invalid_tokens:
        return

    for admin in admins:
        current = admin.metadata.get('fcm_tokens', [])
        cleaned = [t for t in current if t not in invalid_tokens]
        if len(cleaned) != len(current):
            admin.metadata['fcm_tokens'] = cleaned
            admin.save(update_fields=['metadata'])


# ── Expiry task (run via Celery Beat every 5 minutes) ────────────────────────

@shared_task
def expire_stale_price_reduction_requests():
    """
    Expire PENDING requests older than 30 minutes.
    Schedule this in CELERY_BEAT_SCHEDULE:

        'expire-price-requests': {
            'task': 'sales.tasks_price_control.expire_stale_price_reduction_requests',
            'schedule': crontab(minute='*/5'),
        },

    NOTE: This task must be called with tenant context if you use a
    per-tenant beat scheduler. If you run a shared beat, loop over tenants:
    """
    from django_tenants.utils import get_tenant_model, schema_context

    TenantModel = get_tenant_model()
    cutoff = timezone.now() - timezone.timedelta(minutes=30)

    for tenant in TenantModel.objects.exclude(schema_name='public'):
        try:
            with schema_context(tenant.schema_name):
                from sales.models import PriceReductionRequest
                stale = PriceReductionRequest.objects.filter(
                    status=PriceReductionRequest.STATUS_PENDING,
                    created_at__lt=cutoff,
                )
                for req in stale:
                    req.expire()
                    logger.info(f'Expired request {req.id} in schema {tenant.schema_name}')
        except Exception as e:
            logger.error(f'Error expiring requests in {tenant.schema_name}: {e}')