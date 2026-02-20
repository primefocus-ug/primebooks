from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.urls import reverse
import uuid
from django.template import Template, Context
from django.template.exceptions import TemplateSyntaxError

User = get_user_model()


class Announcement(models.Model):
    """
    System-wide announcements
    """

    ANNOUNCEMENT_TYPES = [
        ('info', _('Information')),
        ('warning', _('Warning')),
        ('maintenance', _('Maintenance')),
        ('update', _('Update')),
        ('feature', _('New Feature')),
        ('critical', _('Critical')),
    ]

    title = models.CharField(
        max_length=255,
        verbose_name=_("Title")
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    message = models.TextField(
        verbose_name=_("Message")
    )

    announcement_type = models.CharField(
        max_length=20,
        choices=ANNOUNCEMENT_TYPES,
        default='info',
        verbose_name=_("Type")
    )

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        verbose_name=_("Created By")
    )

    # Scheduling
    start_date = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Start Date")
    )

    end_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("End Date")
    )

    # Display options
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Active")
    )

    is_dismissible = models.BooleanField(
        default=True,
        verbose_name=_("Dismissible")
    )

    show_on_dashboard = models.BooleanField(
        default=True,
        verbose_name=_("Show on Dashboard")
    )

    # Action
    action_url = models.CharField(
        max_length=500,
        blank=True,
        verbose_name=_("Action URL")
    )

    action_text = models.CharField(
        max_length=100,
        blank=True,
        verbose_name=_("Action Text")
    )

    # Priority
    priority = models.IntegerField(
        default=0,
        verbose_name=_("Priority")
    )

    # Tracking
    dismissed_by = models.ManyToManyField(
        User,
        related_name='dismissed_announcements',
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Announcement")
        verbose_name_plural = _("Announcements")
        ordering = ['-priority', '-created_at']

    def __str__(self):
        return self.title

    def is_visible(self):
        """Check if announcement should be visible"""
        now = timezone.now()
        if not self.is_active:
            return False
        if now < self.start_date:
            return False
        if self.end_date and now > self.end_date:
            return False
        return True


class NotificationCategory(models.Model):
    """Categories for organizing notifications"""

    CATEGORY_TYPES = [
        ('SALES', 'Sales & Orders'),
        ('INVENTORY', 'Inventory & Stock'),
        ('EFRIS', 'EFRIS & Compliance'),
        ('FINANCE', 'Finance & Payments'),
        ('SYSTEM', 'System & Security'),
        ('USER', 'User Activity'),
        ('MESSAGING', 'Messages'),
        ('REPORTS', 'Reports'),
        ('COMPANY', 'Company Updates'),
    ]

    ICON_CHOICES = [
        ('shopping-cart', 'Shopping Cart'),
        ('package', 'Package'),
        ('file-text', 'Document'),
        ('alert-triangle', 'Alert'),
        ('check-circle', 'Success'),
        ('info', 'Information'),
        ('dollar-sign', 'Money'),
        ('user', 'User'),
        ('bell', 'Bell'),
        ('settings', 'Settings'),
    ]
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)
    category_type = models.CharField(max_length=20, choices=CATEGORY_TYPES)
    icon = models.CharField(max_length=30, choices=ICON_CHOICES, default='bell')
    color = models.CharField(max_length=20, default='primary')
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name_plural = "Notification Categories"
        ordering = ['sort_order', 'name']

    def __str__(self):
        return self.name


class NotificationTemplate(models.Model):
    """Templates for notification messages"""

    EVENT_TYPES = [
        # Sales Events
        ('sale_completed', 'Sale Completed'),
        ('sale_voided', 'Sale Voided'),
        ('sale_refunded', 'Sale Refunded'),
        ('payment_received', 'Payment Received'),
        ('invoice_created', 'Invoice Created'),
        ('invoice_overdue', 'Invoice Overdue'),

        # Inventory Events
        ('low_stock', 'Low Stock Alert'),
        ('out_of_stock', 'Out of Stock'),
        ('stock_received', 'Stock Received'),
        ('product_added', 'Product Added'),

        # EFRIS Events
        ('efris_fiscalized', 'EFRIS Fiscalized'),
        ('efris_failed', 'EFRIS Fiscalization Failed'),
        ('efris_sync_required', 'EFRIS Sync Required'),
        ('efris_certificate_expiring', 'EFRIS Certificate Expiring'),

        # Finance Events
        ('budget_exceeded', 'Budget Exceeded'),
        ('report_generated', 'Report Generated'),
        ('payment_due', 'Payment Due'),

        # System Events
        ('user_login', 'User Login'),
        ('suspicious_activity', 'Suspicious Activity'),
        ('device_authorized', 'Device Authorized'),
        ('backup_completed', 'Backup Completed'),

        # Company Events
        ('subscription_expiring', 'Subscription Expiring'),
        ('trial_ending', 'Trial Ending'),
        ('company_suspended', 'Company Suspended'),

        # Messaging Events
        ('new_message', 'New Message'),
        ('message_mention', 'Mentioned in Message'),

        # Custom
        ('custom', 'Custom Event'),
    ]

    name = models.CharField(max_length=200)
    event_type = models.CharField(max_length=50, choices=EVENT_TYPES, unique=True)
    category = models.ForeignKey(
        NotificationCategory,
        on_delete=models.SET_NULL,
        null=True,
        related_name='templates'
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    # Message templates
    title_template = models.CharField(
        max_length=255,
        help_text="Use {{variable}} for placeholders"
    )
    message_template = models.TextField(
        help_text="Use {{variable}} for placeholders"
    )

    # Channel settings
    send_in_app = models.BooleanField(default=True)
    send_email = models.BooleanField(default=False)
    send_sms = models.BooleanField(default=False)
    send_push = models.BooleanField(default=False)

    # Priority
    priority = models.CharField(
        max_length=20,
        choices=[
            ('LOW', 'Low'),
            ('MEDIUM', 'Medium'),
            ('HIGH', 'High'),
            ('URGENT', 'Urgent'),
        ],
        default='MEDIUM'
    )

    # Action button (optional)
    action_text = models.CharField(max_length=100, blank=True)
    action_url_template = models.CharField(
        max_length=500,
        blank=True,
        help_text="URL template with {{variable}} placeholders"
    )

    # Email template (if send_email=True)
    email_subject_template = models.CharField(max_length=255, blank=True)
    email_body_template = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.event_type})"

    def render(self, context):
        """Render template with context data using Django's template engine"""
        try:
            # Sanitize context - convert all values to strings
            safe_context = {}
            for key, value in context.items():
                if value is None:
                    safe_context[key] = ''
                elif isinstance(value, (str, int, float, bool)):
                    safe_context[key] = value
                else:
                    safe_context[key] = str(value)

            ctx = Context(safe_context, autoescape=True)

            # Render templates
            title = Template(self.title_template).render(ctx)
            message = Template(self.message_template).render(ctx)
            action_url = Template(self.action_url_template).render(ctx) if self.action_url_template else None
            email_subject = Template(self.email_subject_template).render(ctx) if self.email_subject_template else None
            email_body = Template(self.email_body_template).render(ctx) if self.email_body_template else None

            return {
                'title': title,
                'message': message,
                'action_url': action_url,
                'email_subject': email_subject,
                'email_body': email_body,
            }
        except TemplateSyntaxError as e:
            # Log the error and return safe defaults
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Template rendering error for {self.event_type}: {e}")

            return {
                'title': self.name,
                'message': 'Error rendering notification message',
                'action_url': None,
                'email_subject': None,
                'email_body': None,
            }


class Notification(models.Model):
    """Individual notifications sent to users"""

    NOTIFICATION_TYPES = [
        ('INFO', 'Information'),
        ('SUCCESS', 'Success'),
        ('WARNING', 'Warning'),
        ('ERROR', 'Error'),
        ('ALERT', 'Alert'),
    ]

    # Recipient
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    sender=models.ForeignKey(User,blank=True,null=True,on_delete=models.SET_NULL,related_name='sent_notifications')
    # Classification
    category = models.ForeignKey(
        NotificationCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )
    template = models.ForeignKey(
        NotificationTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='notifications'
    )
    notification_type = models.CharField(
        max_length=20,
        choices=NOTIFICATION_TYPES,
        default='INFO'
    )

    # Content
    title = models.CharField(max_length=255)
    message = models.TextField()

    # Priority
    priority = models.CharField(
        max_length=20,
        choices=[
            ('LOW', 'Low'),
            ('MEDIUM', 'Medium'),
            ('HIGH', 'High'),
            ('URGENT', 'Urgent'),
        ],
        default='MEDIUM'
    )

    # Related object (generic foreign key)
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    object_id = models.CharField(max_length=255,blank=True,null=True)
    related_object = GenericForeignKey('content_type', 'object_id')

    # Action
    action_text = models.CharField(max_length=100, blank=True)
    action_url = models.CharField(max_length=500, blank=True,null=True)

    # Metadata
    metadata = models.JSONField(default=dict, blank=True)

    # Delivery tracking
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    is_sent = models.BooleanField(default=False)
    sent_at = models.DateTimeField(null=True, blank=True)

    # Multi-channel delivery
    sent_via_email = models.BooleanField(default=False)
    email_sent_at = models.DateTimeField(null=True, blank=True)

    sent_via_sms = models.BooleanField(default=False)
    sms_sent_at = models.DateTimeField(null=True, blank=True)

    sent_via_push = models.BooleanField(default=False)
    push_sent_at = models.DateTimeField(null=True, blank=True)

    # Dismissal
    is_dismissed = models.BooleanField(default=False)
    dismissed_at = models.DateTimeField(null=True, blank=True)

    # Expiration
    expires_at = models.DateTimeField(null=True, blank=True)

    # Tenant context (for multi-tenant tracking)
    tenant_id = models.CharField(max_length=100, blank=True, db_index=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read', 'created_at']),
            models.Index(fields=['recipient', 'category', 'is_read']),
            models.Index(fields=['priority', 'is_read']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['tenant_id', 'created_at']),
            models.Index(fields=['tenant_id', 'is_sent']),  # NEW
        ]

    def __str__(self):
        return f"{self.title} - {self.recipient.get_full_name()}"

    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])

    def mark_as_unread(self):
        """Mark notification as unread"""
        if self.is_read:
            self.is_read = False
            self.read_at = None
            self.save(update_fields=['is_read', 'read_at'])

    def dismiss(self):
        """Dismiss notification"""
        self.is_dismissed = True
        self.dismissed_at = timezone.now()
        self.save(update_fields=['is_dismissed', 'dismissed_at'])

    @property
    def is_expired(self):
        """Check if notification has expired"""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    @property
    def time_since_created(self):
        """Get human-readable time since creation"""
        from django.utils.timesince import timesince
        return timesince(self.created_at)


class NotificationPreference(models.Model):
    """User preferences for notifications"""

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    # Global preferences
    email_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    push_enabled = models.BooleanField(default=True)
    in_app_enabled = models.BooleanField(default=True)

    # Quiet hours
    quiet_hours_enabled = models.BooleanField(default=False)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)

    # Frequency
    digest_enabled = models.BooleanField(default=False)
    digest_frequency = models.CharField(
        max_length=20,
        choices=[
            ('DAILY', 'Daily'),
            ('WEEKLY', 'Weekly'),
            ('MONTHLY', 'Monthly'),
        ],
        default='DAILY'
    )

    # Category-specific preferences (JSON)
    category_preferences = models.JSONField(
        default=dict,
        help_text="Per-category notification settings"
    )

    # Event-specific preferences
    event_preferences = models.JSONField(
        default=dict,
        help_text="Per-event notification settings"
    )

    # Do Not Disturb
    dnd_enabled = models.BooleanField(default=False)
    dnd_until = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Notification Preferences"

    def __str__(self):
        return f"Preferences for {self.user.get_full_name()}"

    def should_send_notification(self, category=None, event_type=None, channel='in_app'):
        """Check if notification should be sent based on preferences"""

        # Check DND
        if self.dnd_enabled:
            if self.dnd_until and timezone.now() < self.dnd_until:
                return False
            elif not self.dnd_until:
                return False

        # Check quiet hours
        if self.quiet_hours_enabled and self.quiet_hours_start and self.quiet_hours_end:
            current_time = timezone.now().time()
            if self.quiet_hours_start <= current_time <= self.quiet_hours_end:
                return False

        # Check channel
        channel_map = {
            'in_app': self.in_app_enabled,
            'email': self.email_enabled,
            'sms': self.sms_enabled,
            'push': self.push_enabled,
        }

        if not channel_map.get(channel, True):
            return False

        # Check category preferences
        if category and self.category_preferences:
            cat_prefs = self.category_preferences.get(str(category.id), {})
            if not cat_prefs.get('enabled', True):
                return False

        # Check event preferences
        if event_type and self.event_preferences:
            event_prefs = self.event_preferences.get(event_type, {})
            if not event_prefs.get('enabled', True):
                return False

        return True


class NotificationBatch(models.Model):
    """Batch notifications for bulk sending"""
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    name = models.CharField(max_length=200, blank=True, null=True)
    description = models.TextField(blank=True)

    # Recipients
    recipients = models.ManyToManyField(
        User,
        related_name='notification_batches'
    )
    recipient_count = models.PositiveIntegerField(default=0)

    # Content (from template)
    template = models.ForeignKey(
        NotificationTemplate,
        on_delete=models.CASCADE,
        related_name='batches',
        null=True,
        blank=True
    )
    context_data = models.JSONField(
        default=dict,
        blank=True,
        help_text="Context data for template rendering"
    )

    # Scheduling
    scheduled_for = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Schedule for future delivery"
    )

    # Status
    STATUS_CHOICES = [
        ('DRAFT', 'Draft'),
        ('SCHEDULED', 'Scheduled'),
        ('SENDING', 'Sending'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='DRAFT'
    )

    # Progress
    sent_count = models.PositiveIntegerField(default=0)
    failed_count = models.PositiveIntegerField(default=0)

    # Timing
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='created_batches'
    )
    created_at = models.DateTimeField(default=timezone.now)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "Notification Batches"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name or 'Batch'} ({self.recipient_count} recipients)"


class NotificationLog(models.Model):
    """Log of all notification deliveries"""

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name='delivery_logs'
    )
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    channel = models.CharField(
        max_length=20,
        choices=[
            ('in_app', 'In-App'),
            ('email', 'Email'),
            ('sms', 'SMS'),
            ('push', 'Push'),
        ]
    )

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('SENT', 'Sent'),
        ('DELIVERED', 'Delivered'),
        ('FAILED', 'Failed'),
        ('BOUNCED', 'Bounced'),
        ('OPENED', 'Opened'),
        ('CLICKED', 'Clicked'),
    ]
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING'
    )

    # Delivery details
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)

    # Error tracking
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveIntegerField(default=0)
    max_retries = models.PositiveIntegerField(default=3)

    # Metadata
    metadata = models.JSONField(default=dict)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['notification', 'channel']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['status', 'retry_count']),  # NEW
        ]

    def __str__(self):
        return f"{self.notification.title} via {self.channel} - {self.status}"

    def can_retry(self):
        """Check if notification can be retried"""
        return self.status == 'FAILED' and self.retry_count < self.max_retries


class NotificationRule(models.Model):
    """Automated notification rules based on triggers"""
    sync_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        db_index=True,
        editable=False,
        null=True, blank=True
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)

    # Trigger
    trigger_model = models.CharField(
        max_length=100,
        help_text="Model that triggers notification (e.g., 'sales.Sale')"
    )
    trigger_event = models.CharField(
        max_length=50,
        choices=[
            ('created', 'Created'),
            ('updated', 'Updated'),
            ('deleted', 'Deleted'),
            ('status_changed', 'Status Changed'),
            ('threshold_reached', 'Threshold Reached'),
        ]
    )

    # Conditions (JSON)
    conditions = models.JSONField(
        default=dict,
        help_text="Conditions that must be met for rule to trigger"
    )

    # Notification template
    template = models.ForeignKey(
        NotificationTemplate,
        on_delete=models.CASCADE,
        related_name='rules'
    )

    # Recipients
    RECIPIENT_TYPES = [
        ('SPECIFIC_USERS', 'Specific Users'),
        ('USER_ROLES', 'User Roles'),
        ('STORE_STAFF', 'Store Staff'),
        ('COMPANY_ADMINS', 'Company Admins'),
        ('CREATOR', 'Object Creator'),
        ('CUSTOM', 'Custom Logic'),
    ]
    recipient_type = models.CharField(
        max_length=30,
        choices=RECIPIENT_TYPES
    )
    specific_users = models.ManyToManyField(
        User,
        blank=True,
        related_name='notification_rules'
    )
    user_roles = models.JSONField(default=list, blank=True)

    # Status
    is_active = models.BooleanField(default=True)

    # Throttling
    throttle_enabled = models.BooleanField(default=False)
    throttle_minutes = models.PositiveIntegerField(
        default=60,
        help_text="Minimum minutes between notifications"
    )

    # Statistics
    triggered_count = models.PositiveIntegerField(default=0)
    last_triggered_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.trigger_model}.{self.trigger_event})"