from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from .models import Notification

User = get_user_model()


def create_notification(
        recipient,
        title,
        message,
        notification_type='info',
        sender=None,
        action_url='',
        action_text='View',
        priority=0,
        content_object=None,
        expires_at=None,
        metadata=None
):
    """
    Helper function to create notifications

    Usage:
        create_notification(
            recipient=user,
            title="Expense Approved",
            message="Your expense has been approved",
            notification_type='expense_approved',
            action_url='/expenses/123/',
            content_object=expense
        )
    """

    notification_data = {
        'recipient': recipient,
        'sender': sender,
        'notification_type': notification_type,
        'title': title,
        'message': message,
        'action_url': action_url,
        'action_text': action_text,
        'priority': priority,
        'expires_at': expires_at,
        'metadata': metadata or {}
    }

    if content_object:
        notification_data['content_type'] = ContentType.objects.get_for_model(content_object)
        notification_data['object_id'] = content_object.id

    notification = Notification.objects.create(**notification_data)

    # Send real-time update via WebSocket
    send_realtime_notification(notification)

    return notification


def create_bulk_notifications(recipients, title, message, **kwargs):
    """Create notifications for multiple recipients"""
    notifications = []

    for recipient in recipients:
        notification = create_notification(
            recipient=recipient,
            title=title,
            message=message,
            **kwargs
        )
        notifications.append(notification)

    return notifications


def send_realtime_notification(notification):
    """Send real-time notification via WebSocket"""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    try:
        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            f'user_{notification.recipient.id}',
            {
                'type': 'notification_message',
                'notification': {
                    'id': notification.id,
                    'title': notification.title,
                    'message': notification.message,
                    'icon': notification.get_icon(),
                    'color': notification.get_color(),
                    'url': notification.action_url,
                    'created_at': notification.created_at.isoformat()
                }
            }
        )
    except Exception as e:
        import logging
        logging.error(f"Failed to send real-time notification: {str(e)}")


def notify_expense_action(expense, action, user=None):
    """
    Notify relevant users about expense actions

    Actions: created, submitted, approved, rejected, paid, commented
    """
    from expenses.models import Expense

    notifications_map = {
        'created': {
            'recipient': expense.created_by,
            'title': 'Expense Created',
            'message': f'Expense {expense.expense_number} created successfully',
            'type': 'expense_created'
        },
        'submitted': {
            'recipient': expense.created_by,
            'title': 'Expense Submitted',
            'message': f'Expense {expense.expense_number} submitted for approval',
            'type': 'expense_submitted'
        },
        'approved': {
            'recipient': expense.created_by,
            'title': 'Expense Approved',
            'message': f'Your expense {expense.expense_number} has been approved',
            'type': 'expense_approved'
        },
        'rejected': {
            'recipient': expense.created_by,
            'title': 'Expense Rejected',
            'message': f'Your expense {expense.expense_number} has been rejected',
            'type': 'expense_rejected'
        },
        'paid': {
            'recipient': expense.created_by,
            'title': 'Expense Paid',
            'message': f'Your expense {expense.expense_number} has been paid',
            'type': 'expense_paid'
        },
    }

    if action in notifications_map:
        notif_data = notifications_map[action]

        create_notification(
            recipient=notif_data['recipient'],
            title=notif_data['title'],
            message=notif_data['message'],
            notification_type=notif_data['type'],
            sender=user,
            action_url=f'/expenses/{expense.id}/',
            content_object=expense
        )