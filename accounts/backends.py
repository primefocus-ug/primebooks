from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db import connection

User = get_user_model()


class RoleBasedAuthBackend(ModelBackend):
    """
    Custom authentication backend that respects role hierarchy.
    Only operates in tenant schemas, not in public schema.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """
        Standard authentication - only works in tenant schemas.
        Public schema uses PublicIdentifierBackend instead.
        Accepts either an email address or a username as the identifier.
        """
        # Skip authentication if we're in public schema
        if connection.schema_name == 'public':
            return None

        # Support callers that pass email= directly
        identifier = username or kwargs.get('email') or kwargs.get(User.USERNAME_FIELD)
        if identifier is None:
            return None

        # Try email first (primary USERNAME_FIELD), then fall back to username
        user = None
        try:
            user = User.objects.get(email=identifier)
        except User.DoesNotExist:
            try:
                user = User.objects.get(username=identifier)
            except User.DoesNotExist:
                return None
        except Exception:
            # Catch unexpected DB errors (e.g. missing table in wrong schema)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user

        return None

    def has_perm(self, user_obj, perm, obj=None):
        """
        Check permissions through assigned roles.
        Only applies to tenant users.
        """
        # Skip if in public schema or if user is not from tenant schema
        if connection.schema_name == 'public':
            return False

        if not user_obj.is_active:
            return False

        # SaaS admin has all permissions
        if hasattr(user_obj, 'is_saas_admin') and user_obj.is_saas_admin:
            return True

        # Check through groups/roles
        return super().has_perm(user_obj, perm, obj)

    def has_module_perms(self, user_obj, app_label):
        """
        Control admin access - only SaaS admins.
        Only applies to tenant users.
        """
        # Skip if in public schema
        if connection.schema_name == 'public':
            return False

        if not user_obj.is_active:
            return False

        # Only SaaS admins can access Django admin
        if app_label == 'admin':
            return hasattr(user_obj, 'is_saas_admin') and user_obj.is_saas_admin

        return (hasattr(user_obj, 'is_saas_admin') and user_obj.is_saas_admin) or super().has_module_perms(user_obj,
                                                                                                           app_label)

    def get_user(self, user_id):
        """
        Get user by ID - only in tenant schemas.

        Also acts as a last-resort guard against cross-schema session bleed:
        if a PublicUser UUID somehow reaches this point (StalePublicSession
        middleware should have scrubbed it earlier), the PK coercion below will
        raise before we touch the database, and we return None cleanly.
        """
        # Skip if in public schema — PublicIdentifierBackend handles that
        if connection.schema_name == 'public':
            return None

        # Guard: coerce PK type early so we never hit the DB with a UUID
        # when CustomUser expects an integer.  This mirrors what Django's
        # _get_user_session_key does, but here we catch the exception ourselves.
        try:
            User._meta.pk.to_python(user_id)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "RoleBasedAuthBackend.get_user(%r): PK type mismatch on schema "
                "'%s' — stale public-schema session reached the backend. "
                "Returning None (anonymous).",
                user_id,
                connection.schema_name,
            )
            return None

        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(
                "Unexpected error in get_user(%r): %s", user_id, e
            )
            return None