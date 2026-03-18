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
from channels.sessions import SessionMiddlewareStack

import logging
logger = logging.getLogger(__name__)


class TenantAuthMiddleware:
    """
    Resolves the tenant from the request hostname, sets the correct PostgreSQL
    schema, then authenticates the user from the already-populated session.

    Stack position: must sit INSIDE SessionMiddlewareStack so that
    scope["session"] is already resolved when __call__ runs.

    Key design decisions:
      - ONE @database_sync_to_async call does BOTH tenant lookup AND user fetch,
        so schema_context() and User.objects.get() share the same DB thread.
        Using two separate async DB calls (set_schema then get_user) breaks
        because each call gets a different thread-pool thread with its own
        connection, so the schema set in call #1 is invisible to call #2.
      - If the domain lookup matches the public tenant (e.g. localhost /
        127.0.0.1 registered there), we skip it and fall through to the
        dev fallback so we never try to load accounts_customuser from public.
      - scope["tenant_schema"] is set so consumers can read it via
        _get_schema_from_scope(scope).
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("websocket", "http"):
            return await self.app(scope, receive, send)

        headers = dict(scope.get("headers", []))
        host = headers.get(b"host", b"").decode("utf-8").split(":")[0]

        tenant, user = await self._resolve_tenant_and_user(host, scope)

        scope["tenant"] = tenant
        scope["user"] = user
        scope["tenant_schema"] = tenant.schema_name if tenant else "public"

        return await self.app(scope, receive, send)

    @database_sync_to_async
    def _resolve_tenant_and_user(self, hostname, scope):
        """
        Single synchronous function that:
          1. Looks up the tenant for the given hostname.
          2. Reads user_id from scope["session"].
          3. Loads the User inside schema_context() so the schema switch and
             the User.objects.get() happen in the same thread/connection.

        Returns (tenant | None, User | AnonymousUser).
        """
        from django_tenants.utils import (
            get_tenant_model, get_tenant_domain_model, schema_context,
        )
        from django.contrib.auth import get_user_model

        # ── 1. Tenant lookup ──────────────────────────────────────────────────
        tenant = None
        logger.debug("WS resolving tenant for hostname: %r", hostname)
        try:
            DomainModel = get_tenant_domain_model()
            domain = DomainModel.objects.select_related('tenant').get(domain=hostname)
            candidate = domain.tenant
            # Never use the public schema tenant — it has no accounts_customuser
            # table. If the domain matched public (e.g. localhost/127.0.0.1
            # registered there), fall through to the dev fallback below.
            if candidate.schema_name != 'public':
                tenant = candidate
                logger.debug("WS tenant resolved via domain: %s", tenant.schema_name)
            else:
                logger.debug(
                    "WS domain %r matched public tenant — ignoring, trying fallback",
                    hostname,
                )
        except Exception as exc:
            logger.debug("WS tenant lookup failed for %r: %s", hostname, exc)

        # Fallback for local development: hostname is localhost/127.x/IP,
        # or the domain matched the public tenant above.
        if not tenant:
            try:
                TenantModel = get_tenant_model()
                tenant = TenantModel.objects.exclude(schema_name='public').first()
                if tenant:
                    logger.debug("WS using fallback tenant: %s", tenant.schema_name)
            except Exception as fb_exc:
                logger.debug("WS fallback tenant lookup failed: %s", fb_exc)

        if not tenant:
            logger.warning("No tenant resolved for host %r — returning AnonymousUser", hostname)
            return None, AnonymousUser()

        # ── 2. Session → user_id ──────────────────────────────────────────────
        session = scope.get("session")
        if not session:
            logger.debug("WS scope has no session for host %r", hostname)
            return tenant, AnonymousUser()

        user_id = session.get("_auth_user_id")
        if not user_id:
            return tenant, AnonymousUser()

        # ── 3. Load user inside tenant schema ─────────────────────────────────
        User = get_user_model()
        try:
            with schema_context(tenant.schema_name):
                user = User.objects.get(pk=user_id)
                logger.debug(
                    "WS authenticated user=%s schema=%s",
                    user, tenant.schema_name,
                )
                return tenant, user
        except User.DoesNotExist:
            logger.debug(
                "WS user_id=%s not found in schema %s", user_id, tenant.schema_name
            )
        except Exception as exc:
            logger.exception("WS user resolution error: %s", exc)

        return tenant, AnonymousUser()


# HTTP + WebSocket ASGI application
#
# Middleware execution order (outermost → innermost):
#   AllowedHostsOriginValidator       — blocks bad Origin headers
#     SessionMiddlewareStack          — CookieMiddleware + SessionMiddleware
#       (populates scope["cookies"] and scope["session"])
#         TenantAuthMiddleware        — resolves tenant + user using the
#           (populates scope["tenant"],  already-populated session
#            scope["tenant_schema"],
#            scope["user"])
#               URLRouter             — dispatches to consumer
#
# NOTE: SessionMiddlewareStack already wraps CookieMiddleware internally —
# no separate CookieMiddleware wrapper needed.
application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(
        SessionMiddlewareStack(
            TenantAuthMiddleware(
                URLRouter(routing.websocket_urlpatterns)
            )
        )
    ),
})