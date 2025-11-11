class EncryptionKeyMiddleware:
    """
    Ensure all authenticated users have encryption keys
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            # Check if user has encryption keys
            from messaging.models import EncryptionKeyManager
            if not hasattr(request.user, 'encryption_keys'):
                # Generate keys in background
                from messaging.services import EncryptionService
                try:
                    EncryptionService.generate_user_keys(request.user)
                except Exception as e:
                    # Log error but don't break the request
                    import logging
                    logger = logging.getLogger(__name__)
                    logger.error(f"Failed to generate encryption keys for user {request.user.id}: {e}")

        response = self.get_response(request)
        return response

from .models import MessageAuditLog


class MessageAuditMiddleware:
    """
    Automatically log messaging actions for admin monitoring
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Log messaging-related actions
        if request.user.is_authenticated and request.path.startswith('/api/messaging/'):
            self.log_action(request, response)

        return response

    def log_action(self, request, response):
        """Log the action"""
        try:
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
                # Get tenant info if available
                tenant_id = None
                tenant_name = ''

                if hasattr(request, 'tenant'):
                    tenant_id = request.tenant.id
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
            # Don't break the request if logging fails
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error logging audit: {e}")

    def get_client_ip(self, request):
        """Get client IP address"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip

