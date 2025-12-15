from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from django.db.models import Sum, Count
from django.contrib import messages
from django_tenants.admin import TenantAdminMixin

from .models import Invoice, InvoicePayment, InvoiceTemplate
from efris.models import FiscalizationAudit


@admin.register(Invoice)
class InvoiceAdmin(TenantAdminMixin, admin.ModelAdmin):
    """Enhanced admin for invoices with EFRIS support"""

    list_display = [
        'invoice_number', 'customer_display', 'total_amount_display',
        'status_badge', 'fiscalization_badge', 'issue_date',
        'due_date', 'days_overdue_display', 'created_by'
    ]

    list_filter = [
        'fiscalization_status', 'is_fiscalized', 'efris_document_type',
        'business_type', 'requires_ura_approval', 'ura_approved',
        'auto_fiscalize', 'created_at'
    ]

    search_fields = [
        'sale__document_number', 'fiscal_document_number',
        'fiscal_number', 'sale__customer__name',
        'sale__customer__phone', 'verification_code'
    ]

    readonly_fields = [
        'sale', 'fiscal_document_number', 'fiscal_number',
        'verification_code', 'qr_code', 'fiscalization_status',
        'is_fiscalized', 'fiscalization_time', 'fiscalized_by',
        'fiscalization_error', 'efris_status', 'created_at',
        'updated_at', 'invoice_summary', 'efris_info_display'
    ]

    fieldsets = (
        ('Invoice Information', {
            'fields': (
                'sale', 'store', 'invoice_summary'
            )
        }),
        ('Invoice Details', {
            'fields': (
                'terms', 'purchase_order', 'efris_document_type',
                'business_type', 'operator_name'
            )
        }),
        ('EFRIS Fiscalization', {
            'fields': (
                'fiscalization_status', 'is_fiscalized',
                'fiscal_document_number', 'fiscal_number',
                'verification_code', 'qr_code', 'device_number',
                'fiscalization_time', 'fiscalized_by',
                'fiscalization_error', 'efris_status',
                'efris_info_display'
            ),
            'classes': ('collapse',)
        }),
        ('Credit/Debit Notes', {
            'fields': (
                'original_fdn', 'requires_ura_approval',
                'ura_approved', 'ura_approval_date'
            ),
            'classes': ('collapse',)
        }),
        ('Settings', {
            'fields': (
                'auto_fiscalize', 'related_invoice'
            )
        }),
        ('Metadata', {
            'fields': (
                'created_by', 'created_at', 'updated_at'
            ),
            'classes': ('collapse',)
        }),
    )

    actions = [
        'fiscalize_selected_invoices',
        'mark_as_paid',
        'export_to_csv'
    ]

    date_hierarchy = 'created_at'

    def get_queryset(self, request):
        """Optimize queryset"""
        qs = super().get_queryset(request)
        return qs.select_related(
            'sale', 'sale__customer', 'sale__store',
            'created_by', 'fiscalized_by'
        ).prefetch_related('payments')

    # Display methods
    def invoice_number(self, obj):
        """Display invoice number with link"""
        if obj.invoice_number:
            url = reverse('admin:invoices_invoice_change', args=[obj.pk])
            return format_html(
                '<a href="{}">{}</a>',
                url,
                obj.invoice_number
            )
        return '-'

    invoice_number.short_description = 'Invoice #'

    def customer_display(self, obj):
        """Display customer name"""
        if obj.customer:
            return obj.customer.name
        return 'Walk-in Customer'

    customer_display.short_description = 'Customer'

    def total_amount_display(self, obj):
        """Display total amount with currency"""
        return format_html(
            '<strong>{} {}</strong>',
            obj.currency_code,
            f'{obj.total_amount:,.2f}'
        )

    total_amount_display.short_description = 'Total Amount'

    def status_badge(self, obj):
        """Display status with colored badge"""
        if not obj.sale:
            return '-'

        status_colors = {
            'DRAFT': 'gray',
            'PENDING_PAYMENT': 'orange',
            'PARTIALLY_PAID': 'blue',
            'PAID': 'green',
            'COMPLETED': 'green',
            'OVERDUE': 'red',
            'VOIDED': 'red',
            'REFUNDED': 'purple',
            'CANCELLED': 'red',
        }

        color = status_colors.get(obj.sale.status, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.sale.get_status_display()
        )

    status_badge.short_description = 'Status'

    def fiscalization_badge(self, obj):
        """Display fiscalization status badge"""
        if obj.is_fiscalized:
            return format_html(
                '<span style="background-color: green; color: white; '
                'padding: 3px 10px; border-radius: 3px;">'
                '✓ Fiscalized</span>'
            )
        elif obj.fiscalization_status == 'failed':
            return format_html(
                '<span style="background-color: red; color: white; '
                'padding: 3px 10px; border-radius: 3px;">'
                '✗ Failed</span>'
            )
        else:
            return format_html(
                '<span style="background-color: orange; color: white; '
                'padding: 3px 10px; border-radius: 3px;">'
                '⧗ Pending</span>'
            )

    fiscalization_badge.short_description = 'Fiscalization'

    def days_overdue_display(self, obj):
        """Display days overdue"""
        days = obj.days_overdue
        if days > 0:
            return format_html(
                '<span style="color: red; font-weight: bold;">{} days</span>',
                days
            )
        return '-'

    days_overdue_display.short_description = 'Overdue'

    def invoice_summary(self, obj):
        """Display invoice summary"""
        if not obj.sale:
            return '-'

        html = f"""
        <table style="width: 100%; border-collapse: collapse;">
            <tr>
                <td style="padding: 5px;"><strong>Invoice Number:</strong></td>
                <td style="padding: 5px;">{obj.invoice_number}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Issue Date:</strong></td>
                <td style="padding: 5px;">{obj.issue_date}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Due Date:</strong></td>
                <td style="padding: 5px;">{obj.due_date or 'N/A'}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Subtotal:</strong></td>
                <td style="padding: 5px;">{obj.currency_code} {obj.subtotal:,.2f}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Tax:</strong></td>
                <td style="padding: 5px;">{obj.currency_code} {obj.tax_amount:,.2f}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Discount:</strong></td>
                <td style="padding: 5px;">{obj.currency_code} {obj.discount_amount:,.2f}</td>
            </tr>
            <tr style="border-top: 2px solid #ddd;">
                <td style="padding: 5px;"><strong>Total:</strong></td>
                <td style="padding: 5px;"><strong>{obj.currency_code} {obj.total_amount:,.2f}</strong></td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Paid:</strong></td>
                <td style="padding: 5px;">{obj.currency_code} {obj.amount_paid:,.2f}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Outstanding:</strong></td>
                <td style="padding: 5px;"><strong style="color: red;">{obj.currency_code} {obj.amount_outstanding:,.2f}</strong></td>
            </tr>
        </table>
        """
        return format_html(html)

    invoice_summary.short_description = 'Invoice Summary'

    def efris_info_display(self, obj):
        """Display EFRIS information"""
        if not obj.is_fiscalized:
            return format_html(
                '<p style="color: gray;">Not yet fiscalized</p>'
            )

        html = f"""
        <table style="width: 100%; border-collapse: collapse;">
            <tr>
                <td style="padding: 5px;"><strong>Fiscal Document Number:</strong></td>
                <td style="padding: 5px;">{obj.fiscal_document_number or 'N/A'}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Verification Code:</strong></td>
                <td style="padding: 5px;">{obj.verification_code or 'N/A'}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Device Number:</strong></td>
                <td style="padding: 5px;">{obj.device_number or 'N/A'}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Fiscalization Time:</strong></td>
                <td style="padding: 5px;">{obj.fiscalization_time or 'N/A'}</td>
            </tr>
            <tr>
                <td style="padding: 5px;"><strong>Fiscalized By:</strong></td>
                <td style="padding: 5px;">{obj.fiscalized_by or 'N/A'}</td>
            </tr>
        </table>
        """
        return format_html(html)

    efris_info_display.short_description = 'EFRIS Information'

    # Actions
    def fiscalize_selected_invoices(self, request, queryset):
        """Bulk fiscalize selected invoices"""
        success_count = 0
        failed_count = 0

        for invoice in queryset:
            can_fiscalize, message = invoice.can_fiscalize(request.user)
            if can_fiscalize:
                try:
                    invoice.fiscalize(request.user)
                    success_count += 1
                except Exception as e:
                    failed_count += 1
                    self.message_user(
                        request,
                        f'Failed to fiscalize {invoice.invoice_number}: {str(e)}',
                        messages.ERROR
                    )
            else:
                failed_count += 1

        if success_count > 0:
            self.message_user(
                request,
                f'{success_count} invoices fiscalized successfully.',
                messages.SUCCESS
            )

        if failed_count > 0:
            self.message_user(
                request,
                f'{failed_count} invoices could not be fiscalized.',
                messages.WARNING
            )

    fiscalize_selected_invoices.short_description = 'Fiscalize selected invoices'

    def mark_as_paid(self, request, queryset):
        """Mark selected invoices as paid"""
        count = 0
        for invoice in queryset:
            if invoice.sale:
                invoice.sale.status = 'PAID'
                invoice.sale.payment_status = 'PAID'
                invoice.sale.save()
                count += 1

        self.message_user(
            request,
            f'{count} invoices marked as paid.',
            messages.SUCCESS
        )

    mark_as_paid.short_description = 'Mark as paid'

    def export_to_csv(self, request, queryset):
        """Export selected invoices to CSV"""
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="invoices.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Invoice Number', 'Customer', 'Issue Date', 'Due Date',
            'Total Amount', 'Status', 'Fiscalized'
        ])

        for invoice in queryset:
            writer.writerow([
                invoice.invoice_number,
                invoice.customer_display(invoice),
                invoice.issue_date,
                invoice.due_date,
                invoice.total_amount,
                invoice.sale.get_status_display() if invoice.sale else '',
                'Yes' if invoice.is_fiscalized else 'No'
            ])

        return response

    export_to_csv.short_description = 'Export to CSV'


@admin.register(InvoicePayment)
class InvoicePaymentAdmin(admin.ModelAdmin):
    """Admin for invoice payments"""

    list_display = [
        'invoice_number', 'amount_display', 'payment_method_badge',
        'payment_date', 'processed_by', 'created_at'
    ]

    list_filter = [
        'payment_method', 'payment_date', 'created_at'
    ]

    search_fields = [
        'invoice__sale__document_number', 'transaction_reference',
        'notes', 'invoice__sale__customer__name'
    ]

    readonly_fields = [
        'invoice', 'processed_by', 'created_at'
    ]

    fieldsets = (
        ('Payment Information', {
            'fields': (
                'invoice', 'amount', 'payment_method',
                'transaction_reference', 'payment_date'
            )
        }),
        ('Additional Information', {
            'fields': (
                'notes', 'processed_by', 'created_at'
            )
        }),
    )

    date_hierarchy = 'payment_date'

    def get_queryset(self, request):
        """Optimize queryset"""
        qs = super().get_queryset(request)
        return qs.select_related(
            'invoice', 'invoice__sale',
            'processed_by'
        )

    def invoice_number(self, obj):
        """Display invoice number"""
        return obj.invoice.invoice_number

    invoice_number.short_description = 'Invoice'

    def amount_display(self, obj):
        """Display amount with currency"""
        return format_html(
            '<strong>{} {}</strong>',
            obj.invoice.currency_code,
            f'{obj.amount:,.2f}'
        )

    amount_display.short_description = 'Amount'

    def payment_method_badge(self, obj):
        """Display payment method with badge"""
        colors = {
            'CASH': 'green',
            'BANK_TRANSFER': 'blue',
            'MOBILE_MONEY': 'purple',
            'CHEQUE': 'orange',
            'CREDIT_CARD': 'teal',
            'OTHER': 'gray',
        }

        color = colors.get(obj.payment_method, 'gray')
        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 10px; border-radius: 3px;">{}</span>',
            color,
            obj.get_payment_method_display()
        )

    payment_method_badge.short_description = 'Payment Method'


@admin.register(InvoiceTemplate)
class InvoiceTemplateAdmin(admin.ModelAdmin):
    """Admin for invoice templates"""

    list_display = [
        'name', 'version', 'is_default_badge',
        'is_efris_compliant_badge', 'created_by', 'created_at'
    ]

    list_filter = [
        'is_default', 'is_efris_compliant', 'created_at'
    ]

    search_fields = [
        'name', 'version'
    ]

    readonly_fields = [
        'created_by', 'created_at', 'updated_at'
    ]

    fieldsets = (
        ('Template Information', {
            'fields': (
                'name', 'version', 'template_file'
            )
        }),
        ('Settings', {
            'fields': (
                'is_default', 'is_efris_compliant'
            )
        }),
        ('Metadata', {
            'fields': (
                'created_by', 'created_at', 'updated_at'
            )
        }),
    )

    def is_default_badge(self, obj):
        """Display default badge"""
        if obj.is_default:
            return format_html(
                '<span style="background-color: green; color: white; '
                'padding: 3px 10px; border-radius: 3px;">✓ Default</span>'
            )
        return '-'

    is_default_badge.short_description = 'Default'

    def is_efris_compliant_badge(self, obj):
        """Display EFRIS compliance badge"""
        if obj.is_efris_compliant:
            return format_html(
                '<span style="background-color: blue; color: white; '
                'padding: 3px 10px; border-radius: 3px;">✓ EFRIS</span>'
            )
        return '-'

    is_efris_compliant_badge.short_description = 'EFRIS Compliant'

    def save_model(self, request, obj, form, change):
        """Set created_by on save"""
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)