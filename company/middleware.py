from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import logout
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.core.cache import cache
import logging
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from django.utils.translation import gettext as _

from django.utils.functional import SimpleLazyObject

logger = logging.getLogger(__name__)


class PlanLimitsMiddleware:
    '''
    Middleware to enforce plan limits across the application
    '''

    # URLs that should always be accessible even when limits exceeded
    EXEMPT_URLS = [
        '/accounts/logout/',
        '/companies/subscription/',
        '/companies/billing/',
        '/companies/profile/',
        '/companies/expired/',  # ADD THIS
        '/companies/suspended/',  # ADD THIS
        '/admin/',
        '/api/',
        '/static/',
        '/media/',
    ]

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
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

        # Add company limits to request for easy access in views
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
        from accounts.models import CustomUser
        return CustomUser.objects.filter(company=company, is_hidden=False).count()

    def _get_available_users(self, company):
        if not company.plan:
            return 0
        current = self._get_user_count(company)
        return max(0, company.plan.max_users - current)

    def _check_users_exceeded(self, company):
        if not company.plan:
            return False
        return self._get_user_count(company) >= company.plan.max_users

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

class CompanyAccessMiddleware:
    """
    Middleware to check company access status on each request
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # URLs that should be accessible even when company is suspended
        self.exempt_urls = [
            '/admin/',
            '/accounts/login/',
            '/accounts/logout/',
            '/companies/suspended/',
            '/companies/expired/',
            'expired/',
            '/companies/billing/',
            '/companies/subscription/',
            '/api/webhooks/',
        ]

    def __call__(self, request):
        # Skip processing for exempt URLs
        if self._is_exempt_url(request.path):
            return self.get_response(request)

        # Process authenticated users
        if request.user.is_authenticated and hasattr(request.user, 'company'):
            company = self._get_fresh_company(request.user)

            if company:
                # Check and update company status
                status_changed = company.check_and_update_access_status()
                if status_changed:
                    logger.info(f"Company {company.company_id} status updated to {company.status}")

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
        # FIXED: Use the actual URL paths and correct URL names
        if company.status == 'EXPIRED':
            # Check if we're already on an exempt URL (including expired page)
            exempt_paths = ['/companies/expired/', '/companies/billing/', '/companies/subscription/']
            if not any(request.path.startswith(path) for path in exempt_paths):
                messages.error(
                    request,
                    f"Your {company.plan.get_name_display().lower()} subscription has expired. "
                    "Please renew to continue using the service."
                )
                return redirect('companies:company_expired')  # FIXED: Use correct URL name

        elif company.status == 'SUSPENDED':
            # Check if we're already on suspended page
            if not request.path.startswith('/companies/suspended/'):
                if company.is_in_grace_period:
                    messages.warning(
                        request,
                        f"Your subscription expired on {company.subscription_ends_at}. "
                        f"You have until {company.grace_period_ends_at} to renew."
                    )
                    return redirect('companies:company_grace_period')  # Make sure this URL exists
                else:
                    messages.error(
                        request,
                        "Your company account has been suspended. Please contact support."
                    )
                    return redirect('companies:company_suspended')  # FIXED: Use correct URL name

        elif not company.is_active:
            # Company manually deactivated
            if not request.path.startswith('/companies/deactivated/'):
                messages.error(
                    request,
                    "Your company account has been deactivated. Please contact support."
                )
                logout(request)
                return redirect('companies:company_deactivated')  # FIXED: Use correct URL name

        return None

    def _get_fresh_company(self, user):
        """Get fresh company instance from database, with caching for performance"""
        try:
            # Use a short-lived cache (30 seconds) to avoid hitting DB on every request
            cache_key = f'user_{user.id}_company_fresh'
            company = cache.get(cache_key)

            if company is None:
                # Import here to avoid circular imports
                from company.models import Company

                # Get fresh company instance from database
                if hasattr(user, 'company_id'):
                    company = Company.objects.select_related('plan').get(
                        company_id=user.company_id
                    )
                elif hasattr(user, 'company'):
                    # Refresh the existing company instance
                    user.company.refresh_from_db(fields=[
                        'status', 'is_active', 'subscription_ends_at',
                        'trial_ends_at', 'grace_period_ends_at', 'is_trial'
                    ])
                    company = user.company

                if company:
                    # Cache for 30 seconds only
                    cache.set(cache_key, company, 30)

            return company
        except Exception as e:
            logger.error(f"Error getting fresh company for user {user.id}: {e}")
            return None


class WebSocketNotificationMiddleware(MiddlewareMixin):
    """
    Middleware to handle WebSocket notifications for HTTP requests
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.channel_layer = get_channel_layer()

    def __call__(self, request):
        response = self.get_response(request)

        # Send notifications for certain actions
        if hasattr(request, 'user') and request.user.is_authenticated:
            if request.method == 'POST' and response.status_code in [200, 201, 302]:
                self.handle_post_success(request, response)

        return response

    def handle_post_success(self, request, response):
        """Handle successful POST requests that might need WebSocket updates"""
        try:
            path = request.path
            user = request.user

            # Example: Branch creation/update notifications
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
            # Log error but don't break the response
            print(f"WebSocket notification error: {e}")



def get_efris_status(request):
    """Get EFRIS status for the current request"""
    if hasattr(request, '_efris_status'):
        return request._efris_status
    
    efris_status = {
        'enabled': False,
        'company': None,
        'is_active': False,
    }
    
    # Check tenant
    if hasattr(request, 'tenant'):
        company = request.tenant
        efris_status['company'] = company
        efris_status['enabled'] = getattr(company, 'efris_enabled', False)
        efris_status['is_active'] = getattr(company, 'efris_is_active', False)
    
    # Check user's store
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
        # Add lazy evaluation of EFRIS status
        request.efris = SimpleLazyObject(lambda: get_efris_status(request))
        
        response = self.get_response(request)
        return response