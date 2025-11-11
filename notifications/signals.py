from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import Notification, NotificationPreference

User = get_user_model()


@receiver(post_save, sender=User)
def create_notification_preferences(sender, instance, created, **kwargs):
    """Create notification preferences for new users"""
    if created:
        NotificationPreference.objects.get_or_create(user=instance)


@receiver(post_save, sender=Notification)
def send_email_notification(sender, instance, created, **kwargs):
    """Send email when notification is created (if enabled)"""
    if created and not instance.is_emailed:
        # Check user preferences
        try:
            prefs = instance.recipient.notification_preferences

            # Determine if email should be sent based on notification type
            should_email = False

            if instance.notification_type == 'expense_approved':
                should_email = prefs.email_on_expense_approved
            elif instance.notification_type == 'expense_rejected':
                should_email = prefs.email_on_expense_rejected
            elif instance.notification_type == 'expense_paid':
                should_email = prefs.email_on_expense_paid
            elif instance.notification_type == 'expense_comment':
                should_email = prefs.email_on_comment
            elif instance.notification_type == 'budget_alert':
                should_email = prefs.email_on_budget_alert

            if should_email:
                # Queue email task
                from .tasks import send_notification_email
                send_notification_email.delay(instance.id)

        except NotificationPreference.DoesNotExist:
            pass


# Add to expenses/signals.py

from notifications.utils import create_notification


def handle_status_change_notification(expense):
    """Handle notifications based on status changes"""

    notifications_map = {
        'SUBMITTED': {
            'title': f"Expense Submitted: {expense.expense_number}",
            'message': f"Your expense for {expense.amount} {expense.currency} has been submitted for approval",
            'type': 'expense_submitted',
            'recipient': expense.created_by
        },
        'APPROVED': {
            'title': f"Expense Approved: {expense.expense_number}",
            'message': f"Your expense for {expense.amount} {expense.currency} has been approved by {expense.approved_by.get_full_name()}",
            'type': 'expense_approved',
            'recipient': expense.created_by
        },
        'REJECTED': {
            'title': f"Expense Rejected: {expense.expense_number}",
            'message': f"Your expense has been rejected. Reason: {expense.rejection_reason}",
            'type': 'expense_rejected',
            'recipient': expense.created_by
        },
        'PAID': {
            'title': f"Expense Paid: {expense.expense_number}",
            'message': f"Your expense for {expense.amount} {expense.currency} has been paid",
            'type': 'expense_paid',
            'recipient': expense.created_by
        }
    }

    if expense.status in notifications_map:
        notif_data = notifications_map[expense.status]

        create_notification(
            recipient=notif_data['recipient'],
            title=notif_data['title'],
            message=notif_data['message'],
            notification_type=notif_data['type'],
            action_url=f'/expenses/{expense.id}/',
            content_object=expense
        )

        # Notify approvers when submitted
        if expense.status == 'SUBMITTED':
            from django.contrib.auth import get_user_model
            User = get_user_model()

            approvers = User.objects.filter(
                is_active=True,
                groups__permissions__codename='approve_expense'
            ).exclude(id=expense.created_by.id).distinct()

            for approver in approvers:
                create_notification(
                    recipient=approver,
                    title=f"New Expense Awaiting Approval",
                    message=f"{expense.created_by.get_full_name()} submitted an expense for {expense.amount} {expense.currency}",
                    notification_type='expense_submitted',
                    action_url=f'/expenses/{expense.id}/',
                    content_object=expense
                )