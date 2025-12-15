from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.db.models import Sum, Count
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import Sale, SaleItem, Receipt, Payment, Cart, CartItem


class SaleItemInline(admin.TabularInline):
    model = SaleItem
    extra = 1
    readonly_fields = ('total_price', 'discount_amount', 'tax_amount', 'line_total', 'net_amount')
    fields = (
        'product',
        'quantity',
        'unit_price',
        'total_price',
        'discount',
        'discount_amount',
        'tax_rate',
        'tax_amount',
        'net_amount',
        'line_total',
        'description',
    )
    show_change_link = True

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('product')


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    readonly_fields = ('created_at',)
    fields = (
        'amount',
        'payment_method',
        'payment_type',
        'transaction_reference',
        'is_confirmed',
        'confirmed_at',
        'created_at',
        'notes'
    )


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = (
        'document_number_display',
        'document_type_badge',
        'short_transaction_id',
        'store',
        'created_by',
        'customer_name',
        'payment_method',
        'payment_status_badge',
        'formatted_total_amount',
        'status_display',
        'fiscalization_status',
        'created_at',
    )
    list_filter = (
        'store',
        'document_type',
        'payment_method',
        'payment_status',
        'status',
        'is_fiscalized',
        'is_voided',
        'is_refunded',
        ('created_at', admin.DateFieldListFilter),
        ('due_date', admin.DateFieldListFilter),
        ('fiscalization_time', admin.DateFieldListFilter),
    )
    search_fields = (
        'document_number',
        'transaction_id',
        'efris_invoice_number',
        'customer__name',
        'customer__phone',
        'customer__email',
        'created_by__username',
        'created_by__first_name',
        'created_by__last_name',
    )
    readonly_fields = (
        'transaction_id',
        'document_number',
        'subtotal',
        'tax_amount',
        'discount_amount',
        'total_amount',
        'item_count',
        'total_quantity',
        'created_at',
        'updated_at',
        'fiscalization_time',
        'amount_paid',
        'amount_outstanding',
        'days_overdue',
    )
    ordering = ('-created_at',)
    inlines = [SaleItemInline, PaymentInline]
    list_per_page = 25
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Basic Information', {
            'fields': (
                'transaction_id',
                'document_number',
                'document_type',
                'store',
                'created_by',
                'customer'
            )
        }),
        ('Document Details', {
            'fields': (
                'due_date',
                'payment_method',
                'currency',
                'payment_status',
                'status'
            )
        }),
        ('Financial Summary', {
            'fields': (
                ('subtotal', 'tax_amount'),
                ('discount_amount', 'total_amount'),
                ('item_count', 'total_quantity'),
                ('amount_paid', 'amount_outstanding'),
                'days_overdue'
            ),
            'classes': ('collapse',)
        }),
        ('EFRIS Integration', {
            'fields': (
                'efris_invoice_number',
                'verification_code',
                'qr_code',
                'is_fiscalized',
                'fiscalization_time',
                'fiscalization_status'
            ),
            'classes': ('collapse',)
        }),
        ('Status & Control', {
            'fields': (
                'is_voided',
                'is_refunded',
                'void_reason'
            )
        }),
        ('Additional Information', {
            'fields': (
                'notes',
                'related_sale',
                'created_at',
                'updated_at'
            ),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'store', 'customer', 'created_by', 'related_sale'
        ).prefetch_related('items', 'payments')

    def short_transaction_id(self, obj):
        return str(obj.transaction_id)[:8] + '...'

    short_transaction_id.short_description = 'Transaction ID'

    def customer_name(self, obj):
        if obj.customer:
            return obj.customer.name
        return 'Walk-in Customer'

    customer_name.short_description = 'Customer'
    customer_name.admin_order_field = 'customer__name'

    def formatted_total_amount(self, obj):
        return f"{obj.currency} {obj.total_amount:,.2f}"

    formatted_total_amount.short_description = 'Total Amount'
    formatted_total_amount.admin_order_field = 'total_amount'

    def status_display(self, obj):
        status_colors = {
            'DRAFT': '#6c757d',
            'PENDING_PAYMENT': '#ffc107',
            'PARTIALLY_PAID': '#17a2b8',
            'PAID': '#28a745',
            'COMPLETED': '#28a745',
            'OVERDUE': '#dc3545',
            'VOIDED': '#dc3545',
            'REFUNDED': '#fd7e14',
            'CANCELLED': '#6c757d',
        }
        color = status_colors.get(obj.status, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )

    status_display.short_description = 'Status'
    status_display.admin_order_field = 'status'

    def payment_status_badge(self, obj):
        status_colors = {
            'PENDING': '#ffc107',
            'PARTIALLY_PAID': '#17a2b8',
            'PAID': '#28a745',
            'OVERDUE': '#dc3545',
            'NOT_APPLICABLE': '#6c757d',
        }
        color = status_colors.get(obj.payment_status, '#6c757d')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_payment_status_display()
        )

    payment_status_badge.short_description = 'Payment Status'
    payment_status_badge.admin_order_field = 'payment_status'

    def document_type_badge(self, obj):
        type_colors = {
            'RECEIPT': '#28a745',
            'INVOICE': '#007bff',
            'PROFORMA': '#6c757d',
            'ESTIMATE': '#fd7e14',
        }
        color = type_colors.get(obj.document_type, '#6c757d')
        icon = {
            'RECEIPT': '🧾',
            'INVOICE': '📄',
            'PROFORMA': '📑',
            'ESTIMATE': '📋',
        }.get(obj.document_type, '📄')

        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}</span>',
            color,
            icon,
            obj.get_document_type_display()
        )

    document_type_badge.short_description = 'Document Type'
    document_type_badge.admin_order_field = 'document_type'

    def document_number_display(self, obj):
        return format_html(
            '<strong>{}</strong>',
            obj.document_number
        )

    document_number_display.short_description = 'Document Number'
    document_number_display.admin_order_field = 'document_number'

    def fiscalization_status(self, obj):
        if obj.is_fiscalized:
            return format_html(
                '<span style="color: #28a745;">✓ Fiscalized</span>'
            )
        else:
            return format_html(
                '<span style="color: #dc3545;">✗ Not Fiscalized</span>'
            )

    fiscalization_status.short_description = 'EFRIS Status'
    fiscalization_status.admin_order_field = 'is_fiscalized'

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions['fiscalize_sales'] = (
            self.fiscalize_sales,
            'fiscalize_sales',
            'Fiscalize selected sales'
        )
        actions['void_sales'] = (
            self.void_sales,
            'void_sales',
            'Void selected sales'
        )
        actions['mark_as_paid'] = (
            self.mark_as_paid,
            'mark_as_paid',
            'Mark selected invoices as paid'
        )
        actions['send_invoices'] = (
            self.send_invoices,
            'send_invoices',
            'Send selected invoices to customers'
        )
        actions['convert_to_invoice'] = (
            self.convert_to_invoice,
            'convert_to_invoice',
            'Convert proforma/estimate to invoice'
        )
        return actions

    def fiscalize_sales(self, request, queryset):
        """Custom admin action to fiscalize sales"""
        updated = 0
        for sale in queryset.filter(is_fiscalized=False, document_type='INVOICE'):
            try:
                # Add your EFRIS integration logic here
                sale.is_fiscalized = True
                sale.fiscalization_time = timezone.now()
                sale.fiscalization_status = 'fiscalized'
                sale.save(update_fields=['is_fiscalized', 'fiscalization_time', 'fiscalization_status'])
                updated += 1
            except Exception as e:
                self.message_user(
                    request,
                    f'Error fiscalizing sale {sale.document_number}: {str(e)}',
                    messages.ERROR
                )

        self.message_user(
            request,
            f'{updated} sales were successfully fiscalized.',
            messages.SUCCESS
        )

    fiscalize_sales.short_description = 'Fiscalize selected sales'

    def void_sales(self, request, queryset):
        """Custom admin action to void sales"""
        voided = 0
        for sale in queryset.filter(is_voided=False, is_refunded=False):
            try:
                sale.void_sale("Admin bulk void action")
                voided += 1
            except Exception as e:
                self.message_user(
                    request,
                    f'Error voiding sale {sale.document_number}: {str(e)}',
                    messages.ERROR
                )

        self.message_user(
            request,
            f'{voided} sales were successfully voided.',
            messages.SUCCESS if voided > 0 else messages.WARNING
        )

    void_sales.short_description = 'Void selected sales'

    def mark_as_paid(self, request, queryset):
        """Mark selected invoices as paid"""
        updated = 0
        for sale in queryset.filter(document_type='INVOICE', payment_status__in=['PENDING', 'PARTIALLY_PAID']):
            sale.payment_status = 'PAID'
            sale.status = 'COMPLETED'
            sale.save(update_fields=['payment_status', 'status'])
            updated += 1

        self.message_user(
            request,
            f'{updated} invoices were marked as paid.',
            messages.SUCCESS
        )

    mark_as_paid.short_description = 'Mark invoices as paid'

    def send_invoices(self, request, queryset):
        """Send invoices to customers"""
        sent = 0
        for sale in queryset.filter(document_type='INVOICE', status='PENDING_PAYMENT'):
            # Here you would implement email sending logic
            sale.status = 'SENT'  # This field needs to be added to Sale model if not exists
            sale.save()
            sent += 1

        self.message_user(
            request,
            f'{sent} invoices were sent to customers.',
            messages.SUCCESS
        )

    send_invoices.short_description = 'Send invoices to customers'

    def convert_to_invoice(self, request, queryset):
        """Convert proforma/estimate to invoice"""
        converted = 0
        for sale in queryset.filter(document_type__in=['PROFORMA', 'ESTIMATE']):
            try:
                sale.convert_to_invoice()
                converted += 1
            except Exception as e:
                self.message_user(
                    request,
                    f'Error converting {sale.document_number}: {str(e)}',
                    messages.ERROR
                )

        self.message_user(
            request,
            f'{converted} documents were converted to invoices.',
            messages.SUCCESS
        )

    convert_to_invoice.short_description = 'Convert to invoice'


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = (
        'sale_document',
        'product_name',
        'quantity',
        'unit_price',
        'total_price',
        'discount_display',
        'tax_rate',
        'tax_amount',
        'line_total',
    )
    list_filter = (
        'tax_rate',
        'sale__store',
        'sale__document_type',
        ('sale__created_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'product__name',
        'product__sku',
        'sale__document_number',
        'sale__transaction_id',
        'description'
    )
    readonly_fields = (
        'total_price',
        'discount_amount',
        'tax_amount',
        'line_total',
        'net_amount'
    )
    ordering = ('-sale__created_at', 'id')
    list_select_related = ('sale', 'product')

    fieldsets = (
        ('Sale Information', {
            'fields': ('sale',)
        }),
        ('Product Details', {
            'fields': ('product', 'quantity', 'unit_price', 'description')
        }),
        ('Pricing & Calculations', {
            'fields': (
                'total_price',
                ('discount', 'discount_amount'),
                ('tax_rate', 'tax_amount'),
                'net_amount',
                'line_total'
            )
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('sale', 'product')

    def sale_document(self, obj):
        doc_type = obj.sale.get_document_type_display()
        return f"{doc_type} #{obj.sale.document_number}"

    sale_document.short_description = 'Sale'
    sale_document.admin_order_field = 'sale__document_number'

    def product_name(self, obj):
        return obj.product.name

    product_name.short_description = 'Product'
    product_name.admin_order_field = 'product__name'

    def discount_display(self, obj):
        if obj.discount > 0:
            return f"{obj.discount}% ({obj.discount_amount})"
        return "No discount"

    discount_display.short_description = 'Discount'


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        'receipt_number',
        'sale_document',
        'store',
        'printed_by',
        'printed_at',
        'duplicate_status',
        'print_count',
    )
    list_filter = (
        'is_duplicate',
        'store',
        ('printed_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'receipt_number',
        'sale__document_number',
        'sale__transaction_id',
        'printed_by__username',
    )
    readonly_fields = ('printed_at', 'print_count')
    ordering = ('-printed_at',)
    list_select_related = ('sale', 'store', 'printed_by')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('sale', 'store', 'printed_by')

    def sale_document(self, obj):
        return obj.sale.document_number

    sale_document.short_description = 'Sale'
    sale_document.admin_order_field = 'sale__document_number'

    def duplicate_status(self, obj):
        if obj.is_duplicate:
            return format_html(
                '<span style="color: #fd7e14;">Duplicate</span>'
            )
        else:
            return format_html(
                '<span style="color: #28a745;">Original</span>'
            )

    duplicate_status.short_description = 'Status'
    duplicate_status.admin_order_field = 'is_duplicate'


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'sale_document',
        'amount',
        'payment_method',
        'payment_type_display',
        'confirmation_status',
        'transaction_reference',
        'created_at',
    )
    list_filter = (
        'payment_method',
        'payment_type',
        'is_confirmed',
        ('created_at', admin.DateFieldListFilter),
        ('confirmed_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'sale__document_number',
        'sale__transaction_id',
        'transaction_reference',
    )
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
    list_select_related = ('sale',)

    fieldsets = (
        ('Payment Information', {
            'fields': ('sale', 'amount', 'payment_method', 'payment_type', 'transaction_reference')
        }),
        ('Confirmation Details', {
            'fields': ('is_confirmed', 'confirmed_at')
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_at'),
            'classes': ('collapse',)
        }),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('sale')

    def sale_document(self, obj):
        return obj.sale.document_number

    sale_document.short_description = 'Sale'
    sale_document.admin_order_field = 'sale__document_number'

    def payment_type_display(self, obj):
        return obj.get_payment_type_display()

    payment_type_display.short_description = 'Payment Type'
    payment_type_display.admin_order_field = 'payment_type'

    def confirmation_status(self, obj):
        if obj.is_confirmed:
            return format_html(
                '<span style="color: #28a745;">✓ Confirmed</span>'
            )
        else:
            return format_html(
                '<span style="color: #dc3545;">✗ Pending</span>'
            )

    confirmation_status.short_description = 'Status'
    confirmation_status.admin_order_field = 'is_confirmed'

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions['confirm_payments'] = (
            self.confirm_payments,
            'confirm_payments',
            'Confirm selected payments'
        )
        return actions

    def confirm_payments(self, request, queryset):
        """Custom admin action to confirm payments"""
        updated = queryset.filter(is_confirmed=False).update(
            is_confirmed=True,
            confirmed_at=timezone.now()
        )
        self.message_user(
            request,
            f'{updated} payments were successfully confirmed.',
            messages.SUCCESS
        )

    confirm_payments.short_description = 'Confirm selected payments'


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    readonly_fields = ('total_price', 'discount_amount', 'tax_amount', 'added_at')
    fields = (
        'product',
        'quantity',
        'unit_price',
        'total_price',
        'discount',
        'discount_amount',
        'tax_rate',
        'tax_amount',
        'added_at',
    )


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'customer_name',
        'store',
        'document_type_display',
        'status',
        'item_count_display',
        'total_amount',
        'created_at',
        'updated_at',
    )
    list_filter = (
        'status',
        'document_type',
        'store',
        ('created_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'user__username',
        'customer__name',
        'session_key',
    )
    readonly_fields = (
        'subtotal',
        'tax_amount',
        'discount_amount',
        'total_amount',
        'created_at',
        'updated_at',
    )
    ordering = ('-updated_at',)
    inlines = [CartItemInline]
    list_select_related = ('user', 'customer', 'store')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'user', 'customer', 'store'
        ).prefetch_related('items')

    def customer_name(self, obj):
        return obj.customer.name if obj.customer else 'No customer'

    customer_name.short_description = 'Customer'
    customer_name.admin_order_field = 'customer__name'

    def document_type_display(self, obj):
        type_colors = {
            'RECEIPT': '#28a745',
            'INVOICE': '#007bff',
            'PROFORMA': '#6c757d',
            'ESTIMATE': '#fd7e14',
        }
        color = type_colors.get(obj.document_type, '#6c757d')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_document_type_display()
        )

    document_type_display.short_description = 'Document Type'
    document_type_display.admin_order_field = 'document_type'

    def item_count_display(self, obj):
        return obj.items.count()

    item_count_display.short_description = 'Items'

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions['abandon_carts'] = (
            self.abandon_carts,
            'abandon_carts',
            'Mark selected carts as abandoned'
        )
        return actions

    def abandon_carts(self, request, queryset):
        """Custom admin action to abandon carts"""
        updated = queryset.filter(status='OPEN').update(status='ABANDONED')
        self.message_user(
            request,
            f'{updated} carts were marked as abandoned.',
            messages.SUCCESS
        )

    abandon_carts.short_description = 'Abandon selected carts'


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = (
        'cart_id',
        'product_name',
        'quantity',
        'unit_price',
        'total_price',
        'discount_display',
        'tax_amount',
        'added_at',
    )
    list_filter = (
        'tax_rate',
        'cart__store',
        'cart__document_type',
        ('added_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'product__name',
        'cart__user__username',
        'cart__customer__name',
    )
    readonly_fields = ('total_price', 'discount_amount', 'tax_amount', 'added_at')
    ordering = ('-added_at',)
    list_select_related = ('cart', 'product')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('cart', 'product')

    def cart_id(self, obj):
        return f"Cart #{obj.cart.id}"

    cart_id.short_description = 'Cart'

    def product_name(self, obj):
        return obj.product.name

    product_name.short_description = 'Product'
    product_name.admin_order_field = 'product__name'

    def discount_display(self, obj):
        if obj.discount > 0:
            return f"{obj.discount}% ({obj.discount_amount})"
        return "No discount"

    discount_display.short_description = 'Discount'


# ==================== NEW: Custom Admin Views for Reports ====================
class DocumentTypeFilter(admin.SimpleListFilter):
    """Filter by document type with counts"""
    title = 'Document Type'
    parameter_name = 'document_type'

    def lookups(self, request, model_admin):
        return Sale.DOCUMENT_TYPE_CHOICES

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(document_type=self.value())
        return queryset


class PaymentStatusFilter(admin.SimpleListFilter):
    """Filter by payment status with counts"""
    title = 'Payment Status'
    parameter_name = 'payment_status'

    def lookups(self, request, model_admin):
        return Sale.PAYMENT_STATUS_CHOICES

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(payment_status=self.value())
        return queryset

from .payment_reminders import PaymentReminder

@admin.register(PaymentReminder)
class PaymentReminderAdmin(admin.ModelAdmin):
    list_display = ['sale', 'reminder_type', 'status', 'scheduled_for', 'sent_at']
    list_filter = ['status', 'reminder_type', 'scheduled_for']
    search_fields = ['sale__document_number', 'sent_to']
    readonly_fields = ['sent_at', 'created_at', 'updated_at']

    actions = ['send_reminders']

    def send_reminders(self, request, queryset):
        sent = 0
        for reminder in queryset.filter(status='PENDING'):
            if reminder.send():
                sent += 1

        self.message_user(
            request,
            f'{sent} reminders sent successfully'
        )
    send_reminders.short_description = 'Send selected reminders'
