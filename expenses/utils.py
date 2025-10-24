from django.db.models import Sum, Count, Avg, Q, F
from django.utils import timezone
from datetime import timedelta, date
from decimal import Decimal
import io
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from .models import Expense, Budget, Vendor, ExpenseCategory


class ExpenseAnalytics:
    """Analytics and reporting utilities for expenses"""

    @staticmethod
    def get_expense_summary(store=None, start_date=None, end_date=None):
        """Get comprehensive expense summary"""
        expenses = Expense.objects.filter(status='PAID')

        if store:
            expenses = expenses.filter(store=store)
        if start_date:
            expenses = expenses.filter(expense_date__gte=start_date)
        if end_date:
            expenses = expenses.filter(expense_date__lte=end_date)

        summary = expenses.aggregate(
            total_expenses=Sum('total_amount'),
            total_count=Count('id'),
            average_expense=Avg('total_amount'),
            total_tax=Sum('tax_amount')
        )

        # Category breakdown
        category_breakdown = expenses.values(
            'category__name'
        ).annotate(
            total=Sum('total_amount'),
            count=Count('id')
        ).order_by('-total')

        # Vendor breakdown
        vendor_breakdown = expenses.filter(
            vendor__isnull=False
        ).values(
            'vendor__name'
        ).annotate(
            total=Sum('total_amount'),
            count=Count('id')
        ).order_by('-total')[:10]  # Top 10 vendors

        # Payment method breakdown
        payment_breakdown = expenses.values(
            'payment_method'
        ).annotate(
            total=Sum('total_amount'),
            count=Count('id')
        ).order_by('-total')

        return {
            'summary': summary,
            'by_category': list(category_breakdown),
            'by_vendor': list(vendor_breakdown),
            'by_payment_method': list(payment_breakdown)
        }

    @staticmethod
    def get_budget_performance(store=None, period='month'):
        """Analyze budget performance"""
        today = timezone.now().date()

        if period == 'month':
            start_date = today.replace(day=1)
        elif period == 'quarter':
            quarter_start_month = ((today.month - 1) // 3) * 3 + 1
            start_date = today.replace(month=quarter_start_month, day=1)
        elif period == 'year':
            start_date = today.replace(month=1, day=1)
        else:
            start_date = today

        budgets = Budget.objects.filter(
            start_date__lte=today,
            end_date__gte=today,
            is_active=True
        )

        if store:
            budgets = budgets.filter(Q(store=store) | Q(store__isnull=True))

        performance = []
        for budget in budgets:
            performance.append({
                'budget_name': budget.name,
                'category': budget.category.name,
                'allocated': budget.allocated_amount,
                'spent': budget.spent_amount,
                'remaining': budget.remaining_amount,
                'utilization': budget.utilization_percentage,
                'status': budget.status
            })

        return performance

    @staticmethod
    def get_vendor_performance(vendor_id, days=90):
        """Analyze vendor performance"""
        start_date = timezone.now().date() - timedelta(days=days)

        expenses = Expense.objects.filter(
            vendor_id=vendor_id,
            expense_date__gte=start_date,
            status='PAID'
        )

        total_spent = expenses.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')
        transaction_count = expenses.count()
        average_amount = expenses.aggregate(Avg('total_amount'))['total_amount__avg'] or Decimal('0')

        # Payment performance
        on_time_payments = expenses.filter(
            payment_date__lte=F('due_date')
        ).count()

        late_payments = expenses.filter(
            payment_date__gt=F('due_date')
        ).count()

        return {
            'total_spent': total_spent,
            'transaction_count': transaction_count,
            'average_amount': average_amount,
            'on_time_payments': on_time_payments,
            'late_payments': late_payments,
            'on_time_percentage': (on_time_payments / transaction_count * 100) if transaction_count > 0 else 0
        }

    @staticmethod
    def get_expense_trends(store=None, months=12):
        """Get expense trends over time"""
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=months * 30)

        expenses = Expense.objects.filter(
            expense_date__gte=start_date,
            expense_date__lte=end_date,
            status='PAID'
        )

        if store:
            expenses = expenses.filter(store=store)

        # Monthly breakdown
        from django.db.models.functions import TruncMonth
        monthly_data = expenses.annotate(
            month=TruncMonth('expense_date')
        ).values('month').annotate(
            total=Sum('total_amount'),
            count=Count('id')
        ).order_by('month')

        return list(monthly_data)

    @staticmethod
    def get_overdue_report(store=None):
        """Get overdue expenses report"""
        today = timezone.now().date()

        overdue = Expense.objects.filter(
            due_date__lt=today,
            status__in=['APPROVED', 'PARTIALLY_PAID']
        )

        if store:
            overdue = overdue.filter(store=store)

        overdue_data = []
        for expense in overdue:
            overdue_data.append({
                'expense_number': expense.expense_number,
                'vendor': expense.vendor.name if expense.vendor else 'N/A',
                'amount_due': expense.amount_due,
                'due_date': expense.due_date,
                'days_overdue': expense.days_overdue,
                'category': expense.category.name
            })

        return overdue_data


class ExpenseExporter:
    """Export expenses to various formats"""

    @staticmethod
    def export_to_excel(expenses, filename='expenses.xlsx'):
        """Export expenses to Excel file"""
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Expenses"

        # Styles
        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        header_alignment = Alignment(horizontal="center", vertical="center")

        # Headers
        headers = [
            'Expense Number', 'Date', 'Category', 'Vendor', 'Description',
            'Amount', 'Tax', 'Total', 'Status', 'Payment Method', 'Store'
        ]

        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.value = header
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_alignment

        # Data rows
        for row_num, expense in enumerate(expenses, 2):
            ws.cell(row=row_num, column=1).value = expense.expense_number
            ws.cell(row=row_num, column=2).value = expense.expense_date.strftime('%Y-%m-%d')
            ws.cell(row=row_num, column=3).value = expense.category.name
            ws.cell(row=row_num, column=4).value = expense.vendor.name if expense.vendor else 'N/A'
            ws.cell(row=row_num, column=5).value = expense.description[:100]
            ws.cell(row=row_num, column=6).value = float(expense.amount)
            ws.cell(row=row_num, column=7).value = float(expense.tax_amount)
            ws.cell(row=row_num, column=8).value = float(expense.total_amount)
            ws.cell(row=row_num, column=9).value = expense.get_status_display()
            ws.cell(row=row_num, column=10).value = expense.get_payment_method_display()
            ws.cell(row=row_num, column=11).value = expense.store.name

        # Auto-adjust column widths
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(cell.value)
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width

        # Save to BytesIO
        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        return output

    @staticmethod
    def export_to_pdf(expenses, company_info=None):
        """Export expenses to PDF file"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            textColor=colors.HexColor('#366092'),
            spaceAfter=30,
            alignment=1  # Center
        )

        elements.append(Paragraph("Expense Report", title_style))
        elements.append(Spacer(1, 0.2 * inch))

        # Company info if provided
        if company_info:
            company_style = styles['Normal']
            elements.append(Paragraph(f"<b>{company_info.get('name', '')}</b>", company_style))
            elements.append(Paragraph(company_info.get('address', ''), company_style))
            elements.append(Spacer(1, 0.3 * inch))

        # Summary
        total_amount = sum(e.total_amount for e in expenses)
        total_tax = sum(e.tax_amount for e in expenses)

        summary_data = [
            ['Total Expenses:', f'{total_amount:,.2f}'],
            ['Total Tax:', f'{total_tax:,.2f}'],
            ['Number of Expenses:', str(len(expenses))]
        ]

        summary_table = Table(summary_data, colWidths=[3 * inch, 2 * inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
            ('TEXTCOLOR', (0, 0), (-1, -1), colors.black),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))

        elements.append(summary_table)
        elements.append(Spacer(1, 0.5 * inch))

        # Expenses table
        table_data = [['Expense #', 'Date', 'Category', 'Vendor', 'Amount', 'Status']]

        for expense in expenses:
            table_data.append([
                expense.expense_number,
                expense.expense_date.strftime('%Y-%m-%d'),
                expense.category.name[:20],
                expense.vendor.name[:20] if expense.vendor else 'N/A',
                f'{expense.total_amount:,.2f}',
                expense.get_status_display()
            ])

        expense_table = Table(table_data, colWidths=[1.2 * inch, 1 * inch, 1.3 * inch, 1.3 * inch, 1 * inch, 1 * inch])
        expense_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#366092')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
        ]))

        elements.append(expense_table)

        # Build PDF
        doc.build(elements)
        buffer.seek(0)

        return buffer

    @staticmethod
    def export_to_csv(expenses):
        """Export expenses to CSV format"""
        import csv

        output = io.StringIO()
        writer = csv.writer(output)

        # Headers
        writer.writerow([
            'Expense Number', 'Date', 'Category', 'Vendor', 'Description',
            'Amount', 'Tax', 'Total', 'Status', 'Payment Method', 'Store'
        ])

        # Data
        for expense in expenses:
            writer.writerow([
                expense.expense_number,
                expense.expense_date.strftime('%Y-%m-%d'),
                expense.category.name,
                expense.vendor.name if expense.vendor else 'N/A',
                expense.description[:200],
                float(expense.amount),
                float(expense.tax_amount),
                float(expense.total_amount),
                expense.get_status_display(),
                expense.get_payment_method_display(),
                expense.store.name
            ])

        output.seek(0)
        return output


class BudgetCalculator:
    """Budget calculation and forecasting utilities"""

    @staticmethod
    def calculate_budget_forecast(category, store=None, months_ahead=3):
        """Forecast future budget needs based on historical data"""
        today = timezone.now().date()
        lookback_months = 6
        start_date = today - timedelta(days=lookback_months * 30)

        expenses = Expense.objects.filter(
            category=category,
            expense_date__gte=start_date,
            expense_date__lte=today,
            status='PAID'
        )

        if store:
            expenses = expenses.filter(store=store)

        # Calculate monthly averages
        from django.db.models.functions import TruncMonth
        monthly_totals = expenses.annotate(
            month=TruncMonth('expense_date')
        ).values('month').annotate(
            total=Sum('total_amount')
        ).order_by('month')

        if not monthly_totals:
            return None

        # Calculate average and trend
        totals = [item['total'] for item in monthly_totals]
        average_monthly = sum(totals) / len(totals)

        # Simple linear regression for trend
        if len(totals) > 1:
            x_values = list(range(len(totals)))
            x_mean = sum(x_values) / len(x_values)
            y_mean = sum(totals) / len(totals)

            numerator = sum((x - x_mean) * (float(y) - float(y_mean)) for x, y in zip(x_values, totals))
            denominator = sum((x - x_mean) ** 2 for x in x_values)

            slope = numerator / denominator if denominator != 0 else 0
        else:
            slope = 0

        # Forecast
        forecast = []
        for i in range(1, months_ahead + 1):
            predicted_amount = float(average_monthly) + (slope * (len(totals) + i))
            forecast.append({
                'month_offset': i,
                'predicted_amount': Decimal(str(max(0, predicted_amount))).quantize(Decimal('0.01'))
            })

        return {
            'historical_average': average_monthly,
            'trend': 'increasing' if slope > 0 else 'decreasing' if slope < 0 else 'stable',
            'forecast': forecast
        }

    @staticmethod
    def recommend_budget_allocation(store, period='month'):
        """Recommend budget allocation based on historical spending"""
        today = timezone.now().date()
        lookback_days = 180  # 6 months
        start_date = today - timedelta(days=lookback_days)

        # Get historical spending by category
        category_spending = Expense.objects.filter(
            store=store,
            expense_date__gte=start_date,
            expense_date__lte=today,
            status='PAID'
        ).values(
            'category__id', 'category__name'
        ).annotate(
            total=Sum('total_amount'),
            count=Count('id')
        ).order_by('-total')

        # Calculate recommended allocations
        total_spent = sum(item['total'] for item in category_spending)

        recommendations = []
        for item in category_spending:
            percentage = (item['total'] / total_spent * 100) if total_spent > 0 else 0

            # Add 10% buffer
            recommended_amount = item['total'] / (lookback_days / 30) * 1.1

            recommendations.append({
                'category_id': item['category__id'],
                'category_name': item['category__name'],
                'historical_average': item['total'] / (lookback_days / 30),
                'recommended_amount': recommended_amount.quantize(Decimal('0.01')),
                'percentage_of_total': percentage,
                'transaction_count': item['count']
            })

        return recommendations


class TaxCalculator:
    """Tax calculation utilities for EFRIS compliance"""

    @staticmethod
    def calculate_input_tax_credit(expenses):
        """Calculate total input tax that can be claimed"""
        eligible_expenses = expenses.filter(
            can_claim_input_tax=True,
            is_efris_compliant=True,
            status='PAID'
        )

        total_input_tax = eligible_expenses.aggregate(
            Sum('tax_amount')
        )['tax_amount__sum'] or Decimal('0')

        breakdown = eligible_expenses.values(
            'category__name'
        ).annotate(
            total_tax=Sum('tax_amount'),
            count=Count('id')
        ).order_by('-total_tax')

        return {
            'total_input_tax': total_input_tax,
            'eligible_expense_count': eligible_expenses.count(),
            'breakdown': list(breakdown)
        }

    @staticmethod
    def generate_tax_report(store, start_date, end_date):
        """Generate comprehensive tax report for EFRIS"""
        expenses = Expense.objects.filter(
            store=store,
            expense_date__gte=start_date,
            expense_date__lte=end_date,
            status='PAID'
        )

        # Total expenses
        total_expenses = expenses.aggregate(
            total=Sum('total_amount'),
            tax=Sum('tax_amount')
        )

        # VAT breakdown
        vat_expenses = expenses.filter(tax_rate__gt=0)
        vat_summary = vat_expenses.values('tax_rate').annotate(
            total=Sum('total_amount'),
            tax=Sum('tax_amount'),
            count=Count('id')
        ).order_by('-tax_rate')

        # EFRIS compliant expenses
        efris_compliant = expenses.filter(is_efris_compliant=True)
        efris_summary = {
            'compliant_count': efris_compliant.count(),
            'compliant_total': efris_compliant.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0'),
            'compliant_tax': efris_compliant.aggregate(Sum('tax_amount'))['tax_amount__sum'] or Decimal('0'),
            'non_compliant_count': expenses.count() - efris_compliant.count(),
        }

        # Input tax credit
        input_tax = TaxCalculator.calculate_input_tax_credit(expenses)

        return {
            'period': {
                'start_date': start_date,
                'end_date': end_date
            },
            'total_expenses': total_expenses,
            'vat_breakdown': list(vat_summary),
            'efris_compliance': efris_summary,
            'input_tax_credit': input_tax
        }


class ExpenseValidator:
    """Validation utilities for expenses"""

    @staticmethod
    def validate_expense_amount(expense):
        """Validate expense amount against budget and limits"""
        errors = []
        warnings = []

        # Check budget
        if expense.category:
            budgets = Budget.objects.filter(
                category=expense.category,
                start_date__lte=expense.expense_date,
                end_date__gte=expense.expense_date,
                is_active=True
            )

            if expense.store:
                budgets = budgets.filter(Q(store=expense.store) | Q(store__isnull=True))

            for budget in budgets:
                if budget.is_exceeded():
                    errors.append(f"Budget '{budget.name}' is already exceeded")
                elif budget.spent_amount + expense.total_amount > budget.allocated_amount:
                    overage = budget.spent_amount + expense.total_amount - budget.allocated_amount
                    warnings.append(f"This expense will exceed budget '{budget.name}' by {overage}")

        # Check vendor credit limit
        if expense.vendor and expense.vendor.credit_limit:
            if not expense.vendor.within_credit_limit(expense.total_amount):
                errors.append(f"Expense exceeds vendor credit limit")

        return {
            'is_valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings
        }

    @staticmethod
    def validate_efris_compliance(expense):
        """Validate EFRIS compliance requirements"""
        issues = []

        if not expense.vendor:
            issues.append("No vendor specified")
        elif not expense.vendor.is_registered_for_vat:
            issues.append("Vendor is not VAT registered")

        if not expense.invoice_number:
            issues.append("No invoice number provided")

        if expense.tax_amount > 0 and not expense.efris_invoice_number:
            issues.append("EFRIS invoice number required for tax claims")

        if not expense.efris_verification_code and expense.tax_amount > 0:
            issues.append("EFRIS verification code missing")

        return {
            'is_compliant': len(issues) == 0,
            'issues': issues
        }


class ExpenseNotificationManager:
    """Centralized notification management"""

    @staticmethod
    def send_approval_reminder(expense):
        """Send reminder for pending approval"""
        from django.core.mail import send_mail
        from django.conf import settings

        # Get pending approvers
        pending_approvals = expense.approvals.filter(status='PENDING')

        for approval in pending_approvals:
            if approval.approver.email:
                send_mail(
                    subject=f'Reminder: Expense Approval Required - {expense.expense_number}',
                    message=f'This is a reminder that the following expense requires your approval:\n\n'
                            f'Expense: {expense.expense_number}\n'
                            f'Amount: {expense.total_amount} {expense.currency}\n'
                            f'Description: {expense.description}\n'
                            f'Submitted: {expense.created_at.strftime("%Y-%m-%d %H:%M")}\n\n'
                            f'Please review and approve/reject this expense.',
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[approval.approver.email],
                    fail_silently=True,
                )

    @staticmethod
    def send_payment_reminder(expense):
        """Send reminder for payment due"""
        from django.core.mail import send_mail
        from django.conf import settings

        if expense.created_by.email:
            send_mail(
                subject=f'Payment Due: {expense.expense_number}',
                message=f'Payment is due for the following expense:\n\n'
                        f'Expense: {expense.expense_number}\n'
                        f'Amount: {expense.total_amount} {expense.currency}\n'
                        f'Due Date: {expense.due_date}\n'
                        f'Vendor: {expense.vendor.name if expense.vendor else "N/A"}\n\n'
                        f'Please arrange for payment.',
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[expense.created_by.email],
                fail_silently=True,
            )


def get_expense_statistics(store=None, start_date=None, end_date=None):
    """Get comprehensive expense statistics"""
    expenses = Expense.objects.filter(status='PAID')

    if store:
        expenses = expenses.filter(store=store)
    if start_date:
        expenses = expenses.filter(expense_date__gte=start_date)
    if end_date:
        expenses = expenses.filter(expense_date__lte=end_date)

    stats = {
        'total_amount': expenses.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0'),
        'total_count': expenses.count(),
        'average_amount': expenses.aggregate(Avg('total_amount'))['total_amount__avg'] or Decimal('0'),
        'total_tax': expenses.aggregate(Sum('tax_amount'))['tax_amount__sum'] or Decimal('0'),
        'by_type': list(expenses.values('expense_type').annotate(
            total=Sum('total_amount'),
            count=Count('id')
        ).order_by('-total')),
        'by_category': list(expenses.values('category__name').annotate(
            total=Sum('total_amount'),
            count=Count('id')
        ).order_by('-total')),
        'by_payment_method': list(expenses.values('payment_method').annotate(
            total=Sum('total_amount'),
            count=Count('id')
        ).order_by('-total')),
    }

    return stats