# company/views/pause_views.py

import json
import logging
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import redirect
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django_tenants.utils import schema_context

from company.services.pause_service import (
    set_efris_fiscalization_mode,
    user_can_manage_efris_pause,
)

logger = logging.getLogger(__name__)

# ── Where to redirect after a successful/failed toggle ───────────────────────
# Change this to match your actual settings URL name.
SETTINGS_REDIRECT_URL = 'company:invoice_settings'


class EFRISModeToggleView(LoginRequiredMixin, View):
    """
    Handles toggling of the EFRIS fiscalization mode.

    Accepts:
        POST with JSON body: {"mode": "enabled"|"disabled"|"paused"}
        POST with form data: mode=enabled  (standard Django form)

    Returns:
        JSON  → if request has Accept: application/json or X-Requested-With: XMLHttpRequest
        Redirect → otherwise (standard form submit)
    """

    http_method_names = ['post']

    def post(self, request, *args, **kwargs):
        user = request.user
        # request.tenant is set by django-tenants middleware for every tenant request.
        company = getattr(request, 'tenant', None) or getattr(user, 'company', None)

        # ── Sanity checks ─────────────────────────────────────────────────────
        if not company:
            return self._respond(
                request,
                success=False,
                message='Could not determine your company. Please refresh and try again.',
            )

        schema = company.schema_name

        # ── Only company admins and above may touch this setting ──────────────
        # has_perm() reads from auth_permission which lives in the tenant schema,
        # so we pass the schema_name through to the helper.
        if not self._user_can_toggle(user, schema):
            return self._respond(
                request,
                success=False,
                message='You do not have permission to change EFRIS settings.',
                status=403,
            )

        # ── Parse the requested mode ──────────────────────────────────────────
        new_mode = self._parse_mode(request)
        if not new_mode:
            return self._respond(
                request,
                success=False,
                message='Invalid or missing mode value.',
                status=400,
            )

        # ── Delegate ALL business logic to the service ────────────────────────
        result = set_efris_fiscalization_mode(
            company=company,
            new_mode=new_mode,
            changed_by=user,
        )

        return self._respond(
            request,
            success=result['success'],
            message=result['message'],
            extra=result.get('details', {}),
            status=200 if result['success'] else 400,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _user_can_toggle(self, user, schema: str) -> bool:
        """
        Checks if the user has MINIMUM permission to touch EFRIS settings at all.
        (Pause-specific check is handled inside the service.)

        Permission tables live in the tenant schema, so we switch to it before
        calling has_perm().
        """
        if getattr(user, 'is_saas_admin', False):
            return True
        if getattr(user, 'company_admin', False):
            return True
        # Allow users with the general settings management permission.
        # accounts is a TENANT_APP → wrap in schema_context.
        with schema_context(schema):
            return user.has_perm('accounts.can_manage_settings')

    def _parse_mode(self, request) -> str | None:
        """Parse mode from JSON body or form POST."""
        # Try JSON first
        if request.content_type and 'application/json' in request.content_type:
            try:
                data = json.loads(request.body)
                return data.get('mode', '').strip().lower() or None
            except (json.JSONDecodeError, AttributeError):
                return None

        # Fall back to form POST
        return request.POST.get('mode', '').strip().lower() or None

    def _is_ajax(self, request) -> bool:
        return (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('Accept', '')
        )

    def _respond(self, request, success: bool, message: str, extra: dict = None, status: int = 200):
        """Return JSON for AJAX requests, redirect+messages for standard POSTs."""
        if self._is_ajax(request):
            payload = {'success': success, 'message': message}
            if extra:
                payload['details'] = extra
            return JsonResponse(payload, status=status)

        # Standard form redirect
        if success:
            messages.success(request, message)
        else:
            messages.error(request, message)

        return redirect(SETTINGS_REDIRECT_URL)


# =============================================================================
# FUNCTION-BASED VIEW ALTERNATIVE
# Use this if you prefer FBVs or need to drop into an existing view file.
# =============================================================================

@login_required
@require_POST
def efris_mode_toggle_fbv(request):
    """
    Function-based version of EFRISModeToggleView.
    Same logic, same permission rules.

    Usage in urls.py:
        path('settings/efris/mode/', efris_mode_toggle_fbv, name='efris_mode_toggle'),
    """
    user = request.user
    company = getattr(request, 'tenant', None) or getattr(user, 'company', None)

    if not company:
        return JsonResponse({'success': False, 'message': 'Company not found.'}, status=400)

    schema = company.schema_name

    # Basic permission gate — check permissions inside the tenant schema.
    can_toggle = (
        getattr(user, 'is_saas_admin', False)
        or getattr(user, 'company_admin', False)
    )
    if not can_toggle:
        with schema_context(schema):
            can_toggle = user.has_perm('accounts.can_manage_settings')

    if not can_toggle:
        return JsonResponse({'success': False, 'message': 'Permission denied.'}, status=403)

    # Parse mode
    try:
        data = json.loads(request.body)
        new_mode = data.get('mode', '').strip().lower()
    except (json.JSONDecodeError, AttributeError):
        new_mode = request.POST.get('mode', '').strip().lower()

    if not new_mode:
        return JsonResponse({'success': False, 'message': 'mode is required.'}, status=400)

    result = set_efris_fiscalization_mode(
        company=company,
        new_mode=new_mode,
        changed_by=user,
    )

    status_code = 200 if result['success'] else 400
    return JsonResponse(result, status=status_code)


# =============================================================================
# TEMPLATE CONTEXT HELPER
# Use this in your settings view to pass EFRIS mode info to the template.
# =============================================================================

def get_efris_mode_context(company, user) -> dict:
    """
    Returns context variables for rendering the EFRIS mode toggle UI.

    Usage in your existing settings view:
        from company.views.pause_views import get_efris_mode_context
        context.update(get_efris_mode_context(request.tenant, request.user))
    """
    current_mode = getattr(company, 'efris_fiscalization_mode', 'disabled')

    # user_can_manage_efris_pause() calls has_perm() which needs the tenant
    # schema — pass schema_name so it wraps internally in schema_context.
    can_pause = user_can_manage_efris_pause(user, schema_name=company.schema_name)

    return {
        'efris_current_mode': current_mode,
        'efris_is_enabled':   current_mode == 'enabled',
        'efris_is_disabled':  current_mode == 'disabled',
        'efris_is_paused':    current_mode == 'paused',
        'efris_paused_at':    company.efris_paused_at,
        'efris_paused_by': company.efris_paused_by_name,
        # Whether the current user can see/use the pause toggle
        'user_can_pause_efris': can_pause,
    }