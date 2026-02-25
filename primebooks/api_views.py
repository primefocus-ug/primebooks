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
from rest_framework.decorators import api_view, permission_classes
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from django.contrib.auth import login, get_user_model
from django.http import JsonResponse, HttpResponseBadRequest
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from company.models import Company
from accounts.models import CustomUser
from django_tenants.utils import schema_context
from primebooks.authentication import TenantAwareJWTAuthentication
from .models import AppVersions
import logging

logger = logging.getLogger(__name__)

User = get_user_model()

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def subscription_status(request):
    """
    Return subscription status for desktop app
    ✅ Validates subscription in real-time
    ✅ Returns detailed status for caching

    Usage: GET /api/desktop/subscription/status/?company_id=<id>
    """
    company_id = request.GET.get('company_id')

    if not company_id:
        return Response({'error': 'company_id required'}, status=400)

    try:
        company = Company.objects.get(company_id=company_id)

        # Calculate days until expiry
        today = timezone.now().date()

        if company.is_trial:
            if company.trial_ends_at:
                days_remaining = (company.trial_ends_at - today).days
            else:
                days_remaining = 999
        else:
            if company.subscription_ends_at:
                days_remaining = (company.subscription_ends_at - today).days
            else:
                days_remaining = 999

        return Response({
            'company_id': company.company_id,
            'is_active': company.has_active_access,
            'status': company.status,  # ACTIVE, TRIAL, EXPIRED, SUSPENDED
            'is_trial': company.is_trial,
            'plan': {
                'name': company.plan.name if company.plan else 'FREE',
                'max_users': company.plan.max_users if company.plan else 5,
                'max_branches': company.plan.max_branches if company.plan else 1,
            },
            'trial_ends_at': company.trial_ends_at.isoformat() if company.trial_ends_at else None,
            'subscription_ends_at': company.subscription_ends_at.isoformat() if company.subscription_ends_at else None,
            'grace_period_ends_at': company.grace_period_ends_at.isoformat() if company.grace_period_ends_at else None,
            'days_remaining': days_remaining,
        })

    except Company.DoesNotExist:
        return Response({'error': 'Company not found'}, status=404)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_updates(request):
    current_version = request.GET.get('current_version', '0.0.0')

    # Get latest active version
    latest_version = AppVersions.objects.filter(is_active=True).first()

    if not latest_version:
        return Response({'update_available': False})

    def parse_version(v):
        try:
            return tuple(int(x) for x in v.split('.') if x.isdigit())
        except (ValueError, AttributeError):
            return (0, 0, 0)

    current = parse_version(current_version)
    if not current:
        return Response(
            {'error': 'Invalid current_version format. Expected x.y.z'},
            status=400
        )

    latest = latest_version.version_tuple

    if latest > current:
        # Determine download URL based on platform from User-Agent
        user_agent = request.META.get('HTTP_USER_AGENT', '').lower()

        if 'windows' in user_agent:
            download_url = latest_version.windows_url
        elif 'mac' in user_agent or 'darwin' in user_agent:
            download_url = latest_version.mac_url
        else:
            download_url = latest_version.linux_url

        return Response({
            'update_available': True,
            'latest_version': latest_version.version,
            'current_version': current_version,
            'download_url': download_url,
            'file_size_mb': latest_version.file_size_mb,
            'release_notes': latest_version.release_notes,
            'is_critical': latest_version.is_critical,
        })
    else:
        return Response({
            'update_available': False,
            'latest_version': latest_version.version,
            'current_version': current_version,
        })
    
@csrf_exempt
def health_check(request):
    """Simple health check endpoint for desktop sync"""
    return JsonResponse({
        'status': 'ok',
        'service': 'primebooks'
    })

class DesktopLoginView(APIView):
    """
    Token-based login for desktop app
    Returns JWT token + user data + company data
    ✅ Works with PostgreSQL schemas
    """
    authentication_classes = []        # No token yet — this IS the login endpoint
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        password = request.data.get('password')
        company_id = request.data.get('company_id')

        # Avoid logging the raw email — use a hash for correlation only
        import hashlib
        email_hint = hashlib.sha256(email.encode()).hexdigest()[:8] if email else 'none'
        logger.info(f"🔍 Login attempt - email_hint={email_hint}, Company ID: {company_id}")
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
                    logger.info(f"✅ Found user in schema")
                except CustomUser.DoesNotExist:
                    logger.error(f"❌ User not found in schema {company.schema_name} (hint={email_hint})")
                    return Response(
                        {'detail': 'Invalid credentials'},
                        status=status.HTTP_401_UNAUTHORIZED
                    )

                # Check password
                if not user.check_password(password):
                    logger.error(f"❌ Invalid password (hint={email_hint})")
                    return Response(
                        {'detail': 'Invalid credentials'},
                        status=status.HTTP_401_UNAUTHORIZED
                    )

                if not user.is_active:
                    logger.error(f"❌ User is not active (hint={email_hint})")
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

            logger.info(f"✅ Desktop login successful (hint={email_hint})")
            return Response(response_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"❌ Error during authentication: {e}", exc_info=True)
            return Response(
                {'detail': 'Authentication error'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


@csrf_exempt
def desktop_session_login(request):
    """
    Desktop-only endpoint: given a valid auth token, create a real
    Django session for the user so the browser reflects the switch.

    Called by PrimeBooksWindow._perform_session_switch().
    Only works when DESKTOP_MODE is enabled.

    Token must be sent in the Authorization header (Bearer <token>),
    NOT as a query parameter, to avoid logging in access logs.
    """
    import os
    if not os.environ.get('DESKTOP_MODE'):
        return HttpResponseBadRequest("Not in desktop mode")

    # Accept token from Authorization header only (not query string)
    auth_header = request.META.get('HTTP_AUTHORIZATION', '')
    if auth_header.startswith('Bearer '):
        token = auth_header[7:].strip()
    else:
        return HttpResponseBadRequest("Missing Authorization header")

    email = request.GET.get('email') or (
        request.POST.get('email') if request.method == 'POST' else None
    )

    if not token or not email:
        return HttpResponseBadRequest("Missing token or email")

    try:
        # Validate token cryptographically via simplejwt
        from rest_framework_simplejwt.tokens import AccessToken
        from rest_framework_simplejwt.exceptions import TokenError
        try:
            validated_token = AccessToken(token)
        except TokenError as e:
            logger.warning(f"Invalid token for desktop session switch: {e}")
            return HttpResponseBadRequest("Invalid token")

        # Find user in local DB
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            logger.error(f"User not found locally for session switch")
            return HttpResponseBadRequest("User not found in local database")

        # Confirm the token belongs to this user
        token_user_id = validated_token.get('user_id')
        if str(user.pk) != str(token_user_id):
            logger.warning("Token user_id does not match requested email")
            return HttpResponseBadRequest("Invalid token")

        # Create Django session for this user
        user.backend = 'django.contrib.auth.backends.ModelBackend'
        login(request, user)

        logger.info(f"✅ Desktop session created")
        return redirect('/')

    except Exception as e:
        logger.error(f"Desktop session login error: {e}", exc_info=True)
        return HttpResponseBadRequest("Session switch failed")


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
            token = request.auth
            schema_name = token.get('schema_name') if token else None

            logger.info(f"User sync request in schema: {schema_name}")

            # Get user from current schema context (already set by authentication)
            try:
                user = CustomUser.objects.get(email=email)
            except CustomUser.DoesNotExist:
                logger.error(f"❌ User not found in schema")
                return Response(
                    {'detail': 'User not found'},
                    status=status.HTTP_404_NOT_FOUND
                )

            # Verify requesting user has permission
            if request.user.email != email and not (request.user.is_staff or request.user.is_superuser):
                logger.warning(f"Permission denied: user tried to sync another account")
                return Response(
                    {'detail': 'Permission denied'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Return user data — NEVER expose the real password hash.
            # Desktop authenticates via the server, not local password checks.
            # Use the same unusable placeholder as the bulk download path so
            # the NOT NULL constraint passes on the desktop side.
            user_data = {
                'id': user.id,
                'sync_id': str(user.sync_id) if getattr(user, 'sync_id', None) else None,
                'email': user.email,
                'username': user.username,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'middle_name': getattr(user, 'middle_name', ''),
                'phone_number': getattr(user, 'phone_number', ''),
                'password': '!desktop-no-local-login',  # Never send real hash
                'is_active': user.is_active,
                'is_staff': user.is_staff,
                'is_superuser': user.is_superuser,
                'company_admin': getattr(user, 'company_admin', False),
                'role': getattr(user, 'primary_role_id', None),
            }

            logger.info(f"✅ User sync successful")
            return Response(user_data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"❌ Error syncing user: {e}", exc_info=True)
            return Response(
                {'detail': 'User sync failed'},
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