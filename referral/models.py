import uuid
import string
import random
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.utils import timezone


def generate_referral_code(length=8):
    """Generate a unique referral code."""
    chars = string.ascii_uppercase + string.digits
    while True:
        code = ''.join(random.choices(chars, k=length))
        if not Partner.objects.filter(referral_code=code).exists():
            return code


class PartnerManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, password, **extra_fields)


class Partner(AbstractBaseUser):
    """
    A marketing partner who refers new tenant companies.
    Lives in the PUBLIC schema (shared app).
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=30, blank=True)
    company_name = models.CharField(max_length=200, blank=True, help_text="Partner's own company/agency name")
    referral_code = models.CharField(max_length=20, unique=True, blank=True)

    # Status
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    is_approved = models.BooleanField(default=False, help_text="Admin must approve before partner can share links")

    # Timestamps
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    # Commission/reward settings (optional, extend as needed)
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00,
        help_text="Commission percentage e.g. 10.00 = 10%"
    )

    objects = PartnerManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['full_name']

    class Meta:
        verbose_name = 'Partner'
        verbose_name_plural = 'Partners'
        ordering = ['-date_joined']

    def __str__(self):
        return f"{self.full_name} ({self.email})"

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = generate_referral_code()
        super().save(*args, **kwargs)

    @property
    def total_referrals(self):
        return self.referrals.count()

    @property
    def successful_referrals(self):
        return self.referrals.filter(status='completed').count()

    @property
    def pending_referrals(self):
        return self.referrals.filter(status='pending').count()


class ReferralSignup(models.Model):
    """
    Records each time a company registers using a partner's referral link.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),        # Registered but not yet active tenant
        ('completed', 'Completed'),    # Tenant fully set up and active
        ('cancelled', 'Cancelled'),    # Registration abandoned / tenant deleted
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    partner = models.ForeignKey(
        Partner,
        on_delete=models.SET_NULL,
        null=True,
        related_name='referrals'
    )

    # Company that registered via referral
    company_name = models.CharField(max_length=200)
    company_email = models.EmailField()
    tenant_schema_name = models.CharField(
        max_length=100, blank=True,
        help_text="The schema_name of the created tenant, set after tenant creation"
    )
    subdomain = models.CharField(max_length=100, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    registered_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Commission tracking
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    commission_paid = models.BooleanField(default=False)

    # Raw referral tracking (store ref code even if partner is deleted)
    referral_code_used = models.CharField(max_length=20, blank=True)

    class Meta:
        verbose_name = 'Referral Signup'
        verbose_name_plural = 'Referral Signups'
        ordering = ['-registered_at']

    def __str__(self):
        return f"{self.company_name} → referred by {self.partner}"

    def mark_completed(self, tenant_schema_name='', subdomain=''):
        self.status = 'completed'
        self.completed_at = timezone.now()
        if tenant_schema_name:
            self.tenant_schema_name = tenant_schema_name
        if subdomain:
            self.subdomain = subdomain
        self.save()