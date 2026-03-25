from django.db import models
import uuid
from django.utils import timezone

class TenantPesapalConfig(models.Model):
    """
    Per-tenant Pesapal credentials.
    Tenants with use_own_keys=True use their own merchant account.
    All others fall back to the platform keys in settings.
    """
    tenant = models.OneToOneField(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='pesapal_config',
    )
    use_own_keys    = models.BooleanField(
        default=False,
        help_text='If True, use the keys below. Otherwise use platform keys.'
    )
    consumer_key    = models.CharField(max_length=300, blank=True)
    consumer_secret = models.CharField(max_length=300, blank=True)
    ipn_id          = models.CharField(
        max_length=100, blank=True,
        help_text='Pesapal IPN ID registered for this tenant.'
    )
    environment     = models.CharField(
        max_length=20,
        choices=[('sandbox', 'Sandbox'), ('production', 'Production')],
        default='sandbox',
    )
    is_active       = models.BooleanField(default=True)
    created_at      = models.DateTimeField(auto_now_add=True)
    updated_at      = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tenant Pesapal Config'
        verbose_name_plural = 'Tenant Pesapal Configs'

    def __str__(self):
        mode = 'own keys' if self.use_own_keys else 'platform keys'
        return f'{self.tenant.schema_name} [{mode}] [{self.environment}]'

    @property
    def effective_environment(self):
        return self.environment if self.use_own_keys else getattr(
            __import__('django.conf', fromlist=['settings']).settings,
            'PESAPAL_ENV', 'sandbox'
        )


class PlatformInvoice(models.Model):
    """
    SaaS billing invoice — this is when a TENANT pays YOU for their
    subscription plan OR a module add-on.  Lives on the PUBLIC schema.

    When `plan` is set   → subscription payment
    When `module` is set → module add-on activation payment
    """
    STATUS_CHOICES = [
        ('PENDING',  'Pending'),
        ('PAID',     'Paid'),
        ('FAILED',   'Failed'),
        ('REFUNDED', 'Refunded'),
        ('CANCELLED','Cancelled'),
    ]

    company          = models.ForeignKey(
        'company.Company',
        on_delete=models.CASCADE,
        related_name='platform_invoices',
    )
    plan             = models.ForeignKey(
        'company.SubscriptionPlan',
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    # ── Module add-on payments ─────────────────────────────────────────────────
    # Set when the tenant is paying to activate a specific module.
    # Mutually exclusive with `plan` (one or the other, not both).
    module           = models.ForeignKey(
        'company.AvailableModule',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='platform_invoices',
        help_text='Set when this invoice is for a module add-on purchase.',
    )

    invoice_number   = models.CharField(max_length=60, unique=True, editable=False)
    merchant_reference = models.CharField(max_length=100, blank=True, db_index=True)

    amount           = models.DecimalField(max_digits=12, decimal_places=2)
    currency         = models.CharField(max_length=10, default='UGX')
    description      = models.CharField(max_length=200)
    status           = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='PENDING'
    )

    # ── Pesapal tracking ──────────────────────────────────────────────────────
    pesapal_tracking_id  = models.CharField(max_length=100, blank=True, db_index=True)
    pesapal_confirmation = models.CharField(max_length=200, blank=True)
    redirect_url         = models.URLField(max_length=1000, blank=True)
    payment_method       = models.CharField(max_length=50, blank=True)
    payment_account      = models.CharField(max_length=100, blank=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    paid_at          = models.DateTimeField(null=True, blank=True)
    created_at       = models.DateTimeField(auto_now_add=True)
    updated_at       = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Platform Invoice'
        verbose_name_plural = 'Platform Invoices'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            self.invoice_number = self._generate_number()
        if not self.merchant_reference:
            self.merchant_reference = f'PLT-{uuid.uuid4().hex[:12].upper()}'
        super().save(*args, **kwargs)

    def _generate_number(self):
        year = timezone.now().year
        short = uuid.uuid4().hex[:8].upper()
        return f'PINV-{year}-{short}'

    def __str__(self):
        return f'{self.invoice_number} | {self.company.schema_name} | {self.status}'

    @property
    def is_paid(self):
        return self.status == 'PAID'

    @property
    def payment_type(self):
        """Human-readable payment type for admin / billing history."""
        if self.module_id:
            return 'Module Add-on'
        if self.plan_id:
            return 'Subscription'
        return 'Other'


class TenantPaymentTransaction(models.Model):
    """
    Audit trail for Pesapal transactions initiated from the tenant's OWN
    billing flows (tenant collecting from their customers).
    Lives on PUBLIC schema so the IPN handler can look it up without
    needing to know which tenant schema to switch to.
    """
    STATUS_CHOICES = [
        ('PENDING',   'Pending'),
        ('COMPLETED', 'Completed'),
        ('FAILED',    'Failed'),
        ('REVERSED',  'Reversed'),
        ('INVALID',   'Invalid'),
        ('CANCELLED', 'Cancelled'),
    ]

    TYPE_CHOICES = [
        ('INVOICE',      'Invoice Payment'),
        ('SUBSCRIPTION', 'Subscription'),
        ('ONE_TIME',     'One-time'),
    ]

    # ── Tenant routing ────────────────────────────────────────────────────────
    tenant_schema       = models.CharField(max_length=100, db_index=True)
    tenant              = models.ForeignKey(
        'company.Company',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='pesapal_transactions',
    )

    # ── Identifiers ───────────────────────────────────────────────────────────
    merchant_reference  = models.CharField(max_length=100, db_index=True)
    order_tracking_id   = models.CharField(max_length=100, blank=True, db_index=True)
    confirmation_code   = models.CharField(max_length=200, blank=True)

    # ── Payment details ───────────────────────────────────────────────────────
    amount              = models.DecimalField(max_digits=12, decimal_places=2)
    currency            = models.CharField(max_length=10, default='UGX')
    description         = models.CharField(max_length=200, blank=True)
    payment_method      = models.CharField(max_length=50, blank=True)
    payment_account     = models.CharField(max_length=100, blank=True)
    payment_type        = models.CharField(max_length=20, choices=TYPE_CHOICES, default='ONE_TIME')

    # ── Status ────────────────────────────────────────────────────────────────
    status              = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    status_code         = models.IntegerField(null=True, blank=True)

    # ── Linked object (invoice pk inside the tenant schema) ───────────────────
    object_type         = models.CharField(max_length=50, blank=True)
    object_id           = models.IntegerField(null=True, blank=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    redirect_url        = models.URLField(max_length=1000, blank=True)
    created_at          = models.DateTimeField(auto_now_add=True)
    updated_at          = models.DateTimeField(auto_now=True)
    paid_at             = models.DateTimeField(null=True, blank=True)

    raw_response        = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = 'Tenant Payment Transaction'
        verbose_name_plural = 'Tenant Payment Transactions'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.tenant_schema} | {self.merchant_reference} | {self.status}'


class PesapalIPNLog(models.Model):
    """Raw log of every inbound IPN call — lives on public schema."""
    NOTIFICATION_TYPES = [
        ('IPNCHANGE',   'IPN Change'),
        ('RECURRING',   'Recurring'),
        ('CALLBACKURL', 'Callback'),
    ]

    SOURCE_CHOICES = [
        ('platform', 'Platform (SaaS billing)'),
        ('tenant',   'Tenant (customer payment)'),
    ]

    order_tracking_id        = models.CharField(max_length=101, db_index=True)
    order_merchant_reference = models.CharField(max_length=100)
    order_notification_type  = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    source                   = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='tenant')
    tenant_schema            = models.CharField(max_length=100, blank=True)
    processed                = models.BooleanField(default=False)
    received_at              = models.DateTimeField(auto_now_add=True)
    raw_params               = models.JSONField(null=True, blank=True)
    error                    = models.TextField(blank=True)

    class Meta:
        verbose_name = 'IPN Log'
        verbose_name_plural = 'IPN Logs'
        ordering = ['-received_at']

    def __str__(self):
        return f'[{self.source}] [{self.order_notification_type}] {self.order_tracking_id}'