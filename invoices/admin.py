
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe

from .models import Invoice, InvoiceTemplate, InvoicePayment, FiscalizationAudit

@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = [
        'invoice_number', 'get_customer_name', 'issue_date', 'due_date',
        'total_amount', 'status_badge', 'is_fiscalized_badge', 'created_by'
    ]
    list_filter = [
        'status', 'document_type', 'is_fiscalized', 'issue_date', 'store'
    ]
    search_fields = [
        'invoice_number', 'sale__customer__name', 'fiscal_number'
    ]
    readonly_fields = [
        'fiscal_number', 'verification_code', 'fiscalization_time',
        'fiscalized_by', 'created_at', 'updated_at'
    ]
    date_hierarchy = 'issue_date'
    ordering = ['-issue_date']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('invoice_number', 'sale', 'store', 'document_type')
        }),
        ('Dates', {
            'fields': ('issue_date', 'due_date')
        }),
        ('Financial Details', {
            'fields': ('subtotal', 'tax_amount', 'discount_amount', 'total_amount')
        }),
        ('Status', {
            'fields': ('status',)
        }),
        ('Fiscalization', {
            'fields': ('is_fiscalized', 'fiscal_number', 'verification_code', 
                      'fiscalization_time', 'fiscalized_by'),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('notes', 'terms'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )
    
    def get_customer_name(self, obj):
        if obj.sale and obj.sale.customer:
            return obj.sale.customer.name
        return "No customer"
    get_customer_name.short_description = 'Customer'
    
    def status_badge(self, obj):
        colors = {
            'DRAFT': 'secondary',
            'SENT': 'primary',
            'PAID': 'success',
            'PARTIALLY_PAID': 'warning',
            'CANCELLED': 'dark',
            'REFUNDED': 'info'
        }
        color = colors.get(obj.status, 'secondary')
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            color,
            obj.get_status_display()
        )
    status_badge.short_description = 'Status'
    
    def is_fiscalized_badge(self, obj):
        if obj.is_fiscalized:
            return format_html(
                '<span class="badge bg-success"><i class="fas fa-check"></i> Fiscalized</span>'
            )
        return format_html(
            '<span class="badge bg-secondary"><i class="fas fa-times"></i> Not Fiscalized</span>'
        )
    is_fiscalized_badge.short_description = 'Fiscalization Status'
    
    actions = ['mark_as_sent', 'mark_as_paid', 'export_selected_invoices']
    
    def mark_as_sent(self, request, queryset):
        updated = queryset.filter(status='DRAFT').update(status='SENT')
        self.message_user(request, f'{updated} invoices marked as sent.')
    mark_as_sent.short_description = 'Mark selected invoices as sent'
    
    def mark_as_paid(self, request, queryset):
        updated = queryset.filter(status__in=['SENT', 'PARTIALLY_PAID']).update(status='PAID')
        self.message_user(request, f'{updated} invoices marked as paid.')
    mark_as_paid.short_description = 'Mark selected invoices as paid'


@admin.register(InvoicePayment)
class InvoicePaymentAdmin(admin.ModelAdmin):
    list_display = [
        'invoice', 'amount', 'payment_method', 'payment_date', 'processed_by'
    ]
    list_filter = ['payment_method', 'payment_date']
    search_fields = ['invoice__invoice_number', 'transaction_reference']
    date_hierarchy = 'payment_date'
    ordering = ['-payment_date']


@admin.register(InvoiceTemplate)
class InvoiceTemplateAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'version', 'is_default', 'is_efris_compliant', 'created_by', 'created_at'
    ]
    list_filter = ['is_default', 'is_efris_compliant']
    search_fields = ['name']


@admin.register(FiscalizationAudit)
class FiscalizationAuditAdmin(admin.ModelAdmin):
    list_display = [
        'invoice', 'action', 'success', 'user', 'timestamp'
    ]
    list_filter = ['action', 'success', 'timestamp']
    search_fields = ['invoice__invoice_number']
    readonly_fields = ['efris_response']
    date_hierarchy = 'timestamp'
    ordering = ['-timestamp']

