from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()

class CompanyAwareAuthBackend(ModelBackend):
    """
    Authentication backend that checks both user and company status.
    Skips company checks for PublicUser instances.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        user = super().authenticate(request, username, password, **kwargs)

        if user and user.is_active:
            # Only check company if user has it
            company = getattr(user, 'company', None)
            if company and not self._is_company_accessible(company):
                return None  # Block authentication

        return user

    def has_perm(self, user_obj, perm, obj=None):
        if not user_obj.is_active:
            return False

        company = getattr(user_obj, 'company', None)
        if company and not self._is_company_accessible(company):
            return False

        return super().has_perm(user_obj, perm, obj)

    def _is_company_accessible(self, company):
        if not company or not company.is_active:
            return False
        company.check_and_update_access_status()
        return company.has_active_access
