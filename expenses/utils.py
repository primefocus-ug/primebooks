from django.db.models import Sum, Count, Avg, Q
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
import calendar

from .models import Expense, ExpenseCategory


def get_expense_statistics(user=None, date_from=None, date_to=None):
    """Get comprehensive expense statistics"""

    expenses = Expense.objects.all()

    if user:
        expenses = expenses.filter(created_by=user)

    if date_from:
        expenses = expenses.filter(expense_date__gte=date_from)

    if date_to:
        expenses = expenses.filter(expense_date__lte=date_to)

    stats = {
        'total_expenses': expenses.count(),
        'total_amount': expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'average_amount': expenses.aggregate(Avg('amount'))['amount__avg'] or Decimal('0'),
        'status_breakdown': {},
        'category_breakdown': {},
        'monthly_trend': {}
    }

    # Status breakdown
    for status, _ in Expense.STATUS_CHOICES:
        count = expenses.filter(status=status).count()
        amount = expenses.filter(status=status).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        stats['status_breakdown'][status] = {
            'count': count,
            'amount': amount
        }

    # Category breakdown
    category_data = expenses.values('category__name', 'category__color_code').annotate(
        total=Sum('amount'),
        count=Count('id')
    ).order_by('-total')

    for item in category_data:
        stats['category_breakdown'][item['category__name']] = {
            'amount': item['total'],
            'count': item['count'],
            'color': item['category__color_code']
        }

    # Monthly trend (last 6 months)
    for i in range(6):
        month_start = (timezone.now().replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        month_end = month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])

        month_amount = expenses.filter(
            expense_date__gte=month_start,
            expense_date__lte=month_end
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

        stats['monthly_trend'][month_start.strftime('%B %Y')] = month_amount

    return stats


def get_budget_analysis():
    """Get budget utilization analysis for all categories"""

    categories = ExpenseCategory.objects.filter(
        is_active=True,
        monthly_budget__isnull=False
    )

    analysis = []

    for category in categories:
        spent = category.get_monthly_spent()
        budget = category.monthly_budget
        utilization = category.get_budget_utilization()

        analysis.append({
            'category': category,
            'budget': budget,
            'spent': spent,
            'remaining': budget - spent,
            'utilization': utilization,
            'status': get_budget_status(utilization)
        })

    return sorted(analysis, key=lambda x: x['utilization'] or 0, reverse=True)


def get_budget_status(utilization):
    """Get budget status based on utilization percentage"""

    if not utilization:
        return 'unknown'

    if utilization < 50:
        return 'safe'
    elif utilization < 80:
        return 'warning'
    elif utilization < 100:
        return 'critical'
    else:
        return 'exceeded'


def calculate_expense_metrics(expenses):
    """Calculate various metrics for a queryset of expenses"""

    if not expenses.exists():
        return {
            'count': 0,
            'total': Decimal('0'),
            'average': Decimal('0'),
            'min': Decimal('0'),
            'max': Decimal('0')
        }

    aggregates = expenses.aggregate(
        total=Sum('amount'),
        average=Avg('amount'),
        min_amount=Min('amount'),
        max_amount=Max('amount')
    )

    return {
        'count': expenses.count(),
        'total': aggregates['total'] or Decimal('0'),
        'average': aggregates['average'] or Decimal('0'),
        'min': aggregates['min_amount'] or Decimal('0'),
        'max': aggregates['max_amount'] or Decimal('0')
    }


def get_user_expense_summary(user, year=None, month=None):
    """Get detailed expense summary for a user"""

    if not year:
        year = timezone.now().year
    if not month:
        month = timezone.now().month

    expenses = Expense.objects.filter(
        created_by=user,
        expense_date__year=year,
        expense_date__month=month
    )

    summary = {
        'total_submitted': expenses.filter(status='SUBMITTED').count(),
        'total_approved': expenses.filter(status='APPROVED').count(),
        'total_rejected': expenses.filter(status='REJECTED').count(),
        'total_paid': expenses.filter(status='PAID').count(),
        'amount_submitted': expenses.filter(status='SUBMITTED').aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'amount_approved': expenses.filter(status='APPROVED').aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'amount_paid': expenses.filter(status='PAID').aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'pending_reimbursement': expenses.filter(
            is_reimbursable=True,
            status__in=['APPROVED', 'PAID']
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    }

    return summary


def export_expenses_to_excel(expenses, filename):
    """Export expenses to Excel file"""

    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Expenses"

    # Define headers
    headers = [
        'Expense Number', 'Date', 'Title', 'Category', 'Amount', 'Currency',
        'Tax Amount', 'Total Amount', 'Status', 'Created By', 'Vendor',
        'Reference Number', 'Payment Method', 'Notes'
    ]

    # Style headers
    header_fill = PatternFill(start_color='366092', end_color='366092', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF')

    for col_num, header in enumerate(headers, 1):
        cell = sheet.cell(row=1, column=col_num)
        cell.value = header
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center', vertical='center')

    # Add data
    for row_num, expense in enumerate(expenses, 2):
        sheet.cell(row=row_num, column=1).value = expense.expense_number
        sheet.cell(row=row_num, column=2).value = expense.expense_date.strftime('%Y-%m-%d')
        sheet.cell(row=row_num, column=3).value = expense.title
        sheet.cell(row=row_num, column=4).value = expense.category.name
        sheet.cell(row=row_num, column=5).value = float(expense.amount)
        sheet.cell(row=row_num, column=6).value = expense.currency
        sheet.cell(row=row_num, column=7).value = float(expense.tax_amount)
        sheet.cell(row=row_num, column=8).value = float(expense.total_amount)
        sheet.cell(row=row_num, column=9).value = expense.get_status_display()
        sheet.cell(row=row_num, column=10).value = expense.created_by.get_full_name()
        sheet.cell(row=row_num, column=11).value = expense.vendor_name
        sheet.cell(row=row_num, column=12).value = expense.reference_number
        sheet.cell(row=row_num,
                   column=13).value = expense.get_payment_method_display() if expense.payment_method else ''
        sheet.cell(row=row_num, column=14).value = expense.notes

    # Adjust column widths
    for column in sheet.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(cell.value)
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        sheet.column_dimensions[column_letter].width = adjusted_width

    # Save workbook
    workbook.save(filename)
    return filename


def validate_expense_approval(expense, user):
    """Validate if user can approve an expense"""

    errors = []

    # Check permission
    if not user.has_perm('expenses.approve_expense'):
        errors.append("You don't have permission to approve expenses")

    # Check status
    if expense.status not in ['SUBMITTED', 'DRAFT']:
        errors.append(f"Cannot approve expense with status: {expense.get_status_display()}")

    # Check self-approval
    if expense.created_by == user:
        errors.append("You cannot approve your own expense")

    # Check approval threshold
    if expense.category.approval_threshold:
        if expense.amount < expense.category.approval_threshold:
            # Auto-approve
            return {'auto_approve': True, 'errors': []}

    return {'auto_approve': False, 'errors': errors}


def send_expense_notification_email(expense, notification_type):
    """Send email notification for expense events"""

    from django.core.mail import send_mail
    from django.template.loader import render_to_string

    templates = {
        'submitted': 'expenses/emails/expense_submitted.html',
        'approved': 'expenses/emails/expense_approved.html',
        'rejected': 'expenses/emails/expense_rejected.html',
        'paid': 'expenses/emails/expense_paid.html',
    }

    if notification_type not in templates:
        return False

    context = {'expense': expense}
    html_message = render_to_string(templates[notification_type], context)

    subject_map = {
        'submitted': f'Expense Submitted: {expense.expense_number}',
        'approved': f'Expense Approved: {expense.expense_number}',
        'rejected': f'Expense Rejected: {expense.expense_number}',
        'paid': f'Expense Paid: {expense.expense_number}',
    }

    recipient = expense.created_by.email

    try:
        send_mail(
            subject=subject_map[notification_type],
            message='',
            from_email='noreply@example.com',
            recipient_list=[recipient],
            html_message=html_message
        )
        return True
    except Exception as e:
        print(f"Failed to send email: {str(e)}")
        return False


from django.db.models import Min, Max


def get_expense_insights(user=None):
    """Get intelligent insights from expense data"""

    expenses = Expense.objects.filter(status='PAID')

    if user:
        expenses = expenses.filter(created_by=user)

    insights = []

    # Average processing time
    approved_expenses = expenses.filter(
        approved_at__isnull=False,
        submitted_at__isnull=False
    )

    if approved_expenses.exists():
        total_processing_days = sum([
            (exp.approved_at - exp.submitted_at).days
            for exp in approved_expenses
        ])
        avg_processing_days = total_processing_days / approved_expenses.count()

        insights.append({
            'type': 'processing_time',
            'message': f'Average expense approval time: {avg_processing_days:.1f} days',
            'value': avg_processing_days
        })

    # Most expensive category
    top_category = expenses.values('category__name').annotate(
        total=Sum('amount')
    ).order_by('-total').first()

    if top_category:
        insights.append({
            'type': 'top_category',
            'message': f"Highest spending category: {top_category['category__name']}",
            'value': top_category['total']
        })

    # Spending trend
    current_month = timezone.now().replace(day=1)
    last_month = (current_month - timedelta(days=1)).replace(day=1)

    current_month_total = expenses.filter(
        expense_date__gte=current_month
    ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

    last_month_total = expenses.filter(
        expense_date__gte=last_month,
        expense_date__lt=current_month
    ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

    if last_month_total > 0:
        change_percent = ((current_month_total - last_month_total) / last_month_total) * 100
        trend = 'increased' if change_percent > 0 else 'decreased'

        insights.append({
            'type': 'spending_trend',
            'message': f'Spending has {trend} by {abs(change_percent):.1f}% this month',
            'value': change_percent
        })

    return insights