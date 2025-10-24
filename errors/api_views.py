from rest_framework.views import exception_handler
from django.utils import timezone


def custom_exception_handler(exc, context):
    """Custom API exception handler"""
    response = exception_handler(exc, context)

    if response is not None:
        custom_response_data = {
            'error': True,
            'error_code': response.status_code,
            'error_message': 'An error occurred',
            'details': response.data,
            'timestamp': timezone.now().isoformat(),
        }

        # Map status codes to user-friendly messages
        status_messages = {
            400: 'Bad request. Please check your input.',
            401: 'Authentication required.',
            403: 'You do not have permission to access this resource.',
            404: 'The requested resource was not found.',
            405: 'Method not allowed.',
            429: 'Too many requests. Please slow down.',
            500: 'Internal server error. Please try again later.',
            502: 'Service temporarily unavailable.',
            503: 'Service under maintenance.',
        }

        custom_response_data['error_message'] = status_messages.get(
            response.status_code,
            custom_response_data['error_message']
        )

        response.data = custom_response_data

    return response