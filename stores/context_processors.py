from django.db import connection
from django.db.models import F
from django_tenants.utils import get_public_schema_name
from django.utils import timezone
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def store_context(request):
    """
    Add store-related context to all templates.
    SAFE for public + tenant schemas.
    """
    context = {
        'current_store': None,
        'accessible_stores': [],
        'can_switch_stores': False,
    }

    public_schema = get_public_schema_name()
    current_schema = connection.schema_name

    # Never run tenant logic in public schema
    if current_schema == public_schema:
        return context

    if not request.user.is_authenticated:
        return context

    get_stores = getattr(request.user, 'get_accessible_stores', None)
    if callable(get_stores):
        stores = get_stores()
        context['accessible_stores'] = stores
        context['can_switch_stores'] = stores.count() > 1

    context['current_store'] = getattr(request, 'current_store', None)

    return context


def current_store(request):
    """
    Provides the current store to templates.
    CRITICAL: Only queries tenant-specific models when in a tenant schema.
    """
    public_schema = get_public_schema_name()
    current_schema = connection.schema_name

    context = {
        'store': None,
        'store_name': None,
        'store_address': None,
        'store_phone': None,
        'store_email': None,
        'store_logo': None,
        'store_efris_enabled': False,
        'store_efris_device': None,
        'store_open_now': False,
        'store_inventory_low': [],
        'store_inventory_needs_reorder': [],
    }

    if not current_schema or current_schema == public_schema:
        logger.debug("Skipping store context processor - in public schema")
        return context

    try:
        from stores.models import Store

        store = None

        if request.user.is_authenticated:
            try:
                user_stores = getattr(request.user, 'stores', None)
                if user_stores and hasattr(user_stores, 'first'):
                    store = user_stores.first()

                if not store and hasattr(request.user, 'company') and request.user.company:
                    qs = Store.objects.filter(company=request.user.company, is_active=True)
                    store = qs.first() if qs.exists() else None

            except Exception as user_store_error:
                logger.debug(f"Could not get user's store: {user_store_error}")

        # Safety: if store is a queryset, extract one instance
        if hasattr(store, 'all'):
            store = store.first() or None

        if store:
            context.update({
                'store': store,
                'store_name': getattr(store, 'name', None),
                'store_address': getattr(store, 'physical_address', None),
                'store_phone': getattr(store, 'phone', None),
                'store_email': getattr(store, 'email', None),
                'store_logo': store.logo.url if store.logo else None,
                'store_efris_enabled': getattr(store, 'efris_enabled', False),
                'store_efris_device': getattr(store, 'efris_device_number', None),
            })

            # Operating hours check
            try:
                if isinstance(store.operating_hours, dict):
                    now = timezone.localtime(timezone.now())
                    day = now.strftime('%A').lower()
                    hours = store.operating_hours.get(day)

                    if hours and hours.get('is_open', True):
                        try:
                            open_time = datetime.strptime(hours.get('open_time', '00:00'), '%H:%M').time()
                            close_time = datetime.strptime(hours.get('close_time', '23:59'), '%H:%M').time()
                            context['store_open_now'] = open_time <= now.time() <= close_time
                        except (ValueError, TypeError):
                            context['store_open_now'] = True
            except Exception as hours_error:
                logger.debug(f"Could not check store hours: {hours_error}")
                context['store_open_now'] = False

            # Inventory low-stock detection
            # FIX: Use the module-level F import instead of importing django.db.models
            # inside the function on every request.
            try:
                if hasattr(store, 'inventory_items'):
                    context['store_inventory_low'] = store.inventory_items.filter(
                        quantity__lte=F('low_stock_threshold')
                    )
                    context['store_inventory_needs_reorder'] = store.inventory_items.filter(
                        quantity__lte=F('reorder_quantity')
                    )
            except Exception as inventory_error:
                logger.debug(f"Could not check inventory levels: {inventory_error}")
                context['store_inventory_low'] = []
                context['store_inventory_needs_reorder'] = []

    except Exception as e:
        logger.warning(
            f"Error in store context processor for schema '{current_schema}': {e}"
        )

    return context