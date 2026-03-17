import uuid
import string
import random
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager
from django.utils import timezone
from decimal import Decimal


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

    # Commission/reward settings
    commission_rate = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.00,
        help_text="Commission percentage e.g. 10.00 = 10%"
    )

    # Branding / Ad customisation for QR share cards
    ad_tagline = models.CharField(
        max_length=120, blank=True,
        help_text="Custom tagline shown on the partner's shareable QR card (e.g. 'Get your business on PrimeBooks today!')"
    )
    ad_promo_text = models.CharField(
        max_length=200, blank=True,
        help_text="Short promotional text for the share card (e.g. 'Free 30-day trial + priority onboarding')"
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

    @property
    def total_earned(self):
        """Sum of all commission amounts from completed referrals."""
        result = self.referrals.filter(status='completed').aggregate(
            total=models.Sum('commission_amount')
        )
        return result['total'] or Decimal('0.00')

    @property
    def total_paid(self):
        """Sum of paid-out commissions."""
        result = self.referrals.filter(status='completed', commission_paid=True).aggregate(
            total=models.Sum('commission_amount')
        )
        return result['total'] or Decimal('0.00')

    @property
    def total_pending_payout(self):
        """Earned but not yet paid out."""
        return self.total_earned - self.total_paid


class ReferralSignup(models.Model):
    """
    Records each time a company registers using a partner's referral link.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
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
    tenant_schema_name = models.CharField(max_length=100, blank=True)
    subdomain = models.CharField(max_length=100, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    registered_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Commission tracking
    commission_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    commission_paid = models.BooleanField(default=False)
    commission_paid_at = models.DateTimeField(null=True, blank=True)

    # Raw referral tracking
    referral_code_used = models.CharField(max_length=20, blank=True)

    # UTM / campaign source tracking
    utm_source = models.CharField(max_length=100, blank=True, help_text="e.g. whatsapp, instagram, qrcode")
    utm_campaign = models.CharField(max_length=100, blank=True)

    class Meta:
        verbose_name = 'Referral Signup'
        verbose_name_plural = 'Referral Signups'
        ordering = ['-registered_at']

    def __str__(self):
        return f"{self.company_name} → referred by {self.partner}"

    def mark_completed(self, tenant_schema_name='', subdomain=''):
        from decimal import Decimal
        self.status = 'completed'
        self.completed_at = timezone.now()
        if tenant_schema_name:
            self.tenant_schema_name = tenant_schema_name
        if subdomain:
            self.subdomain = subdomain
        # Auto-calculate commission based on partner rate if not already set
        if self.commission_amount == Decimal('0.00') and self.partner:
            # Default base: 50,000 UGX per completed referral * partner rate
            base = Decimal('50000.00')
            self.commission_amount = (base * self.partner.commission_rate / Decimal('100')).quantize(Decimal('0.01'))
        self.save()

    def mark_commission_paid(self):
        self.commission_paid = True
        self.commission_paid_at = timezone.now()
        self.save()