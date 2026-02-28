"""
saad/models.py
============================
Models for update management and crash reporting.

WHY primebooks (SHARED_APPS) and NOT sync (TENANT_APPS)
--------------------------------------------------------
  sync is a TENANT app — its tables live inside each tenant's PostgreSQL
  schema (ug, ke, etc.). AppVersion and CrashReport must live in the PUBLIC
  schema because:

    AppVersion   — one release applies to ALL tenants. No per-tenant copy.
    CrashReport  — you want all crashes from all clients in one table so
                   you can triage them in one admin view.

  saad is already in SHARED_APPS so its migrations run against the
  public schema automatically.

Migrations
----------
    python manage.py makemigrations primebooks
    python manage.py migrate_schemas --shared
"""

from django.db import models
from django.utils import timezone


class PrimeBooksVersion(models.Model):
    """
    One row per published desktop release.

    The check endpoint (GET /api/version/latest/) on primebooks.sale
    returns the latest is_active=True row whose version > the client's
    current version string.

    Saving a new active version auto-deactivates all previous ones
    (handled in AppVersionAdmin.save_model).
    """

    version         = models.CharField(
        max_length=32, unique=True,
        help_text="Semver string e.g. '1.2.0'",
    )
    is_active       = models.BooleanField(
        default=True, db_index=True,
        help_text="Only one active version is served. Activating a new one deactivates all others.",
    )
    is_critical     = models.BooleanField(
        default=False,
        help_text="Critical = mandatory update dialog, no Later button.",
    )
    min_version     = models.CharField(
        max_length=32, blank=True, default="",
        help_text="Clients older than this are force-updated even if is_critical=False.",
    )
    changelog       = models.TextField(
        blank=True, default="",
        help_text="Shown in update dialog. Use bullet points: '• Fix\\n• Fix'",
    )
    download_url    = models.URLField(
        max_length=500,
        help_text="Direct HTTPS URL to the .exe installer.",
    )
    file_size_bytes = models.BigIntegerField(
        null=True, blank=True,
        help_text="Optional — shown as download size in the dialog.",
    )
    released_at     = models.DateTimeField(null=True, blank=True)
    created_at      = models.DateTimeField(default=timezone.now)
    notes           = models.TextField(
        blank=True, default="",
        help_text="Internal notes — NOT shown to users.",
    )

    class Meta:
        app_label           = "primebooks"
        ordering            = ["-created_at"]
        verbose_name        = "App Version"
        verbose_name_plural = "App Versions"

    def __str__(self):
        flags = []
        if self.is_critical:
            flags.append("CRITICAL")
        if not self.is_active:
            flags.append("inactive")
        tag = f"  [{', '.join(flags)}]" if flags else ""
        return f"PrimeBooks v{self.version}{tag}"

    def save(self, *args, **kwargs):
        if not self.released_at:
            self.released_at = self.created_at or timezone.now()
        super().save(*args, **kwargs)


class CrashReport(models.Model):
    """
    A crash report submitted by a desktop client.

    The view (in sync/update_views.py) temporarily switches the DB
    connection to the public schema before writing here, so reports
    from ALL tenant subdomains (ug.primebooks.sale, ke.primebooks.sale…)
    land in this single public-schema table.
    """

    STATUS_NEW      = "new"
    STATUS_REVIEWED = "reviewed"
    STATUS_RESOLVED = "resolved"
    STATUS_IGNORED  = "ignored"
    STATUS_CHOICES  = [
        (STATUS_NEW,      "New"),
        (STATUS_REVIEWED, "Reviewed"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_IGNORED,  "Ignored"),
    ]

    schema_name      = models.CharField(max_length=64, blank=True, default="", db_index=True)
    app_version      = models.CharField(max_length=32, blank=True, default="")
    platform         = models.CharField(max_length=200, blank=True, default="")
    traceback        = models.TextField()
    context          = models.JSONField(default=dict, blank=True)
    status           = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW, db_index=True)
    triage_notes     = models.TextField(blank=True, default="")
    fingerprint      = models.CharField(max_length=64, blank=True, default="", db_index=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    last_seen_at     = models.DateTimeField(default=timezone.now)
    client_ip        = models.GenericIPAddressField(null=True, blank=True)
    created_at       = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        app_label           = "primebooks"
        ordering            = ["-created_at"]
        verbose_name        = "Crash Report"
        verbose_name_plural = "Crash Reports"

    def __str__(self):
        return (
            f"[{self.status.upper()}] "
            f"{self.schema_name or '?'} v{self.app_version} "
            f"×{self.occurrence_count} — "
            f"{self.created_at.strftime('%Y-%m-%d %H:%M')}"
        )