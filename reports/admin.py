from django.contrib import admin
from django_tenants.admin import TenantAdminMixin

from .models import (
    SavedReport,
    ReportSchedule,
    GeneratedReport,
    EFRISReportTemplate,
)


@admin.register(SavedReport)
class SavedReportAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'report_type',
        'created_by', 'created_at', 'last_modified',
        'is_shared', 'is_efris_approved'
    )
    list_filter = (
        'report_type', 'is_shared', 'is_efris_approved'
    )
    search_fields = (
        'name', 'created_by__username'
    )
    ordering = ('-last_modified',)
    readonly_fields = ('created_at', 'last_modified')

    fieldsets = (
        (None, {
            'fields': (
                'name', 'report_type',
                'created_by', 'is_shared', 'is_efris_approved'
            )
        }),
        ('Report Configuration', {
            'fields': ('columns', 'filters', 'parameters')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_modified')
        }),
    )


@admin.register(ReportSchedule)
class ReportScheduleAdmin(admin.ModelAdmin):
    list_display = (
        'report', 'frequency', 'day_of_week',
        'day_of_month', 'next_scheduled',
        'is_active', 'include_efris'
    )
    list_filter = (
        'frequency', 'is_active', 'include_efris'
    )
    search_fields = ('report__name',)
    ordering = ('next_scheduled',)
    readonly_fields = ('last_sent', 'next_scheduled')

    fieldsets = (
        (None, {
            'fields': ('report', 'frequency', 'is_active')
        }),
        ('Schedule Details', {
            'fields': (
                'day_of_week', 'day_of_month',
                'recipients', 'cc_recipients',
                'include_efris', 'efris_report_format'
            )
        }),
        ('Status', {
            'fields': ('last_sent', 'next_scheduled')
        }),
    )


@admin.register(GeneratedReport)
class GeneratedReportAdmin(admin.ModelAdmin):
    list_display = (
        'report', 'generated_by', 'file_format',
        'generated_at', 'is_efris_verified'
    )
    list_filter = ('file_format', 'is_efris_verified')
    search_fields = (
        'report__name', 'generated_by__username', 'file_path'
    )
    ordering = ('-generated_at',)
    readonly_fields = ('generated_at', 'file_path')


@admin.register(EFRISReportTemplate)
class EFRISReportTemplateAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'report_type', 'version',
        'valid_from', 'valid_to', 'is_default'
    )
    list_filter = ('report_type', 'is_default')
    search_fields = ('name',)
    ordering = ('-valid_from',)
