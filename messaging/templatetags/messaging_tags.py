from django import template
from django.db.models import Q, Count
from messaging.models import Message

register = template.Library()


@register.simple_tag(takes_context=True)
def unread_messages_count(context):
    """
    Get count of unread messages for current user
    Usage: {% unread_messages_count %}
    """
    request = context.get('request')
    if not request or not request.user.is_authenticated:
        return 0

    count = Message.objects.filter(
        conversation__participants__user=request.user,
        conversation__participants__is_active=True,
        is_deleted=False
    ).exclude(
        sender=request.user
    ).exclude(
        read_receipts__user=request.user
    ).count()

    return count


@register.inclusion_tag('messaging/widgets/unread_badge.html', takes_context=True)
def show_unread_badge(context):
    """
    Show unread messages badge
    Usage: {% show_unread_badge %}
    """
    request = context.get('request')
    count = 0

    if request and request.user.is_authenticated:
        count = Message.objects.filter(
            conversation__participants__user=request.user,
            conversation__participants__is_active=True,
            is_deleted=False
        ).exclude(
            sender=request.user
        ).exclude(
            read_receipts__user=request.user
        ).count()

    return {'count': count}

