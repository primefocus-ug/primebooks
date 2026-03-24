"""
saad/models.py
============================
Models for update management and crash reporting.

WHY primebooks (SHARED_APPS) and NOT sync (TENANT_APPS)
--------------------------------------------------------
  sync is a TENANT app — its tables live inside each tenant's PostgreSQL
  schema (ug, ke, etc.). AppVersion and CrashReport must live in the PUBLIC
  schema because:

    PrimeBooksVersion  — one release applies to ALL tenants. No per-tenant copy.
    CrashReport        — you want all crashes from all clients in one table so
                         you can triage them in one admin view.

  saad is already in SHARED_APPS so its migrations run against the
  public schema automatically.

Migrations
----------
    python manage.py makemigrations saad
    python manage.py migrate_schemas --shared

Per-platform support
--------------------
  The model stores the primary Windows installer in download_url / file_size_bytes
  for backward compatibility with the existing desktop updater.py contract
  (GET /api/v1/updates/check/ still returns a flat response).

  For the public Download Center page, the full per-platform data is stored
  in the three JSONField columns:
    windows_builds  — list of {"label", "url", "sha256", "file_size", "min_os"}
    macos_builds    — same structure
    linux_builds    — same structure

  The first entry in each list is the primary/recommended build for that
  platform (shown as the main download button). Additional entries appear
  as "alt builds" (e.g. portable zip alongside the installer).
"""

from django.db import models
from django.utils import timezone


class PrimeBooksVersion(models.Model):
    """
    One row per published desktop release.

    The check endpoint (GET /api/v1/updates/check/) returns the latest
    is_active=True row whose version > the client's current version.

    Saving a new active version auto-deactivates all previous ones
    (handled in the admin's save_model).

    Per-platform builds
    -------------------
    windows_builds / macos_builds / linux_builds store a JSON list:
    [
      {
        "label":     "Windows Installer (.exe)",   # shown as button label
        "url":       "https://…/PrimeBooks-1.2.0-setup.exe",
        "sha256":    "abc123…",                    # full 64-char hex
        "file_size": "48.3 MB",                    # human-readable string
        "min_os":    "Windows 10 64-bit"
      },
      {
        "label":     "Portable (.zip)",
        "url":       "https://…/PrimeBooks-1.2.0-portable.zip",
        "sha256":    "def456…",
        "file_size": "51.0 MB",
        "min_os":    "Windows 10 64-bit"
      }
    ]

    The first item is the primary build; subsequent items are alt-builds.
    Leave the list empty [] if a platform is not supported for this release.
    """

    version         = models.CharField(
        max_length=32, unique=True,
        help_text="Semver string e.g. '1.2.0'",
    )
    is_active       = models.BooleanField(
        default=True, db_index=True,
        help_text=(
            "Only one active version is served to the desktop updater. "
            "Activating a new one deactivates all others."
        ),
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
        help_text=(
            "Shown in the update dialog AND the public Download Center. "
            "Use bullet points: '• Fix one\\n• Fix two'"
        ),
    )

    # ── Primary Windows build (used by existing desktop updater contract) ──
    download_url    = models.URLField(
        max_length=500,
        help_text=(
            "Direct HTTPS URL to the primary Windows .exe installer. "
            "Returned by /api/v1/updates/check/ — must stay a flat URL "
            "for backward compatibility with updater.py."
        ),
    )
    file_size_bytes = models.BigIntegerField(
        null=True, blank=True,
        help_text="Primary Windows installer size in bytes (optional, shown in update dialog).",
    )

    # ── Per-platform build lists (used by Download Center) ─────────────────
    windows_builds  = models.JSONField(
        default=list, blank=True,
        help_text=(
            "List of Windows build objects. "
            "First entry = primary download button. "
            "See module docstring for field structure."
        ),
    )
    macos_builds    = models.JSONField(
        default=list, blank=True,
        help_text="List of macOS build objects (same structure as windows_builds).",
    )
    linux_builds    = models.JSONField(
        default=list, blank=True,
        help_text="List of Linux build objects (same structure as windows_builds).",
    )

    released_at     = models.DateTimeField(
        null=True, blank=True,
        help_text="Public release date/time. Auto-set to created_at if left blank.",
    )
    created_at      = models.DateTimeField(default=timezone.now)
    notes           = models.TextField(
        blank=True, default="",
        help_text="Internal notes — NOT shown to users.",
    )

    class Meta:
        app_label           = "saad"
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

    # ── Helpers used by the releases API view ─────────────────────────────

    def platforms_list(self) -> list[str]:
        """Return list of platform keys that have at least one build."""
        platforms = []
        if self.windows_builds or self.download_url:
            platforms.append("windows")
        if self.macos_builds:
            platforms.append("macos")
        if self.linux_builds:
            platforms.append("linux")
        return platforms

    def primary_build_for(self, platform: str) -> dict | None:
        """Return the first (primary) build dict for a platform, or None."""
        builds = self._builds_for(platform)
        return builds[0] if builds else None

    def alt_builds_for(self, platform: str) -> list[dict]:
        """Return all but the first build (alt downloads) for a platform."""
        builds = self._builds_for(platform)
        return builds[1:] if len(builds) > 1 else []

    def _builds_for(self, platform: str) -> list:
        if platform == "windows":
            # Merge: explicit windows_builds takes priority; fall back to
            # the legacy download_url so old rows still work in the UI.
            if self.windows_builds:
                return self.windows_builds
            if self.download_url:
                size_str = (
                    f"{self.file_size_bytes / 1_048_576:.1f} MB"
                    if self.file_size_bytes else ""
                )
                return [{
                    "label":     "Windows Installer (.exe)",
                    "url":       self.download_url,
                    "sha256":    "",
                    "file_size": size_str,
                    "min_os":    "Windows 10 64-bit",
                }]
            return []
        if platform == "macos":
            return self.macos_builds or []
        if platform == "linux":
            return self.linux_builds or []
        return []

    def to_releases_api_dict(self) -> dict:
        """
        Serialise this version for the public /api/v1/releases/ endpoint
        consumed by the Download Center page.
        """
        platforms = self.platforms_list()

        platforms_info = {}
        for p in platforms:
            primary = self.primary_build_for(p)
            if primary:
                platforms_info[p] = {
                    "download_url": primary.get("url", ""),
                    "file_size":    primary.get("file_size", ""),
                    "min_os":       primary.get("min_os", ""),
                    "sha256":       primary.get("sha256", ""),
                    "alt_builds":   [
                        {"label": b.get("label", ""), "url": b.get("url", "")}
                        for b in self.alt_builds_for(p)
                    ],
                }

        return {
            "version":       self.version,
            "release_date":  self.released_at.isoformat() if self.released_at else None,
            "is_critical":   self.is_critical,
            "changelog":     self.changelog,
            "platforms":     platforms,
            "platforms_info": platforms_info,
        }


class CrashReport(models.Model):
    """
    A crash report submitted by a desktop client.

    The view temporarily switches the DB connection to the public schema
    before writing here, so reports from ALL tenant subdomains
    (ug.primebooks.sale, ke.primebooks.sale…) land in this single
    public-schema table.
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
    status           = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_NEW, db_index=True,
    )
    triage_notes     = models.TextField(blank=True, default="")
    fingerprint      = models.CharField(max_length=64, blank=True, default="", db_index=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    last_seen_at     = models.DateTimeField(default=timezone.now)
    client_ip        = models.GenericIPAddressField(null=True, blank=True)
    created_at       = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        app_label           = "saad"
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