"""
primebooks/admin_updates.py
============================
Django admin for AppVersion and CrashReport.

These models live in the PUBLIC schema (primebooks app / SHARED_APPS).
To register them add this to primebooks/admin.py:

    from .admin_updates import *     # or import AppVersionAdmin, CrashReportAdmin
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone

from .models import PrimeBooksVersion, CrashReport


# ─────────────────────────────────────────────────────────────────────────────
# AppVersion
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(PrimeBooksVersion)
class AppVersionAdmin(admin.ModelAdmin):
    list_display  = [
        "version", "status_badge", "critical_badge",
        "min_version_display", "size_display",
        "released_at", "created_at",
    ]
    list_filter   = ["is_active", "is_critical"]
    search_fields = ["version", "changelog", "notes"]
    readonly_fields = ["created_at"]
    ordering      = ["-created_at"]

    fieldsets = [
        ("Release", {
            "fields": ["version", "is_active", "is_critical", "min_version", "released_at"],
        }),
        ("Distribution", {
            "fields": ["download_url", "file_size_bytes"],
            "description": (
                "Upload your .exe to your file server or S3 first, "
                "then paste the direct download URL here."
            ),
        }),
        ("User-facing content", {
            "fields": ["changelog"],
            "description": "This text is shown inside the update dialog on the desktop app.",
        }),
        ("Internal notes", {
            "fields": ["notes"],
            "classes": ["collapse"],
        }),
        ("Metadata", {
            "fields": ["created_at"],
            "classes": ["collapse"],
        }),
    ]

    def status_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="color:#16a34a;font-weight:700">● Active</span>'
            )
        return format_html(
            '<span style="color:#94a3b8">○ Inactive</span>'
        )
    status_badge.short_description = "Status"

    def critical_badge(self, obj):
        if obj.is_critical:
            return format_html(
                '<span style="color:#dc2626;font-weight:700">🔴 Critical</span>'
            )
        return format_html(
            '<span style="color:#64748b">Optional</span>'
        )
    critical_badge.short_description = "Type"

    def min_version_display(self, obj):
        return obj.min_version or "—"
    min_version_display.short_description = "Min Version"

    def size_display(self, obj):
        if not obj.file_size_bytes:
            return "—"
        return f"{obj.file_size_bytes / 1_048_576:.1f} MB"
    size_display.short_description = "Size"

    def save_model(self, request, obj, form, change):
        """
        When publishing a new active version, deactivate all previous ones.
        This ensures only one active version exists at any time.
        """
        if obj.is_active:
           PrimeBooksVersion.objects.exclude(pk=obj.pk).filter(is_active=True).update(
                is_active=False
            )
        super().save_model(request, obj, form, change)


# ─────────────────────────────────────────────────────────────────────────────
# CrashReport
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(CrashReport)
class CrashReportAdmin(admin.ModelAdmin):
    list_display  = [
        "status_badge", "schema_name", "app_version",
        "occurrences", "error_summary",
        "client_ip", "last_seen_at", "created_at",
    ]
    list_filter   = ["status", "app_version", "schema_name"]
    search_fields = ["traceback", "schema_name", "app_version", "triage_notes"]
    ordering      = ["-created_at"]
    actions       = ["mark_reviewed", "mark_resolved", "mark_ignored"]

    # All crash data is read-only — triage fields are editable
    readonly_fields = [
        "schema_name", "app_version", "platform",
        "traceback", "context", "fingerprint",
        "client_ip", "occurrence_count", "last_seen_at", "created_at",
    ]

    fieldsets = [
        ("Client", {
            "fields": [
                "schema_name", "app_version", "platform",
                "client_ip", "occurrence_count", "last_seen_at", "created_at",
            ],
        }),
        ("Crash details", {
            "fields": ["traceback", "context", "fingerprint"],
        }),
        ("Triage", {
            "fields": ["status", "triage_notes"],
        }),
    ]

    # ── List display helpers ──────────────────────────────────────────────

    def status_badge(self, obj):
        config = {
            CrashReport.STATUS_NEW:      ("#dc2626", "🔴", "New"),
            CrashReport.STATUS_REVIEWED: ("#d97706", "🟡", "Reviewed"),
            CrashReport.STATUS_RESOLVED: ("#16a34a", "🟢", "Resolved"),
            CrashReport.STATUS_IGNORED:  ("#94a3b8", "⚪", "Ignored"),
        }
        color, icon, label = config.get(obj.status, ("#94a3b8", "⚪", obj.status))
        return format_html(
            '<span style="color:{};font-weight:600">{} {}</span>',
            color, icon, label,
        )
    status_badge.short_description = "Status"

    def occurrences(self, obj):
        if obj.occurrence_count > 1:
            return format_html(
                '<span style="color:#d97706;font-weight:700">×{}</span>',
                obj.occurrence_count,
            )
        return "1"
    occurrences.short_description = "×"

    def error_summary(self, obj):
        """Show the last meaningful line of the traceback as a summary."""
        lines = obj.traceback.strip().splitlines()
        for line in reversed(lines):
            line = line.strip()
            if line and not line.startswith("File ") and not line.startswith("^"):
                return line[:100]
        return lines[0][:100] if lines else "—"
    error_summary.short_description = "Error"

    # ── Bulk actions ──────────────────────────────────────────────────────

    @admin.action(description="Mark selected → Reviewed")
    def mark_reviewed(self, request, queryset):
        n = queryset.update(status=CrashReport.STATUS_REVIEWED)
        self.message_user(request, f"{n} report(s) marked as Reviewed.")

    @admin.action(description="Mark selected → Resolved")
    def mark_resolved(self, request, queryset):
        n = queryset.update(status=CrashReport.STATUS_RESOLVED)
        self.message_user(request, f"{n} report(s) marked as Resolved.")

    @admin.action(description="Mark selected → Ignored")
    def mark_ignored(self, request, queryset):
        n = queryset.update(status=CrashReport.STATUS_IGNORED)
        self.message_user(request, f"{n} report(s) marked as Ignored.")