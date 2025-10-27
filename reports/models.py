from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import JSONField
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.utils import timezone
from django.core.cache import cache
import hashlib
import json
from decimal import Decimal
from datetime import date, datetime

class SavedReport(models.Model):
    REPORT_TYPES = [
        ('SALES_SUMMARY', 'Sales Summary'),
        ('PRODUCT_PERFORMANCE', 'Product Performance'),
        ('INVENTORY_STATUS', 'Inventory Status'),
        ('TAX_REPORT', 'Tax Report'),
        ('Z_REPORT', 'Z Report'),
        ('PRICE_LOOKUP', 'Price Lookup Report'),
        ('EFRIS_COMPLIANCE', 'EFRIS Compliance Report'),
        ('CASHIER_PERFORMANCE', 'Cashier Performance'),
        ('PROFIT_LOSS', 'Profit & Loss Statement'),
        ('STOCK_MOVEMENT', 'Stock Movement Report'),
        ('CUSTOMER_ANALYTICS', 'Customer Analytics'),
        ('CUSTOM', 'Custom Report'),
    ]

    name = models.CharField(
        max_length=100,
        verbose_name=_("Report Name")
    )
    report_type = models.CharField(
        max_length=50,
        choices=REPORT_TYPES,
        verbose_name=_("Report Type")
    )
    description = models.TextField(
        blank=True,
        verbose_name=_("Description")
    )
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.PROTECT,
        related_name='created_reports'
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Created At")
    )
    last_modified = models.DateTimeField(
        auto_now=True,
        verbose_name=_("Last Modified")
    )
    last_executed = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Last Executed")
    )
    execution_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Execution Count")
    )
    is_shared = models.BooleanField(
        default=False,
        verbose_name=_("Is Shared")
    )
    is_favorite = models.BooleanField(
        default=False,
        verbose_name=_("Is Favorite")
    )
    columns = JSONField(
        default=list,
        verbose_name=_("Report Columns")
    )
    filters = JSONField(
        default=dict,
        verbose_name=_("Report Filters")
    )
    parameters = JSONField(
        default=dict,
        verbose_name=_("Report Parameters"),
        help_text=_("Additional parameters for report generation")
    )
    visualization_config = JSONField(
        default=dict,
        verbose_name=_("Visualization Configuration"),
        help_text=_("Chart.js configuration for visualizations")
    )
    is_efris_approved = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Approved"),
        help_text=_("Whether this report format is approved by URA")
    )
    cache_duration = models.PositiveIntegerField(
        default=300,
        verbose_name=_("Cache Duration (seconds)"),
        help_text=_("How long to cache report results")
    )
    enable_caching = models.BooleanField(
        default=True,
        verbose_name=_("Enable Caching")
    )
    pdf_orientation = models.CharField(
        max_length=10,
        choices=[('portrait', 'Portrait'), ('landscape', 'Landscape'), ('auto', 'Auto')],
        default='auto',
        verbose_name=_("PDF Orientation")
    )
    include_charts = models.BooleanField(
        default=True,
        verbose_name=_("Include Charts in Export")
    )
    tags = JSONField(
        default=list,
        verbose_name=_("Tags"),
        help_text=_("Tags for categorizing reports")
    )

    class Meta:
        verbose_name = _("Saved Report")
        verbose_name_plural = _("Saved Reports")
        ordering = ['-last_modified']
        indexes = [
            models.Index(fields=['report_type', 'is_shared']),
            models.Index(fields=['created_by', 'is_favorite']),
            models.Index(fields=['last_executed']),
        ]
        permissions = [
            ('generate_efris_reports', 'Can generate EFRIS reports'),
            ('approve_efris_reports', 'Can approve EFRIS reports'),
            ('export_reports', 'Can export reports'),
            ('schedule_reports', 'Can schedule reports'),
            ('share_reports', 'Can share reports'),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_report_type_display()})"

    def get_cache_key(self, user_id, **kwargs):
        serializable_kwargs = {}
        for key, value in kwargs.items():
            if isinstance(value, (date, datetime)):
                serializable_kwargs[key] = value.isoformat()
            elif isinstance(value, Decimal):
                serializable_kwargs[key] = float(value)
            elif hasattr(value, 'id'):
                serializable_kwargs[key] = value.id
            else:
                serializable_kwargs[key] = value

        filter_string = json.dumps(self.filters or {}, sort_keys=True, default=str)
        param_string = json.dumps(serializable_kwargs, sort_keys=True, default=str)
        hash_input = f"{self.id}:{user_id}:{filter_string}:{param_string}"
        return f"report:{hashlib.md5(hash_input.encode()).hexdigest()}"

    def increment_execution_count(self):
        """Increment execution counter safely, even for new instances"""
        self.execution_count += 1
        self.last_executed = timezone.now()

        if self.pk:  # Only force update if instance exists in DB
            self.save(update_fields=['execution_count', 'last_executed'])
        else:
            self.save()

    def invalidate_cache(self, user_id=None):
        """Invalidate cached report results"""
        if user_id:
            cache_key = self.get_cache_key(user_id)
            cache.delete(cache_key)
        else:
            # Clear all cache entries for this report
            if self.pk:  # Ensure instance has a primary key
                cache.delete_pattern(f"report:{self.id}:*")


class ReportSchedule(models.Model):
    FREQUENCIES = [
        ('HOURLY', 'Hourly'),
        ('DAILY', 'Daily'),
        ('WEEKLY', 'Weekly'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('YEARLY', 'Yearly'),
    ]

    DAYS_OF_WEEK = [
        (0, 'Monday'),
        (1, 'Tuesday'),
        (2, 'Wednesday'),
        (3, 'Thursday'),
        (4, 'Friday'),
        (5, 'Saturday'),
        (6, 'Sunday'),
    ]

    FORMAT_CHOICES = [
        ('PDF', 'PDF'),
        ('XLSX', 'Excel'),
        ('CSV', 'CSV'),
        ('JSON', 'JSON'),
    ]

    report = models.ForeignKey(
        SavedReport,
        on_delete=models.CASCADE,
        related_name='schedules'
    )
    frequency = models.CharField(
        max_length=20,
        choices=FREQUENCIES,
        verbose_name=_("Frequency")
    )
    day_of_week = models.IntegerField(
        choices=DAYS_OF_WEEK,
        blank=True,
        null=True,
        verbose_name=_("Day of Week"),
        help_text=_("Required for weekly frequency")
    )
    day_of_month = models.IntegerField(
        blank=True,
        null=True,
        verbose_name=_("Day of Month"),
        help_text=_("Required for monthly frequency"),
        validators=[MinValueValidator(1), MaxValueValidator(31)]
    )
    time_of_day = models.TimeField(
        default='09:00:00',
        verbose_name=_("Time of Day")
    )
    recipients = models.TextField(
        verbose_name=_("Recipients"),
        help_text=_("Comma-separated email addresses")
    )
    cc_recipients = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("CC Recipients"),
        help_text=_("Comma-separated email addresses")
    )
    format = models.CharField(
        max_length=10,
        choices=FORMAT_CHOICES,
        default='PDF',
        verbose_name=_("Export Format")
    )
    last_sent = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Last Sent At")
    )
    next_scheduled = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name=_("Next Scheduled Run")
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name=_("Is Active")
    )
    include_efris = models.BooleanField(
        default=False,
        verbose_name=_("Include EFRIS Data"),
        help_text=_("Include EFRIS verification data in scheduled reports")
    )
    efris_report_format = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name=_("EFRIS Report Format"),
        help_text=_("Format required by Uganda Revenue Authority")
    )
    retry_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Retry Count")
    )
    max_retries = models.PositiveIntegerField(
        default=3,
        verbose_name=_("Max Retries")
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Report Schedule")
        verbose_name_plural = _("Report Schedules")
        ordering = ['next_scheduled']

    def __str__(self):
        return f"{self.report.name} - {self.get_frequency_display()}"

    def calculate_next_run(self):
        """Calculate next scheduled run time"""
        from datetime import datetime, timedelta
        now = timezone.now()

        if self.frequency == 'HOURLY':
            next_run = now + timedelta(hours=1)
        elif self.frequency == 'DAILY':
            next_run = now + timedelta(days=1)
            next_run = next_run.replace(
                hour=self.time_of_day.hour,
                minute=self.time_of_day.minute,
                second=0
            )
        elif self.frequency == 'WEEKLY':
            days_ahead = self.day_of_week - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            next_run = now + timedelta(days=days_ahead)
            next_run = next_run.replace(
                hour=self.time_of_day.hour,
                minute=self.time_of_day.minute,
                second=0
            )
        elif self.frequency == 'MONTHLY':
            if now.day < self.day_of_month:
                next_run = now.replace(day=self.day_of_month)
            else:
                # Next month
                if now.month == 12:
                    next_run = now.replace(year=now.year + 1, month=1, day=self.day_of_month)
                else:
                    next_run = now.replace(month=now.month + 1, day=self.day_of_month)
            next_run = next_run.replace(
                hour=self.time_of_day.hour,
                minute=self.time_of_day.minute,
                second=0
            )
        else:
            next_run = now + timedelta(days=1)

        self.next_scheduled = next_run
        self.save(update_fields=['next_scheduled'])
        return next_run


class GeneratedReport(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]

    report = models.ForeignKey(
        SavedReport,
        on_delete=models.CASCADE,
        related_name='generated_instances'
    )
    generated_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    parameters = JSONField(
        default=dict,
        verbose_name=_("Generation Parameters")
    )
    file_path = models.CharField(
        max_length=500,
        verbose_name=_("File Path"),
        blank=True
    )
    file_format = models.CharField(
        max_length=10,
        choices=[
            ('PDF', 'PDF'),
            ('XLSX', 'Excel'),
            ('CSV', 'CSV'),
            ('JSON', 'JSON'),
        ],
        verbose_name=_("File Format")
    )
    file_size = models.PositiveBigIntegerField(
        default=0,
        verbose_name=_("File Size (bytes)")
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='PENDING',
        verbose_name=_("Status")
    )
    progress = models.PositiveIntegerField(
        default=0,
        validators=[MaxValueValidator(100)],
        verbose_name=_("Progress (%)")
    )
    error_message = models.TextField(
        blank=True,
        verbose_name=_("Error Message")
    )
    generated_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Generated At")
    )
    completed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Completed At")
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Expires At")
    )
    download_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Download Count")
    )
    is_efris_verified = models.BooleanField(
        default=False,
        verbose_name=_("EFRIS Verified")
    )
    efris_verification_code = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("EFRIS Verification Code")
    )
    efris_verification_date = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("EFRIS Verification Date")
    )
    task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name=_("Celery Task ID")
    )
    row_count = models.PositiveIntegerField(
        default=0,
        verbose_name=_("Row Count")
    )
    generation_time = models.FloatField(
        default=0.0,
        verbose_name=_("Generation Time (seconds)")
    )

    class Meta:
        verbose_name = _("Generated Report")
        verbose_name_plural = _("Generated Reports")
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['status', 'generated_at']),
            models.Index(fields=['generated_by', '-generated_at']),
            models.Index(fields=['task_id']),
        ]

    def __str__(self):
        return f"{self.report.name} - {self.generated_at.strftime('%Y-%m-%d %H:%M')}"

    def mark_as_processing(self):
        """Mark report as processing"""
        self.status = 'PROCESSING'
        self.progress = 10
        self.save(update_fields=['status', 'progress'])

    def update_progress(self, progress, message=None):
        """Update generation progress"""
        self.progress = min(progress, 100)
        if message:
            self.error_message = message
        self.save(update_fields=['progress', 'error_message'])

    def mark_as_completed(self, file_path, file_size, row_count, generation_time):
        """Mark report as completed"""
        self.status = 'COMPLETED'
        self.progress = 100
        self.file_path = file_path
        self.file_size = file_size
        self.row_count = row_count
        self.generation_time = generation_time
        self.completed_at = timezone.now()

        # Set expiration (30 days from completion)
        from datetime import timedelta
        self.expires_at = self.completed_at + timedelta(days=30)

        self.save()

    def mark_as_failed(self, error_message):
        """Mark report as failed"""
        self.status = 'FAILED'
        self.error_message = error_message
        self.completed_at = timezone.now()
        self.save()

    def increment_download_count(self):
        """Increment download counter"""
        self.download_count += 1
        self.save(update_fields=['download_count'])

    @property
    def is_expired(self):
        """Check if report has expired"""
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False


class ReportAccessLog(models.Model):
    """Audit trail for report access"""

    ACTION_CHOICES = [
        ('VIEW', 'Viewed'),
        ('GENERATE', 'Generated'),
        ('DOWNLOAD', 'Downloaded'),
        ('EXPORT', 'Exported'),
        ('SHARE', 'Shared'),
        ('DELETE', 'Deleted'),
        ('SCHEDULE', 'Scheduled'),
    ]

    report = models.ForeignKey(
        SavedReport,
        on_delete=models.CASCADE,
        related_name='access_logs',
        null=True,
        blank=True
    )
    generated_report = models.ForeignKey(
        GeneratedReport,
        on_delete=models.CASCADE,
        related_name='access_logs',
        null=True,
        blank=True
    )
    user = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.SET_NULL,
        null=True,
        related_name='report_accesses'
    )
    action = models.CharField(
        max_length=20,
        choices=ACTION_CHOICES,
        verbose_name=_("Action")
    )
    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
        verbose_name=_("IP Address")
    )
    user_agent = models.TextField(
        blank=True,
        verbose_name=_("User Agent")
    )
    parameters = JSONField(
        default=dict,
        verbose_name=_("Request Parameters")
    )
    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name=_("Timestamp")
    )
    duration = models.FloatField(
        default=0.0,
        verbose_name=_("Duration (seconds)")
    )
    success = models.BooleanField(
        default=True,
        verbose_name=_("Success")
    )
    error_message = models.TextField(
        blank=True,
        verbose_name=_("Error Message")
    )

    class Meta:
        verbose_name = _("Report Access Log")
        verbose_name_plural = _("Report Access Logs")
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['user', '-timestamp']),
            models.Index(fields=['report', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
        ]

    def __str__(self):
        return f"{self.user} - {self.action} - {self.timestamp}"


class ReportComparison(models.Model):
    """Store report comparison configurations"""

    name = models.CharField(
        max_length=200,
        verbose_name=_("Comparison Name")
    )
    report = models.ForeignKey(
        SavedReport,
        on_delete=models.CASCADE,
        related_name='comparisons'
    )
    created_by = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE
    )
    base_period = JSONField(
        verbose_name=_("Base Period"),
        help_text=_("Start and end dates for base period")
    )
    compare_period = JSONField(
        verbose_name=_("Compare Period"),
        help_text=_("Start and end dates for comparison period")
    )
    metrics = JSONField(
        default=list,
        verbose_name=_("Metrics to Compare")
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_run = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Report Comparison")
        verbose_name_plural = _("Report Comparisons")
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} - {self.report.name}"


class EFRISReportTemplate(models.Model):
    name = models.CharField(
        max_length=100,
        verbose_name=_("Template Name")
    )
    report_type = models.CharField(
        max_length=50,
        choices=SavedReport.REPORT_TYPES,
        verbose_name=_("Report Type")
    )
    template_file = models.FileField(
        upload_to='reports/efris_templates/',
        verbose_name=_("Template File")
    )
    is_default = models.BooleanField(
        default=False,
        verbose_name=_("Is Default Template")
    )
    version = models.CharField(
        max_length=20,
        verbose_name=_("Template Version")
    )
    valid_from = models.DateField(
        verbose_name=_("Valid From")
    )
    valid_to = models.DateField(
        blank=True,
        null=True,
        verbose_name=_("Valid To")
    )
    description = models.TextField(
        blank=True,
        null=True,
        verbose_name=_("Description")
    )
    is_active = models.BooleanField(default=True)
    ura_approved = models.BooleanField(
        default=False,
        verbose_name=_("URA Approved")
    )

    class Meta:
        verbose_name = _("EFRIS Report Template")
        verbose_name_plural = _("EFRIS Report Templates")
        ordering = ['-valid_from', 'report_type']

    def __str__(self):
        return f"{self.name} (v{self.version})"