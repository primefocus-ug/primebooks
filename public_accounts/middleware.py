from django.db import connection
from django.http import HttpResponseForbidden


class PublicSchemaAuthMiddleware:
    """
    Middleware to ensure public admin routes run in public schema
    and prevent tenant users from accessing public admin
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check if this is a public admin route
        if request.path.startswith('/public-admin/'):
            # Ensure we're in public schema
            if hasattr(connection, 'schema_name') and connection.schema_name != 'public':
                return HttpResponseForbidden(
                    "Public admin is only accessible from the main domain."
                )

            # If user is authenticated, ensure they're a PublicUser
            if request.user.is_authenticated:
                from .models import PublicUser
                if not isinstance(request.user, PublicUser):
                    # This is a tenant user trying to access public admin
                    from django.contrib.auth import logout
                    logout(request)
                    from django.shortcuts import redirect
                    from django.contrib import messages
                    messages.error(request, 'Please use your public admin credentials.')
                    return redirect('public_admin:public_admin_login')

        response = self.get_response(request)
        return response