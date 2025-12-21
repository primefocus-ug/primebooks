# reports/services/export_service.py
import io
import csv
import json
from datetime import datetime
from decimal import Decimal
import pandas as pd
from django.http import HttpResponse
from django.template.loader import render_to_string
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch


class ReportExportService:
    def __init__(self, report_data, filters):
        self.report_data = report_data
        self.filters = filters
        self.styles = getSampleStyleSheet()

    def _format_currency(self, value):
        """Format currency value"""
        if isinstance(value, (int, float, Decimal)):
            return f"UGX {value:,.2f}"
        return value

    def _format_date(self, date_str):
        """Format date string"""
        try:
            return datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')
        except:
            return date_str

    def export_to_pdf(self):
        """Export report to PDF"""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=landscape(letter),
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )

        elements = []

        # Title
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=self.styles['Title'],
            fontSize=24,
            spaceAfter=30,
            textColor=colors.HexColor('#1e3c72')
        )

        elements.append(Paragraph("Combined Business Report", title_style))

        # Date range
        date_range = ""
        if self.filters.get('start_date') and self.filters.get('end_date'):
            date_range = f"Period: {self._format_date(self.filters['start_date'])} to {self._format_date(self.filters['end_date'])}"
        elif self.filters.get('start_date'):
            date_range = f"From: {self._format_date(self.filters['start_date'])}"
        elif self.filters.get('end_date'):
            date_range = f"Up to: {self._format_date(self.filters['end_date'])}"

        if date_range:
            elements.append(Paragraph(date_range, self.styles['Normal']))

        elements.append(Spacer(1, 20))

        # Business Health Score
        if 'business_health' in self.report_data:
            health = self.report_data['business_health']
            elements.append(Paragraph(f"Business Health Score: {health['percentage']:.1f}% ({health['grade']})",
                                      self.styles['Heading2']))

        # Summary Data
        summary_data = []

        if 'SALES_SUMMARY' in self.report_data:
            sales = self.report_data['SALES_SUMMARY'].get('summary', {})
            summary_data.append(['Total Sales', self._format_currency(sales.get('total_sales', 0))])
            summary_data.append(['Total Transactions', sales.get('total_transactions', 0)])
            summary_data.append(['Average Transaction', self._format_currency(sales.get('avg_transaction', 0))])

        if 'PROFIT_LOSS' in self.report_data:
            profit = self.report_data['PROFIT_LOSS'].get('profit_loss', {}).get('profit', {})
            summary_data.append(['Net Profit', self._format_currency(profit.get('net_profit', 0))])
            summary_data.append(['Net Margin', f"{profit.get('net_margin', 0):.1f}%"])

        if 'EXPENSE_REPORT' in self.report_data:
            expenses = self.report_data['EXPENSE_REPORT'].get('summary', {})
            summary_data.append(['Total Expenses', self._format_currency(expenses.get('total_amount', 0))])

        if 'INVENTORY_STATUS' in self.report_data:
            inventory = self.report_data['INVENTORY_STATUS'].get('summary', {})
            summary_data.append(['Inventory Value', self._format_currency(inventory.get('total_stock_value', 0))])
            summary_data.append(['Low Stock Items', inventory.get('low_stock_count', 0)])

        if summary_data:
            summary_table = Table(summary_data, colWidths=[200, 150])
            summary_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e3c72')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 12),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8fafc')),
                ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#e5e7eb')),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ]))
            elements.append(summary_table)
            elements.append(Spacer(1, 30))

        # Build the PDF
        doc.build(elements)

        buffer.seek(0)
        response = HttpResponse(buffer, content_type='application/pdf')
        return response

    def export_to_excel(self):
        """Export report to Excel"""
        # Create Excel writer
        output = io.BytesIO()

        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Write summary sheet
            summary_data = []

            # Add filters
            summary_data.append(['Report Generated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])
            if self.filters.get('start_date'):
                summary_data.append(['Start Date', self.filters['start_date']])
            if self.filters.get('end_date'):
                summary_data.append(['End Date', self.filters['end_date']])

            # Business Health
            if 'business_health' in self.report_data:
                health = self.report_data['business_health']
                summary_data.append(['Business Health Score', f"{health['percentage']:.1f}%"])
                summary_data.append(['Business Grade', health['grade']])

            # Create summary DataFrame
            summary_df = pd.DataFrame(summary_data, columns=['Metric', 'Value'])
            summary_df.to_excel(writer, sheet_name='Summary', index=False)

            # Sales Summary
            if 'SALES_SUMMARY' in self.report_data:
                sales_data = []
                summary = self.report_data['SALES_SUMMARY'].get('summary', {})
                sales_data.append(['Total Sales', summary.get('total_sales', 0)])
                sales_data.append(['Total Transactions', summary.get('total_transactions', 0)])
                sales_data.append(['Average Transaction', summary.get('avg_transaction', 0)])
                sales_data.append(['Total Tax', summary.get('total_tax', 0)])
                sales_data.append(['Total Discount', summary.get('total_discount', 0)])

                sales_df = pd.DataFrame(sales_data, columns=['Metric', 'Value'])
                sales_df.to_excel(writer, sheet_name='Sales Summary', index=False)

            # Product Performance
            if 'PRODUCT_PERFORMANCE' in self.report_data:
                products = self.report_data['PRODUCT_PERFORMANCE'].get('products', [])
                if products:
                    products_df = pd.DataFrame(products)
                    products_df.to_excel(writer, sheet_name='Product Performance', index=False)

            # Expense Report
            if 'EXPENSE_REPORT' in self.report_data:
                expenses = self.report_data['EXPENSE_REPORT'].get('expenses', [])
                if expenses:
                    expenses_df = pd.DataFrame(expenses)
                    expenses_df.to_excel(writer, sheet_name='Expenses', index=False)

            # Inventory Status
            if 'INVENTORY_STATUS' in self.report_data:
                inventory = self.report_data['INVENTORY_STATUS'].get('inventory', [])
                if inventory:
                    inventory_df = pd.DataFrame(inventory)
                    inventory_df.to_excel(writer, sheet_name='Inventory', index=False)

        output.seek(0)
        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        return response

    def export_to_csv(self):
        """Export report to CSV"""
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        # Write header
        writer.writerow(['Combined Business Report'])
        writer.writerow(['Generated', datetime.now().strftime('%Y-%m-%d %H:%M:%S')])

        if self.filters.get('start_date'):
            writer.writerow(['Start Date', self.filters['start_date']])
        if self.filters.get('end_date'):
            writer.writerow(['End Date', self.filters['end_date']])

        writer.writerow([])  # Empty row

        # Write Business Health
        if 'business_health' in self.report_data:
            health = self.report_data['business_health']
            writer.writerow(['BUSINESS HEALTH'])
            writer.writerow(['Score', f"{health['percentage']:.1f}%"])
            writer.writerow(['Grade', health['grade']])
            writer.writerow(['Points', f"{health['score']}/{health['max_score']}"])
            writer.writerow([])

        # Write Sales Summary
        if 'SALES_SUMMARY' in self.report_data:
            sales = self.report_data['SALES_SUMMARY'].get('summary', {})
            writer.writerow(['SALES SUMMARY'])
            writer.writerow(['Total Sales', self._format_currency(sales.get('total_sales', 0))])
            writer.writerow(['Total Transactions', sales.get('total_transactions', 0)])
            writer.writerow(['Average Transaction', self._format_currency(sales.get('avg_transaction', 0))])
            writer.writerow([])

        response = HttpResponse(buffer.getvalue(), content_type='text/csv')
        return response