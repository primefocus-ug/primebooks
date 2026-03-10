"""
stores/views/store_hub.py
─────────────────────────
Single view that drives the Store Hub template (store_hub.html).
It gathers every piece of data previously spread across:

    store_dashboard, store_analytics, low_stock_alert,
    generate_store_report, manage_store_staff,
    ManageStoreAccessView, EditStoreAccessView, SelectStoreView

URL pattern (add to stores/urls.py):

    path('hub/', views.store_hub, name='hub'),

The view is intentionally flat — it builds one big context dict so the
template can render all tabs without extra round-trips.  Heavy sections
(analytics, report stats) are only computed when the user has the
required permissions so the view stays fast for restricted users.
"""

import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from inventory.models import Stock
from .models import Store, StoreAccess, StoreDevice, DeviceOperatorLog
from .forms import EnhancedStoreReportForm, StoreStaffAssignmentForm
from .utils import (
    get_user_accessible_stores,
    get_visible_users_for_store,
    filter_stores_by_permissions,
    validate_store_access,
    get_store_performance_metrics,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_current_store(request, stores_qs):
    """Return the store stored in the session, validated against the queryset."""
    store_id = request.session.get('current_store_id')
    if not store_id:
        return None
    try:
        store = stores_qs.get(id=store_id, is_active=True)
        validate_store_access(request.user, store, action='view', raise_exception=True)
        return store
    except (Store.DoesNotExist, PermissionDenied):
        # Stale/invalid session entry — clear it silently.
        request.session.pop('current_store_id', None)
        return None


def _dashboard_context(request, stores, current_store):
    """Build context data for the Dashboard tab."""
    active_stores = stores.filter(is_active=True)
    all_stock = Stock.objects.filter(store__in=active_stores)

    ctx = {
        'stats': {
            'total_stores':      stores.count(),
            'active_stores':     active_stores.count(),
            'inactive_stores':   stores.filter(is_active=False).count(),
            'efris_enabled':     stores.filter(efris_enabled=True).count(),
            'total_devices':     StoreDevice.objects.filter(store__in=stores, is_active=True).count(),
            'active_devices':    StoreDevice.objects.filter(store__in=stores, is_active=True).count(),
            'main_branch_count': stores.filter(is_main_branch=True).count(),
            'average_inventory': all_stock.count() / max(active_stores.count(), 1),
        },
        'recent_stores': stores.order_by('-created_at')[:5],
        'low_stock_count': all_stock.filter(
            quantity__lte=F('low_stock_threshold')
        ).count(),
        'stores_by_region': list(
            stores.exclude(region__isnull=True).exclude(region='')
            .values('region')
            .annotate(count=Count('id'))
            .order_by('-count')[:8]
        ),
        'recent_activity': DeviceOperatorLog.objects.filter(
            device__store__in=stores,
            user__is_hidden=False,
        ).select_related('user', 'device__store').order_by('-timestamp')[:10],
        'can_switch_stores': stores.count() > 1,
    }
    return ctx


def _analytics_context(request, stores):
    """Build context data for the Analytics tab."""
    active_stores = stores.filter(is_active=True)
    all_stock     = Stock.objects.filter(store__in=stores)

    return {
        'analytics_data': {
            'store_performance': [
                {
                    'name':            store.name,
                    'inventory_value': float(
                        store.inventory_items.aggregate(
                            total=Sum(F('quantity') * F('product__cost_price'))
                        )['total'] or 0
                    ),
                    'device_count':    store.devices.filter(is_active=True).count(),
                    'staff_count':     store.staff.filter(is_hidden=False).count(),
                    'low_stock_items': store.inventory_items.filter(
                        quantity__lte=F('low_stock_threshold')
                    ).count(),
                    'efris_enabled':   store.efris_enabled,
                    'is_main_branch':  store.is_main_branch,
                }
                for store in stores
            ],
            'inventory_summary': all_stock.aggregate(
                total_items=Sum('quantity'),
                low_stock_count=Count('id', filter=Q(quantity__lte=F('low_stock_threshold'))),
            ),
            'device_status': StoreDevice.objects.filter(store__in=stores).aggregate(
                total=Count('id'),
                active=Count('id', filter=Q(is_active=True)),
                pos_devices=Count('id', filter=Q(device_type='POS')),
            ),
            'regional_distribution': list(
                stores.values('region')
                .annotate(store_count=Count('id'))
                .order_by('-store_count')
            ),
        },
    }


def _low_stock_context(request, stores):
    """Build context data for the Low Stock Alerts tab."""
    active_stores = stores.filter(is_active=True)
    low_stock_qs  = Stock.objects.filter(
        quantity__lte=F('low_stock_threshold'),
        store__in=active_stores,
    ).select_related('store', 'product', 'product__category').order_by('quantity')

    # Augment with computed fields
    items_with_computations = []
    for stock_item in low_stock_qs:
        reorder_gap = stock_item.low_stock_threshold - stock_item.quantity
        stock_pct   = (
            stock_item.quantity / stock_item.low_stock_threshold * 100
            if stock_item.low_stock_threshold > 0 else 0
        )
        items_with_computations.append({
            'stock':                 stock_item,
            'product':               stock_item.product,
            'quantity':              stock_item.quantity,
            'low_stock_threshold':   stock_item.low_stock_threshold,
            'reorder_quantity':      stock_item.reorder_quantity,
            'total_cost':            stock_item.quantity * stock_item.product.cost_price,
            'reorder_gap':           reorder_gap,
            'stock_percentage':      min(100, max(0, round(stock_pct, 1))),
            'recommended_order_qty': max(
                Decimal('0'),
                (Decimal(str(stock_item.low_stock_threshold)) * Decimal('1.5')) - stock_item.quantity
            ).quantize(Decimal('0.01')),
        })

    # Group by store for display — matches original low_stock_alert.html
    stores_with_alerts = {}
    for item in items_with_computations:
        store_name = item['stock'].store.name
        stores_with_alerts.setdefault(
            store_name, {'store': item['stock'].store, 'items': []}
        )
        stores_with_alerts[store_name]['items'].append(item)

    return {
        'stores_with_alerts':    stores_with_alerts,
        'total_low_stock_items': len(items_with_computations),
        'low_stock_items':       items_with_computations,
    }


def _report_context(request):
    """Build context data for the Generate Report tab."""
    return {
        'form':             EnhancedStoreReportForm(user=request.user),
        'available_stores': filter_stores_by_permissions(request.user, action='view'),
        'report_stats':     _get_report_statistics(request.user),
        'excel_available':  _excel_available(),
        'pdf_available':    _pdf_available(),
    }


def _get_report_statistics(user):
    accessible = get_user_accessible_stores(user)
    return {
        'total_stores':   accessible.count(),
        'active_stores':  accessible.filter(is_active=True).count(),
        'total_devices':  StoreDevice.objects.filter(
            store__in=accessible, is_active=True
        ).count(),
        'low_stock_items': Stock.objects.filter(
            store__in=accessible,
            quantity__lte=F('low_stock_threshold'),
        ).count(),
    }


def _excel_available():
    try:
        import openpyxl  # noqa: F401
        return True
    except ImportError:
        return False


def _pdf_available():
    try:
        from reportlab.lib import colors  # noqa: F401
        return True
    except ImportError:
        return False


def _store_detail_context(request, current_store):
    """Build context data for the Store Detail tab."""
    if not current_store:
        return {}

    performance_metrics = {}
    try:
        performance_metrics = get_store_performance_metrics(current_store, days=30)
    except Exception as exc:
        logger.error("store_hub: performance metrics error: %s", exc)

    return {
        'devices':      current_store.devices.filter(is_active=True).order_by('-registered_at'),
        'visible_staff': get_visible_users_for_store(current_store, request.user),
        'store_managers': current_store.store_managers.filter(is_active=True, is_hidden=False),
        'low_stock_items': current_store.inventory_items.filter(
            quantity__lte=F('low_stock_threshold')
        ).count(),
        'recent_logs':  DeviceOperatorLog.objects.filter(
            device__store=current_store,
            user__is_hidden=False,
        ).select_related('user', 'device').order_by('-timestamp')[:10],
        'store_open_now':  current_store.is_open_now(),
        'is_store_manager': current_store.store_managers.filter(
            id=request.user.id
        ).exists(),
        'can_fiscalize':   current_store.can_fiscalize,
        'efris_config':    current_store.effective_efris_config,
        'performance_metrics': performance_metrics,
        'staff_form':      StoreStaffAssignmentForm(
            store_instance=current_store, user=request.user
        ),
    }


def _manage_staff_context(request, current_store):
    """Build context data for the Manage Staff tab."""
    if not current_store:
        return {}

    is_manager = current_store.store_managers.filter(id=request.user.id).exists()

    return {
        'current_staff': StoreAccess.objects.filter(
            store=current_store, is_active=True
        ).select_related('user'),
        'store_managers':    current_store.store_managers.filter(is_active=True),
        'is_store_manager':  is_manager,
        'available_staff_count': 0,  # computed if needed
    }


def _manage_access_context(request, current_store):
    """Build context data for the Manage Access tab."""
    if not current_store:
        return {}

    is_manager     = current_store.store_managers.filter(id=request.user.id).exists()
    can_manage     = (
        request.user.is_saas_admin
        or request.user.is_company_owner
        or request.user.company_admin
        or is_manager
    )

    # Respect visibility: non-admins only see their own access record
    if can_manage:
        access_qs = current_store.access_permissions.filter(
            is_active=True
        ).select_related('user', 'granted_by')
    else:
        access_qs = current_store.access_permissions.filter(
            user=request.user, is_active=True
        ).select_related('user', 'granted_by')

    # Users who can still be granted access
    from django.contrib.auth import get_user_model
    User = get_user_model()
    already_granted_ids = current_store.access_permissions.filter(
        is_active=True
    ).values_list('user_id', flat=True)
    available_users = User.objects.filter(
        company=current_store.company,
        is_active=True,
        is_hidden=False,
    ).exclude(id__in=already_granted_ids)

    return {
        'access_permissions':  access_qs,
        'can_manage_access':   can_manage,
        'available_users':     available_users,
        'access_level_choices': StoreAccess.ACCESS_LEVELS,
    }


def _edit_access_context(request, current_store):
    """Build context data for the Edit Access tab.

    The target user is identified via the GET param ``edit_user`` which is set
    by the JS in the template when the user clicks an edit button in Manage
    Access.  Falls back to None so the template shows the 'select a user' guard.
    """
    if not current_store:
        return {}

    edit_user_id = request.GET.get('edit_user')
    edit_access_target = None

    if edit_user_id:
        edit_access_target = StoreAccess.objects.filter(
            store=current_store,
            user_id=edit_user_id,
            is_active=True,
        ).select_related('user').first()

    return {
        'edit_access_target':  edit_access_target,
        'access_level_choices': StoreAccess.ACCESS_LEVELS,
        # Pre-built list of (field_name, label, bootstrap-icon) tuples so the
        # template can loop over them without hardcoding.
        'edit_permissions_fields': [
            ('can_view_sales',       'View Sales',       'eye'),
            ('can_create_sales',     'Create Sales',     'plus-circle'),
            ('can_view_inventory',   'View Inventory',   'box-seam'),
            ('can_manage_inventory', 'Manage Inventory', 'pencil'),
            ('can_view_reports',     'View Reports',     'graph-up'),
            ('can_fiscalize',        'Fiscalize (EFRIS)','receipt'),
            ('can_manage_staff',     'Manage Staff',     'people'),
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Main hub view
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@permission_required('stores.view_store', raise_exception=True)
def store_hub(request):
    """
    Single view that renders the merged Store Hub template.

    All tab data is collected here.  Store-specific tabs gracefully degrade to
    a 'select a store first' guard if no store is active in the session.
    """

    # ── Accessible stores ──────────────────────────────────────
    stores = get_user_accessible_stores(request.user)
    current_store = _get_current_store(request, stores)

    # ── Base context (always computed) ─────────────────────────
    context = {
        'current_store':    current_store,
        'accessible_stores': stores,
    }

    # ── Dashboard ──────────────────────────────────────────────
    context.update(_dashboard_context(request, stores, current_store))

    # ── Analytics (view_store permission already checked above) ─
    context.update(_analytics_context(request, stores))

    # ── Low Stock Alerts ───────────────────────────────────────
    if request.user.has_perm('inventory.view_stock'):
        context.update(_low_stock_context(request, stores))

    # ── Report form ────────────────────────────────────────────
    if request.user.has_perm('stores.view_store'):
        context.update(_report_context(request))

    # ── Store-specific tabs ────────────────────────────────────
    if current_store:
        context.update(_store_detail_context(request, current_store))

        if request.user.has_perm('stores.change_store'):
            context.update(_manage_staff_context(request, current_store))

        if request.user.has_perm('stores.view_storeaccess'):
            context.update(_manage_access_context(request, current_store))

        if request.user.has_perm('stores.change_storeaccess'):
            context.update(_edit_access_context(request, current_store))

    return render(request, 'stores/store_hub.html', context)