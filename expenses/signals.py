from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal
from notifications.models import Notification
from notifications.utils import create_notification
from .models import Expense, ExpenseCategory, ExpenseComment


@receiver(pre_save, sender=Expense)
def expense_pre_save(sender, instance, **kwargs):
    """Handle expense pre-save logic"""

    # Calculate tax amount if tax rate is provided
    if instance.tax_rate and instance.amount:
        instance.tax_amount = (instance.amount * instance.tax_rate / 100).quantize(
            Decimal('0.01')
        )

    # Check if status changed
    if instance.pk:
        try:
            old_instance = Expense.objects.get(pk=instance.pk)
            instance._status_changed = old_instance.status != instance.status
            instance._old_status = old_instance.status
        except Expense.DoesNotExist:
            instance._status_changed = False
    else:
        instance._status_changed = False


@receiver(post_save, sender=Expense)
def expense_post_save(sender, instance, created, **kwargs):
    """Handle expense post-save logic"""

    if created:
        # Notify admins about new expense submission
        if instance.status == 'SUBMITTED':
            create_expense_notification(
                expense=instance,
                notification_type='expense_submitted',
                title=f"New Expense Submitted: {instance.expense_number}",
                message=f"{instance.created_by.get_full_name()} submitted an expense for {instance.amount} {instance.currency}",
                recipients='approvers'
            )

    elif hasattr(instance, '_status_changed') and instance._status_changed:
        # Handle status change notifications
        handle_status_change_notification(instance)


@receiver(post_save, sender=ExpenseComment)
def expense_comment_post_save(sender, instance, created, **kwargs):
    """Notify relevant users about new comments"""

    if created:
        expense = instance.expense

        # Notify expense creator if comment is from someone else
        if instance.user != expense.created_by:
            create_expense_notification(
                expense=expense,
                notification_type='expense_comment',
                title=f"New Comment on {expense.expense_number}",
                message=f"{instance.user.get_full_name()} commented: {instance.comment[:100]}...",
                recipients=[expense.created_by]
            )

        # Notify approvers if it's not an internal comment
        if not instance.is_internal and instance.user != expense.approved_by:
            create_expense_notification(
                expense=expense,
                notification_type='expense_comment',
                title=f"New Comment on {expense.expense_number}",
                message=f"{instance.user.get_full_name()} commented on an expense",
                recipients='approvers'
            )


@receiver(post_delete, sender=Expense)
def expense_post_delete(sender, instance, **kwargs):
    """Handle expense deletion cleanup"""

    # Delete associated files
    for attachment in instance.attachments.all():
        if attachment.file:
            attachment.file.delete(save=False)


def create_expense_notification(expense, notification_type, title, message, recipients):
    """Create notifications for expense events"""

    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Get recipients
    if recipients == 'approvers':
        recipient_users = User.objects.filter(
            is_active=True,
            groups__permissions__codename='approve_expense'
        ).distinct()
    elif isinstance(recipients, (list, tuple)):
        recipient_users = recipients
    else:
        return

    # Create notifications
    content_type = ContentType.objects.get_for_model(Expense)

    for user in recipient_users:
        Notification.objects.create(
            recipient=user,
            sender=expense.created_by,
            notification_type=notification_type,
            title=title,
            message=message,
            content_type=content_type,
            object_id=expense.id,
            action_url=f'/expenses/{expense.id}/'
        )


@receiver(post_save, sender=ExpenseCategory)
def expense_category_post_save(sender, instance, created, **kwargs):
    """Handle expense category save"""

    # Clear any cached category data
    from django.core.cache import cache
    cache.delete('active_expense_categories')



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