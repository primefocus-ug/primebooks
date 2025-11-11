from django.db import connection
from django_tenants.utils import get_public_schema_name
import logging

logger = logging.getLogger(__name__)


def current_store(request):
    """
    Provides the current store/branch to templates.
    CRITICAL: Only queries tenant-specific models when in a tenant schema.
    """
    public_schema = get_public_schema_name()
    current_schema = connection.schema_name

    # Default empty context
    context = {
        'store': None,
        'current_store': None,
        'store_name': None,
        'store_code': None,
        'store_location': None,
        'store_allows_sales': True,
        'store_allows_inventory': True,
        'store_manager': None,
        'store_phone': None,
        'store_email': None,
        'store_timezone': 'UTC',
        'store_is_open': True,
        'store_efris_enabled': False,
        'store_can_fiscalize': False,

        # Backward compatibility with 'branch' terminology
        'branch': None,
        'branch_name': None,
        'branch_location': None,
        'branch_allows_sales': True,
        'branch_allows_inventory': True,
        'branch_manager': None,
        'branch_phone': None,
        'branch_email': None,
        'branch_timezone': 'UTC',
        'branch_open_now': True,
    }

    # Only query tenant data if we're NOT in public schema
    if current_schema and current_schema != public_schema:
        try:
            # Import here to avoid issues when tables don't exist
            from stores.models import Store

            store = None

            # Example: store linked to user
            if request.user.is_authenticated:
                try:
                    store = getattr(request.user, 'default_store', None) or \
                            getattr(request.user, 'store', None)
                except Exception as user_store_error:
                    logger.debug(f"Could not get user store: {user_store_error}")

            # Fallback: main store of the current company (tenant)
            if not store and hasattr(request, 'tenant') and request.tenant:
                try:
                    store = Store.objects.filter(
                        company=request.tenant,
                        is_main_branch=True,
                        is_active=True
                    ).first()
                except Exception as main_store_error:
                    logger.debug(f"Could not query main store: {main_store_error}")

            # If still no store, get any active store for the company
            if not store and hasattr(request, 'tenant') and request.tenant:
                try:
                    store = Store.objects.filter(
                        company=request.tenant,
                        is_active=True
                    ).first()
                except Exception as any_store_error:
                    logger.debug(f"Could not query any store: {any_store_error}")

            # If we found a store, populate the context
            if store:
                # Get timezone with fallback
                store_timezone = getattr(store, 'timezone', None) or \
                                 (getattr(request.tenant, 'time_zone', 'UTC') if hasattr(request, 'tenant') else 'UTC')

                # Check if store is open (with error handling)
                try:
                    store_is_open = store.is_open_now() if hasattr(store, 'is_open_now') else True
                except Exception:
                    store_is_open = True

                context.update({
                    'store': store,
                    'current_store': store,
                    'store_name': store.name,
                    'store_code': getattr(store, 'code', None),
                    'store_location': getattr(store, 'location', None),
                    'store_allows_sales': getattr(store, 'allows_sales', True),
                    'store_allows_inventory': getattr(store, 'allows_inventory', True),
                    'store_manager': getattr(store, 'manager_name', None),
                    'store_phone': getattr(store, 'phone', None),
                    'store_email': getattr(store, 'email', None),
                    'store_timezone': store_timezone,
                    'store_is_open': store_is_open,
                    'store_efris_enabled': getattr(store, 'efris_enabled', False),
                    'store_can_fiscalize': getattr(store, 'can_fiscalize', False),

                    # Backward compatibility with 'branch' terminology
                    'branch': store,
                    'branch_name': store.name,
                    'branch_location': getattr(store, 'location', None),
                    'branch_allows_sales': getattr(store, 'allows_sales', True),
                    'branch_allows_inventory': getattr(store, 'allows_inventory', True),
                    'branch_manager': getattr(store, 'manager_name', None),
                    'branch_phone': getattr(store, 'phone', None),
                    'branch_email': getattr(store, 'email', None),
                    'branch_timezone': store_timezone,
                    'branch_open_now': store_is_open,
                })

        except Exception as e:
            # Log but don't break the view
            logger.warning(
                f"Error in store context processor for schema '{current_schema}': {e}"
            )

    return context