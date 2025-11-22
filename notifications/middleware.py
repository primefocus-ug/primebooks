from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from urllib.parse import parse_qs
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


@database_sync_to_async
def get_user_from_token(token):
    """Get user from session or token"""
    try:
        # Try to get user from session key
        from django.contrib.sessions.models import Session
        from django.utils import timezone

        session = Session.objects.get(
            session_key=token,
            expire_date__gt=timezone.now()
        )

        uid = session.get_decoded().get('_auth_user_id')
        if uid:
            return User.objects.get(pk=uid)
    except Exception as e:
        logger.error(f'Error getting user from token: {e}')

    return AnonymousUser()


class TokenAuthMiddleware(BaseMiddleware):
    """
    Custom middleware to authenticate WebSocket connections
    """

    async def __call__(self, scope, receive, send):
        # Get the token from query string
        query_string = scope.get('query_string', b'').decode()
        params = parse_qs(query_string)
        token = params.get('token', [None])[0]

        # Get user from token
        if token:
            scope['user'] = await get_user_from_token(token)
        else:
            scope['user'] = AnonymousUser()

        return await super().__call__(scope, receive, send)


def TokenAuthMiddlewareStack(inner):
    """
    Middleware stack for WebSocket authentication
    """
    return TokenAuthMiddleware(inner)