from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import RegexValidator
from django.utils.translation import gettext_lazy as _
from django.db.models import Q
from django.conf import settings
from datetime import timedelta
from django_tenants.models import DomainMixin, TenantMixin
import uuid
from django.core.cache import cache
from django.apps import apps
import secrets
import logging
from django.utils import timezone
from django_tenants.utils import schema_context
from django.core.validators import MinValueValidator, MaxValueValidator
from django.core.exceptions import ValidationError
import smtplib
from email.mime.text import MIMEText

from .efris import EFRISCompanyMixin

User = get_user_model()
logger = logging.getLogger(__name__)

class TenantEmailSettings(models.Model):
    """
    Store tenant-specific email configuration
    """
    company = models.OneToOneField(
        'Company',
        on_delete=models.CASCADE,
        related_name='email_settings'
    )

    # SMTP Configuration
    smtp_host = models.CharField(
        max_length=255,
        help_text="SMTP server hostname (e.g., smtp.gmail.com)"
    )
    smtp_port = models.IntegerField(
        default=587,
        validators=[MinValueValidator(1), MaxValueValidator(65535)],
        help_text="SMTP server port (587 for TLS, 465 for SSL)"
    )
    smtp_username = models.CharField(
        max_length=255,
        help_text="SMTP authentication username"
    )
    smtp_password = models.CharField(
        max_length=255,
        help_text="SMTP authentication password (encrypted)"
    )

    # Security Settings
    use_tls = models.BooleanField(
        default=True,
        help_text="Use TLS encryption (port 587)"
    )
    use_ssl = models.BooleanField(
        default=False,
        help_text="Use SSL encryption (port 465)"
    )

    # Email Settings
    from_email = models.EmailField(
        help_text="Default 'from' email address for this tenant"
    )
    from_name = models.CharField(
        max_length=255,
        blank=True,
        help_text="Display name for from email"
    )
    reply_to_email = models.EmailField(
        blank=True,
        null=True,
        help_text="Reply-to email address"
    )

    # Additional Settings
    timeout = models.IntegerField(
        default=30,
        validators=[MinValueValidator(5), MaxValueValidator(300)],
        help_text="Connection timeout in seconds"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Enable/disable this email configuration"
    )
    is_verified = models.BooleanField(
        default=False,
        help_text="Email configuration has been tested and verified"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    test_result = models.TextField(blank=True, help_text="Result of last connection test")

    class Meta:
        verbose_name = "Tenant Email Settings"
        verbose_name_plural = "Tenant Email Settings"
        db_table = 'tenant_email_settings'

    def __str__(self):
        return f"Email Settings for {self.company.name}"

    def clean(self):
        """Validate that TLS and SSL are not both enabled"""
        if self.use_tls and self.use_ssl:
            raise ValidationError("Cannot use both TLS and SSL. Choose one.")

        # Validate port matches security setting
        if self.use_tls and self.smtp_port != 587:
            raise ValidationError("TLS typically uses port 587")
        if self.use_ssl and self.smtp_port != 465:
            raise ValidationError("SSL typically uses port 465")

    def test_connection(self):
        """
        Test SMTP connection with current settings
        Returns (success: bool, message: str)
        """
        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(
                    self.smtp_host,
                    self.smtp_port,
                    timeout=self.timeout
                )
            else:
                server = smtplib.SMTP(
                    self.smtp_host,
                    self.smtp_port,
                    timeout=self.timeout
                )
                if self.use_tls:
                    server.starttls()

            # Login
            server.login(self.smtp_username, self.smtp_password)

            # Send test email
            msg = MIMEText("This is a test email from your tenant configuration.")
            msg['Subject'] = "Test Email Configuration"
            msg['From'] = self.from_email
            msg['To'] = self.from_email

            server.send_message(msg)
            server.quit()

            self.is_verified = True
            self.test_result = "Connection successful"
            self.last_tested_at = timezone.now()
            self.save()

            return True, "Connection test successful"

        except smtplib.SMTPAuthenticationError:
            msg = "Authentication failed. Check username and password."
            self.is_verified = False
            self.test_result = msg
            self.save()
            return False, msg

        except smtplib.SMTPConnectError:
            msg = "Failed to connect to SMTP server. Check host and port."
            self.is_verified = False
            self.test_result = msg
            self.save()
            return False, msg

        except Exception as e:
            msg = f"Connection test failed: {str(e)}"
            self.is_verified = False
            self.test_result = msg
            self.save()
            return False, msg

    def get_from_email_with_name(self):
        """Return formatted from email with display name"""
        if self.from_name:
            return f"{self.from_name} <{self.from_email}>"
        return self.from_email


class TenantInvoiceSettings(models.Model):
    company = models.OneToOneField(
        'Company',
        on_delete=models.CASCADE,
        related_name='invoice_settings'
    )

    # Invoice Numbering
    invoice_prefix = models.CharField(
        max_length=10,
        default="INV",
        help_text="Prefix for invoice numbers (e.g., INV, BILL)"
    )
    invoice_number_start = models.IntegerField(
        default=1000,
        help_text="Starting number for invoices"
    )
    invoice_number_padding = models.IntegerField(
        default=4,
        validators=[MinValueValidator(3), MaxValueValidator(10)],
        help_text="Number of digits in invoice number"
    )

    # Invoice Terms
    default_payment_terms_days = models.IntegerField(
        default=30,
        help_text="Default payment terms in days"
    )
    invoice_notes = models.TextField(
        blank=True,
        help_text="Default notes to include on invoices"
    )
    invoice_terms = models.TextField(
        blank=True,
        help_text="Default terms and conditions for invoices"
    )

    # Invoice Design
    show_company_logo = models.BooleanField(default=True)
    invoice_template = models.CharField(
        max_length=50,
        default='default',
        choices=[
            ('default', 'Default Template'),
            ('modern', 'Modern Template'),
            ('classic', 'Classic Template'),
            ('minimal', 'Minimal Template'),
        ]
    )

    # Tax Settings
    default_tax_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        help_text="Default tax rate percentage"
    )
    tax_name = models.CharField(
        max_length=50,
        default="VAT",
        help_text="Tax name (e.g., VAT, GST, Sales Tax)"
    )

    # Email Settings
    send_invoice_email = models.BooleanField(
        default=True,
        help_text="Automatically send invoice via email"
    )
    invoice_email_subject = models.CharField(
        max_length=255,
        default="Invoice {invoice_number} from {company_name}",
        help_text="Email subject template. Variables: {invoice_number}, {company_name}"
    )
    invoice_email_body = models.TextField(
        default="Please find attached your invoice.",
        help_text="Email body for invoice notifications"
    )

    # EFRIS Integration
    enable_efris = models.BooleanField(
        default=False,
        help_text="Enable EFRIS integration for this tenant"
    )
    efris_tin = models.CharField(
        max_length=50,
        blank=True,
        help_text="TIN number for EFRIS"
    )
    efris_device_no = models.CharField(
        max_length=50,
        blank=True,
        help_text="EFRIS device number"
    )
    efris_private_key = models.TextField(
        blank=True,
        help_text="EFRIS private key for signing"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Tenant Invoice Settings"
        verbose_name_plural = "Tenant Invoice Settings"
        db_table = 'tenant_invoice_settings'

    def __str__(self):
        return f"Invoice Settings for {self.company.name}"

    def get_next_invoice_number(self):
        """Generate next invoice number based on settings"""
        from invoices.models import Invoice

        last_invoice = Invoice.objects.filter(
            company=self.company
        ).order_by('-created_at').first()

        if last_invoice and last_invoice.invoice_number:
            # Extract number from last invoice
            try:
                last_num = int(last_invoice.invoice_number.replace(self.invoice_prefix, ''))
                next_num = last_num + 1
            except ValueError:
                next_num = self.invoice_number_start
        else:
            next_num = self.invoice_number_start

        # Format with padding
        number_str = str(next_num).zfill(self.invoice_number_padding)
        return f"{self.invoice_prefix}{number_str}"

def generate_company_id():
    """Generate unique company code e.g., PF-N123456"""
    uid = uuid.uuid4().int
    return f"PF-N{str(uid)[:6]}"


class SubscriptionPlan(models.Model):
    PLAN_CHOICES = [
        ('FREE', _('Free Trial')),
        ('BASIC', _('Basic')),
        ('PRO', _('Pro')),
        ('ENTERPRISE', _('Enterprise')),
    ]

    BILLING_CYCLES = [
        ('MONTHLY', _('Monthly')),
        ('QUARTERLY', _('Quarterly')),
        ('YEARLY', _('Yearly')),
    ]

    name = models.CharField(max_length=50, choices=PLAN_CHOICES, unique=True)
    display_name = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)

    # Pricing
    price = models.DecimalField(max_digits=10, decimal_places=2)
    setup_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    billing_cycle = models.CharField(max_length=20, choices=BILLING_CYCLES, default='MONTHLY')
    trial_days = models.PositiveIntegerField(default=30)

    # Limits
    max_users = models.PositiveIntegerField(default=5)
    max_branches = models.PositiveIntegerField(default=1)
    max_storage_gb = models.PositiveIntegerField(default=1, help_text=_("Storage limit in GB"))
    max_api_calls_per_month = models.PositiveIntegerField(default=1000)
    max_transactions_per_month = models.PositiveIntegerField(default=500)

    # Features
    features = models.JSONField(default=dict,blank=True, help_text=_("Feature flags for this plan"))
    can_use_api = models.BooleanField(default=False)
    can_export_data = models.BooleanField(default=True)
    can_use_integrations = models.BooleanField(default=False)
    can_use_advanced_reports = models.BooleanField(default=False)
    can_use_multi_currency = models.BooleanField(default=False)
    can_use_custom_branding = models.BooleanField(default=False)

    support_level = models.CharField(
        max_length=20,
        choices=[
            ('BASIC', _('Basic Support')),
            ('PRIORITY', _('Priority Support')),
            ('DEDICATED', _('Dedicated Support')),
        ],
        default='BASIC'
    )

    # Status
    is_active = models.BooleanField(default=True)
    is_popular = models.BooleanField(default=False)
    sort_order = models.PositiveIntegerField(default=0)

    # Metadata
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'price']
        verbose_name = _('Subscription Plan')
        verbose_name_plural = _('Subscription Plans')

    def __str__(self):
        display = self.display_name or self.get_name_display()
        return f"{display} - ${self.price}/{self.get_billing_cycle_display().lower()}"

    @property
    def monthly_price(self):
        """Convert price to monthly equivalent"""
        if self.billing_cycle == 'YEARLY':
            return self.price / 12
        elif self.billing_cycle == 'QUARTERLY':
            return self.price / 3
        return self.price

    def get_feature_list(self):
        """Get list of enabled features"""
        base_features = []
        if self.can_use_api:
            base_features.append(_('API Access'))
        if self.can_export_data:
            base_features.append(_('Data Export'))
        if self.can_use_integrations:
            base_features.append(_('Third-party Integrations'))
        if self.can_use_advanced_reports:
            base_features.append(_('Advanced Reports'))
        if self.can_use_multi_currency:
            base_features.append(_('Multi-currency Support'))
        if self.can_use_custom_branding:
            base_features.append(_('Custom Branding'))

        # Add custom features from JSON field
        base_features.extend(self.features.get('additional_features', []))
        return base_features


class CompanyQuerySet(models.QuerySet):
    def active(self):
        """Return companies with active access."""
        today = timezone.now().date()
        return self.filter(
            Q(is_trial=True, trial_ends_at__gte=today) |
            Q(is_trial=False, subscription_ends_at__gte=today)
        )

    def expired(self):
        """Return companies with expired access."""
        today = timezone.now().date()
        return self.filter(
            Q(is_trial=True, trial_ends_at__lt=today) &
            Q(subscription_ends_at__isnull=True)
        ) | self.filter(
            Q(is_trial=False, subscription_ends_at__lt=today)
        )

    def by_plan(self, plan_name):
        """Filter companies by plan."""
        return self.filter(plan__name=plan_name)


class CompanyManager(models.Manager):
    def get_queryset(self):
        return CompanyQuerySet(self.model, using=self._db)

    def active(self):
        return self.get_queryset().active()

    def expired(self):
        return self.get_queryset().expired()

    def by_plan(self, plan_name):
        return self.get_queryset().by_plan(plan_name)

class Company(TenantMixin,EFRISCompanyMixin):
    CURRENCY_CHOICES = [
        ('UGX', 'Ugandan Shilling'),
        ('USD', 'US Dollar'),
        ('KES', 'Kenyan Shilling'),
        ('EUR', 'Euro'),
        ('GBP', 'British Pound'),
    ]

    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('TRIAL', 'Trial'),
        ('SUSPENDED', 'Suspended'),
        ('EXPIRED', 'Expired'),
        ('ARCHIVED', 'Archived'),
    ]

    EFRIS_MODE_CHOICES = [
        ('online', 'Online Mode'),
        ('offline', 'Offline Mode'),
    ]

    # Core Company Information
    company_id = models.CharField(
        max_length=10,
        unique=True,
        primary_key=True,
        default=generate_company_id,
        verbose_name=_("Company ID")
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='companies'
    )
    schema_name = models.CharField(max_length=63, unique=True)

    # Company Details
    name = models.CharField(max_length=255, blank=True, verbose_name=_("Legal Company Name"))
    trading_name = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("Trading Name"))
    slug = models.SlugField(max_length=50, unique=True, blank=True)
    description = models.TextField(blank=True, verbose_name=_("Company Description"))

    # Contact Information
    physical_address = models.TextField(_("Physical Address"), blank=True)
    postal_address = models.CharField(max_length=255, blank=True, null=True, verbose_name=_("Postal Address"))
    phone = models.CharField(
        max_length=20,
        validators=[RegexValidator(r'^\+?[0-9]+$', _('Enter a valid phone number.'))],
        blank=True,
        verbose_name=_("Primary Phone")
    )
    email = models.EmailField(max_length=400, blank=True, verbose_name=_("Primary Email"))
    website = models.URLField(blank=True, null=True, verbose_name=_("Website"))

    # Tax Information
    tin = models.CharField(max_length=20, blank=True, null=True, verbose_name=_("TIN"))
    brn = models.CharField(max_length=20, blank=True, null=True, verbose_name=_("BRN"))
    nin = models.CharField(max_length=20, blank=True, null=True, verbose_name=_("NIN"))
    vat_registration_number = models.CharField(max_length=50, blank=True, null=True)
    vat_registration_date = models.DateField(blank=True, null=True)
    preferred_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='UGX')

    # EFRIS Core Settings
    efris_enabled = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Enabled"),
        help_text=_("Master switch for EFRIS integration")
    )
    efris_is_production = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Production Mode"),
        help_text=_("Use production EFRIS servers")
    )
    efris_integration_mode = models.CharField(
        max_length=10,
        choices=EFRIS_MODE_CHOICES,
        default='offline',
        verbose_name=_("EFRIS Integration Mode")
    )

    # EFRIS API Credentials (EFRIS-specific fields with no business equivalent)
    efris_client_id = models.CharField(max_length=100, blank=True, null=True, verbose_name=_("EFRIS Client ID"))
    efris_api_key = models.CharField(max_length=200, blank=True, null=True, verbose_name=_("EFRIS API Key"))
    efris_device_number = models.CharField(max_length=50, blank=True, null=True, verbose_name=_("EFRIS Device Number"))
    efris_certificate_data = models.JSONField(
        default=dict,blank=True,
        verbose_name=_("EFRIS Certificate Data"),
        help_text=_("RSA keys and certificate information")
    )

    # EFRIS Automation Settings
    efris_auto_fiscalize_sales = models.BooleanField(
        default=True,
        verbose_name=_("Auto-Fiscalize Sales"),
        help_text=_("Automatically fiscalize completed sales invoices")
    )
    efris_auto_sync_products = models.BooleanField(
        default=True,
        verbose_name=_("Auto-Sync Products"),
        help_text=_("Automatically create EFRIS goods for new products")
    )

    # EFRIS Status Fields
    efris_is_active = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Active"),
        help_text=_("EFRIS integration is active and functional")
    )
    efris_is_registered = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Registered"),
        help_text=_("Company is registered with EFRIS servers")
    )
    efris_last_sync = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("EFRIS Last Sync"),
        help_text=_("Last successful sync with EFRIS")
    )
    certificate_status = models.CharField(max_length=50, blank=True, null=True)
    # Subscription and Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='TRIAL')
    is_trial = models.BooleanField(default=True)
    trial_ends_at = models.DateField(null=True, blank=True)
    subscription_starts_at = models.DateField(null=True, blank=True)
    subscription_ends_at = models.DateField(null=True, blank=True)
    grace_period_ends_at = models.DateField(null=True, blank=True, help_text="Grace period after subscription expires")

    # Billing Information
    last_payment_date = models.DateField(null=True, blank=True)
    next_billing_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=50, blank=True, null=True)
    billing_email = models.EmailField(blank=True, null=True)

    # Localization
    time_zone = models.CharField(max_length=100, default='Africa/Kampala')
    locale = models.CharField(max_length=10, default='en-UG')
    date_format = models.CharField(max_length=20, default='%d/%m/%Y', help_text='Date display format')
    time_format = models.CharField(max_length=10, default='24', choices=[('12', '12 Hour'), ('24', '24 Hour')])

    # Branding
    logo = models.ImageField(upload_to='company/logos/', blank=True, null=True)
    favicon = models.ImageField(upload_to='company/favicons/', blank=True, null=True)
    brand_colors = models.JSONField(default=dict,blank=True, help_text="Primary and secondary brand colors")

    # Security
    is_verified = models.BooleanField(default=False)
    verification_token = models.CharField(max_length=100, blank=True, null=True)
    two_factor_required = models.BooleanField(default=False)
    ip_whitelist = models.JSONField(default=list,blank=True, help_text="Allowed IP addresses")

    # Usage Tracking
    storage_used_mb = models.PositiveIntegerField(default=0)
    api_calls_this_month = models.PositiveIntegerField(default=0)
    last_activity_at = models.DateTimeField(null=True, blank=True)

    # Admin Fields
    notes = models.TextField(blank=True, help_text="Internal notes about this company")
    tags = models.JSONField(default=list,blank=True, help_text="Tags for categorizing companies")

    # Tenant Settings
    auto_create_schema = True
    auto_drop_schema = True

    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    created_on = models.DateTimeField(auto_now_add=True)

    objects = CompanyManager()

    class Meta:
        verbose_name = _("Company")
        verbose_name_plural = _("Companies")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['trial_ends_at']),
            models.Index(fields=['subscription_ends_at']),
            models.Index(fields=['last_activity_at']),
            models.Index(fields=['efris_enabled']),
            models.Index(fields=['efris_is_active']),
            models.Index(fields=['efris_last_sync']),
        ]

    def __str__(self):
        return self.display_name

    def save(self, *args, **kwargs):
        # Generate slug from name if not provided
        if not self.slug:
            from django.utils.text import slugify
            self.slug = slugify(self.trading_name or self.name)[:50]

        for field in ['tin', 'brn', 'nin']:
            val = getattr(self, field, None)
            if val:
                setattr(self, field, val.upper().strip())

        # Set trial period for new companies
        if not self.pk and self.is_trial and not self.trial_ends_at:
            from datetime import timedelta
            self.trial_ends_at = timezone.now().date() + timedelta(days=60)
            self.status = 'TRIAL'

        # Default free plan
        if not self.plan:
            free_plan, _ = SubscriptionPlan.objects.get_or_create(
                name='FREE',
                defaults={
                    'display_name': 'Free Trial',
                    'price': 0,
                    'trial_days': 60,
                    'max_users': 5,
                    'max_branches': 1,
                    'max_storage_gb': 1
                }
            )
            self.plan = free_plan

        # Set grace period for new subscriptions
        if self.subscription_ends_at and not self.grace_period_ends_at:
            from datetime import timedelta
            self.grace_period_ends_at = self.subscription_ends_at + timedelta(days=7)

        # Update status based on subscription
        if not kwargs.get('skip_status_update'):
            self.check_and_update_access_status()

        super().save(*args, **kwargs)

        # Clear cache when company is updated
        self._clear_cache()

    def _clear_cache(self):
        """Clear cached data for this company."""
        cache_keys = [
            f'company_{self.company_id}_branches_count',
            f'company_{self.company_id}_storage_usage',
            f'company_{self.company_id}_efris_status',
        ]
        cache.delete_many(cache_keys)

    # EFRIS Properties - Direct mapping from business data
    @property
    def efris_taxpayer_name(self):
        """EFRIS taxpayer name - uses legal company name"""
        return self.name



    @property
    def efris_config(self):
        """Get EFRIS configuration safely (django-tenants compatible)"""
        from django_tenants.utils import schema_context
        from efris.models import EFRISConfiguration

        try:
            with schema_context(self.schema_name):
                from django.db import connection
                from django.db.utils import ProgrammingError, OperationalError
                # Check if table exists in this schema
                with connection.cursor() as cursor:
                    cursor.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM information_schema.tables 
                            WHERE table_schema = %s AND table_name = 'efris_efrisconfiguration'
                        )
                    """, [self.schema_name])
                    if not cursor.fetchone()[0]:
                        return None

                return EFRISConfiguration.get_for_company(self)
        except (ProgrammingError, OperationalError):
            # Happens if schema context not ready or migrations pending
            return None

    @property
    def efris_business_name(self):
        """EFRIS business name - uses trading name or legal name"""
        return self.trading_name or self.name

    @property
    def efris_email_address(self):
        """EFRIS email - uses primary company email"""
        return self.email

    @property
    def efris_phone_number(self):
        """EFRIS phone - uses primary company phone"""
        return self.phone

    @property
    def efris_business_address(self):
        """EFRIS business address - uses physical address"""
        return self.physical_address

    # Other Properties
    @property
    def display_name(self):
        return self.trading_name or self.name

    @property
    def is_trial_active(self):
        return self.is_trial and self.trial_ends_at and self.trial_ends_at >= timezone.now().date()

    @property
    def is_subscription_active(self):
        return not self.is_trial and self.subscription_ends_at and self.subscription_ends_at >= timezone.now().date()

    @property
    def has_active_access(self):
        """Check if company has active access (trial or subscription)."""
        return self.status in ['ACTIVE', 'TRIAL']

    @property
    def is_in_grace_period(self):
        """Check if company is in grace period after subscription expired."""
        return self.status == 'SUSPENDED' and self.grace_period_ends_at and self.grace_period_ends_at >= timezone.now().date()

    @property
    def days_until_expiry(self):
        """Get days until expiry."""
        today = timezone.now().date()
        if self.is_trial and self.trial_ends_at:
            return (self.trial_ends_at - today).days
        elif self.subscription_ends_at:
            return (self.subscription_ends_at - today).days
        return 0

    # EFRIS Properties
    @property
    def efris_api_url(self):
        """Get EFRIS API URL based on environment."""
        if self.efris_is_production:
            return "https://efrisws.ura.go.ug/ws/taapp/getInformation"
        return "https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation"

    @property
    def efris_status_display(self):
        """Human-readable EFRIS status."""
        if not self.efris_enabled:
            return "Disabled"
        elif not self.efris_is_active:
            return "Enabled but Inactive"
        elif not self.efris_is_registered:
            return "Active but Not Registered"
        else:
            return "Active and Registered"

    @property
    def efris_configuration_complete(self):
        """Check if EFRIS configuration is complete."""
        if not self.efris_enabled:
            return False

        # Check required business fields
        required_fields = [
            self.tin,
            self.name,  # for efris_taxpayer_name
            self.email,  # for efris_email_address
            self.phone,  # for efris_phone_number
            self.physical_address,  # for efris_business_address
        ]

        # Business name can be trading_name or name
        business_name = self.trading_name or self.name

        return all(required_fields) and bool(business_name)

    @property
    def branches_count(self):
        """Get cached branch count."""
        cache_key = f'company_{self.company_id}_branches_count'
        count = cache.get(cache_key)
        if count is None:
            CompanyBranch = apps.get_model('stores', 'Store')
            count = CompanyBranch.objects.filter(
                company=self,
                is_active=True
            ).count()
            cache.set(cache_key, count, 300)
        return count

    @property
    def active_branches(self):
        """Get active branches for this company."""
        CompanyBranch = apps.get_model('stores', 'Store')
        return CompanyBranch.objects.filter(
            company=self,
            is_active=True
        )

    def can_add_branch(self):
        """Check if company can add more branches."""
        if not self.plan:
            return False
        return self.branches_count < self.plan.max_branches

    @property
    def storage_usage_percentage(self):
        """Get storage usage as percentage."""
        if self.plan and self.plan.max_storage_gb > 0:
            return (self.storage_used_mb / (self.plan.max_storage_gb * 1024)) * 100
        return 0

    def can_use_feature(self, feature_name):
        """Check if company can use a specific feature."""
        if not self.plan or not self.has_active_access:
            return False
        return self.plan.features.get(feature_name, False)

    def extend_trial(self, days=30):
        """Extend trial period."""
        if self.is_trial and self.trial_ends_at:
            self.trial_ends_at += timedelta(days=days)
            self.save()
            logger.info(f"Extended trial for company {self.company_id} by {days} days")

    def activate_subscription(self, plan, duration_months=None):
        """Activate paid subscription."""
        self.plan = plan
        self.is_trial = False
        self.subscription_starts_at = timezone.now().date()

        duration = duration_months or plan.duration_months
        self.subscription_ends_at = self.subscription_starts_at + timedelta(days=duration * 30)
        self.next_billing_date = self.subscription_ends_at

        # Set grace period (7 days after expiry)
        self.grace_period_ends_at = self.subscription_ends_at + timedelta(days=7)

        self.status = 'ACTIVE'
        self.save()

        logger.info(f"Activated subscription for company {self.company_id} with plan {plan.name}")

    def suspend_access(self, reason=""):
        """Suspend company access."""
        self.status = 'SUSPENDED'
        if reason:
            self.notes = f"{self.notes}\nSuspended: {reason} at {timezone.now()}"
        self.save()
        logger.warning(f"Suspended company {self.company_id}: {reason}")

    def generate_verification_token(self):
        """Generate new verification token."""
        self.verification_token = secrets.token_urlsafe(32)
        self.save()
        return self.verification_token

    def update_last_activity(self):
        """Update last activity timestamp."""
        self.last_activity_at = timezone.now()
        self.save(update_fields=['last_activity_at'])

    def get_domain_url(self):
        """Get the primary domain for this tenant without port."""
        domain = self.domains.filter(is_primary=True).first()
        if domain:
            return domain.domain.split(':')[0]
        return None

    def get_absolute_url(self):
        """Return normalized absolute URL for this tenant."""
        domain = self.get_domain_url()
        base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')

        if domain:
            return f"https://{domain}"
        return f"https://{self.slug}.{base_domain}"

    # EFRIS Methods
    def enable_efris(self, validate=True):
        """Enable EFRIS integration with optional validation."""
        if validate and not self.efris_configuration_complete:
            raise ValueError("EFRIS configuration is incomplete. Please fill all required company fields.")

        self.efris_enabled = True
        self.efris_is_active = True
        self.save(update_fields=['efris_enabled', 'efris_is_active'])

        logger.info(f"EFRIS enabled for company {self.company_id}")

    def disable_efris(self, reason=""):
        """Disable EFRIS integration."""
        self.efris_enabled = False
        self.efris_is_active = False

        if reason:
            timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
            self.notes = f"{self.notes}\n[{timestamp}] EFRIS disabled: {reason}" if self.notes else f"[{timestamp}] EFRIS disabled: {reason}"

        self.save()
        logger.info(f"EFRIS disabled for company {self.company_id}: {reason}")

    def update_efris_sync(self, sync_successful=True):
        """Update EFRIS last sync timestamp."""
        if sync_successful:
            self.efris_last_sync = timezone.now()
            self.save(update_fields=['efris_last_sync'])

    def get_efris_configuration_errors(self):
        """Get list of EFRIS configuration errors."""
        errors = []

        if not self.efris_enabled:
            return errors

        required_fields = {
            'tin': 'TIN Number',
            'name': 'Legal Company Name',
            'email': 'Primary Email',
            'phone': 'Primary Phone',
            'physical_address': 'Physical Address'
        }

        for field, label in required_fields.items():
            if not getattr(self, field):
                errors.append(f"{label} is required for EFRIS integration")

        # Check business name
        if not (self.trading_name or self.name):
            errors.append("Trading Name or Legal Company Name is required")

        return errors

    def get_efris_data(self):
        """Get company data formatted for EFRIS API."""
        return {
            'tin': self.tin,
            'taxpayerName': self.efris_taxpayer_name,
            'businessName': self.efris_business_name,
            'emailAddress': self.efris_email_address,
            'phoneNumber': self.efris_phone_number,
            'businessAddress': self.efris_business_address,
            'deviceNumber': self.efris_device_number,
            'isProduction': self.efris_is_production,
        }

    def check_and_update_access_status(self):
        """
        Check subscription status and update company access accordingly.
        Returns True if status changed, False otherwise.
        """
        old_status = self.status
        old_is_active = self.is_active

        today = timezone.now().date()

        # Check trial status
        if self.is_trial:
            if self.trial_ends_at and self.trial_ends_at < today:
                self.status = 'EXPIRED'
                self.is_active = False
            else:
                self.status = 'TRIAL'
                self.is_active = True

        # Check subscription status
        else:
            if not self.subscription_ends_at:
                self.status = 'EXPIRED'
                self.is_active = False
            elif self.subscription_ends_at >= today:
                self.status = 'ACTIVE'
                self.is_active = True
            elif self.grace_period_ends_at and self.grace_period_ends_at >= today:
                self.status = 'SUSPENDED'
                self.is_active = False
            else:
                self.status = 'EXPIRED'
                self.is_active = False

        # Check for manual suspension
        if not self.is_active and self.status in ['ACTIVE', 'TRIAL']:
            self.status = 'SUSPENDED'

        # Save if changed
        status_changed = (old_status != self.status or old_is_active != self.is_active)
        if status_changed:
            self.save(update_fields=['status', 'is_active', 'updated_at'])

            if not self.is_active:
                self.deactivate_all_users()
            elif self.is_active and not old_is_active:
                self.reactivate_all_users()

        return status_changed

    def deactivate_company(self, reason="Subscription expired"):
        """Manually deactivate company and all users"""
        self.is_active = False
        self.status = 'SUSPENDED'

        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        self.notes = f"{self.notes}\n[{timestamp}] Deactivated: {reason}" if self.notes else f"[{timestamp}] Deactivated: {reason}"

        self.save()
        self.deactivate_all_users()

        logger.warning(f"Company {self.company_id} deactivated: {reason}")

    def reactivate_company(self, reason="Subscription renewed"):
        """Reactivate company and users"""
        self.is_active = True

        if self.is_trial and self.is_trial_active:
            self.status = 'TRIAL'
        elif not self.is_trial and self.is_subscription_active:
            self.status = 'ACTIVE'

        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        self.notes = f"{self.notes}\n[{timestamp}] Reactivated: {reason}" if self.notes else f"[{timestamp}] Reactivated: {reason}"

        self.save()
        self.reactivate_all_users()

        # Clear all relevant caches
        self._clear_all_caches()

        # Clear Django cache for this company
        from django.core.cache import cache
        cache.delete(f'company_status_{self.company_id}')
        cache.delete(f'company_access_{self.company_id}')
        cache.delete(f'tenant_{self.schema_name}_status')

        logger.info(f"Company {self.company_id} reactivated: {reason}")

    def reallow_company(self, reason="Subscription renewed", days=30, grace_days=7):
        """Reactivate company and users"""
        from django.utils import timezone
        from datetime import timedelta

        self.is_active = True
        self.is_trial = False

        self.subscription_starts_at = timezone.now().date()
        self.subscription_ends_at = (timezone.now() + timedelta(days=days)).date()
        self.grace_period_ends_at = (timezone.now() + timedelta(days=days + grace_days)).date()
        self.status = "ACTIVE"

        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        self.notes = f"{self.notes}\n[{timestamp}] Reactivated: {reason}" if self.notes else f"[{timestamp}] Reactivated: {reason}"

        self.save()
        self.reactivate_all_users()

        # Clear all relevant caches
        self._clear_all_caches()

        # Clear Django cache for this company
        from django.core.cache import cache
        cache.delete(f'company_status_{self.company_id}')
        cache.delete(f'company_access_{self.company_id}')
        cache.delete(f'tenant_{self.schema_name}_status')

        logger.info(f"Company {self.company_id} reactivated: {reason}")

    def _clear_all_caches(self):
        """Clear all cached data for this company."""
        cache_keys = [
            f'company_{self.company_id}_branches_count',
            f'company_{self.company_id}_storage_usage',
            f'company_{self.company_id}_efris_status',
            f'company_{self.company_id}_status',
            f'company_{self.company_id}_access',
            f'tenant_{self.schema_name}_active',
            f'tenant_{self.schema_name}_expired',
        ]

        from django.core.cache import cache
        cache.delete_many(cache_keys)

        # Also clear any tenant-specific caches
        with schema_context(self.schema_name):
            cache.clear()  # Clear all cache for this tenant

    def force_status_refresh(self):
        """Force refresh of status from database and clear caches"""
        # Refresh from DB
        self.refresh_from_db(fields=[
            'status', 'is_active', 'subscription_ends_at',
            'trial_ends_at', 'grace_period_ends_at'
        ])

        # Update status
        self.check_and_update_access_status()

        # Clear caches
        self._clear_all_caches()

        return self

    def deactivate_all_users(self):
        """Deactivate all users in this company (tenant-aware)"""
        with schema_context(self.schema_name):
            updated_count = User.objects.filter(
                is_active=True,
            ).update(is_active=False)

            logger.info(f"Deactivated {updated_count} users for company {self.name}")
            return updated_count

    def reactivate_all_users(self):
        """Reactivate all users in this company (tenant-aware)"""
        with schema_context(self.schema_name):
            updated_count = User.objects.filter(
                is_active=False,
            ).update(is_active=True)

            logger.info(f"Reactivated {updated_count} users for company {self.name}")
            return updated_count

    def suspend_for_misbehavior(self, reason, suspended_by=None):
        """Suspend company for policy violations"""
        self.is_active = False
        self.status = 'SUSPENDED'

        timestamp = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        by_user = f" by {suspended_by.get_full_name()}" if suspended_by else ""
        self.notes = f"{self.notes}\n[{timestamp}] SUSPENDED FOR MISBEHAVIOR{by_user}: {reason}" if self.notes else f"[{timestamp}] SUSPENDED FOR MISBEHAVIOR{by_user}: {reason}"

        self.save()
        self.deactivate_all_users()

        logger.critical(f"Company {self.company_id} suspended for misbehavior: {reason}")

    @property
    def access_status_display(self):
        """Human-readable access status"""
        if not self.is_active:
            return f"No Access ({self.get_status_display()})"

        if self.status == 'TRIAL':
            days_left = self.days_until_expiry
            return f"Trial ({days_left} days left)"
        elif self.status == 'ACTIVE':
            days_left = self.days_until_expiry
            return f"Active ({days_left} days left)"
        elif self.status == 'SUSPENDED':
            if self.is_in_grace_period:
                return "Grace Period"
            return "Suspended"

        return self.get_status_display()

    def extend_grace_period(self, days=7):
        """Extend grace period for expired companies"""
        if self.subscription_ends_at:
            from datetime import timedelta
            self.grace_period_ends_at = (self.grace_period_ends_at or self.subscription_ends_at) + timedelta(days=days)
            self.save()
            logger.info(f"Extended grace period for company {self.company_id} by {days} days")

    def get_access_restrictions(self):
        """Get list of current access restrictions"""
        restrictions = []

        if not self.is_active:
            restrictions.append("Account suspended - no access allowed")
        elif self.status == 'EXPIRED':
            restrictions.append("Subscription expired - please renew")
        elif self.status == 'SUSPENDED':
            if self.is_in_grace_period:
                days_left = (self.grace_period_ends_at - timezone.now().date()).days
                restrictions.append(f"Grace period - {days_left} days to renew")
            else:
                restrictions.append("Account suspended - contact support")

        # Check usage limits
        if self.plan:
            if self.storage_usage_percentage > 100:
                restrictions.append("Storage limit exceeded")
            elif self.storage_usage_percentage > 90:
                restrictions.append("Storage nearly full")

            user_count = User.objects.filter(company=self).count()
            if user_count >= self.plan.max_users:
                restrictions.append("User limit reached")

        # EFRIS restrictions
        if self.efris_enabled and not self.efris_configuration_complete:
            restrictions.append("EFRIS configuration incomplete")

        return restrictions

    def can_perform_action(self, action):
        """Check if company can perform specific actions"""
        if not self.is_active or not self.has_active_access:
            return False, "Account suspended or expired"

        action_requirements = {
            'create_invoice': ['has_active_access'],
            'add_user': ['has_active_access', 'under_user_limit'],
            'export_data': ['has_active_access', 'plan_allows_export'],
            'use_api': ['has_active_access', 'plan_allows_api'],
            'create_branch': ['has_active_access', 'can_add_branch'],
            'use_efris': ['has_active_access', 'efris_enabled', 'efris_configured'],
            'fiscalize_invoice': ['has_active_access', 'efris_enabled', 'efris_active'],
        }

        requirements = action_requirements.get(action, ['has_active_access'])

        for requirement in requirements:
            if requirement == 'has_active_access' and not self.has_active_access:
                return False, "No active access"
            elif requirement == 'under_user_limit':
                user_count = User.objects.filter(company=self).count()
                if self.plan and user_count >= self.plan.max_users:
                    return False, "User limit reached"
            elif requirement == 'plan_allows_export' and self.plan and not self.plan.can_export_data:
                return False, "Plan doesn't allow data export"
            elif requirement == 'plan_allows_api' and self.plan and not self.plan.can_use_api:
                return False, "Plan doesn't allow API access"
            elif requirement == 'can_add_branch' and not self.can_add_branch():
                return False, "Branch limit reached"
            elif requirement == 'efris_enabled' and not self.efris_enabled:
                return False, "EFRIS integration not enabled"
            elif requirement == 'efris_configured' and not self.efris_configuration_complete:
                return False, "EFRIS configuration incomplete"
            elif requirement == 'efris_active' and not self.efris_is_active:
                return False, "EFRIS integration not active"

        return True, "Action allowed"


class Domain(DomainMixin):
    """
    Domain model for django-tenants.
    Enhanced with additional fields for better domain management.
    """
    tenant = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name='domains'
    )

    # Additional fields
    is_primary = models.BooleanField(default=False)
    ssl_enabled = models.BooleanField(default=True)
    redirect_to_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tenant_domains'

    def save(self, *args, **kwargs):
        # Ensure only one primary domain per tenant
        if self.is_primary:
            Domain.objects.filter(tenant=self.tenant, is_primary=True).exclude(id=self.id).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.domain} ({'Primary' if self.is_primary else 'Secondary'})"


class EFRISCommodityCategory(models.Model):
    commodity_category_code = models.CharField(
        max_length=18, unique=True, db_index=True
    )
    parent_code = models.CharField(
        max_length=18, blank=True, null=True, help_text="Parent category code (0 if top-level)"
    )
    commodity_category_name = models.CharField(max_length=200)
    commodity_category_level = models.CharField(max_length=5, blank=True, null=True)

    rate = models.DecimalField(
        max_digits=5, decimal_places=2, blank=True, null=True, help_text="Applicable VAT rate"
    )

    service_mark = models.CharField(
        max_length=3,
        choices=[('101', 'Product'), ('102', 'Service')],
        default='101',
        help_text="101 = Product, 102 = Service"
    )

    is_leaf_node = models.CharField(
        max_length=3,
        choices=[('101', 'Yes'), ('102', 'No')],
        default='101'
    )

    is_zero_rate = models.CharField(
        max_length=3,
        choices=[('101', 'Yes'), ('102', 'No')],
        default='102'
    )
    zero_rate_start_date = models.CharField(max_length=20, blank=True, null=True)
    zero_rate_end_date = models.CharField(max_length=20, blank=True, null=True)

    is_exempt = models.CharField(
        max_length=3,
        choices=[('101', 'Yes'), ('102', 'No')],
        default='102'
    )
    exempt_rate_start_date = models.CharField(max_length=20, blank=True, null=True)
    exempt_rate_end_date = models.CharField(max_length=20, blank=True, null=True)

    enable_status_code = models.CharField(
        max_length=3, blank=True, null=True, help_text="1 = Enabled, 0 = Disabled"
    )
    exclusion = models.CharField(max_length=3, blank=True, null=True)

    last_synced = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['commodity_category_code']
        indexes = [
            models.Index(fields=['commodity_category_code']),
            models.Index(fields=['commodity_category_name']),
        ]

    def __str__(self):
        return f"{self.commodity_category_code} - {self.commodity_category_name}"

    @property
    def type(self):
        """Human-readable category type"""
        return "Service" if self.service_mark == '102' else "Product"
