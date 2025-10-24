from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from .views import trigger_error_response


class CustomErrorMiddleware(MiddlewareMixin):
    """
    Custom middleware to handle specific error scenarios
    """

    def process_exception(self, request, exception):
        """
        Handle exceptions and route to appropriate error pages
        """
        # Handle specific exception types
        if isinstance(exception, PermissionError):
            return trigger_error_response(request, 403, exception)
        elif isinstance(exception, ConnectionError):
            return trigger_error_response(request, 502, exception)
        elif isinstance(exception, TimeoutError):
            return trigger_error_response(request, 408, exception)

        # Let Django handle other exceptions normally
        return None

    def process_response(self, request, response):
        """
        Intercept responses and customize error pages
        """
        # Handle maintenance mode
        if getattr(settings, 'MAINTENANCE_MODE', False):
            if not request.user.is_staff:  # Allow staff to access during maintenance
                return trigger_error_response(request, 503)

        # Handle rate limiting (if using django-ratelimit or similar)
        if hasattr(response, 'status_code') and response.status_code == 429:
            return trigger_error_response(request, 429)

        return response

