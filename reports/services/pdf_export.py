"""
PDF Export Service — Narrative-driven layout
=============================================

Every section follows the pattern:
    Scope line  →  Narrative paragraph box  →  Comparison callout pair
    →  Supporting table  →  Insight box

No charts. Role-aware depth. Currency from CurrencyFormatter.

Usage (from tasks.py or views.py):
    from .services.currency_formatter import get_formatter
    from .services.narrative_engine import build_narratives, resolve_reader_role
    from .services.comparison_engine import ComparisonEngine

    fmt          = get_formatter(user=user)
    reader_role  = resolve_reader_role(user)
    engine       = ComparisonEngine(user, saved_report)
    result       = engine.fetch(start_date=..., end_date=..., store_id=...)

    narratives = build_narratives(
        report_type   = saved_report.report_type,
        data          = result['current'],
        prior         = result['prior'],
        delta         = result['delta'],
        fmt           = fmt,
        period_label  = result['current_label'],
        prior_label   = result['prior_label'],
        reader_role   = reader_role,
    )

    buffer = PDFExportService(
        report_data   = result['current'],
        report_name   = saved_report.name,
        report_type   = saved_report.report_type,
        company_info  = {'name': user.company.name if user.company else 'Company'},
        narratives    = narratives,
        fmt           = fmt,
        prior_data    = result['prior'],
        delta         = result['delta'],
        period_label  = result['current_label'],
        prior_label   = result['prior_label'],
        reader_role   = reader_role,
    ).generate_pdf()
"""

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    PageBreak, HRFlowable, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_RIGHT, TA_LEFT, TA_JUSTIFY
from reportlab.pdfgen import canvas
from django.utils import timezone
from io import BytesIO
from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


# ── Colour palette ────────────────────────────────────────────────────────────

class C:
    PRIMARY       = colors.HexColor('#2563eb')
    PRIMARY_DARK  = colors.HexColor('#1e40af')
    PRIMARY_LIGHT = colors.HexColor('#dbeafe')

    SUCCESS       = colors.HexColor('#059669')
    SUCCESS_BG    = colors.HexColor('#d1fae5')
    WARNING       = colors.HexColor('#d97706')
    WARNING_BG    = colors.HexColor('#fef3c7')
    DANGER        = colors.HexColor('#dc2626')
    DANGER_BG     = colors.HexColor('#fee2e2')
    INFO          = colors.HexColor('#0284c7')
    INFO_BG       = colors.HexColor('#e0f2fe')

    TEXT          = colors.HexColor('#111827')
    TEXT_MUTED    = colors.HexColor('#6b7280')
    BORDER        = colors.HexColor('#e5e7eb')
    BG_PAGE       = colors.HexColor('#f9fafb')
    BG_TABLE_HDR  = colors.HexColor('#1e40af')
    WHITE         = colors.white

    INSIGHT_COLORS = {
        'success': (SUCCESS,    SUCCESS_BG),
        'warning': (WARNING,    WARNING_BG),
        'danger':  (DANGER,     DANGER_BG),
        'info':    (INFO,       INFO_BG),
    }


# ── Role priority map ─────────────────────────────────────────────────────────

ROLE_PRIORITY = {
    'owner':      100,
    'manager':     70,
    'accountant':  40,
    'auditor':     35,
    'limited':     10,
}

def _role_gte(reader_role: str, min_role: str) -> bool:
    return ROLE_PRIORITY.get(reader_role, 0) >= ROLE_PRIORITY.get(min_role, 0)


# ── Numbered canvas (header / footer / page numbers) ─────────────────────────

class _NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        canvas.Canvas.__init__(self, *args, **kwargs)
        self._saved_page_states = []
        self.company_name  = ''
        self.report_title  = ''
        self.period_label  = ''
        self.reader_role   = 'owner'

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_page_chrome(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def _draw_page_chrome(self, page_count):
        page_num = len(self._saved_page_states)
        w, h = self._pagesize

        # ── Header bar ──────────────────────────────────────────────────────
        self.saveState()
        self.setFillColor(C.PRIMARY_DARK)
        self.rect(0, h - 52, w, 52, fill=1, stroke=0)

        self.setFillColor(C.WHITE)
        self.setFont('Helvetica-Bold', 13)
        self.drawString(32, h - 24, self.company_name or 'Company')

        self.setFont('Helvetica', 10)
        self.drawString(32, h - 40, self.report_title or '')

        # Period label top-right
        if self.period_label:
            self.setFont('Helvetica', 9)
            lbl = f'Period: {self.period_label}'
            tw = self.stringWidth(lbl, 'Helvetica', 9)
            self.drawString(w - tw - 32, h - 32, lbl)

        self.restoreState()

        # ── Footer ───────────────────────────────────────────────────────────
        self.saveState()
        self.setStrokeColor(C.BORDER)
        self.setLineWidth(0.5)
        self.line(32, 42, w - 32, 42)

        self.setFillColor(C.TEXT_MUTED)
        self.setFont('Helvetica', 8)

        # Role badge bottom-left
        role_label = self.reader_role.upper()
        self.drawString(32, 28, f'View: {role_label}')

        # Timestamp centre
        ts = timezone.now().strftime('%d %b %Y %H:%M')
        ts_text = f'Generated {ts}'
        tw = self.stringWidth(ts_text, 'Helvetica', 8)
        self.drawString((w - tw) / 2, 28, ts_text)

        # Page number right
        pg = f'Page {page_num} of {page_count}'
        tw = self.stringWidth(pg, 'Helvetica', 8)
        self.drawString(w - tw - 32, 28, pg)

        self.restoreState()


# ── Main service ──────────────────────────────────────────────────────────────

class PDFExportService:
    """
    Narrative-driven PDF export.

    Parameters
    ----------
    report_data   : current-period data dict from ReportGeneratorService
    report_name   : human-readable report name (used in header)
    report_type   : SavedReport.report_type string key
    company_info  : dict with at least {'name': str}
    narratives    : list[NarrativeBlock] from build_narratives()
    fmt           : CurrencyFormatter instance
    prior_data    : prior-period data dict (may be empty {})
    delta         : delta dict from ComparisonEngine
    period_label  : e.g. "April 2026"
    prior_label   : e.g. "March 2026"
    reader_role   : 'owner' | 'manager' | 'accountant' | 'auditor' | 'limited'
    orientation   : 'auto' | 'portrait' | 'landscape'
    """

    def __init__(
        self,
        report_data:  Dict[str, Any],
        report_name:  str,
        report_type:  str               = '',
        company_info: Dict[str, Any]    = None,
        narratives:   list              = None,
        fmt                             = None,
        prior_data:   Dict[str, Any]    = None,
        delta:        Dict[str, Any]    = None,
        period_label: str               = '',
        prior_label:  str               = 'prior period',
        reader_role:  str               = 'owner',
        orientation:  str               = 'auto',
    ):
        self.report_data  = report_data
        self.report_name  = report_name
        self.report_type  = report_type
        self.company_info = company_info or {}
        self.narratives   = narratives   or []
        self.prior_data   = prior_data   or {}
        self.delta        = delta        or {}
        self.period_label = period_label
        self.prior_label  = prior_label
        self.reader_role  = reader_role
        self.orientation  = orientation

        # Currency formatter — fall back to a plain UGX formatter if none given
        if fmt is not None:
            self.fmt = fmt
        else:
            from .currency_formatter import CurrencyFormatter
            self.fmt = CurrencyFormatter()

        self.styles = getSampleStyleSheet()
        self._setup_styles()
        self.doc_width = 515  # A4 portrait usable width (points) at 40pt margins

    # ── Style setup ───────────────────────────────────────────────────────────

    def _setup_styles(self):
        s = self.styles

        def _add(name, **kw):
            if name not in s:
                parent = kw.pop('parent', s['Normal'])
                s.add(ParagraphStyle(name=name, parent=parent, **kw))

        _add('CoverTitle',
             fontSize=28, fontName='Helvetica-Bold',
             textColor=C.PRIMARY_DARK, alignment=TA_CENTER, spaceAfter=12)
        _add('CoverSubtitle',
             fontSize=14, textColor=C.TEXT_MUTED,
             alignment=TA_CENTER, spaceAfter=6)
        _add('CoverMeta',
             fontSize=11, textColor=C.TEXT_MUTED,
             alignment=TA_CENTER, spaceAfter=4)
        _add('SectionHeader',
             parent=s['Heading2'],
             fontSize=13, fontName='Helvetica-Bold',
             textColor=C.PRIMARY_DARK,
             spaceBefore=14, spaceAfter=6)
        _add('ScopeText',
             fontSize=9, textColor=C.TEXT_MUTED,
             spaceBefore=0, spaceAfter=4)
        _add('NarrativeText',
             fontSize=10, textColor=C.TEXT,
             leading=16, alignment=TA_JUSTIFY,
             spaceBefore=0, spaceAfter=0)
        _add('InsightText',
             fontSize=10, fontName='Helvetica-Bold',
             textColor=C.TEXT, leading=14,
             spaceBefore=0, spaceAfter=0)
        _add('CompareLabel',
             fontSize=8, textColor=C.TEXT_MUTED,
             alignment=TA_CENTER, spaceAfter=1)
        _add('CompareValue',
             fontSize=12, fontName='Helvetica-Bold',
             textColor=C.TEXT, alignment=TA_CENTER, spaceAfter=0)
        _add('CompareDelta',
             fontSize=9, alignment=TA_CENTER, spaceAfter=0)
        _add('TableHeader',
             fontSize=9, fontName='Helvetica-Bold',
             textColor=C.WHITE, alignment=TA_CENTER)
        _add('TableCell',
             fontSize=9, textColor=C.TEXT, leading=12)
        _add('TableCellRight',
             fontSize=9, textColor=C.TEXT,
             alignment=TA_RIGHT, leading=12)
        _add('SubSection',
             parent=s['Heading3'],
             fontSize=11, fontName='Helvetica-Bold',
             textColor=C.TEXT, spaceBefore=10, spaceAfter=4)
        # Previously missing styles — kept for combined report compatibility
        _add('TOCItem',
             fontSize=10, textColor=C.TEXT,
             leftIndent=12, spaceAfter=3)
        _add('Footer',
             fontSize=9, textColor=C.TEXT_MUTED,
             alignment=TA_CENTER)
        _add('Small',
             fontSize=8, textColor=C.TEXT_MUTED,
             alignment=TA_CENTER)
        _add('HealthScore',
             fontSize=20, fontName='Helvetica-Bold',
             textColor=C.PRIMARY_DARK, alignment=TA_CENTER, spaceAfter=4)
        _add('HealthGrade',
             fontSize=14, fontName='Helvetica-Bold',
             textColor=C.SUCCESS, alignment=TA_CENTER, spaceAfter=8)

    # ── Public entry point ─────────────────────────────────────────────────────

    def generate_pdf(self) -> BytesIO:
        buffer   = BytesIO()
        pagesize = self._pagesize()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=pagesize,
            rightMargin=40, leftMargin=40,
            topMargin=72, bottomMargin=60,
        )
        self.doc_width = doc.width

        story = self._build_story()
        if not story:
            story = [Paragraph('No data available for this report.', self.styles['Normal'])]

        def _make_canvas(*args, **kwargs):
            c = _NumberedCanvas(*args, **kwargs)
            c.company_name  = self.company_info.get('name', 'Company')
            c.report_title  = self.report_name
            c.period_label  = self.period_label
            c.reader_role   = self.reader_role
            return c

        doc.build(story, canvasmaker=_make_canvas)
        buffer.seek(0)
        return buffer

    def _pagesize(self):
        if self.orientation == 'landscape':
            return landscape(A4)
        if self.orientation == 'portrait':
            return A4
        # auto: portrait for most reports
        return A4

    # ── Story dispatcher ──────────────────────────────────────────────────────

    def _build_story(self) -> List:
        story = []
        story.extend(self._build_cover())
        story.append(PageBreak())

        rt = self.report_type

        if self._is_combined():
            story.extend(self._build_combined())
        elif rt == 'SALES_SUMMARY':
            story.extend(self._build_sections('SALES_SUMMARY',
                ['revenue', 'payment_methods', 'top_products']))
            story.extend(self._build_sales_tables())
        elif rt == 'PROFIT_LOSS':
            story.extend(self._build_sections('PROFIT_LOSS',
                ['profit_loss', 'category_profit']))
            story.extend(self._build_pl_tables())
        elif rt in ('EXPENSE_REPORT', 'EXPENSE_ANALYTICS'):
            story.extend(self._build_sections(rt, ['expenses']))
            story.extend(self._build_expense_tables())
        elif rt == 'INVENTORY_STATUS':
            story.extend(self._build_sections(rt, ['inventory']))
            story.extend(self._build_inventory_tables())
        elif rt == 'CASHIER_PERFORMANCE':
            story.extend(self._build_sections(rt, ['cashier']))
            story.extend(self._build_cashier_tables())
        elif rt == 'PRODUCT_PERFORMANCE':
            story.extend(self._build_sections(rt, ['product_performance']))
            story.extend(self._build_product_tables())
        elif rt == 'TAX_REPORT':
            story.extend(self._build_sections(rt, ['tax']))
            story.extend(self._build_tax_tables())
        elif rt == 'EFRIS_COMPLIANCE':
            story.extend(self._build_sections(rt, ['efris']))
            story.extend(self._build_efris_tables())
        elif rt == 'Z_REPORT':
            story.extend(self._build_sections(rt, ['z_report']))
            story.extend(self._build_z_tables())
        elif rt == 'STOCK_MOVEMENT':
            story.extend(self._build_sections(rt, ['stock_movement']))
            story.extend(self._build_stock_movement_tables())
        elif rt == 'CUSTOMER_ANALYTICS':
            story.extend(self._build_sections(rt, ['customer_analytics']))
            story.extend(self._build_customer_tables())
        else:
            # Generic fallback
            if 'summary' in self.report_data:
                story.extend(self._build_kv_table(self.report_data['summary'],
                                                   'Summary'))

        story.extend(self._build_report_footer())
        return story

    # ── Cover page ─────────────────────────────────────────────────────────────

    def _build_cover(self) -> List:
        el = []
        el.append(Spacer(1, 60))

        company = self.company_info.get('name', 'Company')
        el.append(Paragraph(company, self.styles['CoverTitle']))
        el.append(Spacer(1, 8))
        el.append(Paragraph(self.report_name, self.styles['CoverSubtitle']))
        el.append(Spacer(1, 24))

        el.append(HRFlowable(width='60%', thickness=1,
                              color=C.PRIMARY, hAlign='CENTER'))
        el.append(Spacer(1, 24))

        if self.period_label:
            el.append(Paragraph(f'Period: {self.period_label}',
                                 self.styles['CoverMeta']))
        if self.prior_label and self.prior_data:
            el.append(Paragraph(f'Compared with: {self.prior_label}',
                                 self.styles['CoverMeta']))

        role_display = {
            'owner': 'Owner / Administrator',
            'manager': 'Manager',
            'accountant': 'Accountant',
            'auditor': 'Auditor',
            'limited': 'Limited View',
        }.get(self.reader_role, self.reader_role.title())
        el.append(Paragraph(f'Report depth: {role_display}',
                             self.styles['CoverMeta']))

        ts = timezone.now().strftime('%d %B %Y at %H:%M')
        el.append(Paragraph(f'Generated: {ts}', self.styles['CoverMeta']))

        return el

    # ── Section builder (narrative → callouts → table → insight) ──────────────

    def _build_sections(self, report_type: str, section_keys: List[str]) -> List:
        """
        For each NarrativeBlock whose section key is in section_keys,
        render: scope → narrative box → comparison callout → insight box.
        """
        el = []
        narrative_map = {nb.section: nb for nb in self.narratives}

        for key in section_keys:
            nb = narrative_map.get(key)
            if nb is None:
                continue

            el.append(Paragraph(nb.heading, self.styles['SectionHeader']))

            # Scope line
            scope_parts = []
            if self.period_label:
                scope_parts.append(self.period_label)
            if self.prior_label and self.prior_data:
                scope_parts.append(f'vs {self.prior_label}')
            if scope_parts:
                el.append(Paragraph(' · '.join(scope_parts),
                                     self.styles['ScopeText']))

            # Narrative paragraph box
            if nb.paragraphs:
                el.append(self._narrative_box('\n\n'.join(nb.paragraphs)))
                el.append(Spacer(1, 8))

            # Comparison callout pair (current vs prior)
            callout = self._comparison_callout_for_section(key)
            if callout:
                el.append(callout)
                el.append(Spacer(1, 8))

            # Insight box
            if nb.insight:
                el.append(self._insight_box(nb.insight, nb.insight_level))
                el.append(Spacer(1, 10))

            el.append(Spacer(1, 6))

        return el

    # ── Primitive builders ────────────────────────────────────────────────────

    def _narrative_box(self, text: str) -> Table:
        """A lightly shaded paragraph box for narrative text."""
        para = Paragraph(text.replace('\n\n', '<br/><br/>'),
                         self.styles['NarrativeText'])
        t = Table([[para]], colWidths=[self.doc_width])
        t.setStyle(TableStyle([
            ('BACKGROUND',   (0, 0), (-1, -1), C.INFO_BG),
            ('LEFTPADDING',  (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING',   (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 10),
            ('LINEAFTER',    (0, 0), (0, -1),  3, C.PRIMARY),
        ]))
        return t

    def _insight_box(self, text: str, level: str = 'info') -> Table:
        """Coloured callout box for insight/alert text."""
        border_color, bg_color = C.INSIGHT_COLORS.get(
            level, (C.INFO, C.INFO_BG))
        icon = {'success': '✓', 'warning': '⚠', 'danger': '!', 'info': 'i'}.get(level, 'i')
        label = Paragraph(f'<b>{icon} {text}</b>', self.styles['InsightText'])
        t = Table([[label]], colWidths=[self.doc_width])
        t.setStyle(TableStyle([
            ('BACKGROUND',   (0, 0), (-1, -1), bg_color),
            ('LEFTPADDING',  (0, 0), (-1, -1), 12),
            ('RIGHTPADDING', (0, 0), (-1, -1), 12),
            ('TOPPADDING',   (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING',(0, 0), (-1, -1), 8),
            ('LINEAFTER',    (0, 0), (0, -1),  3, border_color),
        ]))
        return t

    def _comparison_callout_for_section(self, section_key: str) -> Optional[Table]:
        """
        Build a two-column callout showing current vs prior for the
        primary metric of a section, if prior data exists.
        """
        if not self.prior_data or not self.delta:
            return None

        # Map section keys to the delta metric key and a display label
        section_metric_map = {
            'revenue':           ('total_sales',          'Revenue'),
            'profit_loss':       ('pl_net_profit',        'Net Profit'),
            'expenses':          ('total_amount',         'Total Expenses'),
            'cashier':           ('total_sales',          'Total Sales'),
            'inventory':         ('total_stock_value',    'Stock Value'),
            'tax':               ('total_tax_collected',  'Tax Collected'),
            'efris':             ('compliance_rate',      'Compliance Rate'),
            'z_report':          ('total_sales',          'Day Sales'),
            'product_performance':('total_revenue_products', 'Revenue'),
            'stock_movement':    ('net_movement',         'Net Movement'),
            'customer_analytics':('total_revenue',        'Revenue'),
            'payment_methods':   ('total_sales',          'Revenue'),
            'top_products':      ('total_sales',          'Revenue'),
            'category_profit':   ('pl_gross_profit',      'Gross Profit'),
        }
        mapping = section_metric_map.get(section_key)
        if not mapping:
            return None

        metric_key, display_label = mapping
        delta_info = self.delta.get(metric_key)
        if not delta_info:
            return None

        current_val = delta_info.get('current', 0)
        prior_val   = delta_info.get('prior', 0)
        pct         = delta_info.get('pct_change')
        direction   = delta_info.get('direction', 'flat')

        # Format values — compliance rate as %, others as currency
        is_pct_metric = metric_key in ('compliance_rate',)
        if is_pct_metric:
            fmt_current = f'{current_val:.1f}%'
            fmt_prior   = f'{prior_val:.1f}%'
        else:
            fmt_current = self.fmt.format(current_val)
            fmt_prior   = self.fmt.format(prior_val)

        # Delta badge
        if pct is None:
            delta_str   = 'No prior data'
            delta_color = C.TEXT_MUTED
        elif direction == 'up':
            delta_str   = f'▲ {abs(pct):.1f}%'
            delta_color = C.SUCCESS
        elif direction == 'down':
            delta_str   = f'▼ {abs(pct):.1f}%'
            delta_color = C.DANGER
        else:
            delta_str   = '━ No change'
            delta_color = C.TEXT_MUTED

        w3 = self.doc_width / 3

        current_cell = [
            Paragraph(f'This period<br/><font size="7">{self.period_label}</font>',
                      self.styles['CompareLabel']),
            Paragraph(fmt_current, self.styles['CompareValue']),
        ]
        prior_cell = [
            Paragraph(f'Prior period<br/><font size="7">{self.prior_label}</font>',
                      self.styles['CompareLabel']),
            Paragraph(fmt_prior, self.styles['CompareValue']),
        ]
        delta_cell = [
            Paragraph('Change', self.styles['CompareLabel']),
            Paragraph(f'<font color="{delta_color}">{delta_str}</font>',
                      self.styles['CompareDelta']),
        ]

        t = Table(
            [[current_cell, prior_cell, delta_cell]],
            colWidths=[w3, w3, w3],
        )
        t.setStyle(TableStyle([
            ('BACKGROUND',    (0, 0), (0, -1),  C.PRIMARY_LIGHT),
            ('BACKGROUND',    (1, 0), (1, -1),  C.BG_PAGE),
            ('BACKGROUND',    (2, 0), (2, -1),  C.BG_PAGE),
            ('BOX',           (0, 0), (-1, -1), 0.5, C.BORDER),
            ('INNERGRID',     (0, 0), (-1, -1), 0.5, C.BORDER),
            ('TOPPADDING',    (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LEFTPADDING',   (0, 0), (-1, -1), 8),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 8),
            ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        return t

    def _section_divider(self) -> HRFlowable:
        return HRFlowable(width='100%', thickness=0.5, color=C.BORDER,
                          spaceAfter=10, spaceBefore=4)

    # ── Generic table helpers ─────────────────────────────────────────────────

    def _data_table(self, headers: List[str], rows: List[List],
                    col_widths: List[float] = None) -> Table:
        """Standard striped data table with coloured header."""
        header_row = [
            Paragraph(h, self.styles['TableHeader']) for h in headers
        ]
        table_data = [header_row] + [
            [Paragraph(str(cell), self.styles['TableCell']) for cell in row]
            for row in rows
        ]

        if col_widths is None:
            n = len(headers)
            col_widths = [self.doc_width / n] * n

        t = Table(table_data, colWidths=col_widths, repeatRows=1)
        style = [
            ('BACKGROUND',    (0, 0), (-1,  0),  C.BG_TABLE_HDR),
            ('TEXTCOLOR',     (0, 0), (-1,  0),  C.WHITE),
            ('FONTNAME',      (0, 0), (-1,  0),  'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1,  0),  9),
            ('ALIGN',         (0, 0), (-1,  0),  'CENTER'),
            ('TOPPADDING',    (0, 0), (-1, -1),  6),
            ('BOTTOMPADDING', (0, 0), (-1, -1),  6),
            ('LEFTPADDING',   (0, 0), (-1, -1),  6),
            ('RIGHTPADDING',  (0, 0), (-1, -1),  6),
            ('GRID',          (0, 0), (-1, -1),  0.4, C.BORDER),
            ('VALIGN',        (0, 0), (-1, -1),  'MIDDLE'),
        ]
        for i in range(1, len(table_data)):
            if i % 2 == 0:
                style.append(('BACKGROUND', (0, i), (-1, i), C.BG_PAGE))
        t.setStyle(TableStyle(style))
        return t

    def _kv_table(self, data: dict, title: str = '') -> List:
        """Two-column key → value table for summary dicts."""
        el = []
        if title:
            el.append(Paragraph(title, self.styles['SubSection']))
        rows = []
        for k, v in data.items():
            if isinstance(v, dict) or isinstance(v, list):
                continue
            label = str(k).replace('_', ' ').title()
            if isinstance(v, float):
                # Heuristic: format as currency if looks like money
                lower_k = k.lower()
                if any(x in lower_k for x in ('amount', 'sales', 'revenue',
                                               'profit', 'cost', 'tax',
                                               'discount', 'value', 'price')):
                    val = self.fmt.format(v)
                elif 'rate' in lower_k or 'margin' in lower_k or 'pct' in lower_k:
                    val = f'{v:.1f}%'
                else:
                    val = f'{v:,.2f}'
            elif isinstance(v, int):
                val = f'{v:,}'
            else:
                val = str(v) if v is not None else '—'
            rows.append([label, val])

        if not rows:
            return el

        t = Table(rows, colWidths=[self.doc_width * 0.55, self.doc_width * 0.45])
        t.setStyle(TableStyle([
            ('FONTNAME',      (0, 0), (0, -1),  'Helvetica-Bold'),
            ('FONTSIZE',      (0, 0), (-1, -1), 9),
            ('TEXTCOLOR',     (0, 0), (0, -1),  C.TEXT),
            ('TEXTCOLOR',     (1, 0), (1, -1),  C.TEXT),
            ('ALIGN',         (1, 0), (1, -1),  'RIGHT'),
            ('TOPPADDING',    (0, 0), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ('LEFTPADDING',   (0, 0), (-1, -1), 6),
            ('RIGHTPADDING',  (0, 0), (-1, -1), 6),
            ('LINEBELOW',     (0, 0), (-1, -2), 0.3, C.BORDER),
        ]))
        el.append(t)
        return el

    # Convenience alias kept for backward compatibility with combined builder
    def _build_kv_table(self, data, title=''):
        return self._kv_table(data, title)

    # ── Report-type table builders ────────────────────────────────────────────

    def _build_sales_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        summary = self.report_data.get('summary', {})
        if summary:
            el += self._kv_table(summary, 'Sales Summary')
            el.append(Spacer(1, 10))

        # Payment methods
        pm = self.report_data.get('payment_methods', [])
        if pm and _role_gte(self.reader_role, 'limited'):
            el.append(Paragraph('Payment Methods', self.styles['SubSection']))
            rows = []
            for p in pm:
                rows.append([
                    p.get('payment_method', '—'),
                    f"{p.get('count', 0):,}",
                    self.fmt.format(p.get('amount', 0)),
                    f"{p.get('percentage', 0):.1f}%",
                ])
            el.append(self._data_table(
                ['Method', 'Transactions', 'Amount', '% of Total'],
                rows,
                [140, 100, 140, 100],
            ))
            el.append(Spacer(1, 10))

        # Top products
        top = self.report_data.get('top_products', [])
        if top and _role_gte(self.reader_role, 'limited'):
            el.append(Paragraph('Top Products by Revenue', self.styles['SubSection']))
            rows = []
            for p in top[:15]:
                rows.append([
                    p.get('product__name', '—')[:35],
                    p.get('product__sku', '—'),
                    f"{p.get('quantity', 0):,}",
                    self.fmt.format(p.get('revenue', 0)),
                ])
            el.append(self._data_table(
                ['Product', 'SKU', 'Qty', 'Revenue'],
                rows,
                [200, 80, 70, 120],
            ))

        return el

    def _build_pl_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        pl = self.report_data.get('profit_loss', {})
        if pl:
            # Structured P&L statement
            el.append(Paragraph('Profit & Loss Statement', self.styles['SubSection']))
            pl_rows = []
            rev = pl.get('revenue', {})
            costs = pl.get('costs', {})
            profit = pl.get('profit', {})

            pl_rows += [
                ['Revenue', '', ''],
                ['  Gross Revenue',
                 self.fmt.format(rev.get('gross_revenue', 0)), ''],
                ['  Less: Discounts',
                 f"({self.fmt.format(rev.get('discounts', 0))})", ''],
                ['Net Revenue',
                 self.fmt.format(rev.get('net_revenue', 0)), ''],
                ['', '', ''],
                ['Costs', '', ''],
                ['  Cost of Goods Sold',
                 f"({self.fmt.format(costs.get('cost_of_goods_sold', 0))})", ''],
                ['  Tax',
                 f"({self.fmt.format(costs.get('tax', 0))})", ''],
                ['Total Costs',
                 f"({self.fmt.format(costs.get('total_costs', 0))})", ''],
                ['', '', ''],
                ['Gross Profit',
                 self.fmt.format(profit.get('gross_profit', 0)),
                 f"{profit.get('gross_margin', 0):.1f}%"],
                ['Net Profit',
                 self.fmt.format(profit.get('net_profit', 0)),
                 f"{profit.get('net_margin', 0):.1f}%"],
            ]

            t = Table(pl_rows, colWidths=[240, 160, 75])
            t.setStyle(TableStyle([
                ('FONTNAME',      (0, 0),  (0, -1),  'Helvetica'),
                ('FONTNAME',      (0, 0),  (0, 0),   'Helvetica-Bold'),
                ('FONTNAME',      (0, 5),  (0, 5),   'Helvetica-Bold'),
                ('FONTNAME',      (0, 10), (0, 10),  'Helvetica-Bold'),
                ('FONTNAME',      (0, 11), (0, 11),  'Helvetica-Bold'),
                ('FONTSIZE',      (0, 0),  (-1, -1), 9),
                ('ALIGN',         (1, 0),  (2, -1),  'RIGHT'),
                ('TOPPADDING',    (0, 0),  (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0),  (-1, -1), 4),
                ('LEFTPADDING',   (0, 0),  (-1, -1), 6),
                ('RIGHTPADDING',  (0, 0),  (-1, -1), 6),
                ('LINEBELOW',     (0, 3),  (-1, 3),  0.5, C.BORDER),
                ('LINEBELOW',     (0, 8),  (-1, 8),  0.5, C.BORDER),
                ('LINEBELOW',     (0, 10), (-1, 10), 1,   C.PRIMARY),
                ('BACKGROUND',    (0, 11), (-1, 11), C.PRIMARY_LIGHT),
            ]))
            el.append(t)
            el.append(Spacer(1, 10))

        # Category profit — manager+ only
        cat = self.report_data.get('category_profit', [])
        if cat and _role_gte(self.reader_role, 'manager'):
            el.append(Paragraph('Profitability by Category', self.styles['SubSection']))
            rows = []
            for c in cat[:20]:
                rows.append([
                    (c.get('category') or 'Uncategorised')[:30],
                    self.fmt.format(c.get('revenue', 0)),
                    self.fmt.format(c.get('cost', 0)),
                    self.fmt.format(c.get('profit', 0)),
                    f"{c.get('margin', 0):.1f}%",
                ])
            el.append(self._data_table(
                ['Category', 'Revenue', 'Cost', 'Profit', 'Margin'],
                rows,
                [150, 100, 100, 100, 70],
            ))

        return el

    def _build_expense_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        summary = self.report_data.get('summary', {})
        if summary:
            el += self._kv_table(summary, 'Expense Summary')
            el.append(Spacer(1, 10))

        tag_breakdown = self.report_data.get('tag_breakdown', [])
        if tag_breakdown and _role_gte(self.reader_role, 'accountant'):
            el.append(Paragraph('Breakdown by Tag / Category', self.styles['SubSection']))
            rows = [[
                t.get('tag_name', '—')[:35],
                f"{t.get('expense_count', 0):,}",
                self.fmt.format(t.get('total_amount', 0)),
                self.fmt.format(t.get('avg_amount', 0)),
            ] for t in tag_breakdown[:20]]
            el.append(self._data_table(
                ['Tag', 'Count', 'Total', 'Average'],
                rows, [200, 70, 130, 120],
            ))
            el.append(Spacer(1, 10))

        budget_analysis = self.report_data.get('budget_analysis', [])
        if budget_analysis and _role_gte(self.reader_role, 'manager'):
            el.append(Paragraph('Budget vs Actual', self.styles['SubSection']))
            rows = []
            for b in budget_analysis[:15]:
                over = '⚠ Over' if b.get('over_budget') else '✓ OK'
                rows.append([
                    b.get('budget_name', '—')[:30],
                    self.fmt.format(b.get('budget_amount', 0)),
                    self.fmt.format(b.get('total_spent', 0)),
                    f"{b.get('budget_utilization', 0):.1f}%",
                    over,
                ])
            el.append(self._data_table(
                ['Budget', 'Budget Amt', 'Spent', 'Utilisation', 'Status'],
                rows, [150, 95, 95, 80, 55],
            ))

        return el

    def _build_inventory_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        summary = self.report_data.get('summary', {})
        if summary:
            el += self._kv_table(summary, 'Inventory Summary')
            el.append(Spacer(1, 10))

        alerts = self.report_data.get('alerts', [])
        if alerts:
            el.append(Paragraph('Reorder Alerts', self.styles['SubSection']))
            rows = [[
                a.get('product__name', '—')[:35],
                a.get('store__name', '—')[:25],
                f"{a.get('quantity', 0):,}",
                f"{a.get('low_stock_threshold', 0):,}",
                'OUT OF STOCK' if a.get('quantity', 0) == 0 else 'LOW STOCK',
            ] for a in alerts[:25]]
            el.append(self._data_table(
                ['Product', 'Store', 'Current Qty', 'Reorder Level', 'Status'],
                rows, [170, 110, 70, 80, 75],
            ))
            el.append(Spacer(1, 10))

        # Category summary — manager+
        cat = self.report_data.get('category_summary', [])
        if cat and _role_gte(self.reader_role, 'manager'):
            el.append(Paragraph('By Category', self.styles['SubSection']))
            rows = [[
                (c.get('product__category__name') or 'Uncategorised')[:35],
                f"{c.get('product_count', 0):,}",
                f"{c.get('total_quantity', 0):,.0f}",
                self.fmt.format(c.get('stock_value', 0)),
            ] for c in cat[:20]]
            el.append(self._data_table(
                ['Category', 'Products', 'Total Qty', 'Stock Value'],
                rows, [185, 80, 90, 120],
            ))

        return el

    def _build_cashier_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        summary = self.report_data.get('summary', {})
        if summary:
            el += self._kv_table(summary, 'Performance Summary')
            el.append(Spacer(1, 10))

        performance = self.report_data.get('performance', [])
        if performance:
            el.append(Paragraph('Cashier Details', self.styles['SubSection']))
            rows = []
            for i, c in enumerate(performance[:30], 1):
                name = (
                    f"{c.get('created_by__first_name', '')} "
                    f"{c.get('created_by__last_name', '')}".strip()
                    or 'Unknown'
                )
                rows.append([
                    str(i),
                    name[:30],
                    f"{c.get('transaction_count', 0):,}",
                    self.fmt.format(c.get('total_sales', 0)),
                    self.fmt.format(c.get('avg_transaction', 0)),
                ])
            el.append(self._data_table(
                ['#', 'Cashier', 'Transactions', 'Total Sales', 'Avg Sale'],
                rows, [30, 150, 80, 130, 110],
            ))

        return el

    def _build_product_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        summary = self.report_data.get('summary', {})
        if summary:
            el += self._kv_table(summary, 'Product Summary')
            el.append(Spacer(1, 10))

        products = self.report_data.get('products', [])
        if products:
            el.append(Paragraph('Product Performance Detail', self.styles['SubSection']))
            rows = []
            for p in products[:50]:
                rows.append([
                    p.get('product__name', '—')[:35],
                    p.get('product__sku', '—'),
                    f"{p.get('total_quantity', 0):,}",
                    self.fmt.format(p.get('total_revenue', 0)),
                    f"{p.get('transaction_count', 0):,}",
                ])
            el.append(self._data_table(
                ['Product', 'SKU', 'Qty Sold', 'Revenue', 'Transactions'],
                rows, [175, 75, 60, 120, 70],
            ))

        return el

    def _build_tax_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        summary = self.report_data.get('summary', {})
        if summary:
            el += self._kv_table(summary, 'Tax Summary')
            el.append(Spacer(1, 10))

        tax_breakdown = self.report_data.get('tax_breakdown', [])
        if tax_breakdown:
            el.append(Paragraph('Tax by Rate Band', self.styles['SubSection']))
            rows = [[
                t.get('tax_rate_display', t.get('tax_rate', '—')),
                self.fmt.format(t.get('total_sales', 0)),
                self.fmt.format(t.get('total_tax', 0)),
                f"{t.get('effective_rate', 0):.2f}%",
                f"{t.get('transaction_count', 0):,}",
            ] for t in tax_breakdown]
            el.append(self._data_table(
                ['Rate Band', 'Taxable Sales', 'Tax Collected', 'Effective Rate', 'Transactions'],
                rows, [110, 110, 110, 90, 80],
            ))
            el.append(Spacer(1, 10))

        efris = self.report_data.get('efris_stats', {})
        if efris and _role_gte(self.reader_role, 'accountant'):
            el += self._kv_table(efris, 'EFRIS Status')

        return el

    def _build_efris_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        compliance = self.report_data.get('compliance', {})
        if compliance:
            el += self._kv_table(compliance, 'Overall Compliance')
            el.append(Spacer(1, 10))

        store_breakdown = self.report_data.get('store_breakdown', [])
        if store_breakdown:
            el.append(Paragraph('By Store', self.styles['SubSection']))
            rows = [[
                s.get('store__name', '—')[:30],
                f"{s.get('total', 0):,}",
                f"{s.get('fiscalized', 0):,}",
                f"{s.get('pending', 0):,}",
                f"{s.get('compliance_rate', 0):.1f}%",
            ] for s in store_breakdown[:20]]
            el.append(self._data_table(
                ['Store', 'Total', 'Fiscalized', 'Pending', 'Rate'],
                rows, [160, 60, 80, 70, 60],
            ))

        return el

    def _build_z_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        summary = self.report_data.get('summary', {})
        if summary:
            # Clean up for display
            display = {k: v for k, v in summary.items()
                       if not isinstance(v, (dict, list))}
            el += self._kv_table(display, 'End of Day Totals')
            el.append(Spacer(1, 10))

        payment_breakdown = self.report_data.get('payment_breakdown', [])
        if payment_breakdown:
            el.append(Paragraph('Payment Breakdown', self.styles['SubSection']))
            rows = [[
                p.get('payment_method', '—'),
                f"{p.get('count', 0):,}",
                self.fmt.format(p.get('amount', 0)),
            ] for p in payment_breakdown]
            el.append(self._data_table(
                ['Method', 'Count', 'Amount'],
                rows, [200, 80, 160],
            ))
            el.append(Spacer(1, 10))

        cashier_perf = self.report_data.get('cashier_performance', [])
        if cashier_perf and _role_gte(self.reader_role, 'manager'):
            el.append(Paragraph('Cashier Performance', self.styles['SubSection']))
            rows = []
            for c in cashier_perf[:15]:
                name = (
                    f"{c.get('created_by__first_name', '')} "
                    f"{c.get('created_by__last_name', '')}".strip()
                    or c.get('created_by__username', 'Unknown')
                )
                rows.append([
                    name[:30],
                    f"{c.get('transaction_count', 0):,}",
                    self.fmt.format(c.get('total_amount', 0)),
                ])
            el.append(self._data_table(
                ['Cashier', 'Transactions', 'Total'],
                rows, [220, 100, 160],
            ))

        return el

    def _build_stock_movement_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        summary = self.report_data.get('summary', [])
        if summary and isinstance(summary, list):
            el.append(Paragraph('Movement by Type', self.styles['SubSection']))
            rows = [[
                s.get('movement_type', '—'),
                f"{s.get('movement_count', 0):,}",
                f"{s.get('total_quantity', 0):,.0f}",
            ] for s in summary]
            el.append(self._data_table(
                ['Type', 'Count', 'Total Qty'],
                rows, [200, 100, 150],
            ))
            el.append(Spacer(1, 10))

        movements = self.report_data.get('movements', [])
        if movements and _role_gte(self.reader_role, 'manager'):
            el.append(Paragraph('Movement Detail (latest 50)', self.styles['SubSection']))
            rows = [[
                m.get('product_name', '—')[:30],
                m.get('store_name', '—')[:20],
                m.get('movement_type', '—'),
                f"{m.get('quantity', 0):,}",
                str(m.get('created_at', ''))[:10],
            ] for m in movements[:50]]
            el.append(self._data_table(
                ['Product', 'Store', 'Type', 'Qty', 'Date'],
                rows, [150, 100, 80, 60, 80],
            ))

        return el

    def _build_customer_tables(self) -> List:
        el = []
        el.append(self._section_divider())

        summary = self.report_data.get('summary', {})
        if summary:
            el += self._kv_table(summary, 'Customer Summary')
            el.append(Spacer(1, 10))

        customers = self.report_data.get('customers', [])
        if customers and _role_gte(self.reader_role, 'manager'):
            el.append(Paragraph('Top Customers', self.styles['SubSection']))
            rows = [[
                c.get('customer__name', '—')[:35],
                f"{c.get('total_purchases', 0):,}",
                self.fmt.format(c.get('total_spent', 0)),
                self.fmt.format(c.get('avg_purchase', 0)),
            ] for c in customers[:25]]
            el.append(self._data_table(
                ['Customer', 'Purchases', 'Total Spent', 'Avg Purchase'],
                rows, [175, 70, 130, 110],
            ))

        return el

    # ── Combined report ───────────────────────────────────────────────────────

    def _is_combined(self) -> bool:
        combined_keys = [
            'SALES_SUMMARY', 'PROFIT_LOSS', 'EXPENSE_REPORT',
            'INVENTORY_STATUS', 'EXPENSE_ANALYTICS', 'Z_REPORT',
            'CASHIER_PERFORMANCE', 'STOCK_MOVEMENT', 'CUSTOMER_ANALYTICS',
            'business_health', 'custom_analytics',
        ]
        return any(k in self.report_data for k in combined_keys)

    def _build_combined(self) -> List:
        el = []

        el.append(Paragraph('Table of Contents', self.styles['SectionHeader']))
        toc_map = [
            ('business_health',     '1. Business Health Score'),
            ('custom_analytics',    '2. Executive Summary'),
            ('SALES_SUMMARY',       '3. Sales Performance'),
            ('PROFIT_LOSS',         '4. Profit & Loss'),
            ('EXPENSE_REPORT',      '5. Expense Analysis'),
            ('INVENTORY_STATUS',    '6. Inventory Management'),
            ('Z_REPORT',            '7. Daily Operations (Z-Report)'),
            ('CASHIER_PERFORMANCE', '8. Staff Performance'),
            ('PRODUCT_PERFORMANCE', '9. Product Performance'),
            ('STOCK_MOVEMENT',      '10. Stock Movement'),
            ('CUSTOMER_ANALYTICS',  '11. Customer Insights'),
            ('EFRIS_COMPLIANCE',    '12. EFRIS Compliance'),
        ]
        for key, label in toc_map:
            if key in self.report_data:
                el.append(Paragraph(label, self.styles['TOCItem']))
        el.append(Spacer(1, 20))
        el.append(self._section_divider())

        # Business health
        if 'business_health' in self.report_data:
            el.append(PageBreak())
            el.extend(self._combined_health_section())

        # Executive summary
        if 'custom_analytics' in self.report_data:
            el.append(PageBreak())
            el.extend(self._combined_exec_summary())

        # Sub-report sections
        sub_map = [
            ('SALES_SUMMARY',       '3. Sales Performance',
             self._build_sales_tables),
            ('PROFIT_LOSS',         '4. Profit & Loss',
             self._build_pl_tables),
            ('EXPENSE_REPORT',      '5. Expense Analysis',
             self._build_expense_tables),
            ('INVENTORY_STATUS',    '6. Inventory Management',
             self._build_inventory_tables),
            ('Z_REPORT',            '7. Daily Operations (Z-Report)',
             self._build_z_tables),
            ('CASHIER_PERFORMANCE', '8. Staff Performance',
             self._build_cashier_tables),
            ('PRODUCT_PERFORMANCE', '9. Product Performance',
             self._build_product_tables),
            ('STOCK_MOVEMENT',      '10. Stock Movement',
             self._build_stock_movement_tables),
            ('CUSTOMER_ANALYTICS',  '11. Customer Insights',
             self._build_customer_tables),
            ('EFRIS_COMPLIANCE',    '12. EFRIS Compliance',
             self._build_efris_tables),
        ]

        for key, heading, table_builder in sub_map:
            if key not in self.report_data:
                continue
            el.append(PageBreak())
            el.append(Paragraph(heading, self.styles['SectionHeader']))

            # Render narrative blocks for this sub-report type
            sub_data = self.report_data[key]
            # Temporarily swap report_data so table builders work
            saved = self.report_data
            self.report_data = sub_data
            el.extend(table_builder())
            self.report_data = saved

        return el

    def _combined_health_section(self) -> List:
        el = []
        el.append(Paragraph('1. Business Health Score', self.styles['SectionHeader']))
        h = self.report_data['business_health']
        el.append(Paragraph(
            f"{h['score']} / {h['max_score']} ({h['percentage']:.1f}%)",
            self.styles['HealthScore']
        ))
        el.append(Paragraph(f"Grade: {h['grade']}", self.styles['HealthGrade']))
        el.append(Spacer(1, 10))

        rows = [[f.get('factor', f[0]) if isinstance(f, (list, tuple)) else str(f),
                 str(s)] for f, s in (h.get('factors') or [])]
        if rows:
            t = Table(rows, colWidths=[self.doc_width * 0.8, self.doc_width * 0.2])
            t.setStyle(TableStyle([
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('LINEBELOW', (0, 0), (-1, -2), 0.3, C.BORDER),
            ]))
            el.append(t)
        return el

    def _combined_exec_summary(self) -> List:
        el = []
        el.append(Paragraph('2. Executive Summary', self.styles['SectionHeader']))
        analytics = self.report_data.get('custom_analytics', {})
        metrics   = analytics.get('key_metrics', {})

        kv = {}
        if 'cash_flow' in metrics:
            kv['Cash Flow'] = self.fmt.format(metrics['cash_flow'])
        if 'profitability' in metrics:
            p = metrics['profitability']
            kv['Net Profit'] = self.fmt.format(p.get('net_profit', 0))
            kv['Net Margin']  = f"{p.get('net_margin', 0):.1f}%"
        if 'expense_to_sales_ratio' in metrics:
            kv['Expense / Sales Ratio'] = f"{metrics['expense_to_sales_ratio']:.1f}%"
        if kv:
            rows = [[k, v] for k, v in kv.items()]
            t = Table(rows, colWidths=[self.doc_width * 0.6, self.doc_width * 0.4])
            t.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
                ('LEFTPADDING', (0, 0), (-1, -1), 6),
                ('LINEBELOW', (0, 0), (-1, -2), 0.3, C.BORDER),
            ]))
            el.append(t)
            el.append(Spacer(1, 10))

        recs = analytics.get('recommendations', [])
        if recs and _role_gte(self.reader_role, 'manager'):
            el.append(Paragraph('Recommendations', self.styles['SubSection']))
            for r in recs:
                el.append(Paragraph(f'• {r}', self.styles['Normal']))

        return el

    # ── Report footer ─────────────────────────────────────────────────────────

    def _build_report_footer(self) -> List:
        el = []
        el.append(Spacer(1, 24))
        el.append(HRFlowable(width='100%', thickness=1, color=C.BORDER))
        el.append(Spacer(1, 6))
        el.append(Paragraph('END OF REPORT', self.styles['Footer']))
        el.append(Paragraph(
            'Confidential — for authorised use only.',
            self.styles['Small'],
        ))
        return el