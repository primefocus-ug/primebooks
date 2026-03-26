from django.db import models
from django.core.validators import RegexValidator
import uuid
from referral.models import ReferralSignup


class TenantSignupRequest(models.Model):
    """Track tenant signup requests in public schema."""

    STATUS_CHOICES = [
        ('PENDING',    'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED',  'Completed'),
        ('FAILED',     'Failed'),
    ]

    request_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # ── Company Information ───────────────────────────────────────────────────
    company_name = models.CharField(max_length=255)
    trading_name = models.CharField(max_length=255, blank=True)
    subdomain = models.SlugField(
        max_length=63,
        unique=True,
        validators=[
            RegexValidator(r'^[a-z0-9-]+$', 'Only lowercase letters, numbers, and hyphens allowed')
        ]
    )

    # ── Contact Information ───────────────────────────────────────────────────
    email   = models.EmailField()
    phone   = models.CharField(max_length=20)
    country = models.CharField(max_length=100, default='Uganda')

    # ── Admin User Information ────────────────────────────────────────────────
    first_name  = models.CharField(max_length=50)
    last_name   = models.CharField(max_length=50)
    admin_email = models.EmailField()
    admin_phone = models.CharField(max_length=20)

    # ── Business Details ──────────────────────────────────────────────────────
    industry        = models.CharField(max_length=100, blank=True)
    business_type   = models.CharField(max_length=50, blank=True)
    estimated_users = models.PositiveIntegerField(default=1)

    # ── Plan Selection ────────────────────────────────────────────────────────
    # FK to the live SubscriptionPlan table — plan names and prices come from
    # the DB, never hardcoded in this model.
    #
    # FREE plan  → status stays PENDING, waits for your manual approval.
    # Paid plan  → Celery task fires immediately, auto-provisions the tenant
    #              (migrations, store, admin user) without you touching anything.
    #
    # SET_NULL on delete: retiring a plan never orphans old signup records.
    selected_plan = models.ForeignKey(
        'company.SubscriptionPlan',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='signup_requests',
        help_text='The plan the tenant chose at signup.',
    )

    # ── Status Tracking ───────────────────────────────────────────────────────
    status              = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    tenant_created      = models.BooleanField(default=False)
    created_company_id  = models.CharField(max_length=10, blank=True, null=True)
    created_schema_name = models.CharField(max_length=63, blank=True, null=True)

    # ── Error Tracking ────────────────────────────────────────────────────────
    error_message = models.TextField(blank=True, null=True)
    retry_count   = models.PositiveIntegerField(default=0)
    selected_modules = models.TextField(
        blank=True,
        default='',
        help_text="Comma-separated module keys chosen at signup, e.g. 'inventory,sales,purchases'"
    )
    # ── Metadata ──────────────────────────────────────────────────────────────
    ip_address      = models.GenericIPAddressField(blank=True, null=True)
    user_agent      = models.TextField(blank=True)
    referral_source = models.CharField(max_length=100, blank=True)

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        db_table = 'public_tenant_signup_requests'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['subdomain']),
            models.Index(fields=['email']),
            models.Index(fields=['status']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        plan_label = (
            self.selected_plan.display_name or self.selected_plan.name
        ) if self.selected_plan else 'No Plan'
        return f"{self.company_name} ({self.subdomain}) [{plan_label}] – {self.status}"

    # ── Convenience helpers ───────────────────────────────────────────────────

    @property
    def is_free_plan(self) -> bool:
        """True when the signup is on the FREE plan (or no plan set yet)."""
        if not self.selected_plan:
            return True
        return self.selected_plan.name == 'FREE'

    @property
    def is_paid_plan(self) -> bool:
        """True when the tenant chose a plan whose price > 0."""
        if not self.selected_plan:
            return False
        return self.selected_plan.price > 0

    @property
    def requires_manual_approval(self) -> bool:
        """
        Encapsulates the routing decision in one place.
        Free plan → True  (waits for admin approval).
        Paid plan → False (auto-provisioned immediately).
        """
        return self.is_free_plan


class SubdomainReservation(models.Model):
    """Reserved / blacklisted subdomains."""

    subdomain = models.SlugField(max_length=63, unique=True)
    reason = models.CharField(
        max_length=20,
        choices=[
            ('SYSTEM',  'System Reserved'),
            ('BRAND',   'Brand Protection'),
            ('BLOCKED', 'Blocked'),
        ]
    )
    notes      = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'public_subdomain_reservations'

    def __str__(self):
        return f"{self.subdomain} ({self.reason})"


class PublicNewsletterSubscriber(models.Model):
    """Newsletter subscriptions from public site."""

    email        = models.EmailField(unique=True)
    name         = models.CharField(max_length=255, blank=True)
    subscribed_at = models.DateTimeField(auto_now_add=True)
    is_active    = models.BooleanField(default=True)

    class Meta:
        db_table = 'public_newsletter_subscribers'

    def __str__(self):
        return self.email


class TenantApprovalWorkflow(models.Model):
    """Track approval workflow steps."""

    referral_signup = models.ForeignKey(
        'referral.ReferralSignup',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approval_workflows',
        help_text='The referral record that brought this signup, if any.',
    )
    signup_request = models.OneToOneField(
        TenantSignupRequest,
        on_delete=models.CASCADE,
        related_name='approval_workflow',
    )

    reviewed_by = models.ForeignKey(
        'public_accounts.PublicUser',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_signups',
    )
    reviewed_at    = models.DateTimeField(blank=True, null=True)
    approval_notes = models.TextField(blank=True, null=True)

    signup_notification_sent    = models.BooleanField(default=False)
    signup_notification_sent_at = models.DateTimeField(blank=True, null=True)

    approval_notification_sent    = models.BooleanField(default=False)
    approval_notification_sent_at = models.DateTimeField(blank=True, null=True)

    generated_password = models.CharField(max_length=255, blank=True, null=True)
    login_url          = models.URLField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'public_tenant_approval_workflow'

    def __str__(self):
        return f"Approval workflow for {self.signup_request.company_name}"


class TenantNotificationLog(models.Model):
    """Log all notifications sent."""

    NOTIFICATION_TYPES = [
        ('SIGNUP_TO_ADMIN',    'Signup Notification to Admin'),
        ('APPROVAL_TO_CLIENT', 'Approval Notification to Client'),
        ('REJECTION_TO_CLIENT','Rejection Notification to Client'),
        ('REMINDER_TO_ADMIN',  'Reminder to Admin'),
    ]

    signup_request    = models.ForeignKey(TenantSignupRequest, on_delete=models.CASCADE, related_name='notification_logs')
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES)
    recipient_email   = models.EmailField()
    subject           = models.CharField(max_length=255)
    sent_successfully = models.BooleanField(default=False)
    error_message     = models.TextField(blank=True, null=True)
    sent_at           = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'public_tenant_notification_log'
        ordering = ['-sent_at']

    def __str__(self):
        return f"{self.get_notification_type_display()} – {self.recipient_email}"