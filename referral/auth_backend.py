import uuid
from django.contrib.auth.backends import ModelBackend
from .models import Partner


class PartnerAuthBackend(ModelBackend):

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = username or kwargs.get('email')
        if not email:
            return None
        try:
            partner = Partner.objects.get(email=email)
        except Partner.DoesNotExist:
            return None
        if partner.check_password(password) and self.user_can_authenticate(partner):
            return partner
        return None

    def get_user(self, user_id):
        try:
            uid = uuid.UUID(str(user_id))  # reject non-UUID values silently
            return Partner.objects.get(pk=uid)
        except (Partner.DoesNotExist, ValueError, AttributeError):
            return None