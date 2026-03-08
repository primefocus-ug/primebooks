# company/authentication.py
"""
Schema-aware authentication backend
✅ Handles public schema correctly
✅ Skips company checks in public schema
✅ Works with django-tenants
"""
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db import connection
import logging

logger = logging.getLogger(__name__)

User = get_user_model()


class CompanyAwareAuthBackend(ModelBackend):
    """
    Authentication backend that checks both user and company status.
    ✅ Schema-aware - works in both public and tenant schemas
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Authenticate user with schema awareness
        """
        # Check current schema
        schema_name = getattr(connection, 'schema_name', 'public')

        # If we're in public schema, DON'T try to authenticate tenant users
        if schema_name == 'public':
            logger.debug("Authentication attempt in public schema - skipping")
            # Let the default backend handle public users
            return None

        # Now safe to call parent authenticate (we're in tenant schema)
        try:
            user = super().authenticate(request, username, password, **kwargs)
        except Exception as e:
            logger.error(f"Authentication error in schema {schema_name}: {e}")
            return None

        # If user authenticated, check company status
        if user and user.is_active:
            # Only check company if user has it
            company = getattr(user, 'company', None)
            if company and not self._is_company_accessible(company):
                logger.warning(f"User {username} blocked - company not accessible")
                return None  # Block authentication

        return user

    def has_perm(self, user_obj, perm, obj=None):
        """Check permissions with company awareness"""
        if not user_obj.is_active:
            return False

        # Check schema
        schema_name = getattr(connection, 'schema_name', 'public')
        if schema_name == 'public':
            # In public schema, use default permission check
            return super().has_perm(user_obj, perm, obj)

        # In tenant schema, check company
        company = getattr(user_obj, 'company', None)
        if company and not self._is_company_accessible(company):
            return False

        return super().has_perm(user_obj, perm, obj)

    def _is_company_accessible(self, company):
        """Check if company is accessible (read-only — does not mutate the DB)."""
        try:
            if not company or not company.is_active:
                return False
            # Use has_active_access which checks status in-memory without writing.
            # Status is kept up-to-date by the periodic Celery task and middleware.
            return company.has_active_access
        except Exception as e:
            logger.error(f"Error checking company accessibility: {e}")
            return False