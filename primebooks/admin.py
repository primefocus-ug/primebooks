# primebooks/admin.py
"""
Admin interface for version management
"""
from django.contrib import admin
from .models import AppVersion, UpdateLog, MaintenanceWindow


@admin.register(AppVersion)
class AppVersionAdmin(admin.ModelAdmin):
    """
    Admin interface for managing app versions
    """
    list_display = [
        'version',
        'release_date',
        'file_size_mb',
        'is_critical',
        'is_latest',
        'is_active',
    ]

    list_filter = [
        'is_critical',
        'is_latest',
        'is_active',
        'release_date',
    ]

    search_fields = ['version', 'release_notes']

    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Version Info', {
            'fields': ('version', 'release_date', 'release_notes')
        }),
        ('Files', {
            'fields': ('windows_file', 'linux_file', 'mac_file', 'file_size_mb')
        }),
        ('Update Type', {
            'fields': ('is_critical', 'maintenance_start', 'maintenance_duration_minutes')
        }),
        ('Status', {
            'fields': ('is_active', 'is_latest')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['mark_as_latest', 'mark_as_critical']

    def mark_as_latest(self, request, queryset):
        """Mark selected version as latest"""
        if queryset.count() > 1:
            self.message_user(request, "Please select only one version", level='error')
            return

        # Unset all others
        AppVersion.objects.update(is_latest=False)

        # Set selected
        queryset.update(is_latest=True)

        self.message_user(request, "Version marked as latest")

    mark_as_latest.short_description = "Mark as latest version"

    def mark_as_critical(self, request, queryset):
        """Mark as critical update"""
        queryset.update(is_critical=True)
        self.message_user(request, f"{queryset.count()} version(s) marked as critical")

    mark_as_critical.short_description = "Mark as critical update"


@admin.register(UpdateLog)
class UpdateLogAdmin(admin.ModelAdmin):
    """
    Track update downloads and installations
    """
    list_display = [
        'version',
        'platform',
        'download_completed',
        'installation_completed',
        'created_at',
    ]

    list_filter = [
        'platform',
        'download_failed',
        'installation_failed',
        'created_at',
    ]

    search_fields = [ 'version__version']

    readonly_fields = [
        'version',
        'download_started',
        'download_completed',
        'installation_started',
        'installation_completed',
        'created_at',
    ]

    def has_add_permission(self, request):
        return False


@admin.register(MaintenanceWindow)
class MaintenanceWindowAdmin(admin.ModelAdmin):
    """
    Manage maintenance windows
    """
    list_display = [
        'title',
        'start_time',
        'end_time',
        'is_active',
        'is_completed',
    ]

    list_filter = [
        'is_active',
        'is_completed',
        'start_time',
    ]

    search_fields = ['title', 'description']

    fieldsets = (
        ('Basic Info', {
            'fields': ('title', 'description')
        }),
        ('Schedule', {
            'fields': ('start_time', 'end_time')
        }),
        ('Notifications', {
            'fields': ('notify_1_day_before', 'notify_1_hour_before')
        }),
        ('Status', {
            'fields': ('is_active', 'is_completed')
        }),
    )

    actions = ['mark_as_completed']

    def mark_as_completed(self, request, queryset):
        """Mark maintenance as completed"""
        queryset.update(is_completed=True)
        self.message_user(request, f"{queryset.count()} maintenance(s) marked as completed")

    mark_as_completed.short_description = "Mark as completed"