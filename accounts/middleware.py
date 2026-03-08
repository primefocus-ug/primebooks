# accounts/middleware.py
"""
Accounts middleware with schema awareness
✅ All middleware check schema before accessing user
✅ StrictSingleSessionMiddleware — one active session per user account
✅ Concurrent-IP detection wired to SharingDetectionEngine
"""
from django.shortcuts import redirect
from django.contrib import messages
from django.contrib.auth import get_user_model, logout
from django.utils.deprecation import MiddlewareMixin
from django.utils import timezone
from django.core.cache import cache
from django.http import JsonResponse
from django.urls import reverse
from django_tenants.utils import get_tenant_model, get_public_schema_name
from django.db import connection
import time
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


# =============================================================================
# Cache key helpers — imported by views.py, api_views.py, signals.py
# =============================================================================

def _active_session_cache_key(user_id: int) -> str:
    return f"active_session:{user_id}"


def _active_token_cache_key(user_id: int) -> str:
    return f"active_token:{user_id}"


def register_session(user, session_key: str, ttl: int = 60 * 60 * 24 * 30) -> None:
    """Call immediately after a successful cookie-based login."""
    cache.set(_active_session_cache_key(user.pk), session_key, timeout=ttl)
    logger.debug(f"[StrictSession] Registered session for user {user.pk}")


def register_token(user, token_key: str, ttl: int = 60 * 60 * 24 * 30) -> None:
    """Call immediately after a successful token-based login."""
    cache.set(_active_token_cache_key(user.pk), token_key, timeout=ttl)
    logger.debug(f"[StrictSession] Registered token for user {user.pk}")


def clear_session_registry(user_id: int) -> None:
    """Remove both registry entries — call on explicit logout or security lock."""
    cache.delete(_active_session_cache_key(user_id))
    cache.delete(_active_token_cache_key(user_id))


# =============================================================================
# StrictSingleSessionMiddleware
# =============================================================================

class StrictSingleSessionMiddleware:
    """
    Enforces one active session per user account.

    On every authenticated request:
      • Cookie session  — compares session_key against the one registered at
                          login. Mismatch → force-logout + redirect (or 401).
      • DRF token       — compares Authorization token against the registered
                          one. Mismatch → 401 with code 'token_superseded'.
      • Concurrent IPs  — runs ConcurrentRequestDetector once per
                          CONCURRENT_CHECK_COOLDOWN seconds per user.

    MIDDLEWARE order (settings.py):
        'django.contrib.sessions.middleware.SessionMiddleware',
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'accounts.middleware.StrictSingleSessionMiddleware',   ← here
    """

    # Paths that bypass enforcement entirely
    EXEMPT_PATHS = {
        '/accounts/login/',
        '/accounts/logout/',
        '/api/auth/login/',
        '/api/auth/register/',
        '/admin/login/',
        '/admin/logout/',
        '/health/',
        '/favicon.ico',
    }

    # Run the concurrent-IP detector at most once per N seconds per user
    CONCURRENT_CHECK_COOLDOWN = 10   # seconds

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self._enforce(request)
        if response is not None:
            return response
        return self.get_response(request)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_exempt(self, request) -> bool:
        path = request.path_info
        return (
            path in self.EXEMPT_PATHS
            or path.startswith(('/static/', '/media/'))
        )

    def _is_api(self, request) -> bool:
        return (
            request.path_info.startswith('/api/')
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('Accept', '')
        )

    def _reject_session(self, request):
        """Force-logout a superseded cookie session."""
        user = request.user
        logger.warning(
            f"[StrictSession] Kicking superseded session for user {user.pk} ({user.email})"
        )
        try:
            user.last_activity_at = timezone.now()
            user.save(update_fields=['last_activity_at'])
        except Exception:
            pass
        logout(request)

        if self._is_api(request):
            return JsonResponse(
                {
                    'detail': 'Your account was signed in on another device. '
                              'You have been signed out.',
                    'code': 'session_superseded',
                },
                status=401,
            )
        login_url = reverse('login')
        return redirect(f"{login_url}?reason=session_superseded")

    def _reject_token(self):
        """Return 401 for a superseded DRF token."""
        return JsonResponse(
            {
                'detail': 'Your session has been superseded by a new login. '
                          'Please log in again.',
                'code': 'token_superseded',
            },
            status=401,
        )

    def _enforce(self, request):
        """
        Returns an HttpResponse to short-circuit the request, or None to
        allow it through.
        """
        # Skip public schema entirely — no user tables there
        schema_name = getattr(connection, 'schema_name', 'public')
        if schema_name == 'public':
            return None

        if self._is_exempt(request):
            return None

        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        is_token_request = auth_header.lower().startswith('token ')

        user = getattr(request, 'user', None)
        is_authenticated = user is not None and user.is_authenticated

        # ── DRF token auth ────────────────────────────────────────────
        if is_token_request:
            return self._enforce_token(request, auth_header, user if is_authenticated else None)

        # ── Cookie / session auth ─────────────────────────────────────
        if not is_authenticated:
            return None

        session_key = request.session.session_key
        if not session_key:
            return None

        registered = cache.get(_active_session_cache_key(user.pk))

        if registered is None:
            # Cold start (cache flush / server restart) — re-register this session
            register_session(user, session_key)
        elif registered != session_key:
            return self._reject_session(request)

        # ── Concurrent-IP check (throttled) ──────────────────────────
        self._maybe_run_concurrent_check(request, user)

        return None

    def _enforce_token(self, request, auth_header: str, user=None):
        try:
            token_key = auth_header.split(' ', 1)[1].strip()
        except IndexError:
            return None   # Malformed — let DRF handle it

        if user is None:
            try:
                from rest_framework.authtoken.models import Token as DRFToken
                token_obj = DRFToken.objects.select_related('user').get(key=token_key)
                user = token_obj.user
            except Exception:
                return None   # Invalid token — let DRF return 401

        registered = cache.get(_active_token_cache_key(user.pk))

        if registered is None:
            register_token(user, token_key)
        elif registered != token_key:
            return self._reject_token()

        self._maybe_run_concurrent_check(request, user)
        return None

    def _maybe_run_concurrent_check(self, request, user):
        """
        Run ConcurrentRequestDetector at most once per COOLDOWN period per
        user so it doesn't fire on every single request.
        """
        cooldown_key = f"concurrent_cooldown:{user.pk}"
        if cache.get(cooldown_key):
            return

        cache.set(cooldown_key, 1, timeout=self.CONCURRENT_CHECK_COOLDOWN)

        try:
            from accounts.sharing_detection import (
                SharingDetectionEngine,
                DetectionContext,
                ConcurrentRequestDetector,
            )
            from accounts.utils import get_client_ip

            ip = get_client_ip(request)
            ua = request.META.get('HTTP_USER_AGENT', '')
            ctx = DetectionContext(
                user_id=user.pk,
                user_email=user.email,
                ip_address=ip or '0.0.0.0',
                user_agent=ua,
                fingerprint_hash='',    # not available mid-request
                latitude=None,
                longitude=None,
                timestamp=timezone.now(),
            )

            result = ConcurrentRequestDetector().detect(ctx)
            if result.is_suspicious:
                engine = SharingDetectionEngine()
                engine._record_suspicion(user, ctx, [result], result.score)
                if result.score >= 70:
                    engine._take_action(user, ctx, [result], result.score, request)

        except Exception as exc:
            logger.debug(f"[StrictSession] Concurrent check skipped: {exc}")


# =============================================================================
# Existing middleware (unchanged below)
# =============================================================================


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