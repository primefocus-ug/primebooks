from functools import wraps
from django.conf import settings

def maintenance_mode_check(view_func):
    """Check for maintenance mode before executing view"""
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if (getattr(settings, 'MAINTENANCE_MODE', False) and
            not request.user.is_staff):
            from .views import error_503_view
            return error_503_view(request)
        return view_func(request, *args, **kwargs)
    return _wrapped_view