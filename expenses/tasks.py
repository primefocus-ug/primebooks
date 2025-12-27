from celery import shared_task
from django.utils import timezone
from django.db.models import Sum, Q, Count
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from datetime import timedelta
from decimal import Decimal
import logging
import pandas as pd
from io import BytesIO
import os

from .models import Expense  # Removed ExpenseCategory import
from notifications.models import Notification

User = get_user_model()
logger = logging.getLogger(__name__)


@shared_task
def send_pending_approval_reminders():
    """Send reminders for expenses pending approval for more than 3 days"""
    three_days_ago = timezone.now() - timedelta(days=3)

    pending_expenses = Expense.objects.filter(
        status='SUBMITTED',
        submitted_at__lte=three_days_ago
    ).select_related('created_by')  # Removed 'category' from select_related

    if not pending_expenses.exists():
        logger.info("No pending expenses found for reminders")
        return "No pending expenses found"

    # Get approvers with correct permission lookup
    approvers = User.objects.filter(
        is_active=True,
        user_permissions__codename='approve_expense'
    ).distinct() | User.objects.filter(
        is_active=True,
        groups__permissions__codename='approve_expense'
    ).distinct()

    approvers = approvers.distinct()

    for approver in approvers:
        # Filter expenses not created by the approver
        relevant_expenses = pending_expenses.exclude(created_by=approver)

        if relevant_expenses.exists():
            Notification.objects.create(
                recipient=approver,
                notification_type='expense_reminder',
                title=f"{relevant_expenses.count()} Expenses Pending Approval",
                message=f"You have {relevant_expenses.count()} expenses waiting for approval for more than 3 days",
                action_url='/expenses/?status=SUBMITTED'
            )

    logger.info(f"Sent reminders for {pending_expenses.count()} pending expenses to {approvers.count()} approvers")
    return f"Sent reminders for {pending_expenses.count()} expenses to {approvers.count()} approvers"


@shared_task
def send_overdue_payment_alerts():
    """Send alerts for approved but unpaid expenses past due date"""
    today = timezone.now().date()

    overdue_expenses = Expense.objects.filter(
        status='APPROVED',
        due_date__lt=today
    ).select_related('created_by', 'store')  # Removed 'category' from select_related

    if not overdue_expenses.exists():
        logger.info("No overdue expenses found")
        return "No overdue expenses found"

    # Notify finance team
    finance_users = User.objects.filter(
        is_active=True,
        user_permissions__codename='pay_expense'
    ).distinct() | User.objects.filter(
        is_active=True,
        groups__permissions__codename='pay_expense'
    ).distinct()

    finance_users = finance_users.distinct()

    total_overdue = overdue_expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    for user in finance_users:
        Notification.objects.create(
            recipient=user,
            notification_type='expense_overdue',
            title=f"{overdue_expenses.count()} Overdue Expenses",
            message=f"Total overdue amount: {total_overdue:,.2f}. Please process payments.",
            action_url='/expenses/?status=APPROVED&is_overdue=true'
        )

        # Send email notification
        context = {
            'user': user,
            'overdue_count': overdue_expenses.count(),
            'total_amount': total_overdue,
            'expenses': overdue_expenses[:10]  # Top 10 overdue
        }

        html_message = render_to_string('expenses/emails/overdue_payment_alert.html', context)
        plain_message = render_to_string('expenses/emails/overdue_payment_alert.txt', context)

        send_mail(
            subject=f'Urgent: {overdue_expenses.count()} Overdue Expenses',
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=True
        )

    logger.info(f"Sent overdue alerts for {overdue_expenses.count()} expenses to {finance_users.count()} users")
    return f"Sent alerts for {overdue_expenses.count()} overdue expenses"


@shared_task
def generate_monthly_expense_report():
    """Generate and email monthly expense report for all active users"""
    # Get last month's date range
    today = timezone.now()
    first_day_last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    last_day_last_month = today.replace(day=1) - timedelta(days=1)

    # Get users who created expenses last month
    users = User.objects.filter(
        is_active=True,
        created_expenses__expense_date__gte=first_day_last_month,
        created_expenses__expense_date__lte=last_day_last_month
    ).distinct()

    reports_sent = 0

    # Get category choices for display names
    from .models import Expense
    category_choices_dict = dict(Expense.CATEGORY_CHOICES)

    for user in users:
        # Get user's expenses for last month
        expenses = Expense.objects.filter(
            created_by=user,
            expense_date__gte=first_day_last_month,
            expense_date__lte=last_day_last_month
        ).select_related('store')  # Removed 'category' from select_related

        if not expenses.exists():
            continue

        # Calculate statistics
        total_amount = expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        paid_amount = expenses.filter(status='PAID').aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0')
        pending_amount = expenses.filter(
            status__in=['SUBMITTED', 'APPROVED']
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

        # Category breakdown - UPDATED
        category_breakdown = expenses.values('category').annotate(
            total=Sum('amount'),
            count=Count('id')
        ).order_by('-total')

        # Add display names to category breakdown
        for item in category_breakdown:
            item['category_display'] = category_choices_dict.get(item['category'], item['category'])

        # Status breakdown
        status_breakdown = expenses.values('status').annotate(
            count=Count('id'),
            total=Sum('amount')
        )

        # Prepare context
        context = {
            'user': user,
            'month': first_day_last_month.strftime('%B %Y'),
            'date_range': f"{first_day_last_month.strftime('%B %d')} - {last_day_last_month.strftime('%B %d, %Y')}",
            'total_expenses': expenses.count(),
            'total_amount': total_amount,
            'paid_amount': paid_amount,
            'pending_amount': pending_amount,
            'category_breakdown': category_breakdown,
            'status_breakdown': status_breakdown,
            'top_expenses': expenses.order_by('-amount')[:5]
        }

        # Render email
        html_message = render_to_string('expenses/emails/monthly_report.html', context)
        plain_message = render_to_string('expenses/emails/monthly_report.txt', context)

        # Send email
        try:
            send_mail(
                subject=f'Monthly Expense Report - {first_day_last_month.strftime("%B %Y")}',
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[user.email],
                html_message=html_message,
                fail_silently=False
            )
            reports_sent += 1
        except Exception as e:
            logger.error(f"Failed to send monthly report to {user.email}: {str(e)}")

    logger.info(f"Sent monthly reports to {reports_sent} users")
    return f"Sent reports to {reports_sent} users"


# Remove or comment out budget-related tasks since ExpenseCategory is removed
# @shared_task
# def check_budget_utilization():
#     """Check and alert for categories exceeding budget thresholds"""
#     # This function no longer works since ExpenseCategory model was removed
#     return "Budget check disabled - ExpenseCategory model removed"


@shared_task
def cleanup_old_draft_expenses():
    """Delete draft expenses older than 30 days with no activity"""
    thirty_days_ago = timezone.now() - timedelta(days=30)

    old_drafts = Expense.objects.filter(
        status='DRAFT',
        created_at__lte=thirty_days_ago,
        updated_at__lte=thirty_days_ago
    ).select_related('created_by')

    # Notify users before deletion
    for expense in old_drafts:
        try:
            Notification.objects.create(
                recipient=expense.created_by,
                notification_type='expense_deleted',
                title='Draft Expense Auto-Deleted',
                message=f'Your draft expense "{expense.title}" ({expense.expense_number}) was automatically deleted due to inactivity (30+ days)',
                action_url='/expenses/'
            )
        except Exception as e:
            logger.error(f"Failed to notify user about deleted draft: {str(e)}")

    count = old_drafts.count()
    old_drafts.delete()

    logger.info(f"Deleted {count} old draft expenses")
    return f"Deleted {count} old drafts"


@shared_task
def export_expenses_to_excel_task(user_id, filters=None):
    from expenses.models import Expense
    """Export expenses to Excel file asynchronously"""
    try:
        user = User.objects.get(id=user_id)
        filters = filters or {}

        # Build queryset based on filters and permissions
        if user.has_perm('expenses.view_all_expenses'):
            expenses = Expense.objects.all()
        else:
            expenses = Expense.objects.filter(created_by=user)

        # Apply filters
        if filters.get('status'):
            expenses = expenses.filter(status=filters['status'])
        if filters.get('category'):
            expenses = expenses.filter(category=filters['category'])  # Changed from category_id to category
        if filters.get('date_from'):
            expenses = expenses.filter(expense_date__gte=filters['date_from'])
        if filters.get('date_to'):
            expenses = expenses.filter(expense_date__lte=filters['date_to'])
        if filters.get('store'):
            expenses = expenses.filter(store_id=filters['store'])

        # Select related to optimize queries - REMOVED 'category' from select_related
        expenses = expenses.select_related(
            'store', 'created_by', 'approved_by', 'paid_by'  # Removed 'category'
        ).order_by('-expense_date')

        # Get category display names
        from .models import Expense
        category_choices_dict = dict(Expense.CATEGORY_CHOICES)

        # Prepare data for export
        data = []
        for expense in expenses:
            # Get category display name
            category_display = category_choices_dict.get(expense.category, expense.category)

            data.append({
                'Expense Number': expense.expense_number,
                'Title': expense.title,
                'Description': expense.description,
                'Category': category_display,  # Use display name
                'Amount': float(expense.amount),
                'Total Amount': float(expense.total_amount),
                'Currency': expense.currency,
                'Expense Date': expense.expense_date.isoformat(),
                'Vendor': expense.vendor_name,
                'Reference Number': expense.reference_number,
                'Status': expense.get_status_display(),
                'Store': expense.store.name if expense.store else '',
                'Created By': expense.created_by.get_full_name(),
                'Created At': expense.created_at.isoformat(),
                'Submitted At': expense.submitted_at.isoformat() if expense.submitted_at else '',
                'Approved By': expense.approved_by.get_full_name() if expense.approved_by else '',
                'Approved At': expense.approved_at.isoformat() if expense.approved_at else '',
                'Paid By': expense.paid_by.get_full_name() if expense.paid_by else '',
                'Paid At': expense.paid_at.isoformat() if expense.paid_at else '',
                'Payment Method': expense.get_payment_method_display() if expense.payment_method else '',
                'Payment Reference': expense.payment_reference,
                'Is Reimbursable': 'Yes' if expense.is_reimbursable else 'No',
                'Due Date': expense.due_date.isoformat() if expense.due_date else '',
                'Notes': expense.notes,
            })

        # Create DataFrame and export to Excel
        df = pd.DataFrame(data)

        # Generate filename and path
        timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
        filename = f'expenses_export_{user.id}_{timestamp}.xlsx'
        exports_dir = os.path.join(settings.MEDIA_ROOT, 'exports')
        os.makedirs(exports_dir, exist_ok=True)
        filepath = os.path.join(exports_dir, filename)

        # Save Excel with formatting
        with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Expenses')

            # Get the workbook and worksheet
            workbook = writer.book
            worksheet = writer.sheets['Expenses']

            # Auto-adjust column widths
            for column in worksheet.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(cell.value)
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                worksheet.column_dimensions[column_letter].width = adjusted_width

        # Send notification with download link
        send_export_notification.delay(user_id, filename, len(data))

        logger.info(f"Exported {len(data)} expenses to {filename} for user {user_id}")
        return f"Exported {len(data)} expenses to {filename}"

    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for export")
        return f"User {user_id} not found"
    except Exception as e:
        logger.error(f"Export failed for user {user_id}: {str(e)}")
        send_export_failure_notification.delay(user_id, str(e))
        raise


@shared_task
def send_export_notification(user_id, filename, record_count):
    """Send email notification when export is ready"""
    try:
        user = User.objects.get(id=user_id)

        subject = "Your expense export is ready"

        context = {
            'user': user,
            'filename': filename,
            'record_count': record_count,
            'expiry_hours': 24
        }

        html_message = render_to_string('expenses/emails/export_ready.html', context)
        plain_message = render_to_string('expenses/emails/export_ready.txt', context)

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False
        )

        # Also create in-app notification
        Notification.objects.create(
            recipient=user,
            notification_type='export_complete',
            title='Expense Export Complete',
            message=f'Your expense export ({record_count} records) is ready for download',
        )

        logger.info(f"Sent export notification to user {user_id}")

    except User.DoesNotExist:
        logger.error(f"User {user_id} not found for export notification")
    except Exception as e:
        logger.error(f"Failed to send export notification: {str(e)}")


@shared_task
def send_export_failure_notification(user_id, error_message):
    """Send email notification when export fails"""
    try:
        user = User.objects.get(id=user_id)

        subject = "Expense export failed"

        context = {
            'user': user,
            'error_message': error_message,
        }

        html_message = render_to_string('expenses/emails/export_failed.html', context)
        plain_message = render_to_string('expenses/emails/export_failed.txt', context)

        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False
        )

        # Create in-app notification
        Notification.objects.create(
            recipient=user,
            notification_type='export_failed',
            title='Expense Export Failed',
            message=f'Your expense export failed: {error_message}',
            action_url='/expenses/'
        )

    except Exception as e:
        logger.error(f"Failed to send export failure notification: {str(e)}")


@shared_task
def send_pending_approval_reminder(expense_id):
    """Send reminder for specific pending expense"""
    try:
        expense = Expense.objects.select_related(
            'created_by', 'store'  # Removed 'category' from select_related
        ).get(id=expense_id)

        # Get approvers
        approvers = User.objects.filter(
            Q(user_permissions__codename='approve_expense') |
            Q(groups__permissions__codename='approve_expense'),
            is_active=True
        ).exclude(id=expense.created_by.id).distinct()

        # Calculate days pending
        days_pending = (timezone.now() - expense.submitted_at).days if expense.submitted_at else 0

        subject = f"Reminder: Expense pending approval - {expense.expense_number}"

        for approver in approvers:
            context = {
                'approver': approver,
                'expense': expense,
                'days_pending': days_pending,
            }

            html_message = render_to_string('expenses/emails/approval_reminder.html', context)
            plain_message = render_to_string('expenses/emails/approval_reminder.txt', context)

            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[approver.email],
                html_message=html_message,
                fail_silently=True
            )

            # Create in-app notification
            Notification.objects.create(
                recipient=approver,
                notification_type='expense_reminder',
                title=f'Reminder: Expense Pending ({days_pending} days)',
                message=f'Expense {expense.expense_number} from {expense.created_by.get_full_name()} needs approval',
                action_url=f'/expenses/{expense.id}/'
            )

        logger.info(f"Sent approval reminders for expense {expense_id} to {approvers.count()} approvers")

    except Expense.DoesNotExist:
        logger.warning(f"Expense {expense_id} not found for reminder")
    except Exception as e:
        logger.error(f"Failed to send approval reminder for expense {expense_id}: {str(e)}")


@shared_task
def cleanup_temp_files():
    """Clean up temporary export files older than 24 hours"""
    import glob
    from datetime import datetime

    exports_dir = os.path.join(settings.MEDIA_ROOT, 'exports')
    cutoff_time = datetime.now() - timedelta(hours=24)

    deleted_count = 0

    if os.path.exists(exports_dir):
        for file_path in glob.glob(os.path.join(exports_dir, '*.xlsx')) + \
                         glob.glob(os.path.join(exports_dir, '*.csv')):
            try:
                file_time = datetime.fromtimestamp(os.path.getctime(file_path))
                if file_time < cutoff_time:
                    os.remove(file_path)
                    deleted_count += 1
                    logger.info(f"Cleaned up old export file: {file_path}")
            except OSError as e:
                logger.error(f"Failed to clean up {file_path}: {str(e)}")

    logger.info(f"Cleanup completed. Deleted {deleted_count} old export files")
    return f"Deleted {deleted_count} old export files"


@shared_task
def send_expense_status_notifications():
    """Send notifications for expense status changes that occurred recently"""
    # This is typically called by real-time updates, but can run periodically as backup

    one_hour_ago = timezone.now() - timedelta(hours=1)

    # Find recently approved expenses
    recently_approved = Expense.objects.filter(
        status='APPROVED',
        approved_at__gte=one_hour_ago
    ).select_related('created_by', 'approved_by')

    for expense in recently_approved:
        context = {
            'expense': expense,
            'user': expense.created_by
        }

        html_message = render_to_string('expenses/emails/expense_approved.html', context)
        plain_message = render_to_string('expenses/emails/expense_approved.txt', context)

        try:
            send_mail(
                subject=f'Expense Approved: {expense.expense_number}',
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[expense.created_by.email],
                html_message=html_message,
                fail_silently=True
            )
        except Exception as e:
            logger.error(f"Failed to send approval notification for expense {expense.id}: {str(e)}")

    # Find recently paid expenses
    recently_paid = Expense.objects.filter(
        status='PAID',
        paid_at__gte=one_hour_ago
    ).select_related('created_by', 'paid_by')

    for expense in recently_paid:
        context = {
            'expense': expense,
            'user': expense.created_by
        }

        html_message = render_to_string('expenses/emails/expense_paid.html', context)
        plain_message = render_to_string('expenses/emails/expense_paid.txt', context)

        try:
            send_mail(
                subject=f'Expense Paid: {expense.expense_number}',
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[expense.created_by.email],
                html_message=html_message,
                fail_silently=True
            )
        except Exception as e:
            logger.error(f"Failed to send payment notification for expense {expense.id}: {str(e)}")

    total_notifications = recently_approved.count() + recently_paid.count()
    logger.info(f"Sent {total_notifications} status notifications")
    return f"Sent {total_notifications} status notifications"

# Remove or comment out budget-related tasks since ExpenseCategory is removed
# @shared_task
# def generate_budget_reports():
#     """Generate budget utilization reports for managers"""
#     # This function no longer works since ExpenseCategory model was removed
#     return "Budget reports disabled - ExpenseCategory model removed"