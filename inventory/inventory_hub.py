"""
inventory/views/inventory_hub.py

Unified Inventory Hub — single view that replaces:
  - ProductListView      → inventory:product_list
  - CategoryListView     → inventory:category_list
  - StockListView        → inventory:stock_list
  - SupplierListView     → inventory:supplier_list

Wire up in urls.py:
    from inventory.views.inventory_hub import InventoryHubView
    path('', InventoryHubView.as_view(), name='product_list'),

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GET  (normal)   → full page render
GET  (AJAX)     → lightweight partial HTML for the _tab in params
                  Detected via X-Requested-With: XMLHttpRequest
POST (AJAX)     → inline CRUD; dispatched on  _hub_action  field

Inline actions (_hub_action values)
────────────────────────────────────
  stock_adjustment        single-product stock movement
  stock_adjustment_batch  multi-product stock adjustment
  product_create          create product via ProductForm
  product_update          update product via ProductForm (pk in _pk)
  product_delete          delete product              (pk in _pk)
  category_create         create category (raw fields)
  category_update         update category (pk in _pk)
  category_delete         delete category (pk in _pk)
  supplier_create         create supplier (raw fields)
  supplier_update         update supplier (pk in _pk)
  supplier_delete         delete supplier (pk in _pk)

All POST handlers return JSON:
  { "ok": true,  "message": "...",  ...extra... }
  { "ok": false, "error":   "..." }
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

import json
import logging
import traceback as _traceback
from decimal import Decimal, InvalidOperation
from inventory.servicee.scanner_views import _can_create_products
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import ListView

from inventory.forms import BulkActionForm, ProductFilterForm, ProductForm, SupplierForm
from inventory.models import Category, Product, Stock, StockMovement, Supplier
from stores.models import Store

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Tenant / EFRIS helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_efris_enabled(request):
    """Return EFRIS-enabled flag from request or tenant, never raising."""
    try:
        return request.tenant.efris_enabled
    except AttributeError:
        return getattr(request, 'efris', {}).get('enabled', False)


def _get_company(request):
    """Return the tenant Company instance, or None if not available."""
    try:
        from django_tenants.utils import get_tenant_model
        Company = get_tenant_model()
        return Company.objects.get(schema_name=request.tenant.schema_name)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
#  Stock helpers
# ─────────────────────────────────────────────────────────────────────────────

def _enhance_stock_items(stock_items):
    """Annotate each stock record with computed display fields."""
    for stock in stock_items:
        stock.total_cost          = stock.quantity * stock.product.cost_price
        stock.total_selling_value = stock.quantity * stock.product.selling_price
        stock.potential_profit    = stock.total_selling_value - stock.total_cost

        if stock.quantity == 0:
            stock.status_class = 'critical'
            stock.status_text  = 'Out of Stock'
            stock.status_icon  = 'fas fa-times-circle'
        elif stock.quantity <= stock.low_stock_threshold:
            stock.status_class = 'low'
            stock.status_text  = 'Low Stock'
            stock.status_icon  = 'fas fa-exclamation-triangle'
        elif stock.quantity <= stock.low_stock_threshold * 2:
            stock.status_class = 'medium'
            stock.status_text  = 'Medium Stock'
            stock.status_icon  = 'fas fa-info-circle'
        else:
            stock.status_class = 'good'
            stock.status_text  = 'Good Stock'
            stock.status_icon  = 'fas fa-check-circle'


def _get_stock_dashboard_stats(request):
    """Cache-backed KPI stats for the Overview tab (5-minute TTL).
    Keyed per tenant (schema) since these are company-wide figures,
    not user-specific — avoids a separate cache entry per user.
    """
    try:
        from django.db import connection
        schema = connection.schema_name
    except Exception:
        schema = 'public'
    cache_key = f'inv_hub_dashboard_stats_{schema}'
    stats = cache.get(cache_key)
    if stats is not None:
        return stats

    qs = Stock.objects.select_related('product', 'store')
    values = qs.aggregate(
        total_cost_value    = Sum(F('quantity') * F('product__cost_price')),
        total_selling_value = Sum(F('quantity') * F('product__selling_price')),
        avg_stock_level     = Avg('quantity'),
    )

    cost_val = values['total_cost_value']    or Decimal('0.00')
    sell_val = values['total_selling_value'] or Decimal('0.00')

    stats = {
        'total_products':      qs.values('product').distinct().count(),
        'total_stock_records': qs.count(),
        'out_of_stock_count':  qs.filter(quantity=0).count(),
        'low_stock_count':     qs.filter(quantity__gt=0,
                                         quantity__lte=F('low_stock_threshold')).count(),
        'medium_stock_count':  qs.filter(
            quantity__gt=F('low_stock_threshold'),
            quantity__lte=F('low_stock_threshold') * 2,
        ).count(),
        'good_stock_count':    qs.filter(quantity__gt=F('low_stock_threshold') * 2).count(),
        'total_cost_value':    cost_val,
        'total_selling_value': sell_val,
        'avg_stock_level':     values['avg_stock_level'] or 0,
        'potential_profit':    sell_val - cost_val,
        'total_categories':    Category.objects.count(),
        'total_suppliers':     Supplier.objects.count(),
    }
    cache.set(cache_key, stats, 300)
    return stats


# ─────────────────────────────────────────────────────────────────────────────
#  Main view
# ─────────────────────────────────────────────────────────────────────────────

class InventoryHubView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """
    Unified Inventory Hub — Products, Stock, Categories, Suppliers.
    See module docstring for full API.
    """
    model               = Product
    template_name       = 'inventory/inventory_hub.html'
    context_object_name = 'products'
    permission_required = 'inventory.view_product'
    paginate_by         = 25
    ordering            = ['name']

    PARTIAL_TEMPLATES = {
        'products':   'inventory/partials/inv_products.html',
        'stock':      'inventory/partials/inv_stock.html',
        'categories': 'inventory/partials/inv_categories.html',
        'suppliers':  'inventory/partials/inv_suppliers.html',
    }

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _is_ajax(self):
        return self.request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    # ─────────────────────────────────────────────────────────────────────────
    #  GET
    # ─────────────────────────────────────────────────────────────────────────

    def get(self, request, *args, **kwargs):
        self.object_list = self.get_queryset()
        if not self.get_allow_empty() and not self.object_list.exists():
            raise Http404

        # ── Autocomplete endpoint ─────────────────────────────────────────────
        if self._is_ajax() and request.GET.get('_autocomplete'):
            return self._autocomplete(request)

        # ── Single product JSON (for edit modal prefill) ───────────────────────
        if self._is_ajax() and request.GET.get('_product'):
            return self._product_json(request)

        if self._is_ajax():
            tab     = request.GET.get('_tab', 'products')
            partial = self.PARTIAL_TEMPLATES.get(tab)
            if partial:
                return render(request, partial, self._get_tab_context(tab))
            # Unknown _tab → fall through to full render

        return render(request, self.template_name, self.get_context_data())

    # ─────────────────────────────────────────────────────────────────────────
    #  POST dispatcher
    # ─────────────────────────────────────────────────────────────────────────

    # (handler_method_name, required_django_permission)
    _ACTION_MAP = {
        'stock_adjustment':       ('_action_stock_single',    'inventory.add_stockmovement'),
        'stock_adjustment_batch': ('_action_stock_batch',     'inventory.add_stockmovement'),
        'product_create':         ('_action_product_create',  'inventory.add_product'),
        'product_update':         ('_action_product_update',  'inventory.change_product'),
        'product_delete':         ('_action_product_delete',  'inventory.delete_product'),
        'category_create':        ('_action_category_create', 'inventory.add_category'),
        'category_update':        ('_action_category_update', 'inventory.change_category'),
        'category_delete':        ('_action_category_delete', 'inventory.delete_category'),
        'supplier_create':        ('_action_supplier_create', 'inventory.add_supplier'),
        'supplier_update':        ('_action_supplier_update', 'inventory.change_supplier'),
        'supplier_delete':        ('_action_supplier_delete', 'inventory.delete_supplier'),
        'scan_barcode':           ('_action_scan_barcode', 'inventory.view_product'),
    }

    def post(self, request, *args, **kwargs):
        action = request.POST.get('_hub_action', '').strip()

        if action not in self._ACTION_MAP:
            return JsonResponse(
                {'ok': False, 'error': f'Unknown action: "{action}".'},
                status=400,
            )

        method_name, perm = self._ACTION_MAP[action]
        if not request.user.has_perm(perm):
            return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

        return getattr(self, method_name)(request)

    # ─────────────────────────────────────────────────────────────────────────
    #  Autocomplete endpoint
    #  GET ?_autocomplete=<type>&q=<term>  → JSON list of {id, text, ...}
    #  Types: category | supplier | unit_of_measure | store | product
    # ─────────────────────────────────────────────────────────────────────────

    def _autocomplete(self, request):
        """
        Lightweight autocomplete for dropdown fields.
        Called via GET with X-Requested-With: XMLHttpRequest and ?_autocomplete=<type>.
        Returns JSON: { results: [{id, text, ...extra}], has_more: bool }
        """
        kind  = request.GET.get('_autocomplete', '').strip()
        q     = request.GET.get('q', '').strip()
        limit = min(int(request.GET.get('limit', 20)), 50)

        results   = []
        has_more  = False

        try:
            if kind == 'category':
                qs = Category.objects.filter(is_active=True).order_by('name')
                if q:
                    qs = qs.filter(Q(name__icontains=q) | Q(code__icontains=q))
                total = qs.count()
                has_more = total > limit
                results = [
                    {
                        'id':   c.id,
                        'text': c.name,
                        'code': c.code or '',
                        'type': c.category_type,
                    }
                    for c in qs[:limit]
                ]

            elif kind == 'supplier':
                qs = Supplier.objects.filter(is_active=True).order_by('name')
                if q:
                    qs = qs.filter(
                        Q(name__icontains=q) |
                        Q(tin__icontains=q)  |
                        Q(contact_person__icontains=q)
                    )
                total = qs.count()
                has_more = total > limit
                results = [
                    {
                        'id':   s.id,
                        'text': s.name,
                        'tin':  s.tin or '',
                    }
                    for s in qs[:limit]
                ]

            elif kind == 'store':
                qs = Store.objects.filter(is_active=True).order_by('name')
                if q:
                    qs = qs.filter(Q(name__icontains=q))
                total = qs.count()
                has_more = total > limit
                results = [
                    {'id': s.id, 'text': s.name}
                    for s in qs[:limit]
                ]

            elif kind == 'unit_of_measure':
                # choices live on the model — filter in Python (tiny list)
                from inventory.models import Product as _P
                all_choices = _P.UNIT_CHOICES
                if q:
                    q_lower = q.lower()
                    all_choices = [
                        (val, label) for val, label in all_choices
                        if q_lower in label.lower() or q_lower in val.lower()
                    ]
                has_more = len(all_choices) > limit
                results = [
                    {'id': val, 'text': label}
                    for val, label in all_choices[:limit]
                ]

            elif kind == 'product':
                qs = Product.objects.filter(is_active=True).only(
                    'id', 'name', 'sku'
                ).order_by('name')
                if q:
                    qs = qs.filter(Q(name__icontains=q) | Q(sku__icontains=q))
                total = qs.count()
                has_more = total > limit
                results = [
                    {'id': p.id, 'text': p.name, 'sku': p.sku or ''}
                    for p in qs[:limit]
                ]

            else:
                return JsonResponse(
                    {'ok': False, 'error': f'Unknown autocomplete type: "{kind}".'},
                    status=400,
                )

        except Exception as exc:
            logger.error('Autocomplete error (%s): %s', kind, exc, exc_info=True)
            return JsonResponse({'ok': False, 'error': str(exc)}, status=500)

        return JsonResponse({'ok': True, 'results': results, 'has_more': has_more})


    # ─────────────────────────────────────────────────────────────────────────
    #  Single-product JSON  (GET ?_product=<pk>)
    #  Used by the edit modal in the template to prefill the product form.
    # ─────────────────────────────────────────────────────────────────────────

    def _product_json(self, request):
        """
        Return a lightweight JSON representation of a single product for the
        edit-modal prefill.  Called via:
            GET <hub-url>?_product=<pk>   (X-Requested-With: XMLHttpRequest)
        """
        pk = request.GET.get('_product', '').strip()
        if not pk:
            return JsonResponse({'ok': False, 'error': 'Missing product ID.'}, status=400)

        if not request.user.has_perm('inventory.view_product'):
            return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

        try:
            product = get_object_or_404(
                Product.objects.select_related('category', 'supplier'),
                pk=pk,
            )
            image_url = None
            if product.image:
                try:
                    image_url = product.image.url
                except Exception:
                    pass

            return JsonResponse({
                'ok':   True,
                'id':   product.pk,
                'name': product.name,
                'sku':  product.sku or '',
                'barcode':     product.barcode or '',
                'description': product.description or '',
                'cost_price':         str(product.cost_price),
                'selling_price':      str(product.selling_price),
                'discount_percentage': str(product.discount_percentage or '0'),
                'tax_rate':           str(product.tax_rate or ''),
                'excise_duty_rate':   str(getattr(product, 'excise_duty_rate', '') or ''),
                'unit_of_measure': product.unit_of_measure or '',
                'min_stock_level': str(product.min_stock_level or ''),
                'category_id':   product.category.pk   if product.category else '',
                'category_name': product.category.name if product.category else '',
                'supplier_id':   product.supplier.pk   if product.supplier else '',
                'supplier_name': product.supplier.name if product.supplier else '',
                'category': {'id': product.category.pk, 'name': product.category.name} if product.category else None,
                'supplier': {'id': product.supplier.pk, 'name': product.supplier.name} if product.supplier else None,
                'is_active': product.is_active,
                'image_url': image_url,
                'efris_auto_sync_enabled':       getattr(product, 'efris_auto_sync_enabled', False),
                'efris_commodity_category_id':   getattr(product, 'efris_commodity_category_id', None),
                'efris_commodity_category_name': getattr(product, 'efris_commodity_category_name', None),
            })

        except Exception as exc:
            logger.error('Hub _product_json error (pk=%s): %s', pk, exc, exc_info=True)
            return JsonResponse({'ok': False, 'error': str(exc)}, status=500)

    # ─────────────────────────────────────────────────────────────────────────
    #  Stock adjustment handlers
    # ─────────────────────────────────────────────────────────────────────────

    def _action_stock_single(self, request):
        """
        Single-product stock movement.
        Mirrors StockAdjustmentView._handle_single_adjustment — same signed-qty
        logic, same model-level side effects via StockMovement.save().
        """
        try:
            product_id    = request.POST.get('product')
            store_id      = request.POST.get('store')
            movement_type = request.POST.get('movement_type', '').strip().upper()
            raw_qty       = request.POST.get('quantity', '0')
            unit_price    = request.POST.get('unit_price', '') or None
            reference     = request.POST.get('reference', '').strip()
            notes         = request.POST.get('notes', '').strip()

            if not product_id:
                return JsonResponse({'ok': False, 'error': 'Product is required.'})
            if not store_id:
                return JsonResponse({'ok': False, 'error': 'Branch is required.'})
            if not movement_type:
                return JsonResponse({'ok': False, 'error': 'Movement type is required.'})

            try:
                quantity = Decimal(raw_qty)
                if quantity <= 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                return JsonResponse({'ok': False, 'error': 'Quantity must be a positive number.'})

            product = get_object_or_404(Product, id=product_id, is_active=True)
            store   = get_object_or_404(Store,   id=store_id,   is_active=True)

            # Removal-type movements use a negative quantity so StockMovement.save()
            # decrements Stock.quantity correctly without any manual update.
            REMOVE_TYPES = {'SALE', 'ADJUSTMENT_OUT', 'WASTAGE'}
            signed_qty = -quantity if movement_type in REMOVE_TYPES else quantity

            with transaction.atomic():
                StockMovement.objects.create(
                    product       = product,
                    store         = store,
                    movement_type = movement_type,
                    quantity      = signed_qty,
                    unit_price    = Decimal(unit_price) if unit_price else None,
                    reference     = reference or f'HUB-{timezone.now().strftime("%Y%m%d%H%M")}',
                    notes         = notes,
                    created_by    = request.user,
                )

            logger.info('Hub stock single by %s: %s @ %s — %s × %s',
                        request.user.username, product.name, store.name, movement_type, quantity)
            return JsonResponse({
                'ok':      True,
                'message': f'Stock adjusted: {product.name} at {store.name}.',
            })

        except Exception as exc:
            logger.error('Hub stock single error: %s', exc, exc_info=True)
            return JsonResponse({'ok': False, 'error': str(exc)}, status=500)

    def _action_stock_batch(self, request):
        """
        Batch stock adjustment across multiple products.
        Mirrors StockAdjustmentView._handle_batch_adjustment — Decimal arithmetic,
        movement-delta approach, no manual Stock.quantity update.
        """
        try:
            batch_products  = request.POST.getlist('batch_products')
            store_id        = request.POST.get('store')
            adjustment_type = request.POST.get('adjustment_type', 'add')
            reason          = request.POST.get('reason', '').strip()
            notes           = request.POST.get('notes', '').strip()

            try:
                quantity = Decimal(request.POST.get('quantity', '0'))
                if quantity <= 0:
                    raise ValueError
            except (InvalidOperation, ValueError):
                return JsonResponse({'ok': False, 'error': 'Quantity must be a positive number.'})

            if not batch_products:
                return JsonResponse({'ok': False, 'error': 'Select at least one product.'})
            if not store_id:
                return JsonResponse({'ok': False, 'error': 'Branch is required.'})

            store    = get_object_or_404(Store, id=store_id, is_active=True)
            products = Product.objects.filter(id__in=batch_products, is_active=True)
            if not products.exists():
                return JsonResponse({'ok': False, 'error': 'No valid active products found.'})

            success_count = 0
            error_count   = 0
            ref = f'HUB-BATCH-{timezone.now().strftime("%Y%m%d%H%M")}'

            with transaction.atomic():
                for product in products:
                    try:
                        stock, _ = Stock.objects.get_or_create(
                            product=product, store=store,
                            defaults={'quantity': Decimal('0')},
                        )
                        if adjustment_type == 'add':
                            movement_qty = quantity
                        elif adjustment_type == 'remove':
                            movement_qty = -min(quantity, stock.quantity)
                        elif adjustment_type == 'set':
                            movement_qty = quantity - stock.quantity
                        else:
                            raise ValueError(f'Invalid adjustment type: {adjustment_type}')

                        StockMovement.objects.create(
                            product=product, store=store,
                            movement_type='ADJUSTMENT',
                            quantity=movement_qty,
                            reference=ref,
                            notes=f'Batch adjustment: {reason}. {notes}'.strip('. '),
                            created_by=request.user,
                        )
                        success_count += 1

                    except Exception as exc:
                        logger.error('Hub batch item error for %s: %s',
                                     product.name, exc, exc_info=True)
                        error_count += 1

            parts = []
            if success_count:
                parts.append(f'{success_count} product(s) adjusted')
            if error_count:
                parts.append(f'{error_count} failed')

            return JsonResponse({'ok': success_count > 0, 'message': '. '.join(parts) + '.'})

        except Exception as exc:
            logger.error('Hub batch adjustment error: %s', exc, exc_info=True)
            return JsonResponse({'ok': False, 'error': str(exc)}, status=500)

    # ─────────────────────────────────────────────────────────────────────────
    #  Product handlers
    # ─────────────────────────────────────────────────────────────────────────

    # Optional numeric fields that the ProductForm marks required if the model
    # field has blank=False.  We coerce blank → safe default before validation.
    _OPTIONAL_NUMERIC_DEFAULTS = {
        'discount_percentage': '0',
        'min_stock_level':     '0',
        'excise_duty_rate':    '0',
    }

    def _coerce_optional_numerics(self, post):
        """Return a mutable copy of POST with optional numeric fields defaulted."""
        data = post.copy()
        for field, default in self._OPTIONAL_NUMERIC_DEFAULTS.items():
            if not data.get(field, '').strip():
                data[field] = default
        return data

    def _action_product_create(self, request):
        """
        Create a product inline.
        Identical logic to ProductCreateAjaxView — same ProductForm kwargs
        (efris_enabled, company), same JSON response shape, handles file uploads.
        """
        efris_enabled = _get_efris_enabled(request)
        company       = _get_company(request)

        form = ProductForm(
            self._coerce_optional_numerics(request.POST), request.FILES,
            efris_enabled=efris_enabled,
            company=company,
        )

        if form.is_valid():
            try:
                with transaction.atomic():
                    product = form.save(commit=False)
                    product.save()

                logger.info('Hub product create by %s: %s (ID %s)',
                            request.user.username, product.name, product.id)
                return JsonResponse({
                    'ok':      True,
                    'success': True,
                    'message': f'Product "{product.name}" created successfully!',
                    'product': {
                        'id':                  product.id,
                        'name':                product.name,
                        'sku':                 product.sku or '',
                        'barcode':             product.barcode or '',
                        'selling_price':       str(product.selling_price),
                        'cost_price':          str(product.cost_price),
                        'category_id':         product.category.id   if product.category  else None,
                        'category_name':       product.category.name if product.category  else None,
                        'supplier_id':         product.supplier.id   if product.supplier  else None,
                        'supplier_name':       product.supplier.name if product.supplier  else None,
                        'tax_rate':            product.tax_rate,
                        'effective_tax_rate':  getattr(product, 'effective_tax_rate', None),
                        'efris_enabled':       (product.efris_auto_sync_enabled
                                                if efris_enabled else False),
                        'company_vat_enabled': (company.is_vat_enabled if company else True),
                        'is_active':           product.is_active,
                    },
                })

            except Exception as exc:
                logger.error('Hub product create save error: %s', exc, exc_info=True)
                return JsonResponse({
                    'ok': False, 'success': False,
                    'errors': {'non_field_errors': [str(exc)]},
                }, status=400)

        else:
            logger.warning('Hub product create validation failed: %s', form.errors)
            return JsonResponse({
                'ok':    False,
                'success': False,
                'errors': form.errors,
                'error':  'Please correct the form errors.',
            }, status=400)

    def _action_product_update(self, request):
        """
        Update an existing product inline.
        Mirrors ProductUpdateView — same ProductForm kwargs (efris_enabled, company).
        Expects _pk in POST body.
        """
        pk = request.POST.get('_pk')
        if not pk:
            return JsonResponse({'ok': False, 'error': 'Missing product ID (_pk).'}, status=400)

        product       = get_object_or_404(Product, pk=pk)
        efris_enabled = _get_efris_enabled(request)
        company       = _get_company(request)

        form = ProductForm(
            self._coerce_optional_numerics(request.POST), request.FILES,
            instance=product,
            efris_enabled=efris_enabled,
            company=company,
        )

        if form.is_valid():
            try:
                with transaction.atomic():
                    product = form.save()

                logger.info('Hub product update by %s: %s (ID %s)',
                            request.user.username, product.name, product.id)
                return JsonResponse({
                    'ok':      True,
                    'success': True,
                    'message': f'Product "{product.name}" updated successfully!',
                    'product': {
                        'id':                 product.id,
                        'name':               product.name,
                        'sku':                product.sku or '',
                        'selling_price':      str(product.selling_price),
                        'cost_price':         str(product.cost_price),
                        'category_id':        product.category.id   if product.category else None,
                        'category_name':      product.category.name if product.category else None,
                        'supplier_id':        product.supplier.id   if product.supplier else None,
                        'supplier_name':      product.supplier.name if product.supplier else None,
                        'tax_rate':           product.tax_rate,
                        'effective_tax_rate': getattr(product, 'effective_tax_rate', None),
                        'is_active':          product.is_active,
                    },
                })

            except Exception as exc:
                logger.error('Hub product update save error: %s', exc, exc_info=True)
                return JsonResponse({
                    'ok': False, 'success': False,
                    'errors': {'non_field_errors': [str(exc)]},
                }, status=400)

        else:
            return JsonResponse({
                'ok':    False,
                'success': False,
                'errors': form.errors,
                'error':  'Please correct the form errors.',
            }, status=400)

    def _action_product_delete(self, request):
        """
        Delete a product inline.  Mirrors ProductDeleteView.
        Expects _pk in POST body.
        Hard-delete is refused if the product has any stock movements —
        deactivation is suggested instead to preserve history.
        """
        pk = request.POST.get('_pk')
        if not pk:
            return JsonResponse({'ok': False, 'error': 'Missing product ID (_pk).'}, status=400)

        product = get_object_or_404(Product, pk=pk)

        if product.movements.exists():
            return JsonResponse({
                'ok': False,
                'error': (
                    f'Cannot delete "{product.name}" — it has stock movement history. '
                    'Deactivate it instead to preserve audit records.'
                ),
            }, status=400)

        name = product.name
        try:
            with transaction.atomic():
                product.delete()

            logger.info('Hub product delete by %s: %s (ID %s)',
                        request.user.username, name, pk)
            return JsonResponse({
                'ok':        True,
                'message':   f'Product "{name}" deleted successfully.',
                'deleted_id': int(pk),
            })

        except Exception as exc:
            logger.error('Hub product delete error: %s', exc, exc_info=True)
            return JsonResponse({'ok': False, 'error': str(exc)}, status=500)

    # ─────────────────────────────────────────────────────────────────────────
    #  Category handlers
    # ─────────────────────────────────────────────────────────────────────────

    def _action_category_create(self, request):
        """
        Create a category inline.
        Mirrors category_create_ajax exactly — raw-field approach (no CategoryForm,
        which requires a full EFRIS template round-trip), same validation rules,
        same JSON response keys (including 'success' for JS compat).

        CRITICAL: category_type must be explicitly set ('product' or 'service').
        """
        try:
            name          = request.POST.get('name', '').strip()
            code          = request.POST.get('code', '').strip()
            description   = request.POST.get('description', '').strip()
            category_type = request.POST.get('category_type', 'product').strip()
            is_active     = request.POST.get('is_active', 'true').lower() == 'true'

            if not name:
                return JsonResponse({
                    'ok': False, 'success': False,
                    'error': 'Category name is required.',
                    'errors': {'name': ['This field is required.']},
                }, status=400)

            if category_type not in ('product', 'service'):
                return JsonResponse({
                    'ok': False, 'success': False,
                    'error': 'Category type must be "product" or "service".',
                    'errors': {'category_type': ['Invalid category type.']},
                }, status=400)

            category = Category.objects.create(
                name          = name,
                code          = code or None,
                description   = description,
                category_type = category_type,   # CRITICAL — must be set explicitly
                is_active     = is_active,
            )

            logger.info('Hub category create by %s: %s (type=%s, ID %s)',
                        request.user.username, category.name,
                        category.category_type, category.id)
            return JsonResponse({
                'ok': True, 'success': True,
                'message': f'Category "{category.name}" created successfully.',
                'category': {
                    'id':            category.id,
                    'name':          category.name,
                    'code':          category.code or '',
                    'category_type': category.category_type,
                    'is_active':     category.is_active,
                },
            })

        except Exception as exc:
            logger.error('Hub category create error: %s', exc, exc_info=True)
            return JsonResponse({
                'ok': False, 'success': False,
                'error': str(exc),
                'traceback': _traceback.format_exc() if request.user.is_superuser else None,
            }, status=500)

    def _action_category_update(self, request):
        """
        Update an existing category inline.  Mirrors CategoryUpdateView logic.
        Updates the safe subset of fields (name, code, description, type, active).
        EFRIS fields are intentionally excluded — those require the full form page.
        Expects _pk in POST body.
        """
        pk = request.POST.get('_pk')
        if not pk:
            return JsonResponse({'ok': False, 'error': 'Missing category ID (_pk).'}, status=400)

        category = get_object_or_404(Category, pk=pk)

        try:
            name          = request.POST.get('name', '').strip()
            code          = request.POST.get('code', '').strip()
            description   = request.POST.get('description', '').strip()
            category_type = request.POST.get('category_type', category.category_type).strip()
            is_active_raw = request.POST.get('is_active', '')
            is_active     = (is_active_raw.lower() == 'true') if is_active_raw else category.is_active

            if not name:
                return JsonResponse({'ok': False, 'error': 'Category name is required.'}, status=400)
            if category_type not in ('product', 'service'):
                return JsonResponse(
                    {'ok': False, 'error': 'Category type must be "product" or "service".'},
                    status=400,
                )

            # Track EFRIS code change so we can warn the user (mirrors CategoryUpdateView)
            old_efris_code = getattr(category, 'efris_commodity_category_code', None)

            with transaction.atomic():
                category.name          = name
                category.code          = code or None
                category.description   = description
                category.category_type = category_type
                category.is_active     = is_active
                category.save()

            new_efris_code = getattr(category, 'efris_commodity_category_code', None)
            efris_warning  = (
                _get_efris_enabled(request)
                and old_efris_code is not None
                and old_efris_code != new_efris_code
            )

            logger.info('Hub category update by %s: %s (ID %s)',
                        request.user.username, category.name, category.id)
            return JsonResponse({
                'ok': True, 'success': True,
                'message':      f'Category "{category.name}" updated successfully.',
                'efris_warning': efris_warning,
                'category': {
                    'id':            category.id,
                    'name':          category.name,
                    'code':          category.code or '',
                    'category_type': category.category_type,
                    'is_active':     category.is_active,
                },
            })

        except Exception as exc:
            logger.error('Hub category update error: %s', exc, exc_info=True)
            return JsonResponse({'ok': False, 'error': str(exc)}, status=500)

    def _action_category_delete(self, request):
        """
        Delete a category inline.  Mirrors CategoryDeleteView.
        Products in this category will become uncategorised (null FK).
        Expects _pk in POST body.
        """
        pk = request.POST.get('_pk')
        if not pk:
            return JsonResponse({'ok': False, 'error': 'Missing category ID (_pk).'}, status=400)

        category = get_object_or_404(Category, pk=pk)
        name = category.name

        try:
            with transaction.atomic():
                category.delete()

            logger.info('Hub category delete by %s: %s (ID %s)',
                        request.user.username, name, pk)
            return JsonResponse({
                'ok': True, 'success': True,
                'message':    (
                    f'Category "{name}" deleted. '
                    'Affected products are now uncategorised.'
                ),
                'deleted_id': int(pk),
            })

        except Exception as exc:
            logger.error('Hub category delete error: %s', exc, exc_info=True)
            return JsonResponse({'ok': False, 'error': str(exc)}, status=500)

    # ─────────────────────────────────────────────────────────────────────────
    #  Supplier handlers
    # ─────────────────────────────────────────────────────────────────────────

    def _action_supplier_create(self, request):
        """
        Create a supplier inline.
        Mirrors supplier_create_ajax — same raw-field approach, same JSON shape.
        Extended with contact_person and notes fields that the model supports.
        """
        try:
            name           = request.POST.get('name',           '').strip()
            tin            = request.POST.get('tin',            '').strip()
            phone          = request.POST.get('phone',          '').strip()
            email          = request.POST.get('email',          '').strip()
            address        = request.POST.get('address',        '').strip()
            contact_person = request.POST.get('contact_person', '').strip()

            if not name:
                return JsonResponse({
                    'ok': False, 'success': False,
                    'error': 'Supplier name is required.',
                }, status=400)
            if not phone:
                return JsonResponse({
                    'ok': False, 'success': False,
                    'error': 'Phone number is required.',
                }, status=400)

            supplier = Supplier.objects.create(
                name           = name,
                tin            = tin  or None,
                phone          = phone,
                email          = email          or None,
                address        = address        or None,
                contact_person = contact_person or None,
                is_active      = True,
            )

            logger.info('Hub supplier create by %s: %s (ID %s)',
                        request.user.username, supplier.name, supplier.id)
            return JsonResponse({
                'ok': True, 'success': True,
                'message': f'Supplier "{supplier.name}" created successfully.',
                'supplier': {
                    'id':             supplier.id,
                    'name':           supplier.name,
                    'phone':          supplier.phone,
                    'email':          supplier.email          or '',
                    'tin':            supplier.tin            or '',
                    'contact_person': getattr(supplier, 'contact_person', '') or '',
                    'is_active':      supplier.is_active,
                },
            })

        except Exception as exc:
            logger.error('Hub supplier create error: %s', exc, exc_info=True)
            return JsonResponse({'ok': False, 'success': False, 'error': str(exc)}, status=500)

    def _action_supplier_update(self, request):
        """
        Update an existing supplier inline.  Mirrors SupplierUpdateView.
        Uses SupplierForm for full validation (same as the CBV).
        Expects _pk in POST body.
        """
        pk = request.POST.get('_pk')
        if not pk:
            return JsonResponse({'ok': False, 'error': 'Missing supplier ID (_pk).'}, status=400)

        supplier = get_object_or_404(Supplier, pk=pk)
        form     = SupplierForm(request.POST, instance=supplier)

        if form.is_valid():
            try:
                with transaction.atomic():
                    supplier = form.save()

                logger.info('Hub supplier update by %s: %s (ID %s)',
                            request.user.username, supplier.name, supplier.id)
                return JsonResponse({
                    'ok': True, 'success': True,
                    'message': f'Supplier "{supplier.name}" updated successfully.',
                    'supplier': {
                        'id':             supplier.id,
                        'name':           supplier.name,
                        'phone':          supplier.phone,
                        'email':          supplier.email or '',
                        'tin':            supplier.tin   or '',
                        'contact_person': getattr(supplier, 'contact_person', '') or '',
                        'is_active':      supplier.is_active,
                    },
                })

            except Exception as exc:
                logger.error('Hub supplier update save error: %s', exc, exc_info=True)
                return JsonResponse({
                    'ok': False, 'success': False,
                    'errors': {'non_field_errors': [str(exc)]},
                }, status=400)

        else:
            return JsonResponse({
                'ok':    False,
                'success': False,
                'errors': form.errors,
                'error':  'Please correct the form errors.',
            }, status=400)

    def _action_supplier_delete(self, request):
        """
        Delete a supplier inline.
        Refuses if the supplier has active products — reassign or deactivate first.
        Expects _pk in POST body.
        """
        pk = request.POST.get('_pk')
        if not pk:
            return JsonResponse({'ok': False, 'error': 'Missing supplier ID (_pk).'}, status=400)

        supplier = get_object_or_404(Supplier, pk=pk)

        active_count = supplier.products.filter(is_active=True).count()
        if active_count:
            return JsonResponse({
                'ok': False,
                'error': (
                    f'Cannot delete "{supplier.name}" — it has {active_count} active product(s). '
                    'Reassign or deactivate them first.'
                ),
            }, status=400)

        name = supplier.name
        try:
            with transaction.atomic():
                supplier.delete()

            logger.info('Hub supplier delete by %s: %s (ID %s)',
                        request.user.username, name, pk)
            return JsonResponse({
                'ok': True, 'success': True,
                'message':    f'Supplier "{name}" deleted successfully.',
                'deleted_id': int(pk),
            })

        except Exception as exc:
            logger.error('Hub supplier delete error: %s', exc, exc_info=True)
            return JsonResponse({'ok': False, 'error': str(exc)}, status=500)

    # ─────────────────────────────────────────────────────────────────────────
    #  Barcode scan — resolves a barcode within the hub context
    #  Used by the Scanner tab's inline scan input
    # ─────────────────────────────────────────────────────────────────────────

    def _action_scan_barcode(self, request):
        """
        POST _hub_action=scan_barcode
        Body: { barcode: "...", store_id: 3, mode: "product_lookup" }
        Returns same payload shape as BarcodeScanView so the frontend JS is reusable.
        """
        from inventory.servicee.barcode_service import resolve_barcode, lookup_external_barcode

        barcode_value = (request.POST.get('barcode') or '').strip()
        store_id = request.POST.get('store_id')
        mode = request.POST.get('mode', 'product_lookup')

        if not barcode_value:
            return JsonResponse({'ok': False, 'error': 'barcode is required.'}, status=400)

        store = None
        if store_id:
            try:
                store = Store.objects.get(pk=store_id, is_active=True)
            except Store.DoesNotExist:
                pass

        resolution = resolve_barcode(barcode_value, store=store)

        payload = {
            'ok': True,
            'found': resolution['found'],
            'type': resolution['type'],
            'message': resolution['message'],
            'mode': mode,
        }

        if resolution['found']:
            p = resolution['product']
            payload['product'] = {
                'id': p.pk,
                'name': p.name,
                'sku': p.sku,
                'barcode': p.barcode,
                'selling_price': str(p.selling_price),
                'cost_price': str(p.cost_price),
                'category': str(p.category) if p.category else None,
                'barcode_image_url': (
                    p.barcode_image.url
                    if getattr(p, 'barcode_image', None) and p.barcode_image
                    else None
                ),
            }
            payload['stock'] = resolution.get('stock')

            if resolution['type'] == 'bundle':
                b = resolution['bundle']
                payload['bundle'] = {
                    'id': b.pk,
                    'child_qty': b.child_qty,
                    'child_product_name': b.child_product.name,
                }
        else:
            if _can_create_products(request.user):
                external = lookup_external_barcode(barcode_value)
                payload['external_lookup'] = external
                payload['can_create'] = True
            else:
                payload['can_create'] = False

        return JsonResponse(payload)
    # ─────────────────────────────────────────────────────────────────────────
    #  Per-tab AJAX context  (lightweight — skips other tabs' DB work)
    # ─────────────────────────────────────────────────────────────────────────

    def _get_tab_context(self, tab):
        req = self.request
        ctx = {
            'stores':     Store.objects.filter(is_active=True).order_by('name'),
            'categories': Category.objects.filter(is_active=True).order_by('name'),
        }

        if tab == 'products':
            paginator, page, qs, is_paginated = self.paginate_queryset(
                self.object_list, self.paginate_by
            )
            efris_enabled = _get_efris_enabled(req)
            company       = _get_company(req)
            prod_store    = req.GET.get('prod_store', '')
            prod_stores   = Store.objects.filter(is_active=True).order_by('name')
            branch_stocks = (
                {s.id: s for s in prod_stores}
                if not prod_store else {}
            )
            ctx.update({
                'products':       qs,
                'paginator':      paginator,
                'page_obj':       page,
                'is_paginated':   is_paginated,
                'filter_form':    ProductFilterForm(req.GET),
                'bulk_form':      BulkActionForm(),
                'total_products': len(self.object_list),
                'prod_store':     prod_store,
                'prod_stores':    prod_stores,
                'branch_stocks':  branch_stocks,
                'product_form':   ProductForm(
                    efris_enabled=efris_enabled,
                    company=company,
                ),
            })

        elif tab == 'stock':
            stock_qs    = self._build_stock_queryset()
            stock_pager = Paginator(stock_qs, 25)
            stock_page  = stock_pager.get_page(req.GET.get('stock_page', 1))
            _enhance_stock_items(stock_page.object_list)
            ctx.update({
                'stock_items':     stock_page.object_list,
                'stock_page':      stock_page,
                'stock_paginator': stock_pager,
                'stock_paginated': stock_pager.num_pages > 1,
                'stock_filters': {
                    'search':    req.GET.get('search',    ''),
                    'status':    req.GET.get('status',    ''),
                    'store':     req.GET.get('store',     ''),
                    'category':  req.GET.get('category',  ''),
                    'sort':      req.GET.get('sort',      'name'),
                    'date_from': req.GET.get('date_from', ''),
                    'date_to':   req.GET.get('date_to',   ''),
                },
            })

        elif tab == 'categories':
            cat_qs    = self._build_category_queryset()
            cat_pager = Paginator(cat_qs, 20)
            cat_page  = cat_pager.get_page(req.GET.get('cat_page', 1))
            ctx.update({
                'categories_list': cat_page.object_list,
                'cat_page':        cat_page,
                'cat_paginator':   cat_pager,
                'cat_paginated':   cat_pager.num_pages > 1,
                'cat_search':      req.GET.get('cat_search', ''),
                'cat_status':      req.GET.get('cat_status', ''),
            })

        elif tab == 'suppliers':
            supp_qs    = self._build_supplier_queryset()
            supp_pager = Paginator(supp_qs, 20)
            supp_page  = supp_pager.get_page(req.GET.get('supp_page', 1))
            ctx.update({
                'suppliers':      supp_page.object_list,
                'supp_page':      supp_page,
                'supp_paginator': supp_pager,
                'supp_paginated': supp_pager.num_pages > 1,
                'supp_search':    req.GET.get('supp_search', ''),
                'supp_status':    req.GET.get('supp_status', ''),
            })

        return ctx

    # ─────────────────────────────────────────────────────────────────────────
    #  Queryset builders
    # ─────────────────────────────────────────────────────────────────────────

    def get_queryset(self):
        qs        = super().get_queryset().select_related('category', 'supplier')
        form      = ProductFilterForm(self.request.GET)
        prod_store = self.request.GET.get('prod_store', '').strip()

        if form.is_valid():
            cd = form.cleaned_data
            if cd.get('search'):
                qs = qs.filter(
                    Q(name__icontains=cd['search'])        |
                    Q(sku__icontains=cd['search'])         |
                    Q(barcode__icontains=cd['search'])     |
                    Q(description__icontains=cd['search'])
                )
            if cd.get('category'):
                qs = qs.filter(category=cd['category'])
            if cd.get('supplier'):
                qs = qs.filter(supplier=cd['supplier'])
            if cd.get('tax_rate'):
                qs = qs.filter(tax_rate=cd['tax_rate'])
            if cd.get('is_active') in ('True', 'False'):
                qs = qs.filter(is_active=cd['is_active'] == 'True')
            if cd.get('min_price'):
                qs = qs.filter(selling_price__gte=cd['min_price'])
            if cd.get('max_price'):
                qs = qs.filter(selling_price__lte=cd['max_price'])

        # Annotate annotated_total_stock — optionally scoped to a single branch.
        # NOTE: Cannot use 'total_stock' here because Product already defines it
        # as a @property (no setter), which causes Django to raise an AttributeError
        # when it tries to set the annotated value on model instances.
        # Templates/code should reference 'annotated_total_stock' for the DB-computed sum.
        if prod_store:
            qs = qs.annotate(
                annotated_total_stock=Sum(
                    'store_inventory__quantity',
                    filter=Q(store_inventory__store_id=prod_store),
                )
            )
        else:
            qs = qs.annotate(annotated_total_stock=Sum('store_inventory__quantity'))

        return qs

    def _build_stock_queryset(self):
        req  = self.request
        qs   = Stock.objects.select_related(
            'product', 'product__category', 'product__supplier', 'store'
        ).prefetch_related('product__movements')

        status    = req.GET.get('status',    '')
        store     = req.GET.get('store',     '')
        category  = req.GET.get('category',  '')
        search    = req.GET.get('search',    '')
        sort      = req.GET.get('sort',      'name')
        date_from = req.GET.get('date_from', '')
        date_to   = req.GET.get('date_to',   '')

        if status == 'critical':
            qs = qs.filter(quantity=0)
        elif status == 'low_stock':
            qs = qs.filter(quantity__gt=0, quantity__lte=F('low_stock_threshold'))
        elif status == 'medium_stock':
            qs = qs.filter(
                quantity__gt=F('low_stock_threshold'),
                quantity__lte=F('low_stock_threshold') * 2,
            )
        elif status == 'good_stock':
            qs = qs.filter(quantity__gt=F('low_stock_threshold') * 2)

        if store:
            qs = qs.filter(store_id=store)
        if category:
            qs = qs.filter(product__category_id=category)

        if date_from:
            d = parse_date(date_from)
            if d:
                qs = qs.filter(last_updated__date__gte=d)
        if date_to:
            d = parse_date(date_to)
            if d:
                qs = qs.filter(last_updated__date__lte=d)

        if search:
            qs = qs.filter(
                Q(product__name__icontains=search)           |
                Q(product__sku__icontains=search)            |
                Q(product__barcode__icontains=search)        |
                Q(product__category__name__icontains=search) |
                Q(product__supplier__name__icontains=search) |
                Q(store__name__icontains=search)
            )

        sort_map = {
            'name':         'product__name',
            'name_desc':    '-product__name',
            'quantity':     'quantity',
            'quantity_desc':'-quantity',
            'value':        'product__cost_price',
            'value_desc':   '-product__cost_price',
            'updated':      '-last_updated',
            'store':        'store__name',
        }
        return qs.order_by(sort_map.get(sort, 'product__name'))

    def _build_category_queryset(self):
        search = self.request.GET.get('cat_search', '')
        status = self.request.GET.get('cat_status', '')
        qs     = Category.objects.all().order_by('name')
        if search:
            qs = qs.filter(
                Q(name__icontains=search)        |
                Q(code__icontains=search)        |
                Q(description__icontains=search)
            )
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)
        return qs

    def _build_supplier_queryset(self):
        search = self.request.GET.get('supp_search', '')
        status = self.request.GET.get('supp_status', '')
        qs     = Supplier.objects.all().order_by('name')
        if search:
            qs = qs.filter(
                Q(name__icontains=search)           |
                Q(tin__icontains=search)            |
                Q(contact_person__icontains=search) |
                Q(phone__icontains=search)
            )
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)
        return qs

    # ─────────────────────────────────────────────────────────────────────────
    #  Full-page context
    # ─────────────────────────────────────────────────────────────────────────

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        req     = self.request

        # ── Shared — evaluate once, reuse below to avoid duplicate queries ────
        context['filter_form'] = ProductFilterForm(req.GET)
        context['bulk_form']   = BulkActionForm()

        # Evaluate stores/categories once and cache on the queryset so Django's
        # template engine can iterate without re-hitting the DB.
        _stores_qs     = list(Store.objects.filter(is_active=True).order_by('name'))
        _categories_qs = list(Category.objects.filter(is_active=True).order_by('name'))
        context['stores']     = _stores_qs
        context['categories'] = _categories_qs

        # Flat product list for inline stock-adjustment modal dropdown
        context['products_for_adj'] = (
            Product.objects.filter(is_active=True).only('id', 'name', 'sku').order_by('name')
        )

        # EFRIS + VAT status exposed to template (product modal uses these)
        context['efris_enabled']       = _get_efris_enabled(req)
        context['company_vat_enabled'] = True
        company = _get_company(req)
        if company:
            context['company_vat_enabled'] = company.is_vat_enabled

        # Blank ProductForm — exposes unit_of_measure choices to the template
        # (avoids hardcoding choices in the modal; safe since it's never submitted)
        try:
            context['product_form'] = ProductForm(
                efris_enabled=context['efris_enabled'],
                company=company,
            )
        except Exception:
            context['product_form'] = None

        # Selected branch for products tab (used by branch-pill template logic)
        context['prod_store'] = req.GET.get('prod_store', '')

        # Reuse the already-evaluated list — no second DB query
        context['prod_stores'] = _stores_qs

        # Default store for modals (e.g. Quick Stock): prefer the active branch
        # filter, fall back to the first active store alphabetically.
        _prod_store_id = req.GET.get('prod_store', '')
        _default_store = next(
            (s for s in _stores_qs if str(s.id) == _prod_store_id), None
        ) or (_stores_qs[0] if _stores_qs else None)
        context['default_store_id'] = _default_store.id if _default_store else None

        # Per-branch stock breakdown: {store_id: {store, stock_items}}
        # Used by the branch columns in the product list table.
        # Only computed when no single branch is selected (shows all columns).
        if not context['prod_store']:
            branch_stocks = {}
            for store in context['prod_stores']:
                branch_stocks[store.id] = store
            context['branch_stocks'] = branch_stocks
        else:
            context['branch_stocks'] = {}

        # ── Dashboard KPI stats ───────────────────────────────────────────────
        stats = _get_stock_dashboard_stats(req)
        context.update(stats)

        # ── Products tab ──────────────────────────────────────────────────────
        # Use len() here — self.object_list has already been evaluated by get_queryset(),
        # so len() reads from the Python list rather than firing another COUNT(*) query.
        context['total_products'] = len(self.object_list)

        # ── Stock tab ─────────────────────────────────────────────────────────
        stock_qs    = self._build_stock_queryset()
        stock_pager = Paginator(stock_qs, 25)
        stock_page  = stock_pager.get_page(req.GET.get('stock_page', 1))
        _enhance_stock_items(stock_page.object_list)

        context['stock_items']     = stock_page.object_list
        context['stock_page']      = stock_page
        context['stock_paginator'] = stock_pager
        context['stock_paginated'] = stock_pager.num_pages > 1
        context['stock_filters']   = {
            'search':    req.GET.get('search',    ''),
            'status':    req.GET.get('status',    ''),
            'store':     req.GET.get('store',     ''),
            'category':  req.GET.get('category',  ''),
            'sort':      req.GET.get('sort',      'name'),
            'date_from': req.GET.get('date_from', ''),
            'date_to':   req.GET.get('date_to',   ''),
        }

        # Stock alerts (overview tab)
        context['stock_alerts'] = Stock.objects.select_related('product', 'store').filter(
            Q(quantity=0) | Q(quantity__lte=F('low_stock_threshold'))
        ).order_by('quantity', 'product__name')[:10]

        # Recent movements (overview tab)
        context['recent_movements'] = StockMovement.objects.select_related(
            'product', 'store', 'created_by'
        ).order_by('-created_at')[:15]

        # Chart: stock status distribution (doughnut)
        context['chart_data'] = {
            'stock_distribution': json.dumps({
                'labels': ['Out of Stock', 'Low Stock', 'Medium', 'Good'],
                'data': [
                    stats['out_of_stock_count'],
                    stats['low_stock_count'],
                    stats['medium_stock_count'],
                    stats['good_stock_count'],
                ],
            })
        }

        # Chart: top 8 categories by product count (horizontal bar)
        cat_chart_qs = (
            Category.objects
            .annotate(product_count_chart=Count('products'))
            .order_by('-product_count_chart')[:8]
        )
        context['category_chart_data'] = json.dumps({
            'labels': [c.name for c in cat_chart_qs],
            'data':   [c.product_count_chart for c in cat_chart_qs],
        })

        # ── Categories tab ────────────────────────────────────────────────────
        cat_qs    = self._build_category_queryset()
        cat_pager = Paginator(cat_qs, 20)
        cat_page  = cat_pager.get_page(req.GET.get('cat_page', 1))

        context['categories_list'] = cat_page.object_list
        context['cat_page']        = cat_page
        context['cat_paginator']   = cat_pager
        context['cat_paginated']   = cat_pager.num_pages > 1
        context['cat_search']      = req.GET.get('cat_search', '')
        context['cat_status']      = req.GET.get('cat_status', '')

        # ── Suppliers tab ─────────────────────────────────────────────────────
        supp_qs    = self._build_supplier_queryset()
        supp_pager = Paginator(supp_qs, 20)
        supp_page  = supp_pager.get_page(req.GET.get('supp_page', 1))

        context['suppliers']      = supp_page.object_list
        context['supp_page']      = supp_page
        context['supp_paginator'] = supp_pager
        context['supp_paginated'] = supp_pager.num_pages > 1
        context['supp_search']    = req.GET.get('supp_search', '')
        context['supp_status']    = req.GET.get('supp_status', '')

        # ── Scanner tab context ───────────────────────────────────────────────
        from inventory.models import BarcodeLabel, ScanSession
        context['pending_labels_count'] = BarcodeLabel.objects.filter(status='pending').count()
        context['active_scan_sessions'] = ScanSession.objects.filter(
            status='active', user=req.user
        ).count()
        context['scan_mode_url'] = req.build_absolute_uri('/inventory/scan/')
        import json as _json
        context['categories_json'] = _json.dumps(list(
            Category.objects.filter(is_active=True, category_type='product')
            .values('id', 'name').order_by('name')
        ))


        return context