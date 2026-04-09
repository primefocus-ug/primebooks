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

File uploads vs URLs
--------------------
  Each platform now supports EITHER a direct file upload OR a manual URL.
  The helper _builds_for() prefers the uploaded file over the manual URL
  so you can simply upload a file and the URL is auto-derived via
  the FileField's .url property.

  Upload storage layout (MEDIA_ROOT/primebooks/releases/):
    windows/  ← .exe, .zip, etc.
    macos/    ← .dmg, .pkg, etc.
    linux/    ← .AppImage, .deb, .tar.gz, etc.

  For the public Download Center page, additional builds (e.g. portable zip
  alongside the installer) are still stored in the three JSONField columns:
    windows_builds  — list of {"label", "url", "sha256", "file_size", "min_os"}
    macos_builds    — same structure
    linux_builds    — same structure

  The first entry in each list is the primary/recommended build for that
  platform. If a *_file field is set it overrides the first entry's URL.
"""

from django.db import models
from django.utils import timezone
from django.conf import settings


def upload_to_windows(instance, filename):
    return f"primebooks/releases/windows/{filename}"


def upload_to_macos(instance, filename):
    return f"primebooks/releases/macos/{filename}"


def upload_to_linux(instance, filename):
    return f"primebooks/releases/linux/{filename}"


class PrimeBooksVersion(models.Model):
    """
    One row per published desktop release.

    The check endpoint (GET /api/v1/updates/check/) returns the latest
    is_active=True row whose version > the client's current version.

    Saving a new active version auto-deactivates all previous ones
    (handled in the admin's save_model).

    Per-platform builds
    -------------------
    For each platform you can EITHER:
      (a) Upload a file using the *_file field  ← recommended, easiest
      (b) Paste a URL into the *_url field
      (c) Provide a full JSON list in *_builds for multiple download options

    Priority: uploaded file > manual URL > builds JSON list first-entry URL.

    windows_builds / macos_builds / linux_builds store a JSON list:
    [
      {
        "label":     "Windows Installer (.exe)",   # shown as button label
        "url":       "https://…/PrimeBooks-1.2.0-setup.exe",
        "sha256":    "abc123…",                    # full 64-char hex
        "file_size": "48.3 MB",                    # human-readable string
        "min_os":    "Windows 10 64-bit"
      },
      ...
    ]

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

    # ── Windows ───────────────────────────────────────────────────────────────

    windows_file    = models.FileField(
        upload_to=upload_to_windows,
        null=True, blank=True,
        help_text=(
            "Upload the primary Windows installer (.exe). "
            "When set, this overrides the manual URL below. "
            "File is stored on your server under MEDIA_ROOT/primebooks/releases/windows/."
        ),
    )
    windows_file_label = models.CharField(
        max_length=100, blank=True, default="Windows Installer (.exe)",
        help_text="Button label for the uploaded Windows file.",
    )
    windows_min_os  = models.CharField(
        max_length=100, blank=True, default="Windows 10 64-bit",
        help_text="Minimum OS requirement shown on the Download Center.",
    )

    # Legacy / fallback manual URL (kept for backward compatibility with updater.py)
    download_url    = models.URLField(
        max_length=500, blank=True, default="",
        help_text=(
            "Manual Windows .exe URL (fallback if no file is uploaded). "
            "Returned by /api/v1/updates/check/ — must stay a flat URL "
            "for backward compatibility with updater.py."
        ),
    )
    file_size_bytes = models.BigIntegerField(
        null=True, blank=True,
        help_text="Primary Windows installer size in bytes (auto-detected on upload if left blank).",
    )

    # ── macOS ─────────────────────────────────────────────────────────────────

    macos_file      = models.FileField(
        upload_to=upload_to_macos,
        null=True, blank=True,
        help_text=(
            "Upload the primary macOS installer (.dmg or .pkg). "
            "Stored under MEDIA_ROOT/primebooks/releases/macos/."
        ),
    )
    macos_file_label = models.CharField(
        max_length=100, blank=True, default="macOS Installer (.dmg)",
        help_text="Button label for the uploaded macOS file.",
    )
    macos_min_os    = models.CharField(
        max_length=100, blank=True, default="macOS 11 Big Sur",
        help_text="Minimum macOS version shown on the Download Center.",
    )
    macos_url       = models.URLField(
        max_length=500, blank=True, default="",
        help_text="Manual macOS URL (fallback if no file is uploaded).",
    )

    # ── Linux ─────────────────────────────────────────────────────────────────

    linux_file      = models.FileField(
        upload_to=upload_to_linux,
        null=True, blank=True,
        help_text=(
            "Upload the primary Linux package (.AppImage, .deb, .tar.gz…). "
            "Stored under MEDIA_ROOT/primebooks/releases/linux/."
        ),
    )
    linux_file_label = models.CharField(
        max_length=100, blank=True, default="Linux AppImage (.AppImage)",
        help_text="Button label for the uploaded Linux file.",
    )
    linux_min_os    = models.CharField(
        max_length=100, blank=True, default="Ubuntu 20.04 / equivalent",
        help_text="Minimum Linux distro/version shown on the Download Center.",
    )
    linux_url       = models.URLField(
        max_length=500, blank=True, default="",
        help_text="Manual Linux URL (fallback if no file is uploaded).",
    )

    # ── Extra builds (alt downloads shown below the primary button) ───────────

    windows_builds  = models.JSONField(
        default=list, blank=True,
        help_text=(
            "Extra Windows builds (e.g. portable .zip). "
            "List of {label, url, sha256, file_size, min_os}. "
            "The primary build is taken from windows_file / download_url — "
            "do NOT duplicate it here."
        ),
    )
    macos_builds    = models.JSONField(
        default=list, blank=True,
        help_text="Extra macOS builds (same structure as windows_builds).",
    )
    linux_builds    = models.JSONField(
        default=list, blank=True,
        help_text="Extra Linux builds (same structure as windows_builds).",
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

        # Auto-detect file size for the Windows installer if not set manually
        if self.windows_file and not self.file_size_bytes:
            try:
                self.file_size_bytes = self.windows_file.size
            except Exception:
                pass

        super().save(*args, **kwargs)

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _file_url(self, file_field) -> str:
        """
        Return an absolute URL for an uploaded FileField.
        Respects MEDIA_URL and optionally prepends SITE_URL if defined in settings.
        """
        if not file_field:
            return ""
        try:
            relative = file_field.url          # e.g. /media/primebooks/releases/windows/setup.exe
            site_url = getattr(settings, "SITE_URL", "").rstrip("/")
            return f"{site_url}{relative}" if site_url else relative
        except Exception:
            return ""

    def _file_size_str(self, file_field, fallback_bytes=None) -> str:
        """Human-readable file size string."""
        size = None
        if file_field:
            try:
                size = file_field.size
            except Exception:
                pass
        if size is None:
            size = fallback_bytes
        if size:
            return f"{size / 1_048_576:.1f} MB"
        return ""

    def _primary_build_entry(self, file_field, label_field, url_field, min_os_field, fallback_bytes=None) -> dict | None:
        """
        Build a single primary-build dict preferring an uploaded file over a manual URL.
        Returns None if neither is available.
        """
        url = self._file_url(file_field) if file_field else ""
        label = label_field or ""

        if not url:
            url = url_field or ""

        if not url:
            return None

        return {
            "label":     label,
            "url":       url,
            "sha256":    "",           # hash verification left for future work
            "file_size": self._file_size_str(file_field if file_field else None, fallback_bytes),
            "min_os":    min_os_field or "",
        }

    # ── Public API helpers ────────────────────────────────────────────────────

    def platforms_list(self) -> list[str]:
        """Return list of platform keys that have at least one build."""
        platforms = []
        if self.windows_file or self.download_url or self.windows_builds:
            platforms.append("windows")
        if self.macos_file or self.macos_url or self.macos_builds:
            platforms.append("macos")
        if self.linux_file or self.linux_url or self.linux_builds:
            platforms.append("linux")
        return platforms

    def primary_build_for(self, platform: str) -> dict | None:
        """Return the primary build dict for a platform, or None."""
        if platform == "windows":
            return self._primary_build_entry(
                self.windows_file,
                self.windows_file_label,
                self.download_url,
                self.windows_min_os,
                fallback_bytes=self.file_size_bytes,
            )
        if platform == "macos":
            return self._primary_build_entry(
                self.macos_file,
                self.macos_file_label,
                self.macos_url,
                self.macos_min_os,
            )
        if platform == "linux":
            return self._primary_build_entry(
                self.linux_file,
                self.linux_file_label,
                self.linux_url,
                self.linux_min_os,
            )
        return None

    def alt_builds_for(self, platform: str) -> list[dict]:
        """Return the extra/alt builds JSON list for a platform."""
        if platform == "windows":
            return self.windows_builds or []
        if platform == "macos":
            return self.macos_builds or []
        if platform == "linux":
            return self.linux_builds or []
        return []

    def effective_windows_url(self) -> str:
        """
        The flat Windows URL returned by /api/v1/updates/check/.
        Prefers the uploaded file URL; falls back to the manual download_url.
        """
        if self.windows_file:
            return self._file_url(self.windows_file)
        return self.download_url or ""

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
                    "label":        primary.get("label", ""),
                    "alt_builds":   [
                        {"label": b.get("label", ""), "url": b.get("url", "")}
                        for b in self.alt_builds_for(p)
                    ],
                }

        return {
            "version":        self.version,
            "release_date":   self.released_at.isoformat() if self.released_at else None,
            "is_critical":    self.is_critical,
            "changelog":      self.changelog,
            "platforms":      platforms,
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