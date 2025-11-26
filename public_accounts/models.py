from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
import random
import string
from django.core.mail import send_mail
from django.conf import settings


class PublicUserManager(BaseUserManager):
    """Manager for public schema users"""

    def create_user(self, email, username, password=None, **extra_fields):
        if not email:
            raise ValueError('Email address is required')
        if not username:
            raise ValueError('Username is required')

        email = self.normalize_email(email)
        user = self.model(email=email, username=username, **extra_fields)

        # Generate unique identifier
        user.identifier = user.generate_identifier()

        # Set password (will be auto-generated if None)
        if password is None:
            password = user.generate_default_password()

        user.set_password(password)
        user.save(using=self._db)

        # Send welcome email with credentials
        user.send_welcome_email(password)

        return user

    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_admin', True)

        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')

        return self.create_user(email, username, password, **extra_fields)


class PublicUser(AbstractBaseUser):
    """
    Custom user model for public schema administration.
    Login is strictly by unique identifier (PRIME-XXXXPF-YYMM-LTD format)

    NOTE: Does NOT use Django's auth.Group or auth.Permission tables
    since those are in tenant schemas only. Uses role-based boolean fields instead.
    """

    USER_ROLES = [
        ('SUPER_ADMIN', _('Super Administrator')),
        ('ADMIN', _('Administrator')),
        ('CONTENT_MANAGER', _('Content Manager')),
        ('SEO_MANAGER', _('SEO Manager')),
        ('BLOG_EDITOR', _('Blog Editor')),
        ('SUPPORT_AGENT', _('Support Agent')),
        ('VIEWER', _('Viewer')),
    ]

    # Unique identifier (used for login)
    identifier = models.CharField(
        max_length=50,
        unique=True,
        db_index=True,
        editable=False,
        verbose_name=_("Login Identifier"),
        help_text=_("Format: PRIME-XXXXPF-YYMM-LTD")
    )

    # Basic Information
    email = models.EmailField(
        unique=True,
        db_index=True,
        verbose_name=_("Email Address")
    )
    username = models.CharField(
        max_length=150,
        unique=True,
        verbose_name=_("Username")
    )
    first_name = models.CharField(
        max_length=50,
        verbose_name=_("First Name")
    )
    last_name = models.CharField(
        max_length=50,
        verbose_name=_("Last Name")
    )
    phone = models.CharField(
        max_length=20,
        blank=True,
        validators=[RegexValidator(r'^\+?[0-9]+$', 'Enter a valid phone number.')],
        verbose_name=_("Phone Number")
    )

    # Role and Permissions
    role = models.CharField(
        max_length=20,
        choices=USER_ROLES,
        default='SUPER_ADMIN',
        verbose_name=_("Role")
    )

    # Status flags
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    is_staff = models.BooleanField(default=True, verbose_name=_("Staff Status"))
    is_superuser = models.BooleanField(default=False, verbose_name=_("Superuser Status"))
    is_admin = models.BooleanField(default=False, verbose_name=_("Admin"))

    # Email verification
    email_verified = models.BooleanField(default=False)
    email_verification_token = models.CharField(max_length=100, blank=True, null=True)

    # Password management
    password_changed_at = models.DateTimeField(auto_now_add=True)
    force_password_change = models.BooleanField(
        default=True,
        help_text=_("User must change password on first login")
    )

    # Security
    failed_login_attempts = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)

    # Profile
    avatar = models.ImageField(upload_to='public_accounts/avatars/', blank=True, null=True)
    bio = models.TextField(max_length=500, blank=True)

    # Permissions for different apps (role-based boolean permissions)
    can_manage_seo = models.BooleanField(default=False)
    can_manage_blog = models.BooleanField(default=False)
    can_manage_support = models.BooleanField(default=False)
    can_manage_companies = models.BooleanField(default=False)
    can_view_analytics = models.BooleanField(default=False)

    # Timestamps
    date_joined = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(null=True, blank=True)

    objects = PublicUserManager()

    USERNAME_FIELD = 'identifier'
    REQUIRED_FIELDS = ['email', 'username']

    class Meta:
        db_table = 'public_users'
        verbose_name = _("Public User")
        verbose_name_plural = _("Public Users")
        ordering = ['-date_joined']
        indexes = [
            models.Index(fields=['identifier']),
            models.Index(fields=['email']),
            models.Index(fields=['is_active', 'is_staff']),
        ]
        permissions = [
            ('manage_seo_content', 'Can manage SEO content'),
            ('manage_blog_posts', 'Can manage blog posts'),
            ('manage_support_tickets', 'Can manage support tickets'),
            ('view_public_analytics', 'Can view public analytics'),
            ('manage_public_users', 'Can manage public users'),
        ]

    def __str__(self):
        return f"{self.get_full_name()} ({self.identifier})"

    def get_full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.username

    def get_short_name(self):
        return self.first_name or self.username

    # Django admin compatibility methods
    def has_perm(self, perm, obj=None):
        """
        Check if user has a specific permission.
        For public users, we use role-based permissions instead of Django's permission system.
        """
        if self.is_superuser:
            return True

        # Map permissions to role-based checks
        if 'seo' in perm:
            return self.can_manage_seo
        elif 'blog' in perm:
            return self.can_manage_blog
        elif 'support' in perm:
            return self.can_manage_support
        elif 'companies' in perm or 'company' in perm:
            return self.can_manage_companies
        elif 'analytics' in perm:
            return self.can_view_analytics

        return False

    def has_module_perms(self, app_label):
        """
        Check if user has permissions to view app in admin.
        """
        if self.is_superuser:
            return True

        app_permission_map = {
            'public_seo': self.can_manage_seo,
            'public_blog': self.can_manage_blog,
            'public_support': self.can_manage_support,
            'company': self.can_manage_companies,
            'public_analytics': self.can_view_analytics,
            'public_accounts': True,  # All staff can see their own account
        }

        return app_permission_map.get(app_label, False)

    @staticmethod
    def generate_identifier():
        """
        Generate unique identifier in format: PRIME-XXXXPF-YYMM-LTD
        XXXX: 4 random alphanumeric characters + symbols
        YY: Current year (last 2 digits)
        MM: Current month (01-12)
        """
        now = timezone.now()
        year = now.strftime('%y')  # Last 2 digits of year
        month = now.strftime('%m')  # Month as 01-12

        # Generate 4 random characters (letters, numbers, and safe symbols)
        chars = string.ascii_uppercase + string.digits + '#@$%'
        random_part = ''.join(random.choices(chars, k=4))

        identifier = f"PRIME-{random_part}PF-{year}{month}-LTD"

        # Ensure uniqueness
        while PublicUser.objects.filter(identifier=identifier).exists():
            random_part = ''.join(random.choices(chars, k=4))
            identifier = f"PRIME-{random_part}PF-{year}{month}-LTD"

        return identifier

    @staticmethod
    def generate_default_password(length=12):
        """Generate a secure random password"""
        chars = string.ascii_letters + string.digits + '!@#$%^&*'
        return ''.join(random.choices(chars, k=length))

    def send_welcome_email(self, password):
        """Send welcome email with login credentials"""
        subject = 'Your PrimeBook Admin Account - Login Credentials'

        message = f"""
Hello {self.get_full_name()},

Your PrimeBook Public Admin account has been created successfully!

Your Login Credentials:
------------------------
Login Identifier: {self.identifier}
Temporary Password: {password}

Login URL: {settings.PUBLIC_ADMIN_URL}/public-admin/

IMPORTANT SECURITY NOTICE:
- Please change your password immediately after your first login
- Never share your login identifier or password with anyone
- Your identifier is unique and cannot be changed

If you did not request this account, please contact support immediately.

Best regards,
PrimeBook Team
"""

        try:
            send_mail(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [self.email],
                fail_silently=False,
            )
        except Exception as e:
            print(f"Failed to send welcome email to {self.email}: {e}")

    def send_password_reset_email(self, reset_token):
        """Send password reset email"""
        subject = 'Password Reset Request - PrimeBook Admin'

        reset_url = f"{settings.PUBLIC_ADMIN_URL}/reset-password/{reset_token}/"

        message = f"""
Hello {self.get_full_name()},

We received a request to reset your password for your PrimeBook Admin account.

Your Login Identifier: {self.identifier}

To reset your password, click the link below:
{reset_url}

This link will expire in 24 hours.

If you did not request a password reset, please ignore this email or contact support if you have concerns.

Best regards,
PrimeBook Team
"""

        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [self.email],
            fail_silently=False,
        )

    def lock_account(self, duration_minutes=30):
        """Lock account after failed login attempts"""
        self.locked_until = timezone.now() + timezone.timedelta(minutes=duration_minutes)
        self.save(update_fields=['locked_until'])

    def unlock_account(self):
        """Unlock account and reset failed attempts"""
        self.locked_until = None
        self.failed_login_attempts = 0
        self.save(update_fields=['locked_until', 'failed_login_attempts'])

    @property
    def is_locked(self):
        """Check if account is locked"""
        return self.locked_until and self.locked_until > timezone.now()

    def record_login_attempt(self, success=True, ip_address=None):
        """Record login attempt"""
        if success:
            self.failed_login_attempts = 0
            self.last_activity = timezone.now()
            if ip_address:
                self.last_login_ip = ip_address
            self.save(update_fields=['failed_login_attempts', 'last_activity', 'last_login_ip'])
        else:
            self.failed_login_attempts += 1
            if self.failed_login_attempts >= 5:
                self.lock_account()
            self.save(update_fields=['failed_login_attempts'])

    def has_app_permission(self, app_name):
        """Check if user has permission for specific app"""
        if self.is_superuser or self.role == 'SUPER_ADMIN':
            return True

        permission_map = {
            'seo': self.can_manage_seo,
            'blog': self.can_manage_blog,
            'support': self.can_manage_support,
            'companies': self.can_manage_companies,
            'analytics': self.can_view_analytics,
        }

        return permission_map.get(app_name, False)


class PasswordResetToken(models.Model):
    """Password reset tokens for public users"""

    user = models.ForeignKey(
        PublicUser,
        on_delete=models.CASCADE,
        related_name='reset_tokens'
    )
    token = models.CharField(max_length=100, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        db_table = 'public_password_reset_tokens'
        ordering = ['-created_at']

    def __str__(self):
        return f"Reset token for {self.user.identifier}"

    @staticmethod
    def generate_token():
        """Generate secure random token"""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=64))

    def is_valid(self):
        """Check if token is still valid"""
        return not self.is_used and timezone.now() < self.expires_at

    def mark_as_used(self, ip_address=None):
        """Mark token as used"""
        self.is_used = True
        self.used_at = timezone.now()
        if ip_address:
            self.ip_address = ip_address
        self.save()


class PublicUserActivity(models.Model):
    """Track user activities in public admin"""

    ACTION_TYPES = [
        ('LOGIN', 'Login'),
        ('LOGOUT', 'Logout'),
        ('CREATE', 'Create'),
        ('UPDATE', 'Update'),
        ('DELETE', 'Delete'),
        ('VIEW', 'View'),
        ('EXPORT', 'Export'),
        ('PASSWORD_CHANGE', 'Password Change'),
        ('PASSWORD_RESET', 'Password Reset'),
    ]

    user = models.ForeignKey(
        PublicUser,
        on_delete=models.CASCADE,
        related_name='activities'
    )
    action = models.CharField(max_length=20, choices=ACTION_TYPES)
    app_name = models.CharField(max_length=50, blank=True)
    model_name = models.CharField(max_length=50, blank=True)
    object_id = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'public_user_activities'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', 'timestamp']),
            models.Index(fields=['action', 'timestamp']),
        ]

    def __str__(self):
        return f"{self.user.identifier} - {self.action} at {self.timestamp}"