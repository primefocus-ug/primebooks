from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm, AuthenticationForm
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.core.validators import FileExtensionValidator
import pytz
from django.contrib.auth.models import Group, Permission
from django.db.models import Q
from company.models import Company
from .models import CustomUser, UserSignature,Role, RoleHistory
import re
from django.contrib.auth.forms import SetPasswordForm as DjangoSetPasswordForm
from .models import Role, CustomUser
from django.core.exceptions import ValidationError
import logging
from django import forms
from django.contrib.auth.models import Group, Permission
from .models import Role
from django.core.exceptions import ValidationError

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
    """Form for bulk assigning users to roles"""

    users = forms.ModelMultipleChoiceField(
        queryset=None,  # Set in __init__
        widget=forms.CheckboxSelectMultiple(attrs={
            'class': 'form-check-input',
        }),
        required=True,
        label='Select Users',
    )

    role = forms.ModelChoiceField(
        queryset=None,  # Set in __init__
        widget=forms.Select(attrs={
            'class': 'form-select',
        }),
        required=True,
        label='Assign to Role',
    )

    def __init__(self, *args, **kwargs):
        company = kwargs.pop('company', None)
        super().__init__(*args, **kwargs)

        if company:
            from .models import CustomUser

            # Only show visible users from this company
            self.fields['users'].queryset = CustomUser.objects.filter(
                company=company,
                is_hidden=False,
                is_active=True,
            ).order_by('first_name', 'last_name')

            # Only show active roles for this company
            self.fields['role'].queryset = Role.objects.filter(
                company=company,
                is_active=True,
            ).select_related('group')

    def clean(self):
        cleaned_data = super().clean()
        users = cleaned_data.get('users')
        role = cleaned_data.get('role')

        if users and role:
            # Check if role has capacity
            if role.max_users:
                current_count = role.user_count
                new_count = current_count + users.count()

                if new_count > role.max_users:
                    raise ValidationError(
                        f"Cannot assign {users.count()} users to '{role.group.name}'. "
                        f"Role capacity: {current_count}/{role.max_users} users. "
                        f"Available slots: {role.max_users - current_count}."
                    )

        return



# class RoleForm(forms.ModelForm):
#     """Advanced role creation/editing form with enhanced UX"""
#
#     name = forms.CharField(
#         label="Role Name",
#         max_length=150,
#         widget=forms.TextInput(attrs={
#             'class': 'form-control',
#             'placeholder': 'Enter role name (e.g., Sales Manager)',
#             'data-bs-toggle': 'tooltip',
#             'data-bs-placement': 'top',
#             'title': 'Choose a descriptive name for this role'
#         }),
#         help_text="A clear, descriptive name for this role"
#     )
#
#     permissions = forms.ModelMultipleChoiceField(
#         queryset=Permission.objects.select_related('content_type').all(),
#         widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
#         required=False,
#         label="Permissions",
#         help_text="Select the permissions this role should have"
#     )
#
#     class Meta:
#         model = Role
#         fields = [
#             'company', 'description', 'is_system_role', 'is_active',
#             'priority', 'color_code', 'max_users'
#         ]
#         widgets = {
#             'company': forms.Select(attrs={
#                 'class': 'form-select',
#                 'data-bs-toggle': 'tooltip',
#                 'title': 'Select which company this role belongs to'
#             }),
#             'description': forms.Textarea(attrs={
#                 'class': 'form-control',
#                 'rows': 3,
#                 'placeholder': 'Describe the responsibilities and purpose of this role...'
#             }),
#             'is_system_role': forms.CheckboxInput(attrs={
#                 'class': 'form-check-input',
#                 'data-bs-toggle': 'tooltip',
#                 'title': 'System roles are built-in and have special restrictions'
#             }),
#             'is_active': forms.CheckboxInput(attrs={
#                 'class': 'form-check-input',
#                 'data-bs-toggle': 'tooltip',
#                 'title': 'Only active roles can be assigned to users'
#             }),
#             'priority': forms.NumberInput(attrs={
#                 'class': 'form-control',
#                 'min': '0',
#                 'max': '999',
#                 'data-bs-toggle': 'tooltip',
#                 'title': 'Higher priority roles appear first in lists (0-999)'
#             }),
#             'color_code': forms.TextInput(attrs={
#                 'type': 'color',
#                 'class': 'form-control form-control-color',
#                 'data-bs-toggle': 'tooltip',
#                 'title': 'Choose a color for role badges and UI elements'
#             }),
#             'max_users': forms.NumberInput(attrs={
#                 'class': 'form-control',
#                 'min': '1',
#                 'placeholder': 'Leave empty for unlimited',
#                 'data-bs-toggle': 'tooltip',
#                 'title': 'Maximum number of users that can have this role'
#             }),
#         }
#         help_texts = {
#             'priority': 'Higher numbers appear first in role lists',
#             'max_users': 'Leave empty for unlimited users',
#         }
#
#     def __init__(self, *args, **kwargs):
#         self.request = kwargs.pop('request', None)
#         super().__init__(*args, **kwargs)
#
#         # Set initial values for existing role
#         if self.instance and self.instance.pk and hasattr(self.instance, "group"):
#             self.fields["name"].initial = self.instance.group.name
#             self.fields["permissions"].initial = self.instance.group.permissions.all()
#
#         # Organize permissions by app for better UX
#         self._organize_permissions()
#
#         # Customize form based on user permissions
#         if self.request and self.request.user:
#             self._customize_for_user()
#
#     def _organize_permissions(self):
#         """Group permissions by app for better organization in template"""
#         permissions = Permission.objects.select_related('content_type').order_by(
#             'content_type__app_label', 'content_type__model', 'codename'
#         )
#
#         grouped_permissions = defaultdict(list)
#         for perm in permissions:
#             app_name = perm.content_type.app_label.replace('_', ' ').title()
#             grouped_permissions[app_name].append(perm)
#
#         self.grouped_permissions = dict(grouped_permissions)
#
#     def _customize_for_user(self):
#         """Customize form fields based on user's permissions"""
#         user = self.request.user
#
#         # Only superusers or users with specific permission can create system roles
#         if not (user.is_superuser or user.has_perm('accounts.can_manage_system_roles')):
#             self.fields['is_system_role'].widget = forms.HiddenInput()
#             self.fields['is_system_role'].initial = False
#
#         # Filter companies based on user's access
#         if not user.is_superuser:
#             # Assuming user has access to specific companies
#             accessible_companies = Company.objects.filter(
#                 Q(users=user) | Q(created_by=user)
#             ).distinct()
#             self.fields['company'].queryset = accessible_companies
#
#     def clean_name(self):
#         """Validate role name uniqueness"""
#         name = self.cleaned_data['name']
#         company = self.cleaned_data.get('company')
#
#         # Check for existing groups with same name
#         existing_query = Group.objects.filter(name__iexact=name)
#         if self.instance and self.instance.pk:
#             existing_query = existing_query.exclude(pk=self.instance.group.pk)
#
#         if existing_query.exists():
#             raise ValidationError(
#                 f"A role with the name '{name}' already exists. Please choose a different name."
#             )
#
#         return name
#
#     def clean_max_users(self):
#         """Validate max_users doesn't conflict with current assignments"""
#         max_users = self.cleaned_data.get('max_users')
#
#         if max_users and self.instance and self.instance.pk:
#             current_users = self.instance.user_count
#             if current_users > max_users:
#                 raise ValidationError(
#                     f"Cannot set maximum users to {max_users} because {current_users} "
#                     f"users currently have this role. Either increase the limit or "
#                     f"remove users from this role first."
#                 )
#
#         return max_users
#
#     def clean(self):
#         """Cross-field validation"""
#         cleaned_data = super().clean()
#         is_system_role = cleaned_data.get('is_system_role')
#         company = cleaned_data.get('company')
#
#         # System roles cannot be company-specific
#         if is_system_role and company:
#             raise ValidationError({
#                 'company': 'System roles cannot be assigned to a specific company.'
#             })
#
#         return cleaned_data
#
#     def save(self, commit=True):
#         """Enhanced save method with history tracking"""
#         role = super().save(commit=False)
#         is_new = not role.pk
#
#         # Handle the underlying Group
#         if not hasattr(role, 'group') or not role.group:
#             # Create new group
#             role.group = Group.objects.create(name=self.cleaned_data["name"])
#         else:
#             # Update existing group name
#             role.group.name = self.cleaned_data["name"]
#             role.group.save()
#
#         # Set created_by for new roles
#         if is_new and self.request and self.request.user:
#             role.created_by = self.request.user
#
#         if commit:
#             role.save()
#
#             # Assign permissions to the underlying Group
#             selected_permissions = self.cleaned_data.get("permissions", [])
#             role.group.permissions.set(selected_permissions)
#
#             # Create history record
#             self._create_history_record(role, is_new)
#
#         return role
#
#     def _create_history_record(self, role, is_new):
#         """Create a history record for audit purposes"""
#         if not self.request or not self.request.user:
#             return
#
#         action = 'created' if is_new else 'updated'
#         changes = {}
#
#         if not is_new:
#             # Track what changed
#             for field_name in self.changed_data:
#                 if field_name in self.cleaned_data:
#                     changes[field_name] = {
#                         'old': getattr(role, field_name, None),
#                         'new': self.cleaned_data[field_name]
#                     }
#
#         RoleHistory.objects.create(
#             role=role,
#             action=action,
#             user=self.request.user,
#             changes=changes,
#             notes=f"Role {action} via web interface"
#         )


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
    """Enhanced user creation form with company handling"""

    first_name = forms.CharField(
        max_length=50,
        required=True,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter first name'
        })
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
    user_type = forms.ChoiceField(
        choices=CustomUser.USER_TYPES,
        widget=forms.Select(attrs={
            'class': 'form-select'
        })
    )

    class Meta:
        model = CustomUser
        fields = (
            'email', 'username', 'first_name', 'last_name', 'middle_name',
            'phone_number', 'user_type', 'password1', 'password2'
            # 🔥 removed "company" here so it's not validated as required
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

        # If system admin, allow selecting company
        if self.request and getattr(self.request.user, "user_type", None) == 'SYSTEM_ADMIN':
            self.fields['company'] = forms.ModelChoiceField(
                queryset=CustomUser.objects.none(),  # replace with Company.objects.all()
                required=True,
                widget=forms.Select(attrs={'class': 'form-select'})
            )
            logger.debug("System admin detected — added company field to form")

    def clean_phone_number(self):
        """Validate phone number format"""
        phone_number = self.cleaned_data.get('phone_number')
        if phone_number:
            if not phone_number.startswith('+'):
                raise ValidationError(_('Phone number must include country code (e.g., +256)'))
            if not re.match(r'^\+\d{10,15}$', phone_number):
                raise ValidationError(_('Invalid phone number format'))
        return phone_number

    def assign_company(self, user):
        """
        Utility to assign company from request.user if not system admin.
        Called from view after form.save(commit=False).
        """
        if not self.request:
            logger.warning("assign_company called without request")
            return user

        current_user = self.request.user
        if current_user.user_type != 'SYSTEM_ADMIN':
            if hasattr(current_user, 'owned_company') and current_user.owned_company:
                user.company = current_user.owned_company
                logger.debug(f"Assigned company from owned_company: {user.company}")
            elif hasattr(current_user, 'company') and current_user.company:
                user.company = current_user.company
                logger.debug(f"Assigned company from current_user.company: {user.company}")
        else:
            # System admin: use chosen company field
            company = self.cleaned_data.get('company')
            if not company:
                raise ValidationError("System admin must select a company")
            user.company = company
            logger.debug(f"Assigned company from system admin selection: {user.company}")

        return user


class CustomUserChangeForm(UserChangeForm):
    """Enhanced user change form"""

    password = None  # Remove password field from change form

    class Meta:
        model = CustomUser
        fields = ('email', 'username', 'first_name', 'last_name', 'middle_name',
                  'phone_number', 'user_type', 'is_active', 'is_staff',
                  'avatar', 'bio', 'timezone', 'language')
        widgets = {
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'middle_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            'user_type': forms.Select(attrs={'class': 'form-select'}),
            'avatar': forms.FileInput(attrs={'class': 'form-control'}),
            'bio': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
            'timezone': forms.TextInput(attrs={'class': 'form-control'}),
            'language': forms.Select(attrs={'class': 'form-select'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_staff': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CustomAuthenticationForm(AuthenticationForm):
    """Enhanced authentication form with security features and 2FA support"""

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

    def clean(self):
        username = self.cleaned_data.get('username')
        password = self.cleaned_data.get('password')
        code = self.cleaned_data.get('code')

        if username and password:
            # Authenticate the user
            self.user_cache = authenticate(
                self.request,
                username=username,
                password=password
            )

            if self.user_cache is None:
                # Record failed login attempt
                try:
                    user = CustomUser.objects.get(email=username)
                    user.record_login_attempt(success=False, ip_address=self.get_client_ip())
                except CustomUser.DoesNotExist:
                    pass
                raise self.get_invalid_login_error()

            # Check if user is active
            if not self.user_cache.is_active:
                raise forms.ValidationError(_('This account has been deactivated.'))

            # Check if user is locked
            if self.user_cache.is_locked:
                raise forms.ValidationError(
                    _('Account is temporarily locked due to too many failed login attempts. Try again later.')
                )

            # Since 2FA validation is handled in the view, we only record successful credential validation here
            # Note: Do not call record_login_attempt(success=True) here, as it’s handled in the view after 2FA

        # Validate OTP code format (if provided)
        if code and not code.isdigit():
            raise forms.ValidationError(_('The 2FA code must contain only numbers.'))
        if code and len(code) != 6:
            raise forms.ValidationError(_('The 2FA code must be 6 digits long.'))

        return self.cleaned_data

    def get_client_ip(self):
        """Get client IP address from request"""
        if hasattr(self, 'request') and self.request:
            x_forwarded_for = self.request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0]
            else:
                ip = self.request.META.get('REMOTE_ADDR')
            return ip
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
        """
        Validate and format phone number
        """
        phone = self.cleaned_data.get('phone_number', '').strip()
        if phone:
            # Remove any non-digit characters except +
            import re
            cleaned_phone = re.sub(r'[^\d+]', '', phone)

            # Ensure it starts with + if it has country code
            if not cleaned_phone.startswith('+') and len(cleaned_phone) > 10:
                cleaned_phone = '+' + cleaned_phone

            # Basic validation for international format
            if not re.match(r'^\+?[1-9]\d{7,14}$', cleaned_phone):
                raise ValidationError('Please enter a valid phone number with country code.')

            return cleaned_phone
        return phone

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
    user_type = forms.ChoiceField(
        required=False,
        choices=[('', 'All Types')] + CustomUser.USER_TYPES,
        widget=forms.Select(attrs={'class': 'form-select'})
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