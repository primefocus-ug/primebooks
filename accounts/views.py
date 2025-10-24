from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib import messages
from django.http import  HttpResponse, Http404
from django.core.paginator import Paginator
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.core.cache import cache
from django.db.models import Count
from django.http import JsonResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse_lazy, reverse
from django.utils import timezone
from django.http import JsonResponse
from django.contrib.auth import authenticate, login
from django_otp.plugins.otp_totp.models import TOTPDevice
from django.views.decorators.csrf import csrf_exempt
import io, pyotp, qrcode
from allauth.socialaccount.models import SocialAccount
from allauth.account.views import LoginView as AllauthLoginView, LogoutView as AllauthLogoutView
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView, FormView
)
from django.views.decorators.http import require_http_methods, require_POST
from django.core.mail import send_mail
from django.conf import settings
import qrcode
from django.contrib.auth import logout
from django.template.loader import render_to_string
from django.contrib.sessions.models import Session
from django.db.models import Q
import json
import secrets
import zipfile
from io import BytesIO
from datetime import datetime
from .utils import (
    get_visible_users,
    get_company_user_count,
    can_access_company,
    get_accessible_companies,
    require_saas_admin,
    require_company_access
)



# Models for API tokens and sessions
from django.db import models

# For PDF generation
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor

# For Excel export
import openpyxl
from openpyxl.styles import Font, PatternFill

# For CSV export
import csv
from datetime import timedelta
import logging
from .models import CustomUser, UserSignature,Role, RoleHistory
from company.models import Company, SubscriptionPlan
from .forms import (
    CustomUserCreationForm, CustomUserChangeForm, CustomAuthenticationForm,UserRoleAssignForm,
    UserProfileForm, PasswordChangeForm, UserSignatureForm, UserSearchForm,
    BulkUserActionForm, TwoFactorSetupForm,RoleForm, BulkRoleAssignmentForm,BulkUserRoleAssignForm, RoleFilterForm
)

logger = logging.getLogger(__name__)

DASHBOARD_MAPPING = [
    {'permission': 'accounts.view_customuser', 'url_name': 'user_dashboard'},
    {'permission': 'company.view_company', 'url_name': 'dashboard'},
    {'permission': 'stores.view_product', 'url_name': 'stores:dashboard'},
    {'permission': 'inventory.view_product', 'url_name': 'inventory:dashboard'},
    {'permission': 'reports.view_savedreport', 'url_name': 'reports:dashboard'},
]


def get_dashboard_url(user):
    """Return the correct dashboard URL for the user."""
    # SaaS admins get special dashboard
    if getattr(user, 'is_saas_admin', False):
        return reverse('saas_admin_dashboard')

    # Super admins and company admins → company detail
    if getattr(user, 'is_superuser', False) or getattr(user, 'company_admin', False):
        if hasattr(user, 'company') and user.company:  # user must be linked to a company
            return reverse('companies:company_detail', kwargs={'company_id': user.company.company_id})

    # Other roles → pick from mapping
    for item in DASHBOARD_MAPPING:
        if user.has_perm(item['permission']):
            return reverse(item['url_name'])

    return reverse('no_access')


def custom_login(request):
    """Enhanced login view with Google OAuth and 2FA support."""
    if request.user.is_authenticated:
        return redirect(get_dashboard_url(request.user))

    form = CustomAuthenticationForm(request, data=request.POST or None)

    if request.method == 'POST':
        # Handle AJAX requests
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            if not form.is_valid():
                logger.error(f"Form validation failed: {form.errors}")
                return JsonResponse({
                    'success': False,
                    'error': 'Please correct the errors below',
                    'form_errors': form.errors.as_json()
                }, status=400)

            user = form.get_user()

            # 2FA logic
            two_factor_enabled = TOTPDevice.objects.filter(user=user, confirmed=True).exists()
            code = form.cleaned_data.get('code')

            if two_factor_enabled and not code:
                logger.debug(f"2FA required for user: {user.email}")
                return JsonResponse({
                    'success': True,
                    'two_factor_enabled': True,
                    'message': 'Please enter your 2FA code'
                })

            if two_factor_enabled and code:
                try:
                    device = TOTPDevice.objects.get(user=user, confirmed=True)
                    if device.verify_token(code):
                        login(request, user)
                        if form.cleaned_data.get('remember_me'):
                            request.session.set_expiry(60 * 60 * 24 * 30)  # 30 days
                        else:
                            request.session.set_expiry(0)

                        next_url = request.GET.get('next') or get_dashboard_url(user)
                        message = (
                            f'Welcome SaaS Admin: {user.get_short_name()}!'
                            if getattr(user, 'is_saas_admin', False)
                            else f'Welcome back, {user.get_short_name()}!'
                        )
                        logger.info(f"Successful 2FA login for user: {user.email}")
                        return JsonResponse({
                            'success': True,
                            'two_factor_enabled': False,
                            'message': message,
                            'redirect_url': next_url
                        })
                    else:
                        logger.error(f"Invalid 2FA code for user: {user.email}")
                        return JsonResponse({
                            'success': False,
                            'error': 'Invalid 2FA code'
                        }, status=401)
                except TOTPDevice.DoesNotExist:
                    logger.error(f"No confirmed TOTP device for user: {user.email}")
                    return JsonResponse({
                        'success': False,
                        'error': '2FA device not found'
                    }, status=500)

            # No 2FA, proceed with login
            login(request, user)
            if form.cleaned_data.get('remember_me'):
                request.session.set_expiry(60 * 60 * 24 * 30)
            else:
                request.session.set_expiry(0)

            next_url = request.GET.get('next') or get_dashboard_url(user)
            message = (
                f'Welcome SaaS Admin: {user.get_short_name()}!'
                if getattr(user, 'is_saas_admin', False)
                else f'Welcome back, {user.get_short_name()}!'
            )
            logger.info(f"Successful login (no 2FA) for user: {user.email}")
            return JsonResponse({
                'success': True,
                'two_factor_enabled': False,
                'message': message,
                'redirect_url': next_url
            })

        else:
            # Non-AJAX POST
            if form.is_valid():
                user = form.get_user()
                login(request, user)
                if form.cleaned_data.get('remember_me'):
                    request.session.set_expiry(60 * 60 * 24 * 30)
                else:
                    request.session.set_expiry(0)

                if getattr(user, 'is_saas_admin', False):
                    messages.success(request, f'Welcome SaaS Admin: {user.get_short_name()}!')
                else:
                    messages.success(request, f'Welcome back, {user.get_short_name()}!')

                next_url = request.GET.get('next') or get_dashboard_url(user)
                return redirect(next_url)
            else:
                messages.error(request, 'Please correct the errors below.')

    # GET request or failed POST
    context = {
        'form': form,
        'show_google_login': True,
    }
    return render(request, 'accounts/login.html', context)


def social_login_callback(request):
    """
    Callback handler after successful social login.
    This ensures proper session setup and redirects.
    """
    if not request.user.is_authenticated:
        messages.error(request, 'Social login failed. Please try again.')
        return redirect('account_login')

    user = request.user

    # Record the login
    client_ip = get_client_ip(request)
    user.record_login_attempt(success=True, ip_address=client_ip)

    # Update last activity
    user.last_activity_at = timezone.now()
    user.save(update_fields=['last_activity_at'])

    # Check if this is the user's first login (from social account)
    social_account = SocialAccount.objects.filter(user=user).first()
    if social_account and not user.last_login:
        messages.success(
            request,
            f'Welcome to PrimeBooks! Your account has been created using {social_account.provider.title()}.'
        )
    else:
        messages.success(request, f'Welcome back, {user.get_short_name()}!')

    # Determine redirect URL
    next_url = request.GET.get('next') or request.session.get('social_login_next') or get_dashboard_url(user)

    # Clear the session variable if it exists
    if 'social_login_next' in request.session:
        del request.session['social_login_next']

    return redirect(next_url)


def custom_logout(request):
    """Enhanced logout view compatible with allauth"""
    user_name = request.user.get_short_name() if request.user.is_authenticated else None

    if request.user.is_authenticated:
        # Update last activity
        request.user.last_activity_at = timezone.now()
        request.user.save(update_fields=['last_activity_at'])

    logout(request)

    if user_name:
        messages.info(request, f'Goodbye, {user_name}! You have been logged out.')

    return redirect('account_login')


@require_http_methods(["GET"])
def check_social_account(request):
    """
    AJAX endpoint to check if an email is associated with a social account.
    Useful for providing better UX on the login page.
    """
    email = request.GET.get('email', '').strip()

    if not email:
        return JsonResponse({'error': 'Email is required'}, status=400)

    # Check if user exists
    try:
        user = CustomUser.objects.get(email=email)
        social_accounts = SocialAccount.objects.filter(user=user)

        if social_accounts.exists():
            providers = [sa.provider for sa in social_accounts]
            return JsonResponse({
                'exists': True,
                'has_social': True,
                'providers': providers,
                'message': f'This email is linked with {", ".join(providers)}. You can sign in using those providers.'
            })
        else:
            return JsonResponse({
                'exists': True,
                'has_social': False,
                'message': 'Please enter your password to sign in.'
            })
    except CustomUser.DoesNotExist:
        return JsonResponse({
            'exists': False,
            'message': 'No account found with this email. You can sign up using Google or create a new account.'
        })


@login_required
def manage_social_connections(request):
    """
    View to manage connected social accounts
    """
    if request.method == 'POST':
        action = request.POST.get('action')
        provider = request.POST.get('provider')

        if action == 'disconnect':
            try:
                social_account = SocialAccount.objects.get(
                    user=request.user,
                    provider=provider
                )

                # Check if user has password or other login method
                if not request.user.has_usable_password():
                    other_accounts = SocialAccount.objects.filter(
                        user=request.user
                    ).exclude(id=social_account.id)

                    if not other_accounts.exists():
                        messages.error(
                            request,
                            'Cannot disconnect this account as it is your only login method. '
                            'Please set a password first.'
                        )
                        return redirect('manage_social_connections')

                social_account.delete()
                messages.success(request, f'{provider.title()} account disconnected successfully!')

            except SocialAccount.DoesNotExist:
                messages.error(request, f'No {provider.title()} account found.')

        return redirect('manage_social_connections')

    # Get user's social accounts
    social_accounts = SocialAccount.objects.filter(user=request.user)

    # Available providers
    available_providers = {
        'google': {
            'name': 'Google',
            'icon': 'bi-google',
            'connected': social_accounts.filter(provider='google').exists()
        },
        # Add more providers as needed
    }

    context = {
        'social_accounts': social_accounts,
        'available_providers': available_providers,
        'has_password': request.user.has_usable_password(),
    }

    return render(request, 'accounts/manage_social_connections.html', context)


@login_required
def set_password_after_social_login(request):
    """
    Allow users who signed up via social login to set a password
    """
    # Check if user already has a password
    if request.user.has_usable_password():
        messages.info(request, 'You already have a password set.')
        return redirect('user_profile')

    if request.method == 'POST':
        password1 = request.POST.get('password1')
        password2 = request.POST.get('password2')

        if password1 != password2:
            messages.error(request, 'Passwords do not match.')
        elif len(password1) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
        else:
            request.user.set_password(password1)
            request.user.password_changed_at = timezone.now()
            request.user.save()

            # Update session to prevent logout
            update_session_auth_hash(request, request.user)

            messages.success(
                request,
                'Password set successfully! You can now sign in using your email and password.'
            )
            return redirect('user_profile')

    context = {
        'user': request.user,
        'social_accounts': SocialAccount.objects.filter(user=request.user),
    }

    return render(request, 'accounts/set_password_after_social.html', context)


@require_saas_admin
def saas_admin_dashboard(request):
    """Dashboard specifically for SaaS administrators"""
    from company.models import Company, SubscriptionPlan

    # Global statistics across all tenants
    total_companies = Company.objects.count()
    active_companies = Company.objects.filter(status='ACTIVE').count() if hasattr(Company,
                                                                                  'status') else Company.objects.count()
    trial_companies = Company.objects.filter(is_trial=True).count() if hasattr(Company, 'is_trial') else 0

    # User statistics - use visible users to get accurate counts
    total_users = get_visible_users().count()
    active_users = get_visible_users().filter(is_active=True).count()

    # Recent activity
    recent_companies = Company.objects.order_by('-created_at')[:10]
    recent_users = get_visible_users().order_by('-date_joined')[:10]

    # Plan distribution
    plan_stats = []
    if hasattr(Company, 'plan'):
        plan_stats = list(
            Company.objects.values('plan__name', 'plan__display_name')
            .annotate(count=Count('company_id'))
            .order_by('-count')
        )

    # Companies expiring soon
    expiring_soon = []
    if hasattr(Company, 'subscription_ends_at'):
        expiring_soon = Company.objects.filter(
            subscription_ends_at__lte=timezone.now().date() + timedelta(days=30),
            subscription_ends_at__gte=timezone.now().date()
        ).order_by('subscription_ends_at')[:10]

    # SaaS-specific metrics
    context = {
        'total_companies': total_companies,
        'active_companies': active_companies,
        'trial_companies': trial_companies,
        'total_users': total_users,
        'active_users': active_users,
        'recent_companies': recent_companies,
        'recent_users': recent_users,
        'plan_stats': plan_stats,
        'expiring_soon': expiring_soon,
        'accessible_companies': get_accessible_companies(request.user),
        'is_saas_admin': True,
    }

    return render(request, 'accounts/saas_admin_dashboard.html', context)


class RolePermissionMixin(PermissionRequiredMixin):
    """Base mixin for role management permissions"""
    permission_required = 'auth.view_group'

    def handle_no_permission(self):
        messages.error(
            self.request,
            "You don't have permission to access role management."
        )
        return super().handle_no_permission()


class RoleListView(LoginRequiredMixin, RolePermissionMixin, ListView):
    """
    Advanced role listing with search, filtering, and analytics
    """
    model = Role
    template_name = 'accounts/roles/role_list.html'
    context_object_name = 'roles'
    paginate_by = 20

    def get_queryset(self):
        queryset = Role.objects.select_related('group', 'company', 'created_by') \
            .prefetch_related('group__permissions', 'group__user')

        form = RoleFilterForm(self.request.GET)
        if form.is_valid():
            search = form.cleaned_data.get('search')
            company = form.cleaned_data.get('company')
            is_system_role = form.cleaned_data.get('is_system_role')
            is_active = form.cleaned_data.get('is_active')

            if search:
                queryset = queryset.filter(
                    Q(group__name__icontains=search) |
                    Q(description__icontains=search)
                )

            if company:
                queryset = queryset.filter(Q(company=company) | Q(company__isnull=True))

            if is_system_role is not None:
                queryset = queryset.filter(is_system_role=(is_system_role == 'true'))

            if is_active is not None:
                queryset = queryset.filter(is_active=(is_active == 'true'))

        return queryset.order_by('-priority', 'group__name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add filter form
        context['filter_form'] = RoleFilterForm(self.request.GET)

        # Add analytics data
        total_roles = Role.objects.count()
        system_roles = Role.objects.filter(is_system_role=True).count()
        active_roles = Role.objects.filter(is_active=True).count()

        context.update({
            'total_roles': total_roles,
            'system_roles': system_roles,
            'custom_roles': total_roles - system_roles,
            'active_roles': active_roles,
            'inactive_roles': total_roles - active_roles,
            'can_create_role': self.request.user.has_perm('auth.add_group'),
            'can_manage_system_roles': (
                self.request.user.has_perm('accounts.can_manage_system_roles') or
                self.request.user.is_superuser
            )
        })

        return context

class RoleDetailView(LoginRequiredMixin, RolePermissionMixin, DetailView):
    model = Role
    template_name = 'accounts/roles/role_detail.html'
    context_object_name = 'role'

    def get_queryset(self):
        return Role.objects.select_related(
            'group', 'company', 'created_by'
        ).prefetch_related(
            'group__permissions__content_type',
            'history__user'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role = self.object

        # Users with this role — select related company instead of non-existent profile
        users_with_role = role.group.user_set.select_related('company').all()

        permission_groups = role.get_permission_groups()
        recent_history = role.history.select_related('user')[:10]

        capacity_info = {
            'current': role.user_count,
            'maximum': role.max_users,
            'percentage': role.capacity_percentage,
            'is_at_capacity': role.is_at_capacity,
            'can_assign': role.can_assign_to_user()[0]
        }

        context.update({
            'users_with_role': users_with_role,
            'permission_groups': permission_groups,
            'recent_history': recent_history,
            'capacity_info': capacity_info,
            'can_edit': self.request.user.has_perm('auth.change_group'),
            'can_delete': (
                self.request.user.has_perm('auth.delete_group') and
                not role.is_system_role
            ),
        })
        return context


class UserRoleAssignView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    """Bulk assign multiple users to a role"""
    template_name = 'accounts/roles/assign_users.html'
    form_class = BulkUserRoleAssignForm
    permission_required = 'accounts.can_manage_users'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.request.user.company
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.request.user.company

        # Get all roles with user counts
        context['roles'] = Role.objects.filter(
            Q(company=company) | Q(company__isnull=True, is_system_role=True)
        ).select_related('group').annotate(
            total_users=Count('group__user')
        ).order_by('-priority', 'group__name')

        # Get all available users
        context['available_users'] = CustomUser.objects.filter(
            company=company,
            is_hidden=False,
            is_active=True
        ).select_related('company').order_by('first_name', 'last_name')

        # Get statistics
        context['total_users'] = context['available_users'].count()
        context['total_roles'] = context['roles'].count()

        return context

    def form_valid(self, form):
        users = form.cleaned_data['users']
        role = form.cleaned_data['role']

        # Check role capacity
        if role.max_users:
            current_count = role.user_count
            new_count = current_count + users.count()

            if new_count > role.max_users:
                messages.error(
                    self.request,
                    f"Cannot assign {users.count()} users. Role '{role.group.name}' "
                    f"has capacity for only {role.max_users - current_count} more users."
                )
                return self.form_invalid(form)

        # Assign users to role
        success_count = 0
        already_assigned = []

        for user in users:
            if not user.groups.filter(pk=role.group.pk).exists():
                role.group.user_set.add(user)
                success_count += 1
            else:
                already_assigned.append(user.get_full_name())

        # Success message
        if success_count > 0:
            messages.success(
                self.request,
                f"Successfully assigned {success_count} user(s) to role '{role.group.name}'."
            )

        # Warning for already assigned users
        if already_assigned:
            messages.warning(
                self.request,
                f"{len(already_assigned)} user(s) were already in this role: {', '.join(already_assigned[:3])}"
                + ("..." if len(already_assigned) > 3 else "")
            )

        # Record history if you have RoleHistory model
        try:
            from .models import RoleHistory
            RoleHistory.objects.create(
                role=role,
                action='permissions_changed',
                user=self.request.user,
                changes={
                    'action': 'bulk_user_assignment',
                    'users_added': success_count,
                    'user_ids': [u.id for u in users]
                },
                notes=f"Bulk assigned {success_count} users"
            )
        except:
            pass

        return redirect('role_detail', pk=role.pk)

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Please correct the errors below."
        )
        return super().form_invalid(form)

class RoleCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """
    Advanced role creation with enhanced form handling
    """
    model = Role
    form_class = RoleForm
    template_name = 'accounts/roles/role_form.html'
    permission_required = 'auth.add_group'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            'title': 'Create New Role',
            'submit_text': 'Create Role',
            'breadcrumb_title': 'Create Role'
        })
        return context

    def form_valid(self, form):
        messages.success(
            self.request,
            f'Role "{form.cleaned_data["name"]}" has been created successfully.'
        )
        return super().form_valid(form)

    def form_invalid(self, form):
        messages.error(
            self.request,
            'Please correct the errors below and try again.'
        )
        return super().form_invalid(form)


class RoleUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """
    Advanced role editing with change tracking
    """
    model = Role
    form_class = RoleForm
    template_name = 'accounts/roles/role_form.html'
    permission_required = 'auth.change_group'

    def dispatch(self, request, *args, **kwargs):
        # Prevent editing system roles unless user has special permission
        role = self.get_object()
        if (role.is_system_role and
                not request.user.has_perm('accounts.can_manage_system_roles') and
                not request.user.is_superuser):
            messages.error(
                request,
                "You don't have permission to edit system roles."
            )
            return HttpResponseRedirect(reverse('role_detail', kwargs={'pk': role.pk}))

        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role = self.object
        context.update({
            'title': f'Edit Role: {role.group.name}',
            'submit_text': 'Update Role',
            'breadcrumb_title': f'Edit {role.group.name}',
            'role': role
        })
        return context

    def form_valid(self, form):
        messages.success(
            self.request,
            f'Role "{self.object.group.name}" has been updated successfully.'
        )
        return super().form_valid(form)


class RoleDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    """
    Safe role deletion with confirmation and validation
    """
    model = Role
    template_name = 'accounts/roles/role_confirm_delete.html'
    success_url = reverse_lazy('role_list')
    permission_required = 'auth.delete_group'

    def dispatch(self, request, *args, **kwargs):
        role = self.get_object()

        # Prevent deletion of system roles
        if role.is_system_role:
            messages.error(request, "System roles cannot be deleted.")
            return HttpResponseRedirect(reverse('role_detail', kwargs={'pk': role.pk}))

        # Check if role has users assigned
        if role.user_count > 0:
            messages.warning(
                request,
                f"Cannot delete role '{role.group.name}' because {role.user_count} "
                f"user(s) are assigned to it. Please reassign these users first."
            )
            return HttpResponseRedirect(reverse('role_detail', kwargs={'pk': role.pk}))

        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        role = self.get_object()
        role_name = role.group.name

        # Create history record before deletion
        RoleHistory.objects.create(
            role=role,
            action='deleted',
            user=request.user,
            notes=f"Role deleted via web interface"
        )

        # Delete the underlying group (will cascade to role)
        role.group.delete()

        messages.success(
            request,
            f'Role "{role_name}" has been deleted successfully.'
        )

        return HttpResponseRedirect(self.success_url)


class RoleBulkAssignmentView(LoginRequiredMixin, PermissionRequiredMixin, FormView):
    """
    Bulk role assignment functionality
    """
    form_class = BulkRoleAssignmentForm
    template_name = 'accounts/roles/bulk_assignment.html'
    permission_required = 'accounts.can_bulk_assign_roles'
    success_url = reverse_lazy('role_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # If user has limited company access, pass it to form
        if not self.request.user.is_superuser:
            # Assuming user has a company field or related companies
            kwargs['company'] = getattr(self.request.user, 'company', None)
        return kwargs

    def form_valid(self, form):
        users = form.cleaned_data['users']
        role = form.cleaned_data['role']
        action = form.cleaned_data['action']

        success_count = 0
        error_count = 0

        for user in users:
            try:
                if action == 'add':
                    if not user.groups.filter(pk=role.group.pk).exists():
                        user.groups.add(role.group)
                        success_count += 1
                elif action == 'remove':
                    if user.groups.filter(pk=role.group.pk).exists():
                        user.groups.remove(role.group)
                        success_count += 1
                elif action == 'replace':
                    user.groups.clear()
                    user.groups.add(role.group)
                    success_count += 1
            except Exception:
                error_count += 1

        # Create history records
        RoleHistory.objects.create(
            role=role,
            action='permissions_changed',
            user=self.request.user,
            changes={
                'bulk_action': action,
                'users_affected': success_count,
                'errors': error_count
            },
            notes=f"Bulk {action} operation via web interface"
        )

        if success_count > 0:
            messages.success(
                self.request,
                f'Successfully {action}ed role "{role.group.name}" for {success_count} user(s).'
            )

        if error_count > 0:
            messages.warning(
                self.request,
                f'Failed to process {error_count} user(s) due to errors.'
            )

        return super().form_valid(form)


class RoleAnalyticsView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """
    Role analytics and reporting with charts and insights
    """
    model = Role
    template_name = 'accounts/roles/role_analytics.html'
    permission_required = 'accounts.can_view_role_analytics'
    context_object_name = 'role'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role = self.object

        # Date ranges
        thirty_days_ago = timezone.now() - timedelta(days=30)
        seven_days_ago = timezone.now() - timedelta(days=7)

        # Get history data for charts
        history_data = role.history.filter(
            timestamp__gte=thirty_days_ago
        ).values('action', 'timestamp').order_by('timestamp')

        # Count actions by type
        action_counts = {}
        for entry in history_data:
            action = entry['action']
            action_counts[action] = action_counts.get(action, 0) + 1

        # Recent activity (last 7 days)
        recent_history = role.history.filter(
            timestamp__gte=seven_days_ago
        ).select_related('user').order_by('-timestamp')[:10]

        # Permission usage analytics
        permissions_by_app = role.get_permission_groups()

        # Calculate permission distribution
        permission_stats = {
            app: {
                'total': len(perms),
                'view': sum(1 for p in perms if 'view' in p.codename),
                'add': sum(1 for p in perms if 'add' in p.codename),
                'change': sum(1 for p in perms if 'change' in p.codename),
                'delete': sum(1 for p in perms if 'delete' in p.codename),
            }
            for app, perms in permissions_by_app.items()
        }

        # Users with this role grouped by company (if applicable)
        users_by_company = {}
        if role.company:
            users_by_company[role.company.name] = role.user_count
        else:
            # Group users by their companies for system roles
            from django.contrib.auth import get_user_model
            User = get_user_model()

            users_with_role = User.objects.filter(
                groups=role.group,
                is_hidden=False
            ).select_related('company')

            for user in users_with_role:
                company_name = user.company.name if user.company else 'No Company'
                users_by_company[company_name] = users_by_company.get(company_name, 0) + 1

        # User activity analysis
        active_users_count = role.group.user_set.filter(
            is_active=True,
            is_hidden=False
        ).count()

        context.update({
            'history_data': list(history_data),
            'action_counts': action_counts,
            'recent_history': recent_history,
            'permissions_by_app': permissions_by_app,
            'permission_stats': permission_stats,
            'users_by_company': users_by_company,
            'active_users_count': active_users_count,
            'inactive_users_count': role.user_count - active_users_count,
            'capacity_usage': {
                'current': role.user_count,
                'maximum': role.max_users or 'Unlimited',
                'percentage': role.capacity_percentage,
                'available': (role.max_users - role.user_count) if role.max_users else 'Unlimited'
            },
            'timeline_days': 30,
        })

        return context


class RoleHistoryView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """
    Role change history listing with filters
    """
    model = RoleHistory
    template_name = 'accounts/roles/role_history.html'
    context_object_name = 'history_entries'
    paginate_by = 50
    permission_required = 'accounts.can_manage_users'

    def get_queryset(self):
        role_pk = self.kwargs.get('pk')
        queryset = RoleHistory.objects.select_related('role__group', 'user')

        if role_pk:
            # History for specific role
            queryset = queryset.filter(role_id=role_pk)

        # Filter by action if provided
        action = self.request.GET.get('action')
        if action:
            queryset = queryset.filter(action=action)

        # Filter by date range
        days = self.request.GET.get('days', 30)
        if days != 'all':
            try:
                days_ago = timezone.now() - timedelta(days=int(days))
                queryset = queryset.filter(timestamp__gte=days_ago)
            except ValueError:
                pass

        return queryset.order_by('-timestamp')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        role_pk = self.kwargs.get('pk')

        if role_pk:
            role = get_object_or_404(Role, pk=role_pk)
            context.update({
                'role': role,
                'title': f'History for {role.group.name}',
                'breadcrumb_title': f'{role.group.name} History'
            })
        else:
            context.update({
                'title': 'All Role Changes',
                'breadcrumb_title': 'Role History'
            })

        # Get available actions for filter
        context['available_actions'] = RoleHistory.ACTION_CHOICES
        context['current_action'] = self.request.GET.get('action', '')
        context['current_days'] = self.request.GET.get('days', '30')

        return context


class RoleToggleActiveView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """
    Toggle role active status via AJAX
    """
    model = Role
    permission_required = 'accounts.can_manage_users'

    def post(self, request, *args, **kwargs):
        role = self.get_object()

        # Check if user can modify this role
        if role.company and role.company != request.user.company:
            return JsonResponse({
                'success': False,
                'message': 'You do not have permission to modify this role'
            }, status=403)

        # Don't allow deactivating system roles with users
        if role.is_active and role.is_system_role and role.user_count > 0:
            return JsonResponse({
                'success': False,
                'message': 'Cannot deactivate system role with assigned users. Remove users first.'
            }, status=400)

        # Toggle active status
        old_status = role.is_active
        role.is_active = not role.is_active
        role.save()

        # Create history record
        action = 'activated' if role.is_active else 'deactivated'
        RoleHistory.objects.create(
            role=role,
            action=action,
            user=request.user,
            changes={
                'old_status': old_status,
                'new_status': role.is_active
            },
            notes=f"Role {action} via web interface"
        )

        return JsonResponse({
            'success': True,
            'is_active': role.is_active,
            'message': f'Role "{role.group.name}" has been {"activated" if role.is_active else "deactivated"}'
        })


class RolePermissionsAPIView(LoginRequiredMixin, DetailView):
    """
    API endpoint for role permissions (used by frontend)
    """
    model = Role

    def get(self, request, *args, **kwargs):
        role = self.get_object()

        # Check access
        if role.company and role.company != request.user.company:
            return JsonResponse({
                'error': 'Access denied'
            }, status=403)

        permissions_data = {}
        for app_name, permissions in role.get_permission_groups().items():
            permissions_data[app_name] = [
                {
                    'id': perm.id,
                    'name': perm.name,
                    'codename': perm.codename,
                    'content_type': perm.content_type.model,
                    'action': perm.codename.split('_')[0]  # add, change, delete, view
                }
                for perm in permissions
            ]

        return JsonResponse({
            'role_id': role.id,
            'role_name': role.group.name,
            'description': role.description or '',
            'is_system_role': role.is_system_role,
            'is_active': role.is_active,
            'permissions': permissions_data,
            'total_permissions': role.permission_count,
            'user_count': role.user_count
        })


class RoleAutocompleteView(LoginRequiredMixin, ListView):
    """
    Autocomplete API for role selection (for Select2, etc.)
    """
    model = Role

    def get_queryset(self):
        query = self.request.GET.get('q', '')
        company = self.request.user.company

        queryset = Role.objects.filter(
            Q(company=company) | Q(is_system_role=True),
            is_active=True
        ).select_related('group')

        if query:
            queryset = queryset.filter(
                Q(group__name__icontains=query) |
                Q(description__icontains=query)
            )

        return queryset.order_by('-priority', 'group__name')[:10]  # Limit results

    def render_to_response(self, context):
        roles_data = [
            {
                'id': role.id,
                'text': role.group.name,
                'description': role.description or '',
                'is_system': role.is_system_role,
                'user_count': role.user_count,
                'color': role.color_code,
                'capacity': {
                    'current': role.user_count,
                    'max': role.max_users,
                    'available': (role.max_users - role.user_count) if role.max_users else None
                }
            }
            for role in context['object_list']
        ]

        return JsonResponse({
            'results': roles_data,
            'pagination': {
                'more': False
            }
        })


class RoleCompareView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """
    Compare permissions between multiple roles
    """
    model = Role
    template_name = 'accounts/roles/role_compare.html'
    permission_required = 'accounts.can_manage_users'

    def get_queryset(self):
        role_ids = self.request.GET.getlist('roles')
        company = self.request.user.company

        return Role.objects.filter(
            Q(id__in=role_ids),
            Q(company=company) | Q(is_system_role=True)
        ).select_related('group').prefetch_related('group__permissions')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        roles = list(context['object_list'])

        if not roles:
            context['error'] = 'Please select at least one role to compare'
            return context

        # Get all permissions from all roles
        all_permissions = set()
        role_permissions = {}

        for role in roles:
            perms = set(role.group.permissions.all())
            role_permissions[role.id] = perms
            all_permissions.update(perms)

        # Group permissions by app and model
        from collections import defaultdict
        permission_matrix = defaultdict(lambda: defaultdict(dict))

        for perm in all_permissions:
            app = perm.content_type.app_label
            model = perm.content_type.model
            action = perm.codename.split('_')[0]

            for role in roles:
                has_perm = perm in role_permissions[role.id]
                if role.id not in permission_matrix[app][model]:
                    permission_matrix[app][model][role.id] = {}
                permission_matrix[app][model][role.id][action] = has_perm

        context['roles'] = roles
        context['permission_matrix'] = dict(permission_matrix)

        return context


@login_required
@permission_required('accounts.view_customuser', raise_exception=True)
def user_dashboard(request):
    """Enhanced user dashboard with SaaS admin support"""
    user = request.user

    # Basic user statistics
    context = {
        'user': user,
        'total_login_count': user.login_count,
        'last_login_ip': user.last_login_ip,
        'account_age': (timezone.now() - user.date_joined).days,
        'is_locked': user.is_locked,
        'two_factor_enabled': user.two_factor_enabled,
        'email_verified': user.email_verified,
        'phone_verified': user.phone_verified,
        'is_saas_admin': getattr(user, 'is_saas_admin', False),
    }

    # Handle company context for different user types
    if getattr(user, 'is_saas_admin', False):
        # SaaS admin can see all companies
        accessible_companies = get_accessible_companies(user)
        context.update({
            'accessible_companies': accessible_companies,
            'can_switch_companies': True,
            'company_count': accessible_companies.count(),
        })
    else:
        # Regular user logic
        owned_company = getattr(user, 'owned_company', None)
        user_company = getattr(user, 'company', None)

        company_memberships = []
        if user_company and user_company.is_active:
            company_memberships = [user_company]

        context.update({
            'owned_company': owned_company,
            'company_memberships': company_memberships,
            'is_system_admin': user.user_type == 'SYSTEM_ADMIN',
        })

    # Add admin statistics if user has permissions
    if user.has_perm('accounts.can_manage_users') or getattr(user, 'is_saas_admin', False):
        accessible_users = _get_accessible_users(user)
        user_stats = {
            'total': accessible_users.filter(is_hidden=False).count(),
            'active': accessible_users.filter(is_active=True, is_hidden=False).count(),
            'new_today': accessible_users.filter(is_hidden=False,date_joined__date=timezone.now().date()).count(),
            'locked': accessible_users.filter(is_hidden=False,locked_until__gt=timezone.now()).count(),
        }
        context['user_stats'] = user_stats

    return render(request, 'accounts/analytics.html', context)


@login_required
@permission_required('accounts.view_customuser', raise_exception=True)
def company_user_list(request, company_id):
    """List users for a specific company with SaaS admin support"""
    logger.debug("Entered company_user_list view")
    logger.debug("Request user: %s (ID=%s)", request.user, request.user.id)

    try:
        company = get_object_or_404(Company, id=company_id)
        logger.debug("Company found: %s (ID=%s)", company, company.id)
    except Exception as e:
        logger.error("Error fetching company with id=%s: %s", company_id, e, exc_info=True)
        raise

    # Check if user has access to this company (includes SaaS admin check)
    if not can_access_company(request.user, company):
        logger.warning("Permission denied for user %s on company %s", request.user, company)
        raise PermissionDenied("You don't have access to this company.")

    logger.debug("User %s has access to company %s", request.user, company)

    # Query company users - use visible users to exclude hidden SaaS admins
    if getattr(request.user, 'is_saas_admin', False):
        # SaaS admin can see all users in the company
        company_users = CustomUser.objects.filter(company=company).order_by('-date_joined')
    else:
        # Regular users see only visible users
        company_users = get_visible_users().filter(company=company).order_by('-date_joined')

    logger.debug("Initial company_users count: %s", company_users.count())

    # Apply search filter
    search_query = request.GET.get('search', '')
    if search_query:
        logger.debug("Search query received: %s", search_query)
        company_users = company_users.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(email__icontains=search_query) |
            Q(username__icontains=search_query)
        )
        logger.debug("Filtered company_users count: %s", company_users.count())

    # Pagination
    paginator = Paginator(company_users, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Check if can add users (use proper user count)
    can_add_users = False
    if hasattr(company, "can_add_employee"):
        try:
            can_add_users = company.can_add_employee()
        except Exception as e:
            logger.error("Error calling company.can_add_employee(): %s", e, exc_info=True)

    context = {
        'company': company,
        'company_users': page_obj,
        'search_query': search_query,
        'can_add_users': can_add_users,
        'is_saas_admin': getattr(request.user, 'is_saas_admin', False),
        'visible_user_count': get_company_user_count(company),  # Accurate count
    }

    return render(request, 'accounts/company_user_list.html', context)


@login_required
@permission_required('accounts.add_customuser')
def assign_user_to_company(request, company_id):
    """Assign existing user to company or create new user"""
    company = get_object_or_404(Company, id=company_id)

    # Check if user has access to this company
    if not _user_has_company_access(request.user, company):
        raise PermissionDenied

    # Check if company can add more users
    if hasattr(company, 'can_add_employee') and not company.can_add_employee():
        messages.error(request, f'Company has reached the maximum user limit.')
        return redirect('company_user_list', company_id=company_id)

    if request.method == 'POST':
        user_email = request.POST.get('user_email')
        is_admin = request.POST.get('is_admin') == 'on'

        try:
            user = CustomUser.objects.get(email=user_email)

            # Check if user is already assigned to this company
            if company in user.companies.all():
                messages.error(request, f'User {user.get_full_name()} is already assigned to this company.')
            else:
                user.companies.add(company)
                if is_admin:
                    user.company_admin_for.add(company)
                messages.success(request, f'User {user.get_full_name()} assigned to company successfully!')

        except CustomUser.DoesNotExist:
            messages.error(request, 'User with this email does not exist.')

        return redirect('company_user_list', company_id=company_id)

    # Get users not already in this company
    available_users = CustomUser.objects.exclude(
        companies=company
    ).filter(is_active=True)[:100]  # Limit for performance

    context = {
        'company': company,
        'available_users': available_users,
    }

    return render(request, 'accounts/assign_user_to_company.html', context)


@login_required
@permission_required('accounts.delete_customuser')
def remove_user_from_company(request, company_id, user_id):
    """Remove user from company"""
    company = get_object_or_404(Company, id=company_id)
    user = get_object_or_404(CustomUser, id=user_id)

    # Check if user has access to this company
    if not _user_has_company_access(request.user, company):
        raise PermissionDenied

    # Don't allow removing company owner
    if hasattr(company, 'owner') and company.owner == user:
        messages.error(request, 'Cannot remove company owner from company.')
        return redirect('company_user_list', company_id=company_id)

    # Don't allow removing self if user is the only admin
    if (request.user == user and
            user.company_admin_for.filter(id=company_id).exists() and
            company.admin_users.count() <= 1):
        messages.error(request, 'Cannot remove yourself as you are the only admin.')
        return redirect('company_user_list', company_id=company_id)

    if company in user.companies.all():
        user.companies.remove(company)
        user.company_admin_for.remove(company)
        messages.success(request, f'User {user.get_full_name()} removed from company successfully!')
    else:
        messages.error(request, 'User is not assigned to this company.')

    return redirect('company_user_list', company_id=company_id)


@login_required
@permission_required('accounts.can_manage_users')
def toggle_company_admin(request, company_id, user_id):
    """Toggle company admin status for user"""
    company = get_object_or_404(Company, id=company_id)
    user = get_object_or_404(CustomUser, id=user_id)

    # Check if user has access to this company
    if not _user_has_company_access(request.user, company):
        raise PermissionDenied

    # Don't allow removing admin status from company owner
    if hasattr(company, 'owner') and company.owner == user and company in user.company_admin_for.all():
        messages.error(request, 'Cannot remove admin status from company owner.')
        return redirect('company_user_list', company_id=company_id)

    # Don't allow removing admin status if user is the only admin
    if (company in user.company_admin_for.all() and
            company.admin_users.count() <= 1):
        messages.error(request, 'Cannot remove admin status. At least one admin is required.')
        return redirect('company_user_list', company_id=company_id)

    if company in user.company_admin_for.all():
        user.company_admin_for.remove(company)
        status = 'revoked'
    else:
        user.company_admin_for.add(company)
        status = 'granted'

    messages.success(request, f'Admin status {status} for {user.get_full_name()}.')
    return redirect('company_user_list', company_id=company_id)



def _get_accessible_users(user):
    """
    Returns a queryset of users accessible by the current user.
    SUPER_ADMIN: all users
    COMPANY_ADMIN: users in the same company
    Others: only themselves
    """
    if user.user_type == 'SUPER_ADMIN':
        return CustomUser.objects.all()
    elif user.user_type == 'COMPANY_ADMIN':
        return CustomUser.objects.filter(company=user.company)
    else:
        return CustomUser.objects.filter(id=user.id)

@login_required
@permission_required('accounts.can_view_reports')
def user_analytics(request):
    """Enhanced user analytics with proper user filtering"""
    # Get date range from request
    days = int(request.GET.get('days', 30))
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)

    # Get accessible users (properly filtered)
    accessible_users = _get_accessible_users(request.user)

    # User registration analytics
    registration_data = []
    current_date = start_date.date()
    while current_date <= end_date.date():
        count = accessible_users.filter(date_joined__date=current_date).count()
        registration_data.append({
            'date': current_date.strftime('%Y-%m-%d'),
            'count': count
        })
        current_date += timedelta(days=1)

    # User type distribution
    user_type_data = list(
        accessible_users.values('user_type')
        .annotate(count=Count('user_type'))
        .order_by('user_type')
    )

    # Active vs Inactive users
    active_inactive_data = [
        {'status': 'Active', 'count': accessible_users.filter(is_active=True).count()},
        {'status': 'Inactive', 'count': accessible_users.filter(is_active=False).count()},
    ]

    # Company distribution (for SaaS admin and SUPER_ADMIN)
    company_data = []
    is_super_admin = request.user.user_type == 'SUPER_ADMIN' or getattr(request.user, 'is_saas_admin', False)
    if is_super_admin:
        from company.models import Company
        company_data = []
        for company in Company.objects.all()[:10]:
            user_count = get_company_user_count(company)  # Use proper counting
            if user_count > 0:
                company_data.append({
                    'name': company.name,
                    'user_count': user_count
                })
        company_data.sort(key=lambda x: x['user_count'], reverse=True)

    context = {
        'registration_data': json.dumps(registration_data),
        'user_type_data': json.dumps(user_type_data),
        'active_inactive_data': json.dumps(active_inactive_data),
        'company_data': json.dumps(company_data),
        'days': days,
        'total_users': accessible_users.count(),
        'new_users_period': accessible_users.filter(date_joined__gte=start_date).count(),
        'is_super_admin': is_super_admin,
        'is_saas_admin': getattr(request.user, 'is_saas_admin', False),
    }

    return render(request, 'accounts/analytics/user_analytics.html', context)


@login_required
@permission_required('accounts.can_view_reports')
def export_analytics_data(request):
    """Export analytics data in various formats"""
    export_format = request.GET.get('format', 'pdf')
    days = int(request.GET.get('days', 30))

    # Get the same data as the analytics view
    end_date = timezone.now()
    start_date = end_date - timedelta(days=days)
    accessible_users = _get_accessible_users(request.user)

    # Prepare data
    registration_data = []
    current_date = start_date.date()
    while current_date <= end_date.date():
        count = accessible_users.filter(date_joined__date=current_date).count()
        registration_data.append({
            'date': current_date.strftime('%Y-%m-%d'),
            'count': count
        })
        current_date += timedelta(days=1)

    user_type_data = list(
        accessible_users.values('user_type')
        .annotate(count=Count('user_type'))
        .order_by('user_type')
    )

    active_inactive_data = [
        {'status': 'Active', 'count': accessible_users.filter(is_active=True).count()},
        {'status': 'Inactive', 'count': accessible_users.filter(is_active=False).count()},
    ]

    # Generate export based on format
    if export_format == 'pdf':
        return generate_pdf_report(request, {
            'registration_data': registration_data,
            'user_type_data': user_type_data,
            'active_inactive_data': active_inactive_data,
            'days': days,
            'total_users': accessible_users.count(),
            'new_users_period': accessible_users.filter(date_joined__gte=start_date).count(),
            'start_date': start_date,
            'end_date': end_date,
        })
    elif export_format == 'excel':
        return generate_excel_report(request, {
            'registration_data': registration_data,
            'user_type_data': user_type_data,
            'active_inactive_data': active_inactive_data,
            'days': days,
            'total_users': accessible_users.count(),
            'new_users_period': accessible_users.filter(date_joined__gte=start_date).count(),
        })
    elif export_format == 'csv':
        return generate_csv_report(registration_data, user_type_data, active_inactive_data)

    return JsonResponse({'error': 'Invalid format'}, status=400)


def generate_pdf_report(request, data):
    """Generate comprehensive PDF analytics report"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=18)

    # Container for the 'Flowable' objects
    elements = []

    # Get styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        spaceAfter=30,
        alignment=1,  # Center alignment
        textColor=HexColor('#667eea')
    )

    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=16,
        spaceAfter=12,
        textColor=HexColor('#4a5568')
    )

    # Title
    title = Paragraph("User Analytics Report", title_style)
    elements.append(title)

    # Report metadata
    report_info = [
        ['Report Generated:', timezone.now().strftime('%B %d, %Y at %I:%M %p')],
        ['Period:', f'Last {data["days"]} days'],
        ['Date Range:', f'{data["start_date"].strftime("%B %d, %Y")} - {data["end_date"].strftime("%B %d, %Y")}'],
        ['Generated by:', request.user.get_full_name() or request.user.username],
    ]

    info_table = Table(report_info, colWidths=[2 * inch, 3 * inch])
    info_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 20))

    # Summary Statistics
    elements.append(Paragraph("Executive Summary", heading_style))

    summary_data = [
        ['Metric', 'Value'],
        ['Total Users', f"{data['total_users']:,}"],
        ['New Users (Period)', f"{data['new_users_period']:,}"],
        ['Active Users', f"{data['active_inactive_data'][0]['count']:,}"],
        ['Inactive Users', f"{data['active_inactive_data'][1]['count']:,}"],
    ]

    summary_table = Table(summary_data, colWidths=[3 * inch, 2 * inch])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#f7fafc')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))

    # Registration Trends Chart (simplified table representation)
    elements.append(Paragraph("User Registration Trends", heading_style))

    # Group registration data by week for better readability
    weekly_data = {}
    for item in data['registration_data']:
        date_obj = timezone.datetime.strptime(item['date'], '%Y-%m-%d').date()
        week_start = date_obj - timedelta(days=date_obj.weekday())
        week_key = week_start.strftime('%b %d, %Y')

        if week_key not in weekly_data:
            weekly_data[week_key] = 0
        weekly_data[week_key] += item['count']

    reg_data = [['Week Starting', 'New Registrations']]
    for week, count in weekly_data.items():
        reg_data.append([week, str(count)])

    reg_table = Table(reg_data, colWidths=[3 * inch, 2 * inch])
    reg_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#667eea')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#f7fafc')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('ALIGN', (1, 1), (1, -1), 'RIGHT'),
    ]))
    elements.append(reg_table)
    elements.append(Spacer(1, 20))

    # User Types Distribution
    elements.append(Paragraph("User Types Distribution", heading_style))

    user_types_data = [['User Type', 'Count', 'Percentage']]
    total_typed_users = sum(item['count'] for item in data['user_type_data'])

    for item in data['user_type_data']:
        user_type = item['user_type'].replace('_', ' ').title()
        count = item['count']
        percentage = f"{(count / total_typed_users * 100):.1f}%" if total_typed_users > 0 else "0%"
        user_types_data.append([user_type, str(count), percentage])

    types_table = Table(user_types_data, colWidths=[2.5 * inch, 1.5 * inch, 1 * inch])
    types_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#10b981')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#f0fff4')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
    ]))
    elements.append(types_table)
    elements.append(Spacer(1, 20))

    # User Status Distribution
    elements.append(Paragraph("User Status Distribution", heading_style))

    status_data = [['Status', 'Count', 'Percentage']]
    total_status_users = sum(item['count'] for item in data['active_inactive_data'])

    for item in data['active_inactive_data']:
        count = item['count']
        percentage = f"{(count / total_status_users * 100):.1f}%" if total_status_users > 0 else "0%"
        status_data.append([item['status'], str(count), percentage])

    status_table = Table(status_data, colWidths=[2.5 * inch, 1.5 * inch, 1 * inch])
    status_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#f59e0b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), HexColor('#fffbeb')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 10),
        ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
    ]))
    elements.append(status_table)

    # Footer
    elements.append(Spacer(1, 40))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.grey,
        alignment=1
    )
    footer = Paragraph(
        f"Generated on {timezone.now().strftime('%B %d, %Y at %I:%M %p')} | User Analytics Report",
        footer_style
    )
    elements.append(footer)

    # Build PDF
    doc.build(elements)

    # Get the value of the BytesIO buffer and write it to the response
    pdf = buffer.getvalue()
    buffer.close()

    response = HttpResponse(content_type='application/pdf')
    response[
        'Content-Disposition'] = f'attachment; filename="user_analytics_{data["days"]}days_{timezone.now().strftime("%Y%m%d")}.pdf"'
    response.write(pdf)

    return response


def generate_excel_report(request, data):
    """Generate Excel analytics report"""
    wb = openpyxl.Workbook()

    # Remove default sheet
    wb.remove(wb.active)

    # Summary Sheet
    summary_ws = wb.create_sheet("Summary")
    summary_ws.title = "Executive Summary"

    # Headers and styling
    header_font = Font(bold=True, size=14, color="FFFFFF")
    header_fill = PatternFill(start_color="667EEA", end_color="667EEA", fill_type="solid")

    # Title
    summary_ws['A1'] = "User Analytics Report - Executive Summary"
    summary_ws['A1'].font = Font(bold=True, size=16)
    summary_ws.merge_cells('A1:B1')

    # Summary data
    summary_data = [
        ["Metric", "Value"],
        ["Total Users", data['total_users']],
        ["New Users (Period)", data['new_users_period']],
        ["Active Users", data['active_inactive_data'][0]['count']],
        ["Inactive Users", data['active_inactive_data'][1]['count']],
    ]

    for row_idx, row_data in enumerate(summary_data, start=3):
        for col_idx, value in enumerate(row_data, start=1):
            cell = summary_ws.cell(row=row_idx, column=col_idx, value=value)
            if row_idx == 3:  # Header row
                cell.font = header_font
                cell.fill = header_fill

    # Registration Data Sheet
    reg_ws = wb.create_sheet("Registration Trends")
    reg_ws['A1'] = "Date"
    reg_ws['B1'] = "New Registrations"
    reg_ws['A1'].font = header_font
    reg_ws['B1'].font = header_font
    reg_ws['A1'].fill = header_fill
    reg_ws['B1'].fill = header_fill

    for idx, item in enumerate(data['registration_data'], start=2):
        reg_ws[f'A{idx}'] = item['date']
        reg_ws[f'B{idx}'] = item['count']

    # User Types Sheet
    types_ws = wb.create_sheet("User Types")
    types_ws['A1'] = "User Type"
    types_ws['B1'] = "Count"
    types_ws['A1'].font = header_font
    types_ws['B1'].font = header_font
    types_ws['A1'].fill = header_fill
    types_ws['B1'].fill = header_fill

    for idx, item in enumerate(data['user_type_data'], start=2):
        types_ws[f'A{idx}'] = item['user_type'].replace('_', ' ').title()
        types_ws[f'B{idx}'] = item['count']

    # Auto-adjust column widths
    for ws in wb.worksheets:
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width

    # Save to BytesIO
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response[
        'Content-Disposition'] = f'attachment; filename="user_analytics_{data["days"]}days_{timezone.now().strftime("%Y%m%d")}.xlsx"'

    return response


def generate_csv_report(registration_data, user_type_data, active_inactive_data):
    """Generate CSV analytics report"""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="user_analytics_{timezone.now().strftime("%Y%m%d")}.csv"'

    writer = csv.writer(response)

    # Write different sections
    writer.writerow(['USER ANALYTICS REPORT'])
    writer.writerow(['Generated:', timezone.now().strftime('%Y-%m-%d %H:%M:%S')])
    writer.writerow([])

    # Registration data
    writer.writerow(['REGISTRATION TRENDS'])
    writer.writerow(['Date', 'New Registrations'])
    for item in registration_data:
        writer.writerow([item['date'], item['count']])
    writer.writerow([])

    # User types
    writer.writerow(['USER TYPES DISTRIBUTION'])
    writer.writerow(['User Type', 'Count'])
    for item in user_type_data:
        writer.writerow([item['user_type'].replace('_', ' ').title(), item['count']])
    writer.writerow([])

    # User status
    writer.writerow(['USER STATUS DISTRIBUTION'])
    writer.writerow(['Status', 'Count'])
    for item in active_inactive_data:
        writer.writerow([item['status'], item['count']])

    return response


@login_required
def user_profile(request):
    """Enhanced user profile view with social accounts and AJAX support"""

    if request.method == 'POST':
        form = UserProfileForm(request.POST, request.FILES, instance=request.user)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            if form.is_valid():
                user = form.save()

                if 'avatar' in request.FILES:
                    avatar = request.FILES['avatar']
                    processed_avatar = process_avatar_image(avatar)
                    if processed_avatar:
                        user.avatar.save(
                            f"avatar_{user.id}_{avatar.name}",
                            processed_avatar,
                            save=True
                        )

                response_data = {
                    'success': True,
                    'message': 'Profile updated successfully!',
                    'user_data': {
                        'full_name': user.get_full_name() or user.username,
                        'avatar_url': user.avatar.url if user.avatar else None,
                        'email': user.email,
                        'phone_number': user.phone_number or '',
                        'bio': user.bio or '',
                        'timezone': user.timezone,
                        'language': user.language,
                    }
                }
                return JsonResponse(response_data)
            else:
                response_data = {
                    'success': False,
                    'message': 'Please correct the errors below',
                    'errors': form.errors.as_json()
                }
                return JsonResponse(response_data, status=400)
        else:
            if form.is_valid():
                user = form.save()

                if 'avatar' in request.FILES:
                    avatar = request.FILES['avatar']
                    processed_avatar = process_avatar_image(avatar)
                    if processed_avatar:
                        user.avatar.save(
                            f"avatar_{user.id}_{avatar.name}",
                            processed_avatar,
                            save=True
                        )

                messages.success(request, 'Your profile has been updated successfully!')
                return redirect('user_profile')
            else:
                messages.error(request, 'Please correct the errors below.')
    else:
        form = UserProfileForm(instance=request.user)

    user_company = getattr(request.user, 'company', None)
    company_memberships = [user_company] if user_company and user_company.is_active else []

    profile_completion = calculate_profile_completion(request.user)
    recent_activity = get_recent_user_activity(request.user)

    # Get social accounts
    social_accounts = SocialAccount.objects.filter(user=request.user)

    context = {
        'form': form,
        'user': request.user,
        'owned_company': getattr(request.user, 'owned_company', None),
        'company_memberships': company_memberships,
        'profile_completion': profile_completion,
        'recent_activity': recent_activity,
        'social_accounts': social_accounts,  # Add this
        'has_password': request.user.has_usable_password(),  # Add this
    }

    return render(request, 'accounts/profile.html', context)


def process_avatar_image(image_file):
    """
    Process and optimize uploaded avatar images
    """
    try:
        # Open and process the image
        img = Image.open(image_file)

        # Convert RGBA to RGB if necessary
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Resize image to standard avatar size
        max_size = (400, 400)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)

        # Create a square image (crop to center if needed)
        width, height = img.size
        if width != height:
            # Crop to square
            size = min(width, height)
            left = (width - size) // 2
            top = (height - size) // 2
            right = left + size
            bottom = top + size
            img = img.crop((left, top, right, bottom))

        # Save processed image to BytesIO
        from io import BytesIO
        output = BytesIO()
        img.save(output, format='JPEG', quality=85, optimize=True)
        output.seek(0)

        return ContentFile(output.getvalue())

    except Exception as e:
        print(f"Error processing avatar image: {e}")
        return None


def calculate_profile_completion(user):
    """
    Calculate profile completion percentage
    """
    total_fields = 10
    completed_fields = 0

    # Check required fields
    if user.first_name:
        completed_fields += 1
    if user.last_name:
        completed_fields += 1
    if user.email:
        completed_fields += 1
    if user.phone_number:
        completed_fields += 1
    if user.bio:
        completed_fields += 1
    if user.avatar:
        completed_fields += 1
    if user.timezone:
        completed_fields += 1
    if user.language:
        completed_fields += 1
    if user.email_verified:
        completed_fields += 1
    if user.phone_verified:
        completed_fields += 1

    return round((completed_fields / total_fields) * 100)


def get_recent_user_activity(user, limit=5):
    """
    Get recent user activity (customize based on your activity tracking)
    """
    # This is a placeholder - implement based on your activity tracking system
    activities = []

    # Example activities you might track
    if user.last_login:
        activities.append({
            'type': 'login',
            'description': f'Logged in from {user.last_login_ip or "unknown IP"}',
            'timestamp': user.last_login,
            'icon': 'bi-box-arrow-in-right'
        })

    if user.password_changed_at:
        activities.append({
            'type': 'security',
            'description': 'Password was updated',
            'timestamp': user.password_changed_at,
            'icon': 'bi-key'
        })

    # Add more activity types as needed

    # Sort by timestamp and limit
    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    return activities[:limit]


@login_required
def upload_avatar_ajax(request):
    """
    Handle avatar upload via AJAX for immediate preview
    """
    if request.method == 'POST' and request.FILES.get('avatar'):
        avatar_file = request.FILES['avatar']

        # Validate file
        if avatar_file.size > 5 * 1024 * 1024:  # 5MB limit
            return JsonResponse({
                'success': False,
                'error': 'File size must be less than 5MB'
            }, status=400)

        if not avatar_file.content_type.startswith('image/'):
            return JsonResponse({
                'success': False,
                'error': 'File must be an image'
            }, status=400)

        # Process and save avatar
        processed_avatar = process_avatar_image(avatar_file)
        if processed_avatar:
            # Save to user
            request.user.avatar.save(
                f"avatar_{request.user.id}_{avatar_file.name}",
                processed_avatar,
                save=True
            )

            return JsonResponse({
                'success': True,
                'avatar_url': request.user.avatar.url,
                'message': 'Avatar updated successfully!'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Failed to process image'
            }, status=400)

    return JsonResponse({
        'success': False,
        'error': 'Invalid request'
    }, status=400)


# Additional utility functions for enhanced profile features

@login_required
def export_profile_data(request):
    """
    Export user profile data as JSON
    """
    user_data = {
        'personal_info': {
            'username': request.user.username,
            'email': request.user.email,
            'first_name': request.user.first_name,
            'last_name': request.user.last_name,
            'middle_name': request.user.middle_name,
            'phone_number': request.user.phone_number,
            'bio': request.user.bio,
            'date_joined': request.user.date_joined.isoformat(),
        },
        'preferences': {
            'timezone': request.user.timezone,
            'language': request.user.language,
        },
        'security': {
            'email_verified': request.user.email_verified,
            'phone_verified': request.user.phone_verified,
            'two_factor_enabled': request.user.two_factor_enabled,
            'login_count': request.user.login_count,
            'last_login': request.user.last_login.isoformat() if request.user.last_login else None,
        },
        'account': {
            'user_type': request.user.user_type,
            'is_active': request.user.is_active,
            'company': request.user.company.name if hasattr(request.user, 'company') else None,
        }
    }

    response = JsonResponse(user_data, json_dumps_params={'indent': 2})
    response['Content-Disposition'] = f'attachment; filename="profile_data_{request.user.username}.json"'
    return response


@login_required
def delete_avatar(request):
    """
    Delete user avatar via AJAX
    """
    if request.method == 'POST':
        if request.user.avatar:
            request.user.avatar.delete(save=True)
            return JsonResponse({
                'success': True,
                'message': 'Avatar deleted successfully!'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'No avatar to delete'
            }, status=400)

    return JsonResponse({
        'success': False,
        'error': 'Invalid request method'
    }, status=405)


@login_required
def user_security_settings(request):
    """
    Handle user security settings
    """
    if request.method == 'POST':
        form = UserSecurityForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Security settings updated successfully!')
            return redirect('user_security_settings')
    else:
        form = UserSecurityForm(instance=request.user)

    context = {
        'form': form,
        'user': request.user,
        'active_sessions': get_user_active_sessions(request.user),
        'recent_logins': get_recent_login_attempts(request.user),
    }

    return render(request, 'accounts/security_settings.html', context)


@login_required
def user_notification_settings(request):
    """
    Handle user notification preferences
    """
    if request.method == 'POST':
        form = UserNotificationForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Notification preferences updated!'
                })

            messages.success(request, 'Notification preferences updated!')
            return redirect('user_notification_settings')
    else:
        form = UserNotificationForm(instance=request.user)

    context = {
        'form': form,
        'user': request.user,
    }

    return render(request, 'accounts/notification_settings.html', context)


@login_required
def user_preferences(request):
    """
    Handle user preferences and customizations
    """
    if request.method == 'POST':
        form = UserPreferencesForm(request.user, request.POST)
        if form.is_valid():
            form.save()

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Preferences updated!',
                    'preferences': request.user.metadata.get('preferences', {})
                })

            messages.success(request, 'Preferences updated successfully!')
            return redirect('user_preferences')
    else:
        form = UserPreferencesForm(request.user)

    context = {
        'form': form,
        'user': request.user,
    }

    return render(request, 'accounts/preferences.html', context)


@login_required
@require_POST
def send_verification(request):
    """
    Send email or phone verification
    """
    verification_type = request.POST.get('type')  # 'email' or 'phone'

    if verification_type == 'email':
        # Generate verification token
        token = secrets.token_urlsafe(32)

        # Save token to user metadata
        if not request.user.metadata:
            request.user.metadata = {}
        request.user.metadata['email_verification_token'] = token
        request.user.metadata['email_verification_expires'] = (
                timezone.now() + timezone.timedelta(hours=24)
        ).isoformat()
        request.user.save()

        # Send verification email
        verification_link = request.build_absolute_uri(
            f"/accounts/profile/verify-email/?token={token}"
        )

        send_mail(
            'Verify Your Email Address',
            render_to_string('emails/verify_email.txt', {
                'user': request.user,
                'verification_link': verification_link
            }),
            settings.DEFAULT_FROM_EMAIL,
            [request.user.email],
            html_message=render_to_string('emails/verify_email.html', {
                'user': request.user,
                'verification_link': verification_link
            }),
            fail_silently=False,
        )

        return JsonResponse({
            'success': True,
            'message': 'Verification email sent! Check your inbox.'
        })

    elif verification_type == 'phone':
        # Generate SMS verification code
        code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])

        # Save code to user metadata
        if not request.user.metadata:
            request.user.metadata = {}
        request.user.metadata['phone_verification_code'] = code
        request.user.metadata['phone_verification_expires'] = (
                timezone.now() + timezone.timedelta(minutes=10)
        ).isoformat()
        request.user.save()

        # Here you would integrate with SMS service (Twilio, etc.)
        # For now, we'll just return the code (remove in production)
        return JsonResponse({
            'success': True,
            'message': f'Verification code sent to {request.user.phone_number}',
            'debug_code': code if settings.DEBUG else None
        })

    return JsonResponse({
        'success': False,
        'error': 'Invalid verification type'
    }, status=400)


@login_required
def verify_email(request):
    """
    Verify email address with token
    """
    token = request.GET.get('token')
    if not token:
        messages.error(request, 'Invalid verification link.')
        return redirect('user_profile')

    # Check token validity
    user_token = request.user.metadata.get('email_verification_token')
    expires = request.user.metadata.get('email_verification_expires')

    if not user_token or user_token != token:
        messages.error(request, 'Invalid or expired verification link.')
        return redirect('user_profile')

    # Check expiration
    from datetime import datetime
    if expires:
        expire_time = datetime.fromisoformat(expires)
        if timezone.now() > expire_time:
            messages.error(request, 'Verification link has expired.')
            return redirect('user_profile')

    # Verify email
    request.user.email_verified = True
    request.user.metadata.pop('email_verification_token', None)
    request.user.metadata.pop('email_verification_expires', None)
    request.user.save()

    messages.success(request, 'Email address verified successfully!')
    return redirect('user_profile')


@login_required
@require_POST
def verify_phone(request):
    """
    Verify phone number with code
    """
    code = request.POST.get('code')
    if not code:
        return JsonResponse({
            'success': False,
            'error': 'Verification code is required'
        }, status=400)

    # Check code validity
    user_code = request.user.metadata.get('phone_verification_code')
    expires = request.user.metadata.get('phone_verification_expires')

    if not user_code or user_code != code:
        return JsonResponse({
            'success': False,
            'error': 'Invalid verification code'
        }, status=400)

    # Check expiration
    from datetime import datetime
    if expires:
        expire_time = datetime.fromisoformat(expires)
        if timezone.now() > expire_time:
            return JsonResponse({
                'success': False,
                'error': 'Verification code has expired'
            }, status=400)

    # Verify phone
    request.user.phone_verified = True
    request.user.metadata.pop('phone_verification_code', None)
    request.user.metadata.pop('phone_verification_expires', None)
    request.user.save()

    return JsonResponse({
        'success': True,
        'message': 'Phone number verified successfully!'
    })


@login_required
def enable_two_factor(request):
    """
    Step 1: Generate QR and verify TOTP to enable 2FA.
    """
    import io, pyotp, qrcode
    import base64
    user = request.user

    # If already enabled
    if user.two_factor_enabled:
        return JsonResponse({'success': False, 'error': 'Two-factor authentication is already enabled'}, status=400)

    if request.method == 'POST':
        totp_code = request.POST.get('totp_code')
        secret_key = request.session.get('temp_2fa_secret')

        if not secret_key or not totp_code:
            return JsonResponse({'success': False, 'error': 'Missing secret or code'}, status=400)

        totp = pyotp.TOTP(secret_key)
        if not totp.verify(totp_code, valid_window=1):
            return JsonResponse({'success': False, 'error': 'Invalid or expired authentication code'}, status=400)

        # Mark as enabled
        user.two_factor_enabled = True
        user.metadata['totp_secret'] = secret_key
        user.backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]
        user.save()

        request.session.pop('temp_2fa_secret', None)

        return JsonResponse({
            'success': True,
            'message': 'Two-factor authentication enabled successfully!',
            'backup_codes': user.backup_codes
        })

    # GET — Generate secret & QR code
    secret_key = pyotp.random_base32()
    request.session['temp_2fa_secret'] = secret_key

    totp_uri = pyotp.totp.TOTP(secret_key).provisioning_uri(
        name=user.email or user.username,
        issuer_name="PrimeBooks"
    )

    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(totp_uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_code_data = base64.b64encode(buffer.getvalue()).decode()

    return JsonResponse({
        'success': True,
        'qr_code': f"data:image/png;base64,{qr_code_data}",
        'manual_entry_key': secret_key,
        'message': 'Scan the QR code using your authenticator app.'
    })


@login_required
def verify_2fa(request):
    """Step 3: Verify 6-digit code from authenticator."""
    if request.method == "POST":
        code = request.POST.get('code')
        user = request.user
        totp = pyotp.TOTP(user.two_factor_secret)
        if totp.verify(code):
            # Generate backup codes
            import secrets
            user.two_factor_enabled = True
            user.backup_codes = [secrets.token_hex(4).upper() for _ in range(6)]
            user.save(update_fields=['two_factor_enabled', 'backup_codes'])
            return JsonResponse({"success": True, "backup_codes": user.backup_codes})
        else:
            return JsonResponse({"success": False, "error": _("Invalid code")})
    return JsonResponse({"error": "Invalid request"}, status=400)

@login_required
@require_POST
def disable_two_factor(request):
    """
    Disable 2FA after verifying password.
    """
    user = request.user

    if not user.two_factor_enabled:
        return JsonResponse({'success': False, 'error': 'Two-factor authentication is not enabled'}, status=400)

    current_password = request.POST.get('current_password')
    if not current_password or not user.check_password(current_password):
        return JsonResponse({'success': False, 'error': 'Incorrect password'}, status=400)

    user.two_factor_enabled = False
    user.backup_codes = []
    user.metadata.pop('totp_secret', None)
    user.save()

    return JsonResponse({'success': True, 'message': 'Two-factor authentication has been disabled'})


@login_required
def generate_backup_codes(request):
    """
    Regenerate 2FA backup codes.
    """
    user = request.user

    if not user.two_factor_enabled:
        return JsonResponse({'success': False, 'error': 'Two-factor authentication is not enabled'}, status=400)

    user.backup_codes = [secrets.token_hex(4).upper() for _ in range(10)]
    user.save()

    return JsonResponse({
        'success': True,
        'backup_codes': user.backup_codes,
        'message': 'New backup codes generated successfully!'
    })


@require_POST
def verify_two_factor_login(request):
    """
    Verify a user's TOTP or backup code at login.
    """
    from django.contrib.auth import authenticate, login

    username = request.POST.get('username')
    password = request.POST.get('password')
    code = request.POST.get('code')

    user = authenticate(request, username=username, password=password)
    if not user:
        return JsonResponse({'success': False, 'error': 'Invalid credentials'}, status=400)

    if user.two_factor_enabled:
        secret = user.metadata.get('totp_secret')
        totp = pyotp.TOTP(secret)

        # Check TOTP or backup code
        if not totp.verify(code, valid_window=1):
            if code not in user.backup_codes:
                return JsonResponse({'success': False, 'error': 'Invalid 2FA code'}, status=400)
            # Consume backup code once used
            user.backup_codes.remove(code)
            user.save()

    login(request, user)
    return JsonResponse({'success': True, 'message': 'Login successful'})



@login_required
def user_activity_log(request):
    """
    Display user activity log
    """
    # This would typically come from a separate activity tracking system
    # For now, we'll create some sample data
    activities = [
        {
            'type': 'login',
            'description': 'Logged in successfully',
            'ip_address': request.user.last_login_ip,
            'timestamp': request.user.last_login,
            'status': 'success'
        },
        # Add more activities as needed
    ]

    context = {
        'activities': activities,
        'user': request.user,
    }

    return render(request, 'accounts/activity_log.html', context)


# Utility functions

def get_user_active_sessions(user):
    """
    Get active sessions for a user (placeholder implementation)
    """
    # This would typically integrate with Django's session framework
    # or a custom session tracking system
    return []


def get_recent_login_attempts(user, limit=10):
    """
    Get recent login attempts for a user (placeholder implementation)
    """
    # This would come from your login attempt tracking system
    return []

@login_required
def change_password(request):
    """Enhanced password change view"""
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            user.password_changed_at = timezone.now()
            user.save(update_fields=['password_changed_at'])

            update_session_auth_hash(request, user)
            messages.success(request, 'Your password has been changed successfully!')
            return redirect('user_profile')
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'accounts/change_password.html', {'form': form})


@login_required
def user_signature(request):
    """Enhanced user signature management"""
    signature, created = UserSignature.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        form = UserSignatureForm(request.POST, request.FILES, instance=signature)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your signature has been updated successfully!')
            return redirect('user_signature')
    else:
        form = UserSignatureForm(instance=signature)

    return render(request, 'accounts/signature.html', {'form': form, 'signature': signature})


@login_required
def two_factor_setup(request):
    """Enhanced two-factor authentication setup"""
    if request.method == 'POST':
        form = TwoFactorSetupForm(request.POST)
        if form.is_valid():
            # In a real implementation, you would verify the code here
            request.user.two_factor_enabled = True
            request.user.save(update_fields=['two_factor_enabled'])
            messages.success(request, 'Two-factor authentication has been enabled!')
            return redirect('user_profile')
    else:
        form = TwoFactorSetupForm()

    return render(request, 'accounts/two_factor_setup.html', {'form': form})


@login_required
def disable_two_factor(request):
    """Disable two-factor authentication"""
    if request.method == 'POST':
        request.user.two_factor_enabled = False
        request.user.backup_codes = []
        request.user.save(update_fields=['two_factor_enabled', 'backup_codes'])
        messages.success(request, 'Two-factor authentication has been disabled!')

    return redirect('user_profile')


@login_required
@permission_required('accounts.can_manage_users')
def user_quick_stats(request):
    """Enhanced AJAX endpoint for user statistics with SaaS admin support"""
    accessible_users = _get_accessible_users(request.user)

    stats = {
        'total_users': accessible_users.count(),
        'active_users': accessible_users.filter(is_active=True).count(),
        'new_users_today': accessible_users.filter(
            date_joined__date=timezone.now().date()
        ).count(),
        'locked_users': accessible_users.filter(
            locked_until__gt=timezone.now()
        ).count(),
        'user_types': list(
            accessible_users.values('user_type')
            .annotate(count=Count('user_type'))
            .order_by('user_type')
        ),
        'is_saas_admin': getattr(request.user, 'is_saas_admin', False),
    }

    # Add SaaS admin specific stats
    if getattr(request.user, 'is_saas_admin', False):
        stats['hidden_users'] = CustomUser.objects.filter(is_hidden=True).count()
        stats['saas_admins'] = CustomUser.objects.filter(is_saas_admin=True).count()

    return JsonResponse(stats)


@require_saas_admin
def switch_tenant_view(request):
    """Allow SaaS admin to switch between tenants"""
    tenant_id = request.GET.get('tenant_id')

    if tenant_id:
        try:
            from company.models import Company
            company = get_object_or_404(Company, id=tenant_id)

            # Store the target company in session for the middleware to handle
            request.session['saas_admin_target_company'] = company.id

            messages.success(request, f'Switching to {company.name}...')
            return JsonResponse({
                'success': True,
                'message': f'Switching to {company.name}',
                'redirect_url': f'/?switch_tenant={tenant_id}'
            })

        except Company.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Company not found'
            }, status=404)

    # Return list of available companies for switching
    accessible_companies = get_accessible_companies(request.user)
    companies_data = [
        {
            'id': company.id,
            'name': company.name,
            'schema_name': getattr(company, 'schema_name', ''),
            'user_count': get_company_user_count(company),
            'status': getattr(company, 'status', 'ACTIVE')
        }
        for company in accessible_companies
    ]

    return JsonResponse({
        'success': True,
        'companies': companies_data
    })


@require_saas_admin
def saas_admin_user_impersonate(request, user_id):
    """Allow SaaS admin to impersonate a user (for support purposes)"""
    target_user = get_object_or_404(CustomUser, id=user_id)

    # Don't allow impersonating other SaaS admins
    if getattr(target_user, 'is_saas_admin', False):
        messages.error(request, 'Cannot impersonate other SaaS administrators.')
        return redirect('user_detail', pk=user_id)

    # Store original user info in session
    request.session['saas_admin_original_user_id'] = request.user.id
    request.session['saas_admin_impersonating'] = True
    request.session['saas_admin_impersonated_user_id'] = target_user.id

    # Log the impersonation for audit purposes
    logger.info(f"SaaS admin {request.user.email} started impersonating user {target_user.email}")

    messages.success(request, f'Now impersonating user: {target_user.get_full_name() or target_user.email}')
    return redirect('user_dashboard')


@require_saas_admin
def saas_admin_stop_impersonation(request):
    """Stop impersonating a user"""
    if not request.session.get('saas_admin_impersonating'):
        messages.error(request, 'No active impersonation session.')
        return redirect('saas_admin_dashboard')

    impersonated_user_id = request.session.get('saas_admin_impersonated_user_id')

    # Clean up session
    request.session.pop('saas_admin_original_user_id', None)
    request.session.pop('saas_admin_impersonating', None)
    request.session.pop('saas_admin_impersonated_user_id', None)

    # Log the end of impersonation
    logger.info(f"SaaS admin {request.user.email} stopped impersonating user ID {impersonated_user_id}")

    messages.success(request, 'Impersonation session ended.')
    return redirect('saas_admin_dashboard')


@require_saas_admin
def saas_admin_system_settings(request):
    """System-wide settings management for SaaS admins"""
    if request.method == 'POST':
        # Handle system settings updates
        setting_type = request.POST.get('setting_type')

        if setting_type == 'maintenance_mode':
            # Toggle maintenance mode
            maintenance_mode = request.POST.get('maintenance_mode') == 'on'
            # Store in cache or database
            from django.core.cache import cache
            cache.set('system_maintenance_mode', maintenance_mode, timeout=None)

            status = 'enabled' if maintenance_mode else 'disabled'
            messages.success(request, f'Maintenance mode {status}.')

        elif setting_type == 'user_registration':
            # Control user registration
            allow_registration = request.POST.get('allow_registration') == 'on'
            cache.set('allow_user_registration', allow_registration, timeout=None)

            status = 'enabled' if allow_registration else 'disabled'
            messages.success(request, f'User registration {status}.')

        elif setting_type == 'email_settings':
            # Update email settings
            smtp_host = request.POST.get('smtp_host')
            smtp_port = request.POST.get('smtp_port')
            smtp_user = request.POST.get('smtp_user')

            # In a real implementation, you'd update these in settings or database
            messages.success(request, 'Email settings updated.')

        return redirect('saas_admin_system_settings')

    # Get current settings
    from django.core.cache import cache
    context = {
        'maintenance_mode': cache.get('system_maintenance_mode', False),
        'allow_registration': cache.get('allow_user_registration', True),
        'system_stats': {
            'total_companies': Company.objects.count(),
            'total_users': get_visible_users().count(),
            'active_sessions': Session.objects.count(),
        }
    }

    return render(request, 'accounts/saas_admin_system_settings.html', context)


@require_saas_admin
def saas_admin_audit_log(request):
    """View system audit logs"""
    # In a real implementation, you'd have a proper audit log model
    # For now, we'll create some sample data structure

    # Filters
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    action_type = request.GET.get('action_type')
    user_filter = request.GET.get('user')

    # Sample audit log entries (replace with real audit log queries)
    audit_entries = []

    # You could create an AuditLog model to store these properly
    # class AuditLog(models.Model):
    #     user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    #     action = models.CharField(max_length=100)
    #     resource_type = models.CharField(max_length=50)
    #     resource_id = models.CharField(max_length=100)
    #     details = models.JSONField()
    #     timestamp = models.DateTimeField(auto_now_add=True)
    #     ip_address = models.GenericIPAddressField()

    context = {
        'audit_entries': audit_entries,
        'filters': {
            'date_from': date_from,
            'date_to': date_to,
            'action_type': action_type,
            'user': user_filter,
        },
        'action_types': [
            'user_created', 'user_updated', 'user_deleted',
            'company_created', 'company_updated', 'company_deleted',
            'login_success', 'login_failed', 'logout',
            'password_changed', 'email_verified', 'impersonation_started'
        ]
    }

    return render(request, 'accounts/saas_admin_audit_log.html', context)


# Enhanced middleware integration functions

def _user_has_company_access(user, company):
    """Enhanced company access check with SaaS admin support"""
    if getattr(user, 'is_saas_admin', False):
        return True

    if user.user_type == 'SYSTEM_ADMIN':
        return True

    if hasattr(company, 'owner') and company.owner == user:
        return True

    if hasattr(user, 'company_admin_for'):
        return company in user.company_admin_for.all()

    return False


def _user_has_management_access(current_user, target_user):
    """Enhanced management access check with SaaS admin support"""
    if getattr(current_user, 'is_saas_admin', False):
        return True

    if current_user.user_type == 'SYSTEM_ADMIN':
        # System admins can't manage hidden SaaS admin users
        return not getattr(target_user, 'is_hidden', False)

    if hasattr(current_user, 'owned_company'):
        # Company owners can manage users in their company
        return target_user.company == current_user.owned_company

    # Regular users can only manage themselves
    return current_user == target_user


# Additional Helper Functions
def _user_has_company_access(user, company):
    """Check if user has access to manage company"""
    if user.user_type == 'SYSTEM_ADMIN':
        return True

    if hasattr(company, 'owner') and company.owner == user:
        return True

    return company in user.company_admin_for.all()


def get_client_ip(request):
    """Helper function to get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

def _get_accessible_users(user):
    """
    Enhanced function to get users accessible by the current user.
    Includes SaaS admin support and proper filtering of hidden users.
    """
    if getattr(user, 'is_saas_admin', False):
        # SaaS admins can see all users including hidden ones
        return CustomUser.objects.all()
    elif user.user_type == 'SUPER_ADMIN':
        # Super admins see all visible users
        return get_visible_users()
    elif user.user_type == 'COMPANY_ADMIN':
        # Company admins see visible users in their company
        return get_visible_users().filter(company=user.company)
    else:
        # Regular users see only themselves
        return CustomUser.objects.filter(id=user.id)



def _user_has_management_access(current_user, target_user):
    """Check if current user can manage target user"""
    if current_user.user_type == 'SYSTEM_ADMIN':
        return True

    if hasattr(current_user, 'owned_company'):
        # Company owners can manage users in their company
        return target_user.company == current_user.owned_company

    # Regular users can only manage themselves
    return current_user == target_user

# System Admin Views
@login_required
def system_admin_dashboard(request):
    """System admin dashboard with global statistics"""
    if request.user.user_type != 'SYSTEM_ADMIN':
        raise PermissionDenied

    # Global statistics
    total_companies = Company.objects.count()
    active_companies = Company.objects.filter(is_active=True).count()
    trial_companies = Company.objects.filter(is_trial=True).count() if hasattr(Company, 'is_trial') else 0

    total_users = CustomUser.objects.count()
    active_users = CustomUser.objects.filter(is_active=True).count()

    # Recent activity
    recent_companies = Company.objects.order_by('-created_at')[:10]
    recent_users = CustomUser.objects.order_by('-date_joined')[:10]

    # Plan distribution
    plan_stats = []
    if hasattr(Company, 'plan'):
        plan_stats = list(
            Company.objects.values('plan__name', 'plan__display_name')
            .annotate(count=Count('id'))
            .order_by('-count')
        )

    # Companies expiring soon
    expiring_soon = []
    if hasattr(Company, 'subscription_ends_at'):
        expiring_soon = Company.objects.filter(
            subscription_ends_at__lte=timezone.now().date() + timedelta(days=30),
            subscription_ends_at__gte=timezone.now().date()
        ).order_by('subscription_ends_at')[:10]

    context = {
        'total_companies': total_companies,
        'active_companies': active_companies,
        'trial_companies': trial_companies,
        'expired_companies': 0,  # You'll need to implement this logic
        'total_users': total_users,
        'active_users': active_users,
        'recent_companies': recent_companies,
        'recent_users': recent_users,
        'plan_stats': plan_stats,
        'expiring_soon': expiring_soon,
    }

    return render(request, 'accounts/system_admin_dashboard.html', context)


class UserListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Enhanced user list view with SaaS admin support and proper filtering"""
    model = CustomUser
    template_name = 'accounts/user_list.html'
    context_object_name = 'users'
    paginate_by = 25
    permission_required = 'accounts.can_manage_users'

    def get_queryset(self):
        user = self.request.user

        if getattr(user, 'is_saas_admin', False):
            # SaaS admins can see all users including hidden ones
            queryset = CustomUser.objects.select_related('company').prefetch_related('signature')
        else:
            # Regular users see only visible users
            queryset = get_visible_users().select_related('company').prefetch_related('signature')

            # Prevent listing SUPER_ADMIN users unless the current user is a SUPER_ADMIN
            if user.user_type != 'SUPER_ADMIN':
                queryset = queryset.exclude(user_type='SUPER_ADMIN')

            if user.user_type not in ['SYSTEM_ADMIN', 'SUPER_ADMIN']:
                if hasattr(user, 'owned_company'):
                    queryset = queryset.filter(company=user.owned_company)
                elif hasattr(user, 'company') and user.company:
                    queryset = queryset.filter(company=user.company)
                else:
                    queryset = queryset.none()

        # Apply search filters
        search_form = UserSearchForm(self.request.GET)
        if search_form.is_valid():
            search_query = search_form.cleaned_data.get('search_query')
            if search_query:
                queryset = queryset.filter(
                    Q(first_name__icontains=search_query) |
                    Q(last_name__icontains=search_query) |
                    Q(email__icontains=search_query) |
                    Q(username__icontains=search_query)
                )

            user_type = search_form.cleaned_data.get('user_type')
            if user_type:
                queryset = queryset.filter(user_type=user_type)

            is_active = search_form.cleaned_data.get('is_active')
            if is_active:
                queryset = queryset.filter(is_active=is_active == 'true')

            email_verified = search_form.cleaned_data.get('email_verified')
            if email_verified:
                queryset = queryset.filter(email_verified=email_verified == 'true')

            date_from = search_form.cleaned_data.get('date_joined_from')
            date_to = search_form.cleaned_data.get('date_joined_to')
            if date_from:
                queryset = queryset.filter(date_joined__date__gte=date_from)
            if date_to:
                queryset = queryset.filter(date_joined__date__lte=date_to)

        return queryset.order_by('-date_joined')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = UserSearchForm(self.request.GET)
        context['bulk_form'] = BulkUserActionForm()

        # User statistics (filtered by access and visibility)
        queryset = self.get_queryset()
        context['user_stats'] = {
            'total': queryset.count(),
            'active': queryset.filter(is_active=True).count(),
            'inactive': queryset.filter(is_active=False).count(),
            'locked': queryset.filter(locked_until__gt=timezone.now()).count(),
        }

        # Add SaaS admin context
        context.update({
            'is_saas_admin': getattr(self.request.user, 'is_saas_admin', False),
            'is_system_admin': self.request.user.user_type == 'SYSTEM_ADMIN',
        })

        return context

class UserDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """Enhanced user detail view with social account info"""
    model = CustomUser
    template_name = 'accounts/user_detail.html'
    context_object_name = 'user_profile'
    permission_required = 'accounts.can_manage_users'

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not self._user_has_access(obj):
            raise Http404("User not found")
        return obj

    def _user_has_access(self, target_user):
        """Enhanced access control including SaaS admin support"""
        current_user = self.request.user
        if getattr(current_user, 'is_saas_admin', False):
            return True
        if current_user.user_type == 'SYSTEM_ADMIN':
            return not getattr(target_user, 'is_hidden', False)
        if hasattr(current_user, 'owned_company') and current_user.owned_company:
            return target_user.company == current_user.owned_company
        if hasattr(current_user, 'company') and current_user.company:
            return target_user.company == current_user.company
        return False

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_profile = self.get_object()
        current_user = self.request.user

        # Get social accounts
        social_accounts = SocialAccount.objects.filter(user=user_profile)

        can_edit = False
        if getattr(current_user, 'is_saas_admin', False):
            can_edit = True
        elif current_user.user_type == 'SYSTEM_ADMIN':
            can_edit = not getattr(user_profile, 'is_hidden', False)
        elif hasattr(current_user, 'owned_company') and user_profile.company == current_user.owned_company:
            can_edit = True
        elif current_user == user_profile:
            can_edit = True

        context.update({
            'account_age': (timezone.now() - user_profile.date_joined).days,
            'is_locked': user_profile.is_locked,
            'can_unlock': user_profile.is_locked and current_user.has_perm('accounts.can_manage_users'),
            'company': user_profile.company,
            'owned_company': getattr(user_profile, 'owned_company', None),
            'can_edit': can_edit,
            'can_manage_users': current_user.has_perm('accounts.can_manage_users'),
            'is_saas_admin': getattr(current_user, 'is_saas_admin', False),
            'is_hidden_user': getattr(user_profile, 'is_hidden', False),
            'can_access_all_companies': getattr(user_profile, 'can_access_all_companies', False),
            'social_accounts': social_accounts,  # Add social accounts to context
            'has_password': user_profile.has_usable_password(),
        })

        return context


class UserCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """Enhanced user creation with company assignment and logging"""
    model = CustomUser
    form_class = CustomUserCreationForm
    template_name = 'accounts/user_create.html'
    permission_required = 'accounts.can_manage_users'
    success_url = reverse_lazy('user_list')

    def get_form_kwargs(self):
        """Pass request into the form for context"""
        kwargs = super().get_form_kwargs()
        kwargs['request'] = self.request
        return kwargs

    def form_valid(self, form):
        current_user = self.request.user
        logger.debug(f"Attempting to create new user by {current_user} ({current_user.user_type})")

        with transaction.atomic():
            user = form.save(commit=False)

            # Assign company if not system admin
            if current_user.user_type != 'SYSTEM_ADMIN':
                if hasattr(current_user, 'owned_company') and current_user.owned_company:
                    user.company = current_user.owned_company
                    logger.debug(f"Assigned company from owned_company: {user.company}")
                elif hasattr(current_user, 'company') and current_user.company:
                    user.company = current_user.company
                    logger.debug(f"Assigned company from current_user.company: {user.company}")

            # Validate company assignment
            if not user.company:
                logger.error("❌ Company assignment failed. No company available.")
                form.add_error('company', "Company must be assigned.")
                return self.form_invalid(form)

            user.save()
            form.save_m2m()

            messages.success(self.request, f'User {user.get_full_name() or user.email} created successfully!')
            logger.info(f"✅ User {user} created in company {user.company}")

            return super().form_valid(form)

    def form_invalid(self, form):
        """Extra logging when form is invalid"""
        logger.error(f"❌ Form invalid. Errors: {form.errors.as_json()}")
        return super().form_invalid(form)

class UserUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """User update view, prevents editing SUPER_ADMIN users"""
    model = CustomUser
    form_class = CustomUserChangeForm
    template_name = 'accounts/user_update.html'
    permission_required = 'accounts.can_manage_users'

    def get_queryset(self):
        """Limit queryset to non-superusers"""
        qs = super().get_queryset()
        return qs.exclude(user_type='SUPER_ADMIN')

    def get_object(self, queryset=None):
        """Ensure only editable users are returned"""
        queryset = queryset or self.get_queryset()
        return super().get_object(queryset)

    def get_success_url(self):
        return reverse('user_detail', kwargs={'pk': self.object.pk})

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'User {self.object.get_full_name()} updated successfully!')
        return response



class UserDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    model = CustomUser
    template_name = 'accounts/user_delete_options.html'
    permission_required = 'accounts.can_manage_users'
    success_url = reverse_lazy('user_list')

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not self._user_has_access(obj):
            raise Http404("User not found")
        return obj

    def _user_has_access(self, target_user):
        current_user = self.request.user
        if current_user.user_type == 'SUPER_ADMIN':
            return True
        if current_user == target_user:
            return True
        if current_user.user_type == 'COMPANY_ADMIN' and current_user.company == target_user.company:
            return True
        return False

    def post(self, request, *args, **kwargs):
        user = self.get_object()
        action = request.POST.get('action')

        if action == 'deactivate':
            user.is_active = False
            user.save()
            messages.success(request, f'User {user.get_full_name()} deactivated successfully!')
        elif action == 'delete':
            user.delete()
            messages.success(request, f'User {user.get_full_name()} deleted successfully!')
        else:
            messages.error(request, 'No action selected.')

        return redirect(self.success_url)


class APIToken(models.Model):
    """Model for user API tokens"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='api_tokens')
    name = models.CharField(max_length=100, help_text="Descriptive name for this token")
    token = models.CharField(max_length=64, unique=True)
    permissions = models.JSONField(default=list, help_text="List of permissions for this token")
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Token expiration date")
    last_used = models.DateTimeField(null=True, blank=True)
    last_used_ip = models.GenericIPAddressField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.user.email}"

    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False


class UserSession(models.Model):
    """Model to track user sessions"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='user_sessions')
    session_key = models.CharField(max_length=40, unique=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    device_info = models.JSONField(default=dict)
    location = models.CharField(max_length=100, blank=True)
    is_current = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_activity']

    def __str__(self):
        return f"{self.user.email} - {self.ip_address}"


@login_required
def deactivate_account(request):
    """
    Deactivate user account (soft delete)
    """
    if request.method == 'POST':
        password = request.POST.get('password')
        reason = request.POST.get('reason', '')
        feedback = request.POST.get('feedback', '')

        # Verify password
        if not request.user.check_password(password):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': 'Incorrect password'
                }, status=400)
            messages.error(request, 'Incorrect password.')
            return render(request, 'accounts/deactivate_account.html')

        # Store deactivation info in metadata
        if not request.user.metadata:
            request.user.metadata = {}

        request.user.metadata['deactivation'] = {
            'date': timezone.now().isoformat(),
            'reason': reason,
            'feedback': feedback,
            'ip_address': get_client_ip(request)
        }

        # Deactivate account
        request.user.is_active = False
        request.user.save()

        # Send confirmation email
        send_mail(
            'Account Deactivated',
            render_to_string('emails/account_deactivated.txt', {
                'user': request.user,
                'reason': reason
            }),
            settings.DEFAULT_FROM_EMAIL,
            [request.user.email],
            html_message=render_to_string('emails/account_deactivated.html', {
                'user': request.user,
                'reason': reason
            }),
            fail_silently=True,
        )

        # Log out user
        logout(request)

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Account deactivated successfully',
                'redirect_url': '/'
            })

        messages.success(request, 'Your account has been deactivated successfully.')
        return redirect('/')

    return render(request, 'accounts/deactivate_account.html')


@login_required
def download_user_data(request):
    """
    Download user data in JSON format
    """
    # Prepare user data
    user_data = {
        'profile': {
            'username': request.user.username,
            'email': request.user.email,
            'first_name': request.user.first_name,
            'last_name': request.user.last_name,
            'middle_name': request.user.middle_name,
            'phone_number': request.user.phone_number,
            'bio': request.user.bio,
            'date_joined': request.user.date_joined.isoformat(),
            'last_login': request.user.last_login.isoformat() if request.user.last_login else None,
            'timezone': request.user.timezone,
            'language': request.user.language,
            'user_type': request.user.user_type,
        },
        'preferences': request.user.metadata.get('preferences', {}),
        'notifications': request.user.metadata.get('notifications', {}),
        'security': {
            'email_verified': request.user.email_verified,
            'phone_verified': request.user.phone_verified,
            'two_factor_enabled': request.user.two_factor_enabled,
            'login_count': request.user.login_count,
        },
        'activity': {
            'last_activity_at': request.user.last_activity_at.isoformat() if request.user.last_activity_at else None,
            'last_login_ip': request.user.last_login_ip,
        }
    }

    # Create JSON response
    response = JsonResponse(user_data, json_dumps_params={'indent': 2})
    response[
        'Content-Disposition'] = f'attachment; filename="user_data_{request.user.username}_{datetime.now().strftime("%Y%m%d")}.json"'
    return response


@login_required
def privacy_settings(request):
    """
    Handle user privacy settings
    """
    if request.method == 'POST':
        # Get privacy preferences
        privacy_data = {
            'profile_visibility': request.POST.get('profile_visibility', 'private'),
            'show_email': request.POST.get('show_email') == 'on',
            'show_phone': request.POST.get('show_phone') == 'on',
            'show_last_login': request.POST.get('show_last_login') == 'on',
            'allow_search': request.POST.get('allow_search') == 'on',
            'data_processing': request.POST.get('data_processing') == 'on',
            'marketing_consent': request.POST.get('marketing_consent') == 'on',
            'analytics_consent': request.POST.get('analytics_consent') == 'on',
        }

        # Save to user metadata
        if not request.user.metadata:
            request.user.metadata = {}
        request.user.metadata['privacy'] = privacy_data
        request.user.save()

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Privacy settings updated successfully!'
            })

        messages.success(request, 'Privacy settings updated successfully!')
        return redirect('privacy_settings')

    # Get current privacy settings
    privacy_settings = request.user.metadata.get('privacy', {
        'profile_visibility': 'private',
        'show_email': False,
        'show_phone': False,
        'show_last_login': False,
        'allow_search': True,
        'data_processing': True,
        'marketing_consent': False,
        'analytics_consent': True,
    })

    context = {
        'user': request.user,
        'privacy_settings': privacy_settings,
    }

    return render(request, 'accounts/privacy_settings.html', context)


@login_required
def export_all_data(request):
    """
    Export all user data in a comprehensive ZIP file
    """
    if request.method == 'POST':
        # Create a ZIP file in memory
        zip_buffer = BytesIO()

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            # 1. Profile data as JSON
            profile_data = {
                'username': request.user.username,
                'email': request.user.email,
                'first_name': request.user.first_name,
                'last_name': request.user.last_name,
                'middle_name': request.user.middle_name,
                'phone_number': request.user.phone_number,
                'bio': request.user.bio,
                'date_joined': request.user.date_joined.isoformat(),
                'last_login': request.user.last_login.isoformat() if request.user.last_login else None,
                'timezone': request.user.timezone,
                'language': request.user.language,
                'user_type': request.user.user_type,
                'metadata': request.user.metadata,
            }
            zip_file.writestr('profile.json', json.dumps(profile_data, indent=2))

            # 2. API tokens as CSV
            api_tokens = APIToken.objects.filter(user=request.user)
            if api_tokens.exists():
                csv_buffer = BytesIO()
                csv_writer = csv.writer(csv_buffer.getvalue().decode() if csv_buffer.getvalue() else StringIO())
                csv_writer.writerow(['Name', 'Created', 'Last Used', 'Expires', 'Status'])

                for token in api_tokens:
                    csv_writer.writerow([
                        token.name,
                        token.created_at.isoformat(),
                        token.last_used.isoformat() if token.last_used else 'Never',
                        token.expires_at.isoformat() if token.expires_at else 'Never',
                        'Active' if token.is_active else 'Inactive'
                    ])

                zip_file.writestr('api_tokens.csv', csv_buffer.getvalue())

            # 3. Sessions data
            sessions = UserSession.objects.filter(user=request.user)
            if sessions.exists():
                sessions_data = []
                for session in sessions:
                    sessions_data.append({
                        'ip_address': session.ip_address,
                        'user_agent': session.user_agent,
                        'location': session.location,
                        'created_at': session.created_at.isoformat(),
                        'last_activity': session.last_activity.isoformat(),
                        'is_current': session.is_current,
                    })

                zip_file.writestr('sessions.json', json.dumps(sessions_data, indent=2))

            # 4. Avatar image if exists
            if request.user.avatar:
                try:
                    avatar_content = request.user.avatar.read()
                    avatar_name = f"avatar{request.user.avatar.name[request.user.avatar.name.rfind('.'):]}"
                    zip_file.writestr(avatar_name, avatar_content)
                except Exception:
                    pass  # Skip if avatar file is not accessible

            # 5. Export summary
            summary = {
                'export_date': timezone.now().isoformat(),
                'user_id': request.user.id,
                'username': request.user.username,
                'email': request.user.email,
                'files_included': [
                    'profile.json - Complete profile information',
                    'api_tokens.csv - API tokens history' if api_tokens.exists() else None,
                    'sessions.json - Login sessions data' if sessions.exists() else None,
                    'avatar file - Profile picture' if request.user.avatar else None,
                ],
                'notes': 'This export contains all your personal data stored in our system.'
            }
            # Remove None values
            summary['files_included'] = [f for f in summary['files_included'] if f is not None]

            zip_file.writestr('README.json', json.dumps(summary, indent=2))

        # Prepare response
        zip_buffer.seek(0)
        response = HttpResponse(
            zip_buffer.getvalue(),
            content_type='application/zip'
        )
        response[
            'Content-Disposition'] = f'attachment; filename="user_data_export_{request.user.username}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.zip"'

        return response

    context = {
        'user': request.user,
        'api_tokens_count': APIToken.objects.filter(user=request.user).count(),
        'sessions_count': UserSession.objects.filter(user=request.user).count(),
    }

    return render(request, 'accounts/export_all_data.html', context)


@login_required
def delete_account_request(request):
    """
    Request account deletion (GDPR compliance)
    """
    if request.method == 'POST':
        password = request.POST.get('password')
        reason = request.POST.get('reason', '')
        feedback = request.POST.get('feedback', '')
        confirm_deletion = request.POST.get('confirm_deletion') == 'on'

        # Verify password
        if not request.user.check_password(password):
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': 'Incorrect password'
                }, status=400)
            messages.error(request, 'Incorrect password.')
            return render(request, 'accounts/delete_account_request.html')

        if not confirm_deletion:
            messages.error(request, 'Please confirm that you want to delete your account.')
            return render(request, 'accounts/delete_account_request.html')

        # Store deletion request in metadata
        if not request.user.metadata:
            request.user.metadata = {}

        deletion_token = secrets.token_urlsafe(32)
        request.user.metadata['deletion_request'] = {
            'date': timezone.now().isoformat(),
            'reason': reason,
            'feedback': feedback,
            'token': deletion_token,
            'ip_address': get_client_ip(request),
            'scheduled_deletion': (timezone.now() + timedelta(days=30)).isoformat(),  # 30-day grace period
        }
        request.user.save()

        # Send confirmation email with cancellation link
        cancellation_link = request.build_absolute_uri(
            f"/accounts/profile/cancel-deletion/?token={deletion_token}"
        )

        send_mail(
            'Account Deletion Request Received',
            render_to_string('emails/deletion_request.txt', {
                'user': request.user,
                'cancellation_link': cancellation_link,
                'deletion_date': (timezone.now() + timedelta(days=30)).strftime('%B %d, %Y')
            }),
            settings.DEFAULT_FROM_EMAIL,
            [request.user.email],
            html_message=render_to_string('emails/deletion_request.html', {
                'user': request.user,
                'cancellation_link': cancellation_link,
                'deletion_date': (timezone.now() + timedelta(days=30)).strftime('%B %d, %Y')
            }),
            fail_silently=False,
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': True,
                'message': 'Deletion request submitted. Check your email for confirmation.'
            })

        messages.success(request,
                         'Your account deletion request has been submitted. You will receive an email with further instructions.')
        return redirect('user_profile')

    return render(request, 'accounts/delete_account_request.html')


@login_required
def active_sessions(request):
    """
    Display and manage active user sessions
    """
    # Get all active sessions for the user
    user_sessions = UserSession.objects.filter(
        user=request.user,
        last_activity__gte=timezone.now() - timedelta(days=30)
    ).order_by('-last_activity')

    # Get current session
    current_session_key = request.session.session_key

    # Mark current session
    for session in user_sessions:
        session.is_current_session = session.session_key == current_session_key

    context = {
        'user_sessions': user_sessions,
        'current_session_key': current_session_key,
        'user': request.user,
    }

    return render(request, 'accounts/active_sessions.html', context)


@login_required
def api_tokens(request):
    """
    Manage user API tokens
    """
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create':
            name = request.POST.get('name', '').strip()
            permissions = request.POST.getlist('permissions')
            expires_in_days = request.POST.get('expires_in_days')

            if not name:
                messages.error(request, 'Token name is required.')
                return redirect('api_tokens')

            # Generate token
            token = secrets.token_urlsafe(32)

            # Set expiration
            expires_at = None
            if expires_in_days and expires_in_days != 'never':
                expires_at = timezone.now() + timedelta(days=int(expires_in_days))

            # Create token
            api_token = APIToken.objects.create(
                user=request.user,
                name=name,
                token=token,
                permissions=permissions,
                expires_at=expires_at
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'API token created successfully!',
                    'token': {
                        'id': api_token.id,
                        'name': api_token.name,
                        'token': api_token.token,  # Only show once
                        'created_at': api_token.created_at.isoformat()
                    }
                })

            messages.success(request, f'API token "{name}" created successfully!')
            return redirect('api_tokens')

        elif action == 'delete':
            token_id = request.POST.get('token_id')
            try:
                api_token = APIToken.objects.get(id=token_id, user=request.user)
                token_name = api_token.name
                api_token.delete()

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse({
                        'success': True,
                        'message': f'API token "{token_name}" deleted successfully!'
                    })

                messages.success(request, f'API token "{token_name}" deleted successfully!')
            except APIToken.DoesNotExist:
                messages.error(request, 'API token not found.')

            return redirect('api_tokens')

    # Get user's API tokens
    user_tokens = APIToken.objects.filter(user=request.user).order_by('-created_at')

    # Available permissions (customize based on your needs)
    available_permissions = [
        ('read', 'Read Access'),
        ('write', 'Write Access'),
        ('delete', 'Delete Access'),
        ('admin', 'Admin Access'),
    ]

    context = {
        'user_tokens': user_tokens,
        'available_permissions': available_permissions,
        'user': request.user,
    }

    return render(request, 'accounts/api_tokens.html', context)


@login_required
def user_integrations(request):
    """
    Manage user integrations with external services
    """
    # Get user's integrations from metadata
    integrations = request.user.metadata.get('integrations', {})

    available_integrations = {
        'google': {
            'name': 'Google',
            'description': 'Connect with Google services',
            'icon': 'bi-google',
            'status': integrations.get('google', {}).get('status', 'disconnected')
        },
        'microsoft': {
            'name': 'Microsoft',
            'description': 'Connect with Microsoft Office 365',
            'icon': 'bi-microsoft',
            'status': integrations.get('microsoft', {}).get('status', 'disconnected')
        },
        'slack': {
            'name': 'Slack',
            'description': 'Receive notifications in Slack',
            'icon': 'bi-slack',
            'status': integrations.get('slack', {}).get('status', 'disconnected')
        },
        'zapier': {
            'name': 'Zapier',
            'description': 'Automate workflows with Zapier',
            'icon': 'bi-lightning',
            'status': integrations.get('zapier', {}).get('status', 'disconnected')
        }
    }

    if request.method == 'POST':
        action = request.POST.get('action')
        integration = request.POST.get('integration')

        if action == 'connect':
            # In a real implementation, you would redirect to OAuth flow
            # For now, we'll simulate connection
            if not request.user.metadata:
                request.user.metadata = {}
            if 'integrations' not in request.user.metadata:
                request.user.metadata['integrations'] = {}

            request.user.metadata['integrations'][integration] = {
                'status': 'connected',
                'connected_at': timezone.now().isoformat(),
                'access_token': 'simulated_token_' + secrets.token_urlsafe(16)
            }
            request.user.save()

            messages.success(request, f'{available_integrations[integration]["name"]} connected successfully!')

        elif action == 'disconnect':
            if request.user.metadata and 'integrations' in request.user.metadata:
                if integration in request.user.metadata['integrations']:
                    del request.user.metadata['integrations'][integration]
                    request.user.save()

                    messages.success(request,
                                     f'{available_integrations[integration]["name"]} disconnected successfully!')

        return redirect('user_integrations')

    # Update statuses
    for key, integration in available_integrations.items():
        integration['status'] = integrations.get(key, {}).get('status', 'disconnected')
        if integration['status'] == 'connected':
            integration['connected_at'] = integrations.get(key, {}).get('connected_at')

    context = {
        'available_integrations': available_integrations,
        'user': request.user,
    }

    return render(request, 'accounts/user_integrations.html', context)


@login_required
@require_POST
def revoke_session(request, session_id):
    """
    Revoke a specific user session
    """
    try:
        user_session = UserSession.objects.get(id=session_id, user=request.user)

        # Don't allow revoking current session
        if user_session.session_key == request.session.session_key:
            return JsonResponse({
                'success': False,
                'error': 'Cannot revoke current session'
            }, status=400)

        # Delete the Django session
        try:
            Session.objects.get(session_key=user_session.session_key).delete()
        except Session.DoesNotExist:
            pass  # Session already expired or deleted

        # Delete our session record
        session_info = f"{user_session.ip_address} - {user_session.user_agent[:50]}"
        user_session.delete()

        return JsonResponse({
            'success': True,
            'message': f'Session revoked successfully: {session_info}'
        })

    except UserSession.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Session not found'
        }, status=404)


# Utility function
def get_client_ip(request):
    """Get client IP address from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

@login_required
@permission_required('accounts.can_manage_users')
def unlock_user(request, pk):
    """Unlock a locked user account with access control"""
    user = get_object_or_404(CustomUser, pk=pk)

    # Check access
    if not _user_has_management_access(request.user, user):
        raise PermissionDenied

    if user.is_locked:
        user.unlock_account()
        messages.success(request, f'User {user.get_full_name()} has been unlocked successfully!')
    else:
        messages.info(request, f'User {user.get_full_name()} is not locked.')

    return redirect('user_detail', pk=pk)


@login_required
@permission_required('accounts.can_manage_users')
@require_http_methods(["POST"])
def bulk_user_actions(request):
    """Enhanced bulk user actions with SaaS admin support"""
    form = BulkUserActionForm(request.POST)

    if form.is_valid():
        action = form.cleaned_data['action']
        user_ids = form.cleaned_data['selected_users']

        # Filter users based on access
        accessible_users = _get_accessible_users(request.user).filter(id__in=user_ids)

        # Don't allow actions on hidden SaaS admin users unless user is SaaS admin
        if not getattr(request.user, 'is_saas_admin', False):
            accessible_users = accessible_users.filter(is_hidden=False)

        count = accessible_users.count()

        if count == 0:
            messages.error(request, 'No accessible users selected.')
            return redirect('user_list')

        if action == 'activate':
            accessible_users.update(is_active=True)
            messages.success(request, f'{count} users activated successfully!')

        elif action == 'deactivate':
            # Don't deactivate the current user or other SaaS admins
            deactivate_qs = accessible_users.exclude(id=request.user.id)
            if not getattr(request.user, 'is_saas_admin', False):
                deactivate_qs = deactivate_qs.exclude(is_saas_admin=True)

            deactivated_count = deactivate_qs.update(is_active=False)
            messages.success(request, f'{deactivated_count} users deactivated successfully!')

        elif action == 'delete':
            # Soft delete - deactivate instead, with same restrictions
            delete_qs = accessible_users.exclude(id=request.user.id)
            if not getattr(request.user, 'is_saas_admin', False):
                delete_qs = delete_qs.exclude(is_saas_admin=True)

            deleted_count = delete_qs.update(is_active=False)
            messages.success(request, f'{deleted_count} users deactivated successfully!')

        elif action == 'export':
            return export_users(request, list(accessible_users.values_list('id', flat=True)))

    return redirect('user_list')


@login_required
@permission_required('accounts.can_export_data')
def export_users(request, user_ids=None):
    """Enhanced export users with SaaS admin support"""
    if user_ids:
        if isinstance(user_ids, str):
            user_ids_list = [int(uid) for uid in user_ids.split(',')]
        else:
            user_ids_list = user_ids
        users = _get_accessible_users(request.user).filter(id__in=user_ids_list)
    else:
        users = _get_accessible_users(request.user)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = (
        f'attachment; filename="users_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow([
        'ID', 'Email', 'Username', 'First Name', 'Last Name', 'User Type',
        'Is Active', 'Email Verified', 'Phone Number', 'Date Joined', 'Last Login',
        'Company', 'Is Company Admin', 'Is Hidden', 'Is SaaS Admin'
    ])

    for user in users:
        company = user.company
        is_admin = hasattr(user, 'company_admin_for') and user.company_admin_for.filter(id=company.id).exists() if company else False

        writer.writerow([
            user.id,
            user.email,
            user.username,
            user.first_name,
            user.last_name,
            user.get_user_type_display() if hasattr(user, 'get_user_type_display') else '',
            user.is_active,
            getattr(user, 'email_verified', False),
            user.phone_number or '',
            timezone.localtime(user.date_joined).strftime('%Y-%m-%d %H:%M:%S'),
            timezone.localtime(user.last_login).strftime('%Y-%m-%d %H:%M:%S') if user.last_login else '',
            company.name if company else '',
            is_admin,
            getattr(user, 'is_hidden', False),
            getattr(user, 'is_saas_admin', False)
        ])

    return response



@login_required
def check_username_availability(request):
    """AJAX endpoint to check username availability"""
    username = request.GET.get('username', '')
    user_id = request.GET.get('user_id', None)

    if not username:
        return JsonResponse({'available': False, 'message': 'Username is required'})

    query = CustomUser.objects.filter(username=username)
    if user_id:
        query = query.exclude(id=user_id)

    available = not query.exists()
    message = 'Username is available' if available else 'Username is already taken'

    return JsonResponse({'available': available, 'message': message})


@login_required
def check_email_availability(request):
    """AJAX endpoint to check email availability"""
    email = request.GET.get('email', '')
    user_id = request.GET.get('user_id', None)

    if not email:
        return JsonResponse({'available': False, 'message': 'Email is required'})

    query = CustomUser.objects.filter(email=email)
    if user_id:
        query = query.exclude(id=user_id)

    available = not query.exists()
    message = 'Email is available' if available else 'Email is already registered'

    return JsonResponse({'available': available, 'message': message})


# Company switching for multi-tenant users
@login_required
def switch_company(request, company_id):
    """Switch active company context"""
    company = get_object_or_404(Company, id=company_id)

    # Check if user has access to this company
    if not (hasattr(company, 'owner') and company.owner == request.user or
            company in request.user.companies.filter(is_active=True)):
        raise PermissionDenied

    # Store active company in session
    request.session['active_company_id'] = company_id
    messages.success(request, f'Switched to {company.display_name}')

    return redirect('companies:dashboard')


# User invitation system
@login_required
@permission_required('accounts.can_manage_users')
def invite_user(request, company_id):
    """Invite new user to company"""
    company = get_object_or_404(Company, id=company_id)

    # Check if user has access to this company
    if not _user_has_company_access(request.user, company):
        raise PermissionDenied

    # Check if company can add more users
    if hasattr(company, 'can_add_employee') and not company.can_add_employee():
        messages.error(request, f'Company has reached the maximum user limit.')
        return redirect('company_user_list', company_id=company_id)

    if request.method == 'POST':
        email = request.POST.get('email')
        user_type = request.POST.get('user_type', 'EMPLOYEE')
        is_admin = request.POST.get('is_admin') == 'on'

        # Check if user already exists
        existing_user = CustomUser.objects.filter(email=email).first()
        if existing_user:
            # Check if already in company
            if company in existing_user.companies.all():
                messages.error(request, 'User is already a member of this company.')
            else:
                # Add existing user to company
                existing_user.companies.add(company)
                if is_admin:
                    existing_user.company_admin_for.add(company)
                messages.success(request, f'User {existing_user.get_full_name()} added to company.')
        else:
            # Create new user with temporary password
            import secrets
            import string

            temporary_password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))

            with transaction.atomic():
                new_user = CustomUser.objects.create_user(
                    email=email,
                    username=email.split('@')[0] + str(secrets.randbelow(1000)),
                    password=temporary_password,
                    user_type=user_type,
                    is_active=True
                )

                new_user.companies.add(company)
                if is_admin:
                    new_user.company_admin_for.add(company)

                # In a real implementation, send invitation email with temporary password
                messages.success(
                    request,
                    f'User invited successfully. Temporary password: {temporary_password} (Send this securely to the user)'
                )

        return redirect('company_user_list', company_id=company_id)

    context = {
        'company': company,
        'user_types': CustomUser.USER_TYPES,
    }

    return render(request, 'accounts/invite_user.html', context)


# Enhanced Analytics Views
@login_required
def user_activity_log(request):
    """View user's activity log"""
    # In a real implementation, you would have an ActivityLog model
    # For now, we'll show basic user information
    context = {
        'user': request.user,
        'login_history': [
            {
                'date': request.user.last_login,
                'ip': request.user.last_login_ip,
                'success': True
            }
        ] if request.user.last_login else [],
        'password_changed_at': request.user.password_changed_at,
        'failed_attempts': request.user.failed_login_attempts,
    }

    return render(request, 'accounts/user_activity_log.html', context)


@login_required
def user_security_settings(request):
    """User security settings page"""
    context = {
        'user': request.user,
        'two_factor_enabled': request.user.two_factor_enabled,
        'backup_codes_count': len(request.user.backup_codes),
        'password_age': (timezone.now() - request.user.password_changed_at).days,
    }

    return render(request, 'accounts/user_security_settings.html', context)


@login_required
def system_companies_list(request):
    """System admin view of all companies"""
    from company.models import Company,SubscriptionPlan

    # Check if user is allowed to access system-level companies
    if not getattr(request.user, "is_saas_admin", False) and not request.user.is_superuser:
        raise PermissionDenied("You are not allowed to view system companies.")

    # Base queryset
    companies = Company.objects.select_related("plan").order_by("-created_at")

    # Apply filters
    status_filter = request.GET.get("status")
    if status_filter and hasattr(Company, "status"):
        companies = companies.filter(status=status_filter)

    plan_filter = request.GET.get("plan")
    if plan_filter and hasattr(Company, "plan"):
        companies = companies.filter(plan__name=plan_filter)

    search_query = request.GET.get("search")
    if search_query:
        filter_q = Q(name__icontains=search_query) | Q(email__icontains=search_query)
        if hasattr(Company, "trading_name"):
            filter_q |= Q(trading_name__icontains=search_query)
        if hasattr(Company, "company_id"):
            filter_q |= Q(company_id__icontains=search_query)
        companies = companies.filter(filter_q)

    # Pagination
    paginator = Paginator(companies, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    context = {
        "companies": page_obj,
        "status_choices": getattr(Company, "STATUS_CHOICES", []),
        "subscription_plans": SubscriptionPlan.objects.filter(is_active=True),
        "current_filters": {
            "status": status_filter,
            "plan": plan_filter,
            "search": search_query,
        },
    }

    return render(request, "accounts/system_companies_list.html", context)
