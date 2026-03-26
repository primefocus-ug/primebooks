# inventory/views/label_pdf_view.py
"""
PDF barcode label sheet generator.

GET /inventory/labels/print/?ids=1,2,3&mark_printed=1

Generates an A4 PDF with barcode labels arranged in a grid.
Supports small, medium, and large label sizes.

Requirements:
    pip install reportlab python-barcode[images] Pillow
"""

import io
import logging
from django.http import HttpResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET

logger = logging.getLogger(__name__)

# Label size definitions (width_mm, height_mm)
LABEL_SIZES = {
    'small':  (38, 19),
    'medium': (57, 32),
    'large':  (100, 50),
}

# A4 dimensions in mm
A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297
MARGIN_MM = 10
GUTTER_MM = 3


def mm_to_points(mm):
    """Convert millimetres to PDF points (1pt = 0.352778mm)."""
    return mm * 2.834645669


@login_required
@require_GET
def label_pdf_view(request):
    """
    Generate a PDF sheet of barcode labels.

    Query params:
        ids         — comma-separated BarcodeLabel PKs (required)
        mark_printed — set to '1' to mark labels as printed after generation
    """
    from inventory.models import BarcodeLabel

    # Permission check
    user = request.user
    groups = set(user.groups.values_list('name', flat=True))
    if not user.is_superuser and not groups & {'admin', 'stock_manager', 'manager'}:
        return HttpResponseForbidden("You don't have permission to print labels.")

    # Parse label IDs
    ids_param = request.GET.get('ids', '')
    try:
        label_ids = [int(x) for x in ids_param.split(',') if x.strip().isdigit()]
    except Exception:
        label_ids = []

    if not label_ids:
        return HttpResponse("No label IDs provided. Use ?ids=1,2,3", status=400)

    labels = BarcodeLabel.objects.filter(
        pk__in=label_ids, status='pending'
    ).select_related('product', 'store').order_by('pk')

    if not labels.exists():
        return HttpResponse("No pending labels found for provided IDs.", status=404)

    # Generate PDF
    try:
        pdf_buffer = _generate_pdf(labels)
    except Exception as e:
        logger.error(f"Label PDF generation failed: {e}", exc_info=True)
        return HttpResponse(f"PDF generation error: {e}", status=500)

    # Mark as printed if requested
    if request.GET.get('mark_printed') == '1':
        for label in labels:
            label.mark_printed(user)

    response = HttpResponse(pdf_buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="barcode_labels.pdf"'
    return response


def _generate_pdf(labels):
    """
    Build and return an A4 PDF with labels arranged in columns.

    Each BarcodeLabel row may have quantity > 1, so we expand them.
    """
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    import barcode as bc
    from barcode.writer import ImageWriter
    from PIL import Image

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    page_w, page_h = A4  # points

    # Expand labels to individual stickers
    stickers = []
    for label in labels:
        for _ in range(label.quantity):
            stickers.append(label)

    # Group stickers by label size (all stickers in a job share the same size)
    # For simplicity: process all stickers sequentially, changing grid per size.
    # In production you'd sort by size or render separate sections.

    # Use the most common size for page layout (or default to medium)
    from collections import Counter
    size_counter = Counter(lb.label_size for lb in labels)
    dominant_size = size_counter.most_common(1)[0][0]
    label_w_mm, label_h_mm = LABEL_SIZES.get(dominant_size, LABEL_SIZES['medium'])

    label_w = label_w_mm * mm
    label_h = label_h_mm * mm
    margin = MARGIN_MM * mm
    gutter = GUTTER_MM * mm

    cols = int((page_w - 2 * margin + gutter) / (label_w + gutter))
    rows = int((page_h - 2 * margin + gutter) / (label_h + gutter))
    per_page = cols * rows

    sticker_idx = 0
    while sticker_idx < len(stickers):
        # New page
        row_idx = 0
        col_idx = 0

        for _ in range(per_page):
            if sticker_idx >= len(stickers):
                break

            label = stickers[sticker_idx]
            product = label.product

            # Top-left corner of this sticker (PDF coords: y=0 at bottom)
            x = margin + col_idx * (label_w + gutter)
            y = page_h - margin - (row_idx + 1) * label_h - row_idx * gutter

            _draw_label(
                canvas=c,
                product=product,
                label=label,
                x=x, y=y,
                w=label_w, h=label_h,
            )

            col_idx += 1
            if col_idx >= cols:
                col_idx = 0
                row_idx += 1

            sticker_idx += 1

        c.showPage()

    c.save()
    buffer.seek(0)
    return buffer


def _draw_label(canvas, product, label, x, y, w, h):
    """
    Draw a single barcode label at position (x, y) with size (w, h).

    Layout (top to bottom):
      - Product name (truncated)
      - Barcode image
      - Barcode value text
      - Price (if include_price)
    """
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    import barcode as bc
    from barcode.writer import ImageWriter
    import io as _io

    c = canvas

    # Border
    c.setStrokeColor(colors.lightgrey)
    c.setLineWidth(0.3)
    c.rect(x, y, w, h)

    padding = 1.5 * mm
    inner_x = x + padding
    inner_w = w - 2 * padding

    # Generate barcode image in-memory
    barcode_value = product.barcode or product.sku
    try:
        Code128 = bc.get_barcode_class('code128')
        writer = ImageWriter()
        bc_obj = Code128(barcode_value, writer=writer)
        img_buffer = _io.BytesIO()
        bc_obj.write(img_buffer, options={
            'module_width': 0.35,
            'module_height': 8.0,
            'quiet_zone': 2.0,
            'font_size': 6,
            'text_distance': 1.5,
            'write_text': False,  # we draw barcode number ourselves
            'background': 'white',
            'foreground': 'black',
        })
        img_buffer.seek(0)

        # Heights allocation
        name_h = 3.5 * mm
        price_h = 3.5 * mm if label.include_price else 0
        bc_h = h - 2 * padding - name_h - price_h - 2 * mm  # barcode gets remaining space

        # Draw product name (top of label)
        name_y = y + h - padding - name_h
        c.setFont('Helvetica-Bold', 5.5)
        c.setFillColor(colors.black)
        name = product.name[:28] + '…' if len(product.name) > 28 else product.name
        c.drawString(inner_x, name_y + 1 * mm, name)

        # Draw barcode image
        bc_y = name_y - bc_h - 1 * mm
        from reportlab.lib.utils import ImageReader
        c.drawImage(
            ImageReader(img_buffer),
            inner_x, bc_y,
            width=inner_w, height=bc_h,
            preserveAspectRatio=True, anchor='c'
        )

        # Draw barcode value text
        bc_text_y = bc_y - 2.5 * mm
        c.setFont('Helvetica', 4.5)
        c.drawCentredString(x + w / 2, bc_text_y + 0.5 * mm, barcode_value)

        # Draw price if enabled
        if label.include_price:
            price_y = y + padding
            c.setFont('Helvetica-Bold', 6)
            price_str = f"UGX {product.selling_price:,.0f}"
            c.drawCentredString(x + w / 2, price_y + 0.5 * mm, price_str)

    except Exception as e:
        # Fallback: just print product name and barcode as text
        c.setFont('Helvetica', 5)
        c.drawString(inner_x, y + h / 2 + 3 * mm, product.name[:30])
        c.drawString(inner_x, y + h / 2 - 2 * mm, barcode_value)
        logger.warning(f"Barcode image draw failed for {product.pk}: {e}")