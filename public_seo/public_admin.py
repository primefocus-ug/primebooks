from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.contrib import messages
from django.utils import timezone
from django.contrib import admin
from public_accounts.admin_site import public_admin, PublicModelAdmin
from .models import (
    SEOPage, Redirect, Sitemap, RobotsTxt,
    SEOAudit, KeywordTracking, KeywordRankingHistory
)


class SEOPageAdmin(PublicModelAdmin):
    """Admin interface for SEOPage"""

    list_display = [
        'page_type_display', 'url_path', 'title_preview',
        'status_badge', 'last_modified', 'actions_column'
    ]

    list_filter = [
        'page_type', 'is_active', 'last_modified', 'created_at'
    ]

    search_fields = [
        'title', 'meta_description', 'focus_keyword', 'url_path'
    ]

    readonly_fields = [
        'last_modified', 'created_at'
    ]

    ordering = ['page_type']

    fieldsets = (
        (_('Page Identification'), {
            'fields': (
                'page_type', 'url_path', 'is_active'
            )
        }),
        (_('Basic SEO'), {
            'fields': (
                'title', 'meta_description', 'meta_keywords',
                'canonical_url', 'robots_meta'
            )
        }),
        (_('Open Graph'), {
            'fields': (
                'og_title', 'og_description', 'og_image', 'og_type'
            )
        }),
        (_('Twitter Card'), {
            'fields': (
                'twitter_card', 'twitter_title',
                'twitter_description', 'twitter_image'
            )
        }),
        (_('Structured Data & Analytics'), {
            'fields': (
                'structured_data', 'focus_keyword', 'secondary_keywords'
            ),
            'classes': ('collapse',)
        }),
        (_('Metadata'), {
            'fields': ('last_modified', 'created_at'),
            'classes': ('collapse',)
        }),
    )

    actions = ['activate_pages', 'deactivate_pages']

    def page_type_display(self, obj):
        return obj.get_page_type_display()

    page_type_display.short_description = _('Page Type')
    page_type_display.admin_order_field = 'page_type'

    def title_preview(self, obj):
        return obj.title[:60] + '...' if len(obj.title) > 60 else obj.title

    title_preview.short_description = _('Title')

    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="badge bg-success">{}</span>', _('Active'))
        return format_html('<span class="badge bg-secondary">{}</span>', _('Inactive'))

    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'is_active'

    def actions_column(self, obj):
        return format_html(
            '<button class="button" onclick="alert(\'SEO Tags: {}\')">{}</button>',
            obj.title,
            _('Preview Tags')
        )

    actions_column.short_description = _('Actions')

    def activate_pages(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            _('{} SEO page(s) activated.').format(updated),
            messages.SUCCESS
        )

    activate_pages.short_description = _("Activate selected pages")

    def deactivate_pages(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            _('{} SEO page(s) deactivated.').format(updated),
            messages.WARNING
        )

    deactivate_pages.short_description = _("Deactivate selected pages")


class RedirectAdmin(PublicModelAdmin):
    """Admin interface for Redirect"""

    list_display = [
        'old_path', 'new_path', 'redirect_type_badge',
        'hit_count', 'status_badge', 'last_accessed', 'created_at'
    ]

    list_filter = [
        'redirect_type', 'is_active', 'created_at'
    ]

    search_fields = [
        'old_path', 'new_path', 'notes'
    ]

    readonly_fields = [
        'hit_count', 'last_accessed', 'created_at'
    ]

    ordering = ['-created_at']

    fieldsets = (
        (_('Redirect Configuration'), {
            'fields': (
                'old_path', 'new_path', 'redirect_type', 'is_active'
            )
        }),
        (_('Tracking'), {
            'fields': (
                'hit_count', 'last_accessed'
            )
        }),
        (_('Additional Information'), {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
        (_('Metadata'), {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    actions = ['activate_redirects', 'deactivate_redirects']

    def redirect_type_badge(self, obj):
        color = 'success' if obj.redirect_type == 301 else 'warning'
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_redirect_type_display()
        )

    redirect_type_badge.short_description = _('Type')
    redirect_type_badge.admin_order_field = 'redirect_type'

    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="badge bg-success">{}</span>', _('Active'))
        return format_html('<span class="badge bg-secondary">{}</span>', _('Inactive'))

    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'is_active'

    def activate_redirects(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            _('{} redirect(s) activated.').format(updated),
            messages.SUCCESS
        )

    activate_redirects.short_description = _("Activate selected redirects")

    def deactivate_redirects(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            _('{} redirect(s) deactivated.').format(updated),
            messages.WARNING
        )

    deactivate_redirects.short_description = _("Deactivate selected redirects")


class SitemapAdmin(PublicModelAdmin):
    """Admin interface for Sitemap"""

    list_display = [
        'url_path', 'priority_badge', 'change_frequency',
        'status_badge', 'last_modified'
    ]

    list_filter = [
        'priority', 'change_frequency', 'is_active', 'last_modified'
    ]

    search_fields = ['url_path']

    readonly_fields = ['last_modified']

    ordering = ['-priority', 'url_path']

    fieldsets = (
        (_('Sitemap Configuration'), {
            'fields': (
                'url_path', 'priority', 'change_frequency', 'is_active'
            )
        }),
        (_('Metadata'), {
            'fields': ('last_modified',),
            'classes': ('collapse',)
        }),
    )

    actions = ['activate_entries', 'deactivate_entries']

    def priority_badge(self, obj):
        colors = {
            1.0: 'success',
            0.8: 'info',
            0.5: 'warning',
            0.3: 'secondary'
        }
        color = colors.get(obj.priority, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_priority_display()
        )

    priority_badge.short_description = _('Priority')
    priority_badge.admin_order_field = 'priority'

    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="badge bg-success">{}</span>', _('Active'))
        return format_html('<span class="badge bg-secondary">{}</span>', _('Inactive'))

    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'is_active'

    def activate_entries(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            _('{} sitemap entrie(s) activated.').format(updated),
            messages.SUCCESS
        )

    activate_entries.short_description = _("Activate selected entries")

    def deactivate_entries(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            _('{} sitemap entrie(s) deactivated.').format(updated),
            messages.WARNING
        )

    deactivate_entries.short_description = _("Deactivate selected entries")


class RobotsTxtAdmin(PublicModelAdmin):
    """Admin interface for RobotsTxt"""

    list_display = [
        'content_preview', 'status_badge', 'last_modified'
    ]

    readonly_fields = ['last_modified']

    fieldsets = (
        (_('Robots.txt Configuration'), {
            'fields': (
                'content', 'is_active'
            )
        }),
        (_('Metadata'), {
            'fields': ('last_modified',),
            'classes': ('collapse',)
        }),
    )

    def content_preview(self, obj):
        return obj.content[:100] + '...' if len(obj.content) > 100 else obj.content

    content_preview.short_description = _('Content')

    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="badge bg-success">{}</span>', _('Active'))
        return format_html('<span class="badge bg-secondary">{}</span>', _('Inactive'))

    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'is_active'

    def has_add_permission(self, request):
        # Only allow one active RobotsTxt configuration
        if RobotsTxt.objects.filter(is_active=True).exists():
            return False
        return super().has_add_permission(request)


class SEOAuditAdmin(PublicModelAdmin):
    """Admin interface for SEOAudit"""

    list_display = [
        'page', 'severity_badge', 'issue_type',
        'status_badge', 'detected_at'
    ]

    list_filter = [
        'severity', 'is_resolved', 'detected_at'
    ]

    search_fields = [
        'page__title', 'issue_type', 'description', 'recommendation'
    ]

    readonly_fields = [
        'detected_at', 'resolved_at'
    ]

    ordering = ['-detected_at']

    fieldsets = (
        (_('Audit Details'), {
            'fields': (
                'page', 'severity', 'issue_type'
            )
        }),
        (_('Issue Information'), {
            'fields': (
                'description', 'recommendation'
            )
        }),
        (_('Resolution'), {
            'fields': (
                'is_resolved', 'resolved_at'
            )
        }),
        (_('Metadata'), {
            'fields': ('detected_at',),
            'classes': ('collapse',)
        }),
    )

    actions = ['mark_as_resolved', 'mark_as_unresolved']

    def severity_badge(self, obj):
        colors = {
            'CRITICAL': 'danger',
            'WARNING': 'warning',
            'INFO': 'info'
        }
        color = colors.get(obj.severity, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_severity_display()
        )

    severity_badge.short_description = _('Severity')
    severity_badge.admin_order_field = 'severity'

    def status_badge(self, obj):
        if obj.is_resolved:
            return format_html('<span class="badge bg-success">{}</span>', _('Resolved'))
        return format_html('<span class="badge bg-warning">{}</span>', _('Unresolved'))

    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'is_resolved'

    def mark_as_resolved(self, request, queryset):
        updated = queryset.update(is_resolved=True, resolved_at=timezone.now())
        self.message_user(
            request,
            _('{} audit issue(s) marked as resolved.').format(updated),
            messages.SUCCESS
        )

    mark_as_resolved.short_description = _("Mark selected as resolved")

    def mark_as_unresolved(self, request, queryset):
        updated = queryset.update(is_resolved=False, resolved_at=None)
        self.message_user(
            request,
            _('{} audit issue(s) marked as unresolved.').format(updated),
            messages.WARNING
        )

    mark_as_unresolved.short_description = _("Mark selected as unresolved")


class KeywordRankingHistoryInline(admin.TabularInline):
    """Inline for KeywordRankingHistory"""
    model = KeywordRankingHistory
    extra = 0
    readonly_fields = ['checked_at']

    def has_add_permission(self, request, obj):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class KeywordTrackingAdmin(PublicModelAdmin):
    """Admin interface for KeywordTracking"""

    list_display = [
        'keyword', 'target_url_preview', 'current_position_badge',
        'competition_badge', 'status_badge', 'last_checked'
    ]

    list_filter = [
        'competition', 'is_active', 'last_checked'
    ]

    search_fields = [
        'keyword', 'target_url', 'notes'
    ]

    readonly_fields = [
        'tracked_since', 'last_checked'
    ]

    ordering = ['-tracked_since']

    fieldsets = (
        (_('Keyword Information'), {
            'fields': (
                'keyword', 'target_url', 'is_active'
            )
        }),
        (_('Ranking Data'), {
            'fields': (
                'current_position', 'search_volume', 'competition'
            )
        }),
        (_('Tracking Information'), {
            'fields': (
                'tracked_since', 'last_checked'
            )
        }),
        (_('Additional Information'), {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )

    inlines = [KeywordRankingHistoryInline]

    actions = ['activate_tracking', 'deactivate_tracking']

    def target_url_preview(self, obj):
        return obj.target_url[:50] + '...' if len(obj.target_url) > 50 else obj.target_url

    target_url_preview.short_description = _('Target URL')

    def current_position_badge(self, obj):
        if obj.current_position:
            color = 'success' if obj.current_position <= 10 else 'warning'
            return format_html(
                '<span class="badge bg-{}">#{}</span>',
                color,
                obj.current_position
            )
        return format_html('<span class="badge bg-secondary">{}</span>', _('N/A'))

    current_position_badge.short_description = _('Position')
    current_position_badge.admin_order_field = 'current_position'

    def competition_badge(self, obj):
        colors = {
            'LOW': 'success',
            'MEDIUM': 'warning',
            'HIGH': 'danger'
        }
        color = colors.get(obj.competition, 'secondary')
        display = obj.get_competition_display() if obj.competition else _('N/A')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            display
        )

    competition_badge.short_description = _('Competition')
    competition_badge.admin_order_field = 'competition'

    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="badge bg-success">{}</span>', _('Active'))
        return format_html('<span class="badge bg-secondary">{}</span>', _('Inactive'))

    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'is_active'

    def activate_tracking(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(
            request,
            _('{} keyword(s) activated for tracking.').format(updated),
            messages.SUCCESS
        )

    activate_tracking.short_description = _("Activate selected keywords")

    def deactivate_tracking(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(
            request,
            _('{} keyword(s) deactivated from tracking.').format(updated),
            messages.WARNING
        )

    deactivate_tracking.short_description = _("Deactivate selected keywords")


class KeywordRankingHistoryAdmin(PublicModelAdmin):
    """Admin interface for KeywordRankingHistory"""

    list_display = [
        'keyword', 'position_badge', 'checked_at'
    ]

    list_filter = ['checked_at']

    search_fields = [
        'keyword_tracking__keyword', 'keyword_tracking__target_url'
    ]

    readonly_fields = ['checked_at']

    ordering = ['-checked_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def keyword(self, obj):
        return obj.keyword_tracking.keyword

    keyword.short_description = _('Keyword')
    keyword.admin_order_field = 'keyword_tracking__keyword'

    def position_badge(self, obj):
        color = 'success' if obj.position <= 10 else 'warning'
        return format_html(
            '<span class="badge bg-{}">#{}</span>',
            color,
            obj.position
        )

    position_badge.short_description = _('Position')
    position_badge.admin_order_field = 'position'


# Register models with public admin
public_admin.register(SEOPage, SEOPageAdmin, app_label='public_seo')
public_admin.register(Redirect, RedirectAdmin, app_label='public_seo')
public_admin.register(Sitemap, SitemapAdmin, app_label='public_seo')
public_admin.register(RobotsTxt, RobotsTxtAdmin, app_label='public_seo')
public_admin.register(SEOAudit, SEOAuditAdmin, app_label='public_seo')
public_admin.register(KeywordTracking, KeywordTrackingAdmin, app_label='public_seo')
public_admin.register(KeywordRankingHistory, KeywordRankingHistoryAdmin, app_label='public_seo')