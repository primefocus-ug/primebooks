from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

User = get_user_model()


class CompanyAwareAuthBackend(ModelBackend):
    """
    Authentication backend that checks both user and company status
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        # First, perform standard authentication
        user = super().authenticate(request, username, password, **kwargs)

        if user and user.is_active:
            company = user.company

            # Check company status and subscription
            if not self._is_company_accessible(company):
                return None  # Block authentication

        return user

    def has_perm(self, user_obj, perm, obj=None):
        """Override permission checking to include company status"""
        if not user_obj.is_active:
            return False

        # Check company access before checking permissions
        if not self._is_company_accessible(user_obj.company):
            return False

        return super().has_perm(user_obj, perm, obj)

    def _is_company_accessible(self, company):
        """Check if company has active access"""
        if not company or not company.is_active:
            return False

        # Update company status first
        company.check_and_update_access_status()

        # Check if company has valid access
        return company.has_active_access

