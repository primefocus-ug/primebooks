from django.contrib import admin
from .models import (
    SEOPage, Redirect, Sitemap, RobotsTxt,
    SEOAudit, KeywordTracking, KeywordRankingHistory
)


@admin.register(SEOPage)
class SEOPageAdmin(admin.ModelAdmin):
    list_display = ['page_type', 'title', 'focus_keyword', 'is_active', 'last_modified']
    list_filter = ['page_type', 'is_active']
    search_fields = ['title', 'meta_description', 'focus_keyword']
    readonly_fields = ['last_modified', 'created_at']

    fieldsets = [
        ('Page Information', {
            'fields': ['page_type', 'url_path', 'is_active']
        }),
        ('Basic SEO', {
            'fields': ['title', 'meta_description', 'meta_keywords', 'canonical_url', 'robots_meta']
        }),
        ('Open Graph', {
            'fields': ['og_title', 'og_description', 'og_image', 'og_type'],
            'classes': ['collapse']
        }),
        ('Twitter Card', {
            'fields': ['twitter_card', 'twitter_title', 'twitter_description', 'twitter_image'],
            'classes': ['collapse']
        }),
        ('Advanced', {
            'fields': ['structured_data', 'focus_keyword', 'secondary_keywords'],
            'classes': ['collapse']
        }),
        ('Timestamps', {
            'fields': ['last_modified', 'created_at'],
            'classes': ['collapse']
        }),
    ]


@admin.register(Redirect)
class RedirectAdmin(admin.ModelAdmin):
    list_display = ['old_path', 'new_path', 'redirect_type', 'hit_count', 'is_active']
    list_filter = ['redirect_type', 'is_active']
    search_fields = ['old_path', 'new_path']
    readonly_fields = ['hit_count', 'last_accessed', 'created_at']


@admin.register(Sitemap)
class SitemapAdmin(admin.ModelAdmin):
    list_display = ['url_path', 'priority', 'change_frequency', 'is_active']
    list_filter = ['priority', 'change_frequency', 'is_active']
    search_fields = ['url_path']


@admin.register(RobotsTxt)
class RobotsTxtAdmin(admin.ModelAdmin):
    list_display = ['is_active', 'last_modified']
    readonly_fields = ['last_modified']


@admin.register(SEOAudit)
class SEOAuditAdmin(admin.ModelAdmin):
    list_display = ['page', 'severity', 'issue_type', 'is_resolved', 'detected_at']
    list_filter = ['severity', 'is_resolved', 'issue_type']
    search_fields = ['description']
    readonly_fields = ['detected_at']


@admin.register(KeywordTracking)
class KeywordTrackingAdmin(admin.ModelAdmin):
    list_display = ['keyword', 'current_position', 'search_volume', 'competition', 'is_active']
    list_filter = ['competition', 'is_active']
    search_fields = ['keyword', 'target_url']
    readonly_fields = ['tracked_since', 'last_checked']


@admin.register(KeywordRankingHistory)
class KeywordRankingHistoryAdmin(admin.ModelAdmin):
    list_display = ['keyword_tracking', 'position', 'checked_at']
    list_filter = ['checked_at']
    readonly_fields = ['checked_at']