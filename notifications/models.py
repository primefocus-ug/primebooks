from django.db import models
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.urls import reverse

User = get_user_model()


class Notification(models.Model):
    """
    Universal notification model for all types of notifications
    """

    NOTIFICATION_TYPES = [
        ('info', _('Information')),
        ('success', _('Success')),
        ('warning', _('Warning')),
        ('error', _('Error')),
        ('expense_created', _('Expense Created')),
        ('expense_submitted', _('Expense Submitted')),
        ('expense_approved', _('Expense Approved')),
        ('expense_rejected', _('Expense Rejected')),
        ('expense_paid', _('Expense Paid')),
        ('expense_comment', _('Expense Comment')),
        ('expense_reminder', _('Expense Reminder')),
        ('expense_overdue', _('Expense Overdue')),
        ('budget_alert', _('Budget Alert')),
        ('export_complete', _('Export Complete')),
        ('system', _('System Notification')),
        ('announcement', _('Announcement')),
    ]

    # Recipient
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='notifications',
        verbose_name=_("Recipient")
    )

    # Sender (optional - can be system)
    sender = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_notifications',
        verbose_name=_("Sender")
    )

    # Notification details
    notification_type = models.CharField(
        max_length=50,
        choices=NOTIFICATION_TYPES,
        default='info',
        db_index=True,
        verbose_name=_("Type")
    )

    title = models.CharField(
        max_length=255,
        verbose_name=_("Title")
    )

    message = models.TextField(
        verbose_name=_("Message")
    )

    # Action URL
    action_url = models.CharField(
        max_length=500,
        blank=True,
        verbose_name=_("Action URL"),
        help_text=_("URL to redirect when notification is clicked")
    )

    action_text = models.CharField(
        max_length=100,
        blank=True,
        default=_("View"),
        verbose_name=_("Action Text")
    )

    # Generic relation to any model
    content_type = models.ForeignKey(
        ContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True
    )
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey('content_type', 'object_id')

    # Status
    is_read = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Read")
    )

    read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Read At")
    )

    is_emailed = models.BooleanField(
        default=False,
        verbose_name=_("Emailed")
    )

    emailed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Emailed At")
    )

    # Priority
    priority = models.IntegerField(
        default=0,
        verbose_name=_("Priority"),
        help_text=_("Higher numbers = higher priority")
    )

    # Expiry
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Expires At")
    )

    # Metadata
    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata")
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['recipient', 'is_read', '-created_at']),
            models.Index(fields=['notification_type', '-created_at']),
        ]

    def __str__(self):
        return f"{self.title} - {self.recipient.username}"

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

    def is_expired(self):
        """Check if notification has expired"""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    def get_icon(self):
        """Get Bootstrap icon for notification type"""
        icons = {
            'info': 'bi-info-circle',
            'success': 'bi-check-circle',
            'warning': 'bi-exclamation-triangle',
            'error': 'bi-x-circle',
            'expense_created': 'bi-receipt',
            'expense_submitted': 'bi-send',
            'expense_approved': 'bi-check-circle',
            'expense_rejected': 'bi-x-circle',
            'expense_paid': 'bi-cash-coin',
            'expense_comment': 'bi-chat-dots',
            'expense_reminder': 'bi-bell',
            'expense_overdue': 'bi-exclamation-triangle',
            'budget_alert': 'bi-wallet2',
            'export_complete': 'bi-download',
            'system': 'bi-gear',
            'announcement': 'bi-megaphone',
        }
        return icons.get(self.notification_type, 'bi-bell')

    def get_color(self):
        """Get color class for notification type"""
        colors = {
            'info': 'primary',
            'success': 'success',
            'warning': 'warning',
            'error': 'danger',
            'expense_approved': 'success',
            'expense_rejected': 'danger',
            'expense_paid': 'success',
            'budget_alert': 'warning',
            'expense_overdue': 'danger',
        }
        return colors.get(self.notification_type, 'primary')


class NotificationPreference(models.Model):
    """
    User preferences for notifications
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='notification_preferences',
        verbose_name=_("User")
    )

    # Email preferences
    email_on_expense_approved = models.BooleanField(
        default=True,
        verbose_name=_("Email on Expense Approved")
    )

    email_on_expense_rejected = models.BooleanField(
        default=True,
        verbose_name=_("Email on Expense Rejected")
    )

    email_on_expense_paid = models.BooleanField(
        default=True,
        verbose_name=_("Email on Expense Paid")
    )

    email_on_comment = models.BooleanField(
        default=True,
        verbose_name=_("Email on Comment")
    )

    email_on_budget_alert = models.BooleanField(
        default=True,
        verbose_name=_("Email on Budget Alert")
    )

    # Push notification preferences
    push_enabled = models.BooleanField(
        default=True,
        verbose_name=_("Push Notifications Enabled")
    )

    push_on_expense_approved = models.BooleanField(
        default=True,
        verbose_name=_("Push on Expense Approved")
    )

    push_on_expense_rejected = models.BooleanField(
        default=True,
        verbose_name=_("Push on Expense Rejected")
    )

    # General preferences
    digest_frequency = models.CharField(
        max_length=20,
        choices=[
            ('realtime', _('Real-time')),
            ('daily', _('Daily Digest')),
            ('weekly', _('Weekly Digest')),
            ('never', _('Never')),
        ],
        default='realtime',
        verbose_name=_("Digest Frequency")
    )

    quiet_hours_start = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_("Quiet Hours Start"),
        help_text=_("Don't send notifications during this time")
    )

    quiet_hours_end = models.TimeField(
        null=True,
        blank=True,
        verbose_name=_("Quiet Hours End")
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Notification Preference")
        verbose_name_plural = _("Notification Preferences")

    def __str__(self):
        return f"Preferences for {self.user.username}"


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


class NotificationBatch(models.Model):
    """
    For tracking batch notifications (e.g., daily digests)
    """

    batch_type = models.CharField(
        max_length=50,
        verbose_name=_("Batch Type")
    )

    sent_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Sent At")
    )

    recipient_count = models.IntegerField(
        default=0,
        verbose_name=_("Recipient Count")
    )

    success_count = models.IntegerField(
        default=0,
        verbose_name=_("Success Count")
    )

    failure_count = models.IntegerField(
        default=0,
        verbose_name=_("Failure Count")
    )
    status = models.CharField(
        max_length=20,
        choices=[
            ('pending', _('Pending')),
            ('processing', _('Processing')),
            ('completed', _('Completed')),
            ('failed', _('Failed')),
        ],
        default='pending',
        verbose_name=_("Status")
    )

    error_message = models.TextField(
        blank=True,
        verbose_name=_("Error Message")
    )

    metadata = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Metadata")
    )

    class Meta:
        verbose_name = _("Notification Batch")
        verbose_name_plural = _("Notification Batches")
        ordering = ['-sent_at']

    def __str__(self):
        return f"{self.batch_type} - {self.sent_at}"