from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class EFRISWebSocketAuthMiddleware(BaseMiddleware):
    """Authentication middleware for EFRIS WebSocket connections"""

    def __init__(self, inner):
        self.inner = inner

    async def __call__(self, scope, receive, send):
        try:
            # Get user from session or token
            user = await self.get_user_from_scope(scope)
            scope['user'] = user

        except Exception as e:
            logger.error(f"EFRIS WebSocket auth error: {e}")
            scope['user'] = AnonymousUser()

        return await self.inner(scope, receive, send)

    @database_sync_to_async
    def get_user_from_scope(self, scope):
        """Get user from WebSocket scope"""
        try:
            # Try to get user from session first
            session = scope.get('session')
            if session and '_auth_user_id' in session:
                user_id = session['_auth_user_id']
                return User.objects.get(pk=user_id, is_active=True)

            # Try to get from query parameters (for token auth)
            query_string = scope.get('query_string', b'').decode('utf-8')
            if 'token=' in query_string:
                # Implement token-based auth if needed
                # token = parse_qs(query_string).get('token', [None])[0]
                # return self.authenticate_token(token)
                pass

            return AnonymousUser()

        except (User.DoesNotExist, ValueError, KeyError):
            return AnonymousUser()

