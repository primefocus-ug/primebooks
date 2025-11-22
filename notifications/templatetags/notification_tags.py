from django import template
from django.utils import timezone
from datetime import timedelta
from ..models import Notification
from ..utils import (
    get_notification_icon,
    get_notification_color,
    get_priority_badge,
    format_notification_time
)

register = template.Library()


@register.filter
def notification_icon(notification_type):
    """Get icon class for notification type"""
    return get_notification_icon(notification_type)


@register.filter
def notification_color(notification_type):
    """Get color class for notification type"""
    return get_notification_color(notification_type)


@register.filter
def priority_badge(priority):
    """Get badge class for priority level"""
    return get_priority_badge(priority)


@register.filter
def notification_time(notification):
    """Format notification time"""
    return format_notification_time(notification)


@register.simple_tag
def unread_notification_count(user):
    """Get unread notification count for user"""
    if not user.is_authenticated:
        return 0

    return Notification.objects.filter(
        recipient=user,
        is_read=False,
        is_dismissed=False
    ).count()


@register.simple_tag
def recent_notifications(user, limit=5):
    """Get recent notifications for user"""
    if not user.is_authenticated:
        return []

    return Notification.objects.filter(
        recipient=user,
        is_dismissed=False
    ).select_related('category').order_by('-created_at')[:limit]


@register.inclusion_tag('notifications/tags/notification_badge.html')
def notification_badge(notification):
    """Render notification badge"""
    return {
        'notification': notification,
        'icon': get_notification_icon(notification.notification_type),
        'color': get_notification_color(notification.notification_type),
    }


@register.inclusion_tag('notifications/tags/notification_dropdown.html', takes_context=True)
def notification_dropdown(context):
    """Render notification dropdown"""
    user = context.get('user')

    if not user or not user.is_authenticated:
        return {
            'notifications': [],
            'unread_count': 0
        }

    notifications = Notification.objects.filter(
        recipient=user,
        is_read=False,
        is_dismissed=False
    ).select_related('category').order_by('-created_at')[:10]

    return {
        'notifications': notifications,
        'unread_count': notifications.count(),
        'user': user
    }


@register.filter
def is_new(notification, minutes=5):
    """Check if notification is new (within X minutes)"""
    if not notification or not notification.created_at:
        return False

    return (timezone.now() - notification.created_at) < timedelta(minutes=minutes)


@register.filter
def truncate_message(message, length=100):
    """Truncate notification message"""
    if len(message) <= length:
        return message
    return message[:length] + '...'


@register.simple_tag
def unread_notification_count(user):
    """Get unread notification count for user"""
    from notifications.models import Notification
    return Notification.objects.filter(recipient=user, is_read=False).count()


@register.filter
def time_ago(date):
    """Convert date to 'time ago' format"""
    if not date:
        return ""

    now = timezone.now()
    diff = now - date

    if diff.days == 0:
        if diff.seconds < 60:
            return "just now"
        elif diff.seconds < 3600:
            minutes = diff.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            hours = diff.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
    elif diff.days == 1:
        return "yesterday"
    elif diff.days < 7:
        return f"{diff.days} days ago"
    else:
        return date.strftime("%b %d, %Y")