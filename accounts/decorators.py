from functools import wraps
from django.http import HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import connection


def tenant_required(view_func):
    """
    Decorator to ensure we're not in public schema
    """
    @wraps(view_func)
    @login_required
    def _wrapped_view(request, *args, **kwargs):
        # Allow access only in tenant schemas
        if connection.schema_name == 'public':
            messages.error(request, 'This feature is only available for company accounts.')
            return HttpResponseForbidden("Tenant context required")
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def company_admin_required(view_func):
    """
    Decorator for company admin-only views
    """
    @wraps(view_func)
    @tenant_required
    def _wrapped_view(request, *args, **kwargs):
        if not (request.user.is_staff or 
                request.user.company_admin or
                request.user.has_perm('accounts.add_customuser')):
            messages.error(request, 'You do not have permission to access this page.')
            return HttpResponseForbidden("Admin access required")
        return view_func(request, *args, **kwargs)
    return _wrapped_view


def public_schema_required(view_func):
    """
    Decorator to ensure we're in public schema (for tenant management)
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if connection.schema_name != 'public':
            messages.error(request, 'This feature is only available from the main site.')
            return HttpResponseForbidden("Public schema required")
        
        return view_func(request, *args, **kwargs)
    return _wrapped_view
