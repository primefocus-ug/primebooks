from public_accounts.admin_site import public_admin, PublicModelAdmin
from django.contrib import admin
from django.utils import timezone
from django.utils.html import format_html
from django.db.models import F

from .models import PrimeBooksVersion, CrashReport


# ==========================================================
# PRIMEBOOKS VERSION ADMIN
# ==========================================================

class PrimeBooksVersionAdmin(PublicModelAdmin):

    list_display = (
        "version",
        "is_active",
        "is_critical",
        "min_version",
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
        ("Download", {
            "fields": (
                "download_url",
                "file_size_bytes",
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

    def save_model(self, request, obj, form, change):
        """
        Ensure only one version is active at a time.
        """
        super().save_model(request, obj, form, change)

        if obj.is_active:
            PrimeBooksVersion.objects.exclude(pk=obj.pk).update(is_active=False)


# ==========================================================
# CRASH REPORT ADMIN
# ==========================================================

class CrashReportAdmin(PublicModelAdmin):

    list_display = (
        "schema_name",
        "app_version",
        "colored_status",
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

    # ---------------------------
    # Colored Status
    # ---------------------------

    def colored_status(self, obj):
        colors = {
            CrashReport.STATUS_NEW: "red",
            CrashReport.STATUS_REVIEWED: "orange",
            CrashReport.STATUS_RESOLVED: "green",
            CrashReport.STATUS_IGNORED: "gray",
        }
        color = colors.get(obj.status, "black")
        return format_html(
            '<span style="color:{}; font-weight:bold;">{}</span>',
            color,
            obj.get_status_display(),
        )

    colored_status.short_description = "Status"

    # ---------------------------
    # Bulk Actions
    # ---------------------------

    def mark_reviewed(self, request, queryset):
        queryset.update(status=CrashReport.STATUS_REVIEWED)

    def mark_resolved(self, request, queryset):
        queryset.update(status=CrashReport.STATUS_RESOLVED)

    def mark_ignored(self, request, queryset):
        queryset.update(status=CrashReport.STATUS_IGNORED)


# ==========================================================
# REGISTER TO PUBLIC ADMIN
# ==========================================================

public_admin.register(
    PrimeBooksVersion,
    PrimeBooksVersionAdmin,
    app_label="primebooks"
)

public_admin.register(
    CrashReport,
    CrashReportAdmin,
    app_label="primebooks"
)