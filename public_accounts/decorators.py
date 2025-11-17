from functools import wraps
from .models import PublicUserActivity


def log_activity(action, description_template=None):
    """
    Decorator to log user activities

    Usage:
        @log_activity('CREATE', 'Created new blog post: {obj}')
        def my_view(request):
            pass
    """

    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            response = func(request, *args, **kwargs)

            if request.user.is_authenticated:
                # Get object from kwargs if available
                obj = kwargs.get('obj') or kwargs.get('object')

                description = description_template
                if description and obj:
                    description = description.format(obj=obj)

                PublicUserActivity.objects.create(
                    user=request.user,
                    action=action,
                    description=description or f'{action} action performed',
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
                )

            return response

        return wrapper

    return decorator


def get_client_ip(request):
    """Get client IP from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip