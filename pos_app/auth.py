from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)
User = get_user_model()


class LoginView(APIView):
    """
    User login endpoint
    POST /api/auth/login/
    """
    permission_classes = [AllowAny]

    def post(self, request):
        username = request.data.get('username')
        password = request.data.get('password')
        email = request.data.get('email')

        if not password:
            return Response(
                {'error': 'Password is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Allow login with either username or email
        if email and not username:
            try:
                user_obj = User.objects.get(email=email)
                username = user_obj.username
            except User.DoesNotExist:
                return Response(
                    {'error': 'Invalid credentials'},
                    status=status.HTTP_401_UNAUTHORIZED
                )

        # Authenticate user
        user = authenticate(username=username, password=password)

        if user is None:
            return Response(
                {'error': 'Invalid credentials'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Check if user is active
        if not user.is_active:
            return Response(
                {'error': 'Account is disabled'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Check if account is locked
        if user.is_locked:
            return Response(
                {'error': 'Account is temporarily locked. Please try again later.'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)

        # Get user's accessible stores
        accessible_stores = user.get_accessible_stores().values(
            'id', 'name', 'code', 'is_active'
        )

        # Get user's primary role
        primary_role = user.primary_role
        role_data = None
        if primary_role:
            role_data = {
                'id': primary_role.id,
                'name': primary_role.group.name,
                'priority': primary_role.priority,
            }

        # Record successful login
        user.record_login_attempt(
            success=True,
            ip_address=self.get_client_ip(request)
        )

        # Build response
        response_data = {
            'token': str(refresh.access_token),
            'refresh': str(refresh),
            'user': {
                'id': user.id,
                'username': user.username,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'full_name': user.get_full_name(),
                'company_id': user.company_id if user.company else None,
                'company_name': user.company.name if user.company else None,
                'is_company_admin': user.company_admin,
                'primary_role': role_data,
                'accessible_stores': list(accessible_stores),
            }
        }

        return Response(response_data, status=status.HTTP_200_OK)

    def get_client_ip(self, request):
        """Get client IP address from request"""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


class LogoutView(APIView):
    """
    User logout endpoint
    POST /api/auth/logout/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            # Blacklist the refresh token if available
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()

            return Response(
                {'message': 'Successfully logged out'},
                status=status.HTTP_200_OK
            )
        except Exception as e:
            logger.error(f"Logout error: {e}")
            return Response(
                {'error': 'Logout failed'},
                status=status.HTTP_400_BAD_REQUEST
            )


class RefreshTokenView(APIView):
    """
    Refresh JWT token
    POST /api/auth/refresh/
    """
    permission_classes = [AllowAny]

    def post(self, request):
        refresh_token = request.data.get('refresh')

        if not refresh_token:
            return Response(
                {'error': 'Refresh token is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            refresh = RefreshToken(refresh_token)
            access_token = str(refresh.access_token)

            return Response({
                'token': access_token,
            }, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Token refresh error: {e}")
            return Response(
                {'error': 'Invalid or expired refresh token'},
                status=status.HTTP_401_UNAUTHORIZED
            )


class HealthCheckView(APIView):
    """
    Health check endpoint for offline detection
    HEAD /api/health/
    GET /api/health/
    """
    permission_classes = [AllowAny]

    def head(self, request):
        return Response(status=status.HTTP_200_OK)

    def get(self, request):
        return Response({
            'status': 'ok',
            'timestamp': timezone.now().isoformat(),
        }, status=status.HTTP_200_OK)


class CurrentUserView(APIView):
    """
    Get current authenticated user details
    GET /api/auth/me/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user

        # Get user's accessible stores
        accessible_stores = user.get_accessible_stores().values(
            'id', 'name', 'code', 'is_active'
        )

        # Get primary role
        primary_role = user.primary_role
        role_data = None
        if primary_role:
            role_data = {
                'id': primary_role.id,
                'name': primary_role.group.name,
                'priority': primary_role.priority,
            }

        return Response({
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'full_name': user.get_full_name(),
            'company_id': user.company_id if user.company else None,
            'company_name': user.company.name if user.company else None,
            'is_company_admin': user.company_admin,
            'primary_role': role_data,
            'accessible_stores': list(accessible_stores),
        }, status=status.HTTP_200_OK)


class ValidateSessionView(APIView):
    """
    Validate if user session is still valid
    POST /api/auth/validate/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user

        # Check if user is still active
        if not user.is_active:
            return Response(
                {'valid': False, 'reason': 'Account disabled'},
                status=status.HTTP_403_FORBIDDEN
            )

        # Check company status
        if user.company and not user.company.has_active_access:
            return Response(
                {'valid': False, 'reason': 'Company subscription expired'},
                status=status.HTTP_403_FORBIDDEN
            )

        return Response({
            'valid': True,
            'user_id': user.id,
            'username': user.username,
        }, status=status.HTTP_200_OK)