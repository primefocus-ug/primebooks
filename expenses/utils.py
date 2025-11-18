from django.db.models import Sum, Count, Avg, Q, Min, Max
from django.utils import timezone
from django.conf import settings
from decimal import Decimal, InvalidOperation
from datetime import timedelta
import calendar
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

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
        'min_amount': expenses.aggregate(Min('amount'))['amount__min'] or Decimal('0'),
        'max_amount': expenses.aggregate(Max('amount'))['amount__max'] or Decimal('0'),
        'status_breakdown': {},
        'category_breakdown': {},
        'monthly_trend': {}
    }

    # Status breakdown
    for status, _ in Expense.STATUS_CHOICES:
        status_expenses = expenses.filter(status=status)
        count = status_expenses.count()
        amount = status_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        stats['status_breakdown'][status] = {
            'count': count,
            'amount': amount,
            'percentage': (count / stats['total_expenses'] * 100) if stats['total_expenses'] > 0 else 0
        }

    # Category breakdown
    category_data = expenses.values('category__name', 'category__color_code').annotate(
        total=Sum('amount'),
        count=Count('id'),
        avg=Avg('amount')
    ).order_by('-total')

    for item in category_data:
        stats['category_breakdown'][item['category__name']] = {
            'amount': item['total'],
            'count': item['count'],
            'average': item['avg'],
            'color': item['category__color_code'],
            'percentage': (item['total'] / stats['total_amount'] * 100) if stats['total_amount'] > 0 else 0
        }

    # Monthly trend (last 6 months)
    today = timezone.now().date()
    for i in range(6):
        month_start = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        month_end = month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])

        month_expenses = expenses.filter(
            expense_date__gte=month_start,
            expense_date__lte=month_end
        )

        month_amount = month_expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
        month_count = month_expenses.count()

        stats['monthly_trend'][month_start.strftime('%B %Y')] = {
            'amount': month_amount,
            'count': month_count
        }

    return stats


def get_budget_analysis():
    """Get budget utilization analysis for all categories"""
    categories = ExpenseCategory.objects.filter(
        is_active=True,
        monthly_budget__isnull=False,
        monthly_budget__gt=0
    )

    analysis = []

    for category in categories:
        spent = category.get_monthly_spent()
        budget = category.monthly_budget
        utilization = category.get_budget_utilization()
        remaining = budget - spent

        analysis.append({
            'category': category,
            'budget': budget,
            'spent': spent,
            'remaining': remaining,
            'utilization': utilization,
            'status': get_budget_status(utilization),
            'is_over_budget': spent > budget,
            'variance': spent - budget,
            'expense_count': category.expenses.filter(
                expense_date__year=timezone.now().year,
                expense_date__month=timezone.now().month
            ).count()
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
            'max': Decimal('0'),
            'median': Decimal('0')
        }

    aggregates = expenses.aggregate(
        total=Sum('amount'),
        average=Avg('amount'),
        min_amount=Min('amount'),
        max_amount=Max('amount')
    )

    # Calculate median
    count = expenses.count()
    if count > 0:
        middle = count // 2
        if count % 2 == 0:
            median = (expenses.order_by('amount')[middle - 1].amount +
                      expenses.order_by('amount')[middle].amount) / 2
        else:
            median = expenses.order_by('amount')[middle].amount
    else:
        median = Decimal('0')

    return {
        'count': count,
        'total': aggregates['total'] or Decimal('0'),
        'average': aggregates['average'] or Decimal('0'),
        'min': aggregates['min_amount'] or Decimal('0'),
        'max': aggregates['max_amount'] or Decimal('0'),
        'median': median
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
        'period': f"{calendar.month_name[month]} {year}",
        'total_count': expenses.count(),
        'total_submitted': expenses.filter(status='SUBMITTED').count(),
        'total_approved': expenses.filter(status='APPROVED').count(),
        'total_rejected': expenses.filter(status='REJECTED').count(),
        'total_paid': expenses.filter(status='PAID').count(),
        'total_draft': expenses.filter(status='DRAFT').count(),
        'amount_submitted': expenses.filter(status='SUBMITTED').aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'amount_approved': expenses.filter(status='APPROVED').aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'amount_paid': expenses.filter(status='PAID').aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'amount_total': expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'pending_reimbursement': expenses.filter(
            is_reimbursable=True,
            status__in=['APPROVED', 'PAID']
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0'),
        'category_breakdown': expenses.values('category__name').annotate(
            total=Sum('amount'),
            count=Count('id')
        ).order_by('-total')
    }

    return summary


def export_expenses_to_excel(expenses, filename=None):
    """Export expenses to Excel file with formatting"""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Expenses"

    # Define headers
    headers = [
        'Expense Number', 'Date', 'Title', 'Category', 'Amount', 'Currency',
        'Tax Amount', 'Total Amount', 'Status', 'Created By', 'Vendor',
        'Reference Number', 'Store', 'Payment Method', 'Submitted At',
        'Approved At', 'Approved By', 'Paid At', 'Notes'
    ]

    # Style headers
    header_fill = PatternFill(start_color='366092', end_color='366092', fill_type='solid')
    header_font = Font(bold=True, color='FFFFFF', size=11)
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # Add headers
    for col_num, header in enumerate(headers, 1):
        cell = sheet.cell(row=1, column=col_num)
        cell.value = header
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = header_alignment
        cell.border = thin_border

    # Add data
    for row_num, expense in enumerate(expenses, 2):
        data_row = [
            expense.expense_number,
            expense.expense_date.strftime('%Y-%m-%d'),
            expense.title,
            expense.category.name,
            float(expense.amount),
            expense.currency,
            float(expense.tax_amount),
            float(expense.total_amount),
            expense.get_status_display(),
            expense.created_by.get_full_name(),
            expense.vendor_name,
            expense.reference_number,
            expense.store.name if expense.store else '',
            expense.get_payment_method_display() if expense.payment_method else '',
            expense.submitted_at.strftime('%Y-%m-%d %H:%M') if expense.submitted_at else '',
            expense.approved_at.strftime('%Y-%m-%d %H:%M') if expense.approved_at else '',
            expense.approved_by.get_full_name() if expense.approved_by else '',
            expense.paid_at.strftime('%Y-%m-%d %H:%M') if expense.paid_at else '',
            expense.notes
        ]

        for col_num, value in enumerate(data_row, 1):
            cell = sheet.cell(row=row_num, column=col_num)
            cell.value = value
            cell.border = thin_border

            # Format numbers
            if col_num in [5, 7, 8]:  # Amount columns
                cell.number_format = '#,##0.00'

            # Align text
            if col_num in [1, 2, 6, 9]:  # Centered columns
                cell.alignment = Alignment(horizontal='center')

    # Adjust column widths
    for column in sheet.columns:
        max_length = 0
        column_letter = get_column_letter(column[0].column)
        for cell in column:
            try:
                if cell.value:
                    max_length = max(max_length, len(str(cell.value)))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        sheet.column_dimensions[column_letter].width = adjusted_width

    # Freeze header row
    sheet.freeze_panes = 'A2'

    # Save workbook
    if not filename:
        filename = f'expenses_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx'

    workbook.save(filename)
    return filename


def validate_expense_approval(expense, user):
    """Validate if user can approve an expense"""
    errors = []
    warnings = []

    # Check permission
    if not user.has_perm('expenses.approve_expense'):
        errors.append("You don't have permission to approve expenses")

    # Check status
    if expense.status not in ['SUBMITTED']:
        errors.append(f"Cannot approve expense with status: {expense.get_status_display()}")

    # Check self-approval
    if expense.created_by == user:
        errors.append("You cannot approve your own expense")

    # Check if already approved
    if expense.approved_by:
        errors.append("This expense has already been approved")

    # Check approval threshold and budget
    if expense.category.approval_threshold:
        if expense.amount >= expense.category.approval_threshold:
            warnings.append(f"This expense exceeds the approval threshold of {expense.category.approval_threshold}")

    # Check budget utilization
    if expense.category.monthly_budget:
        spent = expense.category.get_monthly_spent()
        if spent + expense.amount > expense.category.monthly_budget:
            warnings.append(f"Approving this expense will exceed the monthly budget for {expense.category.name}")

    # Check for missing attachments
    if expense.category.requires_approval and not expense.attachments.exists():
        warnings.append("This expense has no attachments")

    # Check for missing vendor
    if not expense.vendor_name:
        warnings.append("Vendor name is missing")

    return {
        'auto_approve': False,
        'errors': errors,
        'warnings': warnings
    }


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

    context = {
        'expense': expense,
        'site_url': settings.SITE_URL,
        'expense_url': f"{settings.SITE_URL}/expenses/{expense.id}/"
    }

    html_message = render_to_string(templates[notification_type], context)
    plain_message = render_to_string(
        templates[notification_type].replace('.html', '.txt'),
        context
    )

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
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient],
            html_message=html_message,
            fail_silently=False
        )
        return True
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to send email to {recipient}: {str(e)}")
        return False


def get_expense_insights(user=None):
    """Get intelligent insights from expense data"""
    expenses = Expense.objects.filter(status__in=['APPROVED', 'PAID'])

    if user:
        expenses = expenses.filter(created_by=user)

    insights = []

    # Average processing time
    approved_expenses = expenses.filter(
        approved_at__isnull=False,
        submitted_at__isnull=False
    )

    if approved_expenses.exists():
        processing_times = [
            (exp.approved_at - exp.submitted_at).total_seconds() / 86400  # Convert to days
            for exp in approved_expenses
            if exp.approved_at and exp.submitted_at
        ]

        if processing_times:
            avg_processing_days = sum(processing_times) / len(processing_times)
            insights.append({
                'type': 'processing_time',
                'icon': 'clock',
                'message': f'Average expense approval time: {avg_processing_days:.1f} days',
                'value': avg_processing_days,
                'severity': 'warning' if avg_processing_days > 5 else 'info'
            })

    # Most expensive category
    category_totals = expenses.values('category__name', 'category__id').annotate(
        total=Sum('amount')
    ).order_by('-total')

    if category_totals:
        top_category = category_totals[0]
        insights.append({
            'type': 'top_category',
            'icon': 'trending-up',
            'message': f"Highest spending category: {top_category['category__name']}",
            'value': float(top_category['total']),
            'category_id': top_category['category__id']
        })

    # Spending trend
    current_month = timezone.now().replace(day=1).date()
    last_month = (current_month - timedelta(days=1)).replace(day=1)
    last_month_end = current_month - timedelta(days=1)

    current_month_total = expenses.filter(
        expense_date__gte=current_month
    ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

    last_month_total = expenses.filter(
        expense_date__gte=last_month,
        expense_date__lte=last_month_end
    ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

    if last_month_total > 0:
        change_percent = ((current_month_total - last_month_total) / last_month_total) * 100
        trend = 'increased' if change_percent > 0 else 'decreased'
        severity = 'warning' if change_percent > 20 else 'info'

        insights.append({
            'type': 'spending_trend',
            'icon': 'trending-up' if change_percent > 0 else 'trending-down',
            'message': f'Spending has {trend} by {abs(change_percent):.1f}% this month',
            'value': float(change_percent),
            'severity': severity
        })

    # Budget alerts
    overbudget_categories = ExpenseCategory.objects.filter(
        is_active=True,
        monthly_budget__isnull=False
    )

    for category in overbudget_categories:
        spent = category.get_monthly_spent()
        if category.monthly_budget and spent > category.monthly_budget:
            overage = spent - category.monthly_budget
            insights.append({
                'type': 'budget_exceeded',
                'icon': 'alert-circle',
                'message': f'{category.name} is over budget by {float(overage):,.2f}',
                'value': float(overage),
                'severity': 'error',
                'category_id': category.id
            })

    # Pending reimbursements
    if user:
        pending_reimbursement = Expense.objects.filter(
            created_by=user,
            is_reimbursable=True,
            status__in=['APPROVED']
        ).aggregate(Sum('amount'))['amount__sum'] or Decimal('0')

        if pending_reimbursement > 0:
            insights.append({
                'type': 'pending_reimbursement',
                'icon': 'dollar-sign',
                'message': f'You have {float(pending_reimbursement):,.2f} pending reimbursement',
                'value': float(pending_reimbursement),
                'severity': 'info'
            })

    # Frequent vendors
    vendor_counts = expenses.exclude(vendor_name='').values('vendor_name').annotate(
        count=Count('id'),
        total=Sum('amount')
    ).order_by('-count')[:3]

    if vendor_counts:
        top_vendor = vendor_counts[0]
        insights.append({
            'type': 'frequent_vendor',
            'icon': 'shopping-bag',
            'message': f"Most frequent vendor: {top_vendor['vendor_name']} ({top_vendor['count']} expenses)",
            'value': top_vendor['count']
        })

    return insights


def generate_expense_report_pdf(expenses, title="Expense Report"):
    """Generate PDF report for expenses"""
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
    elements = []

    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#1a237e'),
        spaceAfter=30,
        alignment=TA_CENTER
    )

    # Title
    elements.append(Paragraph(title, title_style))
    elements.append(Spacer(1, 0.3 * inch))

    # Summary statistics
    total_amount = expenses.aggregate(Sum('amount'))['amount__sum'] or Decimal('0')
    summary_data = [
        ['Report Generated:', timezone.now().strftime('%Y-%m-%d %H:%M')],
        ['Total Expenses:', str(expenses.count())],
        ['Total Amount:', f"UGX {total_amount:,.2f}"],
    ]

    summary_table = Table(summary_data, colWidths=[2 * inch, 4 * inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.grey),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black)
    ]))

    elements.append(summary_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Expense details table
    if expenses.exists():
        data = [['#', 'Date', 'Description', 'Category', 'Amount', 'Status']]

        for i, expense in enumerate(expenses[:50], 1):  # Limit to 50 for PDF
            data.append([
                str(i),
                expense.expense_date.strftime('%Y-%m-%d'),
                expense.title[:30] + '...' if len(expense.title) > 30 else expense.title,
                expense.category.name[:20],
                f"{expense.amount:,.2f}",
                expense.get_status_display()
            ])

        detail_table = Table(data, colWidths=[0.4 * inch, 1 * inch, 2.2 * inch, 1.3 * inch, 1 * inch, 1 * inch])
        detail_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.lightgrey])
        ]))

        elements.append(detail_table)

    # Build PDF
    doc.build(elements)
    buffer.seek(0)

    return buffer


def generate_export_filename(user, file_type='xlsx'):
    """Generate standardized export filename"""
    timestamp = timezone.now().strftime('%Y%m%d_%H%M%S')
    return f'expenses_export_{user.id}_{timestamp}.{file_type}'


def validate_expense_amount(amount, category=None):
    """Validate expense amount against various rules"""
    errors = []
    warnings = []

    try:
        amount = Decimal(str(amount))

        if amount <= 0:
            errors.append("Amount must be greater than zero")

        if amount > Decimal('10000000'):  # 10 million threshold
            warnings.append("This is an unusually large amount. Please verify.")

        if category and category.monthly_budget:
            spent_this_month = category.get_monthly_spent()
            if spent_this_month + amount > category.monthly_budget:
                warnings.append(
                    f"This expense will exceed the monthly budget for {category.name}. "
                    f"Current: {spent_this_month:,.2f}, Budget: {category.monthly_budget:,.2f}"
                )

        if category and category.approval_threshold:
            if amount >= category.approval_threshold:
                warnings.append(
                    f"This expense requires approval (threshold: {category.approval_threshold:,.2f})"
                )

    except (ValueError, InvalidOperation):
        errors.append("Invalid amount format")

    return {
        'is_valid': len(errors) == 0,
        'errors': errors,
        'warnings': warnings
    }