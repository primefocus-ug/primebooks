# primebooks/models.py
"""
Version Management Models
✅ Lifecycle states (Active, Stable, Deprecated, EOL)
✅ Rollback support
✅ Error reporting
"""
from django.db import models
from django.core.validators import FileExtensionValidator
from django.utils import timezone


class AppVersion(models.Model):
    """Application version with lifecycle management"""

    # Version info
    version = models.CharField(max_length=20, unique=True)
    release_date = models.DateTimeField()
    release_notes = models.TextField()

    # Lifecycle states
    LIFECYCLE_CHOICES = [
        ('active', '🟢 Active - Fully supported'),
        ('stable', '🔵 Stable - Security updates only'),
        ('deprecated', '⚠️ Deprecated - Limited support'),
        ('eol', '🔴 End of Life - No support'),
    ]
    lifecycle_status = models.CharField(
        max_length=20,
        choices=LIFECYCLE_CHOICES,
        default='active'
    )

    # Lifecycle dates
    active_date = models.DateTimeField(default=timezone.now)
    stable_date = models.DateTimeField(null=True, blank=True)
    deprecated_date = models.DateTimeField(null=True, blank=True)
    eol_date = models.DateTimeField(null=True, blank=True)
    is_critical = models.BooleanField(
        default=False,
        help_text="Mark this version as critical - forces immediate attention"
    )
    # Warnings
    deprecation_warning = models.TextField(
        blank=True,
        help_text="Message shown to users on deprecated version"
    )
    eol_warning = models.TextField(
        blank=True,
        help_text="Message shown to users on EOL version"
    )

    # Rollback support
    requires_rollback = models.BooleanField(
        default=False,
        help_text="Force users to rollback from this version"
    )
    rollback_target = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='rollback_from',
        help_text="Version to rollback to"
    )
    rollback_reason = models.TextField(
        blank=True,
        help_text="Why rollback is required"
    )
    rollback_priority = models.CharField(
        max_length=20,
        choices=[
            ('low', 'Low - User can delay'),
            ('medium', 'Medium - User should update soon'),
            ('critical', 'Critical - Forced immediate rollback'),
        ],
        default='low',
        blank=True
    )

    # Files
    windows_file = models.FileField(
        upload_to='downloads/windows/',
        validators=[FileExtensionValidator(['exe'])],
        null=True,
        blank=True
    )
    linux_file = models.FileField(
        upload_to='downloads/linux/',
        null=True,
        blank=True
    )
    mac_file = models.FileField(
        upload_to='downloads/mac/',
        validators=[FileExtensionValidator(['dmg', 'pkg'])],
        null=True,
        blank=True
    )

    file_size_mb = models.DecimalField(max_digits=6, decimal_places=2)

    # Status flags
    is_latest = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-release_date']
        verbose_name = 'App Version'
        verbose_name_plural = 'App Versions'

    def __str__(self):
        return f"v{self.version} ({self.get_lifecycle_status_display()})"

    def save(self, *args, **kwargs):
        # Only one version can be latest
        if self.is_latest:
            AppVersion.objects.exclude(pk=self.pk).update(is_latest=False)
        super().save(*args, **kwargs)

    def get_download_url(self, platform='windows'):
        """Get download URL for platform"""
        files = {
            'windows': self.windows_file,
            'linux': self.linux_file,
            'mac': self.mac_file,
        }
        file_field = files.get(platform)
        return file_field.url if file_field else None


class ErrorReport(models.Model):
    """Error reports from desktop app"""

    # Error details
    error_type = models.CharField(max_length=200)
    error_message = models.TextField()
    traceback = models.TextField()

    # Context
    app_version = models.ForeignKey(
        AppVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )


    # System info
    os_name = models.CharField(max_length=50, blank=True)
    os_version = models.CharField(max_length=100, blank=True)
    python_version = models.CharField(max_length=20, blank=True)

    # Additional data
    logs = models.TextField(blank=True)
    system_info = models.JSONField(null=True, blank=True)

    # Metadata
    is_critical = models.BooleanField(default=False)
    is_resolved = models.BooleanField(default=False)
    resolution_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Error Report'
        verbose_name_plural = 'Error Reports'

    def __str__(self):
        return f"{self.error_type} - v{self.app_version} ({self.created_at.date()})"


class UpdateLog(models.Model):
    """Track version updates by users"""

    version = models.ForeignKey(AppVersion, on_delete=models.CASCADE)

    # Download tracking
    download_started = models.DateTimeField(null=True, blank=True)
    download_completed = models.DateTimeField(null=True, blank=True)
    download_failed = models.BooleanField(default=False)
    download_error = models.TextField(blank=True)

    # Installation tracking
    installation_started = models.DateTimeField(null=True, blank=True)
    installation_completed = models.DateTimeField(null=True, blank=True)
    installation_failed = models.BooleanField(default=False)
    installation_error = models.TextField(blank=True)

    # Platform
    platform = models.CharField(max_length=20)

    # Update type
    UPDATE_TYPE_CHOICES = [
        ('manual', 'Manual Update'),
        ('automatic', 'Automatic Update'),
        ('rollback', 'Rollback'),
        ('version_select', 'User Selected Version'),
    ]
    update_type = models.CharField(
        max_length=20,
        choices=UPDATE_TYPE_CHOICES,
        default='manual'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f" v{self.version.version}"


class MaintenanceWindow(models.Model):
    """Scheduled maintenance"""

    title = models.CharField(max_length=200)
    description = models.TextField()

    start_time = models.DateTimeField()
    end_time = models.DateTimeField()

    # Related version (optional)
    version = models.ForeignKey(
        AppVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Notifications
    notify_24h_before = models.BooleanField(default=True)
    notify_1h_before = models.BooleanField(default=True)
    notification_sent_24h = models.BooleanField(default=False)
    notification_sent_1h = models.BooleanField(default=False)

    # Status
    is_active = models.BooleanField(default=True)
    is_completed = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['start_time']

    def __str__(self):
        return f"{self.title} - {self.start_time.strftime('%Y-%m-%d %H:%M')}"


class AppVersions(models.Model):

    version = models.CharField(max_length=20, unique=True)
    release_date = models.DateField(auto_now_add=True)

    # Download URLs (platform-specific)
    windows_url = models.URLField(blank=True)
    mac_url = models.URLField(blank=True)
    linux_url = models.URLField(blank=True)

    file_size_mb = models.IntegerField(default=0)
    release_notes = models.TextField(blank=True)

    # Flags
    is_active = models.BooleanField(default=True)
    is_critical = models.BooleanField(
        default=False,
        help_text="If true, users must update immediately"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-version']

    def __str__(self):
        return f"v{self.version}"

    @property
    def version_tuple(self):
        return tuple(map(int, self.version.split('.')))

