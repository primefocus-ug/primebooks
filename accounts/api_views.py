from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.authtoken.models import Token
from django.db.models import Q
from django.utils import timezone
from django.shortcuts import get_object_or_404

from .models import CustomUser, UserSignature, Role, RoleHistory, AuditLog, LoginHistory
from .serializers import (
    UserRegistrationSerializer,
    LoginSerializer,
    PasswordChangeSerializer,
    UserSerializer,
    UserUpdateSerializer,
    UserSignatureSerializer,
    UserProfileSerializer,
    UserListSerializer,
)


# ============================================
# HELPERS
# ============================================

class StandardPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_action(request, action, description, **kwargs):
    try:
        AuditLog.log(
            action=action,
            user=request.user if request.user.is_authenticated else None,
            description=description,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            request_path=request.path,
            request_method=request.method,
            **kwargs
        )
    except Exception:
        pass


# ============================================
# AUTH
# ============================================

class RegisterView(APIView):
    """POST /api/auth/register/"""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = UserRegistrationSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = serializer.save()
            token, _ = Token.objects.get_or_create(user=user)
            log_action(request, 'user_created', f"New user registered: {user.email}")
            return Response({
                'user': UserProfileSerializer(user, context={'request': request}).data,
                'token': token.key,
            }, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    """POST /api/auth/login/"""
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = serializer.validated_data['user']
            ip = get_client_ip(request)

            user.record_login_attempt(success=True, ip_address=ip)

            LoginHistory.objects.create(
                user=user,
                status='success',
                ip_address=ip or '0.0.0.0',
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
            )

            token, _ = Token.objects.get_or_create(user=user)
            log_action(request, 'login_success', f"User logged in: {user.email}")

            return Response({
                'user': UserProfileSerializer(user, context={'request': request}).data,
                'token': token.key,
            })

        # Record failed attempt
        email = request.data.get('email')
        if email:
            try:
                user = CustomUser.objects.get(email=email)
                ip = get_client_ip(request)
                user.record_login_attempt(success=False)
                LoginHistory.objects.create(
                    user=user,
                    status='failed',
                    ip_address=ip or '0.0.0.0',
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    failure_reason='Invalid credentials',
                )
            except CustomUser.DoesNotExist:
                pass

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LogoutView(APIView):
    """POST /api/auth/logout/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            request.user.auth_token.delete()
        except Token.DoesNotExist:
            pass
        log_action(request, 'logout', f"User logged out: {request.user.email}")
        return Response({'detail': 'Successfully logged out.'})


class PasswordChangeView(APIView):
    """POST /api/auth/password/change/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = PasswordChangeSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            # Rotate token on password change for security
            try:
                request.user.auth_token.delete()
            except Token.DoesNotExist:
                pass
            token, _ = Token.objects.get_or_create(user=request.user)
            log_action(request, 'password_changed', f"Password changed for: {request.user.email}")
            return Response({'detail': 'Password updated successfully.', 'token': token.key})
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# ============================================
# CURRENT USER (PROFILE)
# ============================================

class MeView(APIView):
    """
    GET   /api/auth/me/   - Own profile
    PATCH /api/auth/me/   - Update own profile
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        return Response(UserProfileSerializer(request.user, context={'request': request}).data)

    def patch(self, request):
        serializer = UserProfileSerializer(
            request.user, data=request.data, partial=True, context={'request': request}
        )
        if serializer.is_valid():
            serializer.save()
            log_action(request, 'user_updated', f"Profile updated: {request.user.email}")
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class MySignatureView(APIView):
    """
    GET    /api/auth/me/signature/
    POST   /api/auth/me/signature/
    DELETE /api/auth/me/signature/
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        try:
            return Response(UserSignatureSerializer(request.user.signature).data)
        except UserSignature.DoesNotExist:
            return Response({'detail': 'No signature found.'}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request):
        try:
            sig = request.user.signature
            serializer = UserSignatureSerializer(
                sig, data=request.data, partial=True, context={'request': request}
            )
        except UserSignature.DoesNotExist:
            serializer = UserSignatureSerializer(data=request.data, context={'request': request})

        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        try:
            request.user.signature.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except UserSignature.DoesNotExist:
            return Response({'detail': 'No signature found.'}, status=status.HTTP_404_NOT_FOUND)


class MyLoginHistoryView(APIView):
    """GET /api/auth/me/login-history/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = LoginHistory.objects.filter(user=request.user).order_by('-timestamp')[:50]
        data = [
            {
                'id': h.id,
                'status': h.status,
                'ip_address': h.ip_address,
                'browser': h.browser,
                'os': h.os,
                'device_type': h.device_type,
                'location': h.location,
                'timestamp': h.timestamp,
                'session_duration': str(h.session_duration) if h.session_duration else None,
            }
            for h in qs
        ]
        return Response(data)


# ============================================
# USER MANAGEMENT
# ============================================

class UserListCreateView(APIView):
    """
    GET  /api/users/   - List manageable users (with search & pagination)
    POST /api/users/   - Create a new user
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        qs = request.user.get_manageable_users()

        # Search
        search = request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(email__icontains=search) |
                Q(username__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search)
            )

        # Filtering
        if request.query_params.get('is_active') is not None:
            qs = qs.filter(is_active=request.query_params['is_active'].lower() == 'true')

        # Ordering
        ordering = request.query_params.get('ordering', '-date_joined')
        allowed_orderings = ['date_joined', '-date_joined', 'email', '-email', 'username']
        if ordering in allowed_orderings:
            qs = qs.order_by(ordering)

        # Paginate
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = UserListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request):
        if not (request.user.company_admin or request.user.is_saas_admin):
            return Response({'detail': 'Only company admins can create users.'}, status=status.HTTP_403_FORBIDDEN)

        serializer = UserRegistrationSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            user = serializer.save()
            log_action(request, 'user_created', f"User created: {user.email}")
            return Response(
                UserProfileSerializer(user, context={'request': request}).data,
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserDetailView(APIView):
    """
    GET    /api/users/<pk>/
    PATCH  /api/users/<pk>/
    DELETE /api/users/<pk>/   - Deactivates (soft delete)
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_target(self, request, pk):
        user = get_object_or_404(CustomUser, pk=pk, is_hidden=False)
        if not (request.user.can_manage_user(user) or request.user.pk == user.pk):
            return None, Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        return user, None

    def get(self, request, pk):
        user, err = self._get_target(request, pk)
        if err:
            return err
        return Response(UserSerializer(user, context={'request': request}).data)

    def patch(self, request, pk):
        user, err = self._get_target(request, pk)
        if err:
            return err
        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            log_action(request, 'user_updated', f"User updated: {user.email}")
            return Response(UserSerializer(user, context={'request': request}).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        user, err = self._get_target(request, pk)
        if err:
            return err
        if user.pk == request.user.pk:
            return Response({'detail': 'Cannot deactivate yourself.'}, status=status.HTTP_400_BAD_REQUEST)
        user.is_active = False
        user.save(update_fields=['is_active'])
        log_action(request, 'user_deactivated', f"User deactivated: {user.email}")
        return Response({'detail': 'User deactivated.'})


class UserActivateView(APIView):
    """POST /api/users/<pk>/activate/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        user = get_object_or_404(CustomUser, pk=pk, is_hidden=False)
        if not request.user.can_manage_user(user):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        user.is_active = True
        user.save(update_fields=['is_active'])
        log_action(request, 'user_activated', f"User activated: {user.email}")
        return Response({'detail': 'User activated.'})


class UserStatsView(APIView):
    """GET /api/users/stats/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not (request.user.company_admin or request.user.is_saas_admin):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        base = CustomUser.objects.filter(company=request.user.company, is_hidden=False)
        return Response({
            'total': base.count(),
            'active': base.filter(is_active=True).count(),
            'inactive': base.filter(is_active=False).count(),
            'locked': sum(1 for u in base if u.is_locked),
            'company_admins': base.filter(company_admin=True).count(),
        })


# ============================================
# ROLE MANAGEMENT
# ============================================

class RoleListView(APIView):
    """GET /api/roles/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        roles = Role.get_accessible_roles_for_user(request.user)
        data = [
            {
                'id': r.id,
                'name': r.group.name,
                'description': r.description,
                'priority': r.priority,
                'color': r.color_code,
                'is_active': r.is_active,
                'is_system_role': r.is_system_role,
                'user_count': r.user_count,
                'max_users': r.max_users,
                'is_at_capacity': r.is_at_capacity,
                'capacity_percentage': r.capacity_percentage,
                'permission_count': r.permission_count,
            }
            for r in roles
        ]
        return Response(data)


class RoleDetailView(APIView):
    """GET /api/roles/<pk>/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        role = get_object_or_404(Role, pk=pk)
        accessible = Role.get_accessible_roles_for_user(request.user)
        if not accessible.filter(pk=role.pk).exists():
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'id': role.id,
            'name': role.group.name,
            'description': role.description,
            'priority': role.priority,
            'color': role.color_code,
            'is_active': role.is_active,
            'is_system_role': role.is_system_role,
            'user_count': role.user_count,
            'max_users': role.max_users,
            'is_at_capacity': role.is_at_capacity,
            'permissions': role.get_permission_groups(),
        })


class UserRolesView(APIView):
    """GET /api/users/<pk>/roles/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        target = get_object_or_404(CustomUser, pk=pk, is_hidden=False)
        if not (request.user.can_manage_user(target) or request.user.pk == target.pk):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        return Response({
            'primary_role': {
                'id': target.primary_role.id,
                'name': target.primary_role.group.name,
                'priority': target.primary_role.priority,
                'color': target.primary_role.color_code,
            } if target.primary_role else None,
            'all_roles': [
                {
                    'id': r.id,
                    'name': r.group.name,
                    'priority': r.priority,
                    'color': r.color_code,
                    'is_primary': (r.pk == target.primary_role_id),
                }
                for r in target.all_roles
            ],
        })


class AssignRoleView(APIView):
    """POST /api/users/<pk>/roles/assign/   Body: { "role_id": <int> }"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        target = get_object_or_404(CustomUser, pk=pk, is_hidden=False)
        role_id = request.data.get('role_id')
        if not role_id:
            return Response({'detail': 'role_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        role = get_object_or_404(Role, pk=role_id)
        if not request.user.can_assign_role(role):
            return Response({'detail': 'You cannot assign this role.'}, status=status.HTTP_403_FORBIDDEN)
        try:
            target.assign_role(role)
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        log_action(request, 'permission_changed', f"Role '{role.group.name}' assigned to {target.email}")
        return Response({'detail': f"Role '{role.group.name}' assigned successfully."})


class RemoveRoleView(APIView):
    """POST /api/users/<pk>/roles/remove/   Body: { "role_id": <int> }"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        target = get_object_or_404(CustomUser, pk=pk, is_hidden=False)
        role_id = request.data.get('role_id')
        if not role_id:
            return Response({'detail': 'role_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        role = get_object_or_404(Role, pk=role_id)
        if not request.user.can_assign_role(role):
            return Response({'detail': 'You cannot manage this role.'}, status=status.HTTP_403_FORBIDDEN)
        target.remove_role(role)
        log_action(request, 'permission_changed', f"Role '{role.group.name}' removed from {target.email}")
        return Response({'detail': f"Role '{role.group.name}' removed successfully."})


class SetPrimaryRoleView(APIView):
    """POST /api/users/<pk>/roles/set-primary/   Body: { "role_id": <int> }"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        target = get_object_or_404(CustomUser, pk=pk, is_hidden=False)
        role_id = request.data.get('role_id')
        if not role_id:
            return Response({'detail': 'role_id is required.'}, status=status.HTTP_400_BAD_REQUEST)
        role = get_object_or_404(Role, pk=role_id)
        if not target.groups.filter(pk=role.group.pk).exists():
            return Response({'detail': 'User does not have this role.'}, status=status.HTTP_400_BAD_REQUEST)
        if not request.user.can_manage_user(target):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        target.primary_role = role
        target.save(update_fields=['primary_role'])
        log_action(request, 'user_updated', f"Primary role set to '{role.group.name}' for {target.email}")
        return Response({'detail': 'Primary role updated.'})


# ============================================
# SIGNATURE MANAGEMENT (Admin)
# ============================================

class UserSignatureAdminView(APIView):
    """GET /api/users/<pk>/signature/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        if not (request.user.company_admin or request.user.is_saas_admin):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        target = get_object_or_404(CustomUser, pk=pk)
        try:
            return Response(UserSignatureSerializer(target.signature).data)
        except UserSignature.DoesNotExist:
            return Response({'detail': 'No signature found.'}, status=status.HTTP_404_NOT_FOUND)


class VerifySignatureView(APIView):
    """POST /api/users/<pk>/signature/verify/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not (request.user.company_admin or request.user.is_saas_admin):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        target = get_object_or_404(CustomUser, pk=pk)
        try:
            sig = target.signature
        except UserSignature.DoesNotExist:
            return Response({'detail': 'No signature found.'}, status=status.HTTP_404_NOT_FOUND)
        sig.is_verified = True
        sig.verified_at = timezone.now()
        sig.verified_by = request.user
        sig.save(update_fields=['is_verified', 'verified_at', 'verified_by'])
        return Response({'detail': 'Signature verified.', 'verified_at': sig.verified_at})


# ============================================
# AUDIT LOGS
# ============================================

class AuditLogListView(APIView):
    """
    GET /api/audit-logs/
    Query params: action, user_id, severity, success, start_date, end_date
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not (request.user.company_admin or request.user.is_saas_admin
                or request.user.has_perm('accounts.view_all_audit_logs')):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

        qs = AuditLog.objects.select_related('user', 'company', 'store')
        if not request.user.is_saas_admin:
            qs = qs.filter(company=request.user.company)

        p = request.query_params
        if p.get('action'):
            qs = qs.filter(action=p['action'])
        if p.get('user_id'):
            qs = qs.filter(user_id=p['user_id'])
        if p.get('severity'):
            qs = qs.filter(severity=p['severity'])
        if p.get('success') is not None:
            qs = qs.filter(success=p['success'].lower() == 'true')
        if p.get('start_date'):
            qs = qs.filter(timestamp__date__gte=p['start_date'])
        if p.get('end_date'):
            qs = qs.filter(timestamp__date__lte=p['end_date'])

        qs = qs.order_by('-timestamp')
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        data = [
            {
                'id': log.id,
                'action': log.action,
                'action_display': log.get_action_display(),
                'description': log.action_description,
                'severity': log.severity,
                'success': log.success,
                'user': log.user.get_full_name() if log.user else 'System',
                'user_id': log.user_id,
                'ip_address': log.ip_address,
                'timestamp': log.timestamp,
                'resource_name': log.resource_name,
                'requires_review': log.requires_review,
                'reviewed': log.reviewed,
            }
            for log in (page if page is not None else qs)
        ]
        if page is not None:
            return paginator.get_paginated_response(data)
        return Response(data)


class AuditLogDetailView(APIView):
    """GET /api/audit-logs/<pk>/"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, pk):
        if not (request.user.company_admin or request.user.is_saas_admin):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        log = get_object_or_404(AuditLog, pk=pk)
        return Response({
            'id': log.id,
            'action': log.action,
            'action_display': log.get_action_display(),
            'description': log.action_description,
            'severity': log.severity,
            'success': log.success,
            'error_message': log.error_message,
            'user': log.user.get_full_name() if log.user else 'System',
            'ip_address': log.ip_address,
            'user_agent': log.user_agent,
            'request_path': log.request_path,
            'request_method': log.request_method,
            'timestamp': log.timestamp,
            'duration_ms': log.duration_ms,
            'resource_name': log.resource_name,
            'changes': log.changes,
            'metadata': log.metadata,
            'requires_review': log.requires_review,
            'reviewed': log.reviewed,
            'reviewed_by': log.reviewed_by.get_full_name() if log.reviewed_by else None,
            'reviewed_at': log.reviewed_at,
        })


class ReviewAuditLogView(APIView):
    """POST /api/audit-logs/<pk>/review/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        if not request.user.has_perm('accounts.review_audit_logs'):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        log = get_object_or_404(AuditLog, pk=pk)
        log.reviewed = True
        log.reviewed_by = request.user
        log.reviewed_at = timezone.now()
        log.save(update_fields=['reviewed', 'reviewed_by', 'reviewed_at'])
        return Response({'detail': 'Audit log reviewed.'})


# ============================================
# ACCOUNT SECURITY
# ============================================

class LockUserView(APIView):
    """POST /api/users/<pk>/lock/   Body: { "duration_minutes": 30 }"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        target = get_object_or_404(CustomUser, pk=pk)
        if not request.user.can_manage_user(target):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        duration = int(request.data.get('duration_minutes', 30))
        target.lock_account(duration_minutes=duration)
        log_action(request, 'account_locked', f"Account locked: {target.email} for {duration} minutes")
        return Response({'detail': f'Account locked for {duration} minutes.'})


class UnlockUserView(APIView):
    """POST /api/users/<pk>/unlock/"""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        target = get_object_or_404(CustomUser, pk=pk)
        if not request.user.can_manage_user(target):
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        target.unlock_account()
        log_action(request, 'account_unlocked', f"Account unlocked: {target.email}")
        return Response({'detail': 'Account unlocked.'})