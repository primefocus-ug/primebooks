import uuid
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY
from referral.models import Partner


class PartnerSessionMiddleware:
    """
    Intercepts requests where the session belongs to a Partner (UUID pk)
    and resolves request.user before Django's auth middleware tries to cast
    the UUID to an integer via get_user_model() (CustomUser, integer pk).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only act if session has a backend pointing to PartnerAuthBackend
        backend = request.session.get(BACKEND_SESSION_KEY, '')
        if 'PartnerAuthBackend' in backend and SESSION_KEY in request.session:
            try:
                uid = uuid.UUID(str(request.session[SESSION_KEY]))
                partner = Partner.objects.get(pk=uid, is_active=True)
                partner.backend = backend
                request.user = partner
                request._cached_user = partner
            except (Partner.DoesNotExist, ValueError):
                # Invalid session — clear it
                request.session.flush()

        return self.get_response(request)