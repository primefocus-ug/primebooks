# company/authentication.py
"""
Schema-aware authentication backend
✅ Handles public schema correctly
✅ Skips company checks in public schema
✅ Works with django-tenants
✅ FIXED: Always returns a CustomUser instance, never a base User proxy
"""
from django.contrib.auth.backends import ModelBackend
from django.db import connection
import logging

logger = logging.getLogger(__name__)


def _get_custom_user_model():
    """
    Import CustomUser directly instead of using get_user_model().

    get_user_model() can return a different class depending on import order
    and which app is active at the time — causing isinstance() mismatches
    that make TOTPDevice.objects.filter(user=...) raise a ValueError.

    Direct import always gives us the concrete CustomUser class.
    """
    from accounts.models import CustomUser
    return CustomUser


class CompanyAwareAuthBackend(ModelBackend):
    """
    Authentication backend that checks both user and company status.
    ✅ Schema-aware - works in both public and tenant schemas
    ✅ Always returns a concrete CustomUser instance (never a proxy/base model)
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user with schema awareness.
        Returns a CustomUser instance or None.
        """
        # Check current schema
        schema_name = getattr(connection, 'schema_name', 'public')

        # If we're in public schema, don't try to authenticate tenant users.
        # Let the default backend handle public users.
        if schema_name == 'public':
            logger.debug("Authentication attempt in public schema - skipping CompanyAwareAuthBackend")
            return None

        # Now safe to authenticate (we're in a tenant schema)
        try:
            user = super().authenticate(request, username, password, **kwargs)
        except Exception as e:
            logger.error(f"Authentication error in schema {schema_name}: {e}")
            return None

        if user is None:
            return None

        # ── CRITICAL FIX ──────────────────────────────────────────────────────
        # super().authenticate() calls get_user_model() internally, which may
        # resolve to a different class than accounts.CustomUser depending on
        # import timing. This causes:
        #   ValueError: Cannot query "...": Must be "CustomUser" instance.
        # when the returned user is passed to TOTPDevice.objects.filter(user=user).
        #
        # Solution: always re-fetch as a concrete CustomUser so isinstance()
        # checks and FK queries work correctly everywhere downstream.
        CustomUser = _get_custom_user_model()
        if not isinstance(user, CustomUser):
            try:
                backend_attr = getattr(user, 'backend', None)
                user = CustomUser.objects.get(pk=user.pk)
                # Re-attach the backend string Django needs for login()
                if backend_attr:
                    user.backend = backend_attr
                logger.debug(
                    f"Re-fetched user {user.email} as CustomUser instance "
                    f"(was {type(user).__name__})"
                )
            except CustomUser.DoesNotExist:
                logger.error(
                    f"Could not re-fetch user pk={user.pk} as CustomUser — "
                    f"authentication rejected"
                )
                return None
        # ──────────────────────────────────────────────────────────────────────

        # Check company status only for active users
        if user.is_active:
            company = getattr(user, 'company', None)
            if company and not self._is_company_accessible(company):
                logger.warning(
                    f"User {username} blocked — company '{company}' not accessible"
                )
                return None

        return user

    def has_perm(self, user_obj, perm, obj=None):
        """Check permissions with company awareness."""
        if not user_obj.is_active:
            return False

        schema_name = getattr(connection, 'schema_name', 'public')
        if schema_name == 'public':
            return super().has_perm(user_obj, perm, obj)

        company = getattr(user_obj, 'company', None)
        if company and not self._is_company_accessible(company):
            return False

        return super().has_perm(user_obj, perm, obj)

    def _is_company_accessible(self, company):
        """
        Check if company is accessible (read-only — does not mutate the DB).
        Status is kept up-to-date by the periodic Celery task and middleware.
        """
        try:
            if not company or not company.is_active:
                return False
            return company.has_active_access
        except Exception as e:
            logger.error(f"Error checking company accessibility: {e}")
            return False