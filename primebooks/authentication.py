# primebooks/authentication.py
"""
Custom JWT Authentication for Desktop App with Multi-tenancy
✅ Handles schema switching during authentication
"""
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken
from django_tenants.utils import schema_context
from accounts.models import CustomUser
import logging

logger = logging.getLogger(__name__)


class TenantAwareJWTAuthentication(JWTAuthentication):
    """
    Custom JWT Authentication that handles tenant schema switching

    This authentication class:
    1. Validates the JWT token
    2. Extracts schema_name from token payload
    3. Switches to correct tenant schema
    4. Fetches user from tenant schema
    """

    def get_user(self, validated_token):
        """
        Override get_user to switch to correct tenant schema before fetching user
        """
        try:
            # Get user_id from token
            user_id = validated_token.get('user_id')
            if not user_id:
                raise InvalidToken('Token contained no recognizable user identification')

            # ✅ Get schema_name from token payload
            schema_name = validated_token.get('schema_name')

            if not schema_name:
                # If no schema in token, this might be a public schema user (SaaS admin)
                logger.warning(f"No schema_name in token for user_id: {user_id}")
                # Try to get user from current schema (public)
                try:
                    user = self.user_model.objects.get(**{'id': user_id})
                    return user
                except self.user_model.DoesNotExist:
                    raise InvalidToken('User not found')

            # ✅ Switch to tenant schema and fetch user
            logger.info(f"Authenticating user {user_id} in schema: {schema_name}")

            with schema_context(schema_name):
                try:
                    user = self.user_model.objects.get(**{'id': user_id})

                    if not user.is_active:
                        raise InvalidToken('User is inactive')

                    logger.info(f"✅ Authenticated user: {user.email} in schema: {schema_name}")
                    return user

                except self.user_model.DoesNotExist:
                    logger.error(f"❌ User {user_id} not found in schema: {schema_name}")
                    raise InvalidToken('User not found in tenant schema')

        except Exception as e:
            logger.error(f"❌ Error during JWT authentication: {e}", exc_info=True)
            raise InvalidToken(f'Authentication error: {str(e)}')


class PublicSchemaJWTAuthentication(JWTAuthentication):
    """
    JWT Authentication for public schema (SaaS admin users)
    Does NOT switch schemas - stays in public schema
    """

    def get_user(self, validated_token):
        """
        Get user from public schema only
        """
        try:
            user_id = validated_token.get('user_id')
            if not user_id:
                raise InvalidToken('Token contained no recognizable user identification')

            logger.info(f"Authenticating public schema user: {user_id}")

            try:
                # Import here to avoid circular imports
                from public_accounts.models import PublicUser
                user = PublicUser.objects.get(**{'id': user_id})

                if not user.is_active:
                    raise InvalidToken('User is inactive')

                logger.info(f"✅ Authenticated public user: {user.email}")
                return user

            except PublicUser.DoesNotExist:
                logger.error(f"❌ Public user {user_id} not found")
                raise InvalidToken('User not found')

        except Exception as e:
            logger.error(f"❌ Error during public schema JWT authentication: {e}", exc_info=True)
            raise InvalidToken(f'Authentication error: {str(e)}')