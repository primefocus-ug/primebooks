"""
sales/sales_hub.py

Combined view that replaces:
  - SalesListView  (was a ListView at sales:sales_list)
  - sales_analytics (was a function-based view at sales:sales_analytics)

Wire it up in urls.py like this:

    from sales.views.sales_hub import SalesHubView

    path('', SalesHubView.as_view(), name='sales_list'),

The view responds to the same URL for both GET (render) and POST (exports /
bulk actions), so no URL changes are needed for the rest of the codebase.
"""

import csv
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, Min, Q, Sum
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import get_template
from django.utils import timezone
from django.views.generic import ListView

from sales.forms import BulkActionForm, SaleSearchForm
from sales.models import Sale, SaleItem
from stores.models import Store
from stores.utils import validate_store_access,get_user_accessible_stores

try:
    import xlsxwriter
    XLSXWRITER_AVAILABLE = True
except ImportError:
    XLSXWRITER_AVAILABLE = False

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
#  Helper: build analytics context (previously sales_analytics logic)
# ─────────────────────────────────────────────────────────────────────────────

def _build_analytics_context(request, base_qs, accessible_stores, date_from, date_to, store_id):
    """
    Compute all chart / analytics data from the supplied base queryset.
    Returns a dict that is merged into the main template context.
    """
    sales_qs = base_qs.filter(
        transaction_type='SALE',
        is_voided=False,
    )

    stores = accessible_stores.order_by('name')

    # ── Core metrics ──────────────────────────────────────────────────────────
    total_sales    = sales_qs.count()
    total_revenue  = sales_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')
    avg_sale_value = sales_qs.aggregate(Avg('total_amount'))['total_amount__avg']  or Decimal('0')

    total_customers = sales_qs.values('customer').distinct().count()
    if total_customers == 0 and total_sales > 0:
        total_customers = total_sales  # walk-in fallback

    # ── Payment methods ───────────────────────────────────────────────────────
    payment_methods_raw = sales_qs.values('payment_method').annotate(
        count=Count('id'),
        total=Sum('total_amount'),
    ).order_by('-total')

    payment_methods = []
    for pm in payment_methods_raw:
        pct = (pm['total'] / total_revenue * 100) if total_revenue else 0
        payment_methods.append({
            'payment_method':         pm['payment_method'],
            'payment_method_display': dict(Sale.PAYMENT_METHODS).get(
                pm['payment_method'], pm['payment_method']
            ),
            'count':      pm['count'],
            'total':      float(pm['total'] or 0),
            'percentage': round(float(pct), 1),
        })

    # ── Daily trend ───────────────────────────────────────────────────────────
    # B11 fix: replace deprecated .extra() with TruncDate
    from django.db.models.functions import TruncDate
    daily_raw = (
        sales_qs
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(count=Count('id'), total=Sum('total_amount'))
        .order_by('day')
    )

    # B15 fix: only compute growth for consecutive days to avoid wrong % from gaps
    from datetime import date as _date
    daily_sales = []
    prev_day   = None
    prev_total = None
    for d in daily_raw:
        day_total = float(d['total'] or 0)
        day_count = d['count'] or 0
        cur_day   = d['day'] if isinstance(d['day'], _date) else _date.fromisoformat(str(d['day']))
        consecutive = (
            prev_day is not None and prev_total is not None
            and prev_total > 0
            and (cur_day - prev_day).days == 1
        )
        growth = f"{((day_total - prev_total) / prev_total * 100):+.1f}%" if consecutive else '+0.0%'
        daily_sales.append({
            'day':       str(cur_day),
            'count':     day_count,
            'total':     day_total,
            'avg_value': day_total / day_count if day_count else 0,
            'growth':    growth,
        })
        prev_total = day_total
        prev_day   = cur_day

    # ── Top items (products + services) ──────────────────────────────────────
    top_products = (
        SaleItem.objects
        .filter(sale__in=sales_qs, item_type='PRODUCT', product__isnull=False)
        .select_related('product')
        .values('product__id', 'product__name', 'product__sku')
        .annotate(
            quantity_sold=Sum('quantity'),
            revenue=Sum('total_price'),
            sale_count=Count('sale', distinct=True),
        )
        .order_by('-revenue')[:10]
    )

    top_services = (
        SaleItem.objects
        .filter(sale__in=sales_qs, item_type='SERVICE', service__isnull=False)
        .select_related('service')
        .values('service__id', 'service__name', 'service__code')
        .annotate(
            quantity_sold=Sum('quantity'),
            revenue=Sum('total_price'),
            sale_count=Count('sale', distinct=True),
        )
        .order_by('-revenue')[:10]
    )

    top_items = []
    for p in top_products:
        top_items.append({
            'id':            p['product__id'],
            'name':          p['product__name'],
            'code':          p['product__sku'],
            'item_type':     'PRODUCT',
            'quantity_sold': float(p['quantity_sold'] or 0),
            'revenue':       float(p['revenue'] or 0),
            'sale_count':    p['sale_count'],
        })
    for s in top_services:
        top_items.append({
            'id':            s['service__id'],
            'name':          s['service__name'],
            'code':          s['service__code'],
            'item_type':     'SERVICE',
            'quantity_sold': float(s['quantity_sold'] or 0),
            'revenue':       float(s['revenue'] or 0),
            'sale_count':    s['sale_count'],
        })

    top_items.sort(key=lambda x: x['revenue'], reverse=True)
    top_items = top_items[:10]
    max_rev = top_items[0]['revenue'] if top_items else 1
    for item in top_items:
        item['performance_percentage'] = round(item['revenue'] / max_rev * 100, 1) if max_rev else 0

    # ── Hourly pattern ────────────────────────────────────────────────────────
    # B11 fix: replace deprecated .extra() with ExtractHour
    from django.db.models.functions import ExtractHour
    hourly_raw = (
        sales_qs
        .annotate(hour=ExtractHour('created_at'))
        .values('hour')
        .annotate(count=Count('id'), total=Sum('total_amount'))
        .order_by('hour')
    )
    hourly_map = {int(h['hour']): h for h in hourly_raw}
    hourly_sales = [
        {
            'hour':  hr,
            'count': hourly_map.get(hr, {}).get('count', 0),
            'total': float(hourly_map.get(hr, {}).get('total') or 0),
        }
        for hr in range(24)
    ]

    # ── Period-over-period growth ─────────────────────────────────────────────
    period_len = (date_to - date_from).days + 1
    prev_start = date_from - timedelta(days=period_len)
    prev_end   = date_from - timedelta(days=1)

    prev_qs = Sale.objects.filter(
        store__in=accessible_stores,
        created_at__date__gte=prev_start,
        created_at__date__lte=prev_end,
        transaction_type='SALE',
        is_voided=False,
    )
    if store_id:
        prev_qs = prev_qs.filter(store_id=store_id)

    prev_revenue = prev_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')
    if prev_revenue > 0:
        growth_pct     = (total_revenue - prev_revenue) / prev_revenue * 100
        sales_growth   = f'{growth_pct:+.1f}%'
    else:
        sales_growth = '+0.0%'

    # ── New customers ─────────────────────────────────────────────────────────
    new_customers = (
        sales_qs
        .filter(customer__isnull=False)
        .values('customer')
        .annotate(first_sale=Min('created_at'))
        .filter(first_sale__date__gte=date_from, first_sale__date__lte=date_to)
        .count()
    )

    # ── Return rate ───────────────────────────────────────────────────────────
    refund_qs = Sale.objects.filter(
        store__in=accessible_stores,
        created_at__date__gte=date_from,
        created_at__date__lte=date_to,
        transaction_type='REFUND',
    )
    if store_id:
        refund_qs = refund_qs.filter(store_id=store_id)

    refund_amount = refund_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')
    return_rate   = f'{abs(refund_amount) / total_revenue * 100:.1f}%' if total_revenue else '0.0%'

    # ── Store performance ─────────────────────────────────────────────────────
    store_performance = list(
        sales_qs
        .values('store__id', 'store__name')
        .annotate(
            sales_count=Count('id'),
            revenue=Sum('total_amount'),
            avg_sale_value=Avg('total_amount'),
        )
        .order_by('-revenue')
    )
    # Make Decimal JSON-serialisable and normalise key name
    for sp in store_performance:
        sp['total_amount']    = float(sp.pop('revenue') or 0)
        sp['avg_sale_value']  = float(sp['avg_sale_value'] or 0)

    # ── Payment efficiency ────────────────────────────────────────────────────
    payment_efficiency = list(
        sales_qs
        .values('payment_method')
        .annotate(avg_amount=Avg('total_amount'), count=Count('id'))
        .order_by('-avg_amount')
    )

    # ── Item type breakdown ───────────────────────────────────────────────────
    item_type_breakdown = list(
        SaleItem.objects
        .filter(sale__in=sales_qs)
        .values('item_type')
        .annotate(
            count=Count('id'),
            total_quantity=Sum('quantity'),
            total_revenue=Sum('total_price'),
        )
        .order_by('-total_revenue')
    )
    for itb in item_type_breakdown:
        itb['total_revenue']  = float(itb['total_revenue'] or 0)
        itb['total_quantity'] = float(itb['total_quantity'] or 0)

    # ── Store stats — B13 fix: single annotated query instead of N+1 per store ──
    store_agg_map = {
        row['store_id']: row
        for row in sales_qs.values('store_id').annotate(
            sales_count=Count('id'),
            revenue=Sum('total_amount'),
        )
    }
    store_stats = []
    for store in stores:
        cfg     = store.effective_efris_config
        agg_row = store_agg_map.get(store.id, {})
        store_stats.append({
            'id':               store.id,
            'name':             store.name,
            'sales_count':      agg_row.get('sales_count', 0),
            'revenue':          float(agg_row.get('revenue') or 0),
            'efris_enabled':    cfg.get('enabled', False),
            'efris_active':     cfg.get('is_active', False),
            'allows_sales':     store.allows_sales,
            'allows_inventory': store.allows_inventory,
            'is_main_branch':   store.is_main_branch,
        })

    return {
        # Core metrics
        'total_sales':     total_sales,
        'total_revenue':   total_revenue,
        'avg_sale_value':  avg_sale_value,
        'total_customers': total_customers,
        # Chart data (JSON-safe)
        'payment_methods': payment_methods,
        'daily_sales':     daily_sales,
        'top_items':       top_items,
        'hourly_sales':    hourly_sales,
        # Insights
        'sales_growth':    sales_growth,
        'new_customers':   new_customers,
        'return_rate':     return_rate,
        # Filter options
        'stores':          stores,
        'store_stats':     store_stats,
        'selected_store':  store_id,
        # Additional analytics
        'store_performance':    store_performance,
        'payment_efficiency':   payment_efficiency,
        'item_type_breakdown':  item_type_breakdown,
        'period_days':          period_len,
        'has_multiple_stores':  stores.count() > 1,
        'date_from':            date_from,
        'date_to':              date_to,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  Main view
# ─────────────────────────────────────────────────────────────────────────────

class SalesHubView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """
    Unified Sales Hub — combines the sales list with live analytics.

    GET  → renders sales_dashboard.html with list + analytics context
           If the request carries  X-Requested-With: XMLHttpRequest  (set by
           the JS loadSales() function), only the lightweight partial template
           is rendered — no charts, no analytics — so the browser swaps just
           the #salesPane div without a full page reload.
    POST → handles exports (action=export_csv / export_excel / export_pdf)
           or delegates to bulk_actions()
    """
    model                = Sale
    template_name        = 'sales/sales_dashboard.html'
    partial_template_name = 'sales/sales_list_partial.html'   # ← AJAX partial
    context_object_name  = 'sales'
    paginate_by          = 25
    permission_required  = 'sales.view_sale'

    # ── GET — detect AJAX and serve partial ──────────────────────────────────

    def get(self, request, *args, **kwargs):
        # Standard ListView setup (populates self.object_list, self.kwargs, etc.)
        self.object_list = self.get_queryset()
        allow_empty = self.get_allow_empty()
        if not allow_empty and len(self.object_list) == 0:
            raise Http404

        if self._is_ajax():
            # AJAX request from loadSales() — serve a lightweight partial.
            # We still call get_context_data() so pagination, stats and form
            # are all correct, but we skip the heavy _build_analytics_context
            # by passing a flag the method can check.
            context = self._get_list_context()
            return render(request, self.partial_template_name, context)

        # Normal full-page render
        context = self.get_context_data()
        return render(request, self.template_name, context)

    def _is_ajax(self):
        """True when the JS fetch() sends  X-Requested-With: XMLHttpRequest."""
        return self.request.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _get_list_context(self):
        """
        Lightweight context for the AJAX partial — only the data the sales
        table and pagination need.  Skips all chart/analytics computation.
        """
        request    = self.request
        accessible = get_user_accessible_stores(request.user)

        # Paginate exactly as ListView.get_context_data() would
        paginator, page, queryset, is_paginated = self.paginate_queryset(
            self.object_list, self.paginate_by
        )

        search_form = SaleSearchForm(request.GET)
        if search_form.fields.get('store'):
            search_form.fields['store'].queryset = accessible

        context = {
            self.context_object_name: queryset,   # 'sales'
            'paginator':      paginator,
            'page_obj':       page,
            'is_paginated':   is_paginated,
            'search_form':    search_form,
            'bulk_form':      BulkActionForm(),
            'efris_enabled':  any(
                store.effective_efris_config.get('enabled', False)
                for store in accessible
            ),
        }

        # Minimal stats needed by the partial toolbar / bulk bar
        from django.core.cache import cache
        from django.utils import timezone as _tz
        from django.db.models import Count, Sum, Q

        list_qs   = Sale.objects.filter(pk__in=self.object_list.values('pk'))
        date_str  = _tz.now().strftime('%Y-%m-%d')
        store_ids = '_'.join(str(s.id) for s in accessible)
        cache_key = f'hub_stats:{store_ids}:{date_str}'

        agg = cache.get(cache_key)
        if agg is None:
            agg = list_qs.aggregate(
                total_sales_count=Count('id'),
                total_sales_amount=Sum('total_amount', default=0),
                total_credit_amount=Sum('total_amount',
                    filter=Q(document_type='INVOICE', payment_method='CREDIT')),
                fiscalized_count=Count('id', filter=Q(is_fiscalized=True)),
                receipt_count=Count('id', filter=Q(document_type='RECEIPT')),
                invoice_count=Count('id', filter=Q(document_type='INVOICE')),
                proforma_count=Count('id', filter=Q(document_type='PROFORMA')),
                overdue_count=Count('id', filter=Q(payment_status='OVERDUE')),
                overdue_amount=Sum('total_amount', filter=Q(payment_status='OVERDUE')),
                credit_pending_count=Count('id', filter=Q(
                    document_type='INVOICE', payment_method='CREDIT',
                    payment_status__in=['PENDING', 'PARTIALLY_PAID'])),
                credit_paid_count=Count('id', filter=Q(
                    document_type='INVOICE', payment_method='CREDIT',
                    payment_status='PAID')),
            )
            cache.set(cache_key, agg, 60)

        context['stats'] = {
            'total_sales':         agg.get('total_sales_count', 0),
            'total_amount':        agg.get('total_sales_amount', 0),
            'total_credit_amount': agg.get('total_credit_amount', 0),
            'fiscalized_count':    agg.get('fiscalized_count', 0),
            'receipt_count':       agg.get('receipt_count', 0),
            'invoice_count':       agg.get('invoice_count', 0),
            'proforma_count':      agg.get('proforma_count', 0),
        }
        context['credit_stats'] = {
            'total_credit_invoices': agg.get('invoice_count', 0),
            'total_credit_amount':   agg.get('total_credit_amount', 0),
            'overdue_count':         agg.get('overdue_count', 0),
            'overdue_amount':        agg.get('overdue_amount', 0),
            'pending_count':         agg.get('credit_pending_count', 0),
            'paid_count':            agg.get('credit_paid_count', 0),
        }

        return context

    # ── POST dispatcher ───────────────────────────────────────────────────────

    def post(self, request, *args, **kwargs):
        action = request.POST.get('action', '')
        if action.startswith('export_'):
            return self._handle_export(request, action)
        return bulk_actions(request)

    def _handle_export(self, request, action):
        export_format = action.replace('export_', '')
        try:
            selected_json = request.POST.get('selected_sales')
            if selected_json:
                try:
                    ids   = json.loads(selected_json)
                    sales = Sale.objects.filter(id__in=ids)
                except json.JSONDecodeError:
                    sales = self._export_queryset(request)
            else:
                sales = self._export_queryset(request)

            accessible = get_user_accessible_stores(request.user)
            sales = (
                sales
                .filter(store__in=accessible)
                .select_related('store', 'customer', 'created_by')
                .prefetch_related('items', 'payments')
                .order_by('-created_at')
            )

            if export_format == 'csv':
                return self._export_csv(sales)
            elif export_format == 'excel':
                return self._export_excel(sales)
            elif export_format == 'pdf':
                return self._export_pdf(sales)
            else:
                messages.error(request, 'Invalid export format')
                return redirect('sales:sales_list')

        except Exception as exc:
            logger.error(f'Export error: {exc}', exc_info=True)
            messages.error(request, f'Export failed: {exc}')
            return redirect('sales:sales_list')

    def _export_queryset(self, request):
        """Reconstruct queryset from POST filter params (mirrors GET filters)."""
        accessible = get_user_accessible_stores(request.user)
        qs = Sale.objects.filter(store__in=accessible)

        def post(key):
            return request.POST.get(key, '').strip()

        search = post('search')
        if search:
            qs = qs.filter(
                Q(document_number__icontains=search)
                | Q(transaction_id__icontains=search)
                | Q(customer__name__icontains=search)
                | Q(customer__phone__icontains=search)
                | Q(efris_invoice_number__icontains=search)
            )

        for field, lookup in [
            ('store',            'store_id'),
            ('transaction_type', 'transaction_type'),
            ('payment_method',   'payment_method'),
            ('document_type',    'document_type'),
            ('payment_status',   'payment_status'),
            ('status',           'status'),
        ]:
            val = post(field)
            if val:
                qs = qs.filter(**{lookup: val})

        for date_field, lookup in [('date_from', 'created_at__date__gte'), ('date_to', 'created_at__date__lte')]:
            val = post(date_field)
            if val:
                try:
                    qs = qs.filter(**{lookup: val})
                except Exception:
                    pass

        for amt_field, lookup in [('min_amount', 'total_amount__gte'), ('max_amount', 'total_amount__lte')]:
            val = post(amt_field)
            if val:
                try:
                    qs = qs.filter(**{lookup: Decimal(val)})
                except Exception:
                    pass

        is_fisc = post('is_fiscalized')
        if is_fisc:
            qs = qs.filter(is_fiscalized=(is_fisc == '1'))

        return qs

    # ── GET queryset (list tab) ───────────────────────────────────────────────

    def get_queryset(self):
        accessible = get_user_accessible_stores(self.request.user)
        qs = (
            Sale.objects
            .filter(store__in=accessible)
            .select_related('store', 'customer', 'created_by')
            .prefetch_related('items', 'payments')
        )

        form = SaleSearchForm(self.request.GET)
        if not form.is_valid():
            return qs.order_by('-created_at')

        cd = form.cleaned_data

        search = cd.get('search')
        if search:
            qs = qs.filter(
                Q(document_number__icontains=search)
                | Q(transaction_id__icontains=search)
                | Q(customer__name__icontains=search)
                | Q(customer__phone__icontains=search)
                | Q(efris_invoice_number__icontains=search)
                | Q(store__name__icontains=search)
            )

        store = cd.get('store')
        if store:
            # B14 fix: don't use `in accessible` — it calls QuerySet.__contains__ (DB query)
            if accessible.filter(id=store.id).exists():
                qs = qs.filter(store=store)
            else:
                messages.warning(
                    self.request,
                    f"You don't have access to store '{store.name}'. Filter ignored."
                )

        simple_filters = {
            'transaction_type': 'transaction_type',
            'payment_method':   'payment_method',
            'document_type':    'document_type',
            'payment_status':   'payment_status',
            'status':           'status',
        }
        for form_field, model_field in simple_filters.items():
            val = cd.get(form_field)
            if val:
                qs = qs.filter(**{model_field: val})

        date_from = cd.get('date_from')
        if date_from:
            qs = qs.filter(created_at__date__gte=date_from)

        date_to = cd.get('date_to')
        if date_to:
            qs = qs.filter(created_at__date__lte=date_to)

        min_amount = cd.get('min_amount')
        if min_amount:
            qs = qs.filter(total_amount__gte=min_amount)

        max_amount = cd.get('max_amount')
        if max_amount:
            qs = qs.filter(total_amount__lte=max_amount)

        is_fisc = cd.get('is_fiscalized')
        if is_fisc:
            qs = qs.filter(is_fiscalized=(is_fisc == '1'))

        credit_status = cd.get('credit_status')
        if credit_status == 'CREDIT':
            qs = qs.filter(document_type='INVOICE', payment_method='CREDIT')
        elif credit_status == 'OVERDUE':
            qs = qs.filter(document_type='INVOICE', payment_status='OVERDUE')
        elif credit_status == 'OUTSTANDING':
            qs = qs.filter(
                document_type='INVOICE',
                payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE'],
            )

        return qs.order_by('-created_at')

    # ── Context ───────────────────────────────────────────────────────────────

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        request     = self.request
        accessible  = get_user_accessible_stores(request.user)

        # ── Search form ───────────────────────────────────────────────────────
        search_form = SaleSearchForm(request.GET)
        if search_form.fields.get('store'):
            search_form.fields['store'].queryset = accessible
        context['search_form'] = search_form
        context['bulk_form']   = BulkActionForm()

        # ── EFRIS flag ────────────────────────────────────────────────────────
        context['efris_enabled'] = any(
            store.effective_efris_config.get('enabled', False)
            for store in accessible
        )

        # ── Date range for analytics (defaults to last 30 days) ───────────────
        raw_from = request.GET.get('date_from')
        raw_to   = request.GET.get('date_to')

        try:
            date_from = datetime.strptime(raw_from, '%Y-%m-%d').date() if raw_from else (
                timezone.now().date() - timedelta(days=30)
            )
        except ValueError:
            date_from = timezone.now().date() - timedelta(days=30)

        try:
            date_to = datetime.strptime(raw_to, '%Y-%m-%d').date() if raw_to else timezone.now().date()
        except ValueError:
            date_to = timezone.now().date()

        if date_from > date_to:
            date_from, date_to = date_to, date_from

        # ── Store filter for analytics ────────────────────────────────────────
        store_id = request.GET.get('store') or None
        if store_id:
            try:
                store_obj = Store.objects.get(id=store_id)
                try:
                    validate_store_access(request.user, store_obj, action='view', raise_exception=True)
                except PermissionDenied:
                    messages.error(request, 'Access denied to selected store.')
                    store_id = None
            except Store.DoesNotExist:
                store_id = None

        # ── Base analytics queryset (date-filtered, NO prefetch) ────────────
        # No select_related/prefetch_related — the analytics helper uses
        # .values().annotate() and prefetch annotations cause:
        # "Cannot compute Avg: total_amount is an aggregate"
        analytics_qs = Sale.objects.filter(
            store__in=accessible,
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )
        if store_id:
            analytics_qs = analytics_qs.filter(store_id=store_id)

        # ── Build analytics context ───────────────────────────────────────────
        try:
            analytics_ctx = _build_analytics_context(
                request, analytics_qs, accessible, date_from, date_to, store_id
            )
            context.update(analytics_ctx)
        except Exception as exc:
            logger.error(f'Analytics context error: {exc}', exc_info=True)
            context.update({
                'total_sales': 0, 'total_revenue': Decimal('0'),
                'avg_sale_value': Decimal('0'), 'total_customers': 0,
                'payment_methods': [], 'daily_sales': [], 'top_items': [],
                'hourly_sales': [], 'sales_growth': '+0.0%',
                'new_customers': 0, 'return_rate': '0.0%',
                'store_performance': [], 'payment_efficiency': [],
                'item_type_breakdown': [], 'period_days': 30,
                'date_from': date_from, 'date_to': date_to,
            })

        # ── List-tab summary stats ────────────────────────────────────────────
        # Strip select_related/prefetch_related — prefetch annotations
        # conflict with .annotate(Sum/Avg/Count) and raise FieldError.
        # B12+B16 fix: use self.object_list (ListView already evaluated it) instead
        # of calling get_queryset() a second time. Replace ~20 individual queries
        # with a single .aggregate() cached for 60 seconds per store-set per day.
        from django.core.cache import cache
        from django.utils import timezone as _tz

        # The correct fix for "total_amount is an aggregate" FieldError:
        # self.object_list may carry annotations from get_queryset() or Django's
        # pagination pipeline. select_related(None)/prefetch_related(None) do NOT
        # remove annotations — they poison subsequent .aggregate() calls.
        # Solution: rebuild a clean queryset using the same PKs as a subquery.
        # This gives us a zero-annotation base safe for all aggregate operations.
        list_qs = Sale.objects.filter(
            pk__in=self.object_list.values('pk')
        )
        date_str  = _tz.now().strftime('%Y-%m-%d')
        store_ids = '_'.join(str(s.id) for s in accessible)
        cache_key = f'hub_stats:{store_ids}:{date_str}'

        agg = cache.get(cache_key)
        if agg is None:
            agg = list_qs.aggregate(
                total_sales_count=Count('id'),  # Changed from total_sales
                total_sales_amount=Sum('total_amount', default=0),  # Changed from total_amount
                total_credit_amount=Sum('total_amount',
                                        filter=Q(document_type='INVOICE', payment_method='CREDIT')),
                fiscalized_count=Count('id', filter=Q(is_fiscalized=True)),
                receipt_count=Count('id', filter=Q(document_type='RECEIPT')),
                invoice_count=Count('id', filter=Q(document_type='INVOICE')),
                proforma_count=Count('id', filter=Q(document_type='PROFORMA')),
                estimate_count=Count('id', filter=Q(document_type='ESTIMATE')),
                overdue_count=Count('id', filter=Q(payment_status='OVERDUE')),
                overdue_amount=Sum('total_amount', filter=Q(payment_status='OVERDUE')),
                credit_pending_count=Count('id', filter=Q(
                    document_type='INVOICE', payment_method='CREDIT',
                    payment_status__in=['PENDING', 'PARTIALLY_PAID'])),
                credit_paid_count=Count('id', filter=Q(
                    document_type='INVOICE', payment_method='CREDIT',
                    payment_status='PAID')),
                avg_credit_amount=Avg('total_amount', filter=Q(
                    document_type='INVOICE', payment_method='CREDIT')),
            )
            cache.set(cache_key, agg, 60)

        # Update to use the new keys
        total_sales_count = agg.get('total_sales_count', 0)  # Changed from total_sales
        total_sales_amount = agg.get('total_sales_amount', 0)  # Changed from total_amount

        context['stats'] = {
            'total_sales': total_sales_count,  # Keep template var name, use new value
            'total_amount': total_sales_amount,  # Keep template var name, use new value
            'total_credit_amount': agg.get('total_credit_amount', 0),
            'fiscalized_count': agg.get('fiscalized_count', 0),
            'receipt_count': agg.get('receipt_count', 0),
            'invoice_count': agg.get('invoice_count', 0),
            'proforma_count': agg.get('proforma_count', 0),
            'estimate_count': agg.get('estimate_count', 0),
        }

        context['credit_stats'] = {
            'total_credit_invoices': agg.get('invoice_count', 0),
            'total_credit_amount': agg.get('total_credit_amount', 0),
            'overdue_count': agg.get('overdue_count', 0),
            'overdue_amount': agg.get('overdue_amount', 0),
            'pending_count': agg.get('credit_pending_count', 0),
            'paid_count': agg.get('credit_paid_count', 0),
            'avg_credit_amount': agg.get('avg_credit_amount', 0),
        }

        # Document type distribution — 1 query, cached 60 s
        doc_key = f'hub_doc_stats:{store_ids}:{date_str}'
        doc_raw = cache.get(doc_key)
        if doc_raw is None:
            doc_raw = list(list_qs.values('document_type').annotate(
                count=Count('id'), total=Sum('total_amount')
            ).order_by('-count'))
            cache.set(doc_key, doc_raw, 60)

        context['document_type_stats'] = [
            {
                'type': s['document_type'],
                'type_display': dict(Sale.DOCUMENT_TYPE_CHOICES).get(s['document_type'], s['document_type']),
                'count': s['count'],
                'total': s['total'] or 0,
                'percentage': round(s['count'] / (total_sales_count or 1) * 100, 1),  # Updated here
            }
            for s in doc_raw
        ]

        # Payment status distribution
        ps_key = f'hub_ps_stats:{store_ids}:{date_str}'
        ps_raw = cache.get(ps_key)
        if ps_raw is None:
            ps_raw = list(list_qs.values('payment_status').annotate(
                count=Count('id'), total=Sum('total_amount')
            ).order_by('-count'))
            cache.set(ps_key, ps_raw, 60)

        context['payment_status_stats'] = [
            {
                'status': s['payment_status'],
                'status_display': dict(Sale.PAYMENT_STATUS_CHOICES).get(s['payment_status'], s['payment_status']),
                'count': s['count'],
                'total': s['total'] or 0,
            }
            for s in ps_raw
        ]

        # EFRIS stats — reuse agg, no extra DB query
        if agg.get('fiscalized_count', 0):
            efris_key = f'hub_efris_latest:{store_ids}'
            latest = cache.get(efris_key)
            if latest is None:
                latest = (
                    list_qs.filter(is_fiscalized=True)
                    .order_by('-fiscalization_time')
                    .only('id', 'document_number', 'fiscalization_time')
                    .first()
                )
                cache.set(efris_key, latest, 120)
            context['efris_stats'] = {
                'count': agg.get('fiscalized_count', 0),
                'total_amount': agg.get('total_sales_amount', 0),  # Updated here
                'latest_fiscalized': latest,
            }

        # Top credit customers
        top_key = f'hub_top_cust:{store_ids}:{date_str}'
        top_credit = cache.get(top_key)
        if top_credit is None:
            top_credit = list(
                list_qs
                .filter(document_type='INVOICE', payment_method='CREDIT')
                .values('customer__id', 'customer__name', 'customer__phone')
                .annotate(
                    invoice_count=Count('id'),
                    total_credit=Sum('total_amount'),
                    outstanding_count=Count(
                        'id', filter=Q(payment_status__in=['PENDING', 'PARTIALLY_PAID', 'OVERDUE'])
                    ),
                )
                .order_by('-total_credit')[:5]
            )
            cache.set(top_key, top_credit, 120)
        context['top_credit_customers'] = top_credit

        # ── Accessible stores ─────────────────────────────────────────────────
        context['accessible_stores'] = accessible

        return context
    # ── Export helpers ────────────────────────────────────────────────────────

    def _export_csv(self, sales):
        ts = timezone.now().strftime('%Y%m%d_%H%M%S')
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="sales_export_{ts}.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'Document Number', 'Document Type', 'Date', 'Time', 'Customer', 'Phone',
            'Store', 'Payment Method', 'Subtotal', 'Tax', 'Discount', 'Total',
            'Payment Status', 'Status', 'Fiscalized', 'EFRIS Invoice',
        ])
        for s in sales:
            writer.writerow([
                s.document_number or '',
                s.get_document_type_display(),
                s.created_at.strftime('%Y-%m-%d'),
                s.created_at.strftime('%H:%M:%S'),
                s.customer.name if s.customer else 'Walk-in',
                s.customer.phone if s.customer else '',
                s.store.name,
                s.get_payment_method_display(),
                float(s.subtotal),
                float(s.tax_amount),
                float(s.discount_amount),
                float(s.total_amount),
                s.get_payment_status_display(),
                s.get_status_display(),
                'Yes' if s.is_fiscalized else 'No',
                s.efris_invoice_number or '',
            ])
        return response

    def _export_excel(self, sales):
        if not XLSXWRITER_AVAILABLE:
            messages.error(self.request, 'Excel export requires xlsxwriter. Please contact administrator.')
            return redirect('sales:sales_list')

        output   = BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        ws       = workbook.add_worksheet('Sales Export')

        hdr_fmt  = workbook.add_format({'bold': True, 'bg_color': '#2563eb', 'color': 'white',
                                        'border': 1, 'align': 'center', 'valign': 'vcenter'})
        cur_fmt  = workbook.add_format({'num_format': '#,##0.00'})
        date_fmt = workbook.add_format({'num_format': 'yyyy-mm-dd'})
        time_fmt = workbook.add_format({'num_format': 'hh:mm:ss'})

        headers = [
            'Document Number', 'Document Type', 'Date', 'Time', 'Customer', 'Phone',
            'Store', 'Payment Method', 'Subtotal', 'Tax', 'Discount', 'Total',
            'Payment Status', 'Status', 'Fiscalized', 'EFRIS Invoice',
        ]
        for col, h in enumerate(headers):
            ws.write(0, col, h, hdr_fmt)

        for row, s in enumerate(sales, 1):
            ws.write(row, 0,  s.document_number or '')
            ws.write(row, 1,  s.get_document_type_display())
            ws.write(row, 2,  s.created_at.strftime('%Y-%m-%d'), date_fmt)
            ws.write(row, 3,  s.created_at.strftime('%H:%M:%S'), time_fmt)
            ws.write(row, 4,  s.customer.name if s.customer else 'Walk-in')
            ws.write(row, 5,  s.customer.phone if s.customer else '')
            ws.write(row, 6,  s.store.name)
            ws.write(row, 7,  s.get_payment_method_display())
            ws.write(row, 8,  float(s.subtotal), cur_fmt)
            ws.write(row, 9,  float(s.tax_amount), cur_fmt)
            ws.write(row, 10, float(s.discount_amount), cur_fmt)
            ws.write(row, 11, float(s.total_amount), cur_fmt)
            ws.write(row, 12, s.get_payment_status_display())
            ws.write(row, 13, s.get_status_display())
            ws.write(row, 14, 'Yes' if s.is_fiscalized else 'No')
            ws.write(row, 15, s.efris_invoice_number or '')

        ws.set_column('A:P', 15)
        ws.set_column('E:E', 25)
        workbook.close()
        output.seek(0)

        ts       = timezone.now().strftime('%Y%m%d_%H%M%S')
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        response['Content-Disposition'] = f'attachment; filename="sales_export_{ts}.xlsx"'
        return response

    def _export_pdf(self, sales):
        try:
            from xhtml2pdf import pisa
        except ImportError:
            messages.error(self.request, 'PDF export requires xhtml2pdf. Please contact administrator.')
            return redirect('sales:sales_list')

        total_amount   = sales.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
        total_tax      = sales.aggregate(Sum('tax_amount'))['tax_amount__sum'] or 0
        total_discount = sales.aggregate(Sum('discount_amount'))['discount_amount__sum'] or 0

        ctx = {
            'sales':          sales[:100],
            'export_date':    timezone.now(),
            'total_sales':    sales.count(),
            'total_amount':   total_amount,
            'total_tax':      total_tax,
            'total_discount': total_discount,
            'user':           self.request.user,
        }

        template = get_template('sales/sales_export_pdf.html')
        html     = template.render(ctx)

        ts       = timezone.now().strftime('%Y%m%d_%H%M%S')
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="sales_export_{ts}.pdf"'

        status = pisa.CreatePDF(html, dest=response)
        if status.err:
            messages.error(self.request, 'Error generating PDF')
            return redirect('sales:sales_list')

        return response