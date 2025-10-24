
from django.shortcuts import render
from django.http import HttpResponseNotFound
from django.utils import timezone
from django.views.decorators.csrf import requires_csrf_token
from django.views.decorators.cache import never_cache
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


class ErrorPageView:
    """
    Base class for error page handling with common functionality
    """

    @staticmethod
    def get_error_context(error_code, error_title, error_message, suggested_actions=None):
        """
        Generate common context for error pages
        """
        if suggested_actions is None:
            suggested_actions = []

        context = {
            'error_code': error_code,
            'error_title': error_title,
            'error_message': error_message,
            'suggested_actions': suggested_actions,
            'site_name': getattr(settings, 'SITE_NAME', 'Prime Focus Book'),
            'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@primefocusug.com'),
            'home_url': '/',
            'debug': settings.DEBUG,
        }

        return context

    @staticmethod
    def log_error(request, error_code, additional_info=""):
        """
        Log error occurrences for monitoring
        """
        logger.error(
            f"Error {error_code} occurred - Path: {request.path} - "
            f"User: {getattr(request.user, 'username', 'Anonymous')} - "
            f"IP: {request.META.get('REMOTE_ADDR', 'Unknown')} - "
            f"User-Agent: {request.META.get('HTTP_USER_AGENT', 'Unknown')} - "
            f"Additional: {additional_info}"
        )


@never_cache
def error_403_view(request, exception=None):
    """
    Custom 403 Forbidden error page
    """
    ErrorPageView.log_error(request, 403)

    context = ErrorPageView.get_error_context(
        error_code="403",
        error_title="Access Forbidden",
        error_message="Sorry, you don't have permission to access this resource. This area is restricted and requires proper authorization.",
        suggested_actions=[
            {'text': '🏠 Go Home', 'url': '/', 'class': 'btn-primary'},
            {'text': '🔑 Sign In', 'url': '/accounts/login/', 'class': 'btn-secondary'},
            {'text': '← Go Back', 'url': 'javascript:history.back()', 'class': 'btn-secondary'},
        ]
    )

    response = render(request, 'errors/403.html', context)
    response.status_code = 403
    return response


@never_cache
def error_404_view(request, exception=None):
    """
    Custom 404 Not Found error page
    """
    ErrorPageView.log_error(request, 404, f"Requested URL: {request.build_absolute_uri()}")

    context = ErrorPageView.get_error_context(
        error_code="404",
        error_title="Page Not Found",
        error_message="Oops! The page you're looking for seems to have wandered off. It might have been moved, deleted, or you entered the wrong URL.",
        suggested_actions=[
            {'text': '🏠 Go Home', 'url': '/', 'class': 'btn-primary'},
            {'text': '🔍 Search', 'url': '/search/', 'class': 'btn-secondary'},
            {'text': '← Go Back', 'url': 'javascript:history.back()', 'class': 'btn-secondary'},
        ]
    )

    response = render(request, 'errors/404.html', context)
    response.status_code = 404
    return response


@requires_csrf_token
@never_cache
def error_500_view(request):
    """
    Custom 500 Internal Server Error page
    """
    ErrorPageView.log_error(request, 500, "Internal server error occurred")

    context = ErrorPageView.get_error_context(
        error_code="500",
        error_title="Internal Server Error",
        error_message="Something went wrong on our end. Our team has been notified and is working to fix this issue. Please try again later.",
        suggested_actions=[
            {'text': '🏠 Go Home', 'url': '/', 'class': 'btn-primary'},
            {'text': '🔄 Try Again', 'url': 'javascript:location.reload()', 'class': 'btn-secondary'},
            {'text': '📧 Contact Support', 'url': '/contact/', 'class': 'btn-secondary'},
        ]
    )

    response = render(request, 'errors/500.html', context)
    response.status_code = 500
    return response


@never_cache
def error_502_view(request):
    """
    Custom 502 Bad Gateway error page
    """
    ErrorPageView.log_error(request, 502, "Bad gateway error")

    context = ErrorPageView.get_error_context(
        error_code="502",
        error_title="Bad Gateway",
        error_message="We're having trouble connecting to our servers right now. This is usually temporary. Please try refreshing the page in a few moments.",
        suggested_actions=[
            {'text': '🔄 Refresh Page', 'url': 'javascript:location.reload()', 'class': 'btn-primary'},
            {'text': '🏠 Go Home', 'url': '/', 'class': 'btn-secondary'},
            {'text': '📊 Server Status', 'url': '/status/', 'class': 'btn-secondary'},
        ]
    )

    response = render(request, 'errors/502.html', context)
    response.status_code = 502
    return response


@never_cache
def error_503_view(request):
    """
    Custom 503 Service Unavailable error page
    """
    ErrorPageView.log_error(request, 503, "Service unavailable")

    context = ErrorPageView.get_error_context(
        error_code="503",
        error_title="Service Unavailable",
        error_message="We're currently performing scheduled maintenance to improve your experience. We'll be back online shortly. Thank you for your patience!",
        suggested_actions=[
            {'text': '🔄 Check Again', 'url': 'javascript:location.reload()', 'class': 'btn-primary'},
            {'text': '📅 Maintenance Schedule', 'url': '/maintenance/', 'class': 'btn-secondary'},
            {'text': '🐦 Updates', 'url': 'https://twitter.com/yoursite', 'class': 'btn-secondary'},
        ]
    )

    response = render(request, 'errors/503.html', context)
    response.status_code = 503
    return response


@never_cache
def generic_error_view(request, error_code):
    """
    Generic error view for handling custom error codes
    """
    error_configs = {
        '400': {
            'title': 'Bad Request',
            'message': 'Your request could not be understood by the server due to malformed syntax.',
            'icon': '❌',
        },
        '401': {
            'title': 'Unauthorized',
            'message': 'You need to authenticate to access this resource.',
            'icon': '🔐',
        },
        '405': {
            'title': 'Method Not Allowed',
            'message': 'The method specified in the request is not allowed for this resource.',
            'icon': '🚫',
        },
        '408': {
            'title': 'Request Timeout',
            'message': 'The server timed out waiting for the request.',
            'icon': '⏰',
        },
        '429': {
            'title': 'Too Many Requests',
            'message': 'You have sent too many requests in a given amount of time.',
            'icon': '🚦',
        },
    }

    config = error_configs.get(str(error_code), {
        'title': 'An Error Occurred',
        'message': 'An unexpected error has occurred. Please try again later.',
        'icon': '⚠️',
    })

    ErrorPageView.log_error(request, error_code, f"Generic error: {config['title']}")

    context = ErrorPageView.get_error_context(
        error_code=str(error_code),
        error_title=config['title'],
        error_message=config['message'],
        suggested_actions=[
            {'text': '🏠 Go Home', 'url': '/', 'class': 'btn-primary'},
            {'text': '← Go Back', 'url': 'javascript:history.back()', 'class': 'btn-secondary'},
        ]
    )

    context['error_icon'] = config['icon']

    response = render(request, 'errors/generic.html', context)
    response.status_code = int(error_code)
    return response


# Development/Testing views
def test_error_view(request, error_code=None):
    """
    View for testing error pages in development
    Only available when DEBUG=True
    """
    if not settings.DEBUG:
        return HttpResponseNotFound("Not available in production")

    if error_code == '403':
        return error_403_view(request)
    elif error_code == '404':
        return error_404_view(request)
    elif error_code == '500':
        return error_500_view(request)
    elif error_code == '502':
        return error_502_view(request)
    elif error_code == '503':
        return error_503_view(request)
    elif error_code:
        return generic_error_view(request, error_code)
    else:
        # Show all available error pages for testing
        context = {
            'available_errors': ['403', '404', '500', '502', '503', '400', '401', '405', '408', '429']
        }
        return render(request, 'errors/test_index.html', context)


# Middleware helper functions
def trigger_error_response(request, error_code, exception=None):
    """
    Helper function to trigger appropriate error response
    Can be used from middleware or other views
    """
    error_views = {
        403: error_403_view,
        404: error_404_view,
        500: error_500_view,
        502: error_502_view,
        503: error_503_view,
    }

    if error_code in error_views:
        return error_views[error_code](request, exception)
    else:
        return generic_error_view(request, error_code)


# Custom exception handler for API endpoints
def api_error_handler(request, error_code, message=None):
    """
    Handle errors for API endpoints - returns JSON instead of HTML
    """
    from django.http import JsonResponse

    error_messages = {
        400: 'Bad Request',
        401: 'Unauthorized',
        403: 'Forbidden',
        404: 'Not Found',
        405: 'Method Not Allowed',
        408: 'Request Timeout',
        429: 'Too Many Requests',
        500: 'Internal Server Error',
        502: 'Bad Gateway',
        503: 'Service Unavailable',
    }

    response_data = {
        'error': True,
        'error_code': error_code,
        'error_message': message or error_messages.get(error_code, 'An error occurred'),
        'timestamp': str(timezone.now()) if 'timezone' in locals() else None,
    }

    ErrorPageView.log_error(request, error_code, f"API Error: {response_data['error_message']}")

    return JsonResponse(response_data, status=error_code)