"""
support_widget/tasks.py

Celery tasks for the support widget.

Tasks:
  send_offline_followup_email   — email visitor when no agent was available
  close_stale_sessions          — resolve sessions idle for > N hours
  cleanup_old_recordings        — delete recording files older than retention days

Add to settings.py CELERY_BEAT_SCHEDULE:

    'sw-close-stale-sessions': {
        'task': 'support_widget.tasks.close_stale_sessions',
        'schedule': crontab(minute=0, hour='*/2'),   # every 2 hours
    },
    'sw-cleanup-recordings': {
        'task': 'support_widget.tasks.cleanup_old_recordings',
        'schedule': crontab(hour=3, minute=30, day_of_week=0),  # Sunday 03:30
    },
"""

import logging
from celery import shared_task
from django.utils import timezone
from datetime   import timedelta

logger = logging.getLogger(__name__)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _iter_tenant_schemas():
    """
    Yield every active tenant schema name.
    Works with django-tenants: queries the public schema for all Company rows.
    """
    try:
        from django_tenants.utils import get_tenant_model
        TenantModel = get_tenant_model()
        for tenant in TenantModel.objects.exclude(schema_name='public'):
            yield tenant.schema_name
    except Exception as e:
        logger.warning("_iter_tenant_schemas failed: %s", e)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Offline follow-up email
# ═══════════════════════════════════════════════════════════════════════════════

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_offline_followup_email(self, schema_name: str, session_id: int):
    """
    Send an email to the visitor letting them know no agent was available
    and that the support team will follow up.

    Called immediately from SupportChatConsumer._handle_request_agent()
    when no agent is online.
    """
    try:
        from django_tenants.utils import schema_context
        from django.core.mail    import send_mail
        from django.conf         import settings

        with schema_context(schema_name):
            from .models import VisitorSession, SupportWidgetConfig

            session = VisitorSession.objects.get(pk=session_id)
            config  = SupportWidgetConfig.objects.filter(pk=1).first()

            if not session.visitor_email:
                logger.info("sw: no email for session %s — skipping followup", session_id)
                return

            support_email = getattr(config, 'offline_email', '') or settings.SUPPORT_EMAIL
            site_name     = settings.SITE_NAME

            subject = f"We received your support request — {site_name}"
            message = (
                f"Hi {session.visitor_name or 'there'},\n\n"
                f"Thanks for reaching out to {site_name} support.\n\n"
                f"Unfortunately all our agents were busy when you contacted us. "
                f"A member of our team will get back to you at this email address as soon as possible.\n\n"
                f"Your conversation reference: {session.session_token}\n\n"
                f"Best regards,\n{site_name} Support Team"
            )

            send_mail(
                subject      = subject,
                message      = message,
                from_email   = settings.DEFAULT_FROM_EMAIL,
                recipient_list = [session.visitor_email],
                fail_silently  = False,
            )
            logger.info("sw: offline followup email sent to %s", session.visitor_email)

    except Exception as exc:
        logger.error("sw: send_offline_followup_email failed: %s", exc)
        raise self.retry(exc=exc)


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Close stale sessions
# ═══════════════════════════════════════════════════════════════════════════════

@shared_task
def close_stale_sessions(idle_hours: int = 4):
    """
    Resolve sessions that have been in 'onboarding', 'faq', or 'escalated'
    status for longer than `idle_hours` without any message activity.
    Runs across all tenant schemas.
    """
    from django_tenants.utils import schema_context
    cutoff = timezone.now() - timedelta(hours=idle_hours)
    total  = 0

    for schema_name in _iter_tenant_schemas():
        try:
            with schema_context(schema_name):
                from .models import VisitorSession
                stale = VisitorSession.objects.filter(
                    status__in=['onboarding', 'faq', 'escalated'],
                    updated_at__lt=cutoff,
                )
                count = stale.count()
                stale.update(
                    status      = 'resolved',
                    resolved_at = timezone.now(),
                )
                if count:
                    logger.info("sw: closed %d stale sessions in schema=%s", count, schema_name)
                total += count
        except Exception as e:
            logger.warning("sw: close_stale_sessions failed for schema=%s: %s", schema_name, e)

    return f"Resolved {total} stale sessions across all tenants"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Clean up old call recordings
# ═══════════════════════════════════════════════════════════════════════════════

@shared_task
def cleanup_old_recordings(retain_days: int = 90):
    """
    Delete CallRecording files (and their DB rows) older than `retain_days`.
    Runs across all tenant schemas.
    Default retention: 90 days. Adjust to match your data policy.
    """
    from django_tenants.utils import schema_context
    import os
    cutoff = timezone.now() - timedelta(days=retain_days)
    total  = 0

    for schema_name in _iter_tenant_schemas():
        try:
            with schema_context(schema_name):
                from .models import CallRecording
                old = CallRecording.objects.filter(created_at__lt=cutoff)
                for rec in old:
                    try:
                        if rec.file and os.path.isfile(rec.file.path):
                            os.remove(rec.file.path)
                    except Exception as file_err:
                        logger.warning("sw: could not delete file %s: %s", rec.file, file_err)
                    rec.delete()
                    total += 1
        except Exception as e:
            logger.warning("sw: cleanup_old_recordings failed for schema=%s: %s", schema_name, e)

    return f"Deleted {total} old call recordings"


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Notify support team of missed sessions (daily digest)
# ═══════════════════════════════════════════════════════════════════════════════

@shared_task
def daily_missed_sessions_digest():
    """
    Send a daily summary email to the tenant's support address listing
    any sessions that were resolved without agent interaction (missed chats).
    Runs across all tenant schemas.
    """
    from django_tenants.utils import schema_context
    from django.core.mail    import send_mail
    from django.conf         import settings

    since   = timezone.now() - timedelta(hours=24)

    for schema_name in _iter_tenant_schemas():
        try:
            with schema_context(schema_name):
                from .models import VisitorSession, SupportWidgetConfig, ChatMessage

                config = SupportWidgetConfig.objects.filter(pk=1).first()
                if not config or not config.is_active:
                    continue

                support_email = getattr(config, 'offline_email', '') or settings.SUPPORT_EMAIL
                if not support_email:
                    continue

                # Sessions resolved with no agent message
                missed = []
                sessions = VisitorSession.objects.filter(
                    status='resolved',
                    resolved_at__gte=since,
                    visitor_email__isnull=False,
                ).exclude(visitor_email='')

                for s in sessions:
                    has_agent_msg = ChatMessage.objects.filter(
                        session=s, sender='agent'
                    ).exists()
                    if not has_agent_msg:
                        missed.append(s)

                if not missed:
                    continue

                lines = [f"  - {s.visitor_name or 'Anonymous'} <{s.visitor_email}>" for s in missed]
                body  = (
                    f"Daily Missed Support Sessions — {settings.SITE_NAME}\n\n"
                    f"The following {len(missed)} visitor(s) did not receive an agent response "
                    f"in the last 24 hours:\n\n"
                    + "\n".join(lines) +
                    "\n\nPlease follow up with them directly.\n"
                )
                send_mail(
                    subject        = f"[{settings.SITE_NAME}] {len(missed)} missed support session(s)",
                    message        = body,
                    from_email     = settings.DEFAULT_FROM_EMAIL,
                    recipient_list = [support_email],
                    fail_silently  = True,
                )
                logger.info("sw: sent missed sessions digest (%d) for schema=%s", len(missed), schema_name)

        except Exception as e:
            logger.warning("sw: daily_missed_sessions_digest failed for schema=%s: %s", schema_name, e)