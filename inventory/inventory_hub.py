"""
inventory/views/inventory_hub.py

Unified view replacing:
  - ProductListView      → inventory:product_list
  - CategoryListView     → inventory:category_list
  - StockListView        → inventory:stock_list
  - SupplierListView     → inventory:supplier_list

Wire up in urls.py:

    from inventory.views.inventory_hub import InventoryHubView

    path('', InventoryHubView.as_view(), name='product_list'),

All original URL names still work because the single view handles
everything via GET params (_tab, filters) and sub-paginators.
"""

import json
import logging
from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Avg, Count, F, Q, Sum
from django.utils.dateparse import parse_date
from django.views.generic import ListView

from inventory.forms import BulkActionForm, ProductFilterForm
from inventory.models import Category, Product, Stock, StockMovement, Supplier
from stores.models import Store

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _enhance_stock_items(stock_items):
    """Annotate each stock record with computed fields (mirrors StockListView)."""
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


def _get_stock_dashboard_stats(user_id):
    """Cache-backed stats for the Overview KPI cards (mirrors StockListView)."""
    cache_key = f"inv_hub_dashboard_stats_{user_id}"
    stats = cache.get(cache_key)
    if stats is not None:
        return stats

    qs = Stock.objects.select_related('product', 'store')

    values = qs.aggregate(
        total_cost_value   = Sum(F('quantity') * F('product__cost_price')),
        total_selling_value= Sum(F('quantity') * F('product__selling_price')),
        avg_stock_level    = Avg('quantity'),
    )

    out_of_stock  = qs.filter(quantity=0).count()
    low_stock     = qs.filter(quantity__gt=0, quantity__lte=F('low_stock_threshold')).count()
    medium_stock  = qs.filter(
        quantity__gt=F('low_stock_threshold'),
        quantity__lte=F('low_stock_threshold') * 2,
    ).count()
    good_stock    = qs.filter(quantity__gt=F('low_stock_threshold') * 2).count()

    cost_val  = values['total_cost_value']   or Decimal('0.00')
    sell_val  = values['total_selling_value'] or Decimal('0.00')

    stats = {
        'total_products':      qs.values('product').distinct().count(),
        'total_stock_records': qs.count(),
        'out_of_stock_count':  out_of_stock,
        'low_stock_count':     low_stock,
        'medium_stock_count':  medium_stock,
        'good_stock_count':    good_stock,
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
    Unified Inventory Hub.

    Uses Product as the primary model (drives the main ListView pagination),
    but also builds context for stock, categories, and suppliers.

    All four original list views are replaced by this single view.
    """
    model               = Product
    template_name       = 'inventory/inventory_hub.html'
    context_object_name = 'products'
    permission_required = 'inventory.view_product'
    paginate_by         = 25
    ordering            = ['name']

    # ── Products queryset (tab: products) ─────────────────────────────────────

    def get_queryset(self):
        qs   = super().get_queryset().select_related('category', 'supplier')
        form = ProductFilterForm(self.request.GET)
        if not form.is_valid():
            return qs

        cd = form.cleaned_data

        if cd.get('search'):
            s = cd['search']
            qs = qs.filter(
                Q(name__icontains=s)        |
                Q(sku__icontains=s)         |
                Q(barcode__icontains=s)     |
                Q(description__icontains=s)
            )
        if cd.get('category'):
            qs = qs.filter(category=cd['category'])
        if cd.get('supplier'):
            qs = qs.filter(supplier=cd['supplier'])
        if cd.get('tax_rate'):
            qs = qs.filter(tax_rate=cd['tax_rate'])
        if cd.get('is_active'):
            qs = qs.filter(is_active=(cd['is_active'] == 'True'))
        if cd.get('min_price'):
            qs = qs.filter(selling_price__gte=cd['min_price'])
        if cd.get('max_price'):
            qs = qs.filter(selling_price__lte=cd['max_price'])

        return qs

    # ── Stock queryset helpers ────────────────────────────────────────────────

    def _build_stock_queryset(self):
        req = self.request
        qs  = Stock.objects.select_related(
            'product', 'product__category', 'product__supplier', 'store'
        ).prefetch_related('product__movements')

        status   = req.GET.get('status',   '')
        store    = req.GET.get('store',    '')
        category = req.GET.get('category', '')
        search   = req.GET.get('search',   '')
        sort     = req.GET.get('sort',     'name')
        date_from= req.GET.get('date_from','')
        date_to  = req.GET.get('date_to',  '')

        # Status
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

        # Date filters
        if date_from:
            d = parse_date(date_from)
            if d:
                qs = qs.filter(last_updated__date__gte=d)
        if date_to:
            d = parse_date(date_to)
            if d:
                qs = qs.filter(last_updated__date__lte=d)

        # Search
        if search:
            qs = qs.filter(
                Q(product__name__icontains=search)          |
                Q(product__sku__icontains=search)           |
                Q(product__barcode__icontains=search)       |
                Q(product__category__name__icontains=search)|
                Q(product__supplier__name__icontains=search)|
                Q(store__name__icontains=search)
            )

        # Sorting
        sort_map = {
            'name':          'product__name',
            'name_desc':     '-product__name',
            'quantity':      'quantity',
            'quantity_desc': '-quantity',
            'value':         'product__cost_price',
            'value_desc':    '-product__cost_price',
            'updated':       '-last_updated',
            'store':         'store__name',
        }
        qs = qs.order_by(sort_map.get(sort, 'product__name'))
        return qs

    # ── Category queryset helpers ─────────────────────────────────────────────

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

    # ── Supplier queryset helpers ─────────────────────────────────────────────

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

    # ── Context ───────────────────────────────────────────────────────────────

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        req     = self.request

        # ── Shared ───────────────────────────────────────────────────────────
        context['filter_form'] = ProductFilterForm(req.GET)
        context['bulk_form']   = BulkActionForm()
        context['stores']      = Store.objects.filter(is_active=True).order_by('name')
        context['categories']  = Category.objects.filter(is_active=True).order_by('name')

        # ── Dashboard KPI stats ───────────────────────────────────────────────
        stats = _get_stock_dashboard_stats(req.user.id)
        context.update(stats)

        # ── Stock tab ─────────────────────────────────────────────────────────
        stock_qs      = self._build_stock_queryset()
        stock_pg_num  = req.GET.get('stock_page', 1)
        stock_pager   = Paginator(stock_qs, 25)
        stock_page    = stock_pager.get_page(stock_pg_num)

        # Enhance with computed fields
        _enhance_stock_items(stock_page.object_list)

        context['stock_items']      = stock_page.object_list
        context['stock_page']       = stock_page
        context['stock_paginator']  = stock_pager
        context['stock_paginated']  = stock_pager.num_pages > 1
        context['stock_filters']    = {
            'search':   req.GET.get('search',    ''),
            'status':   req.GET.get('status',    ''),
            'store':    req.GET.get('store',     ''),
            'category': req.GET.get('category',  ''),
            'sort':     req.GET.get('sort',      'name'),
            'date_from':req.GET.get('date_from', ''),
            'date_to':  req.GET.get('date_to',   ''),
        }

        # Stock alerts (overview tab)
        context['stock_alerts'] = Stock.objects.select_related(
            'product', 'store'
        ).filter(
            Q(quantity=0) | Q(quantity__lte=F('low_stock_threshold'))
        ).order_by('quantity', 'product__name')[:10]

        # Recent movements (overview tab)
        context['recent_movements'] = StockMovement.objects.select_related(
            'product', 'store', 'created_by'
        ).order_by('-created_at')[:15]

        # Chart data: stock distribution donut
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

        # Category chart data (top 8 by product count)
        # Note: annotation is named 'product_count_chart' to avoid clashing with
        # the read-only @property 'product_count' defined on the Category model.
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
        cat_qs     = self._build_category_queryset()
        cat_pg_num = req.GET.get('cat_page', 1)
        cat_pager  = Paginator(cat_qs, 20)
        cat_page   = cat_pager.get_page(cat_pg_num)

        context['categories_list'] = cat_page.object_list
        context['cat_page']        = cat_page
        context['cat_paginator']   = cat_pager
        context['cat_paginated']   = cat_pager.num_pages > 1
        context['cat_search']      = req.GET.get('cat_search', '')
        context['cat_status']      = req.GET.get('cat_status', '')

        # ── Suppliers tab ─────────────────────────────────────────────────────
        supp_qs    = self._build_supplier_queryset()
        supp_pg_num= req.GET.get('supp_page', 1)
        supp_pager = Paginator(supp_qs, 20)
        supp_page  = supp_pager.get_page(supp_pg_num)

        context['suppliers']        = supp_page.object_list
        context['supp_page']        = supp_page
        context['supp_paginator']   = supp_pager
        context['supp_paginated']   = supp_pager.num_pages > 1
        context['supp_search']      = req.GET.get('supp_search', '')
        context['supp_status']      = req.GET.get('supp_status', '')

        return context