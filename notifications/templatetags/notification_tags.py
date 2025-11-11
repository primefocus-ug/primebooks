from django import template
from django.utils import timezone
from django.utils.timesince import timesince

register = template.Library()


@register.filter
def notification_icon(notification_type):
    """Get icon for notification type"""
    from notifications.models import Notification
    notification = type('obj', (object,), {'notification_type': notification_type})()
    return notification.get_icon() if hasattr(notification, 'get_icon') else 'bi-bell'


@register.filter
def notification_color(notification_type):
    """Get color for notification type"""
    from notifications.models import Notification
    notification = type('obj', (object,), {'notification_type': notification_type})()
    return notification.get_color() if hasattr(notification, 'get_color') else 'primary'


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