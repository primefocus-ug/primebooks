from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
import logging

from .models import Notification, NotificationBatch

logger = logging.getLogger(__name__)


@shared_task
def send_notification_email(notification_id):
    """Send email for a notification"""
    try:
        notification = Notification.objects.get(id=notification_id)

        if notification.is_emailed:
            return "Already emailed"

        context = {
            'notification': notification,
            'user': notification.recipient,
        }

        html_message = render_to_string('notifications/emails/notification_email.html', context)

        send_mail(
            subject=notification.title,
            message=notification.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.recipient.email],
            html_message=html_message,
            fail_silently=False
        )

        notification.is_emailed = True
        notification.emailed_at = timezone.now()
        notification.save(update_fields=['is_emailed', 'emailed_at'])

        logger.info(f"Email sent for notification {notification_id}")
        return "Email sent successfully"

    except Notification.DoesNotExist:
        logger.error(f"Notification {notification_id} not found")
        return "Notification not found"
    except Exception as e:
        logger.error(f"Failed to send email for notification {notification_id}: {str(e)}")
        return f"Failed: {str(e)}"


@shared_task
def send_daily_digest():
    """Send daily digest of notifications"""
    from django.contrib.auth import get_user_model
    from .models import NotificationPreference

    User = get_user_model()

    users_with_digest = NotificationPreference.objects.filter(
        digest_frequency='daily'
    ).select_related('user')

    batch = NotificationBatch.objects.create(
        batch_type='daily_digest',
        recipient_count=users_with_digest.count(),
        status='processing'
    )

    success_count = 0
    failure_count = 0

    for pref in users_with_digest:
        user = pref.user

        # Get unread notifications from last 24 hours
        yesterday = timezone.now() - timezone.timedelta(days=1)
        notifications = Notification.objects.filter(
            recipient=user,
            is_read=False,
            created_at__gte=yesterday
        )

        if notifications.exists():
            try:
                context = {
                    'user': user,
                    'notifications': notifications,
                    'count': notifications.count()
                }

                html_message = render_to_string('notifications/emails/daily_digest.html', context)

                send_mail(
                    subject=f'Daily Notification Digest - {notifications.count()} unread',
                    message='',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[user.email],
                    html_message=html_message
                )

                success_count += 1

            except Exception as e:
                logger.error(f"Failed to send digest to {user.email}: {str(e)}")
                failure_count += 1

    batch.success_count = success_count
    batch.failure_count = failure_count
    batch.status = 'completed'
    batch.save()

    logger.info(f"Daily digest sent to {success_count} users")
    return f"Digest sent to {success_count} users"


@shared_task
def cleanup_old_notifications():
    """Delete old read notifications (older than 30 days)"""
    from datetime import timedelta

    cutoff_date = timezone.now() - timedelta(days=30)

    old_notifications = Notification.objects.filter(
        is_read=True,
        read_at__lte=cutoff_date
    )

    count = old_notifications.count()
    old_notifications.delete()

    logger.info(f"Deleted {count} old notifications")
    return f"Deleted {count} old notifications"


@shared_task
def cleanup_expired_notifications():
    """Delete expired notifications"""
    now = timezone.now()

    expired = Notification.objects.filter(
        expires_at__lte=now
    )

    count = expired.count()
    expired.delete()

    logger.info(f"Deleted {count} expired notifications")
    return f"Deleted {count} expired notifications"