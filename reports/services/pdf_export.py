"""
Professional PDF Export Service with Dynamic Styling
"""
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, Image, Frame, PageTemplate
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

        # Add alerts if any
        if 'alerts' in self.report_data and self.report_data['alerts']:
            story.append(PageBreak())
            story.append(Paragraph("Stock Alerts", self.styles['SectionHeader']))
            story.extend(self._build_alerts_table(self.report_data['alerts']))

        # Build PDF with custom canvas
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

    def _build_summary_section(self, summary: Dict) -> List:
        """Build summary cards section"""
        elements = []
        elements.append(Paragraph("Executive Summary", self.styles['SectionHeader']))

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

        # 🟢 Fix: fill remaining cells with Paragraph() instead of ''
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