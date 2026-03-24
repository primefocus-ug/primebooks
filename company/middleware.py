# company/middleware.py
"""
Company middleware - PROPERLY FIXED
✅ Ensures user queries happen in correct schema context
✅ Skips company checks in public schema
"""
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import logout
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.core.cache import cache
import logging
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.functional import SimpleLazyObject
from django.conf import settings
from django.db import connection

logger = logging.getLogger(__name__)

class ActiveModulesMiddleware:
    """
    Reads which modules this tenant has switched ON,
    and attaches them to the request as a Python set.

    After this runs, anywhere in your code you can write:
        request.active_modules          → {'salon', 'inventory'}
        'salon' in request.active_modules  → True or False

    Uses Redis cache (your system already has Redis set up)
    so it only hits the DB when the cache is cold or after
    a module is toggled.

    Add this to MIDDLEWARE in settings.py right after
    'company.middleware.PlanLimitsMiddleware'
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only run inside a real tenant schema, not public
        if not hasattr(request, 'tenant') or not request.tenant:
            request.active_modules = set()
            return self.get_response(request)

        # Skip in desktop mode (no module switching needed)
        if getattr(settings, 'IS_DESKTOP', False):
            # Desktop mode: all modules active by default
            request.active_modules = self._get_all_module_keys()
            return self.get_response(request)

        schema = request.tenant.schema_name
        cache_key = f"active_modules:{schema}"

        active_modules = cache.get(cache_key)

        if active_modules is None:
            # Cache miss — hit the database
            try:
                from company.models import CompanyModule
                active_keys = CompanyModule.objects.filter(
                    company=request.tenant,
                    is_active=True
                ).values_list('module__key', flat=True)
                active_modules = set(active_keys)
            except Exception as e:
                logger.error(f"ActiveModulesMiddleware error: {e}")
                active_modules = set()

            # Cache for 5 minutes (300 seconds)
            # This key is deleted when a module is toggled ON or OFF
            # so the change takes effect on the very next request
            cache.set(cache_key, active_modules, 300)

        request.active_modules = active_modules
        return self.get_response(request)

    def _get_all_module_keys(self):
        """In desktop mode, return all available module keys."""
        try:
            from company.models import AvailableModule
            return set(
                AvailableModule.objects.values_list('key', flat=True)
            )
        except Exception:
            return set()

class CompanyAccessMiddleware:
    """
    Middleware to check company access status on each request
    ✅ FIXED: Only runs in tenant schema, not public
    ✅ FIXED: Properly handles desktop mode
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.exempt_urls = [
            '/admin/',
            '/accounts/login/',
            '/accounts/logout/',
            '/companies/suspended/',
            '/companies/expired/',
            '/companies/billing/',
            '/companies/subscription/',
            '/api/webhooks/',
            '/desktop/',
            '/static/',
            '/media/',
        ]

    def __call__(self, request):
        # ✅ CRITICAL: Skip for desktop mode
        if getattr(settings, 'IS_DESKTOP', False):
            return self.get_response(request)

        # Skip processing for exempt URLs
        if self._is_exempt_url(request.path):
            return self.get_response(request)

        # ✅ CRITICAL FIX: Only check company status if we're in a TENANT schema
        # Check current schema from connection
        current_schema = connection.schema_name if hasattr(connection, 'schema_name') else 'public'

        # Don't check company status in public schema (where accounts_customuser doesn't exist in tenant apps)
        if current_schema == 'public':
            return self.get_response(request)

        # ✅ Now safe to check authenticated user (we're in tenant schema)
        if request.user.is_authenticated and hasattr(request.user, 'company'):
            company = self._get_fresh_company(request.user)

            if company:
                try:
                    status_changed = company.check_and_update_access_status()
                    if status_changed:
                        logger.info(f"Company {company.company_id} status updated to {company.status}")
                except Exception as e:
                    logger.error(f"Error checking company status: {e}")

                # Handle different company statuses
                response = self._handle_company_status(request, company)
                if response:
                    return response

        return self.get_response(request)

    def _is_exempt_url(self, path):
        """Check if URL should be accessible regardless of company status"""
        return any(path.startswith(exempt) for exempt in self.exempt_urls)

    def _handle_company_status(self, request, company):
        """Handle different company statuses"""
        if company.status == 'EXPIRED':
            exempt_paths = ['/companies/expired/', '/companies/billing/', '/companies/subscription/']
            if not any(request.path.startswith(path) for path in exempt_paths):
                plan_name = company.plan.get_name_display().lower() if company.plan else "current"
                messages.error(
                    request,
                    f"Your {plan_name} subscription has expired. "
                    "Please renew to continue using the service."
                )
                return redirect('companies:company_expired')

        elif company.status == 'SUSPENDED':
            if not request.path.startswith('/companies/suspended/'):
                if company.is_in_grace_period:
                    messages.warning(
                        request,
                        f"Your subscription expired on {company.subscription_ends_at}. "
                        f"You have until {company.grace_period_ends_at} to renew."
                    )
                    return redirect('companies:company_grace_period')
                else:
                    messages.error(
                        request,
                        "Your company account has been suspended. Please contact support."
                    )
                    return redirect('companies:company_suspended')

        elif not company.is_active:
            if not request.path.startswith('/companies/deactivated/'):
                messages.error(
                    request,
                    "Your company account has been deactivated. Please contact support."
                )
                logout(request)
                return redirect('companies:company_deactivated')

        return None

    def _get_fresh_company(self, user):
        """Get a fresh Company from the database on each middleware pass.
        We intentionally do NOT cache the full Company object here because
        check_and_update_access_status() mutates status fields; a cached
        object would carry stale values into the next request.
        We do cache the company PK for 30 s to avoid redundant PK lookups."""
        try:
            from company.models import Company
            cache_key = f'user_{user.id}_company_pk'
            company_pk = cache.get(cache_key)

            if company_pk is None:
                if hasattr(user, 'company_id') and user.company_id:
                    company_pk = user.company_id
                elif hasattr(user, 'company') and user.company:
                    company_pk = user.company.pk
                if company_pk:
                    cache.set(cache_key, company_pk, 30)

            if company_pk:
                return Company.objects.select_related('plan').get(pk=company_pk)
            return None
        except Exception as e:
            logger.error(f"Error getting fresh company for user {user.id}: {e}")
            return None


class PlanLimitsMiddleware:
    """
    Middleware to enforce plan limits across the application
    ✅ FIXED: Only runs in tenant schema
    """

    EXEMPT_URLS = [
        '/accounts/logout/',
        '/companies/subscription/',
        '/companies/billing/',
        '/companies/profile/',
        '/companies/expired/',
        '/companies/suspended/',
        '/admin/',
        '/api/',
        '/static/',
        '/media/',
        '/desktop/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ✅ Skip for desktop mode
        if getattr(settings, 'IS_DESKTOP', False):
            return self.get_response(request)

        # ✅ Skip if in public schema
        current_schema = connection.schema_name if hasattr(connection, 'schema_name') else 'public'
        if current_schema == 'public':
            return self.get_response(request)

        # Skip for anonymous users
        if not request.user.is_authenticated:
            return self.get_response(request)

        # Skip for SaaS admins
        if getattr(request.user, 'is_saas_admin', False):
            return self.get_response(request)

        # Skip exempt URLs
        if any(request.path.startswith(url) for url in self.EXEMPT_URLS):
            return self.get_response(request)

        # Get user's company
        company = getattr(request.user, 'company', None)
        if not company:
            return self.get_response(request)

        # Check if company has active access
        if not company.has_active_access:
            messages.warning(
                request,
                _('Your subscription has expired. Please renew to continue using the system.')
            )
            return redirect('companies:subscription_dashboard')

        # Add company limits to request
        request.plan_limits = {
            'users': {
                'current': self._get_user_count(company),
                'limit': company.plan.max_users if company.plan else 0,
                'available': self._get_available_users(company),
                'exceeded': self._check_users_exceeded(company),
            },
            'branches': {
                'current': company.branches_count,
                'limit': company.plan.max_branches if company.plan else 0,
                'available': self._get_available_branches(company),
                'exceeded': self._check_branches_exceeded(company),
            },
            'storage': {
                'current_mb': company.storage_used_mb,
                'limit_gb': company.plan.max_storage_gb if company.plan else 0,
                'percentage': company.storage_usage_percentage,
                'exceeded': self._check_storage_exceeded(company),
            },
        }

        response = self.get_response(request)
        return response

    def _get_user_count(self, company):
        return company.active_users_count

    def _get_available_users(self, company):
        if not company.plan:
            return 0
        return max(0, company.plan.max_users - company.active_users_count)

    def _check_users_exceeded(self, company):
        if not company.plan:
            return False
        return company.active_users_count >= company.plan.max_users

    def _get_available_branches(self, company):
        if not company.plan:
            return 0
        return max(0, company.plan.max_branches - company.branches_count)

    def _check_branches_exceeded(self, company):
        if not company.plan:
            return False
        return company.branches_count >= company.plan.max_branches

    def _check_storage_exceeded(self, company):
        if not company.plan:
            return False
        return company.storage_usage_percentage >= 100


class WebSocketNotificationMiddleware(MiddlewareMixin):
    """Middleware to handle WebSocket notifications for HTTP requests"""

    def __init__(self, get_response):
        self.get_response = get_response
        self.channel_layer = get_channel_layer() if not getattr(settings, 'IS_DESKTOP', False) else None

    def __call__(self, request):
        response = self.get_response(request)

        if getattr(settings, 'IS_DESKTOP', False) or not self.channel_layer:
            return response

        if hasattr(request, 'user') and request.user.is_authenticated:
            if request.method == 'POST' and response.status_code in [200, 201, 302]:
                self.handle_post_success(request, response)

        return response

    def handle_post_success(self, request, response):
        if not self.channel_layer:
            return

        try:
            path = request.path
            user = request.user

            if '/branches/' in path and user.company:
                async_to_sync(self.channel_layer.group_send)(
                    f'company_dashboard_{user.company.company_id}',
                    {
                        'type': 'dashboard_update',
                        'data': {
                            'event_type': 'branch_action',
                            'message': 'Branch data has been updated',
                            'user': user.get_full_name() or user.username,
                            'timestamp': timezone.now().isoformat()
                        }
                    }
                )
        except Exception as e:
            logger.debug(f"WebSocket notification error: {e}")


def get_efris_status(request):
    """Get EFRIS status for the current request"""
    if hasattr(request, '_efris_status'):
        return request._efris_status

    efris_status = {
        'enabled': False,
        'company': None,
        'is_active': False,
    }

    if hasattr(request, 'tenant'):
        company = request.tenant
        efris_status['company'] = company
        efris_status['enabled'] = getattr(company, 'efris_enabled', False)
        efris_status['is_active'] = getattr(company, 'efris_is_active', False)

    elif hasattr(request, 'user') and request.user.is_authenticated:
        if hasattr(request.user, 'stores') and request.user.stores.exists():
            store = request.user.stores.first()
            if store and hasattr(store, 'company'):
                company = store.company
                efris_status['company'] = company
                efris_status['enabled'] = getattr(company, 'efris_enabled', False)
                efris_status['is_active'] = getattr(company, 'efris_is_active', False)

    request._efris_status = efris_status
    return efris_status


class EFRISStatusMiddleware:
    """Add EFRIS status to all requests"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.efris = SimpleLazyObject(lambda: get_efris_status(request))
        response = self.get_response(request)
        return response