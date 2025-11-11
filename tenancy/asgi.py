import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# Set Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'tenancy.settings')

# Initialize Django ASGI app first
django_asgi_app = get_asgi_application()

# Import after Django initialization
from . import routing
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from channels.sessions import SessionMiddlewareStack, CookieMiddleware


# Custom Tenant-Aware Auth Middleware
class TenantAuthMiddleware:
    """
    Sets tenant schema BEFORE attempting authentication
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        from django.db import connection

        # Get hostname from headers
        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("utf-8").split(":")[0]

        # Get and set tenant
        tenant = await self.get_tenant(host)

        if tenant:
            # Set the schema BEFORE any database queries
            await database_sync_to_async(connection.set_schema)(tenant.schema_name)
            scope["tenant"] = tenant

            # Now get the user with the correct schema set
            scope["user"] = await self.get_user(scope)
        else:
            scope["user"] = AnonymousUser()
            print(f"WARNING: No tenant found for host: {host}")

        return await self.app(scope, receive, send)

    @database_sync_to_async
    def get_tenant(self, hostname):
        """Get tenant from hostname"""
        try:
            from django_tenants.utils import get_tenant_model, get_tenant_domain_model
            DomainModel = get_tenant_domain_model()
            domain = DomainModel.objects.select_related('tenant').get(domain=hostname)
            return domain.tenant
        except Exception as e:
            print(f"DEBUG: Tenant lookup failed for {hostname}: {e}")
            # Try to return the first tenant as fallback (for development)
            TenantModel = get_tenant_model()
            try:
                fallback = TenantModel.objects.exclude(schema_name='public').first()
                if fallback:
                    print(f"DEBUG: Using fallback tenant: {fallback.schema_name}")
                return fallback
            except Exception as fallback_err:
                print(f"DEBUG: Fallback tenant lookup failed: {fallback_err}")
                return None

    @database_sync_to_async
    def get_user(self, scope):
        """Get user from session with tenant schema already set"""
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import AnonymousUser
        from django_tenants.utils import schema_context

        # Get tenant from scope
        tenant = scope.get("tenant")
        if not tenant:
            print("DEBUG: No tenant in scope")
            return AnonymousUser()

        # Get session - should be populated by SessionMiddlewareStack
        session = scope.get("session")

        if not session:
            return AnonymousUser()


        # Get user ID from session
        user_id = session.get("_auth_user_id")
        backend = session.get("_auth_user_backend")


        if user_id and backend:
            User = get_user_model()
            try:
                # CRITICAL: Use schema_context to ensure correct schema
                with schema_context(tenant.schema_name):
                    user = User.objects.get(pk=user_id)
                    return user
            except User.DoesNotExist:
                print(f"DEBUG: User {user_id} not found in schema {tenant.schema_name}")
            except Exception as e:
                print(f"DEBUG: Error getting user: {e}")

        print("DEBUG: Returning AnonymousUser")
        return AnonymousUser()


# HTTP + WebSocket ASGI application
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        CookieMiddleware(  # Cookie middleware first
            SessionMiddlewareStack(  # Then session middleware
                TenantAuthMiddleware(  # Then tenant middleware
                    URLRouter(routing.websocket_urlpatterns)
                )
            )
        )
    ),
})