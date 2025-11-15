from django.shortcuts import redirect
from django.http import HttpResponsePermanentRedirect, HttpResponseRedirect
from .models import Redirect


class SEORedirectMiddleware:
    """
    Handle SEO redirects (301/302).
    Add to MIDDLEWARE in settings.py
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only process public schema requests
        from django.db import connection
        if connection.schema_name != 'public':
            return self.get_response(request)

        # Check for redirect
        path = request.path

        try:
            redirect_obj = Redirect.objects.get(old_path=path, is_active=True)
            redirect_obj.record_hit()

            if redirect_obj.redirect_type == 301:
                return HttpResponsePermanentRedirect(redirect_obj.new_path)
            else:
                return HttpResponseRedirect(redirect_obj.new_path)
        except Redirect.DoesNotExist:
            pass

        response = self.get_response(request)
        return response