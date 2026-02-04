# messaging/middleware.py - FIXED VERSION
"""
Messaging middleware with schema awareness
✅ Checks schema before accessing user
✅ Skips processing in public schema
"""
import logging
from django.db import connection

logger = logging.getLogger(__name__)


class EncryptionKeyMiddleware:
    """
    Ensure all authenticated users have encryption keys
    ✅ FIXED: Checks schema before accessing user
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # ✅ CHECK SCHEMA FIRST - CRITICAL FIX!
        schema_name = getattr(connection, 'schema_name', 'public')

        # Skip if in public schema or no tenant
        if schema_name == 'public':
            return self.get_response(request)

        if not hasattr(connection, 'tenant') or connection.tenant is None:
            return self.get_response(request)

        # ✅ NOW safe to check user
        try:
            if request.user.is_authenticated:
                # Check if user has encryption keys
                from messaging.models import EncryptionKeyManager
                if not hasattr(request.user, 'encryption_keys'):
                    # Generate keys in background
                    from messaging.services import EncryptionService
                    try:
                        EncryptionService.generate_user_keys(request.user)
                    except Exception as e:
                        logger.error(f"Failed to generate encryption keys: {e}")
        except Exception as e:
            logger.error(f"Error in EncryptionKeyMiddleware: {e}")

        response = self.get_response(request)
        return response


class MessageAuditMiddleware:
    """
    Automatically log messaging actions for admin monitoring
    ✅ FIXED: Checks schema before accessing user
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # ✅ CHECK SCHEMA FIRST
        schema_name = getattr(connection, 'schema_name', 'public')

        # Skip if in public schema
        if schema_name == 'public':
            return response

        if not hasattr(connection, 'tenant') or connection.tenant is None:
            return response

        # ✅ NOW safe to check user and log
        try:
            if request.user.is_authenticated and request.path.startswith('/api/messaging/'):
                self.log_action(request, response)
        except Exception as e:
            logger.error(f"Error in MessageAuditMiddleware: {e}")

        return response

    def log_action(self, request, response):
        """Log the action"""
        try:
            from messaging.models import MessageAuditLog

            # Determine action type
            action_type = None
            metadata = {}

            if request.method == 'POST' and 'messages' in request.path:
                action_type = 'created'
                metadata = {
                    'method': 'POST',
                    'path': request.path,
                    'status': response.status_code
                }
            elif request.method == 'DELETE':
                action_type = 'deleted'
            elif request.method in ['PUT', 'PATCH']:
                action_type = 'edited'

            if action_type:
                # Get tenant info
                tenant_id = None
                tenant_name = ''

                if hasattr(request, 'tenant'):
                    tenant_id = request.tenant.pk
                    tenant_name = request.tenant.schema_name

                MessageAuditLog.objects.create(
                    action_type=action_type,
                    user=request.user,
                    metadata=metadata,
                    tenant_id=tenant_id,
                    tenant_name=tenant_name,
                    ip_address=self.get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
                )

        except Exception as e:
            logger.error(f"Error logging audit: {e}")

    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip