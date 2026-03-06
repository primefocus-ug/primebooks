from collections import defaultdict
import hashlib
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Permission
from django.contrib.auth.tokens import default_token_generator
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import connection
from django.db.models import Q, Count
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode

from django_tenants.utils import tenant_context

from company.email import send_tenant_email, send_password_reset_email
from .models import Role, CustomUser
from .forms import (
    RoleForm,
    RolePermissionForm,
    PasswordResetRequestForm,
    SetPasswordForm,
    UserProfileForm,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------
# Lightweight cache-based rate limiting for unauthenticated views
# ----------------------------------------------------------------

def _get_reset_client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    return xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR', '')


def _rl_key_view(scope, identifier):
    h = hashlib.sha256(f"{scope}:{identifier}".encode()).hexdigest()[:16]
    return f"rl:{scope}:{h}"


def _is_reset_rate_limited(scope, identifier, max_attempts, window):
    return cache.get(_rl_key_view(scope, identifier), 0) >= max_attempts


def _increment_reset_rate_limit(scope, identifier, window):
    key = _rl_key_view(scope, identifier)
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, timeout=window)


@login_required
def debug_permissions(request):
    user = request.user

    return JsonResponse({
        'user': user.email,
        'is_active': user.is_active,
        'is_saas_admin': user.is_saas_admin,
        'company_id': user.company_id,
        'company_name': user.company.name if user.company else None,
        'groups': list(user.groups.values_list('name', flat=True)),
        'roles': list(user.groups.filter(role__isnull=False).values(
            'name', 'role__priority', 'role__is_active'
        )),
        'all_permissions': list(user.get_all_permissions()),
        'group_permissions': list(
            user.groups.values_list('permissions__codename', flat=True)
        ),
    })

def password_reset_request(request):
    """
    Password reset request - user enters email
    """
    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']
            ip = _get_reset_client_ip(request)

            # Rate limit: 5 attempts per IP per hour, 3 per email per hour
            if _is_reset_rate_limited('reset_ip', ip, max_attempts=5, window=3600):
                messages.success(
                    request,
                    'If that email exists, password reset instructions have been sent.'
                )
                return redirect('login')

            if _is_reset_rate_limited('reset_email', email.lower(), max_attempts=3, window=3600):
                messages.success(
                    request,
                    'If that email exists, password reset instructions have been sent.'
                )
                return redirect('login')

            _increment_reset_rate_limit('reset_ip', ip, window=3600)
            _increment_reset_rate_limit('reset_email', email.lower(), window=3600)

            try:
                # Get the current tenant
                tenant = getattr(request, 'tenant', None) or getattr(connection, 'tenant', None)

                # Use tenant context for user lookup and email sending
                if tenant:
                    with tenant_context(tenant):
                        user = CustomUser.objects.get(email=email, is_active=True)

                        # Generate password reset token
                        token = default_token_generator.make_token(user)
                        uid = urlsafe_base64_encode(force_bytes(user.pk))

                        # Build reset URL
                        reset_url = request.build_absolute_uri(
                            reverse('password_reset_confirm', kwargs={
                                'uidb64': uid,
                                'token': token
                            })
                        )

                        # Send email using tenant-aware function
                        subject = 'Password Reset Request'
                        message = render_to_string('accounts/password_reset_email.html', {
                            'user': user,
                            'reset_url': reset_url,
                            'site_name': tenant.name,
                        })

                        send_tenant_email(
                            subject=subject,
                            message=message,
                            recipient_list=[user.email],
                            html_message=message,
                            fail_silently=False,
                            tenant=tenant
                        )

                        logger.info(f"Password reset email sent to {email} for tenant {tenant.name}")
                else:
                    # Fallback to regular user lookup and email sending
                    user = CustomUser.objects.get(email=email, is_active=True)

                    # Generate password reset token
                    token = default_token_generator.make_token(user)
                    uid = urlsafe_base64_encode(force_bytes(user.pk))

                    # Build reset URL
                    reset_url = request.build_absolute_uri(
                        reverse('password_reset_confirm', kwargs={
                            'uidb64': uid,
                            'token': token
                        })
                    )

                    # Send email using default method
                    subject = 'Password Reset Request'
                    message = render_to_string('accounts/password_reset_email.html', {
                        'user': user,
                        'reset_url': reset_url,
                        'site_name': 'POS System',
                    })

                    send_mail(
                        subject,
                        message,
                        settings.DEFAULT_FROM_EMAIL,
                        [user.email],
                        html_message=message,
                        fail_silently=False,
                    )

                    logger.info(f"Password reset email sent to {email} (no tenant context)")

            except CustomUser.DoesNotExist:
                # Don't reveal if email exists or not (security) — log quietly
                logger.info(f"Password reset requested for unknown email (not revealed to user)")

            # Always show the same message and redirect, regardless of whether the
            # email exists, to prevent user-enumeration via response differences.
            messages.success(
                request,
                'If that email exists, password reset instructions have been sent.'
            )
            return redirect('login')
    else:
        form = PasswordResetRequestForm()

    return render(request, 'accounts/password_reset_request.html', {'form': form})


def password_reset_confirm(request, uidb64, token):
    """
    Password reset confirmation - user clicks link from email
    """
    try:
        # Get the current tenant
        tenant = getattr(request, 'tenant', None) or getattr(connection, 'tenant', None)

        uid = force_str(urlsafe_base64_decode(uidb64))

        if tenant:
            # Use tenant context for user lookup and password reset
            with tenant_context(tenant):
                user = CustomUser.objects.get(pk=uid)

                if default_token_generator.check_token(user, token):
                    if request.method == 'POST':
                        form = SetPasswordForm(user, request.POST)
                        if form.is_valid():
                            form.save()

                            # Unlock account if locked
                            if user.is_locked:
                                user.unlock_account()

                            messages.success(
                                request,
                                'Your password has been reset successfully. You can now log in.'
                            )
                            logger.info(f"Password reset successful for user {user.email} in tenant {tenant.name}")

                            return redirect('login')
                    else:
                        form = SetPasswordForm(user)

                    return render(request, 'accounts/password_reset_confirm.html', {
                        'form': form,
                        'validlink': True,
                    })
                else:
                    messages.error(
                        request,
                        'The password reset link is invalid or has expired. Please request a new one.'
                    )
                    return render(request, 'accounts/password_reset_confirm.html', {
                        'validlink': False,
                    })
        else:
            # Fallback without tenant context
            user = CustomUser.objects.get(pk=uid)

            if default_token_generator.check_token(user, token):
                if request.method == 'POST':
                    form = SetPasswordForm(user, request.POST)
                    if form.is_valid():
                        form.save()

                        # Unlock account if locked
                        if user.is_locked:
                            user.unlock_account()

                        messages.success(
                            request,
                            'Your password has been reset successfully. You can now log in.'
                        )
                        logger.info(f"Password reset successful for user {user.email}")

                        return redirect('login')
                else:
                    form = SetPasswordForm(user)

                return render(request, 'accounts/password_reset_confirm.html', {
                    'form': form,
                    'validlink': True,
                })
            else:
                messages.error(
                    request,
                    'The password reset link is invalid or has expired. Please request a new one.'
                )
                return render(request, 'accounts/password_reset_confirm.html', {
                    'validlink': False,
                })

    except (TypeError, ValueError, OverflowError, CustomUser.DoesNotExist):
        messages.error(
            request,
            'The password reset link is invalid or has expired. Please request a new one.'
        )
        return render(request, 'accounts/password_reset_confirm.html', {
            'validlink': False,
        })


@login_required
@permission_required('accounts.view_role', raise_exception=True)
def role_list(request):
    company = request.tenant

    roles = Role.objects.filter(
        Q(company=company) | Q(company__isnull=True, is_system_role=True)
    ).select_related('group', 'company', 'created_by').annotate(
        total_users=Count('group__user')
    ).order_by('-priority', 'group__name')

    total_users = CustomUser.objects.filter(company=company, is_hidden=False).count()
    active_roles = roles.filter(is_active=True).count()

    context = {
        'roles': roles,
        'total_users': total_users,
        'active_roles': active_roles,
        'can_create': not request.user.company.plan or \
                      roles.filter(company=company).count() < 20,
    }

    return render(request, 'accounts/role_list.html', context)



@login_required
@permission_required('accounts.view_role', raise_exception=True)
def role_detail(request, pk):
    """Show detailed view of a role with permissions and users"""
    company = request.tenant

    role = get_object_or_404(
        Role.objects.select_related('group', 'company', 'created_by'),
        pk=pk
    )

    # Check access
    if role.company and role.company != company:
        messages.error(request, "You don't have access to this role.")
        return redirect('role_list')

    # Get users in this role
    users = CustomUser.objects.filter(
        groups=role.group,
        company=company,
        is_hidden=False
    ).select_related('company')

    # Get permissions grouped by app
    permission_groups = role.get_permission_groups()

    context = {
        'role': role,
        'users': users,
        'permission_groups': permission_groups,
        'can_edit': not role.is_system_role or request.user.is_superuser,
        'can_delete': not role.is_system_role and role.user_count == 0,
    }

    return render(request, 'accounts/role_detail.html', context)


@login_required
@permission_required('accounts.add_role', raise_exception=True)
def role_create(request):
    """Create a new custom role"""
    company = request.tenant

    if request.method == 'POST':
        form = RoleForm(request.POST, company=company)
        if form.is_valid():
            role = form.save(commit=False)
            role.company = company
            role.is_system_role = False
            role.created_by = request.user
            role.save()

            messages.success(request, f"Role '{role.group.name}' created successfully!")
            return redirect('role_permissions', pk=role.pk)
    else:
        form = RoleForm(company=company)

    context = {
        'form': form,
        'title': 'Create New Role',
        'submit_text': 'Create & Set Permissions',
    }

    return render(request, 'accounts/role_form.html', context)


@login_required
@permission_required('accounts.change_role', raise_exception=True)
def role_edit(request, pk):
    """Edit an existing role"""
    company = request.tenant

    role = get_object_or_404(Role, pk=pk)

    # Check access
    if role.company and role.company != company:
        messages.error(request, "You don't have access to this role.")
        return redirect('role_list')

    if role.is_system_role and not request.user.is_superuser:
        messages.error(request, "System roles cannot be edited.")
        return redirect('role_detail', pk=pk)

    if request.method == 'POST':
        form = RoleForm(request.POST, instance=role, company=company)
        if form.is_valid():
            form.save()
            messages.success(request, f"Role '{role.group.name}' updated successfully!")
            return redirect('role_detail', pk=pk)
    else:
        form = RoleForm(instance=role, company=company)

    context = {
        'form': form,
        'role': role,
        'title': f'Edit Role: {role.group.name}',
        'submit_text': 'Save Changes',
    }

    return render(request, 'accounts/role_form.html', context)


RBAC_ALLOWED_APPS = {
    'accounts',
    'company',
    'inventory',
    'invoices',
    'sales',
    'stores',
    'reports',
    'customers',
    'branches',
    'expenses',
    'efris',
    'notifications',
    'finance',
}


@login_required
@permission_required('accounts.add_role', raise_exception=True)
def role_permissions(request, pk):
    """Manage permissions for a role with visual interface"""
    company = request.tenant

    role = get_object_or_404(
        Role.objects.select_related('group'),
        pk=pk
    )

    # Access checks
    if role.company and role.company != company:
        messages.error(request, "You don't have access to this role.")
        return redirect('role_list')

    if role.is_system_role and not request.user.is_superuser:
        messages.error(request, "System role permissions cannot be modified.")
        return redirect('role_detail', pk=pk)

    # -------------------------------
    # POST: update permissions (SECURE)
    # -------------------------------
    if request.method == 'POST':
        selected_permissions = request.POST.getlist('permissions')

        # Guard against non-integer values submitted by a malicious or broken client
        permission_ids = []
        for p in selected_permissions:
            try:
                permission_ids.append(int(p))
            except (ValueError, TypeError):
                pass

        # IMPORTANT: restrict permissions again on POST
        permissions = Permission.objects.filter(
            id__in=permission_ids,
            content_type__app_label__in=RBAC_ALLOWED_APPS
        )

        role.group.permissions.set(permissions)

        messages.success(
            request,
            f"Updated permissions for '{role.group.name}'. "
            f"Now has {permissions.count()} permissions."
        )
        return redirect('role_detail', pk=pk)

    # --------------------------------
    # GET: list permissions (FILTERED)
    # --------------------------------
    all_permissions = (
        Permission.objects.filter(
            content_type__app_label__in=RBAC_ALLOWED_APPS
        )
        .select_related('content_type')
        .order_by(
            'content_type__app_label',
            'content_type__model',
            'codename'
        )
    )

    permission_structure = defaultdict(lambda: defaultdict(list))
    current_permissions = set(
        role.group.permissions.values_list('id', flat=True)
    )

    for perm in all_permissions:
        app_label = perm.content_type.app_label
        model_name = perm.content_type.model

        permission_structure[app_label][model_name].append({
            'id': perm.id,
            'name': perm.name,
            'codename': perm.codename,
            'action': perm.codename.split('_', 1)[0],
            'selected': perm.id in current_permissions,
        })

    permission_structure = {
        app: dict(models) for app, models in permission_structure.items()
    }

    context = {
        'role': role,
        'permission_structure': permission_structure,
        'current_count': len(current_permissions),
    }

    return render(request, 'accounts/role_permissions.html', context)



@login_required
@permission_required('accounts.add_role', raise_exception=True)
def role_users(request, pk):
    """Manage users assigned to a role"""
    company = request.tenant

    role = get_object_or_404(Role, pk=pk)

    # Check access
    if role.company and role.company != company:
        messages.error(request, "You don't have access to this role.")
        return redirect('role_list')

    if request.method == 'POST':
        action = request.POST.get('action')
        user_ids = request.POST.getlist('users')

        if action == 'add':
            users = CustomUser.objects.filter(
                id__in=user_ids,
                company=company,
                is_hidden=False
            )
            for user in users:
                user.groups.add(role.group)
            messages.success(request, f"Added {users.count()} users to '{role.group.name}'")

        elif action == 'remove':
            users = CustomUser.objects.filter(
                id__in=user_ids,
                company=company
            )
            for user in users:
                user.groups.remove(role.group)
            messages.success(request, f"Removed {users.count()} users from '{role.group.name}'")

        return redirect('role_users', pk=pk)

    # Get current users in role
    current_users = CustomUser.objects.filter(
        groups=role.group,
        company=company,
        is_hidden=False
    ).select_related('company')

    # Get available users not in role
    available_users = CustomUser.objects.filter(
        company=company,
        is_hidden=False
    ).exclude(
        groups=role.group
    ).select_related('company')

    context = {
        'role': role,
        'current_users': current_users,
        'available_users': available_users,
        'can_add': not role.is_at_capacity,
    }

    return render(request, 'accounts/roles/role_users.html', context)


@login_required
@permission_required('accounts.delete_role', raise_exception=True)
def role_delete(request, pk):
    """Delete a custom role"""
    company = request.tenant

    role = get_object_or_404(Role, pk=pk)

    # Check access
    if role.company and role.company != company:
        messages.error(request, "You don't have access to this role.")
        return redirect('role_list')

    if role.is_system_role:
        messages.error(request, "System roles cannot be deleted.")
        return redirect('role_detail', pk=pk)

    if role.user_count > 0:
        messages.error(
            request,
            f"Cannot delete role '{role.group.name}' because it has {role.user_count} users. "
            "Please reassign users first."
        )
        return redirect('role_detail', pk=pk)

    if request.method == 'POST':
        role_name = role.group.name
        group = role.group
        role.delete()
        group.delete()

        messages.success(request, f"Role '{role_name}' deleted successfully!")
        return redirect('role_list')

    context = {
        'role': role,
    }

    return render(request, 'accounts/roles/role_confirm_delete.html', context)


# AJAX endpoints for better UX
@login_required
def role_check_capacity(request, pk):
    """Check if role can accept more users (AJAX)"""
    role = get_object_or_404(Role, pk=pk)

    # Restrict to roles belonging to the current tenant or system roles
    company = getattr(request, 'tenant', None)
    if company and role.company and role.company != company:
        return JsonResponse({'error': 'Access denied'}, status=403)

    can_assign, message = role.can_assign_to_user()

    return JsonResponse({
        'can_assign': can_assign,
        'message': message,
        'current_users': role.user_count,
        'max_users': role.max_users,
        'capacity_percentage': role.capacity_percentage,
    })


@login_required
def role_permission_preview(request, pk):
    """Get permission summary for a role (AJAX)"""
    role = get_object_or_404(Role, pk=pk)

    permission_groups = role.get_permission_groups()

    summary = {
        app: len(perms) for app, perms in permission_groups.items()
    }

    return JsonResponse({
        'total': role.permission_count,
        'by_app': summary,
    })