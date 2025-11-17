from django.contrib import admin
from public_accounts.admin_site import public_admin,PublicModelAdmin
from .models import PageView, Event, Conversion, VisitorSession, DailyStats


class PageViewAdmin(PublicModelAdmin):
    list_display = ['url_path', 'visitor_id', 'device_type', 'country', 'viewed_at']
    list_filter = ['device_type', 'viewed_at', 'country']
    search_fields = ['url_path', 'visitor_id', 'ip_address']
    date_hierarchy = 'viewed_at'
    readonly_fields = ['viewed_at']


class EventAdmin(PublicModelAdmin):
    list_display = ['category', 'action', 'label', 'visitor_id', 'occurred_at']
    list_filter = ['category', 'occurred_at']
    search_fields = ['action', 'label', 'visitor_id']
    date_hierarchy = 'occurred_at'
    readonly_fields = ['occurred_at']


class ConversionAdmin(PublicModelAdmin):
    list_display = ['conversion_type', 'visitor_id', 'utm_campaign', 'converted_at']
    list_filter = ['conversion_type', 'converted_at']
    search_fields = ['visitor_id', 'utm_campaign', 'utm_source']
    date_hierarchy = 'converted_at'
    readonly_fields = ['converted_at']


class VisitorSessionAdmin(PublicModelAdmin):
    list_display = ['session_id', 'visitor_id', 'pages_viewed', 'converted', 'started_at']
    list_filter = ['converted', 'started_at']
    search_fields = ['session_id', 'visitor_id']
    date_hierarchy = 'started_at'
    readonly_fields = ['started_at', 'last_activity_at']


class DailyStatsAdmin(PublicModelAdmin):
    list_display = ['date', 'unique_visitors', 'total_pageviews', 'conversion_rate']
    list_filter = ['date']
    date_hierarchy = 'date'
    readonly_fields = ['created_at']

public_admin.register(PageView,PageViewAdmin ,app_label='public_analytics')
public_admin.register(Event,EventAdmin,app_label='public_analytics')
public_admin.register(Conversion,ConversionAdmin,app_label='public_analytics')
public_admin.register(VisitorSession,VisitorSessionAdmin,app_label='public_analytics')
public_admin.register(DailyStats,DailyStatsAdmin,app_label='public_analytics')