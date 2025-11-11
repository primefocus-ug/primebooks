from celery import shared_task
from django.utils import timezone
from django.db.models import Sum, Q
from django.contrib.auth import get_user_model
from datetime import timedelta
from decimal import Decimal
import logging
from celery import shared_task
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import logging
import pandas as pd
from io import BytesIO
import os


from .models import Expense, ExpenseCategory
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
    ).select_related('created_by', 'category')

    if not pending_expenses.exists():
        return "No pending expenses found"

    # Get approvers
    approvers = User.objects.filter(
        is_active=True,
        groups__permissions__codename='approve_expense'
    ).distinct()

    for approver in approvers:
        Notification.objects.create(
            recipient=approver,
            notification_type='expense_reminder',
            title=f"{pending_expenses.count()} Expenses Pending Approval",
            message=f"You have {pending_expenses.count()} expenses waiting for approval for more than 3 days",
            action_url='/expenses/?status=SUBMITTED'
        )

    logger.info(f"Sent reminders for {pending_expenses.count()} pending expenses")
    return f"Sent reminders for {pending_expenses.count()} expenses"


@shared_task
def send_overdue_payment_alerts():
    """Send alerts for approved but unpaid expenses past due date"""

    today = timezone.now().date()

    overdue_expenses = Expense.objects.filter(
        status='APPROVED',
        due_date__lt=today
    ).select_related('created_by')

    if not overdue_expenses.exists():
        return "No overdue expenses found"

    # Notify finance team
    finance_users = User.objects.filter(
        is_active=True,
        groups__permissions__codename='pay_expense'
    ).distinct()

    for user in finance_users:
        total_overdue = overdue_expenses.aggregate(
            total=Sum('amount')
        )['total'] or Decimal('0')

        Notification.objects.create(
            recipient=user,
            notification_type='expense_overdue',
            title=f"{overdue_expenses.count()} Overdue Expenses",
            message=f"Total overdue amount: {total_overdue}. Please process payments.",
            action_url='/expenses/?status=APPROVED'
        )

    logger.info(f"Sent overdue alerts for {overdue_expenses.count()} expenses")
    return f"Sent alerts for {overdue_expenses.count()} overdue expenses"


@shared_task
def generate_monthly_expense_report():
    """Generate monthly expense report for all users"""

    from django.core.mail import send_mail
    from django.template.loader import render_to_string

    # Get last month's date range
    today = timezone.now()
    first_day_last_month = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    last_day_last_month = today.replace(day=1) - timedelta(days=1)

    users = User.objects.filter(is_active=True, created_expenses__isnull=False).distinct()

    for user in users:
        # Get user's expenses for last month
        expenses = Expense.objects.filter(
            created_by=user,
            expense_date__gte=first_day_last_month,
            expense_date__lte=last_day_last_month
        )

        if not expenses.exists():
            continue

        # Calculate statistics
        total_amount = expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        paid_amount = expenses.filter(status='PAID').aggregate(
            Sum('amount')
        )['amount__sum'] or Decimal('0')

        category_breakdown = expenses.values(
            'category__name'
        ).annotate(
            total=Sum('amount')
        ).order_by('-total')

        # Send email report
        context = {
            'user': user,
            'month': first_day_last_month.strftime('%B %Y'),
            'total_expenses': expenses.count(),
            'total_amount': total_amount,
            'paid_amount': paid_amount,
            'category_breakdown': category_breakdown
        }

        html_message = render_to_string('expenses/emails/monthly_report.html', context)

        send_mail(
            subject=f'Monthly Expense Report - {first_day_last_month.strftime("%B %Y")}',
            message='',
            from_email='noreply@example.com',
            recipient_list=[user.email],
            html_message=html_message
        )

    logger.info(f"Sent monthly reports to {users.count()} users")
    return f"Sent reports to {users.count()} users"


@shared_task
def check_budget_utilization():
    """Check and alert for categories exceeding budget thresholds"""

    categories = ExpenseCategory.objects.filter(
        is_active=True,
        monthly_budget__isnull=False
    )

    for category in categories:
        utilization = category.get_budget_utilization()

        if utilization and utilization >= 80:
            # Notify relevant users
            admins = User.objects.filter(
                is_active=True,
                is_staff=True
            )

            for admin in admins:
                Notification.objects.create(
                    recipient=admin,
                    notification_type='budget_alert',
                    title=f"Budget Alert: {category.name}",
                    message=f"Category '{category.name}' has used {utilization:.1f}% of monthly budget",
                    action_url=f'/expenses/?category={category.id}'
                )

    logger.info("Budget utilization check completed")
    return "Budget check completed"


@shared_task
def cleanup_old_draft_expenses():
    """Delete draft expenses older than 30 days"""

    thirty_days_ago = timezone.now() - timedelta(days=30)

    old_drafts = Expense.objects.filter(
        status='DRAFT',
        created_at__lte=thirty_days_ago
    )

    count = old_drafts.count()
    old_drafts.delete()

    logger.info(f"Deleted {count} old draft expenses")
    return f"Deleted {count} old drafts"


@shared_task
def export_expenses_to_csv(user_id, filters=None):
    """Export expenses to CSV file"""

    import csv
    from io import StringIO
    from django.core.files.base import ContentFile

    try:
        user = User.objects.get(id=user_id)

        # Build queryset based on filters
        expenses = Expense.objects.all()
        if filters:
            if 'status' in filters:
                expenses = expenses.filter(status=filters['status'])
            if 'date_from' in filters:
                expenses = expenses.filter(expense_date__gte=filters['date_from'])
            if 'date_to' in filters:
                expenses = expenses.filter(expense_date__lte=filters['date_to'])

        # Create CSV
        output = StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow([
            'Expense Number', 'Title', 'Category', 'Amount', 'Currency',
            'Tax Amount', 'Total Amount', 'Status', 'Expense Date',
            'Created By', 'Vendor', 'Reference Number'
        ])

        # Write data
        for expense in expenses:
            writer.writerow([
                expense.expense_number,
                expense.title,
                expense.category.name,
                expense.amount,
                expense.currency,
                expense.tax_amount,
                expense.total_amount,
                expense.get_status_display(),
                expense.expense_date.strftime('%Y-%m-%d'),
                expense.created_by.get_full_name(),
                expense.vendor_name,
                expense.reference_number
            ])

        # Save file and notify user
        filename = f'expenses_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv'

        Notification.objects.create(
            recipient=user,
            notification_type='export_complete',
            title='Expense Export Complete',
            message=f'Your expense export is ready: {filename}',
            action_url=f'/exports/{filename}'
        )

        logger.info(f"Exported {expenses.count()} expenses for user {user_id}")
        return f"Exported {expenses.count()} expenses"

    except User.DoesNotExist:
        logger.error(f"User {user_id} not found")
        return "User not found"
    except Exception as e:
        logger.error(f"Export failed: {str(e)}")
        return f"Export failed: {str(e)}"


@shared_task
def process_recurring_expenses():
    """Process and create recurring expenses"""

    # This would handle recurring expense creation
    # Implementation depends on your recurring expense logic

    recurring_expenses = Expense.objects.filter(
        is_recurring=True,
        status='PAID'
    )

    created_count = 0
    for expense in recurring_expenses:
        # Check if a new instance should be created
        # This is a simplified example
        last_created = Expense.objects.filter(
            created_by=expense.created_by,
            category=expense.category,
            amount=expense.amount,
            is_recurring=True
        ).order_by('-created_at').first()

        # Logic to determine if new expense should be created
        # based on recurrence pattern

    logger.info(f"Processed {created_count} recurring expenses")
    return f"Created {created_count} recurring expenses"



@shared_task
def export_expenses_to_csv(user_id, filters=None):
    """Export expenses to CSV file asynchronously"""
    from django.contrib.auth import get_user_model
    from .models import Expense
    from .utils import generate_export_filename
    
    User = get_user_model()
    
    try:
        user = User.objects.get(id=user_id)
        filters = filters or {}
        
        # Build queryset based on filters
        expenses = Expense.objects.filter(created_by=user)
        
        if filters.get('status'):
            expenses = expenses.filter(status=filters['status'])
        if filters.get('category'):
            expenses = expenses.filter(category_id=filters['category'])
        if filters.get('date_from'):
            expenses = expenses.filter(expense_date__gte=filters['date_from'])
        if filters.get('date_to'):
            expenses = expenses.filter(expense_date__lte=filters['date_to'])
        
        # Prepare data for export
        data = []
        for expense in expenses.select_related('category', 'store'):
            data.append({
                'Expense Number': expense.expense_number,
                'Title': expense.title,
                'Category': expense.category.name,
                'Amount': float(expense.amount),
                'Tax Amount': float(expense.tax_amount),
                'Total Amount': float(expense.total_amount),
                'Currency': expense.currency,
                'Expense Date': expense.expense_date.isoformat(),
                'Vendor': expense.vendor_name,
                'Status': expense.get_status_display(),
                'Store': expense.store.name if expense.store else '',
                'Description': expense.description,
                'Submitted At': expense.submitted_at.isoformat() if expense.submitted_at else '',
                'Approved At': expense.approved_at.isoformat() if expense.approved_at else '',
                'Paid At': expense.paid_at.isoformat() if expense.paid_at else '',
            })
        
        # Create DataFrame and export to CSV
        df = pd.DataFrame(data)
        
        # Generate filename and path
        filename = generate_export_filename(user, 'csv')
        filepath = os.path.join(settings.MEDIA_ROOT, 'exports', filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        # Save CSV
        df.to_csv(filepath, index=False)
        
        # Send notification email with download link
        send_export_notification.delay(user_id, filename, len(data))
        
        return f"Exported {len(data)} expenses to {filename}"
        
    except Exception as e:
        logger.error(f"Export failed: {str(e)}")
        # Notify user of failure
        send_export_failure_notification.delay(user_id, str(e))
        raise

@shared_task
def send_export_notification(user_id, filename, record_count):
    """Send email notification when export is ready"""
    from django.contrib.auth import get_user_model
    
    User = get_user_model()
    
    try:
        user = User.objects.get(id=user_id)
        
        subject = f"Your expense export is ready"
        download_url = f"{settings.SITE_URL}/media/exports/{filename}"
        
        context = {
            'user': user,
            'filename': filename,
            'record_count': record_count,
            'download_url': download_url,
            'expiry_hours': 24  # Link expires in 24 hours
        }
        
        html_message = render_to_string('expenses/emails/export_ready.html', context)
        plain_message = render_to_string('expenses/emails/export_ready.txt', context)
        
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message
        )
        
    except Exception as e:
        logger.error(f"Failed to send export notification: {str(e)}")

@shared_task
def send_export_failure_notification(user_id, error_message):
    """Send email notification when export fails"""
    from django.contrib.auth import get_user_model
    
    User = get_user_model()
    
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
            html_message=html_message
        )
        
    except Exception as e:
        logger.error(f"Failed to send export failure notification: {str(e)}")

@shared_task
def send_expense_reminders():
    """Send reminders for pending expenses"""
    from .models import Expense
    
    # Find expenses that need reminders
    pending_expenses = Expense.objects.filter(
        status='SUBMITTED',
        submitted_at__lte=timezone.now() - timedelta(days=2)  # After 2 days
    )
    
    for expense in pending_expenses:
        # Send reminder to approvers
        send_pending_approval_reminder.delay(expense.id)

@shared_task
def send_pending_approval_reminder(expense_id):
    """Send reminder for specific pending expense"""
    from .models import Expense
    from django.contrib.auth.models import User
    
    try:
        expense = Expense.objects.get(id=expense_id)
        approvers = User.objects.filter(
            groups__permissions__codename='approve_expense'
        ).distinct()
        
        subject = f"Reminder: Expense pending approval - {expense.expense_number}"
        
        for approver in approvers:
            context = {
                'approver': approver,
                'expense': expense,
                'days_pending': expense.days_pending,
            }
            
            html_message = render_to_string('expenses/emails/approval_reminder.html', context)
            plain_message = render_to_string('expenses/emails/approval_reminder.txt', context)
            
            send_mail(
                subject=subject,
                message=plain_message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[approver.email],
                html_message=html_message
            )
            
    except Expense.DoesNotExist:
        logger.warning(f"Expense {expense_id} not found for reminder")

@shared_task
def cleanup_temp_files():
    """Clean up temporary export files older than 24 hours"""
    import os
    import glob
    from datetime import datetime, timedelta
    
    exports_dir = os.path.join(settings.MEDIA_ROOT, 'exports')
    cutoff_time = datetime.now() - timedelta(hours=24)
    
    if os.path.exists(exports_dir):
        for file_path in glob.glob(os.path.join(exports_dir, '*.csv')):
            file_time = datetime.fromtimestamp(os.path.getctime(file_path))
            if file_time < cutoff_time:
                try:
                    os.remove(file_path)
                    logger.info(f"Cleaned up old export file: {file_path}")
                except OSError as e:
                    logger.error(f"Failed to clean up {file_path}: {str(e)}")