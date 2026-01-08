from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.http import JsonResponse
from stores.models import Store
import logging

logger = logging.getLogger(__name__)


@login_required
@never_cache
def pos_index(request):
    """
    Main POS interface
    Loads the offline-capable POS application
    """
    try:
        # Get user's accessible stores
        accessible_stores = request.user.get_accessible_stores()

        if not accessible_stores.exists():
            return render(request, 'pos_app/no_access.html', {
                'message': 'You do not have access to any stores. Please contact your administrator.'
            })

        # Get default store
        default_store = request.user.default_store
        if not default_store:
            default_store = accessible_stores.first()

        # Check company access
        if not request.user.company or not request.user.company.has_active_access:
            return render(request, 'pos_app/subscription_expired.html', {
                'company': request.user.company
            })

        context = {
            'user': request.user,
            'default_store': default_store,
            'accessible_stores': accessible_stores,
            'company': request.user.company,
        }

        return render(request, 'pos/offline.html', context)

    except Exception as e:
        logger.error(f"POS index error: {e}", exc_info=True)
        return render(request, 'pos_app/error.html', {
            'error': str(e)
        })


@login_required
def get_user_stores(request):
    """
    API endpoint to get user's accessible stores
    """
    try:
        stores = request.user.get_accessible_stores()

        stores_data = []
        for store in stores:
            stores_data.append({
                'id': store.id,
                'name': store.name,
                'code': store.code,
                'address': store.physical_address,
                'is_active': store.is_active,
                'efris_enabled': store.efris_enabled,
            })

        return JsonResponse({
            'stores': stores_data,
            'default_store_id': request.user.default_store.id if request.user.default_store else None
        })

    except Exception as e:
        logger.error(f"Get stores error: {e}")
        return JsonResponse({
            'error': str(e)
        }, status=400)