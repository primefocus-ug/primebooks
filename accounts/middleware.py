# accounts/middleware.py - FIXED WITH SCHEMA AWARENESS
"""
Accounts middleware with schema awareness
✅ All middleware check schema before accessing user
"""
from django.shortcuts import redirect
from django.contrib import messages
from django.utils.deprecation import MiddlewareMixin
from django.contrib.auth import get_user_model
from django_tenants.utils import get_tenant_model, get_public_schema_name
from django.db import connection
import time
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class RolePermissionMiddleware:
    """Ensure permissions are loaded from roles"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ✅ CHECK SCHEMA
        schema_name = getattr(connection, 'schema_name', 'public')

        if schema_name != 'public':
            if hasattr(request, 'user') and request.user.is_authenticated:
                # Refresh the user object in place so all existing references
                # (including request.user itself) see up-to-date permissions.
                # Avoid replacing request.user with a SimpleLazyObject, which
                # creates stale-reference hazards for code that cached the old object.
                self._refresh_user_in_place(request)

        response = self.get_response(request)
        return response

    def _refresh_user_in_place(self, request):
        try:
            fresh_user = (
                get_user_model()
                .objects
                .select_related('company')
                .prefetch_related('groups__permissions', 'user_permissions')
                .get(pk=request.user.pk)
            )
            # Copy freshly-fetched permission state onto the existing user
            # object so all callers that hold a reference to request.user
            # automatically see the updated data.
            request.user.__dict__.update(fresh_user.__dict__)
            # Clear any stale permission caches carried over from the session
            for cache_attr in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
                request.user.__dict__.pop(cache_attr, None)
        except Exception as e:
            logger.error(f"Error refreshing user permissions: {e}")


class SaaSAdminAccessMiddleware(MiddlewareMixin):
    """Handle SaaS admin access across all tenants"""

    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.get_response = get_response

    def process_request(self, request):
        if self._should_skip_processing(request):
            return None

        # ✅ CHECK SCHEMA - But SaaS admins can access any schema
        # So we don't skip based on schema, but we check tenant exists
        if not hasattr(connection, 'tenant') or connection.tenant is None:
            return None

        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return None

        if not getattr(request.user, 'is_saas_admin', False):
            return None

        return self._handle_saas_admin_access(request)

    def _should_skip_processing(self, request):
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
        current_tenant = getattr(request, 'tenant', None)
        if not current_tenant:
            return None

        tenant_switch = request.GET.get('switch_tenant')
        if tenant_switch:
            return self._handle_tenant_switch(request, tenant_switch)

        request.saas_admin_context = {
            'can_switch_tenants': True,
            'current_tenant': current_tenant,
            'available_tenants': self._get_available_tenants(request.user)
        }

        return None

    def _handle_tenant_switch(self, request, tenant_id):
        try:
            Tenant = get_tenant_model()
            target_tenant = Tenant.objects.get(id=tenant_id)
            target_url = self._build_tenant_url(target_tenant, request)
            messages.success(request, f'Switched to tenant: {target_tenant.name}')
            return redirect(target_url)
        except Exception as e:
            messages.error(request, f'Error switching tenant: {str(e)}')
            return None

    def _build_tenant_url(self, tenant, request):
        primary_domain = tenant.domains.filter(is_primary=True).first()
        if primary_domain:
            protocol = 'https' if getattr(primary_domain, 'ssl_enabled', False) else 'http'
            domain = primary_domain.domain
            path = request.path
            query_string = request.META.get('QUERY_STRING', '')

            if query_string:
                query_parts = [part for part in query_string.split('&')
                               if not part.startswith('switch_tenant=')]
                query_string = '&'.join(query_parts)

            url = f"{protocol}://{domain}{path}"
            if query_string:
                url += f"?{query_string}"
            return url

        return request.build_absolute_uri(request.path)

    def _get_available_tenants(self, user):
        if not user.is_saas_admin:
            return []

        try:
            Tenant = get_tenant_model()
            return Tenant.objects.exclude(
                schema_name='public'
            ).select_related().order_by('name')[:50]
        except Exception:
            return []


class HiddenUserMiddleware(MiddlewareMixin):
    """Ensure hidden users are not shown in regular listings"""

    def process_view(self, request, view_func, view_args, view_kwargs):
        # ✅ CHECK SCHEMA
        schema_name = getattr(connection, 'schema_name', 'public')
        if schema_name == 'public':
            return None

        if hasattr(request, 'user') and request.user.is_authenticated:
            request.get_visible_users = lambda qs=None: self._get_visible_users(qs)
            request.get_company_user_count = lambda company: self._get_company_user_count(company)

        return None

    def _get_visible_users(self, queryset=None):
        if queryset is None:
            queryset = User.objects.all()
        return queryset.filter(is_hidden=False)

    def _get_company_user_count(self, company):
        return User.objects.filter(
            company=company,
            is_hidden=False,
            is_active=True
        ).count()


class SaaSAdminContextMiddleware(MiddlewareMixin):
    """Add SaaS admin context to templates"""

    def process_template_response(self, request, response):
        # ✅ CHECK SCHEMA
        schema_name = getattr(connection, 'schema_name', 'public')

        if not hasattr(request, 'user') or not request.user.is_authenticated:
            return response

        extra = {
            'is_saas_admin': getattr(request.user, 'is_saas_admin', False),
            'can_access_all_companies': getattr(request.user, 'can_access_all_companies', False),
            'saas_admin_context': getattr(request, 'saas_admin_context', {}),
            'current_schema': schema_name,
        }

        # TemplateResponse (class-based views) stores context in context_data
        if hasattr(response, 'context_data') and response.context_data is not None:
            response.context_data.update(extra)
        # render() / render_to_response() stores context in context dict
        elif hasattr(response, 'context') and isinstance(response.context, dict):
            response.context.update(extra)

        return response


class AuditMiddleware(MiddlewareMixin):
    """Track request timing for audit logs"""

    def process_request(self, request):
        request._audit_start_time = time.time()

    def process_response(self, request, response):
        if hasattr(request, '_audit_start_time'):
            duration = (time.time() - request._audit_start_time) * 1000
            request._audit_duration = int(duration)
        return response


class RefreshPermissionsMiddleware:
    """Ensure user permissions are fresh after state-mutating requests"""

    # Only clear caches after requests that could change permissions
    MUTATING_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # ✅ CHECK SCHEMA — only applies to tenant schemas
        schema_name = getattr(connection, 'schema_name', 'public')

        if (
            schema_name != 'public'
            and request.method in self.MUTATING_METHODS
            and hasattr(request, 'user')
            and request.user.is_authenticated
        ):
            # Clear permission cache so the next request sees fresh data
            for cache_attr in ['_perm_cache', '_user_perm_cache', '_group_perm_cache']:
                request.user.__dict__.pop(cache_attr, None)

        return response