"""
primebooks/admin_updates.py
============================
Django admin for PrimeBooksVersion and CrashReport.

These models live in the PUBLIC schema (saad app / SHARED_APPS).
To register them add this to your admin.py:

    from .admin_updates import *
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone

from .models import PrimeBooksVersion, CrashReport


# ─────────────────────────────────────────────────────────────────────────────
# PrimeBooksVersion
# ─────────────────────────────────────────────────────────────────────────────

@admin.register(PrimeBooksVersion)
class AppVersionAdmin(admin.ModelAdmin):
    list_display = [
        "version", "status_badge", "critical_badge",
        "min_version_display", "platforms_display",
        "released_at", "created_at",
    ]
    list_filter   = ["is_active", "is_critical"]
    search_fields = ["version", "changelog", "notes"]
    readonly_fields = ["created_at"]
    ordering      = ["-created_at"]

    fieldsets = [
        # ── Core release info ────────────────────────────────────────────────
        ("Release", {
            "fields": [
                "version", "is_active", "is_critical",
                "min_version", "released_at",
            ],
        }),

        # ── Windows ─────────────────────────────────────────────────────────
        ("Windows", {
            "fields": [
                "windows_file",
                "windows_file_label",
                "windows_min_os",
                "download_url",        # legacy fallback for updater.py
                "file_size_bytes",     # legacy fallback; auto-detected on upload
                "windows_builds",      # extra alt builds (e.g. portable .zip)
            ],
            "description": (
                "Upload a <code>.exe</code> installer to <b>Windows file</b> — the URL is "
                "auto-derived and returned by <code>/api/v1/updates/check/</code>. "
                "<b>Download URL</b> is a legacy fallback used only when no file is uploaded. "
                "Add portable or other variant links in <b>Windows builds</b> (JSON list)."
            ),
        }),

        # ── macOS ────────────────────────────────────────────────────────────
        ("macOS", {
            "fields": [
                "macos_file",
                "macos_file_label",
                "macos_min_os",
                "macos_url",           # manual fallback
                "macos_builds",        # extra alt builds
            ],
            "description": (
                "Upload a <code>.dmg</code> or <code>.pkg</code> to <b>macOS file</b>. "
                "<b>macOS URL</b> is a fallback used only when no file is uploaded."
            ),
            "classes": ["collapse"],
        }),

        # ── Linux ────────────────────────────────────────────────────────────
        ("Linux", {
            "fields": [
                "linux_file",
                "linux_file_label",
                "linux_min_os",
                "linux_url",           # manual fallback
                "linux_builds",        # extra alt builds
            ],
            "description": (
                "Upload an <code>.AppImage</code>, <code>.deb</code>, or <code>.tar.gz</code> "
                "to <b>Linux file</b>. "
                "<b>Linux URL</b> is a fallback used only when no file is uploaded."
            ),
            "classes": ["collapse"],
        }),

        # ── User-facing content ──────────────────────────────────────────────
        ("User-facing content", {
            "fields": ["changelog"],
            "description": (
                "Shown inside the desktop update dialog <em>and</em> on the public "
                "Download Center page. Use bullet points: <code>• Fix one\\n• Fix two</code>"
            ),
        }),

        # ── Internal notes ───────────────────────────────────────────────────
        ("Internal notes", {
            "fields": ["notes"],
            "classes": ["collapse"],
        }),

        # ── Metadata ─────────────────────────────────────────────────────────
        ("Metadata", {
            "fields": ["created_at"],
            "classes": ["collapse"],
        }),
    ]

    # ── List display helpers ──────────────────────────────────────────────────

    def status_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="color:#16a34a;font-weight:700">● Active</span>'
            )
        return format_html('<span style="color:#94a3b8">○ Inactive</span>')
    status_badge.short_description = "Status"

    def critical_badge(self, obj):
        if obj.is_critical:
            return format_html(
                '<span style="color:#dc2626;font-weight:700">🔴 Critical</span>'
            )
        return format_html('<span style="color:#64748b">Optional</span>')
    critical_badge.short_description = "Type"

    def min_version_display(self, obj):
        return obj.min_version or "—"
    min_version_display.short_description = "Min Version"

    def platforms_display(self, obj):
        """Show coloured icons for each platform that has a build."""
        icons = []
        if obj.windows_file or obj.download_url or obj.windows_builds:
            icons.append('<span style="color:#0078d4" title="Windows">⊞ Win</span>')
        if obj.macos_file or obj.macos_url or obj.macos_builds:
            icons.append('<span style="color:#555" title="macOS"> Mac</span>')
        if obj.linux_file or obj.linux_url or obj.linux_builds:
            icons.append('<span style="color:#e95420" title="Linux">🐧 Linux</span>')
        return format_html(" &nbsp; ".join(icons)) if icons else format_html(
            '<span style="color:#94a3b8">—</span>'
        )
    platforms_display.short_description = "Platforms"

    # ── Save hook ────────────────────────────────────────────────────────────

    def save_model(self, request, obj, form, change):
        """
        When publishing a new active version, deactivate all previous ones so
        only one active version exists at any time.
        """
        if obj.is_active:
            PrimeBooksVersion.objects.exclude(pk=obj.pk).filter(
                is_active=True
            ).update(is_active=False)
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

    # All crash data is read-only — only triage fields are editable
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

    # ── List display helpers ──────────────────────────────────────────────────

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

    # ── Bulk actions ──────────────────────────────────────────────────────────

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