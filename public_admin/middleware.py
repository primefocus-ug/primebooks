from django.utils.deprecation import MiddlewareMixin
from django.shortcuts import redirect
from django.urls import reverse, NoReverseMatch
from .models import PublicStaffUser


class PublicStaffAuthMiddleware(MiddlewareMixin):
    """
    Middleware to handle authentication for public staff users
    """

    def get_login_url(self):
        """Get login URL safely"""
        try:
            return reverse('public_admin:login')
        except NoReverseMatch:
            # Fallback to hardcoded path if reverse fails
            return '/auth/login/'

    def process_request(self, request):
        # Only process if we're in public schema
        from django.db import connection
        if connection.schema_name != 'public':
            return None

        # Check if accessing analytics
        if not request.path.startswith('/analytics/'):
            return None

        # Get login URL
        login_url = self.get_login_url()

        # Skip login page
        if request.path == login_url or request.path.startswith('/auth/'):
            return None

        # Check for session token
        token = request.session.get('staff_token')

        if token:
            try:
                user = PublicStaffUser.objects.get(
                    session_token=token,
                    is_active=True
                )

                if user.is_token_valid():
                    request.public_staff_user = user
                    return None
                else:
                    # Token expired
                    request.session.flush()
            except PublicStaffUser.DoesNotExist:
                request.session.flush()

        # Redirect to login
        return redirect(f'{login_url}?next={request.path}')