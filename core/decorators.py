from functools import wraps
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.contrib import messages


def require_module(module_key):
    """
    View decorator. Blocks access if the tenant has not activated
    the specified module.

    Usage on function-based views:
        @login_required
        @require_module('salon')
        def appointments_view(request):
            ...

    Usage on class-based views — use RequireModuleMixin instead
    (see core/mixins.py).

    What happens when blocked:
    - If the request is AJAX → returns JSON 403 response
    - Otherwise → redirects to the App Store with a message
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            active = getattr(request, 'active_modules', set())

            if module_key not in active:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': f"The '{module_key}' module is not enabled for your account."
                    }, status=403)

                messages.warning(
                    request,
                    f"'{module_key.replace('_', ' ').title()}' module is not enabled. "
                    f"Enable it from your App Store."
                )
                return redirect('company:module_store')

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def efris_required(view_func=None, redirect_url=None):
    """
    Decorator to require EFRIS to be enabled
    Usage:
        @efris_required
        def my_view(request):
            ...

        @efris_required(redirect_url='dashboard')
        def my_view(request):
            ...
    """

    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not hasattr(request, 'tenant') or not request.tenant.efris_enabled:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': False,
                        'error': 'EFRIS integration is not enabled for this company.'
                    }, status=403)

                messages.error(request, 'EFRIS integration must be enabled to access this feature.')

                if redirect_url:
                    return redirect(redirect_url)
                return HttpResponseForbidden('EFRIS integration is not enabled.')

            return func(request, *args, **kwargs)

        return wrapper

    if view_func:
        return decorator(view_func)
    return decorator


def efris_active_required(view_func=None, redirect_url=None):
    """
    Decorator to require EFRIS to be enabled AND active
    Usage:
        @efris_active_required
        def my_view(request):
            ...
    """

    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            tenant = getattr(request, 'tenant', None)

            if not tenant or not tenant.efris_enabled:
                messages.error(request, 'EFRIS integration must be enabled.')
                if redirect_url:
                    return redirect(redirect_url)
                return HttpResponseForbidden('EFRIS not enabled')

            if not tenant.efris_is_active:
                messages.error(request, 'EFRIS integration is enabled but not active. Please complete configuration.')
                if redirect_url:
                    return redirect(redirect_url)
                return HttpResponseForbidden('EFRIS not active')

            return func(request, *args, **kwargs)

        return wrapper

    if view_func:
        return decorator(view_func)
    return decorator
