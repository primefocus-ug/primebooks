
from django.utils.deprecation import MiddlewareMixin
from django.db import connection


class TenantAwareMiddleware(MiddlewareMixin):
    """
    Simple middleware to add tenant info to request
    """
    
    def process_request(self, request):
        # Add tenant info to request for easy access
        request.tenant = getattr(connection, 'tenant', None)
        request.schema_name = getattr(connection, 'schema_name', 'public')
        request.is_public_schema = request.schema_name == 'public'
        
        return None
    

# from django.http import HttpResponseForbidden

# class RestrictTenantLoginMiddleware:
#     def __init__(self, get_response):
#         self.get_response = get_response

#     def __call__(self, request):
#         # Ensure user is authenticated
#         if request.user.is_authenticated:
#             # Current tenant (from django-tenants)
#             current_tenant = request.tenant

#             # User’s assigned company (adjust if your model differs)
#             user_company = getattr(request.user, "company", None)

#             # If mismatch, forbid
#             if user_company and user_company.id != current_tenant.id:
#                 return HttpResponseForbidden("Access denied for this tenant.")

#         return self.get_response(request)