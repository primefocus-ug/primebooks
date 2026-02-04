# primebooks/api_views.py
"""
Desktop API Views - PostgreSQL Version
Server-side API endpoints for desktop authentication and sync
✅ Updated for PostgreSQL multi-tenancy
✅ Uses custom JWT authentication with schema switching
"""
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from company.models import Company
from accounts.models import CustomUser
from django_tenants.utils import schema_context
from primebooks.authentication import TenantAwareJWTAuthentication
import logging

logger = logging.getLogger(__name__)


class DesktopLoginView(APIView):
    """
    Token-based login for desktop app
    Returns JWT token + user data + company data
    ✅ Works with PostgreSQL schemas
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        company_id = request.data.get('company_id')

        logger.info(f"🔍 Login attempt - Email: {email}, Company ID: {company_id}")
        logger.info(f"🔍 Host: {request.get_host()}")

        if not email or not password:
            return Response(
                {'detail': 'Email and password required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get company
        company = None

        # Try to get company from request.tenant (django-tenants)
        if hasattr(request, 'tenant') and request.tenant:
            if hasattr(request.tenant, 'schema_name') and request.tenant.schema_name != 'public':
                company = request.tenant
                logger.info(f"✅ Got company from request.tenant: {company.name}")

        # Try company_id from request data
        if not company and company_id:
            try:
                company = Company.objects.get(company_id=company_id)
                logger.info(f"✅ Got company from company_id: {company.name}")
            except Company.DoesNotExist:
                logger.error(f"❌ Company with ID {company_id} not found")
                return Response(
                    {'detail': f'Company with ID {company_id} not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

        # Try to extract from subdomain
        if not company:
            host = request.get_host().split(':')[0]  # Remove port
            parts = host.split('.')

            if len(parts) > 1 and parts[0] not in ['localhost', 'www']:
                subdomain = parts[0]
                logger.info(f"🔍 Extracted subdomain: {subdomain}")

                try:
                    # Try to find by slug first
                    company = Company.objects.get(slug=subdomain)
                    logger.info(f"✅ Got company from slug '{subdomain}': {company.name}")
                except Company.DoesNotExist:
                    try:
                        # Try schema_name
                        company = Company.objects.get(schema_name=subdomain)
                        logger.info(f"✅ Got company from schema_name '{subdomain}': {company.name}")
                    except Company.DoesNotExist:
                        logger.error(f"❌ No company found for subdomain: {subdomain}")
                        return Response(
                            {'detail': f'No company found for subdomain: {subdomain}'},
                            status=status.HTTP_404_NOT_FOUND
                        )

        if not company:
            logger.error("❌ No company could be determined from request")
            return Response(
                {'detail': 'Company could not be determined. Please provide company_id or use correct subdomain.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        logger.info(f"🎯 Using company: {company.name} (ID: {company.company_id})")

        # ✅ Switch to tenant schema and authenticate
        try:
            with schema_context(company.schema_name):
                logger.info(f"✅ Inside schema context: {company.schema_name}")

                # Get user in tenant schema
                try:
                    user = CustomUser.objects.get(email=email)
                    logger.info(f"✅ Found user: {user.email}")
                except CustomUser.DoesNotExist:
                    logger.error(f"❌ User {email} not found in schema {company.schema_name}")
                    return Response(
                        {'detail': 'Invalid credentials'},
                        status=status.HTTP_401_UNAUTHORIZED
                    )

                # Check password
                if not user.check_password(password):
                    logger.error(f"❌ Invalid password for {email}")
                    return Response(
                        {'detail': 'Invalid credentials'},
                        status=status.HTTP_401_UNAUTHORIZED
                    )

                if not user.is_active:
                    logger.error(f"❌ User {email} is not active")
                    return Response(
                        {'detail': 'User account is disabled'},
                        status=status.HTTP_401_UNAUTHORIZED
                    )

                # Generate JWT token WITH schema information in payload
                refresh = RefreshToken.for_user(user)

                # ✅ Add company schema to token payload (CRITICAL for TenantAwareJWTAuthentication)
                refresh['company_id'] = company.company_id
                refresh['schema_name'] = company.schema_name
                refresh['user_id'] = user.id  # Explicitly add user_id

                # Prepare user data
                user_data = {
                    'id': user.id,
                    'email': user.email,
                    'username': user.username,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                    'middle_name': getattr(user, 'middle_name', ''),
                    'phone_number': getattr(user, 'phone_number', ''),
                    'is_active': user.is_active,
                    'is_staff': user.is_staff,
                    'is_superuser': user.is_superuser,
                    'company_admin': getattr(user, 'company_admin', False),
                    'role': getattr(user, 'primary_role_id', None),
                }

            # ✅ Prepare company data OUTSIDE schema context (from public schema)
            company_data = {
                'company_id': company.company_id,
                'name': company.name,
                'trading_name': getattr(company, 'trading_name', ''),
                'email': getattr(company, 'email', ''),
                'phone': getattr(company, 'phone', ''),
                'tin': getattr(company, 'tin', ''),
                'is_trial': getattr(company, 'is_trial', False),
                'status': getattr(company, 'status', ''),
                'slug': getattr(company, 'slug', ''),
                'schema_name': getattr(company, 'schema_name', ''),
            }

            response_data = {
                'token': str(refresh.access_token),
                'refresh': str(refresh),
                'user': user_data,
                'company': company_data,
            }

            logger.info(f"✅ Desktop login successful: {email}")
            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"❌ Error during authentication: {e}", exc_info=True)
            return Response(
                {'detail': f'Authentication error: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DesktopUserSyncView(APIView):
    """
    Get user data WITH password hash for local sync
    🔒 Requires authentication
    ✅ Works with PostgreSQL schemas
    ✅ Uses TenantAwareJWTAuthentication
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, email):
        try:
            # ✅ User is already authenticated in correct schema by TenantAwareJWTAuthentication
            # Get schema from token for logging
            token = request.auth
            schema_name = token.get('schema_name') if token else None

            logger.info(f"User sync request for {email} in schema: {schema_name}")

            # Get user from current schema context (already set by authentication)
            try:
                user = CustomUser.objects.get(email=email)
            except CustomUser.DoesNotExist:
                logger.error(f"❌ User not found: {email}")
                return Response(
                    {'detail': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Verify requesting user has permission
            if request.user.email != email and not (request.user.is_staff or request.user.is_superuser):
                logger.warning(f"Permission denied: {request.user.email} tried to sync {email}")
                return Response(
                    {'detail': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Return user data INCLUDING password hash
            user_data = {
                'id': user.id,
                'email': user.email,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'middle_name': getattr(user, 'middle_name', ''),
                'phone_number': getattr(user, 'phone_number', ''),
                'password': user.password,  # 🔥 Include password hash
                'is_active': user.is_active,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
                'company_admin': getattr(user, 'company_admin', False),
                'role': getattr(user, 'primary_role_id', None),
            }

            logger.info(f"✅ User sync successful: {email}")
            return Response(user_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"❌ Error syncing user: {e}", exc_info=True)
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class DesktopCompanyDetailsView(APIView):
    """
    Get company details for desktop sync
    🔒 Requires authentication
    ✅ Works with PostgreSQL - no schema context needed
    ✅ Uses TenantAwareJWTAuthentication
    """
    authentication_classes = [TenantAwareJWTAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            # ✅ Get company info from JWT token payload
            token = request.auth
            if not token:
                return Response(
                    {'detail': 'Authentication required'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

            company_id = token.get('company_id')
            schema_name = token.get('schema_name')

            if not company_id or not schema_name:
                logger.error("❌ No company info in token")
                return Response(
                    {'detail': 'Invalid token - missing company information'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            logger.info(f"Fetching company details for: {company_id} ({schema_name})")

            # ✅ Get company from public schema (Company model is in SHARED_APPS)
            # No schema context needed - queries public schema by default
            try:
                company = Company.objects.get(company_id=company_id)
            except Company.DoesNotExist:
                logger.error(f"❌ Company not found: {company_id}")
                return Response(
                    {'detail': 'Company not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Prepare company data
            company_data = {
                'company_id': company.company_id,
                'name': company.name,
                'trading_name': getattr(company, 'trading_name', ''),
                'email': getattr(company, 'email', ''),
                'phone': getattr(company, 'phone', ''),
                'physical_address': getattr(company, 'physical_address', ''),
                'tin': getattr(company, 'tin', ''),
                'nin': getattr(company, 'nin', ''),
                'slug': getattr(company, 'slug', ''),
                'is_trial': getattr(company, 'is_trial', False),
                'status': getattr(company, 'status', ''),
                'schema_name': getattr(company, 'schema_name', ''),
            }

            logger.info(f"✅ Company details sent: {company.name}")
            return Response(company_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"❌ Error getting company details: {e}", exc_info=True)
            return Response(
                {'detail': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )