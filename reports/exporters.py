import os
import csv
from io import BytesIO
from datetime import datetime

from django.conf import settings

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

import xlsxwriter

# Constants
MIME_CSV = 'text/csv'
MIME_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
MIME_PDF = 'application/pdf'


class BaseReportExporter:
    """
    Base class for all report exporters. Handles file naming and directory logic.
    """
    def __init__(self, report, parameters):
        self.report = report
        self.parameters = parameters
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    def get_output_dir(self):
        """
        Returns the directory where the report file should be saved.
        """
        path = os.path.join(settings.MEDIA_ROOT, 'reports', str(self.report.company.company_id))
        os.makedirs(path, exist_ok=True)
        return path

    def get_filename(self, extension):
        """
        Generates a sanitized filename with timestamp.
        """
        base_name = ''.join(c if c.isalnum() else '_' for c in self.report.name)
        return f"{base_name}_{self.timestamp}.{extension}"

    def get_file_path(self, extension):
        """
        Full path where the file will be written.
        """
        return os.path.join(self.get_output_dir(), self.get_filename(extension))

    def get_headers(self):
        raise NotImplementedError("You must implement get_headers()")

    def get_rows(self):
        raise NotImplementedError("You must implement get_rows()")

    def generate(self):
        raise NotImplementedError("Subclasses must implement generate()")


class CSVReportExporter(BaseReportExporter):
    def generate(self):
        path = self.get_file_path("csv")
        with open(path, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(self.get_headers())
            for row in self.get_rows():
                writer.writerow(row)
        return path, 'CSV'


class ExcelReportExporter(BaseReportExporter):
    def generate(self):
        path = self.get_file_path("xlsx")
        workbook = xlsxwriter.Workbook(path)
        worksheet = workbook.add_worksheet()

        for col_num, header in enumerate(self.get_headers()):
            worksheet.write(0, col_num, header)

        for row_num, row in enumerate(self.get_rows(), 1):
            for col_num, value in enumerate(row):
                worksheet.write(row_num, col_num, value)

        workbook.close()
        return path, 'XLSX'


class PDFReportExporter(BaseReportExporter):
    def generate(self):
        path = self.get_file_path("pdf")
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = []

        # Title
        elements.append(Paragraph(self.report.name, styles['Title']))
        elements.append(Spacer(1, 12))

        # Table
        data = [self.get_headers()] + self.get_rows()
        table = Table(data)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))

        elements.append(table)
        doc.build(elements)

        with open(path, 'wb') as f:
            f.write(buffer.getvalue())
        buffer.close()
        return path, 'PDF'


# === Specialized Exporters === #

class ZReportExporter(ExcelReportExporter):
    def get_headers(self):
        return [
            'Date', 'Transaction ID', 'Product', 'Quantity',
            'Unit Price', 'Tax Amount', 'Total Amount', 'Payment Method'
        ]

    def get_rows(self):
        from sales.models import Sale
        store_id = self.parameters.get('store_id')
        start_date = self.parameters.get('start_date')
        end_date = self.parameters.get('end_date')

        sales = Sale.objects.filter(
            store_id=store_id,
            created_at__range=(start_date, end_date)
        ).prefetch_related('items__product')

        rows = []
        for sale in sales:
            for item in sale.items.all():
                rows.append([
                    sale.created_at.strftime('%Y-%m-%d %H:%M'),
                    str(sale.transaction_id),
                    item.product.name,
                    item.quantity,
                    item.unit_price,
                    item.tax_amount,
                    item.total_price,
                    sale.payment_method
                ])
        return rows


class TaxReportExporter(PDFReportExporter):
    def get_headers(self):
        return [
            'Period', 'Tax Type', 'Taxable Amount',
            'Tax Amount', 'Number of Transactions'
        ]

    def get_rows(self):
        # TODO: Replace with real tax aggregation logic
        return []


# === Exporter Resolver === #

def get_exporter_for_report(report, parameters):
    """
    Returns the appropriate exporter based on report type.
    """
    exporters = {
        'Z_REPORT': ZReportExporter,
        'TAX_REPORT': TaxReportExporter,
    }
    return exporters.get(report.report_type, CSVReportExporter)(report, parameters)
