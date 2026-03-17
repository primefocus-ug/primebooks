import json
from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_GET
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

from .models import UserNavigationPreference, TenantWorkspaceDefault
from .navigation import NAVIGATION_ITEMS


# ─────────────────────────────────────────────────────────────────────────────
# USER PREFERENCES
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_GET
def get_nav_preferences(request):
    """
    GET /nav-preferences/
    Returns hidden_items, raw workspace_layout override, and the
    fully-resolved effective layout (tenant default + user override).
    """
    pref = UserNavigationPreference.get_for_user(request.user)
    return JsonResponse({
        'hidden_items':      pref.hidden_items,
        'workspace_layout':  pref.workspace_layout or {},
        'effective_layout':  pref.effective_layout(),
        'tenant_default':    TenantWorkspaceDefault.get().to_dict(),
    })


@login_required
@require_POST
def save_nav_preferences(request):
    """
    POST /nav-preferences/save/
    Body: {
        "hidden_items": [...],          -- optional, keep existing if omitted
        "workspace_layout": {           -- optional user overrides
            "navMode":      "sidebar"|"topnav"|"tabs"|null,
            "headerOrder":  [...],      -- [] means "use tenant default"
            "sidebarOrder": [...],      -- [] means "use tenant default"
        }
    }
    """
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    pref = UserNavigationPreference.get_for_user(request.user)

    if 'hidden_items' in body:
        hidden_items = body['hidden_items']
        if not isinstance(hidden_items, list):
            return JsonResponse({'error': 'hidden_items must be a list'}, status=400)
        pref.hidden_items = hidden_items

    if 'workspace_layout' in body:
        layout = body['workspace_layout']
        if not isinstance(layout, dict):
            return JsonResponse({'error': 'workspace_layout must be an object'}, status=400)
        # Validate navMode
        nav_mode = layout.get('navMode')
        if nav_mode and nav_mode not in ('sidebar', 'topnav', 'tabs'):
            return JsonResponse({'error': 'Invalid navMode'}, status=400)
        # Validate boolean accessibility fields
        for bool_field in ('highContrast', 'reduceMotion', 'focusRings', 'rtl'):
            if bool_field in layout and not isinstance(layout[bool_field], bool):
                return JsonResponse({'error': f'{bool_field} must be a boolean'}, status=400)
        # Validate numeric fontSize
        if 'fontSize' in layout:
            try:
                layout['fontSize'] = int(layout['fontSize'])
                if not (10 <= layout['fontSize'] <= 24):
                    raise ValueError
            except (TypeError, ValueError):
                return JsonResponse({'error': 'fontSize must be an integer between 10 and 24'}, status=400)
        pref.workspace_layout = layout

    pref.save()
    return JsonResponse({
        'status':           'ok',
        'hidden_items':     pref.hidden_items,
        'workspace_layout': pref.workspace_layout,
        'effective_layout': pref.effective_layout(),
    })


@login_required
@require_POST
def reset_layout_to_tenant_default(request):
    """
    POST /nav-preferences/reset-layout/
    Clears user's workspace_layout so tenant default takes over.
    """
    pref = UserNavigationPreference.get_for_user(request.user)
    pref.workspace_layout = {}
    pref.save()
    return JsonResponse({
        'status':          'ok',
        'effective_layout': pref.effective_layout(),
    })


# ─────────────────────────────────────────────────────────────────────────────
# TENANT DEFAULT (admin only)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_GET
def get_tenant_default(request):
    """
    GET /nav-preferences/tenant-default/
    Returns the current tenant-wide layout default.
    Only staff/superusers should call this.
    """
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    return JsonResponse({'tenant_default': TenantWorkspaceDefault.get().to_dict()})


@login_required
@require_POST
def save_tenant_default(request):
    """
    POST /nav-preferences/tenant-default/save/
    Saves the tenant-wide default layout. Staff/superuser only.
    Body: { "navMode": "...", "headerOrder": [...], "sidebarOrder": [...] }
    """
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': 'Forbidden'}, status=403)
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)

    td = TenantWorkspaceDefault.get()
    if 'navMode' in body:
        if body['navMode'] not in ('sidebar', 'topnav', 'tabs'):
            return JsonResponse({'error': 'Invalid navMode'}, status=400)
        td.nav_mode = body['navMode']
    if 'headerOrder' in body:
        td.header_order = body['headerOrder']
    if 'sidebarOrder' in body:
        td.sidebar_order = body['sidebarOrder']
    # Accept optional theme/accessibility defaults stored in extra_config
    extra_keys = ('accentColor', 'fontSize', 'density',
                  'highContrast', 'reduceMotion', 'focusRings', 'rtl')
    extra = td.extra_config or {}
    for key in extra_keys:
        if key in body:
            extra[key] = body[key]
    td.extra_config = extra
    td.updated_by = request.user
    td.save()
    return JsonResponse({'status': 'ok', 'tenant_default': td.to_dict()})


# ─────────────────────────────────────────────────────────────────────────────
# NAV STRUCTURE
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_GET
def get_nav_structure(request):
    """
    GET /nav-preferences/structure/
    Returns the permission-filtered, divider-cleaned nav tree for the workspace
    customiser.  Uses get_navigation_for_user() so the result is identical to
    what the sidebar renders — correct permissions, no orphan dividers, and
    hidden_items already stripped.

    Two modes controlled by ?mode=:
      customiser (default) – omits hidden_items so the customiser can show
                             every item the user *could* see and let them
                             toggle visibility themselves.
      nav                  – fully resolves hidden_items (used by topnav/tabs).
    """
    from .navigation import get_navigation_for_user

    mode = request.GET.get('mode', 'customiser')

    # For the customiser we want to show ALL permitted items so the user can
    # re-show things they previously hid.  We achieve this by temporarily
    # clearing hidden_items before calling get_navigation_for_user.
    if mode == 'customiser':
        # Build a lightweight stand-in that has no hidden items
        class _NoPrefUser:
            """Proxy that makes get_navigation_for_user ignore hidden_items."""
            pass

        # Monkey-patch: pass hidden_keys as empty so nothing is pre-hidden
        from .navigation import NAVIGATION_ITEMS
        from .models import UserNavigationPreference

        # Reuse the same logic but without applying hidden_items
        def _serialize(item, parent_key=None):
            if item.is_divider:
                return None
            key = f"{parent_key}.{item.name}" if parent_key else item.name
            children = [c for c in (_serialize(ch, key) for ch in item.children) if c is not None]
            if not item.url_name and not item.url and not children:
                return None
            url = item.get_url(request) if (item.url_name or item.url) else None
            return {
                'key':      key,
                'name':     item.name,
                'icon':     item.icon or 'bi bi-circle',
                'url':      url,
                'css':      item.css_class or '',
                'children': children,
            }

        # Run permission filtering + divider cleaning WITHOUT hidden_items
        # by calling get_navigation_for_user with a fresh preference object
        from .navigation import NavigationItem

        def _filter_no_hidden(items, parent_key=None):
            visible = []
            for item in items:
                if not item.is_visible(request.user, request):
                    continue
                item_key = f"{parent_key}.{item.name}" if parent_key else item.name
                filtered_children = _filter_no_hidden(item.children, item_key)
                cloned = NavigationItem(
                    name=item.name, url_name=item.url_name, url=item.url,
                    icon=item.icon, permission=item.permission,
                    children=filtered_children, visible_func=item.visible_func,
                    css_class=item.css_class, url_params=item.url_params,
                    url_kwargs_func=item.url_kwargs_func,
                    requires_efris=item.requires_efris, is_divider=item.is_divider,
                )
                if filtered_children or item.url_name or item.url or item.is_divider:
                    visible.append(cloned)

            # clean_dividers inline
            cleaned, i = [], 0
            for it in visible:
                if it.is_divider:
                    if cleaned and not cleaned[-1].is_divider:
                        cleaned.append(it)
                else:
                    cleaned.append(it)
            while cleaned and cleaned[-1].is_divider:
                cleaned.pop()
            return cleaned

        filtered = _filter_no_hidden(NAVIGATION_ITEMS)
        structure = [s for s in (_serialize(i) for i in filtered) if s is not None]

    else:
        # 'nav' mode: fully apply permissions + hidden_items + divider cleanup
        # This is what topnav and tabnav should use when rendering live nav.
        nav_items = get_navigation_for_user(request.user, request)

        def _serialize_full(item, parent_key=None):
            if item.is_divider:
                return None
            key = f"{parent_key}.{item.name}" if parent_key else item.name
            children = [c for c in (_serialize_full(ch, key) for ch in item.children) if c is not None]
            if not item.url_name and not item.url and not children:
                return None
            url = item.get_url(request) if (item.url_name or item.url) else None
            return {
                'key':      key,
                'name':     item.name,
                'icon':     item.icon or 'bi bi-circle',
                'url':      url,
                'css':      item.css_class or '',
                'children': children,
            }

        structure = [s for s in (_serialize_full(i) for i in nav_items) if s is not None]

    return JsonResponse({'structure': structure})