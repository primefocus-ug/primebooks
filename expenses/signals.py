from django.db.models.signals import post_save, pre_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.template.loader import render_to_string
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.db import models
import json

from .models import (
    Expense, ExpenseApproval, ExpenseAuditLog,
    Budget, PettyCash, EmployeeReimbursement,
    RecurringExpense, ExpenseSplit
)


@receiver(pre_save, sender=Expense)
def expense_pre_save(sender, instance, **kwargs):
    """Track changes for audit log"""
    if instance.pk:
        try:
            old_instance = Expense.objects.get(pk=instance.pk)
            instance._old_instance = old_instance
        except Expense.DoesNotExist:
            pass


@receiver(post_save, sender=Expense)
def expense_post_save(sender, instance, created, **kwargs):
    """Handle expense creation and updates"""

    # Determine action for audit log
    if created:
        action = 'CREATED'
        old_values = {}
        new_values = {
            'expense_number': instance.expense_number,
            'amount': str(instance.total_amount),
            'status': instance.status,
            'category': instance.category.name,
            'vendor': instance.vendor.name if instance.vendor else None,
        }
    else:
        # Check what changed
        old_instance = getattr(instance, '_old_instance', None)
        if old_instance:
            old_values = {}
            new_values = {}

            # Track status changes
            if old_instance.status != instance.status:
                old_values['status'] = old_instance.status
                new_values['status'] = instance.status

                if instance.status == 'APPROVED':
                    action = 'APPROVED'
                elif instance.status == 'REJECTED':
                    action = 'REJECTED'
                elif instance.status == 'PAID':
                    action = 'PAID'
                elif instance.status == 'CANCELLED':
                    action = 'CANCELLED'
                else:
                    action = 'UPDATED'
            else:
                action = 'UPDATED'

            # Track amount changes
            if old_instance.total_amount != instance.total_amount:
                old_values['total_amount'] = str(old_instance.total_amount)
                new_values['total_amount'] = str(instance.total_amount)
        else:
            action = 'UPDATED'
            old_values = {}
            new_values = {}

    # Create audit log
    ExpenseAuditLog.objects.create(
        expense=instance,
        action=action,
        user=instance.created_by if created else getattr(instance, '_modified_by', instance.created_by),
        old_values=old_values,
        new_values=new_values,
        notes=f"Expense {action.lower()}"
    )

    # Send notifications based on status
    if instance.status == 'PENDING':
        notify_approvers(instance)
    elif instance.status == 'APPROVED':
        notify_creator_approved(instance)
    elif instance.status == 'REJECTED':
        notify_creator_rejected(instance)
    elif instance.status == 'PAID':
        notify_payment_made(instance)

    # Check budget alerts
    check_budget_alerts(instance)

    # Send WebSocket update
    send_expense_websocket_update(instance, action)

    # Check petty cash replenishment
    if instance.payment_method == 'PETTY_CASH' and instance.status == 'PAID':
        check_petty_cash_level(instance)


@receiver(post_save, sender=ExpenseSplit)
def expense_split_created(sender, instance, created, **kwargs):
    """Handle expense split creation"""
    if created:
        # Mark parent expense as split
        if not instance.expense.is_split:
            instance.expense.is_split = True
            instance.expense.save(update_fields=['is_split'])

        # Create audit log
        ExpenseAuditLog.objects.create(
            expense=instance.expense,
            action='UPDATED',
            user=instance.expense.created_by,
            new_values={
                'split_added': {
                    'store': instance.store.name,
                    'percentage': str(instance.allocation_percentage),
                    'amount': str(instance.allocated_amount)
                }
            },
            notes=f"Expense split added for {instance.store.name}"
        )


@receiver(post_save, sender=Budget)
def budget_created_or_updated(sender, instance, created, **kwargs):
    """Handle budget creation or updates"""
    if created:
        # Notify relevant users
        notify_budget_created(instance)
    else:
        # Check if budget was exceeded
        if instance.is_exceeded():
            notify_budget_exceeded(instance)


@receiver(post_save, sender=EmployeeReimbursement)
def reimbursement_status_changed(sender, instance, created, **kwargs):
    """Handle reimbursement status changes"""
    if not created:
        old_instance = getattr(instance, '_old_instance', None)
        if old_instance and old_instance.status != instance.status:
            if instance.status == 'APPROVED':
                notify_reimbursement_approved(instance)
            elif instance.status == 'REJECTED':
                notify_reimbursement_rejected(instance)
            elif instance.status == 'PAID':
                notify_reimbursement_paid(instance)


# Notification Functions

def notify_approvers(expense):
    """Notify approvers when expense is pending"""
    try:
        # Get approvers based on approval flow
        from django.contrib.auth.models import Group

        approver_groups = expense.category.approval_flows.filter(
            is_active=True,
            approval_level=1  # First level approvers
        ).values_list('approver_role', flat=True)

        if approver_groups:
            approvers = get_users_in_groups(approver_groups)

            for approver in approvers:
                if approver.email:
                    send_mail(
                        subject=f'Expense Approval Required: {expense.expense_number}',
                        message=f'An expense of {expense.total_amount} {expense.currency} requires your approval.\n\n'
                                f'Expense: {expense.expense_number}\n'
                                f'Description: {expense.description}\n'
                                f'Amount: {expense.total_amount} {expense.currency}\n'
                                f'Submitted by: {expense.created_by.get_full_name()}\n\n'
                                f'Please review and approve/reject this expense.',
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[approver.email],
                        fail_silently=True,
                    )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error notifying approvers for expense {expense.id}: {e}")


def notify_creator_approved(expense):
    """Notify expense creator when approved"""
    if expense.created_by.email:
        send_mail(
            subject=f'Expense Approved: {expense.expense_number}',
            message=f'Your expense has been approved.\n\n'
                    f'Expense: {expense.expense_number}\n'
                    f'Amount: {expense.total_amount} {expense.currency}\n'
                    f'Approved by: {expense.approved_by.get_full_name() if expense.approved_by else "System"}\n\n'
                    f'The expense will be processed for payment.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[expense.created_by.email],
            fail_silently=True,
        )


def notify_creator_rejected(expense):
    """Notify expense creator when rejected"""
    if expense.created_by.email:
        send_mail(
            subject=f'Expense Rejected: {expense.expense_number}',
            message=f'Your expense has been rejected.\n\n'
                    f'Expense: {expense.expense_number}\n'
                    f'Amount: {expense.total_amount} {expense.currency}\n'
                    f'Reason: {expense.rejection_reason}\n\n'
                    f'Please contact your manager for more details.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[expense.created_by.email],
            fail_silently=True,
        )


def notify_payment_made(expense):
    """Notify relevant parties when payment is made"""
    # Notify creator
    if expense.created_by.email:
        send_mail(
            subject=f'Expense Paid: {expense.expense_number}',
            message=f'Your expense has been paid.\n\n'
                    f'Expense: {expense.expense_number}\n'
                    f'Amount: {expense.total_amount} {expense.currency}\n'
                    f'Payment Method: {expense.get_payment_method_display()}\n'
                    f'Payment Date: {expense.payment_date}\n'
                    f'Reference: {expense.payment_reference}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[expense.created_by.email],
            fail_silently=True,
        )

    # Notify vendor if email available
    if expense.vendor and expense.vendor.email:
        send_mail(
            subject=f'Payment Notification: {expense.expense_number}',
            message=f'Payment has been processed for your invoice.\n\n'
                    f'Reference: {expense.expense_number}\n'
                    f'Invoice: {expense.invoice_number}\n'
                    f'Amount: {expense.total_amount} {expense.currency}\n'
                    f'Payment Date: {expense.payment_date}\n'
                    f'Payment Method: {expense.get_payment_method_display()}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[expense.vendor.email],
            fail_silently=True,
        )


def check_budget_alerts(expense):
    """Check if expense affects budget alerts"""
    try:
        # Find relevant budget
        budgets = Budget.objects.filter(
            category=expense.category,
            start_date__lte=expense.expense_date,
            end_date__gte=expense.expense_date,
            is_active=True
        )

        if expense.store:
            budgets = budgets.filter(store=expense.store)

        for budget in budgets:
            utilization = budget.utilization_percentage

            # Check thresholds
            if utilization >= budget.critical_threshold:
                notify_budget_critical(budget, utilization)
            elif utilization >= budget.warning_threshold:
                notify_budget_warning(budget, utilization)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error checking budget alerts for expense {expense.id}: {e}")


def notify_budget_warning(budget, utilization):
    """Notify when budget reaches warning threshold"""
    # Get budget managers
    managers = get_budget_managers(budget)

    for manager in managers:
        if manager.email:
            send_mail(
                subject=f'Budget Warning: {budget.name}',
                message=f'Budget utilization has reached warning level.\n\n'
                        f'Budget: {budget.name}\n'
                        f'Category: {budget.category.name}\n'
                        f'Allocated: {budget.allocated_amount}\n'
                        f'Spent: {budget.spent_amount}\n'
                        f'Utilization: {utilization}%\n'
                        f'Threshold: {budget.warning_threshold}%\n\n'
                        f'Please monitor spending in this category.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[manager.email],
                fail_silently=True,
            )


def notify_budget_critical(budget, utilization):
    """Notify when budget reaches critical threshold"""
    managers = get_budget_managers(budget)

    for manager in managers:
        if manager.email:
            send_mail(
                subject=f'CRITICAL: Budget Alert - {budget.name}',
                message=f'⚠️ Budget utilization has reached CRITICAL level!\n\n'
                        f'Budget: {budget.name}\n'
                        f'Category: {budget.category.name}\n'
                        f'Allocated: {budget.allocated_amount}\n'
                        f'Spent: {budget.spent_amount}\n'
                        f'Utilization: {utilization}%\n'
                        f'Threshold: {budget.critical_threshold}%\n\n'
                        f'Immediate action may be required!',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[manager.email],
                fail_silently=True,
            )


def notify_budget_exceeded(budget):
    """Notify when budget is exceeded"""
    managers = get_budget_managers(budget)

    for manager in managers:
        if manager.email:
            send_mail(
                subject=f'BUDGET EXCEEDED: {budget.name}',
                message=f'❌ Budget has been EXCEEDED!\n\n'
                        f'Budget: {budget.name}\n'
                        f'Category: {budget.category.name}\n'
                        f'Allocated: {budget.allocated_amount}\n'
                        f'Spent: {budget.spent_amount}\n'
                        f'Overspend: {budget.spent_amount - budget.allocated_amount}\n\n'
                        f'Please review expenses in this category immediately!',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[manager.email],
                fail_silently=True,
            )


def notify_budget_created(budget):
    """Notify when new budget is created"""
    managers = get_budget_managers(budget)

    for manager in managers:
        if manager.email:
            send_mail(
                subject=f'New Budget Created: {budget.name}',
                message=f'A new budget has been created.\n\n'
                        f'Budget: {budget.name}\n'
                        f'Category: {budget.category.name}\n'
                        f'Period: {budget.start_date} to {budget.end_date}\n'
                        f'Allocated Amount: {budget.allocated_amount}\n\n'
                        f'Please ensure expenses are tracked accordingly.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[manager.email],
                fail_silently=True,
            )


def check_petty_cash_level(expense):
    """Check petty cash level after disbursement"""
    try:
        petty_cash = PettyCash.objects.filter(
            store=expense.store,
            is_active=True
        ).first()

        if petty_cash and petty_cash.needs_replenishment:
            notify_petty_cash_low(petty_cash)
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Error checking petty cash level: {e}")


def notify_petty_cash_low(petty_cash):
    """Notify when petty cash needs replenishment"""
    if petty_cash.custodian.email:
        send_mail(
            subject=f'Petty Cash Replenishment Required - {petty_cash.store.name}',
            message=f'Petty cash balance is below minimum threshold.\n\n'
                    f'Store: {petty_cash.store.name}\n'
                    f'Current Balance: {petty_cash.current_balance}\n'
                    f'Minimum Balance: {petty_cash.minimum_balance}\n'
                    f'Maximum Limit: {petty_cash.maximum_limit}\n\n'
                    f'Please arrange for replenishment.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[petty_cash.custodian.email],
            fail_silently=True,
        )


def notify_reimbursement_approved(reimbursement):
    """Notify employee when reimbursement is approved"""
    if reimbursement.employee.email:
        send_mail(
            subject=f'Reimbursement Approved: {reimbursement.reimbursement_number}',
            message=f'Your reimbursement claim has been approved.\n\n'
                    f'Reimbursement: {reimbursement.reimbursement_number}\n'
                    f'Amount: {reimbursement.total_amount}\n'
                    f'Approved by: {reimbursement.approved_by.get_full_name()}\n\n'
                    f'Payment will be processed shortly.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[reimbursement.employee.email],
            fail_silently=True,
        )


def notify_reimbursement_rejected(reimbursement):
    """Notify employee when reimbursement is rejected"""
    if reimbursement.employee.email:
        send_mail(
            subject=f'Reimbursement Rejected: {reimbursement.reimbursement_number}',
            message=f'Your reimbursement claim has been rejected.\n\n'
                    f'Reimbursement: {reimbursement.reimbursement_number}\n'
                    f'Amount: {reimbursement.total_amount}\n\n'
                    f'Please contact your manager for more details.',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[reimbursement.employee.email],
            fail_silently=True,
        )


def notify_reimbursement_paid(reimbursement):
    """Notify employee when reimbursement is paid"""
    if reimbursement.employee.email:
        send_mail(
            subject=f'Reimbursement Paid: {reimbursement.reimbursement_number}',
            message=f'Your reimbursement has been paid.\n\n'
                    f'Reimbursement: {reimbursement.reimbursement_number}\n'
                    f'Amount: {reimbursement.total_amount}\n'
                    f'Payment Method: {reimbursement.get_payment_method_display()}\n'
                    f'Payment Date: {reimbursement.paid_date}\n'
                    f'Reference: {reimbursement.payment_reference}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[reimbursement.employee.email],
            fail_silently=True,
        )


def send_expense_websocket_update(expense, action):
    """Send real-time updates via WebSocket"""
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'expenses_{expense.store.id}',
                {
                    'type': 'expense_update',
                    'message': {
                        'expense_id': str(expense.expense_id),
                        'expense_number': expense.expense_number,
                        'action': action,
                        'status': expense.status,
                        'total_amount': str(expense.total_amount),
                        'category': expense.category.name,
                        'store_id': expense.store.id,
                        'timestamp': timezone.now().isoformat(),
                    }
                }
            )
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"WebSocket Error for Expense {expense.id}: {e}")


# Helper Functions

def get_users_in_groups(group_ids):
    """Get all users in specified groups"""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return User.objects.filter(
        groups__id__in=group_ids,
        is_active=True
    ).distinct()


def get_budget_managers(budget):
    """Get managers who should be notified about budget"""
    from django.contrib.auth import get_user_model
    User = get_user_model()

    # Get company admins and managers for the store
    users = User.objects.filter(
        company=budget.store.company if budget.store else None,
        is_active=True
    ).filter(
        models.Q(user_type='COMPANY_ADMIN') |
        models.Q(user_type='MANAGER')
    )

    if budget.store:
        users = users.filter(stores=budget.store)

    return users.distinct()


# Scheduled Tasks Support

def generate_recurring_expenses():
    """
    Generate expenses from recurring schedules.
    This should be called by a Celery task or cron job.
    """
    from datetime import date

    today = date.today()
    recurring_expenses = RecurringExpense.objects.filter(
        is_active=True,
        next_occurrence__lte=today
    )

    generated_count = 0
    for recurring in recurring_expenses:
        try:
            expense = recurring.generate_expense()
            if expense:
                generated_count += 1
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error generating recurring expense {recurring.id}: {e}")

    return generated_count


def check_overdue_expenses():
    """
    Check for overdue expenses and send notifications.
    This should be called by a Celery task or cron job.
    """
    from datetime import date

    today = date.today()
    overdue_expenses = Expense.objects.filter(
        due_date__lt=today,
        status__in=['APPROVED', 'PARTIALLY_PAID']
    )

    for expense in overdue_expenses:
        try:
            # Notify relevant parties
            if expense.created_by.email:
                send_mail(
                    subject=f'Overdue Expense: {expense.expense_number}',
                    message=f'The following expense is overdue:\n\n'
                            f'Expense: {expense.expense_number}\n'
                            f'Amount Due: {expense.amount_due} {expense.currency}\n'
                            f'Due Date: {expense.due_date}\n'
                            f'Days Overdue: {expense.days_overdue}\n\n'
                            f'Please arrange for payment.',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[expense.created_by.email],
                    fail_silently=True,
                )
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error notifying overdue expense {expense.id}: {e}")