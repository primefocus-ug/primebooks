from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models import Sum, Count, Avg
from django.db.models.functions import TruncDate, TruncWeek, TruncMonth
import io
from decimal import Decimal

# For PDF generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import VerticalBarChart

# For Excel generation
import openpyxl
from openpyxl.chart import PieChart, BarChart, Reference
from openpyxl.styles import Font, Alignment, PatternFill

# For charts
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt


def get_date_range(period):
    """Get start and end dates based on period"""
    today = timezone.now().date()

    if period == 'today':
        return today, today
    elif period == 'week':
        start = today - timedelta(days=today.weekday())
        return start, today
    elif period == 'fortnight':
        return today - timedelta(days=14), today
    elif period == 'month':
        start = today.replace(day=1)
        return start, today
    elif period == 'quarter':
        quarter_month = ((today.month - 1) // 3) * 3 + 1
        start = today.replace(month=quarter_month, day=1)
        return start, today
    elif period == '6months':
        return today - timedelta(days=182), today
    elif period == 'year':
        start = today.replace(month=1, day=1)
        return start, today

    return None, None


def get_expense_summary(expenses):
    """Generate summary statistics"""
    total = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0.00')
    count = expenses.count()
    avg = expenses.aggregate(avg=Avg('amount'))['avg'] or Decimal('0.00')

    # Group by tags
    tag_summary = {}
    for expense in expenses:
        for tag in expense.tags.all():
            if tag.name not in tag_summary:
                tag_summary[tag.name] = Decimal('0.00')
            tag_summary[tag.name] += expense.amount

    # Sort by amount
    tag_summary = dict(sorted(tag_summary.items(), key=lambda x: x[1], reverse=True))

    return {
        'total': total,
        'count': count,
        'average': avg,
        'by_tag': tag_summary
    }


def generate_chart_data(expenses, group_by='date'):
    """Generate data for charts"""
    if group_by == 'date':
        data = expenses.annotate(
            period=TruncDate('date')
        ).values('period').annotate(
            total=Sum('amount')
        ).order_by('period')
    elif group_by == 'week':
        data = expenses.annotate(
            period=TruncWeek('date')
        ).values('period').annotate(
            total=Sum('amount')
        ).order_by('period')
    elif group_by == 'month':
        data = expenses.annotate(
            period=TruncMonth('date')
        ).values('period').annotate(
            total=Sum('amount')
        ).order_by('period')

    return list(data)


def create_pie_chart_image(tag_summary):
    """Create pie chart for tags"""
    if not tag_summary:
        return None

    fig, ax = plt.subplots(figsize=(8, 6))
    labels = list(tag_summary.keys())[:10]  # Top 10
    sizes = [float(tag_summary[label]) for label in labels]

    ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
    ax.axis('equal')

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight')
    buffer.seek(0)
    plt.close()

    return buffer


def create_bar_chart_image(chart_data):
    """Create bar chart for time-based data"""
    if not chart_data:
        return None

    fig, ax = plt.subplots(figsize=(10, 6))
    dates = [item['period'].strftime('%Y-%m-%d') for item in chart_data]
    amounts = [float(item['total']) for item in chart_data]

    ax.bar(dates, amounts)
    ax.set_xlabel('Date')
    ax.set_ylabel('Amount ($)')
    ax.set_title('Expenses Over Time')
    plt.xticks(rotation=45, ha='right')
    plt.tight_layout()

    buffer = io.BytesIO()
    plt.savefig(buffer, format='png', bbox_inches='tight')
    buffer.seek(0)
    plt.close()

    return buffer


def export_to_pdf(expenses, summary, filters):
    """Export expenses to PDF with charts"""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    elements = []
    styles = getSampleStyleSheet()

    # Title
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=30,
    )
    elements.append(Paragraph('Expense Report', title_style))
    elements.append(Spacer(1, 0.2 * inch))

    # Summary section
    summary_data = [
        ['Total Expenses:', f"${summary['total']:,.2f}"],
        ['Number of Expenses:', str(summary['count'])],
        ['Average Expense:', f"${summary['average']:,.2f}"],
    ]

    summary_table = Table(summary_data, colWidths=[3 * inch, 2 * inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#ecf0f1')),
        ('TEXTCOLOR', (0, 0), (-1, -1), colors.HexColor('#2c3e50')),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 0.3 * inch))

    # Add pie chart for tags
    if summary['by_tag']:
        elements.append(Paragraph('Expenses by Tag', styles['Heading2']))
        pie_image = create_pie_chart_image(summary['by_tag'])
        if pie_image:
            elements.append(Image(pie_image, width=5 * inch, height=3.75 * inch))
            elements.append(Spacer(1, 0.3 * inch))

    # Add bar chart for time series
    chart_data = generate_chart_data(expenses, group_by='date')
    if chart_data:
        elements.append(Paragraph('Expenses Over Time', styles['Heading2']))
        bar_image = create_bar_chart_image(chart_data)
        if bar_image:
            elements.append(Image(bar_image, width=6 * inch, height=3.6 * inch))
            elements.append(Spacer(1, 0.3 * inch))

    # Detailed expense table
    elements.append(Paragraph('Detailed Expenses', styles['Heading2']))
    elements.append(Spacer(1, 0.1 * inch))

    expense_data = [['Date', 'Description', 'Tags', 'Amount']]
    for expense in expenses[:100]:  # Limit to 100 for PDF
        tags = ', '.join([tag.name for tag in expense.tags.all()])
        expense_data.append([
            expense.date.strftime('%Y-%m-%d'),
            expense.description[:40],
            tags[:30],
            f"${expense.amount:,.2f}"
        ])

    expense_table = Table(expense_data, colWidths=[1 * inch, 2.5 * inch, 1.5 * inch, 1 * inch])
    expense_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#3498db')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 10),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('FONTSIZE', (0, 1), (-1, -1), 9),
    ]))
    elements.append(expense_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def export_to_excel(expenses, summary, filters):
    """Export expenses to Excel with charts"""
    wb = openpyxl.Workbook()

    # Summary sheet
    ws_summary = wb.active
    ws_summary.title = "Summary"

    # Headers
    ws_summary['A1'] = 'Expense Report Summary'
    ws_summary['A1'].font = Font(size=16, bold=True)
    ws_summary.merge_cells('A1:B1')

    ws_summary['A3'] = 'Total Expenses:'
    ws_summary['B3'] = float(summary['total'])
    ws_summary['A4'] = 'Number of Expenses:'
    ws_summary['B4'] = summary['count']
    ws_summary['A5'] = 'Average Expense:'
    ws_summary['B5'] = float(summary['average'])

    # Format currency
    ws_summary['B3'].number_format = '$#,##0.00'
    ws_summary['B5'].number_format = '$#,##0.00'

    # Tag breakdown
    ws_summary['A7'] = 'Expenses by Tag'
    ws_summary['A7'].font = Font(size=14, bold=True)

    row = 8
    ws_summary['A8'] = 'Tag'
    ws_summary['B8'] = 'Amount'
    ws_summary['A8'].font = Font(bold=True)
    ws_summary['B8'].font = Font(bold=True)

    for tag, amount in summary['by_tag'].items():
        row += 1
        ws_summary[f'A{row}'] = tag
        ws_summary[f'B{row}'] = float(amount)
        ws_summary[f'B{row}'].number_format = '$#,##0.00'

    # Add pie chart for tags
    if summary['by_tag']:
        pie = PieChart()
        labels = Reference(ws_summary, min_col=1, min_row=9, max_row=row)
        data = Reference(ws_summary, min_col=2, min_row=8, max_row=row)
        pie.add_data(data, titles_from_data=True)
        pie.set_categories(labels)
        pie.title = "Expenses by Tag"
        ws_summary.add_chart(pie, "D3")

    # Detailed expenses sheet
    ws_detail = wb.create_sheet("Detailed Expenses")
    headers = ['Date', 'Description', 'Tags', 'Amount', 'Notes']
    ws_detail.append(headers)

    # Style header row
    for cell in ws_detail[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill(start_color="3498db", end_color="3498db", fill_type="solid")
        cell.alignment = Alignment(horizontal="center")

    for expense in expenses:
        tags = ', '.join([tag.name for tag in expense.tags.all()])
        ws_detail.append([
            expense.date,
            expense.description,
            tags,
            float(expense.amount),
            expense.notes
        ])

    # Format amounts
    for row in range(2, ws_detail.max_row + 1):
        ws_detail[f'D{row}'].number_format = '$#,##0.00'

    # Adjust column widths
    ws_detail.column_dimensions['A'].width = 12
    ws_detail.column_dimensions['B'].width = 30
    ws_detail.column_dimensions['C'].width = 20
    ws_detail.column_dimensions['D'].width = 12
    ws_detail.column_dimensions['E'].width = 30

    # Time series chart
    chart_data = generate_chart_data(expenses, group_by='month')
    if chart_data:
        ws_chart = wb.create_sheet("Trend Analysis")
        ws_chart['A1'] = 'Period'
        ws_chart['B1'] = 'Total Amount'

        for idx, item in enumerate(chart_data, start=2):
            ws_chart[f'A{idx}'] = item['period'].strftime('%Y-%m-%d')
            ws_chart[f'B{idx}'] = float(item['total'])

        # Create bar chart
        bar_chart = BarChart()
        bar_chart.title = "Expenses Over Time"
        bar_chart.x_axis.title = "Period"
        bar_chart.y_axis.title = "Amount ($)"

        data = Reference(ws_chart, min_col=2, min_row=1, max_row=len(chart_data) + 1)
        cats = Reference(ws_chart, min_col=1, min_row=2, max_row=len(chart_data) + 1)
        bar_chart.add_data(data, titles_from_data=True)
        bar_chart.set_categories(cats)
        ws_chart.add_chart(bar_chart, "D2")

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer