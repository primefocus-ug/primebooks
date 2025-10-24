from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta

from .models import (
    EFRISConfiguration, EFRISAPILog, FiscalizationAudit,
    EFRISSystemDictionary, EFRISSyncQueue, EFRISCommodityCategorry
)

@admin.register(EFRISCommodityCategorry)
class EFRISCommodityCategoryAdmin(admin.ModelAdmin):
    list_display = (
        'commodity_category_code',
        'commodity_category_name',
        'is_exempt',
        'is_leaf_node',
        'is_zero_rate',
        'last_synced',
    )
    search_fields = ('commodity_category_code', 'commodity_category_name')
    list_filter = ('is_exempt', 'is_leaf_node', 'is_zero_rate')
    ordering = ('commodity_category_code',)
    readonly_fields = ('last_synced',)

@admin.register(EFRISConfiguration)
class EFRISConfigurationAdmin(admin.ModelAdmin):
    list_display = [
        'company', 'environment', 'mode', 'is_active', 'is_initialized',
        'test_connection_success', 'last_test_connection', 'certificate_status'
    ]
    list_filter = ['environment', 'mode', 'is_active', 'is_initialized', 'test_connection_success']
    search_fields = ['company__name', 'company__company_id']
    readonly_fields = ['created_at', 'updated_at', 'last_test_connection', 'last_login']

    fieldsets = (
        ('Company', {
            'fields': ('company',)
        }),
        ('Configuration', {
            'fields': ('environment', 'mode', 'api_base_url', 'app_id', 'version')
        }),
        ('Device Settings', {
            'fields': ('device_mac', 'device_number', 'timeout_seconds', 'max_retry_attempts')
        }),
        ('Security', {
            'fields': ('private_key', 'public_certificate', 'key_password', 'certificate_fingerprint')
        }),
        ('Sync Settings', {
            'fields': ('auto_sync_enabled', 'auto_fiscalize', 'sync_interval_minutes')
        }),
        ('Status', {
            'fields': ('is_initialized', 'is_active', 'last_test_connection', 'test_connection_success')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_login', 'last_dictionary_sync'),
            'classes': ('collapse',)
        })
    )

    def certificate_status(self, obj):
        if not obj.public_certificate:
            return format_html('<span style="color: red;">Not Set</span>')
        elif obj.certificate_expires_at and obj.certificate_expires_at < timezone.now():
            return format_html('<span style="color: red;">Expired</span>')
        elif obj.certificate_expires_at and obj.certificate_expires_at < timezone.now() + timedelta(days=30):
            return format_html('<span style="color: orange;">Expires Soon</span>')
        else:
            return format_html('<span style="color: green;">Valid</span>')

    certificate_status.short_description = 'Certificate Status'


@admin.register(EFRISAPILog)
class EFRISAPILogAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'company', 'interface_code', 'status', 'return_code',
        'duration_ms', 'request_time', 'invoice_link', 'product_link'
    ]
    list_filter = [
        'status', 'interface_code', 'company', 'request_time'
    ]
    search_fields = [
        'company__name', 'interface_code', 'return_code', 'return_message'
    ]
    readonly_fields = [
        'id', 'company', 'interface_code', 'request_data', 'response_data',
        'status', 'return_code', 'return_message', 'request_time', 'response_time',
        'duration_ms', 'invoice', 'product', 'user'
    ]
    date_hierarchy = 'request_time'
    ordering = ['-request_time']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def invoice_link(self, obj):
        if obj.invoice:
            url = reverse('admin:invoices_invoice_change', args=[obj.invoice.pk])
            return format_html('<a href="{}">{}</a>', url, obj.invoice.invoice_number)
        return '-'

    invoice_link.short_description = 'Invoice'

    def product_link(self, obj):
        if obj.product:
            url = reverse('admin:inventory_product_change', args=[obj.product.pk])
            return format_html('<a href="{}">{}</a>', url, obj.product.name)
        return '-'

    product_link.short_description = 'Product'


@admin.register(FiscalizationAudit)
class FiscalizationAuditAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'invoice_number', 'company', 'action', 'status', 'severity',
        'user', 'duration_display', 'created_at'
    ]
    list_filter = [
        'status', 'action', 'severity', 'company', 'created_at'
    ]
    search_fields = [
        'invoice__invoice_number', 'fiscal_document_number', 'verification_code',
        'company__name', 'user__email'
    ]
    readonly_fields = [
        'id', 'company', 'invoice', 'action', 'status', 'severity',
        'fiscal_document_number', 'verification_code', 'efris_return_code',
        'efris_return_message', 'error_message', 'started_at', 'completed_at',
        'duration_seconds', 'user', 'amount', 'tax_amount', 'created_at', 'updated_at'
    ]
    date_hierarchy = 'created_at'
    ordering = ['-created_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def invoice_number(self, obj):
        return obj.invoice.invoice_number if obj.invoice else obj.invoice_number or '-'

    invoice_number.short_description = 'Invoice Number'


@admin.register(EFRISSystemDictionary)
class EFRISSystemDictionaryAdmin(admin.ModelAdmin):
    list_display = ['company', 'dictionary_type', 'version', 'updated_at']
    list_filter = ['dictionary_type', 'company', 'updated_at']
    search_fields = ['company__name', 'dictionary_type']
    readonly_fields = ['created_at', 'updated_at']

    def has_add_permission(self, request):
        return False


@admin.register(EFRISSyncQueue)
class EFRISSyncQueueAdmin(admin.ModelAdmin):
    list_display = [
        'id', 'company', 'sync_type', 'status', 'priority',
        'retry_count', 'scheduled_at', 'started_at', 'completed_at'
    ]
    list_filter = [
        'sync_type', 'status', 'priority', 'company', 'scheduled_at'
    ]
    search_fields = ['company__name', 'sync_type', 'object_type']
    readonly_fields = [
        'id', 'created_at', 'updated_at', 'started_at', 'completed_at'
    ]
    date_hierarchy = 'scheduled_at'
    ordering = ['priority', 'scheduled_at']

    actions = ['retry_failed_items', 'cancel_pending_items']

    def retry_failed_items(self, request, queryset):
        updated = 0
        for item in queryset.filter(status='failed'):
            if item.can_retry():
                item.status = 'pending'
                item.retry_count += 1
                item.next_retry_at = timezone.now() + timedelta(minutes=30)
                item.save()
                updated += 1

        self.message_user(request, f"Queued {updated} items for retry.")

    retry_failed_items.short_description = "Retry selected failed items"

    def cancel_pending_items(self, request, queryset):
        updated = queryset.filter(status='pending').update(status='cancelled')
        self.message_user(request, f"Cancelled {updated} pending items.")

    cancel_pending_items.short_description = "Cancel selected pending items"

