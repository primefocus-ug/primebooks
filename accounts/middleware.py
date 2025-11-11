from django.shortcuts import redirect
from django.contrib import messages
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import get_user_model
from django.utils.functional import SimpleLazyObject
from django_tenants.utils import get_tenant_model, get_public_schema_name
import time

User = get_user_model()


class RolePermissionMiddleware:
    """
    Middleware to ensure permissions are loaded from roles
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, 'user') and request.user.is_authenticated:
            # Force permission refresh on each request
            request.user = SimpleLazyObject(lambda: self._get_user_with_perms(request.user))

        response = self.get_response(request)
        return response

    def _get_user_with_perms(self, user):
        """Refresh user permissions from database"""
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Get fresh user instance with permissions
        fresh_user = User.objects.select_related('company').prefetch_related(
            'groups__permissions',
            'user_permissions'
        ).get(pk=user.pk)

        return fresh_user

class SaaSAdminAccessMiddleware(MiddlewareMixin):
    """
    Middleware to handle SaaS admin access across all tenants.
    Allows SaaS admins to access any company's tenant.
    """

    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.get_response = get_response

    def process_request(self, request):
        """Process request to handle SaaS admin tenant switching"""

        # Skip processing for certain paths
        if self._should_skip_processing(request):
            return None

        # Only process authenticated users
        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return None

        # Check if user is a SaaS admin
        if not getattr(request.user, 'is_saas_admin', False):
            return None

        # Handle tenant switching for SaaS admins
        return self._handle_saas_admin_access(request)

    def _should_skip_processing(self, request):
        """Determine if we should skip processing this request"""
        skip_paths = [
            '/admin/login/',
            '/admin/logout/',
            '/static/',
            '/media/',
            '/api/auth/',
            '/health/',
            '/favicon.ico'
        ]

        return any(request.path.startswith(path) for path in skip_paths)

    def _handle_saas_admin_access(self, request):
        """Handle SaaS admin access to different tenants"""

        # Get the current tenant
        current_tenant = getattr(request, 'tenant', None)
        if not current_tenant:
            return None

        # Check if SaaS admin is trying to access a specific company
        tenant_switch = request.GET.get('switch_tenant')
        if tenant_switch:
            return self._handle_tenant_switch(request, tenant_switch)

        # Add tenant context to the request for SaaS admins
        request.saas_admin_context = {
            'can_switch_tenants': True,
            'current_tenant': current_tenant,
            'available_tenants': self._get_available_tenants(request.user)
        }

        return None

    def _handle_tenant_switch(self, request, tenant_id):
        """Handle tenant switching for SaaS admin"""
        try:
            # Get the target tenant
            Tenant = get_tenant_model()
            target_tenant = Tenant.objects.get(id=tenant_id)

            # Build the URL for the target tenant
            target_url = self._build_tenant_url(target_tenant, request)

            # Add success message
            messages.success(
                request,
                f'Switched to tenant: {target_tenant.name}'
            )

            return redirect(target_url)

        except Tenant.DoesNotExist:
            messages.error(request, 'Invalid tenant specified')
            return None
        except Exception as e:
            messages.error(request, f'Error switching tenant: {str(e)}')
            return None

    def _build_tenant_url(self, tenant, request):
        """Build URL for accessing a specific tenant"""
        # Get the primary domain for the tenant
        primary_domain = tenant.domains.filter(is_primary=True).first()

        if primary_domain:
            protocol = 'https' if primary_domain.ssl_enabled else 'http'
            domain = primary_domain.domain
            path = request.path
            query_string = request.META.get('QUERY_STRING', '')

            # Remove switch_tenant from query string
            if query_string:
                query_parts = []
                for part in query_string.split('&'):
                    if not part.startswith('switch_tenant='):
                        query_parts.append(part)
                query_string = '&'.join(query_parts)

            url = f"{protocol}://{domain}{path}"
            if query_string:
                url += f"?{query_string}"

            return url

        # Fallback to current domain with tenant parameter
        return request.build_absolute_uri(request.path)

    def _get_available_tenants(self, user):
        """Get list of tenants available to the SaaS admin"""
        if not user.is_saas_admin:
            return []

        try:
            Tenant = get_tenant_model()
            return Tenant.objects.filter(
                schema_name__ne=get_public_schema_name()
            ).exclude(
                schema_name='public'
            ).select_related().order_by('name')[:50]  # Limit for performance
        except Exception:
            return []


class HiddenUserMiddleware(MiddlewareMixin):
    """
    Middleware to ensure hidden users (SaaS admins) are not shown in
    regular user listings and don't affect user counts.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):
        """Add context about hidden users to requests"""

        if hasattr(request, 'user') and request.user.is_authenticated:
            # Add helper methods to the request for filtering hidden users
            request.get_visible_users = lambda qs=None: self._get_visible_users(qs)
            request.get_company_user_count = lambda company: self._get_company_user_count(company)

        return None

    def _get_visible_users(self, queryset=None):
        """Get only visible users (excluding hidden SaaS admins)"""
        if queryset is None:
            queryset = User.objects.all()

        return queryset.filter(is_hidden=False)

    def _get_company_user_count(self, company):
        """Get user count for a company excluding hidden users"""
        return User.objects.filter(
            company=company,
            is_hidden=False,
            is_active=True
        ).count()


class SaaSAdminContextMiddleware(MiddlewareMixin):
    """
    Middleware to add SaaS admin context to templates
    """

    def process_template_response(self, request, response):
        """Add SaaS admin context to template responses"""

        if hasattr(response, 'context_data') and response.context_data is not None:
            # Add SaaS admin context
            if hasattr(request, 'user') and request.user.is_authenticated:
                response.context_data.update({
                    'is_saas_admin': getattr(request.user, 'is_saas_admin', False),
                    'can_access_all_companies': getattr(request.user, 'can_access_all_companies', False),
                    'saas_admin_context': getattr(request, 'saas_admin_context', {}),
                })

        return response




class AuditMiddleware(MiddlewareMixin):
    """
    Middleware to track request timing for audit logs
    """

    def process_request(self, request):
        """Store request start time"""
        request._audit_start_time = time.time()

    def process_response(self, request, response):
        """Calculate request duration"""
        if hasattr(request, '_audit_start_time'):
            duration = (time.time() - request._audit_start_time) * 1000  # Convert to ms
            request._audit_duration = int(duration)

        return response


class RefreshPermissionsMiddleware:
    """Ensure user permissions are fresh on each request"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if hasattr(request, 'user') and request.user.is_authenticated:
            # Clear permission cache
            if hasattr(request.user, '_perm_cache'):
                delattr(request.user, '_perm_cache')
            if hasattr(request.user, '_user_perm_cache'):
                delattr(request.user, '_user_perm_cache')
            if hasattr(request.user, '_group_perm_cache'):
                delattr(request.user, '_group_perm_cache')

        response = self.get_response(request)
        return response