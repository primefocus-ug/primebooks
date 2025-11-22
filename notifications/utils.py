# utils.py
from django.utils import timezone
from datetime import timedelta
from .models import Notification, NotificationPreference
import logging

logger = logging.getLogger(__name__)


def get_notification_icon(notification_type):
    """Get icon class for notification type"""
    icons = {
        'INFO': 'bi-info-circle',
        'SUCCESS': 'bi-check-circle',
        'WARNING': 'bi-exclamation-triangle',
        'ERROR': 'bi-x-circle',
        'ALERT': 'bi-bell',
    }
    return icons.get(notification_type, 'bi-bell')


def get_notification_color(notification_type):
    """Get color class for notification type"""
    colors = {
        'INFO': 'info',
        'SUCCESS': 'success',
        'WARNING': 'warning',
        'ERROR': 'danger',
        'ALERT': 'primary',
    }
    return colors.get(notification_type, 'secondary')


def get_priority_badge(priority):
    """Get badge class for priority level"""
    badges = {
        'LOW': 'badge-secondary',
        'MEDIUM': 'badge-info',
        'HIGH': 'badge-warning',
        'URGENT': 'badge-danger',
    }
    return badges.get(priority, 'badge-secondary')


def should_send_notification(user, category=None, event_type=None, channel='in_app'):
    """
    Check if notification should be sent to user based on preferences
    """
    try:
        prefs = user.notification_preferences
    except NotificationPreference.DoesNotExist:
        # Create default preferences
        prefs = NotificationPreference.objects.create(user=user)

    return prefs.should_send_notification(category, event_type, channel)


def format_notification_time(notification):
    """
    Format notification time in a human-readable way
    """
    from django.utils.timesince import timesince

    now = timezone.now()
    diff = now - notification.created_at

    if diff < timedelta(minutes=1):
        return 'Just now'
    elif diff < timedelta(hours=1):
        return f'{int(diff.seconds / 60)} minutes ago'
    elif diff < timedelta(days=1):
        return f'{int(diff.seconds / 3600)} hours ago'
    elif diff < timedelta(days=7):
        return f'{diff.days} days ago'
    else:
        return notification.created_at.strftime('%b %d, %Y')


def group_notifications_by_date(notifications):
    """
    Group notifications by date (Today, Yesterday, This Week, etc.)
    """
    now = timezone.now()
    today = now.date()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)

    grouped = {
        'Today': [],
        'Yesterday': [],
        'This Week': [],
        'Older': []
    }

    for notification in notifications:
        notif_date = notification.created_at.date()

        if notif_date == today:
            grouped['Today'].append(notification)
        elif notif_date == yesterday:
            grouped['Yesterday'].append(notification)
        elif notif_date > week_ago:
            grouped['This Week'].append(notification)
        else:
            grouped['Older'].append(notification)

    # Remove empty groups
    return {k: v for k, v in grouped.items() if v}


def batch_mark_as_read(user, notification_ids):
    """
    Mark multiple notifications as read
    """
    count = Notification.objects.filter(
        id__in=notification_ids,
        recipient=user,
        is_read=False
    ).update(
        is_read=True,
        read_at=timezone.now()
    )
    return count


def batch_delete(user, notification_ids):
    """
    Delete multiple notifications
    """
    count, _ = Notification.objects.filter(
        id__in=notification_ids,
        recipient=user
    ).delete()
    return count


def get_notification_summary(user, days=30):
    """
    Get notification summary for a user
    """
    since = timezone.now() - timedelta(days=days)

    notifications = Notification.objects.filter(
        recipient=user,
        created_at__gte=since
    )

    return {
        'total': notifications.count(),
        'unread': notifications.filter(is_read=False).count(),
        'by_type': dict(notifications.values_list('notification_type').annotate(
            count=Count('id')
        )),
        'by_category': dict(notifications.filter(
            category__isnull=False
        ).values_list('category__name').annotate(
            count=Count('id')
        )),
        'urgent': notifications.filter(priority='URGENT').count(),
    }


def cleanup_old_notifications(days=90, batch_size=1000):
    """
    Clean up old read notifications in batches
    """
    cutoff_date = timezone.now() - timedelta(days=days)

    total_deleted = 0
    while True:
        notifications = Notification.objects.filter(
            is_read=True,
            read_at__lt=cutoff_date
        )[:batch_size]

        if not notifications:
            break

        count, _ = notifications.delete()
        total_deleted += count

        logger.info(f'Deleted {count} old notifications')

    return total_deleted


def export_notifications_to_csv(user, queryset=None):
    """
    Export notifications to CSV
    """
    import csv
    from io import StringIO

    if queryset is None:
        queryset = Notification.objects.filter(recipient=user)

    output = StringIO()
    writer = csv.writer(output)

    # Header
    writer.writerow([
        'Date', 'Title', 'Message', 'Type', 'Priority',
        'Category', 'Read', 'Action URL'
    ])

    # Data
    for notification in queryset:
        writer.writerow([
            notification.created_at.strftime('%Y-%m-%d %H:%M'),
            notification.title,
            notification.message,
            notification.notification_type,
            notification.priority,
            notification.category.name if notification.category else '',
            'Yes' if notification.is_read else 'No',
            notification.action_url
        ])

    return output.getvalue()

from .services import NotificationService

def create_notification(recipient, title, message, notification_type='INFO',
                       content_object=None, action_text='', action_url='',
                       priority='MEDIUM', channels=None):
    """
    Helper function to create notifications - wraps NotificationService
    """
    return NotificationService.create_notification(
        recipient=recipient,
        title=title,
        message=message,
        notification_type=notification_type,
        related_object=content_object,  # Map content_object to related_object
        action_text=action_text,
        action_url=action_url,
        priority=priority,
        channels=channels
    )