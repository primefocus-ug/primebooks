"""
Professional PDF Export Service with Dynamic Styling
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, Image, Frame, PageTemplate, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT
from reportlab.pdfgen import canvas
from django.conf import settings
from django.utils import timezone
from io import BytesIO
import os
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class ColorScheme:
    """Dynamic color schemes based on report data"""

    # Default brand colors
    PRIMARY = colors.HexColor('#2563eb')  # Blue
    SECONDARY = colors.HexColor('#0ea5e9')  # Light Blue
    SUCCESS = colors.HexColor('#10b981')  # Green
    WARNING = colors.HexColor('#f59e0b')  # Orange
    DANGER = colors.HexColor('#ef4444')  # Red
    NEUTRAL = colors.HexColor('#6b7280')  # Gray

    # Background colors
    BG_LIGHT = colors.HexColor('#f9fafb')
    BG_HEADER = colors.HexColor('#1e40af')
    BG_TABLE_HEADER = colors.HexColor('#3b82f6')

    # Text colors
    TEXT_DARK = colors.HexColor('#111827')
    TEXT_LIGHT = colors.HexColor('#ffffff')

    @staticmethod
    def get_status_color(value, metric_type='amount'):
        """Get color based on value/status"""
        if metric_type == 'amount':
            if value > 0:
                return ColorScheme.SUCCESS
            elif value < 0:
                return ColorScheme.DANGER
            return ColorScheme.NEUTRAL
        elif metric_type == 'percentage':
            if value >= 75:
                return ColorScheme.SUCCESS
            elif value >= 50:
                return ColorScheme.WARNING
            return ColorScheme.DANGER
        elif metric_type == 'stock':
            if value == 0:
                return ColorScheme.DANGER
            elif value < 10:
                return ColorScheme.WARNING
            return ColorScheme.SUCCESS
        return ColorScheme.NEUTRAL


class NumberedCanvas(canvas.Canvas):
    """Custom canvas with headers, footers, and page numbers"""

    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []
        self.company_info = {}
        self.report_title = ""
        self.watermark_text = ""

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        """Add page headers and footers to all pages"""
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_elements(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_elements(self, page_count):
        """Draw header, footer, page numbers, and watermark"""
        page_num = len(self._saved_page_states)

        # Draw watermark if specified
        if self.watermark_text:
            self.saveState()
            self.setFont('Helvetica', 60)
            self.setFillColorRGB(0.9, 0.9, 0.9, alpha=0.3)
            self.translate(self._pagesize[0] / 2, self._pagesize[1] / 2)
            self.rotate(45)
            self.drawCentredString(0, 0, self.watermark_text)
            self.restoreState()

        # Draw header
        self.saveState()
        # Header background
        self.setFillColor(ColorScheme.BG_HEADER)
        self.rect(0, self._pagesize[1] - 80, self._pagesize[0], 80, fill=1, stroke=0)

        # Company logo (if exists)
        if self.company_info.get('logo_path'):
            try:
                logo_path = self.company_info['logo_path']
                if os.path.exists(logo_path):
                    self.drawImage(logo_path, 40, self._pagesize[1] - 70,
                                   width=50, height=50, preserveAspectRatio=True,
                                   mask='auto')
            except Exception as e:
                logger.error(f"Error drawing logo: {e}")

        # Company name and report title
        self.setFillColor(ColorScheme.TEXT_LIGHT)
        self.setFont('Helvetica-Bold', 16)
        self.drawString(100, self._pagesize[1] - 35,
                        self.company_info.get('name', 'Company Name'))

        self.setFont('Helvetica', 12)
        self.drawString(100, self._pagesize[1] - 55, self.report_title)

        # Date on right side
        self.setFont('Helvetica', 10)
        date_str = timezone.now().strftime('%B %d, %Y %I:%M %p')
        text_width = self.stringWidth(date_str, 'Helvetica', 10)
        self.drawString(self._pagesize[0] - text_width - 40,
                        self._pagesize[1] - 45, date_str)

        self.restoreState()

        # Draw footer
        self.saveState()
        # Footer line
        self.setStrokeColor(ColorScheme.PRIMARY)
        self.setLineWidth(2)
        self.line(40, 50, self._pagesize[0] - 40, 50)

        # Footer text
        self.setFillColor(ColorScheme.NEUTRAL)
        self.setFont('Helvetica', 9)

        # Left side - Company info
        footer_left = f"{self.company_info.get('address', '')} | {self.company_info.get('phone', '')} | {self.company_info.get('email', '')}"
        self.drawString(40, 35, footer_left[:80])  # Truncate if too long

        # Center - EFRIS info if applicable
        if self.company_info.get('efris_device'):
            efris_text = f"EFRIS Device: {self.company_info['efris_device']} | TIN: {self.company_info.get('tin', '')}"
            text_width = self.stringWidth(efris_text, 'Helvetica', 9)
            self.drawString((self._pagesize[0] - text_width) / 2, 35, efris_text)

        # Right side - Page numbers
        self.setFont('Helvetica', 9)
        page_text = f"Page {page_num} of {page_count}"
        text_width = self.stringWidth(page_text, 'Helvetica', 9)
        self.drawString(self._pagesize[0] - text_width - 40, 35, page_text)

        # Confidential/Internal Use text
        if self.company_info.get('confidential'):
            self.setFont('Helvetica-Oblique', 8)
            self.setFillColor(ColorScheme.DANGER)
            conf_text = "CONFIDENTIAL - INTERNAL USE ONLY PRIME BOOKS"
            text_width = self.stringWidth(conf_text, 'Helvetica-Oblique', 8)
            self.drawString((self._pagesize[0] - text_width) / 2, 20, conf_text)

        self.restoreState()


class PDFExportService:
    """Professional PDF export service with dynamic styling"""

    def __init__(self, report_data: Dict[str, Any], report_name: str,
                 company_info: Dict[str, Any], orientation='auto'):
        self.report_data = report_data
        self.report_name = report_name
        self.company_info = company_info
        self.orientation = orientation
        self.styles = getSampleStyleSheet()
        self._setup_custom_styles()

    def _setup_custom_styles(self):
        """Setup custom paragraph styles"""
        # Title style
        self.styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=ColorScheme.PRIMARY,
            spaceAfter=30,
            alignment=TA_CENTER,
            fontName='Helvetica-Bold'
        ))

        # Section header style
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=16,
            textColor=ColorScheme.BG_HEADER,
            spaceAfter=12,
            spaceBefore=12,
            fontName='Helvetica-Bold',
            borderWidth=0,
            borderColor=ColorScheme.PRIMARY,
            borderPadding=5,
        ))

        # Subsection style
        self.styles.add(ParagraphStyle(
            name='SubSection',
            parent=self.styles['Heading3'],
            fontSize=14,
            textColor=ColorScheme.TEXT_DARK,
            spaceAfter=8,
            fontName='Helvetica-Bold'
        ))

        # Summary box style
        self.styles.add(ParagraphStyle(
            name='SummaryText',
            parent=self.styles['Normal'],
            fontSize=12,
            textColor=ColorScheme.TEXT_DARK,
            alignment=TA_CENTER,
            spaceAfter=6,
        ))

        # Highlight style
        self.styles.add(ParagraphStyle(
            name='Highlight',
            parent=self.styles['Normal'],
            fontSize=11,
            textColor=ColorScheme.PRIMARY,
            fontName='Helvetica-Bold'
        ))

    def _determine_orientation(self, data: Dict) -> Any:
        """Auto-determine page orientation based on data"""
        if self.orientation == 'landscape':
            return landscape(A4)
        elif self.orientation == 'portrait':
            return A4
        else:  # auto
            # Use landscape if we have many columns
            if 'grouped_data' in data and data['grouped_data']:
                first_row = data['grouped_data'][0]
                if len(first_row.keys()) > 5:
                    return landscape(A4)
            return A4

    def generate_pdf(self) -> BytesIO:
        """Generate PDF document"""
        buffer = BytesIO()
        pagesize = self._determine_orientation(self.report_data)

        # Create document with custom canvas
        doc = SimpleDocTemplate(
            buffer,
            pagesize=pagesize,
            rightMargin=40,
            leftMargin=40,
            topMargin=100,
            bottomMargin=80,
        )
        self.doc_width = doc.width

        # Build content
        story = []

        # 🟢 HANDLE COMBINED BUSINESS REPORT
        if self._is_combined_report():
            story.extend(self._build_combined_report())

        # 🟢 HANDLE PROFIT & LOSS REPORT
        elif 'profit_loss' in self.report_data:
            story.extend(self._build_profit_loss_report())

        # 🟢 HANDLE CASHIER PERFORMANCE
        elif 'performance' in self.report_data:
            story.extend(self._build_cashier_performance_report())

        # 🟢 HANDLE EXPENSE REPORTS
        elif 'expenses' in self.report_data:
            story.extend(self._build_expense_report())

        # 🟢 HANDLE STOCK MOVEMENT REPORT
        elif 'movements' in self.report_data:
            story.extend(self._build_stock_movement_report())

        # 🟢 HANDLE CUSTOMER ANALYTICS
        elif 'customers' in self.report_data:
            story.extend(self._build_customer_analytics_report())

        # Original handlers for other reports
        else:
            # Add summary section
            if 'summary' in self.report_data:
                story.extend(self._build_summary_section(self.report_data['summary']))
                story.append(Spacer(1, 20))

            # Add main data table
            if 'grouped_data' in self.report_data:
                story.append(Paragraph("Detailed Report", self.styles['SectionHeader']))
                story.extend(self._build_data_table(self.report_data['grouped_data']))
                story.append(Spacer(1, 20))

            # Add products section
            if 'products' in self.report_data:
                story.append(Paragraph("Product Performance", self.styles['SectionHeader']))
                story.extend(self._build_product_table(self.report_data['products']))
                story.append(Spacer(1, 20))

            # Add inventory section
            if 'inventory' in self.report_data:
                story.append(Paragraph("Inventory Status", self.styles['SectionHeader']))
                story.extend(self._build_inventory_table(self.report_data['inventory']))
                story.append(Spacer(1, 20))

            # Add tax breakdown
            if 'tax_breakdown' in self.report_data:
                story.append(Paragraph("Tax Breakdown", self.styles['SectionHeader']))
                story.extend(self._build_tax_table(self.report_data['tax_breakdown']))
                story.append(Spacer(1, 20))

            # Add EFRIS compliance
            if 'efris_stats' in self.report_data:
                story.extend(self._build_efris_section(self.report_data['efris_stats']))
                story.append(Spacer(1, 20))

            # Add compliance section
            if 'compliance' in self.report_data:
                story.extend(self._build_compliance_section(self.report_data['compliance']))
                story.append(Spacer(1, 20))

            # Add alerts if any
            if 'alerts' in self.report_data and self.report_data['alerts']:
                story.append(PageBreak())
                story.append(Paragraph("Stock Alerts", self.styles['SectionHeader']))
                story.extend(self._build_alerts_table(self.report_data['alerts']))

        # Build PDF with custom canvas
        if not story:
            # If story is empty, add a placeholder
            story.append(Paragraph("No data available for this report.", self.styles['Normal']))

        doc.build(story, canvasmaker=lambda *args, **kwargs: self._create_canvas(*args, **kwargs))

        buffer.seek(0)
        return buffer

    def _create_canvas(self, *args, **kwargs):
        """Create custom canvas with company info"""
        canvas_obj = NumberedCanvas(*args, **kwargs)
        canvas_obj.company_info = self.company_info
        canvas_obj.report_title = self.report_name
        canvas_obj.watermark_text = self.company_info.get('watermark', '')
        return canvas_obj

    from reportlab.platypus import Paragraph

    def _build_summary_section(self, summary) -> List:
        """Build summary cards section (supports dict or list of dicts)"""
        elements = []
        elements.append(Paragraph("Executive Summary", self.styles['SectionHeader']))

        # Normalize: if summary is a list of dicts, merge them into one dict
        if isinstance(summary, list):
            merged_summary = {}
            for item in summary:
                if isinstance(item, dict):
                    merged_summary.update(item)
            summary = merged_summary
        elif not isinstance(summary, dict):
            # fallback: wrap non-dict as a single dict
            summary = {'Summary': str(summary)}

        summary_data = []
        row = []
        count = 0

        for key, value in summary.items():
            display_key = key.replace('_', ' ').title()

            if isinstance(value, (int, float)):
                if 'amount' in key.lower() or 'sales' in key.lower() or 'revenue' in key.lower():
                    formatted_value = f"UGX {value:,.2f}"
                    color = ColorScheme.get_status_color(value, 'amount')
                elif 'percentage' in key.lower() or 'rate' in key.lower():
                    formatted_value = f"{value:.2f}%"
                    color = ColorScheme.get_status_color(value, 'percentage')
                else:
                    formatted_value = f"{value:,}"
                    color = ColorScheme.PRIMARY
            else:
                formatted_value = str(value)
                color = ColorScheme.TEXT_DARK

            # Create each cell as Flowables
            cell_data = [
                Paragraph(f"<b>{display_key}</b>", self.styles['Normal']),
                Paragraph(f"<font color='{color}'><b>{formatted_value}</b></font>", self.styles['SummaryText'])
            ]
            row.append(cell_data)
            count += 1

            if count % 3 == 0:
                summary_data.append(row)
                row = []

        # Fill remaining cells
        if row:
            empty_cell = [
                Paragraph("", self.styles['Normal']),
                Paragraph("", self.styles['SummaryText'])
            ]
            while len(row) < 3:
                row.append(empty_cell)
            summary_data.append(row)

        # Create table
        if summary_data:
            col_width = getattr(self, 'doc_width', 500) / 3
            table = Table(summary_data, colWidths=[col_width] * 3)
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), ColorScheme.BG_LIGHT),
                ('GRID', (0, 0), (-1, -1), 1, ColorScheme.SECONDARY),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('TOPPADDING', (0, 0), (-1, -1), 12),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
            ]))
            elements.append(table)

        return elements

    def _build_data_table(self, data: List[Dict]) -> List:
        """Build main data table"""
        elements = []

        if not data:
            elements.append(Paragraph("<i>No data available</i>", self.styles['Normal']))
            return elements

        # Get column headers
        headers = list(data[0].keys())

        # Create table data
        table_data = [[Paragraph(f"<b>{h.replace('_', ' ').title()}</b>",
                                 self.styles['Normal']) for h in headers]]

        # Add rows
        for row in data[:100]:  # Limit to 100 rows per page
            table_row = []
            for header in headers:
                value = row.get(header, '')

                # Format value
                if isinstance(value, float):
                    if 'amount' in header.lower() or 'price' in header.lower():
                        formatted = f"UGX {value:,.2f}"
                    elif 'percentage' in header.lower() or 'rate' in header.lower():
                        formatted = f"{value:.2f}%"
                    else:
                        formatted = f"{value:.2f}"
                elif isinstance(value, int):
                    formatted = f"{value:,}"
                else:
                    formatted = str(value) if value else '-'

                table_row.append(Paragraph(formatted, self.styles['Normal']))
            table_data.append(table_row)

        # Create table with dynamic column widths
        num_cols = len(headers)
        col_width = 500 / num_cols if num_cols > 0 else 100

        table = Table(table_data, colWidths=[col_width] * num_cols, repeatRows=1)

        # Apply styling
        style_commands = [
            ('BACKGROUND', (0, 0), (-1, 0), ColorScheme.BG_TABLE_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), ColorScheme.TEXT_LIGHT),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('TOPPADDING', (0, 0), (-1, 0), 12),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]

        # Alternate row colors
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                style_commands.append(('BACKGROUND', (0, i), (-1, i), ColorScheme.BG_LIGHT))

        table.setStyle(TableStyle(style_commands))
        elements.append(table)

        # Add note if data was truncated
        if len(data) > 100:
            elements.append(Spacer(1, 10))
            elements.append(Paragraph(
                f"<i>Showing first 100 of {len(data)} records. Download full report for complete data.</i>",
                self.styles['Normal']
            ))

        return elements

    def _build_product_table(self, products: List[Dict]) -> List:
        """Build product performance table"""
        elements = []

        if not products:
            elements.append(Paragraph("<i>No product data available</i>", self.styles['Normal']))
            return elements

        # Table headers
        headers = ['Product', 'SKU', 'Quantity', 'Revenue', 'Profit', 'Margin']
        table_data = [[Paragraph(f"<b>{h}</b>", self.styles['Normal']) for h in headers]]

        # Add product rows
        for product in products[:50]:
            product_name = product.get('product__name') or ''
            sku = product.get('product__sku') or ''
            quantity = product.get('total_quantity') or 0
            revenue = product.get('total_revenue') or 0
            profit = product.get('total_profit') or 0
            profit_margin = product.get('profit_margin') or 0

            margin_color = ColorScheme.get_status_color(profit_margin, 'percentage')

            row = [
                Paragraph(product_name[:30], self.styles['Normal']),
                Paragraph(sku, self.styles['Normal']),
                Paragraph(f"{quantity:,}", self.styles['Normal']),
                Paragraph(f"UGX {revenue:,.2f}", self.styles['Normal']),
                Paragraph(f"UGX {profit:,.2f}", self.styles['Normal']),
                Paragraph(
                    f"<font color='{margin_color}'><b>{profit_margin:.1f}%</b></font>",
                    self.styles['Normal']
                ),
            ]

            table_data.append(row)

        # Create table
        table = Table(table_data,
                      colWidths=[120, 60, 60, 90, 90, 60],
                      repeatRows=1)

        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ColorScheme.BG_TABLE_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), ColorScheme.TEXT_LIGHT),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))

        # Alternate row colors
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, i), (-1, i), ColorScheme.BG_LIGHT)
                ]))

        elements.append(table)
        return elements

    def _build_inventory_table(self, inventory: List[Dict]) -> List:
        """Build inventory status table"""
        elements = []

        if not inventory:
            elements.append(Paragraph("<i>No inventory data available</i>", self.styles['Normal']))
            return elements

        # Table headers
        headers = ['Product', 'Store', 'Quantity', 'Status', 'Value']
        table_data = [[Paragraph(f"<b>{h}</b>", self.styles['Normal']) for h in headers]]

        # Add inventory rows
        for item in inventory[:50]:
            status = item.get('status', 'in_stock')
            quantity = item.get('quantity', 0)

            # Color code based on status
            if status == 'out_of_stock':
                status_color = ColorScheme.DANGER
                status_text = 'OUT OF STOCK'
            elif status == 'low_stock':
                status_color = ColorScheme.WARNING
                status_text = 'LOW STOCK'
            else:
                status_color = ColorScheme.SUCCESS
                status_text = 'IN STOCK'

            row = [
                Paragraph(item.get('product__name', '')[:25], self.styles['Normal']),
                Paragraph(item.get('store__name', '')[:20], self.styles['Normal']),
                Paragraph(f"{quantity:,}", self.styles['Normal']),
                Paragraph(f"<font color='{status_color}'><b>{status_text}</b></font>",
                          self.styles['Normal']),
                Paragraph(f"UGX {item.get('stock_value', 0):,.2f}", self.styles['Normal']),
            ]
            table_data.append(row)

        # Create table
        table = Table(table_data,
                      colWidths=[120, 100, 60, 90, 90],
                      repeatRows=1)

        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ColorScheme.BG_TABLE_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), ColorScheme.TEXT_LIGHT),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (2, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        elements.append(table)
        return elements

    def _build_tax_table(self, tax_data: List[Dict]) -> List:
        """Build tax breakdown table"""
        elements = []

        headers = ['Tax Rate', 'Category', 'Total Sales', 'Tax Collected', 'Transactions']
        table_data = [[Paragraph(f"<b>{h}</b>", self.styles['Normal']) for h in headers]]

        for tax in tax_data:
            row = [
                Paragraph(tax.get('tax_rate', ''), self.styles['Normal']),
                Paragraph(tax.get('tax_rate_display', ''), self.styles['Normal']),
                Paragraph(f"UGX {tax.get('total_sales', 0):,.2f}", self.styles['Normal']),
                Paragraph(f"<font color='{ColorScheme.SUCCESS}'><b>UGX {tax.get('total_tax', 0):,.2f}</b></font>",
                          self.styles['Normal']),
                Paragraph(f"{tax.get('transaction_count', 0):,}", self.styles['Normal']),
            ]
            table_data.append(row)

        table = Table(table_data, colWidths=[60, 120, 100, 100, 80], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ColorScheme.BG_TABLE_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), ColorScheme.TEXT_LIGHT),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        elements.append(table)
        return elements

    def _is_combined_report(self) -> bool:
        """Check if this is a combined business report"""
        combined_keys = ['SALES_SUMMARY', 'PROFIT_LOSS', 'EXPENSE_REPORT', 'INVENTORY_STATUS',
                         'EXPENSE_ANALYTICS', 'Z_REPORT', 'CASHIER_PERFORMANCE', 'STOCK_MOVEMENT',
                         'CUSTOMER_ANALYTICS', 'business_health', 'custom_analytics']
        return any(key in self.report_data for key in combined_keys)

    def _build_combined_report(self) -> List:
        """Build comprehensive combined business report with improved structure"""
        elements = []

        # Report Header
        elements.append(Paragraph("COMPREHENSIVE BUSINESS REPORT", self.styles['CustomTitle']))
        elements.append(Spacer(1, 15))

        # Report Metadata
        report_date = timezone.now().strftime("%B %d, %Y %I:%M %p")
        elements.append(Paragraph(f"Generated: {report_date}", self.styles['Normal']))

        if self.filters.get('start_date') and self.filters.get('end_date'):
            period = f"{self.filters['start_date']} to {self.filters['end_date']}"
        elif self.filters.get('start_date'):
            period = f"Since {self.filters['start_date']}"
        elif self.filters.get('end_date'):
            period = f"Up to {self.filters['end_date']}"
        else:
            period = "All Time"

        elements.append(Paragraph(f"Period: {period}", self.styles['Normal']))

        if self.filters.get('store'):
            elements.append(Paragraph(f"Store: {self.filters['store']}", self.styles['Normal']))
        else:
            elements.append(Paragraph("Store: All Stores", self.styles['Normal']))

        elements.append(Spacer(1, 25))

        # Table of Contents
        elements.append(Paragraph("TABLE OF CONTENTS", self.styles['SectionHeader']))
        toc_items = []

        if 'business_health' in self.report_data:
            toc_items.append("1. Business Health Score")
        if 'custom_analytics' in self.report_data:
            toc_items.append("2. Executive Summary & Key Metrics")
        if 'SALES_SUMMARY' in self.report_data:
            toc_items.append("3. Sales Performance Analysis")
        if 'PROFIT_LOSS' in self.report_data:
            toc_items.append("4. Financial Performance (P&L)")
        if 'EXPENSE_REPORT' in self.report_data:
            toc_items.append("5. Expense Analysis")
        if 'INVENTORY_STATUS' in self.report_data:
            toc_items.append("6. Inventory Management")
        if 'Z_REPORT' in self.report_data:
            toc_items.append("7. Daily Operations (Z-Report)")
        if 'CASHIER_PERFORMANCE' in self.report_data:
            toc_items.append("8. Staff Performance")
        if 'PRODUCT_PERFORMANCE' in self.report_data:
            toc_items.append("9. Product Performance")
        if 'STOCK_MOVEMENT' in self.report_data:
            toc_items.append("10. Stock Movement Analysis")
        if 'CUSTOMER_ANALYTICS' in self.report_data:
            toc_items.append("11. Customer Insights")
        if 'EFRIS_COMPLIANCE' in self.report_data:
            toc_items.append("12. EFRIS Compliance")

        for item in toc_items:
            elements.append(Paragraph(item, self.styles['TOCItem']))

        elements.append(Spacer(1, 30))
        elements.append(HRFlowable(width="100%", thickness=1, color=colors.black))
        elements.append(Spacer(1, 20))

        # 1. Business Health Score (If Available)
        if 'business_health' in self.report_data:
            elements.append(Paragraph("1. BUSINESS HEALTH SCORE", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            elements.extend(self._build_business_health_section())
            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 2. Executive Summary & Custom Analytics
        if 'custom_analytics' in self.report_data:
            elements.append(Paragraph("2. EXECUTIVE SUMMARY", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            elements.extend(self._build_custom_analytics_section())
            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 3. Sales Performance Analysis
        if 'SALES_SUMMARY' in self.report_data:
            elements.append(Paragraph("3. SALES PERFORMANCE ANALYSIS", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            sales_data = self.report_data['SALES_SUMMARY']

            if 'summary' in sales_data:
                # Enhanced sales summary
                summary_table_data = [
                    ['Metric', 'Value', 'Details']
                ]

                summary = sales_data['summary']
                summary_table_data.append([
                    'Total Sales',
                    f"UGX {float(summary.get('total_sales', 0)):,.0f}",
                    f"{summary.get('total_transactions', 0)} transactions"
                ])
                summary_table_data.append([
                    'Average Transaction',
                    f"UGX {float(summary.get('avg_transaction', 0)):,.0f}",
                    f"Per transaction"
                ])
                summary_table_data.append([
                    'Tax Collected',
                    f"UGX {float(summary.get('total_tax', 0)):,.0f}",
                    f"EFRIS compliance"
                ])
                summary_table_data.append([
                    'Total Discounts',
                    f"UGX {float(summary.get('total_discount', 0)):,.0f}",
                    f"Given to customers"
                ])

                sales_table = Table(summary_table_data, colWidths=[150, 120, 150])
                sales_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4A6572')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                    ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, 0), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F7FA')),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ]))
                elements.append(sales_table)
                elements.append(Spacer(1, 15))

            # Payment Method Breakdown
            if 'payment_methods' in sales_data and sales_data['payment_methods']:
                elements.append(Paragraph("Payment Method Distribution", self.styles['SubSection']))
                payment_data = []
                for payment in sales_data['payment_methods'][:6]:  # Top 6 methods
                    percentage = (float(payment.get('amount', 0)) / float(
                        sales_data['summary'].get('total_sales', 1)) * 100) if sales_data['summary'].get('total_sales',
                                                                                                         0) > 0 else 0
                    payment_data.append([
                        payment.get('payment_method', 'Unknown'),
                        f"UGX {float(payment.get('amount', 0)):,.0f}",
                        f"{payment.get('count', 0)} transactions",
                        f"{percentage:.1f}%"
                    ])

                if payment_data:
                    payment_table = Table([['Method', 'Amount', 'Transactions', '%']] + payment_data)
                    payment_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495E')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ]))
                    elements.append(payment_table)
                    elements.append(Spacer(1, 15))

            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 4. Financial Performance (Profit & Loss)
        if 'PROFIT_LOSS' in self.report_data:
            elements.append(Paragraph("4. FINANCIAL PERFORMANCE (PROFIT & LOSS)", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            elements.extend(self._build_profit_loss_section(self.report_data['PROFIT_LOSS']))
            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 5. Expense Analysis
        if 'EXPENSE_REPORT' in self.report_data:
            elements.append(Paragraph("5. EXPENSE ANALYSIS", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            expense_data = self.report_data['EXPENSE_REPORT']

            if 'summary' in expense_data:
                # Expense Summary
                summary = expense_data['summary']
                expense_summary_data = [
                    ['Total Expenses', f"UGX {float(summary.get('total_amount', 0)):,.0f}"],
                    ['Number of Expenses', str(summary.get('total_expenses', 0))],
                    ['Average Expense', f"UGX {float(summary.get('avg_expense', 0)):,.0f}"],
                    ['Tax Paid', f"UGX {float(summary.get('total_tax', 0)):,.0f}"],
                    ['Pending Approval', str(summary.get('pending_expenses', 0))],
                    ['Overdue Payments', str(summary.get('overdue_expenses', 0))],
                ]

                expense_table = Table(expense_summary_data, colWidths=[200, 150])
                expense_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#F8F9FA')),
                    ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#E9ECEF')),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('PADDING', (0, 0), (-1, -1), 8),
                ]))
                elements.append(expense_table)
                elements.append(Spacer(1, 15))

            # Expense by Category
            if 'category_breakdown' in expense_data and expense_data['category_breakdown']:
                elements.append(Paragraph("Expense Breakdown by Category", self.styles['SubSection']))
                elements.append(Spacer(1, 8))
                elements.extend(self._build_expense_category_table(expense_data['category_breakdown']))

            # Expense Status Distribution
            if 'status_counts' in expense_data and expense_data['status_counts']:
                elements.append(Spacer(1, 12))
                elements.append(Paragraph("Expense Status Distribution", self.styles['SubSection']))
                status_data = []
                for status in expense_data['status_counts']:
                    status_data.append([
                        status.get('status', 'Unknown'),
                        str(status.get('count', 0)),
                        f"UGX {float(status.get('total_amount', 0)):,.0f}"
                    ])

                if status_data:
                    status_table = Table([['Status', 'Count', 'Amount']] + status_data)
                    status_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#495057')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
                    ]))
                    elements.append(status_table)

            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 6. Inventory Management
        if 'INVENTORY_STATUS' in self.report_data:
            elements.append(Paragraph("6. INVENTORY MANAGEMENT", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            inventory_data = self.report_data['INVENTORY_STATUS']

            if 'summary' in inventory_data:
                summary = inventory_data['summary']

                # Create inventory summary table
                inventory_summary = [
                    ['Total Products', str(summary.get('total_products', 0))],
                    ['Total Quantity', f"{summary.get('total_quantity', 0):,.0f} units"],
                    ['Stock Value', f"UGX {float(summary.get('total_stock_value', 0)):,.0f}"],
                    ['Retail Value', f"UGX {float(summary.get('total_retail_value', 0)):,.0f}"],
                    ['Low Stock Items', str(summary.get('low_stock_count', 0))],
                    ['Out of Stock Items', str(summary.get('out_of_stock_count', 0))],
                ]

                inventory_table = Table(inventory_summary, colWidths=[180, 170])
                inventory_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#E3F2FD')),
                    ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#F3F4F6')),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('PADDING', (0, 0), (-1, -1), 8),
                ]))
                elements.append(inventory_table)

            # Show alerts if available
            if 'alerts' in inventory_data and inventory_data['alerts']:
                elements.append(Spacer(1, 15))
                elements.append(Paragraph("Stock Alerts", self.styles['SubSection']))

                alert_data = []
                for i, alert in enumerate(inventory_data['alerts'][:10]):  # Top 10 alerts
                    alert_data.append([
                        str(i + 1),
                        alert.get('product__name', 'Unknown')[:30],
                        alert.get('store__name', 'Unknown'),
                        str(alert.get('quantity', 0)),
                        str(alert.get('low_stock_threshold', 0))
                    ])

                if alert_data:
                    alerts_table = Table([['#', 'Product', 'Store', 'Current Qty', 'Reorder Level']] + alert_data)
                    alerts_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DC3545')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                        ('TEXTCOLOR', (3, 1), (3, -1), colors.red),
                    ]))
                    elements.append(alerts_table)

            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 7. Daily Operations (Z-Report)
        if 'Z_REPORT' in self.report_data:
            elements.append(Paragraph("7. DAILY OPERATIONS (Z-REPORT)", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            z_data = self.report_data['Z_REPORT']

            if 'summary' in z_data:
                summary = z_data['summary']

                z_report_summary = [
                    ['Total Sales', f"UGX {float(summary.get('total_sales', 0)):,.0f}"],
                    ['Total Transactions', str(summary.get('total_transactions', 0))],
                    ['Average Transaction', f"UGX {float(summary.get('avg_transaction', 0)):,.0f}"],
                    ['Total Tax', f"UGX {float(summary.get('total_tax', 0)):,.0f}"],
                    ['Total Discounts', f"UGX {float(summary.get('total_discount', 0)):,.0f}"],
                ]

                z_table = Table(z_report_summary, colWidths=[180, 170])
                z_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#17A2B8')),
                    ('TEXTCOLOR', (0, 0), (0, -1), colors.white),
                    ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#E3F2FD')),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('PADDING', (0, 0), (-1, -1), 8),
                ]))
                elements.append(z_table)

            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 8. Staff Performance
        if 'CASHIER_PERFORMANCE' in self.report_data:
            elements.append(Paragraph("8. STAFF PERFORMANCE", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            cashier_data = self.report_data['CASHIER_PERFORMANCE']

            if 'summary' in cashier_data:
                summary = cashier_data['summary']

                performance_summary = [
                    ['Total Cashiers', str(summary.get('total_cashiers', 0))],
                    ['Total Sales', f"UGX {float(summary.get('total_sales', 0)):,.0f}"],
                    ['Total Transactions', str(summary.get('total_transactions', 0))],
                    ['Average per Cashier', f"UGX {float(summary.get('avg_per_cashier', 0)):,.0f}"],
                ]

                perf_table = Table(performance_summary, colWidths=[180, 170])
                perf_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#28A745')),
                    ('TEXTCOLOR', (0, 0), (0, -1), colors.white),
                    ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#D4EDDA')),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('PADDING', (0, 0), (-1, -1), 8),
                ]))
                elements.append(perf_table)

            # Top Performers
            if 'performance' in cashier_data and cashier_data['performance']:
                elements.append(Spacer(1, 15))
                elements.append(Paragraph("Top Performing Cashiers", self.styles['SubSection']))

                top_performers = []
                for i, cashier in enumerate(cashier_data['performance'][:5]):  # Top 5
                    cashier_name = f"{cashier.get('created_by__first_name', '')} {cashier.get('created_by__last_name', '')}".strip() or 'Unknown'
                    top_performers.append([
                        str(i + 1),
                        cashier_name,
                        f"UGX {float(cashier.get('total_sales', 0)):,.0f}",
                        str(cashier.get('transaction_count', 0)),
                        f"UGX {float(cashier.get('avg_transaction', 0)):,.0f}"
                    ])

                if top_performers:
                    cashier_table = Table(
                        [['Rank', 'Cashier', 'Total Sales', 'Transactions', 'Avg Sale']] + top_performers)
                    cashier_table.setStyle(TableStyle([
                        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#343A40')),
                        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
                    ]))
                    elements.append(cashier_table)

            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 9. Product Performance (if available)
        if 'PRODUCT_PERFORMANCE' in self.report_data:
            elements.append(Paragraph("9. PRODUCT PERFORMANCE", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            product_data = self.report_data['PRODUCT_PERFORMANCE']

            if 'summary' in product_data:
                summary = product_data['summary']

                product_summary = [
                    ['Total Products Sold', str(summary.get('total_products', 0))],
                    ['Total Quantity Sold', f"{summary.get('total_quantity_sold', 0):,.0f} units"],
                    ['Total Revenue', f"UGX {float(summary.get('total_revenue', 0)):,.0f}"],
                    ['Total Profit', f"UGX {float(summary.get('total_profit', 0)):,.0f}"],
                    ['Average Profit Margin', f"{summary.get('avg_profit_margin', 0):.1f}%"],
                ]

                product_table = Table(product_summary, colWidths=[180, 170])
                product_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#FD7E14')),
                    ('TEXTCOLOR', (0, 0), (0, -1), colors.white),
                    ('BACKGROUND', (1, 0), (1, -1), colors.HexColor('#FFF3CD')),
                    ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                    ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                    ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('PADDING', (0, 0), (-1, -1), 8),
                ]))
                elements.append(product_table)

            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 10. Stock Movement (if available)
        if 'STOCK_MOVEMENT' in self.report_data:
            elements.append(Paragraph("10. STOCK MOVEMENT ANALYSIS", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("Stock movement tracking and analysis", self.styles['Normal']))
            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 11. Customer Insights (if available)
        if 'CUSTOMER_ANALYTICS' in self.report_data:
            elements.append(Paragraph("11. CUSTOMER INSIGHTS", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("Customer behavior and segmentation analysis", self.styles['Normal']))
            elements.append(Spacer(1, 20))
            elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
            elements.append(Spacer(1, 20))

        # 12. EFRIS Compliance (if available)
        if 'EFRIS_COMPLIANCE' in self.report_data:
            elements.append(Paragraph("12. EFRIS COMPLIANCE", self.styles['SectionHeader']))
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("URA fiscal device compliance status", self.styles['Normal']))
            elements.append(Spacer(1, 20))

        # Report Footer
        elements.append(Spacer(1, 30))
        elements.append(HRFlowable(width="100%", thickness=2, color=colors.black))
        elements.append(Spacer(1, 10))
        elements.append(Paragraph("END OF REPORT", self.styles['Footer']))
        elements.append(Spacer(1, 5))
        elements.append(Paragraph("Confidential Business Document - For Internal Use Only", self.styles['Small']))

        return elements

    def _build_business_health_section(self):
        """Build business health score section"""
        elements = []
        health_data = self.report_data['business_health']

        # Health Score Card
        score_color = colors.green
        if health_data['percentage'] < 50:
            score_color = colors.red
        elif health_data['percentage'] < 70:
            score_color = colors.orange

        elements.append(Paragraph(
            f"Overall Health Score: {health_data['score']}/{health_data['max_score']} ({health_data['percentage']:.1f}%)",
            self.styles['HealthScore']))
        elements.append(Spacer(1, 5))
        elements.append(Paragraph(f"Grade: {health_data['grade']}", self.styles['HealthGrade']))
        elements.append(Spacer(1, 15))

        # Health Factors
        elements.append(Paragraph("Health Factors:", self.styles['SubSection']))
        for factor, score in health_data['factors']:
            elements.append(Paragraph(f"• {factor}: {score} points", self.styles['Normal']))

        return elements

    def _build_custom_analytics_section(self):
        """Build custom analytics section"""
        elements = []
        analytics = self.report_data['custom_analytics']

        # Key Metrics
        if 'key_metrics' in analytics:
            elements.append(Paragraph("Key Business Metrics:", self.styles['SubSection']))

            if 'cash_flow' in analytics['key_metrics']:
                cash_flow = analytics['key_metrics']['cash_flow']
                cash_color = colors.green if cash_flow >= 0 else colors.red
                elements.append(Paragraph(f"Cash Flow: UGX {cash_flow:,.0f}", self.styles['Normal']))

            if 'profitability' in analytics['key_metrics']:
                profit = analytics['key_metrics']['profitability']
                elements.append(
                    Paragraph(f"Net Profit: UGX {profit['net_profit']:,.0f} ({profit['net_margin']:.1f}% margin)",
                              self.styles['Normal']))

            if 'expense_to_sales_ratio' in analytics['key_metrics']:
                ratio = analytics['key_metrics']['expense_to_sales_ratio']
                ratio_status = "Good" if ratio < 30 else "Moderate" if ratio < 50 else "High"
                elements.append(Paragraph(f"Expense to Sales Ratio: {ratio:.1f}% ({ratio_status})",
                                          self.styles['Normal']))

            if 'credit_sales' in analytics['key_metrics']:
                credit = analytics['key_metrics']['credit_sales']
                if 'outstanding_amount' in credit:
                    elements.append(Paragraph(f"Outstanding Credit Sales: UGX {credit['outstanding_amount']:,.0f}",
                                              self.styles['Normal']))
                    elements.append(Paragraph(f"Collection Rate: {credit.get('collection_rate', 0):.1f}%",
                                              self.styles['Normal']))

        # Recommendations
        if 'recommendations' in analytics and analytics['recommendations']:
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("Recommendations:", self.styles['SubSection']))
            for rec in analytics['recommendations']:
                elements.append(Paragraph(f"• {rec}", self.styles['Normal']))

        return elements

    def _build_profit_loss_report(self) -> List:
        """Build profit and loss report"""
        elements = []

        elements.append(Paragraph("Profit & Loss Statement", self.styles['CustomTitle']))
        elements.append(Spacer(1, 20))

        pl_data = self.report_data['profit_loss']

        # Revenue Section
        if 'revenue' in pl_data:
            elements.append(Paragraph("Revenue", self.styles['SectionHeader']))
            revenue_data = [
                ['Gross Revenue', f"UGX {pl_data['revenue'].get('gross_revenue', 0):,.2f}"],
                ['Discounts', f"UGX {pl_data['revenue'].get('discounts', 0):,.2f}"],
                ['Net Revenue', f"UGX {pl_data['revenue'].get('net_revenue', 0):,.2f}"],
            ]
            elements.extend(self._build_simple_table(revenue_data))
            elements.append(Spacer(1, 15))

        # Costs Section
        if 'costs' in pl_data:
            elements.append(Paragraph("Costs", self.styles['SectionHeader']))
            costs_data = [
                ['Cost of Goods Sold', f"UGX {pl_data['costs'].get('cost_of_goods_sold', 0):,.2f}"],
                ['Tax', f"UGX {pl_data['costs'].get('tax', 0):,.2f}"],
                ['Total Costs', f"UGX {pl_data['costs'].get('total_costs', 0):,.2f}"],
            ]
            elements.extend(self._build_simple_table(costs_data))
            elements.append(Spacer(1, 15))

        # Profit Section
        if 'profit' in pl_data:
            elements.append(Paragraph("Profit", self.styles['SectionHeader']))

            gross_margin = pl_data['profit'].get('gross_margin', 0)
            net_margin = pl_data['profit'].get('net_margin', 0)

            gross_color = ColorScheme.get_status_color(gross_margin, 'percentage')
            net_color = ColorScheme.get_status_color(net_margin, 'percentage')

            profit_data = [
                ['Gross Profit', f"UGX {pl_data['profit'].get('gross_profit', 0):,.2f}"],
                ['Gross Margin',
                 Paragraph(f"<font color='{gross_color}'><b>{gross_margin:.2f}%</b></font>", self.styles['Normal'])],
                ['Net Profit', f"UGX {pl_data['profit'].get('net_profit', 0):,.2f}"],
                ['Net Margin',
                 Paragraph(f"<font color='{net_color}'><b>{net_margin:.2f}%</b></font>", self.styles['Normal'])],
            ]

            # Convert to table format
            profit_table_data = []
            for label, value in profit_data:
                if isinstance(value, str):
                    profit_table_data.append(
                        [Paragraph(f"<b>{label}</b>", self.styles['Normal']), Paragraph(value, self.styles['Normal'])])
                else:
                    profit_table_data.append([Paragraph(f"<b>{label}</b>", self.styles['Normal']), value])

            col_width = self.doc_width / 2
            profit_table = Table(profit_table_data, colWidths=[col_width, col_width])
            profit_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), ColorScheme.BG_LIGHT),
                ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ]))
            elements.append(profit_table)

        # Category Profit
        if 'category_profit' in self.report_data and self.report_data['category_profit']:
            elements.append(Spacer(1, 20))
            elements.append(Paragraph("Category Performance", self.styles['SectionHeader']))
            elements.extend(self._build_category_profit_table(self.report_data['category_profit']))

        return elements

    def _build_profit_loss_section(self, profit_loss_data):
        """Build profit & loss section"""
        elements = []

        if 'profit_loss' in profit_loss_data:
            pl_data = profit_loss_data['profit_loss']

            # P&L Statement Table
            pl_table_data = [
                ['Revenue', '', ''],
                ['  Gross Revenue', f"UGX {float(pl_data['revenue']['gross_revenue']):,.0f}", ''],
                ['  Less: Discounts', f"(UGX {float(pl_data['revenue']['discounts']):,.0f})", ''],
                ['Net Revenue', f"UGX {float(pl_data['revenue']['net_revenue']):,.0f}", ''],
                ['', '', ''],
                ['Costs', '', ''],
                ['  Cost of Goods Sold', f"(UGX {float(pl_data['costs']['cost_of_goods_sold']):,.0f})", ''],
                ['  Taxes', f"(UGX {float(pl_data['costs']['tax']):,.0f})", ''],
                ['Total Costs', f"(UGX {float(pl_data['costs']['total_costs']):,.0f})", ''],
                ['', '', ''],
                ['Profit', '', ''],
                ['  Gross Profit', f"UGX {float(pl_data['profit']['gross_profit']):,.0f}",
                 f"{pl_data['profit']['gross_margin']:.1f}%"],
                ['  Net Profit', f"UGX {float(pl_data['profit']['net_profit']):,.0f}",
                 f"{pl_data['profit']['net_margin']:.1f}%"],
            ]

            pl_table = Table(pl_table_data, colWidths=[200, 120, 80])
            pl_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2C3E50')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('BACKGROUND', (0, 5), (-1, 5), colors.HexColor('#34495E')),
                ('TEXTCOLOR', (0, 5), (-1, 5), colors.white),
                ('BACKGROUND', (0, 10), (-1, 10), colors.HexColor('#27AE60')),
                ('TEXTCOLOR', (0, 10), (-1, 10), colors.white),
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTNAME', (1, 0), (2, -1), 'Helvetica'),
                ('ALIGN', (1, 0), (2, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
            ]))
            elements.append(pl_table)

        return elements

    def _build_cashier_performance_report(self) -> List:
        """Build cashier performance report"""
        elements = []

        elements.append(Paragraph("Cashier Performance Report", self.styles['CustomTitle']))
        elements.append(Spacer(1, 20))

        # Summary
        if 'summary' in self.report_data:
            elements.extend(self._build_summary_section(self.report_data['summary']))
            elements.append(Spacer(1, 20))

        # Cashier Performance Table
        if 'performance' in self.report_data:
            elements.append(Paragraph("Cashier Details", self.styles['SectionHeader']))
            elements.extend(self._build_cashier_table(self.report_data['performance']))

        return elements

    def _build_cashier_table(self, performance_data: List[Dict]) -> List:
        """Build cashier performance table"""
        elements = []

        if not performance_data:
            elements.append(Paragraph("<i>No cashier data available</i>", self.styles['Normal']))
            return elements

        headers = ['Cashier', 'Store', 'Transactions', 'Total Sales', 'Avg Transaction']
        table_data = [[Paragraph(f"<b>{h}</b>", self.styles['Normal']) for h in headers]]

        for cashier in performance_data[:50]:
            name = f"{cashier.get('created_by__first_name', '')} {cashier.get('created_by__last_name', '')}".strip()
            if not name:
                name = cashier.get('created_by__username', 'Unknown')

            row = [
                Paragraph(name, self.styles['Normal']),
                Paragraph(cashier.get('store__name', '')[:20], self.styles['Normal']),
                Paragraph(f"{cashier.get('transaction_count', 0):,}", self.styles['Normal']),
                Paragraph(f"UGX {cashier.get('total_sales', 0):,.2f}", self.styles['Normal']),
                Paragraph(f"UGX {cashier.get('avg_transaction', 0):,.2f}", self.styles['Normal']),
            ]
            table_data.append(row)

        table = Table(table_data, colWidths=[120, 100, 80, 100, 100], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ColorScheme.BG_TABLE_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), ColorScheme.TEXT_LIGHT),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))

        # Alternate row colors
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, i), (-1, i), ColorScheme.BG_LIGHT)
                ]))

        elements.append(table)
        return elements

    def _build_expense_report(self) -> List:
        """Build expense report"""
        elements = []

        elements.append(Paragraph("Expense Report", self.styles['CustomTitle']))
        elements.append(Spacer(1, 20))

        # Summary
        if 'summary' in self.report_data:
            elements.extend(self._build_summary_section(self.report_data['summary']))
            elements.append(Spacer(1, 20))

        # Category Breakdown
        if 'category_breakdown' in self.report_data and self.report_data['category_breakdown']:
            elements.append(Paragraph("Expenses by Category", self.styles['SectionHeader']))
            elements.extend(self._build_expense_category_table(self.report_data['category_breakdown']))
            elements.append(Spacer(1, 20))

        # Store Breakdown
        if 'store_breakdown' in self.report_data and self.report_data['store_breakdown']:
            elements.append(Paragraph("Expenses by Store", self.styles['SectionHeader']))
            elements.extend(self._build_expense_store_table(self.report_data['store_breakdown']))

        return elements

    def _build_expense_category_table(self, category_breakdown):
        """Build expense category table"""
        elements = []

        category_data = []
        for category in category_breakdown[:10]:  # Top 10 categories
            category_data.append([
                category.get('category__name', 'Unknown')[:30],
                f"UGX {float(category.get('total_amount', 0)):,.0f}",
                str(category.get('expense_count', 0)),
                f"UGX {float(category.get('avg_amount', 0)):,.0f}"
            ])

        if category_data:
            category_table = Table([['Category', 'Total Amount', 'Count', 'Average']] + category_data)
            category_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#6C757D')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('ALIGN', (1, 0), (3, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 1, colors.grey),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F9FA')]),
            ]))
            elements.append(category_table)

        return elements

    def _build_expense_store_table(self, stores: List[Dict]) -> List:
        """Build expense store breakdown table"""
        elements = []

        if not stores:
            return elements

        headers = ['Store', 'Count', 'Total Amount']
        table_data = [[Paragraph(f"<b>{h}</b>", self.styles['Normal']) for h in headers]]

        for store in stores[:20]:
            row = [
                Paragraph(store.get('store__name', 'Unknown')[:30], self.styles['Normal']),
                Paragraph(f"{store.get('expense_count', 0):,}", self.styles['Normal']),
                Paragraph(f"UGX {store.get('total_amount', 0):,.2f}", self.styles['Normal']),
            ]
            table_data.append(row)

        table = Table(table_data, colWidths=[200, 100, 150], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ColorScheme.BG_TABLE_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), ColorScheme.TEXT_LIGHT),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        elements.append(table)
        return elements

    def _build_stock_movement_report(self) -> List:
        """Build stock movement report"""
        elements = []

        elements.append(Paragraph("Stock Movement Report", self.styles['CustomTitle']))
        elements.append(Spacer(1, 20))

        # Summary
        if 'summary' in self.report_data:
            elements.extend(self._build_summary_section(self.report_data['summary']))
            elements.append(Spacer(1, 20))

        # Movement details table
        if 'movements' in self.report_data and self.report_data['movements']:
            elements.append(Paragraph("Movement Details", self.styles['SectionHeader']))
            elements.extend(self._build_stock_movement_table(self.report_data['movements']))

        return elements

    def _build_stock_movement_table(self, movements: List[Dict]) -> List:
        """Build stock movement table"""
        elements = []

        headers = ['Product', 'Store', 'Type', 'Quantity', 'Date']
        table_data = [[Paragraph(f"<b>{h}</b>", self.styles['Normal']) for h in headers]]

        for movement in movements[:50]:
            row = [
                Paragraph(movement.get('product_name', '')[:25], self.styles['Normal']),
                Paragraph(movement.get('store_name', '')[:20], self.styles['Normal']),
                Paragraph(movement.get('movement_type', ''), self.styles['Normal']),
                Paragraph(f"{movement.get('quantity', 0):,}", self.styles['Normal']),
                Paragraph(movement.get('created_at', '')[:10], self.styles['Normal']),
            ]
            table_data.append(row)

        table = Table(table_data, colWidths=[120, 100, 80, 80, 80], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ColorScheme.BG_TABLE_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), ColorScheme.TEXT_LIGHT),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        elements.append(table)
        return elements

    def _build_customer_analytics_report(self) -> List:
        """Build customer analytics report"""
        elements = []

        elements.append(Paragraph("Customer Analytics Report", self.styles['CustomTitle']))
        elements.append(Spacer(1, 20))

        # Summary
        if 'summary' in self.report_data:
            elements.extend(self._build_summary_section(self.report_data['summary']))
            elements.append(Spacer(1, 20))

        # Top customers table
        if 'customers' in self.report_data and self.report_data['customers']:
            elements.append(Paragraph("Top Customers", self.styles['SectionHeader']))
            elements.extend(self._build_customer_table(self.report_data['customers']))

        return elements

    def _build_customer_table(self, customers: List[Dict]) -> List:
        """Build customer analytics table"""
        elements = []

        headers = ['Customer', 'Purchases', 'Total Spent', 'Avg Purchase']
        table_data = [[Paragraph(f"<b>{h}</b>", self.styles['Normal']) for h in headers]]

        for customer in customers[:30]:
            row = [
                Paragraph(customer.get('customer__name', 'Unknown')[:30], self.styles['Normal']),
                Paragraph(f"{customer.get('total_purchases', 0):,}", self.styles['Normal']),
                Paragraph(f"UGX {customer.get('total_spent', 0):,.2f}", self.styles['Normal']),
                Paragraph(f"UGX {customer.get('avg_purchase', 0):,.2f}", self.styles['Normal']),
            ]
            table_data.append(row)

        table = Table(table_data, colWidths=[150, 80, 120, 120], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ColorScheme.BG_TABLE_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), ColorScheme.TEXT_LIGHT),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        elements.append(table)
        return elements

    def _build_compliance_section(self, compliance: Dict) -> List:
        """Build EFRIS compliance section"""
        elements = []

        elements.append(Paragraph("EFRIS Compliance Status", self.styles['SectionHeader']))

        compliance_rate = compliance.get('compliance_rate', 0)
        color = ColorScheme.get_status_color(compliance_rate, 'percentage')

        compliance_data = [
            ['Total Sales', f"{compliance.get('total_sales', 0):,}"],
            ['Fiscalized', f"{compliance.get('fiscalized', 0):,}"],
            ['Pending', f"{compliance.get('pending', 0):,}"],
            ['Failed', f"{compliance.get('failed', 0):,}"],
            ['Compliance Rate',
             Paragraph(f"<font color='{color}'><b>{compliance_rate:.2f}%</b></font>", self.styles['Normal'])],
        ]

        # Convert to proper format
        table_data = []
        for label, value in compliance_data:
            if isinstance(value, str):
                table_data.append(
                    [Paragraph(f"<b>{label}</b>", self.styles['Normal']), Paragraph(value, self.styles['Normal'])])
            else:
                table_data.append([Paragraph(f"<b>{label}</b>", self.styles['Normal']), value])

        elements.extend(self._build_simple_table_from_paragraphs(table_data))
        return elements

    def _build_simple_table(self, data: List[List]) -> List:
        """Build a simple two-column table"""
        elements = []

        col_width = self.doc_width / 2
        table = Table(data, colWidths=[col_width, col_width])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), ColorScheme.BG_LIGHT),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ]))

        elements.append(table)
        return elements

    def _build_simple_table_from_paragraphs(self, table_data: List[List]) -> List:
        """Build a simple table from pre-formatted Paragraph objects"""
        elements = []

        col_width = self.doc_width / 2
        table = Table(table_data, colWidths=[col_width, col_width])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), ColorScheme.BG_LIGHT),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ]))

        elements.append(table)
        return elements

    def _build_category_profit_table(self, categories: List[Dict]) -> List:
        """Build category profit table"""
        elements = []

        if not categories:
            elements.append(Paragraph("<i>No category data available</i>", self.styles['Normal']))
            return elements

        headers = ['Category', 'Revenue', 'Cost', 'Profit', 'Margin']
        table_data = [[Paragraph(f"<b>{h}</b>", self.styles['Normal']) for h in headers]]
        for cat in categories[:20]:
            margin = cat.get('margin', 0)
            margin_color = ColorScheme.get_status_color(margin, 'percentage')

            row = [
                Paragraph(cat.get('category', 'Unknown')[:25], self.styles['Normal']),
                Paragraph(f"UGX {cat.get('revenue', 0):,.2f}", self.styles['Normal']),
                Paragraph(f"UGX {cat.get('cost', 0):,.2f}", self.styles['Normal']),
                Paragraph(f"UGX {cat.get('profit', 0):,.2f}", self.styles['Normal']),
                Paragraph(f"<font color='{margin_color}'><b>{margin:.1f}%</b></font>", self.styles['Normal']),
            ]
            table_data.append(row)

        table = Table(table_data, colWidths=[120, 100, 100, 100, 80], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ColorScheme.BG_TABLE_HEADER),
            ('TEXTCOLOR', (0, 0), (-1, 0), ColorScheme.TEXT_LIGHT),
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        # Alternate row colors
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                table.setStyle(TableStyle([
                    ('BACKGROUND', (0, i), (-1, i), ColorScheme.BG_LIGHT)
                ]))

        elements.append(table)
        return elements

    def _build_efris_section(self, efris_stats: Dict) -> List:
        """Build EFRIS compliance section"""
        elements = []
        elements.append(Paragraph("EFRIS Compliance Status", self.styles['SectionHeader']))

        compliance_rate = efris_stats.get('compliance_rate', 0)
        status_color = ColorScheme.get_status_color(compliance_rate, 'percentage')

        # Compliance summary
        summary_text = f"""
        <para align=center>
        <font size=14><b>Compliance Rate: </b></font>
        <font size=18 color='{status_color}'><b>{compliance_rate:.2f}%</b></font><br/>
        <font size=11>Total Sales: {efris_stats.get('total_sales', 0):,} | 
        Fiscalized: {efris_stats.get('fiscalized', 0):,} | 
        Pending: {efris_stats.get('pending', 0):,}</font>
        </para>
        """
        elements.append(Paragraph(summary_text, self.styles['Normal']))
        elements.append(Spacer(1, 15))

        return elements

    def _build_alerts_table(self, alerts: List[Dict]) -> List:
        """Build stock alerts table"""
        elements = []

        headers = ['Product', 'Store', 'Current Stock', 'Reorder Level', 'Action Required']
        table_data = [[Paragraph(f"<b>{h}</b>", self.styles['Normal']) for h in headers]]

        for alert in alerts:
            quantity = alert.get('quantity', 0)
            threshold = alert.get('low_stock_threshold', 0)

            # Determine urgency
            if quantity == 0:
                urgency_color = ColorScheme.DANGER
                action = "RESTOCK IMMEDIATELY"
            elif quantity <= threshold / 2:
                urgency_color = ColorScheme.DANGER
                action = "RESTOCK URGENT"
            else:
                urgency_color = ColorScheme.WARNING
                action = "Restock Soon"

            row = [
                Paragraph(alert.get('product__name', ''), self.styles['Normal']),
                Paragraph(alert.get('store__name', ''), self.styles['Normal']),
                Paragraph(f"<font color='{urgency_color}'><b>{quantity:,}</b></font>",
                          self.styles['Normal']),
                Paragraph(f"{threshold:,}", self.styles['Normal']),
                Paragraph(f"<font color='{urgency_color}'><b>{action}</b></font>",
                          self.styles['Normal']),
            ]
            table_data.append(row)

        table = Table(table_data, colWidths=[120, 100, 80, 80, 100], repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), ColorScheme.DANGER),
            ('TEXTCOLOR', (0, 0), (-1, 0), ColorScheme.TEXT_LIGHT),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 0.5, ColorScheme.NEUTRAL),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))

        elements.append(table)
        return elements