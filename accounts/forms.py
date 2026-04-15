from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, AuthenticationForm
from django.contrib.auth.forms import SetPasswordForm as DjangoSetPasswordForm
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.core.validators import FileExtensionValidator
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
import pytz
import re
import logging
from django_otp.plugins.otp_totp.models import TOTPDevice
from company.models import Company
from .models import CustomUser, UserSignature, Role, RoleHistory, APIToken, UserSession

logger = logging.getLogger(__name__)

class RoleForm(forms.ModelForm):
    """Form for creating/editing roles"""

    name = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., Store Manager, Assistant Cashier',
        }),
        help_text='Choose a clear, descriptive name for this role'
    )

    class Meta:
        model = Role
        fields = ['description', 'color_code', 'priority', 'max_users', 'is_active']
        widgets = {
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Describe what this role can do and who should have it...',
            }),
            'color_code': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
            }),
            'priority': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0,
                'max': 100,
            }),
            'max_users': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'placeholder': 'Leave empty for unlimited',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)  # ✅ now accepts request
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)

        # If editing, populate name from group
        if self.instance.pk and self.instance.group:
            self.fields['name'].initial = self.instance.group.name

    def clean_name(self):
        name = self.cleaned_data['name']

        existing = Group.objects.filter(name__iexact=name)
        if self.instance.pk:
            existing = existing.exclude(pk=self.instance.group.pk)

        if existing.exists():
            role_exists = Role.objects.filter(
                group__name__iexact=name,
                company=self.company
            ).exists()
            if role_exists:
                raise ValidationError(
                    f"A role named '{name}' already exists in your company."
                )

        return name

    def save(self, commit=True):
        role = super().save(commit=False)

        if self.instance.pk and self.instance.group:
            group = self.instance.group
            group.name = self.cleaned_data['name']
            group.save()
        else:
            group, created = Group.objects.get_or_create(
                name=self.cleaned_data['name']
            )
            role.group = group

        if commit:
            role.save()

        return role


class RolePermissionForm(forms.Form):
    """Form for managing role permissions with grouped checkboxes"""

    permissions = forms.ModelMultipleChoiceField(
        queryset=Permission.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )

    def __init__(self, *args, **kwargs):
        self.role = kwargs.pop('role', None)
        super().__init__(*args, **kwargs)

        if self.role:
            # Set initial permissions
            self.fields['permissions'].initial = self.role.group.permissions.all()

class PasswordResetRequestForm(forms.Form):
    """Form to request password reset"""
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Enter your email address',
            'autofocus': True,
        }),
        label='Email Address',
        help_text='Enter the email address associated with your account'
    )


class SetPasswordForm(DjangoSetPasswordForm):
    """Custom set password form with better styling"""
    new_password1 = forms.CharField(
        label="New Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Enter new password',
            'autocomplete': 'new-password',
        }),
        strip=False,
        help_text='Password must be at least 8 characters long'
    )
    new_password2 = forms.CharField(
        label="Confirm New Password",
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': 'Confirm new password',
            'autocomplete': 'new-password',
        }),
        strip=False,
        help_text='Enter the same password again for verification'
    )


class BulkUserRoleAssignForm(forms.Form):
    """Form for bulk assigning users to a role"""

    users = forms.ModelMultipleChoiceField(
        queryset=CustomUser.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Select Users",
        help_text="Select users to assign to the role"
    )

    role = forms.ModelChoiceField(
        queryset=Role.objects.none(),
        required=True,
        label="Select Role",
        help_text="Role to assign to selected users"
    )

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company', None)
        requesting_user = kwargs.pop('requesting_user', None)
        super().__init__(*args, **kwargs)

        if requesting_user:
            # Get manageable users
            self.fields['users'].queryset = requesting_user.get_manageable_users()

            # Get accessible roles
            self.fields['role'].queryset = Role.objects.accessible_by_user(requesting_user)
        elif company:
            # Fallback to company-based filtering
            self.fields['users'].queryset = CustomUser.objects.filter(
                company=company,
                is_hidden=False,
                is_active=True
            ).order_by('first_name', 'last_name')

            self.fields['role'].queryset = Role.objects.filter(
                Q(company=company) | Q(is_system_role=True, company__isnull=True),
                is_active=True
            )

    def clean(self):
        cleaned_data = super().clean()
        users = cleaned_data.get('users')
        role = cleaned_data.get('role')

        if users and role:
            # Check if role has capacity
            if role.max_users:
                current_count = role.group.user_set.filter(
                    is_hidden=False,
                    is_active=True
                ).count()

                # Count how many selected users don't already have the role
                new_assignments = sum(
                    1 for user in users
                    if not user.groups.filter(pk=role.group.pk).exists()
                )

                if current_count + new_assignments > role.max_users:
                    raise forms.ValidationError(
                        f"Role '{role.group.name}' can only accommodate "
                        f"{role.max_users - current_count} more users. "
                        f"You're trying to assign {new_assignments} new users."
                    )

        return cleaned_data


class BulkRoleAssignmentForm(forms.Form):
    """Form for bulk assigning roles to multiple users"""

    users = forms.ModelMultipleChoiceField(
        queryset=None,
        widget=forms.CheckboxSelectMultiple,
        label="Select Users"
    )

    role = forms.ModelChoiceField(
        queryset=None,
        widget=forms.Select(attrs={'class': 'form-select'}),
        label="Role to Assign"
    )

    action = forms.ChoiceField(
        choices=[
            ('add', 'Add role to selected users'),
            ('remove', 'Remove role from selected users'),
            ('replace', 'Replace all roles with this role')
        ],
        widget=forms.RadioSelect,
        initial='add'
    )

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)

        # Set querysets based on company
        from django.contrib.auth import get_user_model
        User = get_user_model()

        if company:
            self.fields['users'].queryset = User.objects.filter(
                company=company, is_active=True
            )
            self.fields['role'].queryset = Role.objects.filter(
                Q(company=company) | Q(is_system_role=True),
                is_active=True
            )
        else:
            self.fields['users'].queryset = User.objects.filter(is_active=True)
            self.fields['role'].queryset = Role.objects.filter(is_active=True)

class UserRoleAssignForm(forms.Form):
    users = forms.ModelMultipleChoiceField(
        queryset=CustomUser.objects.all(),
        widget=forms.SelectMultiple(attrs={'class': 'form-control'}),
        required=True,
        label="Select Users"
    )
    role = forms.ModelChoiceField(
        queryset=Role.objects.all(),
        widget=forms.Select(attrs={'class': 'form-control'}),
        required=True,
        label="Select Role"
    )

    def clean(self):
        cleaned_data = super().clean()
        role = cleaned_data.get('role')
        users = cleaned_data.get('users')

        # Validate max_users capacity
        if role and role.max_users:
            available_slots = role.max_users - role.user_count
            if len(users) > available_slots:
                raise forms.ValidationError(
                    f"Cannot assign {len(users)} users. Only {available_slots} slots available for this role."
                )
        return cleaned_data

class RoleFilterForm(forms.Form):
    """Form for filtering roles in list view"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search roles...',
            'data-bs-toggle': 'tooltip',
            'title': 'Search by role name or description'
        })
    )

    company = forms.ModelChoiceField(
        queryset=Company.objects.all(),
        required=False,
        empty_label="All Companies",
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    is_system_role = forms.ChoiceField(
        choices=[
            ('', 'All Roles'),
            ('true', 'System Roles Only'),
            ('false', 'Custom Roles Only')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    is_active = forms.ChoiceField(
        choices=[
            ('', 'All Status'),
            ('true', 'Active Only'),
            ('false', 'Inactive Only')
        ],
        required=False,
        widget=forms.Select(attrs={'class': 'form-select'})
    )


class CustomUserCreationForm(UserCreationForm):
    """
    Enhanced user creation form - ROLE-BASED ONLY
    No user_type field - users get roles directly
    """

    first_name = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter first name'
        })
    )
    company = forms.ModelChoiceField(
        queryset=Company.objects.all(),
        required=False,
        widget=forms.Select(attrs={
            'class': 'form-select',
        }),
        help_text='Company this user belongs to (SaaS admins only)'
    )
    last_name = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter last name'
        })
    )
    middle_name = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter middle name (optional)'
        })
    )
    phone_number = forms.CharField(
        max_length=20,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': '+256700000000'
        })
    )

    # ✅ ONLY ROLE SELECTION - NO USER_TYPE
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.none(),
        required=True,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-check-input'
        }),
        help_text="Select one or more roles for this user. Roles determine what the user can do."
    )

    class Meta:
        model = CustomUser
        fields = (
            'email','company', 'username', 'first_name', 'last_name', 'middle_name',
            'phone_number', 'roles', 'password1', 'password2'
        )
        widgets = {
            'email': forms.EmailInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter email address'
            }),
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter username'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        if self.request and hasattr(self.request, 'user'):
            current_user = self.request.user

            # ✅ Filter roles based on user's hierarchy
            accessible_roles = Role.get_accessible_roles_for_user(current_user)
            self.fields['roles'].queryset = accessible_roles

            logger.debug(
                f"User {current_user.email} can assign {accessible_roles.count()} roles"
            )

        # If SAAS_ADMIN, allow selecting company
        if self.request and getattr(self.request.user, "is_saas_admin", False):
            self.fields['company'] = forms.ModelChoiceField(
                queryset=Company.objects.all(),
                required=True,
                widget=forms.Select(attrs={'class': 'form-select'})
            )

    def clean_roles(self):
        """Validate that user can assign selected roles"""
        roles = self.cleaned_data.get('roles')

        if not roles:
            raise ValidationError(_('At least one role must be selected'))

        if not self.request or not hasattr(self.request, 'user'):
            raise ValidationError(_('Invalid request context'))

        current_user = self.request.user

        # Check each role
        for role in roles:
            can_assign, reason = role.can_be_assigned_by(current_user)
            if not can_assign:
                raise ValidationError(
                    _(f'Cannot assign role "{role.group.name}": {reason}')
                )

        return roles

    def clean_phone_number(self):
        """Validate phone number format"""
        phone_number = self.cleaned_data.get('phone_number')
        if phone_number:
            if not phone_number.startswith('+'):
                raise ValidationError(_('Phone number must include country code (e.g., +256)'))
            if not re.match(r'^\+\d{10,15}$', phone_number):
                raise ValidationError(_('Invalid phone number format'))
        return phone_number

    def save(self, commit=True):
        user = super().save(commit=False)

        # Assign company
        if self.request:
            current_user = self.request.user

            if hasattr(current_user, 'is_saas_admin') and current_user.is_saas_admin:
                company = self.cleaned_data.get('company')
                if company:
                    user.company = company
            elif hasattr(current_user, 'company'):
                user.company = current_user.company

        if commit:
            user.save()

            # ✅ Assign roles (M2M must be done after save)
            roles = self.cleaned_data.get('roles', [])
            user.groups.set([role.group for role in roles])

            # Log role assignments
            for role in roles:
                RoleHistory.objects.create(
                    role=role,
                    action='assigned',
                    user=self.request.user if self.request else None,
                    affected_user=user,
                    notes="Role assigned during user creation"
                )

            logger.info(f"✅ Created user {user.email} with roles: {[r.group.name for r in roles]}")

        return user


class CustomUserChangeForm(UserChangeForm):
    """
    Enhanced user change form - ROLE-BASED ONLY
    """

    password = None  # Remove password field

    # ✅ Add roles field for editing
    roles = forms.ModelMultipleChoiceField(
        queryset=Role.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-check-input'
        }),
        help_text="Select roles for this user"
    )

    class Meta:
        model = CustomUser
        fields = ('email', 'username', 'first_name', 'last_name', 'middle_name',
                  'phone_number', 'roles', 'is_active', 'is_staff',
                  'avatar', 'bio', 'timezone', 'language')
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'avatar': forms.FileInput(attrs={'class': 'form-control'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'timezone': forms.TextInput(attrs={'class': 'form-control'}),
            'language': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        # ✅ Filter roles based on current user's permissions
        if self.request and hasattr(self.request, 'user'):
            current_user = self.request.user
            accessible_roles = Role.get_accessible_roles_for_user(current_user)
            self.fields['roles'].queryset = accessible_roles

            # Set initial roles
            if self.instance and self.instance.pk:
                self.fields['roles'].initial = self.instance.all_roles

    def save(self, commit=True):
        user = super().save(commit=False)

        if commit:
            user.save()

            # ✅ Update roles if changed
            if 'roles' in self.cleaned_data:
                new_roles = set(self.cleaned_data['roles'])
                old_roles = set(user.all_roles)

                # Roles to remove
                for role in old_roles - new_roles:
                    user.groups.remove(role.group)
                    RoleHistory.objects.create(
                        role=role,
                        action='removed',
                        user=self.request.user if self.request else None,
                        affected_user=user,
                        notes="Role removed during user update"
                    )

                # Roles to add
                for role in new_roles - old_roles:
                    user.groups.add(role.group)
                    RoleHistory.objects.create(
                        role=role,
                        action='assigned',
                        user=self.request.user if self.request else None,
                        affected_user=user,
                        notes="Role assigned during user update"
                    )

        return user


class CustomAuthenticationForm(AuthenticationForm):
    """Enhanced authentication form with 2FA support"""

    username = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': _('Enter your email'),
            'autofocus': True,
            'autocomplete': 'email'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-lg',
            'placeholder': _('Enter your password'),
            'autocomplete': 'current-password'
        })
    )
    remember_me = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label=_("Remember me")
    )
    code = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-lg otp-input',
            'placeholder': _('Enter 6-digit code'),
            'maxlength': '6',
            'autocomplete': 'one-time-code'
        }),
        label=_("Two-Factor Authentication Code")
    )

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.request = request
        self.user_cache = None


    def clean_username(self):
        """Validate email field - with tenant schema awareness"""
        username = self.cleaned_data.get('username', '').strip()

        if not username:
            raise forms.ValidationError(_('Email is required.'))

        if '@' not in username:
            raise forms.ValidationError(_('Please enter a valid email address.'))

        # Get current schema from connection
        from django.db import connection

        schema_name = getattr(connection, 'schema_name', 'public')

        # Skip user validation if we're in public schema or schema not initialized
        if schema_name == 'public' or not schema_name:
            logger.warning(f"Login form validation in public schema - skipping user check")
            return username

        # Check if schema has the accounts_customuser table
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = 'accounts_customuser'
                    )
                """, [schema_name])

                table_exists = cursor.fetchone()[0]

                if not table_exists:
                    logger.warning(f"accounts_customuser table not found in schema {schema_name}")
                    # Schema not ready, skip validation
                    # Authentication will handle this properly
                    return username
        except Exception as e:
            logger.error(f"Error checking schema tables: {e}")
            # On error, skip validation and let authentication handle it
            return username

        # Now safe to query users
        try:
            user = CustomUser.objects.get(email=username)
            if not user.is_active:
                raise forms.ValidationError(
                    _('This account has been deactivated. Please contact support.')
                )
            if hasattr(user, 'is_locked') and user.is_locked:
                raise forms.ValidationError(
                    _('Account is temporarily locked. Please try again later or reset your password.')
                )
        except CustomUser.DoesNotExist:
            pass

        return username

    def clean_password(self):
        """Validate password field"""
        password = self.cleaned_data.get('password')

        if not password:
            raise forms.ValidationError(_('Password is required.'))

        return password

    def clean_code(self):
        """Validate 2FA code format"""
        code = self.cleaned_data.get('code', '').strip()

        if code:
            if not code.isdigit():
                raise forms.ValidationError(_('Code must contain only numbers.'))
            if len(code) != 6:
                raise forms.ValidationError(_('Code must be exactly 6 digits.'))

        return code

    def clean(self):
        """
        Validate credentials WITH schema awareness
        ✅ CRITICAL FIX: Check schema BEFORE calling authenticate
        """
        from django.db import connection

        cleaned_data = super(AuthenticationForm, self).clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')

        if not username or not password:
            return cleaned_data

        # ✅ CHECK SCHEMA FIRST!
        schema_name = getattr(connection, 'schema_name', 'public')

        # ✅ If in public schema, don't try to authenticate tenant users
        if schema_name == 'public':
            logger.warning(f"Login attempt in public schema for {username} - authentication skipped")
            raise forms.ValidationError(
                _('Please access the application through your company subdomain.'),
                code='wrong_schema'
            )

        # ✅ Check if schema has required tables
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables 
                        WHERE table_schema = %s AND table_name = 'accounts_customuser'
                    )
                """, [schema_name])

                table_exists = cursor.fetchone()[0]

                if not table_exists:
                    logger.error(f"Schema {schema_name} missing accounts_customuser table")
                    raise forms.ValidationError(
                        _('Database not properly initialized. Please contact support.'),
                        code='schema_not_ready'
                    )
        except forms.ValidationError:
            raise
        except Exception as e:
            logger.error(f"Error checking schema tables: {e}")
            raise forms.ValidationError(
                _('Database error. Please try again later.'),
                code='database_error'
            )

        # ✅ NOW safe to authenticate (we're in tenant schema with proper tables)
        try:
            self.user_cache = authenticate(
                self.request,
                username=username,
                password=password
            )
        except Exception as e:
            logger.error(f"Authentication error in schema {schema_name}: {e}")
            raise forms.ValidationError(
                _('Authentication failed. Please try again.'),
                code='auth_error'
            )

        if self.user_cache is None:
            # Record failed attempt WITHOUT leaking whether the email/password was wrong
            try:
                from accounts.models import CustomUser
                user = CustomUser.objects.get(email=username)
                user.record_login_attempt(success=False, ip_address=self.get_client_ip())
            except CustomUser.DoesNotExist:
                pass  # Silently ignore — don't reveal that the email doesn't exist

            # Always raise the same generic error regardless of the failure reason
            raise forms.ValidationError(
                _('Invalid email or password. Please try again.'),
                code='invalid_login'
            )
        else:
            # Valid credentials - check if account is active
            if not self.user_cache.is_active:
                raise forms.ValidationError(
                    _('This account has been deactivated. Please contact support.'),
                    code='inactive'
                )

        return cleaned_data

    def get_user(self):
        """Return the authenticated user, always as a CustomUser instance"""
        user = self.user_cache
        if user is None:
            return None
        if isinstance(user, CustomUser):
            return user
        # Backend returned a non-CustomUser — re-fetch the correct instance
        try:
            backend = getattr(user, 'backend', 'django.contrib.auth.backends.ModelBackend')
            fetched = CustomUser.objects.get(pk=user.pk)
            fetched.backend = backend  # preserve backend for login()
            self.user_cache = fetched
            return fetched
        except CustomUser.DoesNotExist:
            return None

    def get_client_ip(self):
        """Get client IP from request"""
        if hasattr(self, 'request') and self.request:
            x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                return x_forwarded_for.split(',')[0]
            return self.request.META.get('REMOTE_ADDR')
        return None

class CompanyUserForm(forms.ModelForm):
    """Form for managing company user relationships"""
    email = forms.EmailField(required=True)
    username = forms.CharField(required=True)
    first_name = forms.CharField(required=False)
    last_name = forms.CharField(required=False)
    phone_number = forms.CharField(required=False)
    is_company_admin = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )

    class Meta:
        model = CustomUser
        fields = ['email', 'username', 'first_name', 'last_name', 'phone_number', 'is_active']
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def __init__(self, *args, **kwargs):
        self.company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk and self.company:
            # Set initial value for company admin status
            self.fields['is_company_admin'].initial = self.company in self.instance.company_admin_for.all()

    def save(self, commit=True):
        user = super().save(commit=False)

        if commit:
            user.save()

            # Handle company admin relationship
            if self.company:
                is_admin = self.cleaned_data.get('is_company_admin', False)
                if is_admin:
                    user.company_admin_for.add(self.company)
                else:
                    user.company_admin_for.remove(self.company)

        return user


class UserProfileForm(forms.ModelForm):
    """Enhanced user profile update form with better validation and widgets"""

    # Override avatar field with custom validation
    avatar = forms.ImageField(
        required=False,
        validators=[
            FileExtensionValidator(allowed_extensions=['jpg', 'jpeg', 'png', 'gif'])
        ],
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*',
            'id': 'avatarInput'
        }),
        help_text='Upload an image file (JPG, PNG, GIF). Max size: 5MB'
    )

    # Custom bio field with character counter
    bio = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Tell us about yourself, your role, and your interests...',
            'maxlength': '500'
        }),
        help_text='Maximum 500 characters'
    )

    # Enhanced timezone field with grouped options
    timezone = forms.ChoiceField(
        choices=[],  # Will be populated in __init__
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        help_text='Select your timezone for accurate timestamps'
    )

    class Meta:
        model = CustomUser
        fields = [
            'first_name', 'last_name', 'middle_name', 'phone_number',
            'avatar', 'bio', 'timezone', 'language'
        ]
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your first name',
                'maxlength': '50'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your last name',
                'maxlength': '50'
            }),
            'middle_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your middle name (optional)',
                'maxlength': '50'
            }),
            'phone_number': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '+256700000000',
                'pattern': r'^\+?[1-9]\d{1,14}$',
                'title': 'Enter a valid phone number with country code'
            }),
            'language': forms.Select(attrs={
                'class': 'form-select'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Populate timezone choices with grouped options
        self.fields['timezone'].choices = self.get_timezone_choices()

        # Add custom CSS classes and attributes
        for field_name, field in self.fields.items():
            if field_name != 'avatar':  # Avatar has special handling
                field.widget.attrs.update({'class': f"{field.widget.attrs.get('class', '')} auto-save"})

        # Set initial values if instance exists
        if self.instance and self.instance.pk:
            self.fields['timezone'].initial = self.instance.timezone

    def get_timezone_choices(self):
        """
        Get timezone choices grouped by continent for better UX
        """
        timezone_choices = []

        # Common/Popular timezones first
        popular_timezones = [
            ('Africa/Kampala', 'Kampala (EAT)'),
            ('UTC', 'UTC'),
            ('Europe/London', 'London (GMT/BST)'),
            ('America/New_York', 'New York (EST/EDT)'),
            ('America/Los_Angeles', 'Los Angeles (PST/PDT)'),
            ('Asia/Tokyo', 'Tokyo (JST)'),
            ('Australia/Sydney', 'Sydney (AEST/AEDT)'),
        ]

        timezone_choices.append(('Popular', popular_timezones))

        # Group timezones by continent
        continents = {
            'Africa': [],
            'America': [],
            'Asia': [],
            'Europe': [],
            'Australia': [],
            'Other': []
        }

        # Get all timezones and group them
        all_timezones = pytz.all_timezones
        for tz in sorted(all_timezones):
            # Skip already added popular timezones
            if any(tz == popular[0] for popular in popular_timezones):
                continue

            continent = tz.split('/')[0] if '/' in tz else 'Other'
            display_name = tz.replace('_', ' ').split('/')[-1]

            if continent in continents:
                continents[continent].append((tz, f"{display_name} ({tz})"))
            else:
                continents['Other'].append((tz, f"{display_name} ({tz})"))

        # Add continent groups to choices
        for continent, timezones in continents.items():
            if timezones:  # Only add non-empty groups
                timezone_choices.append((continent, timezones[:20]))  # Limit to 20 per group

        return timezone_choices

    def clean_avatar(self):
        """
        Validate avatar upload
        """
        avatar = self.cleaned_data.get('avatar')
        if avatar:
            # Check file size (5MB limit)
            if avatar.size > 5 * 1024 * 1024:
                raise ValidationError('Avatar file size cannot exceed 5MB.')

            # Check file type
            if not avatar.content_type.startswith('image/'):
                raise ValidationError('Avatar must be an image file.')

            # Check dimensions (optional)
            try:
                from PIL import Image
                img = Image.open(avatar)
                width, height = img.size

                # Warn if image is too small
                if width < 100 or height < 100:
                    raise ValidationError('Avatar image should be at least 100x100 pixels.')

                # Warn if image is too large
                if width > 2000 or height > 2000:
                    raise ValidationError('Avatar image should not exceed 2000x2000 pixels.')

            except Exception:
                raise ValidationError('Invalid image file.')

        return avatar

    def clean_phone_number(self):
        """Validate phone number format"""
        phone_number = self.cleaned_data.get('phone_number')
        if phone_number:
            if not phone_number.startswith('+'):
                raise ValidationError(_('Phone number must include country code (e.g., +256)'))
            if not re.match(r'^\+\d{10,15}$', phone_number):
                raise ValidationError(_('Invalid phone number format'))
        return phone_number

    def clean_bio(self):
        """
        Clean and validate bio text
        """
        bio = self.cleaned_data.get('bio', '').strip()
        if bio:
            # Remove excessive whitespace
            bio = ' '.join(bio.split())

            # Check for minimum meaningful length
            if len(bio) < 10 and bio:
                raise ValidationError('Bio should be at least 10 characters if provided.')

        return bio

    def clean(self):
        """
        Perform cross-field validation
        """
        cleaned_data = super().clean()

        # Ensure at least first or last name is provided
        first_name = cleaned_data.get('first_name', '').strip()
        last_name = cleaned_data.get('last_name', '').strip()

        if not first_name and not last_name:
            raise ValidationError('Please provide at least a first name or last name.')

        return cleaned_data

    def save(self, commit=True):
        """
        Enhanced save method with additional processing
        """
        user = super().save(commit=False)

        # Process names - capitalize first letters
        if user.first_name:
            user.first_name = user.first_name.strip().title()
        if user.last_name:
            user.last_name = user.last_name.strip().title()
        if user.middle_name:
            user.middle_name = user.middle_name.strip().title()

        if commit:
            user.save()
            # Update last activity timestamp
            from django.utils import timezone
            user.last_activity_at = timezone.now()
            user.save(update_fields=['last_activity_at'])

        return user


class UserSecurityForm(forms.ModelForm):
    """
    Separate form for security settings
    """
    current_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter current password'
        }),
        required=False,
        help_text='Required when changing security settings'
    )

    class Meta:
        model = CustomUser
        fields = ['two_factor_enabled']
        widgets = {
            'two_factor_enabled': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

    def clean_current_password(self):
        """
        Validate current password if security changes are being made
        """
        current_password = self.cleaned_data.get('current_password')

        # Only require current password if we're enabling 2FA
        if self.cleaned_data.get('two_factor_enabled') and not self.instance.two_factor_enabled:
            if not current_password:
                raise ValidationError('Current password is required to enable two-factor authentication.')

            if not self.instance.check_password(current_password):
                raise ValidationError('Current password is incorrect.')

        return current_password


class UserNotificationForm(forms.ModelForm):
    """
    Form for managing user notification preferences
    """
    email_notifications = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        help_text='Receive notifications via email'
    )

    sms_notifications = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        help_text='Receive notifications via SMS (requires verified phone)'
    )

    marketing_emails = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        help_text='Receive marketing and promotional emails'
    )

    class Meta:
        model = CustomUser
        fields = []  # We'll handle these in metadata field

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Load current preferences from metadata
        if self.instance and self.instance.metadata:
            notifications = self.instance.metadata.get('notifications', {})
            self.fields['email_notifications'].initial = notifications.get('email', True)
            self.fields['sms_notifications'].initial = notifications.get('sms', False)
            self.fields['marketing_emails'].initial = notifications.get('marketing', False)

    def save(self, commit=True):
        """
        Save notification preferences to user metadata
        """
        user = super().save(commit=False)

        # Initialize metadata if it doesn't exist
        if not user.metadata:
            user.metadata = {}

        # Save notification preferences
        user.metadata['notifications'] = {
            'email': self.cleaned_data.get('email_notifications', True),
            'sms': self.cleaned_data.get('sms_notifications', False),
            'marketing': self.cleaned_data.get('marketing_emails', False),
        }

        if commit:
            user.save()

        return user


class UserPreferencesForm(forms.Form):
    """
    Form for advanced user preferences
    """
    theme = forms.ChoiceField(
        choices=[
            ('light', 'Light Theme'),
            ('dark', 'Dark Theme'),
            ('auto', 'Auto (System)'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        initial='light',
        help_text='Choose your preferred interface theme'
    )

    items_per_page = forms.ChoiceField(
        choices=[
            ('10', '10 items'),
            ('25', '25 items'),
            ('50', '50 items'),
            ('100', '100 items'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        initial='25',
        help_text='Number of items to display per page'
    )

    date_format = forms.ChoiceField(
        choices=[
            ('d/m/Y', 'DD/MM/YYYY'),
            ('m/d/Y', 'MM/DD/YYYY'),
            ('Y-m-d', 'YYYY-MM-DD'),
            ('d M Y', 'DD Mon YYYY'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        initial='d/m/Y',
        help_text='Preferred date display format'
    )

    currency_format = forms.ChoiceField(
        choices=[
            ('UGX', 'UGX (Ugandan Shilling)'),
            ('USD', 'USD (US Dollar)'),
            ('EUR', 'EUR (Euro)'),
            ('GBP', 'GBP (British Pound)'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        initial='UGX',
        help_text='Preferred currency for display'
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

        # Load current preferences from metadata
        if user.metadata:
            prefs = user.metadata.get('preferences', {})
            for field_name, field in self.fields.items():
                if field_name in prefs:
                    field.initial = prefs[field_name]

    def save(self):
        """
        Save preferences to user metadata
        """
        if not self.user.metadata:
            self.user.metadata = {}

        if 'preferences' not in self.user.metadata:
            self.user.metadata['preferences'] = {}

        # Save all form fields to preferences
        for field_name in self.fields.keys():
            self.user.metadata['preferences'][field_name] = self.cleaned_data[field_name]

        self.user.save()
        return self.user

class PasswordChangeForm(forms.Form):
    """Custom password change form"""

    old_password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Current Password'
        })
    )
    new_password1 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'New Password'
        }),
        help_text=_('Password must be at least 8 characters long and contain letters and numbers.')
    )
    new_password2 = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Confirm New Password'
        })
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self):
        old_password = self.cleaned_data["old_password"]
        if not self.user.check_password(old_password):
            raise ValidationError(_('Your old password was entered incorrectly.'))
        return old_password

    def clean_new_password2(self):
        password1 = self.cleaned_data.get('new_password1')
        password2 = self.cleaned_data.get('new_password2')
        if password1 and password2:
            if password1 != password2:
                raise ValidationError(_('The two password fields didn\'t match.'))
        return password2

    def save(self):
        password = self.cleaned_data["new_password1"]
        self.user.set_password(password)
        self.user.password_changed_at = timezone.now()
        self.user.save()
        return self.user


class UserSignatureForm(forms.ModelForm):
    """User signature form"""

    class Meta:
        model = UserSignature
        fields = ['signature_image', 'signature_data']
        widgets = {
            'signature_image': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/*'
            }),
            'signature_data': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Digital signature data...'
            }),
        }


class UserSearchForm(forms.Form):
    """Advanced user search form"""

    search_query = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by name, email, or username...'
        })
    )
    is_active = forms.ChoiceField(
        required=False,
        choices=[('', 'All'), ('true', 'Active'), ('false', 'Inactive')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    email_verified = forms.ChoiceField(
        required=False,
        choices=[('', 'All'), ('true', 'Verified'), ('false', 'Unverified')],
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    date_joined_from = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )
    date_joined_to = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={
            'class': 'form-control',
            'type': 'date'
        })
    )


class BulkUserActionForm(forms.Form):
    """Form for bulk user actions"""

    ACTION_CHOICES = [
        ('activate', _('Activate Selected Users')),
        ('deactivate', _('Deactivate Selected Users')),
        ('delete', _('Delete Selected Users')),
        ('export', _('Export Selected Users')),
    ]

    action = forms.ChoiceField(
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    selected_users = forms.CharField(
        widget=forms.HiddenInput()
    )

    def clean_selected_users(self):
        user_ids = self.cleaned_data['selected_users']
        if not user_ids:
            raise ValidationError(_('No users selected.'))
        try:
            user_ids = [int(id.strip()) for id in user_ids.split(',') if id.strip()]
            if not user_ids:
                raise ValidationError(_('No valid user IDs provided.'))
        except ValueError:
            raise ValidationError(_('Invalid user IDs provided.'))
        return user_ids


class TwoFactorSetupForm(forms.Form):
    """Two-factor authentication setup form"""

    verification_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control text-center',
            'placeholder': '000000',
            'maxlength': '6',
            'pattern': '[0-9]{6}'
        })
    )

    def clean_verification_code(self):
        code = self.cleaned_data['verification_code']
        if not code.isdigit():
            raise ValidationError(_('Verification code must contain only numbers.'))
        return code

class APITokenForm(forms.ModelForm):
    """Form for creating and editing API tokens"""

    class Meta:
        model = APIToken
        fields = ['name', 'token_type', 'expires_at']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Mobile App Token, CI/CD Integration',
            }),
            'token_type': forms.Select(attrs={
                'class': 'form-select',
            }),
            'expires_at': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local',
            }),
        }
        help_texts = {
            'name': 'A descriptive label so you can identify this token later.',
            'token_type': 'Controls what operations this token can perform.',
            'expires_at': 'Leave blank for a token that never expires.',
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        token = super().save(commit=False)
        if self.user:
            token.user = self.user
        if commit:
            token.save()
        return token


class UserSessionFilterForm(forms.Form):
    """Form for filtering/searching user sessions"""

    search = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by IP address or device...',
        }),
    )
    is_active = forms.ChoiceField(
        required=False,
        choices=[('', 'All Sessions'), ('true', 'Active Only'), ('false', 'Inactive Only')],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )
    device_type = forms.ChoiceField(
        required=False,
        choices=[
            ('', 'All Devices'),
            ('desktop', 'Desktop'),
            ('mobile', 'Mobile'),
            ('tablet', 'Tablet'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
    )


class ReviewAuditLogForm(forms.Form):
    """Form for reviewing a flagged audit log entry."""

    ACTION_CHOICES = [
        ('', _('No Action')),
        ('acknowledge', _('Acknowledge — noted, no further action needed')),
        ('investigate', _('Investigate — mark for further investigation')),
        ('escalate', _('Escalate — escalate to senior administrator')),
        ('dismiss', _('Dismiss — false positive, dismiss the flag')),
    ]

    notes = forms.CharField(
        required=False,
        label=_('Review Notes'),
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 4,
            'placeholder': 'Add your review notes, observations, or any follow-up actions taken...',
            'maxlength': '2000',
        }),
        max_length=2000,
        help_text=_('Optional notes about this audit log entry (max 2000 characters).')
    )

    action = forms.ChoiceField(
        required=False,
        label=_('Review Action'),
        choices=ACTION_CHOICES,
        widget=forms.Select(attrs={
            'class': 'form-select',
        }),
        help_text=_('Select an action to take on this audit log entry.')
    )

    def clean(self):
        cleaned_data = super().clean()
        action = cleaned_data.get('action')
        notes = cleaned_data.get('notes', '').strip()

        # Require notes when escalating or investigating
        if action in ('investigate', 'escalate') and not notes:
            raise ValidationError(
                _('Please provide review notes when marking an entry for investigation or escalation.')
            )

        cleaned_data['notes'] = notes
        return cleaned_data