# company/middleware.py
"""
Company middleware
─────────────────
Execution order (top → bottom in MIDDLEWARE setting):
  1. ActiveModulesMiddleware   — attaches request.active_modules
  2. CompanyAccessMiddleware   — enforces subscription status, redirects expired/suspended
  3. PlanLimitsMiddleware      — attaches request.plan_limits, blocks exceeded-limit actions
  4. WebSocketNotificationMiddleware — fires WS events after successful POST
  5. EFRISStatusMiddleware     — attaches request.efris (lazy)

All middleware classes:
  ✅ Skip in desktop mode (IS_DESKTOP=True)
  ✅ Skip in public schema (django-tenants)
  ✅ Never block Pesapal IPN/payment URLs — those must work even when subscription is expired
  ✅ Never block saas_admin users
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.core.cache import cache
from django.db import connection
from django.shortcuts import redirect
from django.utils import timezone
from django.utils.deprecation import MiddlewareMixin
from django.utils.functional import SimpleLazyObject
from django.utils.translation import gettext as _

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_tenant_schema() -> bool:
    """Return True when we are currently operating inside a tenant schema."""
    schema = getattr(connection, 'schema_name', 'public')
    return schema not in ('public', '')


def _is_desktop() -> bool:
    return getattr(settings, 'IS_DESKTOP', False)


def _is_saas_admin(user) -> bool:
    return getattr(user, 'is_saas_admin', False)


# ─────────────────────────────────────────────────────────────────────────────
# 1. ActiveModulesMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class ActiveModulesMiddleware:
    """
    Attaches the set of active module keys to every request:
        request.active_modules  →  {'salon', 'inventory', ...}

    Source of truth is CompanyModule (DB), cached in Redis for 5 minutes.
    Cache is invalidated whenever a module is toggled ON/OFF — so the change
    is visible on the very next request.

    In desktop mode all available modules are returned unconditionally.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.active_modules = self._resolve_modules(request)
        return self.get_response(request)

    # ── internals ─────────────────────────────────────────────────────────────

    def _resolve_modules(self, request) -> set:
        # Public schema or unauthenticated — no modules
        if not hasattr(request, 'tenant') or not request.tenant:
            return set()

        # Desktop mode — all modules on
        if _is_desktop():
            return self._all_module_keys()

        schema    = request.tenant.schema_name
        cache_key = f'active_modules:{schema}'
        cached    = cache.get(cache_key)

        if cached is not None:
            return cached

        # Cache miss — query DB
        try:
            from company.models import CompanyModule
            keys = set(
                CompanyModule.objects
                .filter(company=request.tenant, is_active=True)
                .values_list('module__key', flat=True)
            )
        except Exception as exc:
            logger.error('ActiveModulesMiddleware DB error: %s', exc)
            keys = set()

        cache.set(cache_key, keys, 300)
        return keys

    @staticmethod
    def _all_module_keys() -> set:
        try:
            from company.models import AvailableModule
            return set(AvailableModule.objects.values_list('key', flat=True))
        except Exception:
            return set()


# ─────────────────────────────────────────────────────────────────────────────
# 2. CompanyAccessMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class CompanyAccessMiddleware:
    """
    Enforces company subscription status on every authenticated request.

    Status → action mapping:
      EXPIRED    → redirect to companies:company_expired
      SUSPENDED  → in grace period → companies:company_grace_period
                   past grace      → companies:company_suspended
      inactive   → logout + redirect to companies:company_deactivated

    The following URL prefixes are always allowed through regardless of status,
    so that payment/IPN flows and billing pages always remain reachable:

        /admin/                 Django admin
        /accounts/login/        Login page
        /accounts/logout/       Logout
        /companies/expired/     Expired landing page (would cause redirect loop otherwise)
        /companies/grace/       Grace period landing page
        /companies/suspended/   Suspended landing page
        /companies/deactivated/ Deactivated landing page
        /companies/billing/     Billing history / invoice download
        /companies/subscription/ Renewal, plans, dashboard
        /pesapal/               ALL Pesapal IPN and callback endpoints
        /pay/                   Public invoice/sale payment pages
        /api/webhooks/          External webhook receivers
        /static/                Static files
        /media/                 Media files
        /desktop/               Desktop-mode endpoints

    Performance:
      - Company PK is cached per-user for 30 s (avoids repeated FK lookups).
      - check_and_update_access_status() is called at most once per minute per
        company (guarded by a separate cache key) to avoid a DB write on every
        single request.
    """

    # URL prefixes that are ALWAYS accessible regardless of company status.
    # ⚠️  /pesapal/ and /pay/ MUST remain here — removing them breaks payments
    #     for tenants whose subscription is expired.
    EXEMPT_PREFIXES = (
        '/admin/',
        '/accounts/login/',
        '/accounts/logout/',
        '/companies/expired/',
        '/companies/grace/',
        '/companies/suspended/',
        '/companies/deactivated/',
        '/companies/billing/',
        '/companies/subscription/',
        '/pesapal/',
        '/pay/',
        '/api/webhooks/',
        '/static/',
        '/media/',
        '/desktop/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip entirely in desktop mode
        if _is_desktop():
            return self.get_response(request)

        # Skip for public schema — tenant user table doesn't exist there
        if not _is_tenant_schema():
            return self.get_response(request)

        # Skip exempt URLs
        if self._is_exempt(request.path):
            return self.get_response(request)

        # Only applies to authenticated non-saas-admin users
        if not request.user.is_authenticated:
            return self.get_response(request)

        if _is_saas_admin(request.user):
            return self.get_response(request)

        company = self._get_company(request.user)
        if not company:
            return self.get_response(request)

        # Run status update at most once per minute to avoid per-request DB writes
        self._maybe_update_status(company)

        response = self._enforce_status(request, company)
        return response if response else self.get_response(request)

    # ── URL exemption ─────────────────────────────────────────────────────────

    def _is_exempt(self, path: str) -> bool:
        return path.startswith(self.EXEMPT_PREFIXES)

    # ── Status enforcement ────────────────────────────────────────────────────

    def _enforce_status(self, request, company):
        status = company.status

        if status == 'EXPIRED':
            # No flash message here — the expired page itself explains everything.
            # Adding messages.error() on every request causes stacked alert spam.
            return redirect('companies:company_expired')

        if status == 'SUSPENDED':
            if company.is_in_grace_period:
                messages.warning(
                    request,
                    _(
                        'Your subscription expired on %(end)s. '
                        'You have until %(grace)s to renew before access is fully suspended.'
                    ) % {
                        'end':   company.subscription_ends_at.strftime('%d %b %Y') if company.subscription_ends_at else '—',
                        'grace': company.grace_period_ends_at.strftime('%d %b %Y') if company.grace_period_ends_at else '—',
                    }
                )
                return redirect('companies:company_grace_period')
            else:
                messages.error(
                    request,
                    _('Your company account has been suspended. Please contact support.')
                )
                return redirect('companies:company_suspended')

        if not company.is_active:
            messages.error(
                request,
                _('Your company account has been deactivated. Please contact support.')
            )
            logout(request)
            return redirect('companies:company_deactivated')

        return None

    # ── Company fetch (PK cached 30 s) ────────────────────────────────────────

    def _get_company(self, user):
        """
        Fetch a fresh Company instance from the DB.
        We cache only the PK (30 s) to skip the FK resolution overhead.
        The full object is always re-fetched so status fields are current.
        """
        try:
            from company.models import Company

            pk_cache_key = f'user_company_pk:{user.id}'
            company_pk   = cache.get(pk_cache_key)

            if company_pk is None:
                company_pk = (
                    getattr(user, 'company_id', None)
                    or (user.company.pk if getattr(user, 'company', None) else None)
                )
                if company_pk:
                    cache.set(pk_cache_key, company_pk, 30)

            if not company_pk:
                return None

            return Company.objects.select_related('plan').get(pk=company_pk)

        except Exception as exc:
            logger.error('CompanyAccessMiddleware._get_company error (user=%s): %s', user.id, exc)
            return None

    # ── Status check throttle (once per minute per company) ───────────────────

    @staticmethod
    def _maybe_update_status(company):
        """
        Call company.check_and_update_access_status() at most once per minute.
        This prevents a DB write on every single request while still keeping
        the status up-to-date within a reasonable window.
        """
        throttle_key = f'status_checked:{company.pk}'
        if cache.get(throttle_key):
            return  # Already ran within the last 60 seconds

        try:
            changed = company.check_and_update_access_status()
            if changed:
                logger.info(
                    'Company %s status updated to %s',
                    company.company_id, company.status
                )
        except Exception as exc:
            logger.error('check_and_update_access_status error (company=%s): %s', company.pk, exc)

        cache.set(throttle_key, True, 60)


# ─────────────────────────────────────────────────────────────────────────────
# 3. PlanLimitsMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class PlanLimitsMiddleware:
    """
    Attaches request.plan_limits with current usage vs. plan caps.
    Also blocks requests from companies that have lost active access
    (belt-and-suspenders after CompanyAccessMiddleware).

    request.plan_limits = {
        'users':    {'current', 'limit', 'available', 'exceeded'},
        'branches': {'current', 'limit', 'available', 'exceeded'},
        'storage':  {'current_mb', 'limit_gb', 'percentage', 'exceeded'},
    }
    """

    EXEMPT_PREFIXES = (
        '/admin/',
        '/accounts/logout/',
        '/companies/subscription/',
        '/companies/billing/',
        '/companies/profile/',
        '/companies/expired/',
        '/companies/grace/',
        '/companies/suspended/',
        '/companies/deactivated/',
        '/pesapal/',
        '/pay/',
        '/api/',
        '/static/',
        '/media/',
        '/desktop/',
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _is_desktop():
            return self.get_response(request)

        if not _is_tenant_schema():
            return self.get_response(request)

        if not request.user.is_authenticated:
            return self.get_response(request)

        if _is_saas_admin(request.user):
            return self.get_response(request)

        if request.path.startswith(self.EXEMPT_PREFIXES):
            return self.get_response(request)

        company = getattr(request.user, 'company', None)
        if not company:
            return self.get_response(request)

        # Belt-and-suspenders: if CompanyAccessMiddleware somehow let an
        # inactive company through, stop here and redirect to expired page
        # (no flash message — CompanyAccessMiddleware already handled that).
        if not company.has_active_access:
            return redirect('companies:company_expired')

        request.plan_limits = self._build_limits(company)
        return self.get_response(request)

    # ── Limit calculation ─────────────────────────────────────────────────────

    @staticmethod
    def _build_limits(company) -> dict:
        plan = company.plan

        max_users    = plan.max_users    if plan else 0
        max_branches = plan.max_branches if plan else 0
        max_storage  = plan.max_storage_gb if plan else 0

        current_users    = company.active_users_count
        current_branches = company.branches_count
        storage_pct      = company.storage_usage_percentage

        return {
            'users': {
                'current':  current_users,
                'limit':    max_users,
                'available': max(0, max_users - current_users),
                'exceeded': current_users >= max_users if max_users else False,
            },
            'branches': {
                'current':  current_branches,
                'limit':    max_branches,
                'available': max(0, max_branches - current_branches),
                'exceeded': current_branches >= max_branches if max_branches else False,
            },
            'storage': {
                'current_mb': company.storage_used_mb,
                'limit_gb':   max_storage,
                'percentage': storage_pct,
                'exceeded':   storage_pct >= 100,
            },
        }


# ─────────────────────────────────────────────────────────────────────────────
# 4. WebSocketNotificationMiddleware
# ─────────────────────────────────────────────────────────────────────────────

class WebSocketNotificationMiddleware(MiddlewareMixin):
    """
    Fires WebSocket group messages to the company dashboard channel after
    successful POST requests that mutate specific resources (e.g. branches).

    Disabled automatically in desktop mode or when no channel layer is
    configured (avoids import errors in environments without Redis/Channels).
    """

    def __init__(self, get_response):
        self.get_response   = get_response
        self.channel_layer  = (
            get_channel_layer()
            if not _is_desktop()
            else None
        )

    def __call__(self, request):
        response = self.get_response(request)

        if _is_desktop() or not self.channel_layer:
            return response

        if (
            hasattr(request, 'user')
            and request.user.is_authenticated
            and request.method == 'POST'
            and response.status_code in (200, 201, 302)
        ):
            self._maybe_notify(request)

        return response

    def _maybe_notify(self, request):
        try:
            user    = request.user
            company = getattr(user, 'company', None)

            if '/branches/' in request.path and company:
                async_to_sync(self.channel_layer.group_send)(
                    f'company_dashboard_{company.company_id}',
                    {
                        'type': 'dashboard_update',
                        'data': {
                            'event_type': 'branch_action',
                            'message':    'Branch data has been updated',
                            'user':       user.get_full_name() or user.username,
                            'timestamp':  timezone.now().isoformat(),
                        },
                    }
                )
        except Exception as exc:
            # WS errors are non-fatal — log at DEBUG to avoid noise
            logger.debug('WebSocketNotificationMiddleware error: %s', exc)


# ─────────────────────────────────────────────────────────────────────────────
# 5. EFRISStatusMiddleware
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_efris_status(request) -> dict:
    """
    Build the EFRIS status dict for this request.
    Called lazily — only evaluated when request.efris is first accessed.
    """
    status = {'enabled': False, 'is_active': False, 'company': None}

    company = None

    if hasattr(request, 'tenant') and request.tenant:
        company = request.tenant
    elif request.user.is_authenticated:
        stores = getattr(request.user, 'stores', None)
        if stores is not None:
            try:
                store = stores.select_related('company').first()
                if store:
                    company = store.company
            except Exception:
                pass

    if company:
        status['company']   = company
        status['enabled']   = getattr(company, 'efris_enabled', False)
        status['is_active'] = getattr(company, 'efris_is_active', False)

    return status


class EFRISStatusMiddleware:
    """
    Attaches request.efris (lazy dict) to every request so templates and
    views can check EFRIS availability without hitting the DB unless needed.

        request.efris['enabled']    → bool
        request.efris['is_active']  → bool
        request.efris['company']    → Company | None
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.efris = SimpleLazyObject(lambda: _resolve_efris_status(request))
        return self.get_response(request)