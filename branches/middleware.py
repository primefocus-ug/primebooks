from django.utils.deprecation import MiddlewareMixin
from stores.models import Store


class StoreDetectionMiddleware(MiddlewareMixin):
    """
    Middleware to detect and attach the current store to the request.
    This can be based on subdomain, URL parameter, or user's default store.
    """

    def process_request(self, request):
        """Attach current store to request object."""
        store = None

        # Method 1: Get from URL parameter
        store_id = request.GET.get('store_id') or request.POST.get('store_id')
        if store_id:
            try:
                store = Store.objects.select_related('company').get(id=store_id, is_active=True)
            except (Store.DoesNotExist, ValueError):
                pass

        # Method 2: Get from session
        if not store and request.session.get('current_store_id'):
            try:
                store = Store.objects.select_related('company').get(
                    id=request.session['current_store_id'],
                    is_active=True
                )
            except Store.DoesNotExist:
                del request.session['current_store_id']

        # Method 3: Get from user's default store
        if not store and request.user.is_authenticated:
            store = getattr(request.user, 'default_store', None)

        # Method 4: Get main store from tenant/company
        if not store and hasattr(request, 'tenant') and request.tenant:
            store = Store.objects.filter(
                company=request.tenant,
                is_main_branch=True,
                is_active=True
            ).first()

        # Attach to request
        request.current_store = store
        request.store = store  # Alias

        # Also maintain backward compatibility with 'branch'
        request.current_branch = store
        request.branch = store

        return None

