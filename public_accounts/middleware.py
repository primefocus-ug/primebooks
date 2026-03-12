from django.db import connection
from django.http import HttpResponseForbidden


class PublicSchemaAuthMiddleware:
    """
    Middleware to ensure public admin routes run in public schema
    and prevent tenant users from accessing public admin.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path.startswith('/public-admin/'):

            # Must be in public schema — if not, hard stop
            if hasattr(connection, 'schema_name') and connection.schema_name != 'public':
                return HttpResponseForbidden(
                    "Public admin is only accessible from the main domain."
                )

            # If authenticated, must be a PublicUser — Partners and tenant
            # users are not allowed here
            if request.user.is_authenticated:
                from .models import PublicUser
                if not isinstance(request.user, PublicUser):
                    from django.contrib.auth import logout
                    from django.shortcuts import redirect
                    from django.contrib import messages
                    logout(request)
                    messages.error(request, 'Please use your public admin credentials.')
                    # Use a hardcoded path — reverse() is unsafe here because
                    # this middleware may run in a tenant URL context where the
                    # public_admin namespace is not registered, causing NoReverseMatch
                    return redirect('/public-admin/login/')

        return self.get_response(request)