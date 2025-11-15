from django.utils.deprecation import MiddlewareMixin
import uuid


class AnalyticsMiddleware(MiddlewareMixin):
    """
    Track page views on public site.
    Add to MIDDLEWARE after SessionMiddleware
    """

    def process_request(self, request):
        # Only track public schema
        from django.db import connection
        if connection.schema_name != 'public':
            return None

        # Skip admin, static files, and analytics dashboard
        excluded_paths = ['/admin/', '/static/', '/media/', '/analytics/', '/auth/']
        if any(request.path.startswith(path) for path in excluded_paths):
            return None

        # Get or create visitor ID (cookie-based)
        visitor_id = request.COOKIES.get('visitor_id')
        if not visitor_id:
            visitor_id = str(uuid.uuid4())
            request._visitor_id = visitor_id  # Store for response processing

        # Get session ID
        if not request.session.session_key:
            request.session.create()
        session_id = request.session.session_key

        # Store IDs in request for tracking
        request.visitor_id = visitor_id
        request.session_id = session_id

        return None

    def process_response(self, request, response):
        # Set visitor ID cookie if new
        if hasattr(request, '_visitor_id'):
            response.set_cookie(
                'visitor_id',
                request._visitor_id,
                max_age=365 * 24 * 60 * 60,  # 1 year
                httponly=True,
                samesite='Lax'
            )

        # Track pageview asynchronously
        if hasattr(request, 'visitor_id') and hasattr(request, 'session_id'):
            try:
                from .tasks import track_pageview_async
                track_pageview_async.delay(
                    url_path=request.path,
                    visitor_id=request.visitor_id,
                    session_id=request.session_id,
                    request_meta={
                        'HTTP_REFERER': request.META.get('HTTP_REFERER', ''),
                        'HTTP_USER_AGENT': request.META.get('HTTP_USER_AGENT', ''),
                        'REMOTE_ADDR': self.get_client_ip(request),
                    },
                    get_params=dict(request.GET)
                )
            except Exception as e:
                # Fail silently to not break the app
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Analytics tracking failed: {str(e)}")

        return response

    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
        return ip