from django.db import models, connection
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.core.validators import MinLengthValidator
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from datetime import timedelta
import hashlib
from django.conf import settings
from django.contrib.auth.models import Group
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
import uuid
from primebooks.mixins import OfflineIDMixin


def validate_phone_number(value):
    """Enhanced phone number validation"""
    if value and not value.startswith('+'):
        raise ValidationError(_('Phone number must include country code (e.g., +256)'))


class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError(_('The Email field must be set'))

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, company=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('Superuser must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('Superuser must have is_superuser=True.'))

        # Handle company requirement
        if company is None:
            try:
                from company.models import Company, SubscriptionPlan
                company = Company.objects.filter(status__in=['ACTIVE', 'TRIAL']).first()

                if company is None:
                    free_plan, _ = SubscriptionPlan.objects.get_or_create(
                        name='FREE',
                        defaults={
                            'display_name': 'Free Trial',
                            'description': 'Default free trial plan',
                            'price': 0,
                            'trial_days': 60,
                            'max_users': 5,
                            'max_branches': 1,
                            'max_storage_gb': 1,
                            'max_api_calls_per_month': 1000,
                            'max_transactions_per_month': 500,
                        }
                    )

                    company = Company.objects.create(
                        name="Default Company",
                        trading_name="Default Company",
                        email=email,
                        schema_name="default_tenant",
                        plan=free_plan,
                        is_trial=True,
                        status='TRIAL',
                        trial_ends_at=timezone.now().date() + timedelta(days=60),
                    )

                    from company.models import Domain
                    Domain.objects.create(
                        tenant=company,
                        domain="default.localhost",
                        is_primary=True,
                        ssl_enabled=False
                    )
            except Exception as e:
                raise ValueError(f'Could not get or create company: {str(e)}')

        return self.create_user(email, password=password, company=company, **extra_fields)

    def create_saas_admin(self, email, password=None, **extra_fields):
        """Create a hidden SaaS admin user"""
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('is_saas_admin', True)
        extra_fields.setdefault('is_hidden', True)

        try:
            from company.models import Company
            placeholder_company = Company.objects.first()
            if not placeholder_company:
                raise ValueError('At least one company must exist to create SaaS admin')
            extra_fields['company'] = placeholder_company
        except Exception as e:
            raise ValueError(f'Could not assign placeholder company: {str(e)}')

        return self.create_user(email, password=password, **extra_fields)

    def active_users(self):
        """Return only visible active users"""
        return self.filter(is_active=True, is_hidden=False)

    def visible_users(self):
        """Return only visible users (excludes hidden SaaS admins)"""
        return self.filter(is_hidden=False)

    def company_users(self, company):
        """Return visible users for a specific company"""
        return self.filter(company=company, is_hidden=False)


class CustomUser(OfflineIDMixin,AbstractBaseUser, PermissionsMixin):
    # Core Fields
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    company = models.ForeignKey('company.Company', on_delete=models.CASCADE)
    email = models.EmailField(unique=True, verbose_name=_("Email Address"))
    username = models.CharField(
        max_length=150,
        unique=True,
        verbose_name=_("Username"),
        validators=[MinLengthValidator(3)]
    )
    first_name = models.CharField(max_length=50, blank=True, verbose_name=_("First Name"))
    last_name = models.CharField(max_length=50, blank=True, verbose_name=_("Last Name"))
    middle_name = models.CharField(max_length=50, blank=True, verbose_name=_("Middle Name"))
    primary_role = models.ForeignKey(
        'Role',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='users_with_primary_role'
    )
    # SaaS Admin specific fields (special system user)
    is_saas_admin = models.BooleanField(
        default=False,
        verbose_name=_("SaaS Administrator"),
        help_text=_("Designates whether this user can access all companies")
    )
    is_hidden = models.BooleanField(
        default=False,
        verbose_name=_("Hidden User"),
        help_text=_("Hidden users are not shown in user listings")
    )
    can_access_all_companies = models.BooleanField(
        default=False,
        verbose_name=_("Can Access All Companies"),
        help_text=_("Allows user to access any company in the system")
    )

    # Contact & Profile
    phone_number = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name=_("Phone Number"),
        validators=[validate_phone_number]
    )
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True)

    # Status & Permissions
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))
    is_staff = models.BooleanField(default=False, verbose_name=_("Is Staff"))
    company_admin = models.BooleanField(
        default=False,
        verbose_name=_("Company Admin"),
        help_text=_("Tenant owner with full control")
    )
    is_device_operator = models.BooleanField(default=False, verbose_name=_("Device Operator"))

    # Verification
    email_verified = models.BooleanField(default=False, verbose_name=_("Email Verified"))
    phone_verified = models.BooleanField(default=False, verbose_name=_("Phone Verified"))

    # Security
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    password_changed_at = models.DateTimeField(auto_now_add=True)
    two_factor_enabled = models.BooleanField(default=False)
    backup_codes = models.JSONField(default=list, blank=True)

    # Activity Tracking
    date_joined = models.DateTimeField(auto_now_add=True, verbose_name=_("Date Joined"))
    last_login_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("Last Login IP"))
    last_activity_at = models.DateTimeField(null=True, blank=True)
    login_count = models.PositiveIntegerField(default=0)

    # Preferences
    timezone = models.CharField(max_length=100, default='Africa/Kampala')
    language = models.CharField(max_length=10, default='en', choices=[
        ('en', 'English'),
        ('sw', 'Swahili'),
        ('lg', 'Luganda'),
    ])

    # Metadata
    metadata = models.JSONField(default=dict, blank=True, help_text=_("Additional user metadata"))

    objects = CustomUserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['is_active']),
            models.Index(fields=['last_activity_at']),
            models.Index(fields=['is_hidden']),
            models.Index(fields=['is_saas_admin']),
        ]
        permissions = [
            ('can_manage_users', _('Can manage users')),
            ('can_view_reports', _('Can view reports')),
            ('can_manage_settings', _('Can manage settings')),
            ('can_export_data', _('Can export data')),
            ('can_access_saas_admin', _('Can access SaaS admin features')),
            ('can_manage_all_companies', _('Can manage all companies')),
        ]

    def clean(self):
        super().clean()

        # Auto-configure SaaS admin
        if self.is_saas_admin:
            self.is_superuser = True
            self.is_staff = True
            self.is_hidden = True
            self.can_access_all_companies = True

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.is_saas_admin:
            return f"SaaS Admin: {self.get_full_name() or self.email}"
        return self.get_full_name() or self.email

    def get_full_name(self):
        names = [self.first_name, self.middle_name, self.last_name]
        return ' '.join(name for name in names if name).strip()

    def get_short_name(self):
        return self.first_name or self.username

    # ============================================
    # ROLE-BASED PROPERTIES (Replace user_type)
    # ============================================

    @property
    def computed_primary_role(self):
        """Get computed primary role as fallback (for migration period)"""
        user_roles = self.groups.filter(role__isnull=False).select_related('role')
        if not user_roles.exists():
            return None
        return max(user_roles, key=lambda g: g.role.priority).role

    @property
    def effective_primary_role(self):
        """Get primary role from database or compute it"""
        return self.primary_role or self.computed_primary_role

    @property
    def all_roles(self):
        """Get all roles assigned to this user"""
        return Role.objects.filter(group__in=self.groups.all())

    @property
    def role_names(self):
        """Get list of role names for display"""
        return [role.group.name for role in self.all_roles]

    @property
    def display_role(self):
        """Get display name for primary role"""
        primary = self.primary_role
        return primary.group.name if primary else "No Role Assigned"

    @property
    def highest_role_priority(self):
        """Get highest priority among user's roles"""
        primary = self.primary_role
        return primary.priority if primary else 0

    @property
    def is_company_owner(self):
        """Check if user is company admin"""
        return self.company_admin or self.is_saas_admin

    # ============================================
    # PERMISSION METHODS
    # ============================================

    def has_perm(self, perm, obj=None):
        """Check permissions through assigned roles and direct permissions"""
        # SaaS admins have all permissions
        if self.is_saas_admin:
            return True

        # Inactive users have no permissions
        if not self.is_active:
            return False

        # Superusers have all permissions
        if self.is_superuser:
            return True

        # ✅ Let Django's default permission checking handle the rest
        # This automatically checks:
        # 1. User's direct permissions (user_permissions)
        # 2. Group permissions (through groups)
        # 3. Custom model permissions
        return super().has_perm(perm, obj)

    def has_module_perms(self, app_label):
        """Control admin access - only SaaS admins"""
        if not self.is_active:
            return False

        # Only SaaS admins can access Django admin
        if app_label == 'admin':
            return self.is_saas_admin

        return self.is_saas_admin or super().has_module_perms(app_label)

    @property
    def can_access_django_admin(self):
        """Explicit check for Django admin access"""
        return self.is_saas_admin

    # ============================================
    # ROLE ASSIGNMENT & HIERARCHY
    # ============================================

    def assign_role(self, role):
        """Assign a role to this user"""

        if not role.is_active:
            raise ValidationError(f"Cannot assign inactive role: {role.group.name}")

        # Check capacity
        can_assign, reason = role.can_assign_to_user()
        if not can_assign:
            raise ValidationError(reason)

        # Assign
        self.groups.add(role.group)

        # Log
        RoleHistory.objects.create(
            role=role,
            action='assigned',
            affected_user=self,
            notes=f"Role assigned to {self.email}"
        )

    def remove_role(self, role):
        """Remove a role from this user"""

        self.groups.remove(role.group)

        # Log
        RoleHistory.objects.create(
            role=role,
            action='removed',
            affected_user=self,
            notes=f"Role removed from {self.email}"
        )

    def can_assign_role(self, role):
        """Check if user can assign a specific role to others"""
        if self.is_saas_admin:
            return True

        can_assign, reason = role.can_be_assigned_by(self)
        return can_assign

    def can_manage_user(self, target_user):
        """Check if this user can manage (edit/delete) another user"""
        if self.id == target_user.id:
            return False

        if self.is_saas_admin:
            return True

        if self.company_id != target_user.company_id:
            return False

        my_priority = self.highest_role_priority
        target_priority = target_user.highest_role_priority

        return my_priority > target_priority

    def get_manageable_users(self):
        """Get queryset of users this user can manage"""
        if self.is_saas_admin:
            return CustomUser.objects.filter(is_hidden=False).exclude(id=self.id)

        if not self.company:
            return CustomUser.objects.none()

        # Get users in same company
        queryset = CustomUser.objects.filter(
            company=self.company,
            is_hidden=False,
            is_saas_admin=False  # Can't manage SaaS admins
        ).exclude(id=self.id)  # Can't manage self

        # Apply role hierarchy filtering
        my_priority = self.highest_role_priority

        if my_priority > 0:
            from django.db.models import Max, Q

            # Get users whose highest role priority is strictly less than mine
            queryset = queryset.annotate(
                max_role_priority=Max('groups__role__priority')
            ).filter(
                Q(max_role_priority__lt=my_priority) | Q(max_role_priority__isnull=True)
            )

        return queryset.select_related('company').prefetch_related('groups__role')

    # ============================================
    # COMPANY ACCESS
    # ============================================

    def can_access_company(self, company):
        """Check if user can access a specific company"""
        if self.is_saas_admin or self.can_access_all_companies:
            return True
        return self.company == company

    def get_accessible_stores(self):
        """
        Get all stores this user can access based on:
        1. Direct store assignment (staff field)
        2. StoreAccess permissions
        3. Role-based access
        4. Company-wide access flags
        """
        from stores.models import Store, StoreAccess

        # SaaS admin can access all stores
        if self.is_saas_admin:
            return Store.objects.filter(is_active=True)

        # Company admin can access all stores in their company
        if self.company_admin:
            return Store.objects.filter(
                company=self.company,
                is_active=True
            )

        # Get stores through StoreAccess model
        accessible_store_ids = StoreAccess.objects.filter(
            user=self,
            is_active=True
        ).values_list('store_id', flat=True)

        # Get stores where user is directly assigned as staff
        directly_assigned = self.stores.filter(is_active=True)

        # Get stores where user is a manager
        managed_stores = self.managed_stores.filter(is_active=True)

        # Get stores accessible by all company users
        company_wide_stores = Store.objects.filter(
            company=self.company,
            accessible_by_all=True,
            is_active=True
        )

        # Combine all querysets
        from django.db.models import Q
        all_accessible = Store.objects.filter(
            Q(id__in=accessible_store_ids) |
            Q(id__in=directly_assigned.values_list('id', flat=True)) |
            Q(id__in=managed_stores.values_list('id', flat=True)) |
            Q(id__in=company_wide_stores.values_list('id', flat=True)),
            company=self.company,
            is_active=True
        ).distinct()

        return all_accessible

    def can_access_store(self, store):
        """
        Check if user can access a specific store
        """
        # SaaS admin can access all stores
        if self.is_saas_admin:
            return True

        # Check company match
        if self.company_id != store.company_id:
            return False

        # Company admin can access all stores
        if self.company_admin:
            return True

        # Check if store is accessible by all
        if store.accessible_by_all:
            return True

        # Check direct assignment
        if store.staff.filter(id=self.id).exists():
            return True

        # Check manager assignment
        if store.store_managers.filter(id=self.id).exists():
            return True

        # Check StoreAccess permission
        from stores.models import StoreAccess
        return StoreAccess.objects.filter(
            user=self,
            store=store,
            is_active=True
        ).exists()

    def get_store_access_level(self, store):
        """
        Get user's access level for a specific store
        Returns: 'admin', 'manager', 'staff', 'view', or None
        """
        from stores.models import StoreAccess

        if self.is_saas_admin or self.company_admin:
            return 'admin'

        if store.store_managers.filter(id=self.id).exists():
            return 'manager'

        access_perm = StoreAccess.objects.filter(
            user=self,
            store=store,
            is_active=True
        ).first()

        if access_perm:
            return access_perm.access_level

        if store.staff.filter(id=self.id).exists():
            return 'staff'

        if store.accessible_by_all:
            return 'view'

        return None

    def has_store_permission(self, store, permission):
        """
        Check if user has a specific permission for a store

        Args:
            store: Store instance
            permission: String like 'can_create_sales', 'can_manage_inventory'
        """
        from stores.models import StoreAccess

        # SaaS admin and company admin have all permissions
        if self.is_saas_admin or self.company_admin:
            return True

        # Store managers have elevated permissions
        if store.store_managers.filter(id=self.id).exists():
            return permission not in ['can_delete_store']  # Managers can't delete stores

        # Check StoreAccess permissions
        access = StoreAccess.objects.filter(
            user=self,
            store=store,
            is_active=True
        ).first()

        if access:
            return getattr(access, permission, False)

        # Default staff permissions if directly assigned
        if store.staff.filter(id=self.id).exists():
            basic_permissions = ['can_view_sales', 'can_create_sales', 'can_view_inventory']
            return permission in basic_permissions

        return False

    @property
    def default_store(self):
        """
        Get user's default/primary store
        """
        accessible_stores = self.get_accessible_stores()

        # Try to get from user preferences first
        if self.metadata.get('default_store_id'):
            store = accessible_stores.filter(
                id=self.metadata['default_store_id']
            ).first()
            if store:
                return store

        # Return first accessible store
        return accessible_stores.first()

    def set_default_store(self, store):
        """
        Set user's default store
        """
        if self.can_access_store(store):
            self.metadata['default_store_id'] = store.id
            self.save(update_fields=['metadata'])
            return True
        return False

    def get_accessible_companies(self):
        """Get all companies this user can access"""
        if self.is_saas_admin or self.can_access_all_companies:
            from company.models import Company
            return Company.objects.all()
        return Company.objects.filter(id=self.company_id) if self.company else Company.objects.none()

    # ============================================
    # SECURITY & ACCOUNT STATUS
    # ============================================

    @property
    def is_locked(self):
        """Check if account is temporarily locked"""
        return self.locked_until and self.locked_until > timezone.now()

    def lock_account(self, duration_minutes=30):
        """Lock account for specified duration"""
        self.locked_until = timezone.now() + timedelta(minutes=duration_minutes)
        self.save(update_fields=['locked_until'])

    def unlock_account(self):
        """Unlock account and reset failed attempts"""
        self.locked_until = None
        self.failed_login_attempts = 0
        self.save(update_fields=['locked_until', 'failed_login_attempts'])

    def record_login_attempt(self, success=True, ip_address=None):
        """Record login attempt"""
        if success:
            self.failed_login_attempts = 0
            self.locked_until = None
            self.login_count += 1
            self.last_activity_at = timezone.now()
            if ip_address:
                self.last_login_ip = ip_address
        else:
            self.failed_login_attempts += 1
            if self.failed_login_attempts >= 5:
                self.locked_until = timezone.now() + timedelta(minutes=30)

        self.save(update_fields=[
            'failed_login_attempts', 'login_count',
            'last_activity_at', 'last_login_ip', 'locked_until',
        ])

    def can_fiscalize(self, store):
        """Check if user can fiscalize invoices for a given store"""
        if self.is_saas_admin:
            return True

        # Check if user has appropriate role
        primary = self.primary_role
        if not primary:
            return False

        # High priority roles can fiscalize
        return primary.priority >= 70  # Manager level and above

    def refresh_permissions(self):
        """Force refresh of user permissions from database"""
        from django.contrib.auth.models import _user_has_perm, _user_has_module_perms

        # Clear cached permissions
        if hasattr(self, '_perm_cache'):
            delattr(self, '_perm_cache')
        if hasattr(self, '_user_perm_cache'):
            delattr(self, '_user_perm_cache')
        if hasattr(self, '_group_perm_cache'):
            delattr(self, '_group_perm_cache')


class UserSignature(models.Model):
    user = models.OneToOneField(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='signature'
    )
    signature_image = models.ImageField(
        upload_to='user_signatures/',
        blank=True,
        null=True
    )
    signature_data = models.TextField(
        blank=True,
        null=True,
        help_text=_('Digital signature data for EFRIS')
    )
    signature_hash = models.CharField(max_length=64, blank=True)
    is_verified = models.BooleanField(default=False)
    verified_at = models.DateTimeField(blank=True, null=True)
    verified_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_signatures'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _('User Signature')
        verbose_name_plural = _('User Signatures')

    def save(self, *args, **kwargs):
        if self.signature_data:
            self.signature_hash = hashlib.sha256(
                self.signature_data.encode()
            ).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Signature for {self.user}"


class RoleManager(models.Manager):

    """Custom manager for Role model with useful querysets"""

    def system_roles(self):
        return self.filter(is_system_role=True)

    def custom_roles(self):
        return self.filter(is_system_role=False)

    def for_company(self, company):
        return self.filter(company=company)

    def active_roles(self):
        return self.filter(is_active=True)

    def accessible_by_user(self, user):
        """
        Get roles that the user can assign to others
        """
        from django.db.models import Q

        # SaaS admins can access all active roles
        if getattr(user, 'is_saas_admin', False):
            return self.filter(is_active=True)

        # Users without a company can't assign roles
        if not user.company:
            return self.none()

        # Base queryset: roles from user's company or system-wide roles
        queryset = self.filter(
            Q(company=user.company) | Q(is_system_role=True, company__isnull=True),
            is_active=True
        )

        # Get user's highest role priority
        user_roles = user.groups.filter(role__isnull=False).select_related('role')

        # If user has no roles but is company_admin, show all company roles
        if not user_roles.exists():
            if getattr(user, 'company_admin', False):
                return queryset.filter(company=user.company)
            return self.none()

        # Get highest priority from user's roles
        max_priority = max(role.role.priority for role in user_roles)

        # Return roles with equal or lower priority
        return queryset.filter(priority__lte=max_priority)


class Role(OfflineIDMixin, models.Model):
    """Extended Group model for company-specific roles with metadata."""

    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    group = models.OneToOneField(
        Group,
        on_delete=models.CASCADE,
        related_name="role",
        help_text="Underlying group that manages permissions"
    )
    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text="Company this role belongs to (null for system-wide roles)"
    )
    description = models.TextField(blank=True, null=True)
    is_system_role = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    priority = models.PositiveIntegerField(default=0)
    color_code = models.CharField(max_length=7, default="#6c757d")
    max_users = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_roles'
    )

    objects = RoleManager()  # 🔥 Use the custom manager

    class Meta:
        ordering = ['-priority', 'group__name']
        unique_together = [['group', 'company']]
        verbose_name = 'Role'
        verbose_name_plural = 'Roles'
        permissions = [
            ('can_manage_system_roles', 'Can manage system roles'),
            ('can_view_role_analytics', 'Can view role analytics'),
            ('can_bulk_assign_roles', 'Can bulk assign roles to users'),
        ]

    def __str__(self):
        company_str = f" ({self.company.name})" if self.company else ""
        system_str = " [System]" if self.is_system_role else ""
        return f"{self.group.name}{company_str}{system_str}"

    def get_absolute_url(self):
        return reverse('role_detail', kwargs={'pk': self.pk})

    def clean(self):
        # System roles must never be tied to a specific company, in any schema
        if self.is_system_role and self.company:
            raise ValidationError("System roles cannot be company-specific")

        if self.max_users and self.max_users < 1:
            raise ValidationError("Maximum users must be at least 1")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def user_count(self):
        """Get number of visible users in this role."""
        return self.group.user_set.filter(is_hidden=False).count()

    @property
    def permission_count(self):
        return self.group.permissions.count()

    @property
    def is_at_capacity(self):
        if not self.max_users:
            return False
        return self.user_count >= self.max_users

    @property
    def capacity_percentage(self):
        if not self.max_users:
            return 0
        return min(100, (self.user_count / self.max_users) * 100)

    def can_assign_to_user(self, user=None):
        if not self.is_active:
            return False, "Role is not active"
        if self.is_at_capacity:
            return False, f"Role has reached maximum capacity ({self.max_users} users)"
        return True, "Role can be assigned"

    def get_permission_groups(self):
        """Get permissions grouped by content type."""
        from collections import defaultdict
        grouped_permissions = defaultdict(list)
        for perm in self.group.permissions.select_related('content_type'):
            app_label = perm.content_type.app_label
            grouped_permissions[app_label].append(perm)
        return dict(grouped_permissions)

    # 🔥 NEW METHODS FOR HIERARCHY

    @classmethod
    def get_accessible_roles_for_user(cls, user):
        """
        Get all roles that this user can assign to others.
        Returns QuerySet of Role objects.
        """
        return cls.objects.accessible_by_user(user)

    def can_be_assigned_by(self, user):
        """
        Check if this role can be assigned by the given user.
        Returns (bool, str) - (can_assign, reason)
        """
        # SaaS admin can assign any role
        if user.is_saas_admin:
            return True, "SaaS admin has full access"

        # Check if role is active
        if not self.is_active:
            return False, "Role is not active"

        # Check company match
        if self.company_id != user.company_id:
            return False, "Role belongs to different company"

        # Get user's highest role priority
        user_roles = user.groups.filter(role__isnull=False).select_related('role')
        if not user_roles.exists():
            return False, "User has no roles"

        max_user_priority = max(role.role.priority for role in user_roles)

        # Check priority
        if self.priority > max_user_priority:
            return False, f"Insufficient privileges (role priority {self.priority} > user priority {max_user_priority})"

        # Check capacity
        if self.is_at_capacity:
            return False, f"Role at capacity ({self.max_users} users)"

        return True, "Role can be assigned"

    def is_higher_than(self, other_role):
        """Check if this role has higher priority than another role"""
        if not isinstance(other_role, Role):
            return False
        return self.priority > other_role.priority

    def is_equal_or_higher_than(self, other_role):
        """Check if this role has equal or higher priority than another role"""
        if not isinstance(other_role, Role):
            return False
        return self.priority >= other_role.priority


class RoleHistory(OfflineIDMixin, models.Model):
    """Track changes to roles for auditing."""

    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('deleted', 'Deleted'),
        ('permissions_changed', 'Permissions Changed'),
        ('activated', 'Activated'),
        ('deactivated', 'Deactivated'),
        ('assigned', 'Assigned to User'),  # 🔥 NEW
        ('removed', 'Removed from User'),  # 🔥 NEW
    ]

    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name='history'
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='role_history_actions'  # 🔥 Changed to avoid conflict
    )
    affected_user = models.ForeignKey(  # 🔥 NEW - who was affected
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='role_history_affected'
    )
    timestamp = models.DateTimeField(default=timezone.now)
    changes = models.JSONField(default=dict)
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Role History'
        verbose_name_plural = 'Role Histories'

    def __str__(self):
        return f"{self.role.group.name} - {self.get_action_display()} by {self.user}"


class AuditLogManager(models.Manager):
    """Custom manager for AuditLog with filtering methods"""

    def for_user(self, user):
        """Get all logs for a specific user"""
        return self.filter(user=user)

    def for_model(self, model_class):
        """Get all logs for a specific model"""
        content_type = ContentType.objects.get_for_model(model_class)
        return self.filter(content_type=content_type)

    def for_action(self, action):
        """Get all logs for a specific action"""
        return self.filter(action=action)

    def recent(self, days=7):
        """Get recent logs within specified days"""
        from datetime import timedelta
        cutoff = timezone.now() - timedelta(days=days)
        return self.filter(timestamp__gte=cutoff)


class AuditLog(OfflineIDMixin, models.Model):
    ACTION_TYPES = [
        # User Management
        ('user_created', _('User Created')),
        ('user_updated', _('User Updated')),
        ('user_deleted', _('User Deleted')),
        ('user_activated', _('User Activated')),
        ('user_deactivated', _('User Deactivated')),

        # Authentication
        ('login_success', _('Login Success')),
        ('login_failed', _('Login Failed')),
        ('logout', _('Logout')),
        ('password_changed', _('Password Changed')),
        ('password_reset', _('Password Reset')),
        ('email_verified', _('Email Verified')),
        ('2fa_enabled', _('2FA Enabled')),
        ('2fa_disabled', _('2FA Disabled')),

        # Company/Tenant Management
        ('company_created', _('Company Created')),
        ('company_updated', _('Company Updated')),
        ('company_deleted', _('Company Deleted')),
        ('company_suspended', _('Company Suspended')),
        ('company_activated', _('Company Activated')),

        # Store Management
        ('store_created', _('Store Created')),
        ('store_updated', _('Store Updated')),
        ('store_deleted', _('Store Deleted')),

        # Product/Inventory
        ('product_created', _('Product Created')),
        ('product_updated', _('Product Updated')),
        ('product_deleted', _('Product Deleted')),
        ('stock_added', _('Stock Added')),
        ('stock_removed', _('Stock Removed')),
        ('stock_adjusted', _('Stock Adjusted')),

        # Sales
        ('sale_created', _('Sale Created')),
        ('sale_completed', _('Sale Completed')),
        ('sale_voided', _('Sale Voided')),
        ('sale_refunded', _('Sale Refunded')),

        # Invoices
        ('invoice_created', _('Invoice Created')),
        ('invoice_sent', _('Invoice Sent')),
        ('invoice_paid', _('Invoice Paid')),
        ('invoice_cancelled', _('Invoice Cancelled')),

        # EFRIS
        ('efris_fiscalized', _('EFRIS Fiscalized')),
        ('efris_sync', _('EFRIS Sync')),
        ('efris_failed', _('EFRIS Failed')),

        # Reports
        ('report_generated', _('Report Generated')),
        ('report_exported', _('Report Exported')),
        ('report_scheduled', _('Report Scheduled')),

        # Expenses
        ('expense_created', _('Expense Created')),
        ('expense_approved', _('Expense Approved')),
        ('expense_rejected', _('Expense Rejected')),
        ('expense_paid', _('Expense Paid')),

        # Settings
        ('settings_updated', _('Settings Updated')),
        ('permission_changed', _('Permission Changed')),

        # Security
        ('impersonation_started', _('Impersonation Started')),
        ('impersonation_ended', _('Impersonation Ended')),
        ('suspicious_activity', _('Suspicious Activity')),
        ('account_locked', _('Account Locked')),
        ('account_unlocked', _('Account Unlocked')),

        # System
        ('system_backup', _('System Backup')),
        ('system_restore', _('System Restore')),
        ('maintenance_mode', _('Maintenance Mode')),

        # Other
        ('other', _('Other Action')),
    ]

    SEVERITY_LEVELS = [
        ('info', _('Info')),
        ('warning', _('Warning')),
        ('error', _('Error')),
        ('critical', _('Critical')),
    ]

    # User Information
    user = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name=_("User"),
        help_text=_("User who performed the action")
    )

    impersonated_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='impersonation_logs',
        verbose_name=_("Impersonated By"),
        help_text=_("If action was performed during impersonation")
    )

    # Action Details
    action = models.CharField(
        max_length=50,
        choices=ACTION_TYPES,
        db_index=True,
        verbose_name=_("Action Type")
    )

    action_description = models.TextField(
        verbose_name=_("Action Description"),
        help_text=_("Human-readable description of the action")
    )

    severity = models.CharField(
        max_length=20,
        choices=SEVERITY_LEVELS,
        default='info',
        verbose_name=_("Severity Level")
    )

    # Resource Information (Generic Foreign Key)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        verbose_name=_("Resource Type")
    )
    object_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        verbose_name=_("Resource ID")
    )
    content_object = GenericForeignKey('content_type', 'object_id')

    # Store the resource name for quick access
    resource_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Resource Name")
    )

    # Additional Context
    changes = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Changes"),
        help_text=_("Before and after values for updates")
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Additional Metadata")
    )

    # Request Information
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP Address")
    )

    user_agent = models.TextField(
        blank=True,
        verbose_name=_("User Agent")
    )

    request_path = models.CharField(
        max_length=500,
        blank=True,
        verbose_name=_("Request Path")
    )

    request_method = models.CharField(
        max_length=10,
        blank=True,
        verbose_name=_("Request Method")
    )

    company = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name=_("Company")
    )

    store = models.ForeignKey(
        'stores.Store',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='audit_logs',
        verbose_name=_("Store")
    )

    # Status
    success = models.BooleanField(
        default=True,
        verbose_name=_("Success"),
        help_text=_("Whether the action was successful")
    )

    error_message = models.TextField(
        blank=True,
        verbose_name=_("Error Message"),
        help_text=_("Error details if action failed")
    )

    # Timing
    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_("Timestamp")
    )

    duration_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name=_("Duration (ms)"),
        help_text=_("How long the action took in milliseconds")
    )

    # Flags
    is_system_action = models.BooleanField(
        default=False,
        verbose_name=_("System Action"),
        help_text=_("Action performed by system, not user")
    )

    requires_review = models.BooleanField(
        default=False,
        verbose_name=_("Requires Review"),
        help_text=_("Flag for actions that need admin review")
    )

    reviewed = models.BooleanField(
        default=False,
        verbose_name=_("Reviewed")
    )

    reviewed_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_logs',
        verbose_name=_("Reviewed By")
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Reviewed At")
    )

    objects = AuditLogManager()

    class Meta:
        verbose_name = _("Audit Log")
        verbose_name_plural = _("Audit Logs")
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['company', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
            models.Index(fields=['content_type', 'object_id']),
            models.Index(fields=['ip_address', '-timestamp']),
            models.Index(fields=['severity', '-timestamp']),
            models.Index(fields=['success', '-timestamp']),
            models.Index(fields=['requires_review', 'reviewed']),
        ]
        permissions = [
            ('view_all_audit_logs', 'Can view all audit logs'),
            ('export_audit_logs', 'Can export audit logs'),
            ('review_audit_logs', 'Can review flagged audit logs'),
        ]

    def __str__(self):
        user_str = self.user.get_full_name() if self.user else "System"
        return f"{user_str} - {self.get_action_display()} at {self.timestamp}"

    @classmethod
    def log(cls, action, user, description, **kwargs):
        return cls.objects.create(
            action=action,
            user=user,
            action_description=description,
            **kwargs
        )

    @classmethod
    def log_change(cls, action, user, instance, old_values, new_values, description=None):
        changes = {
            'before': old_values,
            'after': new_values
        }

        if not description:
            description = f"Updated {instance._meta.verbose_name}"

        return cls.objects.create(
            action=action,
            user=user,
            action_description=description,
            content_object=instance,
            resource_name=str(instance),
            changes=changes
        )


class LoginHistory(OfflineIDMixin, models.Model):
    STATUS_CHOICES = [
        ('success', _('Success')),
        ('failed', _('Failed')),
        ('blocked', _('Blocked')),
    ]

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='login_history',
        verbose_name=_("User")
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        verbose_name=_("Status")
    )

    ip_address = models.GenericIPAddressField(
        verbose_name=_("IP Address")
    )

    user_agent = models.TextField(
        verbose_name=_("User Agent")
    )

    browser = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Browser")
    )

    os = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Operating System")
    )

    device_type = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Device Type")
    )

    location = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Location"),
        help_text=_("City, Country")
    )

    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )

    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True
    )

    failure_reason = models.CharField(
        max_length=255,
        blank=True,
        verbose_name=_("Failure Reason")
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name=_("Timestamp")
    )

    session_key = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Session Key")
    )

    logout_timestamp = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Logout Timestamp")
    )

    class Meta:
        verbose_name = _("Login History")
        verbose_name_plural = _("Login History")
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['status', '-timestamp']),
            models.Index(fields=['ip_address', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.get_status_display()} at {self.timestamp}"

    @property
    def session_duration(self):
        """Calculate session duration"""
        if self.logout_timestamp:
            return self.logout_timestamp - self.timestamp
        return None


class DataExportLog(OfflineIDMixin, models.Model):
    EXPORT_TYPES = [
        ('csv', 'CSV'),
        ('excel', 'Excel'),
        ('pdf', 'PDF'),
        ('json', 'JSON'),
    ]

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='export_logs',
        verbose_name=_("User")
    )

    export_type = models.CharField(
        max_length=20,
        choices=EXPORT_TYPES,
        verbose_name=_("Export Type")
    )

    resource_type = models.CharField(
        max_length=100,
        verbose_name=_("Resource Type"),
        help_text=_("What type of data was exported")
    )

    filters_applied = models.JSONField(
        default=dict,
        verbose_name=_("Filters Applied")
    )

    record_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Record Count")
    )

    file_size_bytes = models.PositiveBigIntegerField(
        default=0,
        verbose_name=_("File Size (bytes)")
    )

    ip_address = models.GenericIPAddressField(
        verbose_name=_("IP Address")
    )

    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Timestamp")
    )

    class Meta:
        verbose_name = _("Data Export Log")
        verbose_name_plural = _("Data Export Logs")
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.user.username} exported {self.resource_type} at {self.timestamp}"


class APIToken(OfflineIDMixin, models.Model):
    """API tokens for programmatic access to the system."""

    TOKEN_TYPE_CHOICES = [
        ('read', _('Read Only')),
        ('write', _('Read & Write')),
        ('admin', _('Admin')),
    ]

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='api_tokens',
        verbose_name=_("User")
    )

    name = models.CharField(
        max_length=100,
        verbose_name=_("Token Name"),
        help_text=_("A label to identify this token")
    )

    token = models.CharField(
        max_length=64,
        unique=True,
        db_index=True,
        verbose_name=_("Token")
    )

    token_type = models.CharField(
        max_length=20,
        choices=TOKEN_TYPE_CHOICES,
        default='read',
        verbose_name=_("Token Type")
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Is Active")
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Expires At")
    )

    last_used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Used At")
    )

    last_used_ip = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("Last Used IP")
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )

    class Meta:
        verbose_name = _("API Token")
        verbose_name_plural = _("API Tokens")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['token']),
            models.Index(fields=['user', 'is_active']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.token:
            import secrets
            self.token = secrets.token_hex(32)
        super().save(*args, **kwargs)

    @property
    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    @property
    def is_valid(self):
        return self.is_active and not self.is_expired


class UserSession(OfflineIDMixin, models.Model):
    """Tracks active user sessions across devices."""

    user = models.ForeignKey(
        CustomUser,
        on_delete=models.CASCADE,
        related_name='sessions',
        verbose_name=_("User")
    )

    session_key = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        verbose_name=_("Session Key")
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP Address")
    )

    user_agent = models.TextField(
        blank=True,
        verbose_name=_("User Agent")
    )

    browser = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Browser")
    )

    os = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Operating System")
    )

    device_type = models.CharField(
        max_length=50,
        blank=True,
        verbose_name=_("Device Type")
    )

    location = models.CharField(
        max_length=200,
        blank=True,
        verbose_name=_("Location")
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Is Active")
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )

    last_activity = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Last Activity")
    )

    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Expires At")
    )

    class Meta:
        verbose_name = _("User Session")
        verbose_name_plural = _("User Sessions")
        ordering = ['-last_activity']
        indexes = [
            models.Index(fields=['user', 'is_active']),
            models.Index(fields=['session_key']),
            models.Index(fields=['last_activity']),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.session_key[:8]}... ({self.ip_address})"

    @property
    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    def terminate(self):
        """Terminate this session."""
        self.is_active = False
        self.save(update_fields=['is_active'])