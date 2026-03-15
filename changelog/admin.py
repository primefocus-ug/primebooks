"""
changelog/admin.py

Key additions over the previous version:
  - "Push to all users" action  — triggers re-show of a release to all users
  - "Unpush" action             — reverts the push without affecting view records
  - push_status column          — shows Live / Pushed / Patch / Inactive badge
  - Preview button              — links to /changelog/preview/<pk>/ to see the
                                  modal exactly as users will see it
  - push_info readonly panel    — shows push count, last pushed, pushed by
"""

from django.contrib        import admin, messages
from django.utils.html     import format_html
from django.utils          import timezone
from django.urls           import path, reverse
from django.http           import HttpResponseRedirect
from .models import (
    ChangelogRelease, ChangelogSlide, ChangelogView,
    Announcement, AnnouncementDismissal,
)


# ─────────────────────────────────────────────────────────────
# Inline: Slides inside a Release
# ─────────────────────────────────────────────────────────────

class ChangelogSlideInline(admin.StackedInline):
    model    = ChangelogSlide
    extra    = 1
    ordering = ('order',)
    fields   = (
        ('order', 'tag', 'media_type'),
        'title',
        'description',
        'chips',
        ('media_url', 'media_alt', 'media_poster'),
        ('before_image', 'after_image'),
        ('highlight_selector', 'highlight_label'),
    )


# ─────────────────────────────────────────────────────────────
# ChangelogRelease
# ─────────────────────────────────────────────────────────────

@admin.register(ChangelogRelease)
class ChangelogReleaseAdmin(admin.ModelAdmin):

    list_display = (
        'version_tag',
        'title',
        'release_type',
        'push_status',
        'slide_count',
        'view_count',
        'push_info_short',
        'published_at',
        'push_button',
    )
    list_filter   = ('release_type', 'is_active', 'is_minor_push')
    list_editable = ('release_type',)
    search_fields = ('version_tag', 'title')
    ordering      = ('-published_at',)
    inlines       = [ChangelogSlideInline]

    readonly_fields = (
        'created_at', 'published_at',
        'push_count', 'last_pushed_at', 'pushed_by',
        'push_info_panel', 'preview_link',
    )

    fieldsets = (
        ('Release', {
            'fields': (
                ('version_tag', 'release_type'),
                'title',
                'subtitle',
                ('is_active', 'is_minor_push'),
                'preview_link',
            ),
        }),
        ('Push History', {
            'fields': ('push_info_panel',),
            'classes': ('collapse',),
            'description': (
                'Use the "Push to all users" action (checkbox → Action dropdown above) '
                'or the 📢 button in the list view to trigger a re-show.'
            ),
        }),
        ('Timestamps', {
            'fields': ('published_at', 'created_at'),
            'classes': ('collapse',),
        }),
    )

    # ── Custom columns ───────────────────────────────────────────────

    @admin.display(description='Status')
    def push_status(self, obj):
        if not obj.is_active:
            return format_html(
                '<span style="background:#6b7280;color:#fff;padding:2px 8px;'
                'border-radius:12px;font-size:0.73rem;font-weight:600">Inactive</span>'
            )
        if obj.is_minor_push:
            return format_html(
                '<span style="background:#8b5cf6;color:#fff;padding:2px 8px;'
                'border-radius:12px;font-size:0.73rem;font-weight:600">📢 Pushed</span>'
            )
        if obj.release_type == 'patch':
            return format_html(
                '<span style="background:#f59e0b;color:#fff;padding:2px 8px;'
                'border-radius:12px;font-size:0.73rem;font-weight:600">Patch</span>'
            )
        return format_html(
            '<span style="background:#22c55e;color:#fff;padding:2px 8px;'
            'border-radius:12px;font-size:0.73rem;font-weight:600">Live</span>'
        )

    @admin.display(description='Slides')
    def slide_count(self, obj):
        return obj.slides.count()

    @admin.display(description='Views')
    def view_count(self, obj):
        c = obj.views.count()
        return format_html('<span style="font-weight:600">{}</span>', c)

    @admin.display(description='Push history')
    def push_info_short(self, obj):
        if not obj.push_count:
            return '—'
        when = obj.last_pushed_at.strftime('%d %b %H:%M') if obj.last_pushed_at else '?'
        return format_html(
            '{}× · {} · <em style="color:#6b7280">{}</em>',
            obj.push_count, when, obj.pushed_by or 'unknown',
        )

    @admin.display(description='Push history (full)')
    def push_info_panel(self, obj):
        if not obj.push_count:
            return format_html(
                '<p style="color:#9ca3af;font-style:italic">Not yet pushed to users.</p>'
            )
        when = obj.last_pushed_at.strftime('%d %b %Y at %H:%M') if obj.last_pushed_at else 'unknown'
        return format_html(
            '<table style="border-collapse:collapse;font-size:0.85rem">'
            '<tr><td style="padding:4px 16px 4px 0;color:#6b7280">Total pushes</td>'
            '<td><strong>{}</strong></td></tr>'
            '<tr><td style="padding:4px 16px 4px 0;color:#6b7280">Last pushed</td>'
            '<td><strong>{}</strong></td></tr>'
            '<tr><td style="padding:4px 16px 4px 0;color:#6b7280">Pushed by</td>'
            '<td><strong>{}</strong></td></tr>'
            '<tr><td style="padding:4px 16px 4px 0;color:#6b7280">Current views</td>'
            '<td><strong>{}</strong></td></tr>'
            '</table>',
            obj.push_count,
            when,
            obj.pushed_by or '—',
            obj.views.count(),
        )

    @admin.display(description='Preview')
    def preview_link(self, obj):
        if not obj.pk:
            return '—'
        url = reverse('changelog_admin_preview', args=[obj.pk])
        return format_html(
            '<a href="{}" target="_blank" style="'
            'background:#3b82f6;color:#fff;padding:4px 12px;border-radius:6px;'
            'text-decoration:none;font-size:0.8rem;font-weight:600">'
            '👁 Preview modal</a>',
            url,
        )

    @admin.display(description='')
    def push_button(self, obj):
        """Inline push button in the list view."""
        if not obj.is_active:
            return '—'
        if obj.is_minor_push:
            url = reverse('admin:changelog_changelogrelease_changelist')
            return format_html(
                '<a href="{}?action=unpush_releases&_selected_action={}" '
                'style="color:#8b5cf6;font-size:0.8rem;font-weight:600;'
                'text-decoration:none" title="Unpush this release">'
                '↩ Unpush</a>',
                url, obj.pk,
            )
        url = reverse('changelog_admin_push', args=[obj.pk])
        return format_html(
            '<a href="{}" style="background:#8b5cf6;color:#fff;padding:3px 10px;'
            'border-radius:6px;text-decoration:none;font-size:0.78rem;font-weight:600"'
            ' title="Push this release to all users">'
            '📢 Push</a>',
            url,
        )

    # ── Admin actions ────────────────────────────────────────────────

    actions = ['push_releases', 'unpush_releases', 'reset_views']

    @admin.action(description='📢 Push selected releases to all users (re-show modal)')
    def push_releases(self, request, queryset):
        total_deleted = 0
        pushed = 0
        for release in queryset.filter(is_active=True):
            deleted = release.push_to_all_users(pushed_by_username=request.user.username)
            total_deleted += deleted
            pushed += 1
        self.message_user(
            request,
            f'✅ Pushed {pushed} release(s) to all users. '
            f'Cleared {total_deleted} existing view record(s). '
            f'Users will see the modal on next login.',
            messages.SUCCESS,
        )

    @admin.action(description='↩ Unpush selected releases (stop re-showing)')
    def unpush_releases(self, request, queryset):
        count = 0
        for release in queryset:
            release.unpush()
            count += 1
        self.message_user(
            request,
            f'Unpushed {count} release(s). '
            f'Users who have not logged in yet will no longer see the modal.',
            messages.WARNING,
        )

    @admin.action(description='🗑 Reset all view records (show to ALL users again)')
    def reset_views(self, request, queryset):
        total = 0
        for release in queryset:
            deleted, _ = ChangelogView.objects.filter(release=release).delete()
            total += deleted
        self.message_user(
            request,
            f'Reset {total} view record(s). Every user will see the selected '
            f'release(s) on next login.',
            messages.SUCCESS,
        )

    # ── Custom URL for per-row push button ────────────────────────────

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<int:release_id>/push/',
                self.admin_site.admin_view(self.push_single_view),
                name='changelog_admin_push_single',  # internal — not used by name externally
            ),
        ]
        return custom + urls

    def push_single_view(self, request, release_id):
        """Handles the per-row 📢 Push button click."""
        try:
            release = ChangelogRelease.objects.get(pk=release_id)
            deleted = release.push_to_all_users(pushed_by_username=request.user.username)
            self.message_user(
                request,
                f'✅ "{release.version_tag}" pushed to all users. '
                f'Cleared {deleted} view record(s).',
                messages.SUCCESS,
            )
        except ChangelogRelease.DoesNotExist:
            self.message_user(request, 'Release not found.', messages.ERROR)

        return HttpResponseRedirect(
            reverse('admin:changelog_changelogrelease_changelist')
        )


# ─────────────────────────────────────────────────────────────
# ChangelogSlide (standalone)
# ─────────────────────────────────────────────────────────────

@admin.register(ChangelogSlide)
class ChangelogSlideAdmin(admin.ModelAdmin):
    list_display  = ('release', 'order', 'tag', 'title', 'media_type', 'has_highlight')
    list_filter   = ('release', 'tag', 'media_type')
    search_fields = ('title', 'description')
    ordering      = ('release', 'order')

    @admin.display(description='Highlight?', boolean=True)
    def has_highlight(self, obj):
        return bool(obj.highlight_selector)


# ─────────────────────────────────────────────────────────────
# ChangelogView
# ─────────────────────────────────────────────────────────────

@admin.register(ChangelogView)
class ChangelogViewAdmin(admin.ModelAdmin):
    list_display    = ('user_id', 'release', 'last_slide', 'opted_out', 'dismissed_at', 'viewed_at')
    list_filter     = ('release', 'opted_out')
    search_fields   = ('user_id', 'release__version_tag')
    readonly_fields = ('viewed_at',)
    ordering        = ('-viewed_at',)


# ─────────────────────────────────────────────────────────────
# Announcement
# ─────────────────────────────────────────────────────────────

@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display  = ('title', 'type', 'is_active', 'is_dismissible', 'status_badge', 'starts_at', 'ends_at')
    list_editable = ('is_active',)
    list_filter   = ('type', 'is_active', 'is_dismissible')
    search_fields = ('title', 'message')
    ordering      = ('-starts_at',)
    fieldsets     = (
        (None, {
            'fields': ('title', 'message', 'type', 'is_active', 'is_dismissible'),
        }),
        ('Call to Action', {
            'fields': ('action_text', 'action_url'),
            'classes': ('collapse',),
        }),
        ('Scheduling', {
            'fields': ('starts_at', 'ends_at'),
        }),
    )

    @admin.display(description='Status')
    def status_badge(self, obj):
        now = timezone.now()
        if not obj.is_active:
            return format_html('<span style="color:#9ca3af">Inactive</span>')
        if obj.starts_at and now < obj.starts_at:
            return format_html('<span style="color:#f59e0b;font-weight:600">Scheduled</span>')
        if obj.ends_at and now > obj.ends_at:
            return format_html('<span style="color:#ef4444;font-weight:600">Expired</span>')
        return format_html('<span style="color:#22c55e;font-weight:600">● Live</span>')


# ─────────────────────────────────────────────────────────────
# AnnouncementDismissal
# ─────────────────────────────────────────────────────────────

@admin.register(AnnouncementDismissal)
class AnnouncementDismissalAdmin(admin.ModelAdmin):
    list_display    = ('user_id', 'announcement', 'dismissed_at')
    list_filter     = ('announcement',)
    search_fields   = ('user_id',)
    readonly_fields = ('dismissed_at',)
    ordering        = ('-dismissed_at',)