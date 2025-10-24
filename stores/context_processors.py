from stores.models import Store
from django.db import models
from django.utils import timezone
from datetime import datetime

def current_store(request):
    store = None

    if request.user.is_authenticated:
        # Try getting from user's related stores (many-to-many)
        user_stores = getattr(request.user, 'stores', None)
        if user_stores and hasattr(user_stores, 'first'):
            store = user_stores.first()

        # Fallback: first active store of user's company
        if not store and hasattr(request.user, 'company') and request.user.company:
            qs = Store.objects.filter(company=request.user.company, is_active=True)
            store = qs.first() if qs.exists() else None  # ✅ ensures instance, not queryset

    # ✅ extra safety: if store is still a queryset, extract one instance
    if hasattr(store, 'all'):
        store = store.first() or None

    context = {
        'store': store,
        'store_name': getattr(store, 'name', None),
        'store_address': getattr(store, 'physical_address', None),
        'store_phone': getattr(store, 'phone', None),
        'store_email': getattr(store, 'email', None),
        'store_logo': store.logo.url if store and store.logo else None,
        'store_efris_enabled': getattr(store, 'efris_enabled', False),
        'store_efris_device': getattr(store, 'efris_device_number', None),
        'store_open_now': False,
        'store_inventory_low': [],
        'store_inventory_needs_reorder': [],
    }

    # ✅ JSONField operating hours
    if store and isinstance(store.operating_hours, dict):
        now = timezone.localtime(timezone.now())
        day = now.strftime('%A').lower()
        hours = store.operating_hours.get(day)
        if hours:
            if hours.get('is_open', True):
                try:
                    open_time = datetime.strptime(hours.get('open_time', '00:00'), '%H:%M').time()
                    close_time = datetime.strptime(hours.get('close_time', '23:59'), '%H:%M').time()
                    context['store_open_now'] = open_time <= now.time() <= close_time
                except ValueError:
                    context['store_open_now'] = True

    # ✅ Inventory low-stock detection
    if store and hasattr(store, 'inventory_items'):
        low_stock = store.inventory_items.filter(quantity__lte=models.F('low_stock_threshold'))
        reorder = store.inventory_items.filter(quantity__lte=models.F('reorder_quantity'))
        context['store_inventory_low'] = low_stock
        context['store_inventory_needs_reorder'] = reorder

    return context
