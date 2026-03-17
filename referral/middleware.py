"""
referral/middleware.py
======================
PartnerSessionMiddleware must be placed in MIDDLEWARE **before**:
  - django.contrib.auth.middleware.AuthenticationMiddleware
  - django_otp.middleware.OTPMiddleware
  - Any custom middleware that touches request.user

Correct MIDDLEWARE order in settings.py:
    MIDDLEWARE = [
        'django.middleware.security.SecurityMiddleware',
        'django.contrib.sessions.middleware.SessionMiddleware',   # ← sessions must be before us
        ...
        'referral.middleware.PartnerSessionMiddleware',           # ← ADD HERE, before auth
        'django.contrib.auth.middleware.AuthenticationMiddleware',
        'django_otp.middleware.OTPMiddleware',
        ...
        'accounts.middleware.YourCustomMiddleware',              # ← after us
    ]
"""

import uuid
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY
from django.contrib.auth.middleware import get_user


class PartnerSessionMiddleware:
    """
    Intercepts requests where the session belongs to a Partner (UUID pk)
    and resolves request.user BEFORE Django's AuthenticationMiddleware or
    django_otp try to cast the UUID to an integer via get_user_model().

    If the session key is a valid UUID and maps to an active Partner,
    we short-circuit the lazy user resolution entirely by setting both
    request.user and request._cached_user to the Partner instance.

    Any downstream middleware (OTP, your custom auth middleware) that
    checks request.user.is_authenticated will get the Partner object
    directly — no integer cast attempted.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        self._resolve_partner_session(request)
        return self.get_response(request)

    def _resolve_partner_session(self, request):
        # Only act when session has been populated (SessionMiddleware ran before us)
        if not hasattr(request, 'session'):
            return

        backend = request.session.get(BACKEND_SESSION_KEY, '')
        if 'PartnerAuthBackend' not in backend:
            return

        session_key = request.session.get(SESSION_KEY)
        if not session_key:
            return

        # Try to parse the session key as a UUID — if it fails, not a Partner session
        try:
            uid = uuid.UUID(str(session_key))
        except (ValueError, AttributeError):
            return

        # Import here to avoid circular imports at module load time
        from referral.models import Partner

        try:
            partner = Partner.objects.get(pk=uid, is_active=True)
        except Partner.DoesNotExist:
            # Invalid / stale session — flush it so downstream middleware
            # doesn't try to resolve it and crash
            request.session.flush()
            return

        # Attach the backend string so Django's login() / auth checks work
        partner.backend = backend

        # Set BOTH attributes so that:
        #   - SimpleLazyObject never calls get_user() (which would crash)
        #   - django_otp.middleware sees a real user object, not a lazy wrapper
        request.user = partner
        request._cached_user = partner