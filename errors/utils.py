import logging
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


class ErrorNotificationService:
    """Service for handling error notifications"""

    @staticmethod
    def notify_admins(error_code, request, exception=None):
        """Send error notifications to administrators"""
        if not settings.DEBUG:
            subject = f'Error {error_code} on {settings.SITE_NAME}'
            message = f"""
            Error Details:
            - Code: {error_code}
            - Path: {request.path}
            - Method: {request.method}
            - User: {getattr(request.user, 'username', 'Anonymous')}
            - IP: {request.META.get('REMOTE_ADDR', 'Unknown')}
            - User-Agent: {request.META.get('HTTP_USER_AGENT', 'Unknown')}
            - Exception: {str(exception) if exception else 'N/A'}
            """

            try:
                send_mail(
                    subject=subject,
                    message=message,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[settings.SUPPORT_EMAIL],
                    fail_silently=True,
                )
            except Exception as e:
                logger.error(f"Failed to send error notification: {e}")