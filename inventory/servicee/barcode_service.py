# inventory/services/barcode_service.py
"""
Barcode generation and lookup service.

Responsibilities:
  - Generate Code128 barcodes for internal products / cartons
  - Save barcode PNG to product.barcode_image
  - Auto-assign barcode value if none exists
  - Resolve a scanned barcode to a Product or ProductBundle (DB only — no external API calls)

Install requirements:
    pip install python-barcode[images] Pillow
"""

import io
import logging
from django.core.files.base import ContentFile
from django.db import transaction

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
#  Barcode generation                                                  #
# ------------------------------------------------------------------ #

def generate_barcode_value(product) -> str:
    """
    Generate a unique barcode string for an internal product.
    Format: IN{product.pk:010d}
    Falls back to a UUID-based code if pk is not yet available.
    """
    if product.pk:
        return f"IN{product.pk:010d}"
    import uuid
    return f"IN{uuid.uuid4().hex[:10].upper()}"


def generate_barcode_image(barcode_value: str, product_name: str = "") -> ContentFile:
    """
    Generate a Code128 barcode PNG and return as a Django ContentFile.

    Args:
        barcode_value: The string to encode
        product_name:  Optional — kept for signature compatibility (not rendered on image)

    Returns:
        ContentFile ready to assign to an ImageField, or None on failure.
    """
    import barcode
    from barcode.writer import ImageWriter

    try:
        Code128 = barcode.get_barcode_class('code128')
        writer = ImageWriter()

        options = {
            'module_width': 0.4,
            'module_height': 12.0,
            'quiet_zone': 4.0,
            'font_size': 8,
            'text_distance': 3.0,
            'background': 'white',
            'foreground': 'black',
            'write_text': True,
        }

        bc = Code128(barcode_value, writer=writer)
        buffer = io.BytesIO()
        bc.write(buffer, options=options)
        buffer.seek(0)

        filename = f"barcode_{barcode_value}.png"
        return ContentFile(buffer.read(), name=filename)

    except Exception as e:
        logger.error(f"Barcode image generation failed for {barcode_value}: {e}")
        return None


def assign_and_generate_barcode(product, save=True):
    """
    Main entry point called from Product.save() signal or view.

    - If product has no barcode: generate one (internal type)
    - If barcode exists but no image: generate image only
    - If both exist: skip

    Args:
        product: Product instance (must have pk if save=True)
        save:    Whether to call product.save() after updating fields
    """
    changed_fields = []

    if not product.barcode:
        product.barcode = generate_barcode_value(product)
        product.barcode_type = 'internal'
        changed_fields.extend(['barcode', 'barcode_type'])
        logger.info(f"Assigned internal barcode {product.barcode} to product {product.pk}")

    if not product.barcode_image:
        image_file = generate_barcode_image(product.barcode, product.name)
        if image_file:
            product.barcode_image.save(image_file.name, image_file, save=False)
            changed_fields.append('barcode_image')
            logger.info(f"Generated barcode image for product {product.pk}")

    if save and changed_fields:
        product.save(update_fields=changed_fields)

    return product


# ------------------------------------------------------------------ #
#  Scan resolution — DB only, no external API calls                   #
# ------------------------------------------------------------------ #

def resolve_barcode(barcode_value: str, store=None) -> dict:
    """
    Resolve a scanned barcode to a product or bundle using the local DB only.

    No external HTTP calls are made here. This keeps scan response time fast
    and works fully offline.

    Returns a dict with:
        found   (bool)
        type:   'product' | 'bundle' | 'not_found'
        product: Product instance or None
        bundle:  ProductBundle instance or None
        stock:   current quantity at store (int) or None
        message: human-readable status string
    """
    from inventory.models import Product, ProductBundle

    result = {
        'found': False,
        'type': 'not_found',
        'product': None,
        'bundle': None,
        'stock': None,
        'message': f'No product found for barcode: {barcode_value}',
    }

    # ── 1. Direct product lookup ──────────────────────────────────── #
    try:
        product = Product.objects.select_related('category', 'supplier').get(
            barcode=barcode_value,
            is_active=True,
        )
        result.update({
            'found': True,
            'type': 'product',
            'product': product,
            'message': f'Found: {product.name}',
        })

        if store:
            try:
                from inventory.models import Stock
                stock_obj = Stock.objects.get(product=product, store=store)
                result['stock'] = stock_obj.quantity
            except Exception:
                result['stock'] = 0

        return result

    except Product.DoesNotExist:
        pass

    # ── 2. Bundle lookup (carton / pack barcode) ──────────────────── #
    try:
        bundle = ProductBundle.objects.select_related(
            'parent_product', 'child_product'
        ).get(
            parent_product__barcode=barcode_value,
            is_active=True,
        )
        result.update({
            'found': True,
            'type': 'bundle',
            'product': bundle.parent_product,
            'bundle': bundle,
            'message': (
                f'Bundle: {bundle.parent_product.name} '
                f'→ adds {bundle.child_qty}× {bundle.child_product.name}'
            ),
        })

        if store:
            try:
                from inventory.models import Stock
                stock_obj = Stock.objects.get(
                    product=bundle.child_product, store=store
                )
                result['stock'] = stock_obj.quantity
            except Exception:
                result['stock'] = 0

        return result

    except ProductBundle.DoesNotExist:
        pass

    # ── 3. Nothing found — return not_found ──────────────────────── #
    return result