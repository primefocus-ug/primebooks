from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse
from django.db.models import Q
from .models import PublicUser, PasswordResetToken, PublicUserActivity
from .forms import (
    PublicLoginForm, PublicUserCreationForm, PublicUserChangeForm,
    PasswordResetRequestForm, PasswordResetForm, PasswordChangeForm
)
import secrets
from public_support.models import SupportTicket
from public_seo.models import SEOPage
from public_blog.models import BlogPost
from company.models import Company
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .dashboard_widgets import get_signup_stats

@login_required(login_url='public_accounts:login')
def dashboard_view(request):
    """Admin dashboard with signup statistics"""
    context = {
        'title': 'Dashboard',
        'signup_stats': get_signup_stats(),
    }
    return render(request, 'public_admin/dashboard.html', context)


def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

@login_required
def public_admin_index(request):
    user = request.user

    # Stats (replace with tenant-aware queries if needed)
    stats = {
        'total_companies': Company.objects.count(),
        'total_blog_posts': BlogPost.objects.count(),
        'total_seo_pages': SEOPage.objects.count(),
        'total_support_tickets': SupportTicket.objects.count(),
    }

    recent_activities = PublicUserActivity.objects.order_by('-timestamp')[:10]

    # Only check permissions if user has a company
    if hasattr(user, 'company'):
        user.can_manage_blog = user.has_perm('blog.add_blogpost')
        user.can_manage_seo = user.has_perm('seo.change_seopage')
        user.can_manage_support = user.has_perm('support.change_supportticket')
        user.can_manage_companies = user.has_perm('companies.view_company')
    else:
        # Public users: no company-level permissions
        user.can_manage_blog = False
        user.can_manage_seo = False
        user.can_manage_support = False
        user.can_manage_companies = False

    return render(request, 'public_admin/index.html', {
        'title': 'Dashboard',
        'stats': stats,
        'recent_activities': recent_activities,
        'user': user,
    })

def login_view(request):
    """Public admin login view"""
    if request.user.is_authenticated:
        return redirect('public_accounts:public_admin_index')

    if request.method == 'POST':
        form = PublicLoginForm(request.POST)
        if form.is_valid():
            identifier = form.cleaned_data['identifier']
            password = form.cleaned_data['password']

            user = authenticate(
                request,
                identifier=identifier,
                password=password
            )

            if user is not None:
                login(request, user, backend='public_accounts.backends.PublicIdentifierBackend')

                # Log activity
                PublicUserActivity.objects.create(
                    user=user,
                    action='LOGIN',
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')
                )

                messages.success(request, f'Welcome back, {user.get_full_name()}!')

                # Check if password change required
                if user.force_password_change:
                    messages.warning(request, 'Please change your password.')
                    return redirect('public_accounts:change_password')

                # Redirect to next or dashboard
                next_url = request.GET.get('next')
                if next_url:
                    return redirect(next_url)
                return redirect('public_accounts:public_admin_index')
            else:
                messages.error(request, 'Invalid identifier or password.')
    else:
        form = PublicLoginForm()

    return render(request, 'public_admin/login.html', {
        'form': form,
        'title': 'Login'
    })


@login_required(login_url='public_accounts:login')
def logout_view(request):
    """Logout view"""
    # Log activity
    PublicUserActivity.objects.create(
        user=request.user,
        action='LOGOUT',
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')
    )

    logout(request)
    messages.success(request, 'You have been logged out successfully.')
    return redirect('public_accounts:login')


@login_required(login_url='public_accounts:login')
def profile_view(request):
    """User profile view"""
    if request.method == 'POST':
        form = PublicUserChangeForm(request.POST, request.FILES, instance=request.user)
        if form.is_valid():
            form.save()

            # Log activity
            PublicUserActivity.objects.create(
                user=request.user,
                action='UPDATE',
                description='Updated profile',
                ip_address=get_client_ip(request)
            )

            messages.success(request, 'Profile updated successfully.')
            return redirect('public_accounts:profile')
    else:
        form = PublicUserChangeForm(instance=request.user)

    # Get recent activities
    recent_activities = PublicUserActivity.objects.filter(
        user=request.user
    ).order_by('-timestamp')[:10]

    return render(request, 'public_admin/profile.html', {
        'form': form,
        'recent_activities': recent_activities,
        'title': 'My Profile'
    })


@login_required(login_url='public_accounts:login')
def change_password_view(request):
    """Change password view"""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()

            # Update password metadata
            user.password_changed_at = timezone.now()
            user.force_password_change = False
            user.save(update_fields=['password_changed_at', 'force_password_change'])

            # Log activity
            PublicUserActivity.objects.create(
                user=user,
                action='PASSWORD_CHANGE',
                ip_address=get_client_ip(request)
            )

            # Re-login user
            login(request, user, backend='public_accounts.backends.PublicIdentifierBackend')

            messages.success(request, 'Password changed successfully.')
            return redirect('public_accounts:public_admin_index')
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'public_admin/change_password.html', {
        'form': form,
        'title': 'Change Password'
    })


def password_reset_request_view(request):
    """Request password reset"""
    if request.method == 'POST':
        form = PasswordResetRequestForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data['email']

            try:
                user = PublicUser.objects.get(email=email, is_active=True)

                # Generate reset token
                token = PasswordResetToken.generate_token()
                expires_at = timezone.now() + timezone.timedelta(hours=24)

                reset_token = PasswordResetToken.objects.create(
                    user=user,
                    token=token,
                    expires_at=expires_at,
                    ip_address=get_client_ip(request)
                )

                # Send reset email
                user.send_password_reset_email(token)

                messages.success(
                    request,
                    'Password reset instructions have been sent to your email.'
                )
            except PublicUser.DoesNotExist:
                # Don't reveal if email exists
                messages.success(
                    request,
                    'If that email exists, password reset instructions have been sent.'
                )

            return redirect('public_accounts:login')
    else:
        form = PasswordResetRequestForm()

    return render(request, 'public_admin/password_reset_request.html', {
        'form': form,
        'title': 'Reset Password'
    })


def password_reset_confirm_view(request, token):
    """Confirm password reset with token"""
    try:
        reset_token = PasswordResetToken.objects.get(token=token)

        if not reset_token.is_valid():
            messages.error(request, 'This password reset link has expired or been used.')
            return redirect('public_accounts:password_reset_request')

        if request.method == 'POST':
            form = PasswordResetForm(request.POST)
            if form.is_valid():
                # Update password
                user = reset_token.user
                user.set_password(form.cleaned_data['password'])
                user.force_password_change = False
                user.password_changed_at = timezone.now()
                user.save()

                # Mark token as used
                reset_token.mark_as_used(ip_address=get_client_ip(request))

                # Log activity
                PublicUserActivity.objects.create(
                    user=user,
                    action='PASSWORD_RESET',
                    ip_address=get_client_ip(request)
                )

                messages.success(request, 'Password reset successfully. You can now login.')
                return redirect('public_accounts:login')
        else:
            form = PasswordResetForm()

        return render(request, 'public_admin/password_reset_confirm.html', {
            'form': form,
            'token': token,
            'title': 'Set New Password'
        })

    except PasswordResetToken.DoesNotExist:
        messages.error(request, 'Invalid password reset link.')
        return redirect('public_accounts:password_reset_request')


@login_required(login_url='public_accounts:login')
@require_http_methods(["POST"])
def activity_log_api(request):
    """API to log user activities"""
    action = request.POST.get('action')
    app_name = request.POST.get('app_name', '')
    model_name = request.POST.get('model_name', '')
    object_id = request.POST.get('object_id', '')
    description = request.POST.get('description', '')

    PublicUserActivity.objects.create(
        user=request.user,
        action=action,
        app_name=app_name,
        model_name=model_name,
        object_id=object_id,
        description=description,
        ip_address=get_client_ip(request),
        user_agent=request.META.get('HTTP_USER_AGENT', '')
    )

    return JsonResponse({'success': True})


# Admin User Management Views (for superusers)
@login_required(login_url='public_accounts:login')
def user_list_view(request):
    """List all public users (superuser only)"""
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('public_accounts:public_admin_index')

    users = PublicUser.objects.all().order_by('-date_joined')

    # Search
    search_query = request.GET.get('q')
    if search_query:
        users = users.filter(
            Q(identifier__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(username__icontains=search_query) |
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query)
        )

    return render(request, 'public_admin/user_list.html', {
        'users': users,
        'search_query': search_query,
        'title': 'Manage Users'
    })


@login_required(login_url='public_accounts:login')
def user_create_view(request):
    """Create new public user (superuser only)"""
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('public_accounts:public_admin_index')

    if request.method == 'POST':
        form = PublicUserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()

            # Log activity
            PublicUserActivity.objects.create(
                user=request.user,
                action='CREATE',
                app_name='public_accounts',
                model_name='PublicUser',
                object_id=str(user.id),
                description=f'Created user: {user.identifier}',
                ip_address=get_client_ip(request)
            )

            messages.success(
                request,
                f'User created successfully! Identifier: {user.identifier}'
            )
            return redirect('public_accounts:user_list')
    else:
        form = PublicUserCreationForm()

    return render(request, 'public_admin/user_form.html', {
        'form': form,
        'title': 'Create New User',
        'action': 'Create'
    })


@login_required(login_url='public_accounts:login')
def user_edit_view(request, user_id):
    """Edit public user (superuser only)"""
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('public_accounts:public_admin_index')

    user = get_object_or_404(PublicUser, id=user_id)

    if request.method == 'POST':
        form = PublicUserChangeForm(request.POST, request.FILES, instance=user)
        if form.is_valid():
            form.save()

            # Log activity
            PublicUserActivity.objects.create(
                user=request.user,
                action='UPDATE',
                app_name='public_accounts',
                model_name='PublicUser',
                object_id=str(user.id),
                description=f'Updated user: {user.identifier}',
                ip_address=get_client_ip(request)
            )

            messages.success(request, 'User updated successfully.')
            return redirect('public_accounts:user_list')
    else:
        form = PublicUserChangeForm(instance=user)

    return render(request, 'public_admin/user_form.html', {
        'form': form,
        'user_obj': user,
        'title': 'Edit User',
        'action': 'Update'
    })


@login_required(login_url='public_accounts:login')
def user_delete_view(request, user_id):
    """Delete public user (superuser only)"""
    if not request.user.is_superuser:
        messages.error(request, 'You do not have permission to access this page.')
        return redirect('public_accounts:public_admin_index')

    user = get_object_or_404(PublicUser, id=user_id)

    if user.is_superuser:
        messages.error(request, 'Cannot delete superuser.')
        return redirect('public_accounts:user_list')

    if request.method == 'POST':
        identifier = user.identifier

        # Log activity before deletion
        PublicUserActivity.objects.create(
            user=request.user,
            action='DELETE',
            app_name='public_accounts',
            model_name='PublicUser',
            object_id=str(user.id),
            description=f'Deleted user: {identifier}',
            ip_address=get_client_ip(request)
        )

        user.delete()
        messages.success(request, f'User {identifier} deleted successfully.')
        return redirect('public_accounts:user_list')

    return render(request, 'public_admin/user_confirm_delete.html', {
        'user_obj': user,
        'title': 'Delete User'
    })