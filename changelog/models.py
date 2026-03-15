"""
changelog/models.py
"""

from django.db import models
from django.utils import timezone


class ChangelogRelease(models.Model):
    """
    A versioned release shown in the What's New modal.

    Release types:
      major  — new version (e.g. v2.0.0). Always shows to all users.
      minor  — notable features added (e.g. v2.1.0). Always shows.
      patch  — small fixes/tweaks. Shown only if is_minor_push=True
               and admin triggers a push.

    Minor push workflow:
      - Admin creates a release with release_type='patch' (or any type)
      - Adds slides describing the new feature
      - Clicks "Push to all users" in the admin action
      - This sets is_minor_push=True, records last_pushed_at, and
        deletes all ChangelogView records for this release so every
        user sees it again on next login.
    """

    RELEASE_TYPE_CHOICES = [
        ('major', 'Major — new version'),
        ('minor', 'Minor — notable features'),
        ('patch', 'Patch — small improvements / fixes'),
    ]

    version_tag    = models.CharField(
        max_length=20, unique=True,
        help_text=(
            'Version tag, e.g. v2.4.0. For minor feature pushes that '
            'do not increment the version, use a descriptive tag like '
            '"v2.4.0-nav-update" or "v2.4.1".'
        ),
    )
    title          = models.CharField(max_length=120)
    subtitle       = models.CharField(
        max_length=200, blank=True,
        default="Here's what we've been building for you",
    )
    release_type   = models.CharField(
        max_length=10,
        choices=RELEASE_TYPE_CHOICES,
        default='minor',
        help_text=(
            'Major/Minor: shows automatically to all users. '
            'Patch: only shows after you click "Push to all users" in admin.'
        ),
    )
    is_active      = models.BooleanField(
        default=True,
        help_text='Inactive releases are never shown.',
    )

    # ── Minor push tracking ──────────────────────────────────────────
    is_minor_push  = models.BooleanField(
        default=False,
        help_text=(
            'Set to True when you push a patch/minor update via admin. '
            'Causes the modal to re-show to users who already dismissed '
            'this release.'
        ),
    )
    push_count     = models.PositiveSmallIntegerField(
        default=0,
        help_text='Number of times this release has been pushed to users.',
    )
    last_pushed_at = models.DateTimeField(
        null=True, blank=True,
        help_text='When this release was last pushed to all users.',
    )
    pushed_by      = models.CharField(
        max_length=150, blank=True,
        help_text='Username of admin who last triggered the push.',
    )

    created_at     = models.DateTimeField(auto_now_add=True)
    published_at   = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-published_at']
        verbose_name = 'Changelog Release'
        verbose_name_plural = 'Changelog Releases'

    def __str__(self):
        type_label = dict(self.RELEASE_TYPE_CHOICES).get(self.release_type, '')
        pushed = ' 📢' if self.is_minor_push else ''
        return f'{self.version_tag} [{type_label}]{pushed} — {self.title}'

    @classmethod
    def get_latest_active(cls):
        """
        Returns the latest active release.
        Used by the context processor on every request.
        """
        return cls.objects.filter(is_active=True).first()

    def push_to_all_users(self, pushed_by_username=''):
        """
        Trigger a re-show to all users:
          1. Set is_minor_push = True
          2. Delete all existing ChangelogView records for this release
             so every user's "have I seen this?" check returns False
          3. Record push metadata

        Returns the number of ChangelogView records deleted.
        """
        deleted_count, _ = ChangelogView.objects.filter(release=self).delete()

        self.is_minor_push  = True
        self.push_count     += 1
        self.last_pushed_at = timezone.now()
        self.pushed_by      = pushed_by_username or ''
        self.save(update_fields=[
            'is_minor_push', 'push_count', 'last_pushed_at', 'pushed_by'
        ])

        return deleted_count

    def unpush(self):
        """
        Revert the push flag without affecting ChangelogView records.
        Useful if you pushed by mistake and want to stop the modal
        showing to users who haven't logged in yet.
        """
        self.is_minor_push = False
        self.save(update_fields=['is_minor_push'])


class ChangelogSlide(models.Model):
    """One slide in a changelog carousel."""

    TAG_CHOICES = [
        ('new',      'New Feature'),
        ('improved', 'Improved'),
        ('tip',      'Pro Tip'),
        ('fixed',    'Bug Fix'),
        ('removed',  'Removed'),
    ]

    MEDIA_TYPE_CHOICES = [
        ('none',       'No Media (text only)'),
        ('image',      'Image / Screenshot / GIF'),
        ('video',      'Self-hosted Video'),
        ('embed',      'Embed (YouTube / Loom iframe src)'),
        ('comparison', 'Before/After Comparison'),
    ]

    release            = models.ForeignKey(
        ChangelogRelease, on_delete=models.CASCADE, related_name='slides',
    )
    order              = models.PositiveSmallIntegerField(default=0)
    tag                = models.CharField(max_length=20, choices=TAG_CHOICES, default='new')
    title              = models.CharField(max_length=120)
    description        = models.TextField(
        help_text='Supports <strong>, <em>, <br> HTML tags.',
    )
    chips              = models.JSONField(
        default=list, blank=True,
        help_text='List of {"icon": "bi-...", "label": "..."} objects.',
    )
    media_type         = models.CharField(
        max_length=20, choices=MEDIA_TYPE_CHOICES, default='none',
    )
    media_url          = models.CharField(max_length=500, blank=True)
    media_alt          = models.CharField(max_length=200, blank=True)
    media_poster       = models.CharField(max_length=500, blank=True)
    before_image       = models.CharField(max_length=500, blank=True)
    after_image        = models.CharField(max_length=500, blank=True)
    highlight_selector = models.CharField(max_length=200, blank=True)
    highlight_label    = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['release', 'order']
        verbose_name = 'Changelog Slide'
        verbose_name_plural = 'Changelog Slides'

    def __str__(self):
        return f'[{self.release.version_tag}] Slide {self.order}: {self.title}'


class ChangelogView(models.Model):
    """
    Records which release a user has seen and how far they got.

    user_id is a plain integer (no FK) — cross-schema fix for django-tenants.
    accounts.CustomUser lives in tenant schemas; this model is in public schema.
    """

    user_id      = models.PositiveIntegerField(
        db_index=True,
        help_text='PK of the tenant user. No FK — cross-schema reference.',
    )
    release      = models.ForeignKey(
        ChangelogRelease, on_delete=models.CASCADE, related_name='views',
    )
    last_slide   = models.PositiveSmallIntegerField(default=0)
    dismissed_at = models.DateTimeField(null=True, blank=True)
    opted_out    = models.BooleanField(default=False)
    viewed_at    = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user_id', 'release')
        verbose_name = 'Changelog View'
        verbose_name_plural = 'Changelog Views'

    def __str__(self):
        return f'user:{self.user_id} — {self.release.version_tag} (slide {self.last_slide})'


# ─────────────────────────────────────────────────────────────
# Announcements
# ─────────────────────────────────────────────────────────────

class Announcement(models.Model):

    TYPE_CHOICES = [
        ('info',        'Info'),
        ('warning',     'Warning'),
        ('maintenance', 'Maintenance'),
        ('billing',     'Billing'),
        ('promo',       'Promotion'),
        ('critical',    'Critical'),
    ]

    title          = models.CharField(max_length=120)
    message        = models.TextField()
    type           = models.CharField(max_length=20, choices=TYPE_CHOICES, default='info')
    is_active      = models.BooleanField(default=True)
    is_dismissible = models.BooleanField(default=True)
    action_text    = models.CharField(max_length=60, blank=True)
    action_url     = models.CharField(max_length=500, blank=True)
    starts_at      = models.DateTimeField(default=timezone.now)
    ends_at        = models.DateTimeField(null=True, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-starts_at']
        verbose_name = 'Announcement'
        verbose_name_plural = 'Announcements'

    def __str__(self):
        return f'[{self.type.upper()}] {self.title}'

    def is_visible(self):
        now = timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        return True


class AnnouncementDismissal(models.Model):
    """
    user_id is a plain integer — cross-schema fix for django-tenants.
    """

    user_id      = models.PositiveIntegerField(
        db_index=True,
        help_text='PK of the tenant user. No FK — cross-schema reference.',
    )
    announcement = models.ForeignKey(
        Announcement, on_delete=models.CASCADE, related_name='dismissals',
    )
    dismissed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user_id', 'announcement')
        verbose_name = 'Announcement Dismissal'

    def __str__(self):
        return f'user:{self.user_id} dismissed [{self.announcement}]'