from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone

from .models import PrimeBooksVersion, CrashReport


# ==========================================================
# PRIMEBOOKS VERSION ADMIN
# ==========================================================

@admin.register(PrimeBooksVersion)
class PrimeBooksVersionAdmin(admin.ModelAdmin):
    list_display = (
        "version",
        "is_active",
        "is_critical",
        "min_version",
        "platform_badges",
        "released_at",
        "created_at",
    )

    list_filter = (
        "is_active",
        "is_critical",
        "released_at",
    )

    search_fields = (
        "version",
        "changelog",
        "notes",
    )

    readonly_fields = (
        "created_at",
        "released_at",
        "windows_file_preview",
        "macos_file_preview",
        "linux_file_preview",
    )

    ordering = ("-created_at",)

    fieldsets = (
        ("Release Info", {
            "fields": (
                "version",
                "is_active",
                "is_critical",
                "min_version",
            )
        }),
        ("Windows Download", {
            "description": (
                "Upload your .exe installer. "
                "The file is stored on your server and served from MEDIA_URL. "
                "If you upload a file, the manual URL below is ignored."
            ),
            "fields": (
                "windows_file",
                "windows_file_preview",
                "windows_file_label",
                "windows_min_os",
                "download_url",       # legacy fallback
                "file_size_bytes",
                "windows_builds",     # extra/alt builds JSON
            )
        }),
        ("macOS Download", {
            "description": (
                "Upload your .dmg or .pkg installer. "
                "If you upload a file, the manual URL below is ignored."
            ),
            "fields": (
                "macos_file",
                "macos_file_preview",
                "macos_file_label",
                "macos_min_os",
                "macos_url",
                "macos_builds",
            )
        }),
        ("Linux Download", {
            "description": (
                "Upload your .AppImage, .deb, or .tar.gz package. "
                "If you upload a file, the manual URL below is ignored."
            ),
            "fields": (
                "linux_file",
                "linux_file_preview",
                "linux_file_label",
                "linux_min_os",
                "linux_url",
                "linux_builds",
            )
        }),
        ("Details", {
            "fields": (
                "changelog",
                "notes",
            )
        }),
        ("Timestamps", {
            "fields": (
                "released_at",
                "created_at",
            )
        }),
    )

    # ---------------------------
    # File preview helpers
    # ---------------------------

    def _file_preview(self, file_field, label):
        if not file_field:
            return "No file uploaded."
        try:
            size_mb = file_field.size / 1_048_576
            return format_html(
                '<a href="{}" target="_blank">📦 {}</a> &nbsp; <small>({:.1f} MB)</small>',
                file_field.url,
                file_field.name.split("/")[-1],
                size_mb,
            )
        except Exception:
            return "File saved (preview unavailable)."

    def windows_file_preview(self, obj):
        return self._file_preview(obj.windows_file, "Windows")
    windows_file_preview.short_description = "Current Windows File"

    def macos_file_preview(self, obj):
        return self._file_preview(obj.macos_file, "macOS")
    macos_file_preview.short_description = "Current macOS File"

    def linux_file_preview(self, obj):
        return self._file_preview(obj.linux_file, "Linux")
    linux_file_preview.short_description = "Current Linux File"

    # ---------------------------
    # Platform badges in list view
    # ---------------------------

    def platform_badges(self, obj):
        icons = {"windows": "🪟", "macos": "🍎", "linux": "🐧"}
        badges = []
        for p in obj.platforms_list():
            badges.append(format_html(
                '<span style="margin-right:4px;">{} {}</span>',
                icons.get(p, ""), p,
            ))
        return format_html("".join(badges)) if badges else "—"
    platform_badges.short_description = "Platforms"

    # ---------------------------
    # Save logic
    # ---------------------------

    def save_model(self, request, obj, form, change):
        """
        When activating a new version, automatically deactivate all others.
        """
        super().save_model(request, obj, form, change)

        if obj.is_active:
            PrimeBooksVersion.objects.exclude(pk=obj.pk).update(is_active=False)


# ==========================================================
# CRASH REPORT ADMIN
# ==========================================================

@admin.register(CrashReport)
class CrashReportAdmin(admin.ModelAdmin):
    list_display = (
        "short_schema",
        "app_version",
        "status",
        "occurrence_count",
        "last_seen_at",
        "created_at",
    )

    list_filter = (
        "status",
        "app_version",
        "schema_name",
        "created_at",
    )

    search_fields = (
        "schema_name",
        "app_version",
        "traceback",
        "fingerprint",
    )

    readonly_fields = (
        "schema_name",
        "app_version",
        "platform",
        "traceback",
        "context",
        "fingerprint",
        "occurrence_count",
        "last_seen_at",
        "client_ip",
        "created_at",
    )

    ordering = ("-created_at",)

    actions = [
        "mark_reviewed",
        "mark_resolved",
        "mark_ignored",
    ]

    fieldsets = (
        ("Crash Info", {
            "fields": (
                "schema_name",
                "app_version",
                "platform",
                "status",
                "fingerprint",
                "occurrence_count",
                "last_seen_at",
                "client_ip",
                "created_at",
            )
        }),
        ("Traceback", {
            "fields": ("traceback",)
        }),
        ("Context (JSON)", {
            "fields": ("context",)
        }),
        ("Triage", {
            "fields": ("triage_notes",)
        }),
    )

    # --------------------------
    # Admin Actions
    # --------------------------

    @admin.action(description="Mark selected as Reviewed")
    def mark_reviewed(self, request, queryset):
        queryset.update(status=CrashReport.STATUS_REVIEWED)

    @admin.action(description="Mark selected as Resolved")
    def mark_resolved(self, request, queryset):
        queryset.update(status=CrashReport.STATUS_RESOLVED)

    @admin.action(description="Mark selected as Ignored")
    def mark_ignored(self, request, queryset):
        queryset.update(status=CrashReport.STATUS_IGNORED)

    # --------------------------
    # Helpers
    # --------------------------

    def short_schema(self, obj):
        return obj.schema_name or "?"
    short_schema.short_description = "Tenant"