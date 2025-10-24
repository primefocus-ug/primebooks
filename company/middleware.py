from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import logout
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)


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
            '/billing/',
            '/api/webhooks/',
        ]

    def __call__(self, request):
        # Skip processing for exempt URLs
        if self._is_exempt_url(request.path):
            return self.get_response(request)

        # Process authenticated users
        if request.user.is_authenticated and hasattr(request.user, 'company'):
            # FIXED: Get fresh company instance from database instead of using cached one
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

    def _get_fresh_company(self, user):
        """Get fresh company instance from database, with caching for performance"""
        try:
            # Use a short-lived cache (30 seconds) to avoid hitting DB on every request
            # but ensure we get fresh data after reactivation
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
                    # Cache for 30 seconds only - short enough that reactivation takes effect quickly
                    cache.set(cache_key, company, 30)

            return company
        except Exception as e:
            logger.error(f"Error getting fresh company for user {user.id}: {e}")
            return None

    def _is_exempt_url(self, path):
        """Check if URL should be accessible regardless of company status"""
        return any(path.startswith(exempt) for exempt in self.exempt_urls)

    def _handle_company_status(self, request, company):
        """Handle different company statuses"""
        if company.status == 'EXPIRED':
            if not request.path.startswith('/company/expired/'):
                messages.error(
                    request,
                    f"Your {company.plan.get_name_display().lower()} subscription has expired. "
                    "Please renew to continue using the service."
                )
                return redirect('companies:company_expired')

        elif company.status == 'SUSPENDED':
            if not request.path.startswith('/company/suspended/'):
                if company.is_in_grace_period:
                    messages.warning(
                        request,
                        f"Your subscription expired on {company.subscription_ends_at}. "
                        f"You have until {company.grace_period_ends_at} to renew."
                    )
                    return redirect('company_grace_period')
                else:
                    messages.error(
                        request,
                        "Your company account has been suspended. Please contact support."
                    )
                    return redirect('companies:company_suspended')

        elif not company.is_active:
            # Company manually deactivated
            if not request.path.startswith('/company/deactivated/'):
                messages.error(
                    request,
                    "Your company account has been deactivated. Please contact support."
                )
                logout(request)
                return redirect('companies:company_deactivated')

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