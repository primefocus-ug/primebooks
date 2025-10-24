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
            # Try to get or create a default company
            try:
                # Import here to avoid circular imports
                from company.models import Company, SubscriptionPlan
                from django.utils import timezone
                from datetime import timedelta

                # Try to get the first active company
                company = Company.objects.filter(status__in=['ACTIVE', 'TRIAL']).first()

                if company is None:
                    # Create a default company if none exists
                    # First ensure we have a free plan
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

                    # Create a default domain
                    from company.models import Domain
                    Domain.objects.create(
                        tenant=company,
                        domain="default.localhost",
                        is_primary=True,
                        ssl_enabled=False
                    )

                    print(f"Created default company: {company.display_name} ({company.company_id})")
                else:
                    print(f"Using existing company: {company.display_name} ({company.company_id})")

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
        extra_fields.setdefault('user_type', 'SAAS_ADMIN')

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_('SaaS admin must have is_staff=True.'))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_('SaaS admin must have is_superuser=True.'))

        # SaaS admin doesn't need a specific company - can access all
        # Create with a placeholder company that we'll handle in the model
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
        """Return only visible active users (excludes hidden SaaS admins)"""
        return self.filter(is_active=True, is_hidden=False)

    def visible_users(self):
        """Return only visible users (excludes hidden SaaS admins)"""
        return self.filter(is_hidden=False)

    def company_users(self, company):
        """Return visible users for a specific company"""
        return self.filter(company=company, is_hidden=False)


class CustomUser(AbstractBaseUser, PermissionsMixin):
    USER_TYPES = [
        ('SAAS_ADMIN', _('SaaS Admin')),
        ('SUPER_ADMIN', _('Super Admin')),
        ('COMPANY_ADMIN', _('Company Admin')),
        ('MANAGER', _('Manager')),
        ('CASHIER', _('Cashier')),
        ('EMPLOYEE', _('Employee')),
    ]

    # Core Fields
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

    # Role and Permissions
    user_type = models.CharField(
        max_length=20,
        choices=USER_TYPES,
        default='EMPLOYEE',
        verbose_name=_("User Type")
    )

    # SaaS Admin specific fields
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

    phone_number = models.CharField(max_length=20, blank=True, null=True, verbose_name=_("Phone Number"),
                                    validators=[validate_phone_number])
    is_active = models.BooleanField(default=True, verbose_name=_("Is Active"))
    is_staff = models.BooleanField(default=False, verbose_name=_("Is Staff"))
    is_device_operator = models.BooleanField(default=False, verbose_name=_("Device Operator"))
    company_admin = models.BooleanField(default=False, verbose_name=_("Company Admin"))
    email_verified = models.BooleanField(default=False, verbose_name=_("Email Verified"))
    phone_verified = models.BooleanField(default=False, verbose_name=_("Phone Verified"))
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    password_changed_at = models.DateTimeField(auto_now_add=True)
    two_factor_enabled = models.BooleanField(default=False)
    backup_codes = models.JSONField(default=list, blank=True)
    date_joined = models.DateTimeField(auto_now_add=True, verbose_name=_("Date Joined"))
    last_login_ip = models.GenericIPAddressField(null=True, blank=True, verbose_name=_("Last Login IP"))
    last_activity_at = models.DateTimeField(null=True, blank=True)
    login_count = models.PositiveIntegerField(default=0)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True)
    timezone = models.CharField(max_length=100, default='Africa/Kampala')
    language = models.CharField(max_length=10, default='en', choices=[
        ('en', 'English'),
        ('sw', 'Swahili'),
        ('lg', 'Luganda'),
    ])
    metadata = models.JSONField(default=dict, blank=True, help_text=_("Additional user metadata"))
    objects = CustomUserManager()
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        indexes = [
            models.Index(fields=['email']),
            models.Index(fields=['user_type']),
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
        # Auto-set user_type based on role
        if self.is_saas_admin:
            self.user_type = 'SAAS_ADMIN'
            self.is_superuser = True
            self.is_staff = True
            self.is_hidden = True
            self.can_access_all_companies = True
        elif self.is_superuser:
            self.user_type = 'SUPER_ADMIN'
        elif self.company_admin:
            self.user_type = 'COMPANY_ADMIN'

    def save(self, *args, **kwargs):
        self.full_clean()

        # Auto-create default SaaS admin for first company if needed
        if not self.is_saas_admin and not CustomUser.objects.filter(is_saas_admin=True).exists():
            self._create_default_saas_admin()

        super().save(*args, **kwargs)

    def _create_default_saas_admin(self):
        """Create a default SaaS admin when first company user is created"""
        try:
            default_admin = CustomUser.objects.create_saas_admin(
                email=getattr(settings, 'DEFAULT_SAAS_ADMIN_EMAIL', 'admin@saas.com'),
                password=getattr(settings, 'DEFAULT_SAAS_ADMIN_PASSWORD', 'saas_admin_2024'),
                username='saas_admin',
                first_name='SaaS',
                last_name='Administrator'
            )
            print(f"Created default SaaS admin: {default_admin.email}")
        except Exception as e:
            print(f"Could not create default SaaS admin: {str(e)}")

    def __str__(self):
        if self.is_saas_admin:
            return f"SaaS Admin: {self.get_full_name() or self.email}"
        return self.get_full_name() or self.email

    def get_full_name(self):
        names = [self.first_name, self.middle_name, self.last_name]
        return ' '.join(name for name in names if name).strip()

    def get_short_name(self):
        return self.first_name or self.username

    @property
    def is_company_owner(self):
        return self.company_admin or self.is_saas_admin

    @property
    def is_locked(self):
        """Check if account is temporarily locked"""
        return self.locked_until and self.locked_until > timezone.now()

    def can_access_company(self, company):
        """Check if user can access a specific company"""
        if self.is_saas_admin or self.can_access_all_companies:
            return True
        return self.company == company

    def get_accessible_companies(self):
        """Get all companies this user can access"""
        if self.is_saas_admin or self.can_access_all_companies:
            from company.models import Company
            return Company.objects.all()
        return Company.objects.filter(id=self.company_id) if self.company else Company.objects.none()

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
            self.login_count += 1
            self.last_activity_at = timezone.now()
            if ip_address:
                self.last_login_ip = ip_address
        else:
            self.failed_login_attempts += 1
            if self.failed_login_attempts >= 5:
                self.lock_account()

        self.save(update_fields=[
            'failed_login_attempts', 'login_count',
            'last_activity_at', 'last_login_ip'
        ])

    def can_fiscalize(self, store):
        """
        Check if this user can fiscalize invoices for a given store.
        """
        # SaaS admin can do everything
        if self.is_saas_admin:
            return True

        # Other checks
        if self.is_superuser or self.user_type in ['SUPER_ADMIN', 'COMPANY_ADMIN']:
            return True

        if self.user_type in ['MANAGER', 'CASHIER']:
            return True

        return False


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
    signature_hash = models.CharField(max_length=64, blank=True)  # SHA-256 hash
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
        # Generate hash for signature verification
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


class Role(models.Model):
    """Extended Group model for company-specific roles with metadata."""
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

    objects = models.Manager()

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
        # ⚙️ Only enforce this in the public schema (shared/global context)
        if connection.schema_name == 'public':
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


class RoleHistory(models.Model):
    """Track changes to roles for auditing."""

    ACTION_CHOICES = [
        ('created', 'Created'),
        ('updated', 'Updated'),
        ('deleted', 'Deleted'),
        ('permissions_changed', 'Permissions Changed'),
        ('activated', 'Activated'),
        ('deactivated', 'Deactivated'),
    ]

    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name='history'
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
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
