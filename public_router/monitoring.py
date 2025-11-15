from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


def track_signup_metrics(signup_request):
    """Track signup metrics in cache for monitoring"""

    today = timezone.now().date()
    hour = timezone.now().hour

    # Increment counters
    cache.incr(f'signups_total_{today}', 1)
    cache.incr(f'signups_hour_{today}_{hour}', 1)
    cache.incr(f'signups_plan_{signup_request.selected_plan}_{today}', 1)

    # Set expiry (keep for 7 days)
    cache.expire(f'signups_total_{today}', 86400 * 7)
    cache.expire(f'signups_hour_{today}_{hour}', 86400 * 7)
    cache.expire(f'signups_plan_{signup_request.selected_plan}_{today}', 86400 * 7)


def check_signup_health():
    """
    Check signup system health.
    Call this from a monitoring endpoint or Celery task.
    """

    from .models import TenantSignupRequest

    issues = []

    # Check for stale processing requests
    stale_cutoff = timezone.now() - timedelta(minutes=10)
    stale_count = TenantSignupRequest.objects.filter(
        status='PROCESSING',
        updated_at__lt=stale_cutoff
    ).count()

    if stale_count > 0:
        issues.append(f"{stale_count} stale processing requests detected")

    # Check failed signup rate
    recent_cutoff = timezone.now() - timedelta(hours=1)
    recent_signups = TenantSignupRequest.objects.filter(
        created_at__gte=recent_cutoff
    )

    total_recent = recent_signups.count()
    failed_recent = recent_signups.filter(status='FAILED').count()

    if total_recent > 0:
        failure_rate = (failed_recent / total_recent) * 100
        if failure_rate > 20:  # More than 20% failing
            issues.append(f"High failure rate: {failure_rate:.1f}%")

    # Check Celery queue length
    try:
        from celery import current_app
        inspect = current_app.control.inspect()
        active = inspect.active()

        if active:
            queue_length = sum(len(tasks) for tasks in active.values())
            if queue_length > 50:
                issues.append(f"High Celery queue length: {queue_length}")
    except Exception as e:
        logger.warning(f"Could not check Celery queue: {str(e)}")

    # Check database connections
    from django.db import connection
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as e:
        issues.append(f"Database connection issue: {str(e)}")

    return {
        'healthy': len(issues) == 0,
        'issues': issues,
        'metrics': {
            'stale_processing': stale_count,
            'recent_total': total_recent,
            'recent_failed': failed_recent,
        }
    }


def alert_on_high_failure_rate():
    """
    Alert administrators when signup failure rate is high.
    Call this from Celery Beat every 15 minutes.
    """

    health = check_signup_health()

    if not health['healthy']:
        # Send alert (email, Slack, PagerDuty, etc.)
        logger.critical(
            f"Signup system health check failed: {health['issues']}",
            extra={'metrics': health['metrics']}
        )

        # Example: Send email to admins
        from django.core.mail import mail_admins
        from django.conf import settings

        subject = "⚠️ Signup System Health Alert"
        message = f"""
        The signup system is experiencing issues:

        Issues:
        {chr(10).join(f'- {issue}' for issue in health['issues'])}

        Metrics:
        - Stale processing: {health['metrics']['stale_processing']}
        - Recent signups: {health['metrics']['recent_total']}
        - Recent failures: {health['metrics']['recent_failed']}

        Please investigate immediately.
        """

        mail_admins(subject, message, fail_silently=True)