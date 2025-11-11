
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
