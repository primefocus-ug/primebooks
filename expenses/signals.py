from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from decimal import Decimal
from notifications.models import Notification
from notifications.utils import create_notification
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.db.models import Sum, F, Avg, Count, Q
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from .models import Expense, ExpenseComment
from .models import Expense, ExpenseCategory, ExpenseComment

User = get_user_model()


@receiver(post_save, sender=ExpenseCategory)
def handle_category_change(sender, instance, created, **kwargs):
    """Handle category changes and update related expenses if needed"""
    if not created:
        try:
            # Get the original instance from database
            original = sender.objects.get(pk=instance.pk)
            # Check if is_active changed
            if original.is_active != instance.is_active:
                # Notify users if category is deactivated
                if not instance.is_active:
                    send_category_deactivation_notification(instance)
        except sender.DoesNotExist:
            # Instance was deleted or doesn't exist
            pass

def send_category_deactivation_notification(category):
    """Send notification when category is deactivated"""
    # Get users who have expenses in this category
    users_with_expenses = User.objects.filter(
        created_expenses__category=category,
        created_expenses__status__in=['DRAFT', 'SUBMITTED']
    ).distinct()
    
    for user in users_with_expenses:
        subject = f"Category Deactivated: {category.name}"
        context = {
            'user': user,
            'category': category,
            'pending_expenses_count': user.created_expenses.filter(
                category=category,
                status__in=['DRAFT', 'SUBMITTED']
            ).count()
        }
        
        html_message = render_to_string('expenses/emails/category_deactivated.html', context)
        plain_message = render_to_string('expenses/emails/category_deactivated.txt', context)
        
        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=True
            )
        except Exception as e:
            print(f"Failed to send category deactivation notification: {e}")

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



@receiver(post_save, sender=Expense)
def handle_expense_status_change(sender, instance, created, **kwargs):
    """Handle expense status changes and send notifications"""
    if not created:
        # Check if status changed
        if instance.tracker.has_changed('status'):
            send_expense_status_notification(instance)

@receiver(post_save, sender=ExpenseComment)
def handle_new_comment(sender, instance, created, **kwargs):
    """Handle new comments and send notifications"""
    if created:
        send_comment_notification(instance)

def send_expense_status_notification(expense):
    """Send notification when expense status changes"""
    subject = f"Expense {expense.expense_number} - Status Updated"
    
    # Determine recipients
    recipients = [expense.created_by.email]
    
    if expense.status == 'SUBMITTED':
        # Notify approvers
        approvers = get_approvers(expense)
        recipients.extend([approver.email for approver in approvers])
        subject = f"New Expense Submitted for Approval - {expense.expense_number}"
    
    elif expense.status in ['APPROVED', 'REJECTED']:
        subject = f"Expense {expense.status.lower().title()} - {expense.expense_number}"
    
    context = {
        'expense': expense,
        'status': expense.get_status_display(),
        'user': expense.created_by.get_full_name() or expense.created_by.username
    }
    
    html_message = render_to_string('expenses/emails/status_update.html', context)
    plain_message = render_to_string('expenses/emails/status_update.txt', context)
    
    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=recipients,
            html_message=html_message,
            fail_silently=True
        )
    except Exception as e:
        # Log email error but don't break the application
        print(f"Failed to send email notification: {e}")

def send_comment_notification(comment):
    """Send notification for new comments"""
    expense = comment.expense
    
    # Don't notify the user who made the comment
    recipients = []
    if comment.user != expense.created_by:
        recipients.append(expense.created_by.email)
    
    # Notify other users involved with this expense
    other_commenters = ExpenseComment.objects.filter(
        expense=expense
    ).exclude(
        user__in=[comment.user, expense.created_by]
    ).values_list('user__email', flat=True).distinct()
    
    recipients.extend(other_commenters)
    
    if recipients:
        subject = f"New Comment on Expense {expense.expense_number}"
        
        context = {
            'expense': expense,
            'comment': comment,
            'commenter': comment.user.get_full_name() or comment.user.username
        }
        
        html_message = render_to_string('expenses/emails/new_comment.html', context)
        plain_message = render_to_string('expenses/emails/new_comment.txt', context)
        
        try:
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=list(set(recipients)),
                html_message=html_message,
                fail_silently=True
            )
        except Exception as e:
            print(f"Failed to send comment notification: {e}")

def get_approvers(expense):
    """Get users who can approve this expense"""
    from django.contrib.auth.models import User
    from django.contrib.auth.models import Permission
    from django.contrib.contenttypes.models import ContentType
    
    content_type = ContentType.objects.get_for_model(Expense)
    permission = Permission.objects.get(
        content_type=content_type,
        codename='approve_expense'
    )
    
    return User.objects.filter(
        Q(groups__permissions=permission) |
        Q(user_permissions=permission) |
        Q(is_superuser=True)
    ).distinct()

@receiver(pre_save, sender=Expense)
def set_expense_dates(sender, instance, **kwargs):
    """Set submitted_at, approved_at, etc. dates automatically"""
    if not instance.pk:
        return  # New instance, dates will be set on status changes
    
    try:
        old_instance = Expense.objects.get(pk=instance.pk)
    except Expense.DoesNotExist:
        return
    
    # Set submitted_at when status changes to SUBMITTED
    if (instance.status == 'SUBMITTED' and 
        old_instance.status != 'SUBMITTED'):
        instance.submitted_at = timezone.now()
    
    # Set approved_at when status changes to APPROVED
    if (instance.status == 'APPROVED' and 
        old_instance.status != 'APPROVED'):
        instance.approved_at = timezone.now()
    
    # Set rejected_at when status changes to REJECTED
    if (instance.status == 'REJECTED' and 
        old_instance.status != 'REJECTED'):
        instance.rejected_at = timezone.now()
    
    # Set paid_at when status changes to PAID
    if (instance.status == 'PAID' and 
        old_instance.status != 'PAID'):
        instance.paid_at = timezone.now()