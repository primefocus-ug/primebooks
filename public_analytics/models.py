from django.db import models
from django.utils import timezone
from django.contrib.postgres.fields import JSONField  # Or models.JSONField for Django 3.1+


class PageView(models.Model):
    """Track page views on public site"""

    # Page Info
    url_path = models.CharField(max_length=500)
    page_title = models.CharField(max_length=255, blank=True)
    referrer = models.CharField(max_length=500, blank=True)

    # Visitor Info
    session_id = models.CharField(max_length=64, db_index=True)
    visitor_id = models.CharField(max_length=64, db_index=True, help_text="Anonymous visitor ID")

    # Technical Info
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    browser = models.CharField(max_length=50, blank=True)
    os = models.CharField(max_length=50, blank=True)
    device_type = models.CharField(
        max_length=20,
        choices=[
            ('desktop', 'Desktop'),
            ('mobile', 'Mobile'),
            ('tablet', 'Tablet'),
            ('bot', 'Bot'),
        ],
        default='desktop'
    )

    # Location (can be enriched via IP lookup)
    country = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)

    # Timing
    viewed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    time_on_page_seconds = models.PositiveIntegerField(null=True, blank=True)

    # UTM Parameters
    utm_source = models.CharField(max_length=100, blank=True)
    utm_medium = models.CharField(max_length=100, blank=True)
    utm_campaign = models.CharField(max_length=100, blank=True)
    utm_term = models.CharField(max_length=100, blank=True)
    utm_content = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = 'public_analytics_pageviews'
        verbose_name = 'Page View'
        verbose_name_plural = 'Page Views'
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['url_path', 'viewed_at']),
            models.Index(fields=['session_id', 'viewed_at']),
            models.Index(fields=['visitor_id', 'viewed_at']),
            models.Index(fields=['utm_campaign', 'viewed_at']),
        ]

    def __str__(self):
        return f"{self.url_path} at {self.viewed_at}"


class Event(models.Model):
    """Track custom events (button clicks, form submissions, etc.)"""

    EVENT_CATEGORIES = [
        ('SIGNUP', 'Signup'),
        ('CLICK', 'Click'),
        ('FORM', 'Form'),
        ('DOWNLOAD', 'Download'),
        ('VIDEO', 'Video'),
        ('SCROLL', 'Scroll'),
        ('ENGAGEMENT', 'Engagement'),
    ]

    # Event Info
    category = models.CharField(max_length=50, choices=EVENT_CATEGORIES)
    action = models.CharField(max_length=100, help_text="e.g., 'clicked_pricing_cta'")
    label = models.CharField(max_length=255, blank=True)
    value = models.IntegerField(null=True, blank=True)

    # Page Context
    url_path = models.CharField(max_length=500)
    page_title = models.CharField(max_length=255, blank=True)

    # Visitor Info
    session_id = models.CharField(max_length=64, db_index=True)
    visitor_id = models.CharField(max_length=64, db_index=True)

    # Additional Data
    metadata = models.JSONField(default=dict, blank=True)

    # Timing
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'public_analytics_events'
        verbose_name = 'Event'
        verbose_name_plural = 'Events'
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['category', 'occurred_at']),
            models.Index(fields=['action', 'occurred_at']),
            models.Index(fields=['session_id', 'occurred_at']),
        ]

    def __str__(self):
        return f"{self.category}: {self.action}"


class Conversion(models.Model):
    """Track conversions (signups, trial starts, etc.)"""

    CONVERSION_TYPES = [
        ('SIGNUP_STARTED', 'Signup Started'),
        ('SIGNUP_COMPLETED', 'Signup Completed'),
        ('TRIAL_STARTED', 'Trial Started'),
        ('DEMO_REQUESTED', 'Demo Requested'),
        ('CONTACT_FORM', 'Contact Form Submitted'),
        ('NEWSLETTER_SIGNUP', 'Newsletter Signup'),
    ]

    # Conversion Info
    conversion_type = models.CharField(max_length=50, choices=CONVERSION_TYPES)
    conversion_value = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Monetary value of conversion"
    )

    # Visitor Journey
    visitor_id = models.CharField(max_length=64, db_index=True)
    session_id = models.CharField(max_length=64)
    first_touch_source = models.CharField(max_length=100, blank=True)
    last_touch_source = models.CharField(max_length=100, blank=True)

    # Attribution
    utm_source = models.CharField(max_length=100, blank=True)
    utm_medium = models.CharField(max_length=100, blank=True)
    utm_campaign = models.CharField(max_length=100, blank=True)

    # Related Objects
    signup_request_id = models.UUIDField(null=True, blank=True)
    company_id = models.CharField(max_length=10, blank=True)

    # Additional Data
    metadata = models.JSONField(default=dict, blank=True)

    # Timing
    converted_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = 'public_analytics_conversions'
        verbose_name = 'Conversion'
        verbose_name_plural = 'Conversions'
        ordering = ['-converted_at']
        indexes = [
            models.Index(fields=['conversion_type', 'converted_at']),
            models.Index(fields=['visitor_id', 'converted_at']),
            models.Index(fields=['utm_campaign', 'converted_at']),
        ]

    def __str__(self):
        return f"{self.get_conversion_type_display()} at {self.converted_at}"



class DailyStats(models.Model):
    """Aggregated daily statistics"""

    date = models.DateField(unique=True, db_index=True)

    # Traffic
    unique_visitors = models.PositiveIntegerField(default=0)
    total_pageviews = models.PositiveIntegerField(default=0)
    total_sessions = models.PositiveIntegerField(default=0)

    # Engagement
    avg_session_duration = models.FloatField(default=0)
    avg_pages_per_session = models.FloatField(default=0)
    bounce_rate = models.FloatField(default=0)

    # Conversions
    signups_started = models.PositiveIntegerField(default=0)
    signups_completed = models.PositiveIntegerField(default=0)
    conversion_rate = models.FloatField(default=0)

    # Top Pages
    top_pages = models.JSONField(default=list, blank=True)

    # Sources
    top_sources = models.JSONField(default=list, blank=True)
    top_campaigns = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'public_analytics_daily_stats'
        verbose_name = 'Daily Statistics'
        verbose_name_plural = 'Daily Statistics'
        ordering = ['-date']

    def __str__(self):
        return f"Stats for {self.date}"

class VisitorSession(models.Model):
    """Track visitor sessions"""

    session_id = models.CharField(max_length=64, unique=True, db_index=True)
    visitor_id = models.CharField(max_length=64, db_index=True)

    # Session Info
    started_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    # Entry/Exit
    entry_page = models.CharField(max_length=500)
    exit_page = models.CharField(max_length=500, blank=True)
    pages_viewed = models.PositiveIntegerField(default=0)

    # Engagement
    events_count = models.PositiveIntegerField(default=0)
    converted = models.BooleanField(default=False)

    # Source
    referrer = models.CharField(max_length=500, blank=True)
    utm_source = models.CharField(max_length=100, blank=True)
    utm_medium = models.CharField(max_length=100, blank=True)
    utm_campaign = models.CharField(max_length=100, blank=True)
    utm_term = models.CharField(max_length=100, blank=True)  # ADD THIS
    utm_content = models.CharField(max_length=100, blank=True)  # ADD THIS

    class Meta:
        db_table = 'public_analytics_sessions'
        verbose_name = 'Visitor Session'
        verbose_name_plural = 'Visitor Sessions'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['visitor_id', 'started_at']),
            models.Index(fields=['converted', 'started_at']),
        ]

    def __str__(self):
        return f"Session {self.session_id[:8]}..."