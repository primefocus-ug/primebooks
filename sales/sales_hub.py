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
from django.http import HttpResponse
from django.shortcuts import redirect
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
    daily_raw = (
        sales_qs
        .extra(select={'day': 'DATE(created_at)'})
        .values('day')
        .annotate(count=Count('id'), total=Sum('total_amount'))
        .order_by('day')
    )

    daily_sales = []
    prev_total = None
    for d in daily_raw:
        day_total = float(d['total'] or 0)
        day_count = d['count'] or 0
        if prev_total is not None and prev_total > 0:
            growth = f"{((day_total - prev_total) / prev_total * 100):+.1f}%"
        else:
            growth = '+0.0%'
        daily_sales.append({
            'day':      str(d['day']),
            'count':    day_count,
            'total':    day_total,
            'avg_value': day_total / day_count if day_count else 0,
            'growth':   growth,
        })
        prev_total = day_total

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
    hourly_raw = (
        sales_qs
        .extra(select={'hour': 'EXTRACT(HOUR FROM created_at)'})
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

    # ── Store stats (EFRIS info per branch) ───────────────────────────────────
    store_stats = []
    for store in stores:
        cfg          = store.effective_efris_config
        store_sales  = sales_qs.filter(store=store)
        store_stats.append({
            'id':              store.id,
            'name':            store.name,
            'sales_count':     store_sales.count(),
            'revenue':         float(store_sales.aggregate(Sum('total_amount'))['total_amount__sum'] or 0),
            'efris_enabled':   cfg.get('enabled', False),
            'efris_active':    cfg.get('is_active', False),
            'allows_sales':    store.allows_sales,
            'allows_inventory':store.allows_inventory,
            'is_main_branch':  store.is_main_branch,
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
    POST → handles exports (action=export_csv / export_excel / export_pdf)
           or delegates to bulk_actions()
    """
    model                = Sale
    template_name        = 'sales/sales_dashboard.html'
    context_object_name  = 'sales'
    paginate_by          = 25
    permission_required  = 'sales.view_sale'

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
            if store in accessible:
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
        list_qs      = self.get_queryset().select_related(None).prefetch_related(None)
        credit_sales = list_qs.filter(document_type='INVOICE', payment_method='CREDIT')

        context['stats'] = {
            'total_sales':          list_qs.count(),
            'total_amount':         list_qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
            'total_credit_amount':  credit_sales.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
            'fiscalized_count':     list_qs.filter(is_fiscalized=True).count(),
            'receipt_count':        list_qs.filter(document_type='RECEIPT').count(),
            'invoice_count':        list_qs.filter(document_type='INVOICE').count(),
            'proforma_count':       list_qs.filter(document_type='PROFORMA').count(),
            'estimate_count':       list_qs.filter(document_type='ESTIMATE').count(),
        }

        # ── Credit stats ──────────────────────────────────────────────────────
        credit_invoices = list_qs.filter(document_type='INVOICE', payment_method='CREDIT')
        context['credit_stats'] = {
            'total_credit_invoices': credit_invoices.count(),
            'total_credit_amount':   credit_invoices.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
            'overdue_count':         credit_invoices.filter(payment_status='OVERDUE').count(),
            'overdue_amount':        credit_invoices.filter(payment_status='OVERDUE').aggregate(
                                         Sum('total_amount'))['total_amount__sum'] or 0,
            'pending_count':         credit_invoices.filter(
                                         payment_status__in=['PENDING', 'PARTIALLY_PAID']).count(),
            'paid_count':            credit_invoices.filter(payment_status='PAID').count(),
            'avg_credit_amount':     credit_invoices.aggregate(Avg('total_amount'))['total_amount__avg'] or 0,
        }

        # ── Document type distribution ────────────────────────────────────────
        total = context['stats']['total_sales'] or 1
        doc_stats = list_qs.values('document_type').annotate(
            count=Count('id'), total=Sum('total_amount')
        ).order_by('-count')

        context['document_type_stats'] = [
            {
                'type':         s['document_type'],
                'type_display': dict(Sale.DOCUMENT_TYPE_CHOICES).get(s['document_type'], s['document_type']),
                'count':        s['count'],
                'total':        s['total'] or 0,
                'percentage':   round(s['count'] / total * 100, 1),
            }
            for s in doc_stats
        ]

        # ── Payment status distribution ───────────────────────────────────────
        ps_stats = list_qs.values('payment_status').annotate(
            count=Count('id'), total=Sum('total_amount')
        ).order_by('-count')

        context['payment_status_stats'] = [
            {
                'status':         s['payment_status'],
                'status_display': dict(Sale.PAYMENT_STATUS_CHOICES).get(s['payment_status'], s['payment_status']),
                'count':          s['count'],
                'total':          s['total'] or 0,
            }
            for s in ps_stats
        ]

        # ── EFRIS stats ───────────────────────────────────────────────────────
        efris_sales = list_qs.filter(is_fiscalized=True)
        if efris_sales.exists():
            context['efris_stats'] = {
                'count':             efris_sales.count(),
                'total_amount':      efris_sales.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
                'latest_fiscalized': efris_sales.order_by('-fiscalization_time').first(),
            }

        # ── Top credit customers ──────────────────────────────────────────────
        context['top_credit_customers'] = (
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