# errors/middleware.py - FIXED
"""
Error handling middleware with schema awareness
"""
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings
from django.db import connection
import logging

logger = logging.getLogger(__name__)


class CustomErrorMiddleware(MiddlewareMixin):
    """Custom middleware to handle specific error scenarios"""

    def process_exception(self, request, exception):
        # Handle specific exception types
        if isinstance(exception, PermissionError):
            from .views import trigger_error_response
            return trigger_error_response(request, 403, exception)
        elif isinstance(exception, ConnectionError):
            from .views import trigger_error_response
            return trigger_error_response(request, 502, exception)
        elif isinstance(exception, TimeoutError):
            from .views import trigger_error_response
            return trigger_error_response(request, 408, exception)

        return None

    def process_response(self, request, response):
        # Handle maintenance mode
        if getattr(settings, 'MAINTENANCE_MODE', False):
            if not request.user.is_staff:
                from .views import trigger_error_response
                return trigger_error_response(request, 503)

        # Handle rate limiting
        if hasattr(response, 'status_code') and response.status_code == 429:
            from .views import trigger_error_response
            return trigger_error_response(request, 429)

        return response

