from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


def safe_cache_incr(key, delta=1, default=0, timeout=None):
    """
    Safely increment a cache key, initializing it if it doesn't exist.

    Args:
        key: Cache key to increment
        delta: Amount to increment by (default 1)
        default: Initial value if key doesn't exist (default 0)
        timeout: Expiry time in seconds

    Returns:
        New value after increment
    """
    try:
        # Try to increment
        return cache.incr(key, delta)
    except ValueError:
        # Key doesn't exist (or stores a non-integer) — initialize it
        cache.set(key, default + delta, timeout)
        return default + delta
    except Exception as e:
        # Other cache errors (connection issues, serialization, etc.) — log and continue.
        # Monitoring failures must never crash the signup flow.
        logger.warning(f"Cache operation failed for key {key} ({type(e).__name__}): {str(e)}")
        return default + delta


def track_signup_metrics(signup_request):
    """Track signup metrics in cache for monitoring"""

    try:
        today = timezone.now().date()
        hour = timezone.now().hour

        # 7 days expiry
        timeout = 86400 * 7

        # Increment counters with safe method
        safe_cache_incr(f'signups_total_{today}', 1, 0, timeout)
        safe_cache_incr(f'signups_hour_{today}_{hour}', 1, 0, timeout)
        safe_cache_incr(f'signups_plan_{signup_request.selected_plan}_{today}', 1, 0, timeout)

        # Track by country if available
        if hasattr(signup_request, 'country') and signup_request.country:
            safe_cache_incr(f'signups_country_{signup_request.country}_{today}', 1, 0, timeout)

        logger.debug(f"Tracked metrics for signup: {signup_request.request_id}")

    except Exception as e:
        # Don't let metrics tracking break the signup process
        logger.warning(f"Failed to track signup metrics: {str(e)}")


def get_signup_metrics(date=None):
    """
    Get signup metrics for a specific date.

    Args:
        date: Date to get metrics for (defaults to today)

    Returns:
        Dictionary with signup metrics
    """
    if date is None:
        date = timezone.now().date()

    try:
        total = cache.get(f'signups_total_{date}', 0)

        # Get hourly breakdown
        hourly = {}
        for hour in range(24):
            count = cache.get(f'signups_hour_{date}_{hour}', 0)
            if count > 0:
                hourly[hour] = count

        # Get plan breakdown
        plans = {}
        for plan in ['FREE', 'STARTER', 'PROFESSIONAL', 'ENTERPRISE']:
            count = cache.get(f'signups_plan_{plan}_{date}', 0)
            if count > 0:
                plans[plan] = count

        return {
            'date': str(date),
            'total': total,
            'hourly': hourly,
            'by_plan': plans,
        }
    except Exception as e:
        logger.error(f"Failed to get signup metrics: {str(e)}")
        return {
            'date': str(date),
            'total': 0,
            'hourly': {},
            'by_plan': {},
            'error': str(e)
        }


def check_signup_health():
    """
    Check signup system health.
    Call this from a monitoring endpoint or Celery task.
    """

    from .models import TenantSignupRequest

    issues = []

    try:
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

        # Check pending requests stuck too long
        pending_cutoff = timezone.now() - timedelta(minutes=5)
        stuck_pending = TenantSignupRequest.objects.filter(
            status='PENDING',
            created_at__lt=pending_cutoff
        ).count()

        if stuck_pending > 0:
            issues.append(f"{stuck_pending} pending requests stuck for >5 minutes")

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

        # Check cache connectivity
        try:
            cache.set('health_check_test', 1, 60)
            test_value = cache.get('health_check_test')
            if test_value != 1:
                issues.append("Cache read/write test failed")
        except Exception as e:
            issues.append(f"Cache connection issue: {str(e)}")

        return {
            'healthy': len(issues) == 0,
            'issues': issues,
            'metrics': {
                'stale_processing': stale_count,
                'stuck_pending': stuck_pending,
                'recent_total': total_recent,
                'recent_failed': failed_recent,
                'failure_rate': round((failed_recent / total_recent * 100), 2) if total_recent > 0 else 0,
            }
        }

    except Exception as e:
        logger.error(f"Health check failed: {str(e)}", exc_info=True)
        return {
            'healthy': False,
            'issues': [f"Health check error: {str(e)}"],
            'metrics': {}
        }


def alert_on_high_failure_rate():
    """
    Alert administrators when signup failure rate is high.
    Call this from Celery Beat every 15 minutes.
    """

    try:
        health = check_signup_health()

        # Note: health['healthy'] is False only when failure_rate > 20% of *recent* signups
        # (last hour) or other conditions. Old FAILED records outside the window won't
        # trigger this alert. See check_signup_health() for full conditions.
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
- Stale processing: {health['metrics'].get('stale_processing', 'N/A')}
- Stuck pending: {health['metrics'].get('stuck_pending', 'N/A')}
- Recent signups: {health['metrics'].get('recent_total', 'N/A')}
- Recent failures: {health['metrics'].get('recent_failed', 'N/A')}
- Failure rate: {health['metrics'].get('failure_rate', 'N/A')}%

Timestamp: {timezone.now().isoformat()}

Please investigate immediately.
            """

            try:
                mail_admins(subject, message, fail_silently=False)
                logger.info("Alert email sent to admins")
            except Exception as email_error:
                logger.error(f"Failed to send alert email: {str(email_error)}")

        return health

    except Exception as e:
        logger.error(f"Failed to check/alert on failure rate: {str(e)}", exc_info=True)
        return {'healthy': False, 'error': str(e)}


def cleanup_old_metrics():
    """
    Clean up old metrics from cache.
    Call this daily from Celery Beat.
    """

    try:
        # Get all signup metric keys
        # Note: This is redis-specific. For other cache backends, adjust accordingly.
        # WARNING: The key patterns below assume Django's cache key prefix is correctly
        # reflected in the '*:' glob prefix. If KEY_PREFIX differs in settings, these
        # patterns will not match and cleanup will silently delete nothing.
        # Verify with: redis_conn.keys('*signups_total*') in a shell first.
        from django_redis import get_redis_connection

        redis_conn = get_redis_connection("default")

        # Find all signup metric keys older than 7 days
        cutoff_date = timezone.now().date() - timedelta(days=7)

        patterns = [
            f'*:signups_total_{cutoff_date}*',
            f'*:signups_hour_{cutoff_date}*',
            f'*:signups_plan_*_{cutoff_date}*',
            f'*:signups_country_*_{cutoff_date}*',
        ]

        deleted_count = 0
        for pattern in patterns:
            keys = redis_conn.keys(pattern)
            if keys:
                deleted_count += redis_conn.delete(*keys)

        logger.info(f"Cleaned up {deleted_count} old metric keys")
        return deleted_count

    except Exception as e:
        logger.warning(f"Failed to cleanup old metrics: {str(e)}")
        return 0