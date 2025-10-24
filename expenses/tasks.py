from celery import shared_task
from django.utils import timezone
from django.db.models import Q
from datetime import timedelta, date
import logging

logger = logging.getLogger(__name__)


@shared_task
def generate_recurring_expenses_task():
    """
    Generate expenses from recurring schedules.
    Run daily at midnight.
    """
    from .models import RecurringExpense

    today = date.today()
    recurring_expenses = RecurringExpense.objects.filter(
        is_active=True,
        next_occurrence__lte=today
    )

    generated_count = 0
    failed_count = 0

    for recurring in recurring_expenses:
        try:
            expense = recurring.generate_expense()
            if expense:
                generated_count += 1
                logger.info(f"Generated expense {expense.expense_number} from recurring {recurring.id}")
        except Exception as e:
            failed_count += 1
            logger.error(f"Failed to generate expense from recurring {recurring.id}: {str(e)}")

    logger.info(f"Recurring expense generation complete: {generated_count} generated, {failed_count} failed")

    return {
        'generated': generated_count,
        'failed': failed_count
    }


# @shared_task
# def check_overdue_expenses_task():
#     """
#     Check for overdue expenses and send notifications.
#     Run daily at 9 AM.
#     """
#     from .models import Expense
#     from .signals import notify_payment_reminder
#
#     today = timezone.now().date()
#     overdue_expenses = Expense.objects.filter(
#         due_date__lt=today,
#         status__in=['APPROVED', 'PARTIALLY_PAID']
#     )
#
#     notified_count = 0
#
#     for expense in overdue_expenses:
#         try:
#             from .utils import ExpenseNotificationManager
#             ExpenseNotificationManager.send_payment_reminder(expense)
#             notified_count += 1
#             logger.info(f"Sent overdue notification for expense {expense.expense_number}")
#         except Exception as e:
#             logger.error(f"Failed to send overdue notification for {expense.expense_number}: {str(e)}")
#
#     logger.info(f"Overdue expense check complete: {notified_count} notifications sent")
#
#     return {
#         'overdue_count': overdue_expenses.count(),
#         'notified': notified_count
#     }


@shared_task
def check_budget_alerts_task():
    """
    Check budgets and send alerts if thresholds are reached.
    Run daily at 8 AM.
    """
    from .models import Budget

    today = timezone.now().date()
    active_budgets = Budget.objects.filter(
        start_date__lte=today,
        end_date__gte=today,
        is_active=True
    )

    warning_count = 0
    critical_count = 0
    exceeded_count = 0

    for budget in active_budgets:
        try:
            utilization = budget.utilization_percentage

            if budget.is_exceeded():
                from .signals import notify_budget_exceeded
                notify_budget_exceeded(budget)
                exceeded_count += 1
                logger.warning(f"Budget {budget.name} exceeded: {utilization}%")

            elif utilization >= budget.critical_threshold:
                from .signals import notify_budget_critical
                notify_budget_critical(budget, utilization)
                critical_count += 1
                logger.warning(f"Budget {budget.name} critical: {utilization}%")

            elif utilization >= budget.warning_threshold:
                from .signals import notify_budget_warning
                notify_budget_warning(budget, utilization)
                warning_count += 1
                logger.info(f"Budget {budget.name} warning: {utilization}%")

        except Exception as e:
            logger.error(f"Error checking budget {budget.id}: {str(e)}")

    logger.info(
        f"Budget check complete: {warning_count} warnings, {critical_count} critical, {exceeded_count} exceeded")

    return {
        'checked': active_budgets.count(),
        'warnings': warning_count,
        'critical': critical_count,
        'exceeded': exceeded_count
    }


@shared_task
def send_approval_reminders_task():
    """
    Send reminders for pending expense approvals.
    Run daily at 10 AM.
    """
    from .models import Expense
    from datetime import timedelta

    # Find expenses pending approval for more than 2 days
    cutoff_date = timezone.now() - timedelta(days=2)
    pending_expenses = Expense.objects.filter(
        status='PENDING',
        created_at__lte=cutoff_date
    )

    reminded_count = 0

    for expense in pending_expenses:
        try:
            from .utils import ExpenseNotificationManager
            ExpenseNotificationManager.send_approval_reminder(expense)
            reminded_count += 1
            logger.info(f"Sent approval reminder for expense {expense.expense_number}")
        except Exception as e:
            logger.error(f"Failed to send approval reminder for {expense.expense_number}: {str(e)}")

    logger.info(f"Approval reminders sent: {reminded_count}")

    return {
        'pending_count': pending_expenses.count(),
        'reminded': reminded_count
    }


@shared_task
def check_petty_cash_levels_task():
    """
    Check petty cash levels and alert if replenishment needed.
    Run daily at 8 AM.
    """
    from .models import PettyCash
    from .signals import notify_petty_cash_low

    petty_cash_accounts = PettyCash.objects.filter(is_active=True)

    low_count = 0

    for petty_cash in petty_cash_accounts:
        try:
            if petty_cash.needs_replenishment:
                notify_petty_cash_low(petty_cash)
                low_count += 1
                logger.warning(f"Petty cash low for store {petty_cash.store.name}")
        except Exception as e:
            logger.error(f"Error checking petty cash {petty_cash.id}: {str(e)}")

    logger.info(f"Petty cash check complete: {low_count} accounts need replenishment")

    return {
        'checked': petty_cash_accounts.count(),
        'low_balance': low_count
    }


@shared_task
def generate_monthly_expense_report_task(store_id=None):
    """
    Generate and email monthly expense report.
    Run on the 1st of each month.
    """
    from .models import Expense
    from .utils import ExpenseExporter, ExpenseAnalytics
    from django.core.mail import EmailMessage
    from django.conf import settings
    import calendar
    from datetime import datetime

    # Previous month
    today = timezone.now().date()
    first_day_current = today.replace(day=1)
    last_day_previous = first_day_current - timedelta(days=1)
    first_day_previous = last_day_previous.replace(day=1)

    month_name = calendar.month_name[last_day_previous.month]
    year = last_day_previous.year

    # Get expenses
    expenses = Expense.objects.filter(
        expense_date__gte=first_day_previous,
        expense_date__lte=last_day_previous,
        status='PAID'
    )

    if store_id:
        from stores.models import Store
        store = Store.objects.filter(id=store_id).first()
        if store:
            expenses = expenses.filter(store=store)

    if not expenses.exists():
        logger.info(f"No expenses found for {month_name} {year}")
        return {'status': 'no_data'}

    try:
        # Generate report
        pdf_output = ExpenseExporter.export_to_pdf(expenses)
        excel_output = ExpenseExporter.export_to_excel(expenses)

        # Get analytics
        analytics = ExpenseAnalytics.get_expense_summary(
            store=store if store_id else None,
            start_date=first_day_previous,
            end_date=last_day_previous
        )

        # Prepare email
        subject = f'Monthly Expense Report - {month_name} {year}'
        message = f"""
        Monthly Expense Report for {month_name} {year}

        Summary:
        - Total Expenses: {analytics['summary']['total_expenses']:,.2f} UGX
        - Number of Transactions: {analytics['summary']['total_count']}
        - Average Expense: {analytics['summary']['average_expense']:,.2f} UGX
        - Total Tax: {analytics['summary']['total_tax']:,.2f} UGX

        Please find the detailed reports attached.

        Best regards,
        Expense Management System
        """

        # Send email to managers
        from accounts.models import CustomUser
        managers = CustomUser.objects.filter(
            user_type__in=['COMPANY_ADMIN', 'MANAGER'],
            is_active=True
        )

        if store_id and store:
            managers = managers.filter(stores=store)

        recipient_emails = [m.email for m in managers if m.email]

        if recipient_emails:
            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipient_emails
            )

            # Attach reports
            email.attach(
                f'expenses_{month_name}_{year}.pdf',
                pdf_output.read(),
                'application/pdf'
            )
            email.attach(
                f'expenses_{month_name}_{year}.xlsx',
                excel_output.read(),
                'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            )

            email.send()

            logger.info(f"Monthly expense report sent to {len(recipient_emails)} recipients")

            return {
                'status': 'success',
                'recipients': len(recipient_emails),
                'expense_count': expenses.count()
            }

    except Exception as e:
        logger.error(f"Failed to generate monthly expense report: {str(e)}")
        return {'status': 'error', 'message': str(e)}


@shared_task
def cleanup_old_attachments_task(days=90):
    """
    Clean up old expense attachments from cancelled/rejected expenses.
    Run monthly.
    """
    from .models import Expense, ExpenseAttachment
    import os
    from django.conf import settings

    cutoff_date = timezone.now() - timedelta(days=days)

    # Find old cancelled/rejected expenses
    old_expenses = Expense.objects.filter(
        status__in=['CANCELLED', 'REJECTED'],
        updated_at__lt=cutoff_date
    )

    deleted_count = 0

    for expense in old_expenses:
        attachments = expense.attachments.all()

        for attachment in attachments:
            try:
                # Delete file from storage
                if attachment.file:
                    if os.path.isfile(attachment.file.path):
                        os.remove(attachment.file.path)

                # Delete database record
                attachment.delete()
                deleted_count += 1

            except Exception as e:
                logger.error(f"Failed to delete attachment {attachment.id}: {str(e)}")

    logger.info(f"Cleanup complete: {deleted_count} attachments deleted")

    return {
        'deleted': deleted_count,
        'expenses_checked': old_expenses.count()
    }


@shared_task
def sync_vendor_ratings_task():
    """
    Update vendor ratings based on payment performance.
    Run weekly.
    """
    from .models import Vendor, Expense
    from django.db.models import Count, Q, F
    from decimal import Decimal

    vendors = Vendor.objects.filter(is_active=True)
    updated_count = 0

    for vendor in vendors:
        try:
            # Get vendor's expenses
            expenses = vendor.expenses.filter(status='PAID')

            if not expenses.exists():
                continue

            total_count = expenses.count()

            # Calculate on-time payment ratio
            on_time = expenses.filter(payment_date__lte=F('due_date')).count()
            on_time_ratio = on_time / total_count if total_count > 0 else 0

            # Calculate rating (0-5 scale)
            # Base rating on payment performance
            rating = Decimal(on_time_ratio * 5).quantize(Decimal('0.01'))

            # Update vendor rating
            vendor.rating = rating
            vendor.save(update_fields=['rating'])
            updated_count += 1

        except Exception as e:
            logger.error(f"Failed to update rating for vendor {vendor.id}: {str(e)}")

    logger.info(f"Vendor ratings updated: {updated_count} vendors")

    return {
        'updated': updated_count,
        'total_vendors': vendors.count()
    }


@shared_task
def export_tax_report_task(month, year, store_id=None):
    """
    Generate monthly tax report for EFRIS compliance.
    """
    from .utils import TaxCalculator
    from .models import Expense
    from django.core.mail import EmailMessage
    from django.conf import settings
    import calendar

    # Get month date range
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])

    # Get store
    store = None
    if store_id:
        from stores.models import Store
        store = Store.objects.filter(id=store_id).first()

    try:
        # Generate tax report
        tax_report = TaxCalculator.generate_tax_report(
            store=store,
            start_date=first_day,
            end_date=last_day
        )

        month_name = calendar.month_name[month]

        # Prepare email
        subject = f'Tax Report - {month_name} {year}'
        message = f"""
        Tax Report for {month_name} {year}
        {f'Store: {store.name}' if store else 'All Stores'}

        Summary:
        - Total Expenses: {tax_report['total_expenses']['total']:,.2f} UGX
        - Total Tax Paid: {tax_report['total_expenses']['tax']:,.2f} UGX
        - Input Tax Credit: {tax_report['input_tax_credit']['total_input_tax']:,.2f} UGX
        - EFRIS Compliant Expenses: {tax_report['efris_compliance']['compliant_count']}
        - Non-compliant Expenses: {tax_report['efris_compliance']['non_compliant_count']}

        Please review the attached report for EFRIS submission.

        Best regards,
        Expense Management System
        """

        # Send to finance team
        from accounts.models import CustomUser
        finance_users = CustomUser.objects.filter(
            user_type__in=['COMPANY_ADMIN', 'MANAGER'],
            is_active=True
        )

        if store:
            finance_users = finance_users.filter(stores=store)

        recipient_emails = [u.email for u in finance_users if u.email]

        if recipient_emails:
            email = EmailMessage(
                subject=subject,
                body=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipient_emails
            )

            # Attach JSON report
            import json
            email.attach(
                f'tax_report_{month_name}_{year}.json',
                json.dumps(tax_report, indent=2, default=str),
                'application/json'
            )

            email.send()

            logger.info(f"Tax report sent to {len(recipient_emails)} recipients")

            return {
                'status': 'success',
                'recipients': len(recipient_emails)
            }

    except Exception as e:
        logger.error(f"Failed to generate tax report: {str(e)}")
        return {'status': 'error', 'message': str(e)}