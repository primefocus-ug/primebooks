"""
PrimeBooks — Professional PDF Exporter
=======================================
Converts a GeneralTracker JSON payload into a polished A4 PDF report.

Usage (in a Django view):
    from accounts.pdf_exporter import build_report_pdf

    pdf_bytes = build_report_pdf(data, report_type="sale", date_from="2025-01-01", date_to="2025-01-31")
    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    response["Content-Disposition"] = 'attachment; filename="report.pdf"'
    return response

Or add a PDF endpoint in urls.py and call it from the frontend.

Wire up (urls.py):
    from accounts.pdf_exporter import ReportPDFView
    path("api/report/pdf/", ReportPDFView.as_view(), name="report-pdf"),
"""

import io
import logging
from datetime import datetime

from django.http import HttpResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)
from reportlab.platypus.flowables import KeepTogether

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════
#  BRAND PALETTE
# ══════════════════════════════════════════════════════
C_PRIMARY   = colors.HexColor("#1e3a5f")   # deep navy  — header bar, accents
C_ACCENT    = colors.HexColor("#c94f2a")   # rust red   — section dots, highlights
C_TEAL      = colors.HexColor("#2a7a6f")   # teal       — positive values
C_GOLD      = colors.HexColor("#d4943a")   # gold       — warnings
C_PURPLE    = colors.HexColor("#5e4ba3")   # purple     — misc
C_BLUE      = colors.HexColor("#2563c4")   # blue       — info
C_DANGER    = colors.HexColor("#b83232")   # red        — negative/error
C_HEADER_BG = colors.HexColor("#1e3a5f")
C_ROW_ODD   = colors.HexColor("#f7f8fa")
C_ROW_EVEN  = colors.white
C_TH_BG     = colors.HexColor("#e8ecf2")
C_BORDER    = colors.HexColor("#d0d7e3")
C_MUTED     = colors.HexColor("#6b7280")
C_TEXT      = colors.HexColor("#1a1f2e")
C_STAT_BG   = colors.HexColor("#f0f4ff")

# Map API badge_color → ReportLab color
COLOR_MAP = {
    "green":  C_TEAL,
    "teal":   C_TEAL,
    "blue":   C_BLUE,
    "yellow": C_GOLD,
    "red":    C_DANGER,
    "purple": C_PURPLE,
    "dim":    C_MUTED,
}

PAGE_W, PAGE_H = A4
MARGIN_L = MARGIN_R = 18 * mm
MARGIN_T = 14 * mm
MARGIN_B = 16 * mm


# ══════════════════════════════════════════════════════
#  STYLES
# ══════════════════════════════════════════════════════
def _styles():
    base = getSampleStyleSheet()
    def s(name, **kw):
        return ParagraphStyle(name, **kw)

    return {
        "report_title": s("report_title",
            fontName="Helvetica-Bold", fontSize=18,
            textColor=colors.white, leading=22, alignment=TA_LEFT),
        "report_sub": s("report_sub",
            fontName="Helvetica", fontSize=9,
            textColor=colors.HexColor("#c8d8f0"), leading=12, alignment=TA_LEFT),
        "section_title": s("section_title",
            fontName="Helvetica-Bold", fontSize=10,
            textColor=C_PRIMARY, leading=13, spaceBefore=6),
        "stat_label": s("stat_label",
            fontName="Helvetica", fontSize=8,
            textColor=C_MUTED, leading=10, alignment=TA_CENTER),
        "stat_value": s("stat_value",
            fontName="Helvetica-Bold", fontSize=14,
            textColor=C_PRIMARY, leading=17, alignment=TA_CENTER),
        "th": s("th",
            fontName="Helvetica-Bold", fontSize=8,
            textColor=C_PRIMARY, leading=10, alignment=TA_LEFT),
        "td": s("td",
            fontName="Helvetica", fontSize=8,
            textColor=C_TEXT, leading=10, alignment=TA_LEFT),
        "td_right": s("td_right",
            fontName="Helvetica", fontSize=8,
            textColor=C_TEXT, leading=10, alignment=TA_RIGHT),
        "td_bold": s("td_bold",
            fontName="Helvetica-Bold", fontSize=8,
            textColor=C_TEAL, leading=10, alignment=TA_RIGHT),
        "note": s("note",
            fontName="Helvetica-Oblique", fontSize=8.5,
            textColor=C_TEXT, leading=12, leftIndent=8),
        "kv_label": s("kv_label",
            fontName="Helvetica", fontSize=7.5,
            textColor=C_MUTED, leading=9),
        "kv_value": s("kv_value",
            fontName="Helvetica-Bold", fontSize=9.5,
            textColor=C_TEXT, leading=12),
        "tl_label": s("tl_label",
            fontName="Helvetica-Bold", fontSize=8.5,
            textColor=C_TEXT, leading=11),
        "tl_meta": s("tl_meta",
            fontName="Helvetica", fontSize=7.5,
            textColor=C_MUTED, leading=10),
        "footer": s("footer",
            fontName="Helvetica", fontSize=7,
            textColor=C_MUTED, alignment=TA_CENTER),
        "body": s("body",
            fontName="Helvetica", fontSize=9,
            textColor=C_TEXT, leading=13),
    }


# ══════════════════════════════════════════════════════
#  PAGE TEMPLATES  (header + footer drawn on canvas)
# ══════════════════════════════════════════════════════
class _PrimeDoc(BaseDocTemplate):
    """Custom doc with cover page + inner pages."""

    def __init__(self, buf, title, subtitle, generated, report_type, note=""):
        super().__init__(buf, pagesize=A4,
                         leftMargin=MARGIN_L, rightMargin=MARGIN_R,
                         topMargin=MARGIN_T, bottomMargin=MARGIN_B)
        self.title_text    = title
        self.subtitle_text = subtitle
        self.generated     = generated
        self.report_type   = report_type.upper()
        self.note          = note
        self._build_templates()

    def _build_templates(self):
        w = PAGE_W - MARGIN_L - MARGIN_R

        # Cover page — full-height frame below the big header band
        cover_frame = Frame(MARGIN_L, MARGIN_B + 10*mm,
                            w, PAGE_H - MARGIN_B - 70*mm - 10*mm,
                            id="cover")

        # Inner pages — shorter top margin (header band is only 14 mm)
        inner_frame = Frame(MARGIN_L, MARGIN_B + 8*mm,
                            w, PAGE_H - MARGIN_B - 22*mm - 8*mm,
                            id="inner")

        self.addPageTemplates([
            PageTemplate(id="Cover", frames=[cover_frame],
                         onPage=self._cover_page),
            PageTemplate(id="Inner", frames=[inner_frame],
                         onPage=self._inner_page),
        ])

    # ── Cover page canvas ──
    def _cover_page(self, canvas, doc):
        canvas.saveState()
        w, h = PAGE_W, PAGE_H

        # Full-width navy header band
        canvas.setFillColor(C_HEADER_BG)
        canvas.rect(0, h - 58*mm, w, 58*mm, fill=1, stroke=0)

        # Accent stripe at very top
        canvas.setFillColor(C_ACCENT)
        canvas.rect(0, h - 3.5*mm, w, 3.5*mm, fill=1, stroke=0)

        # Left colour sidebar
        canvas.setFillColor(colors.HexColor("#16304f"))
        canvas.rect(0, h - 58*mm, 6*mm, 58*mm, fill=1, stroke=0)

        # Company / app name
        canvas.setFont("Helvetica-Bold", 11)
        canvas.setFillColor(colors.HexColor("#c8d8f0"))
        canvas.drawString(MARGIN_L, h - 14*mm, "PRIMEBOOKS")

        # Report type pill
        pill_x = MARGIN_L
        pill_y = h - 24*mm
        pill_w = len(self.report_type) * 6.5 + 14
        canvas.setFillColor(C_ACCENT)
        canvas.roundRect(pill_x, pill_y, pill_w, 10*mm, 3*mm, fill=1, stroke=0)
        canvas.setFont("Helvetica-Bold", 9)
        canvas.setFillColor(colors.white)
        canvas.drawString(pill_x + 7, pill_y + 3.5*mm, self.report_type)

        # Report title
        canvas.setFont("Helvetica-Bold", 20)
        canvas.setFillColor(colors.white)
        canvas.drawString(MARGIN_L, h - 40*mm, self.title_text)

        # Sub-title (date range)
        canvas.setFont("Helvetica", 9)
        canvas.setFillColor(colors.HexColor("#c8d8f0"))
        canvas.drawString(MARGIN_L, h - 49*mm, self.subtitle_text)

        # Generated line (right-aligned)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#8aa4c8"))
        canvas.drawRightString(w - MARGIN_R, h - 49*mm, f"Generated: {self.generated}")

        # Bottom footer bar
        canvas.setFillColor(C_HEADER_BG)
        canvas.rect(0, 0, w, 10*mm, fill=1, stroke=0)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#8aa4c8"))
        canvas.drawCentredString(w / 2, 3.5*mm,
            "PrimeBooks  ·  Confidential Business Report  ·  Page 1")

        canvas.restoreState()

    # ── Inner page canvas ──
    def _inner_page(self, canvas, doc):
        canvas.saveState()
        w, h = PAGE_W, PAGE_H
        page = doc.page

        # Thin header band
        canvas.setFillColor(C_HEADER_BG)
        canvas.rect(0, h - 14*mm, w, 14*mm, fill=1, stroke=0)

        # Accent top stripe
        canvas.setFillColor(C_ACCENT)
        canvas.rect(0, h - 2.5*mm, w, 2.5*mm, fill=1, stroke=0)

        # Header text
        canvas.setFont("Helvetica-Bold", 8.5)
        canvas.setFillColor(colors.white)
        canvas.drawString(MARGIN_L, h - 9*mm, "PRIMEBOOKS")

        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#c8d8f0"))
        canvas.drawString(MARGIN_L + 57, h - 9*mm, f"  ·  {self.title_text}")
        canvas.drawRightString(w - MARGIN_R, h - 9*mm, self.subtitle_text)

        # Bottom footer
        canvas.setFillColor(colors.HexColor("#f0f2f5"))
        canvas.rect(0, 0, w, 9*mm, fill=1, stroke=0)

        # Footer separator line
        canvas.setStrokeColor(C_BORDER)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_L, 9*mm, w - MARGIN_R, 9*mm)

        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(C_MUTED)
        canvas.drawString(MARGIN_L, 3.5*mm, "Confidential · PrimeBooks")
        canvas.drawCentredString(w / 2, 3.5*mm, self.generated)
        canvas.drawRightString(w - MARGIN_R, 3.5*mm, f"Page {page}")

        canvas.restoreState()


# ══════════════════════════════════════════════════════
#  SECTION BUILDERS
# ══════════════════════════════════════════════════════
def _section_heading(title, st):
    """Rust dot + bold section title + rule."""
    return KeepTogether([
        Spacer(1, 5*mm),
        Table(
            [[Paragraph(f'<font color="#{C_ACCENT.hexval()[2:]}">●</font>  {title}',
                        st["section_title"])]],
            colWidths=[PAGE_W - MARGIN_L - MARGIN_R],
            style=TableStyle([
                ("LINEBELOW", (0,0), (-1,-1), 0.6, C_ACCENT),
                ("BOTTOMPADDING", (0,0), (-1,-1), 3),
                ("TOPPADDING", (0,0), (-1,-1), 0),
            ])
        ),
        Spacer(1, 3*mm),
    ])


def _build_stats(stats, st):
    """Stat cards row — up to 4 per row."""
    if not stats:
        return []
    chunks = [stats[i:i+4] for i in range(0, len(stats), 4)]
    flowables = []
    col_w = (PAGE_W - MARGIN_L - MARGIN_R) / 4

    for chunk in chunks:
        # Pad to 4 columns so grid is even
        while len(chunk) < 4:
            chunk = chunk + [None]

        cells = []
        for stat in chunk:
            if stat is None:
                cells.append([""])
                continue
            c = COLOR_MAP.get(stat.get("color", ""), C_TEAL)
            cells.append([
                Paragraph(stat.get("label", ""), st["stat_label"]),
                Paragraph(f'<font color="#{c.hexval()[2:]}">{stat.get("value","—")}</font>',
                          st["stat_value"]),
            ])

        # Two-row table: labels top, values bottom
        label_row = [cell[0] if len(cell) > 1 else cell[0] for cell in cells]
        value_row = [cell[1] if len(cell) > 1 else "" for cell in cells]

        tbl = Table(
            [label_row, value_row],
            colWidths=[col_w] * 4,
            rowHeights=[9*mm, 14*mm],
            style=TableStyle([
                ("BACKGROUND",    (0,0), (-1,-1), C_STAT_BG),
                ("ROUNDEDCORNERS",(0,0), (-1,-1), 4),
                ("BOX",           (0,0), (-1,-1), 0.5, C_BORDER),
                ("INNERGRID",     (0,0), (-1,-1), 0.4, C_BORDER),
                ("ALIGN",         (0,0), (-1,-1), "CENTER"),
                ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
                ("TOPPADDING",    (0,0), (-1,-1), 3),
                ("BOTTOMPADDING", (0,0), (-1,-1), 3),
                ("LEFTPADDING",   (0,0), (-1,-1), 4),
                ("RIGHTPADDING",  (0,0), (-1,-1), 4),
            ])
        )
        flowables.append(tbl)
        flowables.append(Spacer(1, 4*mm))

    return flowables


def _build_table_section(sec, st):
    """Render a 'table' or 'lineitems' section."""
    cols = sec.get("columns", [])
    rows = sec.get("rows", [])
    if not cols:
        return []

    n = len(cols)
    total_w = PAGE_W - MARGIN_L - MARGIN_R

    # Heuristic: last column is usually a currency/amount — give it extra width
    base_w = total_w / n
    col_widths = [base_w] * n
    if n > 1:
        col_widths[-1] = base_w * 1.3
        remaining = total_w - col_widths[-1]
        for i in range(n - 1):
            col_widths[i] = remaining / (n - 1)

    header = [Paragraph(c, st["th"]) for c in cols]
    data_rows = []
    for row in rows:
        r = []
        for i, cell in enumerate(row):
            val = str(cell) if cell is not None else "—"
            # Last column is numeric/currency — right-align and bold
            if i == len(row) - 1:
                r.append(Paragraph(val, st["td_bold"]))
            else:
                r.append(Paragraph(val, st["td"]))
        data_rows.append(r)

    if not data_rows:
        data_rows = [[Paragraph("No data available", st["td"])] + [""] * (n - 1)]

    table_data = [header] + data_rows

    row_styles = []
    for i, _ in enumerate(data_rows, start=1):
        bg = C_ROW_ODD if i % 2 == 0 else C_ROW_EVEN
        row_styles.append(("BACKGROUND", (0, i), (-1, i), bg))

    tbl = Table(
        table_data,
        colWidths=col_widths,
        repeatRows=1,
        style=TableStyle([
            # Header
            ("BACKGROUND",    (0,0), (-1,0), C_TH_BG),
            ("LINEBELOW",     (0,0), (-1,0), 1.2, C_PRIMARY),
            ("TOPPADDING",    (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
            ("LEFTPADDING",   (0,0), (-1,-1), 6),
            ("RIGHTPADDING",  (0,0), (-1,-1), 6),
            ("VALIGN",        (0,0), (-1,-1), "MIDDLE"),
            # Row grid
            ("LINEBELOW",     (0,1), (-1,-1), 0.4, C_BORDER),
            ("BOX",           (0,0), (-1,-1), 0.5, C_BORDER),
        ] + row_styles)
    )
    return [tbl, Spacer(1, 3*mm)]


def _build_kv_section(sec, st):
    """Render a 'keyvalue' section as a 2-column grid."""
    pairs = sec.get("pairs", [])
    if not pairs:
        return []

    col_w = (PAGE_W - MARGIN_L - MARGIN_R) / 2
    rows = []
    for i in range(0, len(pairs), 2):
        row = []
        for pair in pairs[i:i+2]:
            row.append(
                Table([[Paragraph(pair.get("label",""), st["kv_label"])],
                        [Paragraph(str(pair.get("value","—")), st["kv_value"])]],
                      colWidths=[col_w - 8],
                      style=TableStyle([
                          ("BACKGROUND",    (0,0), (-1,-1), C_STAT_BG),
                          ("BOX",           (0,0), (-1,-1), 0.4, C_BORDER),
                          ("TOPPADDING",    (0,0), (-1,-1), 5),
                          ("BOTTOMPADDING", (0,0), (-1,-1), 5),
                          ("LEFTPADDING",   (0,0), (-1,-1), 7),
                          ("RIGHTPADDING",  (0,0), (-1,-1), 7),
                      ]))
            )
        while len(row) < 2:
            row.append("")
        rows.append(row)

    tbl = Table(rows, colWidths=[col_w, col_w],
                style=TableStyle([
                    ("VALIGN",        (0,0), (-1,-1), "TOP"),
                    ("LEFTPADDING",   (0,0), (-1,-1), 0),
                    ("RIGHTPADDING",  (0,0), (-1,-1), 4),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 4),
                ]))
    return [tbl, Spacer(1, 3*mm)]


SEV_COLORS = {
    "success": C_TEAL,
    "error":   C_DANGER,
    "warning": C_GOLD,
    "info":    C_BLUE,
    "purple":  C_PURPLE,
}
SEV_BULLET = {
    "success": "✓", "error": "✗", "warning": "!", "info": "i", "purple": "★",
}


def _build_timeline_section(sec, st):
    """Render timeline / audit items as a compact table."""
    items = sec.get("items", [])
    if not items:
        return []

    total_w = PAGE_W - MARGIN_L - MARGIN_R
    rows = []
    for item in items:
        sev  = item.get("severity", "info")
        c    = SEV_COLORS.get(sev, C_BLUE)
        bul  = SEV_BULLET.get(sev, "•")
        desc = item.get("description") or item.get("label") or "—"
        user = item.get("user", "")
        date_raw = item.get("date", "")
        date_str = ""
        if date_raw:
            try:
                dt = datetime.fromisoformat(date_raw.replace("Z",""))
                date_str = dt.strftime("%d %b %Y %H:%M")
            except Exception:
                date_str = str(date_raw)[:16]

        sub  = item.get("sub") or item.get("note") or ""
        full = desc + (f"\n{sub}" if sub else "")

        rows.append([
            Paragraph(f'<font color="#{c.hexval()[2:]}">{bul}</font>', st["tl_label"]),
            Paragraph(full, st["tl_meta"]),
            Paragraph(user, st["tl_meta"]),
            Paragraph(date_str, st["tl_meta"]),
        ])

    tbl = Table(
        rows,
        colWidths=[8*mm, total_w - 8*mm - 30*mm - 42*mm, 30*mm, 42*mm],
        style=TableStyle([
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("ALIGN",         (0,0), (0,-1),  "CENTER"),
            ("TOPPADDING",    (0,0), (-1,-1), 4),
            ("BOTTOMPADDING", (0,0), (-1,-1), 4),
            ("LEFTPADDING",   (0,0), (-1,-1), 4),
            ("RIGHTPADDING",  (0,0), (-1,-1), 4),
            ("LINEBELOW",     (0,0), (-1,-2), 0.3, C_BORDER),
        ] + [
            ("BACKGROUND", (0,i), (-1,i), C_ROW_ODD if i%2==0 else C_ROW_EVEN)
            for i in range(len(rows))
        ])
    )
    return [tbl, Spacer(1, 3*mm)]


def _build_section(sec, st):
    """Dispatch to the correct renderer based on sec['type']."""
    stype = sec.get("type", "")
    title = sec.get("title", "Section")
    flowables = [_section_heading(title, st)]

    if stype in ("table", "lineitems"):
        flowables += _build_table_section(sec, st)
    elif stype == "keyvalue":
        flowables += _build_kv_section(sec, st)
    elif stype in ("timeline", "audit"):
        flowables += _build_timeline_section(sec, st)

    return flowables


# ══════════════════════════════════════════════════════
#  PUBLIC API
# ══════════════════════════════════════════════════════
def build_report_pdf(data: dict, report_type: str = "report",
                     date_from: str = "", date_to: str = "",
                     note: str = "") -> bytes:
    """
    Convert a GeneralTracker JSON payload to professional PDF bytes.

    Parameters
    ----------
    data        : dict   — the JSON returned by GeneralTrackerView
    report_type : str    — 'sale' | 'product' | 'customer' | 'expense' | 'budget' | 'user'
    date_from   : str    — YYYY-MM-DD
    date_to     : str    — YYYY-MM-DD
    note        : str    — optional analyst note appended to cover page

    Returns
    -------
    bytes — raw PDF content, ready for HttpResponse
    """
    buf       = io.BytesIO()
    title     = data.get("title", f"{report_type.capitalize()} Report")
    generated = datetime.now().strftime("%d %b %Y, %H:%M")

    def _fmt(d):
        try:
            return datetime.strptime(d, "%Y-%m-%d").strftime("%d %b %Y")
        except Exception:
            return d or "—"

    subtitle = f"{_fmt(date_from)}  –  {_fmt(date_to)}"

    st  = _styles()
    doc = _PrimeDoc(buf, title=title, subtitle=subtitle,
                    generated=generated, report_type=report_type, note=note)

    story = [NextPageTemplate("Cover")]

    # ── Cover page summary stats ──────────────────────────
    story.append(Spacer(1, 6*mm))
    story += _build_stats(data.get("stats", []), st)

    if note:
        story.append(Spacer(1, 4*mm))
        story.append(Table(
            [[Paragraph(f"<b>Analyst Note:</b> {note}", st["note"])]],
            colWidths=[PAGE_W - MARGIN_L - MARGIN_R],
            style=TableStyle([
                ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#fffbf0")),
                ("BOX",           (0,0), (-1,-1), 0.5, C_GOLD),
                ("LINEAFTER",     (0,0), (0,-1),  3, C_GOLD),
                ("TOPPADDING",    (0,0), (-1,-1), 6),
                ("BOTTOMPADDING", (0,0), (-1,-1), 6),
                ("LEFTPADDING",   (0,0), (-1,-1), 10),
            ])
        ))

    # ── Switch to inner template for sections ─────────────
    story.append(NextPageTemplate("Inner"))
    story.append(PageBreak())

    for sec in data.get("sections", []):
        story += _build_section(sec, st)

    doc.build(story)
    return buf.getvalue()


# ══════════════════════════════════════════════════════
#  DJANGO VIEW
# ══════════════════════════════════════════════════════
class ReportPDFView(LoginRequiredMixin, View):
    """
    GET /api/report/pdf/
        ?type=sale
        &date_from=2025-01-01
        &date_to=2025-01-31
        [&store_id=3]
        [&sections=summary,top_products]
        [&note=Reviewed+by+Finance]

    Internally calls GeneralTrackerView logic then streams a PDF.
    """

    def get(self, request):
        from accounts.general_tracker import (
            REPORT_REGISTRY, GeneralTrackerView, parse_date
        )

        rtype     = request.GET.get("type",      "").strip().lower()
        date_from = request.GET.get("date_from", "").strip()
        date_to   = request.GET.get("date_to",   "").strip()
        store_id  = request.GET.get("store_id",  "").strip() or None
        sections  = request.GET.get("sections",  "").strip() or None
        note      = request.GET.get("note",      "").strip()

        if not rtype or rtype not in REPORT_REGISTRY:
            from django.http import JsonResponse
            return JsonResponse({"error": f"Unknown type '{rtype}'."}, status=400)

        d_from = parse_date(date_from)
        d_to   = parse_date(date_to)
        if not d_from or not d_to:
            from django.http import JsonResponse
            return JsonResponse({"error": "date_from and date_to required (YYYY-MM-DD)."}, status=400)

        section_filter = [s.strip() for s in sections.split(",")] if sections else None
        store_id_int   = int(store_id) if store_id and store_id.isdigit() else None

        try:
            data = REPORT_REGISTRY[rtype].build(
                user           = request.user,
                date_from      = d_from,
                date_to        = d_to,
                store_id       = store_id_int,
                section_filter = section_filter,
            )
        except Exception:
            logger.exception("PDF build error type=%s from=%s to=%s", rtype, date_from, date_to)
            from django.http import JsonResponse
            return JsonResponse({"error": "Internal error building report."}, status=500)

        pdf_bytes = build_report_pdf(
            data        = data,
            report_type = rtype,
            date_from   = date_from,
            date_to     = date_to,
            note        = note,
        )

        filename = f"primebooks-{rtype}-{date_from}-{date_to}.pdf"
        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response
