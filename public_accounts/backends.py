from django.contrib.auth.backends import BaseBackend
from .models import PublicUser


class PublicIdentifierBackend(BaseBackend):
    """
    Custom authentication backend that authenticates using identifier + password
    """

    def authenticate(self, request, identifier=None, password=None, **kwargs):
        if identifier is None or password is None:
            return None

        try:
            user = PublicUser.objects.get(identifier=identifier, is_active=True)
        except PublicUser.DoesNotExist:
            return None

        # Check if account is locked
        if user.is_locked:
            return None

        # Verify password
        if user.check_password(password):
            # Record successful login
            ip_address = self.get_client_ip(request) if request else None
            user.record_login_attempt(success=True, ip_address=ip_address)
            return user
        else:
            # Record failed attempt
            user.record_login_attempt(success=False)
            return None

    def get_user(self, user_id):
        try:
            return PublicUser.objects.get(pk=user_id)
        except PublicUser.DoesNotExist:
            return None

    @staticmethod
    def get_client_ip(request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip