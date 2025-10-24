from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.db.models import Sum, Count
from django.http import HttpResponseRedirect
from django.contrib import messages
from django.shortcuts import get_object_or_404

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
        'transaction_reference',
        'is_confirmed',
        'confirmed_at',
        'created_at',
        'notes'
    )


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = (
        'invoice_number',
        'short_transaction_id',
        'store',
        'created_by',
        'customer_name',
        'transaction_type',
        'payment_method',
        'formatted_total_amount',
        'status_display',
        'fiscalization_status',
        'created_at',
    )
    list_filter = (
        'store',
        'transaction_type',
        'document_type',
        'payment_method',
        'is_completed',
        'is_refunded',
        'is_voided',
        'is_fiscalized',
        ('created_at', admin.DateFieldListFilter),
        ('fiscalization_time', admin.DateFieldListFilter),
    )
    search_fields = (
        'invoice_number',
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
        'invoice_number',
        'subtotal',
        'tax_amount',
        'discount_amount',
        'total_amount',
        'item_count',
        'total_quantity',
        'created_at',
        'updated_at',
        'fiscalization_time',
    )
    ordering = ('-created_at',)
    inlines = [SaleItemInline, PaymentInline]
    list_per_page = 25
    date_hierarchy = 'created_at'

    fieldsets = (
        ('Basic Information', {
            'fields': (
                'transaction_id',
                'invoice_number',
                'store',
                'created_by',
                'customer'
            )
        }),
        ('Transaction Details', {
            'fields': (
                'transaction_type',
                'document_type',
                'payment_method',
                'currency'
            )
        }),
        ('Financial Summary', {
            'fields': (
                ('subtotal', 'tax_amount'),
                ('discount_amount', 'total_amount'),
                ('item_count', 'total_quantity')
            ),
            'classes': ('collapse',)
        }),
        ('EFRIS Integration', {
            'fields': (
                'efris_invoice_number',
                'verification_code',
                'qr_code',
                'is_fiscalized',
                'fiscalization_time'
            ),
            'classes': ('collapse',)
        }),
        ('Status & Control', {
            'fields': (
                'is_completed',
                'is_refunded',
                'is_voided',
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
        if obj.is_voided:
            return format_html(
                '<span style="color: #dc3545; font-weight: bold;">VOIDED</span>'
            )
        elif obj.is_refunded:
            return format_html(
                '<span style="color: #fd7e14; font-weight: bold;">REFUNDED</span>'
            )
        elif obj.is_completed:
            return format_html(
                '<span style="color: #28a745; font-weight: bold;">COMPLETED</span>'
            )
        else:
            return format_html(
                '<span style="color: #6c757d; font-weight: bold;">PENDING</span>'
            )

    status_display.short_description = 'Status'

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
        return actions

    def fiscalize_sales(self, request, queryset):
        """Custom admin action to fiscalize sales"""
        updated = 0
        for sale in queryset.filter(is_fiscalized=False):
            # Add your EFRIS integration logic here
            sale.is_fiscalized = True
            sale.fiscalization_time = timezone.now()
            sale.save(update_fields=['is_fiscalized', 'fiscalization_time'])
            updated += 1

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
                    f'Error voiding sale {sale.invoice_number}: {str(e)}',
                    messages.ERROR
                )

        self.message_user(
            request,
            f'{voided} sales were successfully voided.',
            messages.SUCCESS if voided > 0 else messages.WARNING
        )

    void_sales.short_description = 'Void selected sales'


@admin.register(SaleItem)
class SaleItemAdmin(admin.ModelAdmin):
    list_display = (
        'sale_invoice',
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
        ('sale__created_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'product__name',
        'product__sku',
        'sale__invoice_number',
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

    def sale_invoice(self, obj):
        return obj.sale.invoice_number or f"Sale #{obj.sale.id}"

    sale_invoice.short_description = 'Sale'
    sale_invoice.admin_order_field = 'sale__invoice_number'

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
        'sale_invoice',
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
        'sale__invoice_number',
        'sale__transaction_id',
        'printed_by__username',
    )
    readonly_fields = ('printed_at', 'print_count')
    ordering = ('-printed_at',)
    list_select_related = ('sale', 'store', 'printed_by')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('sale', 'store', 'printed_by')

    def sale_invoice(self, obj):
        return obj.sale.invoice_number or f"Sale #{obj.sale.id}"

    sale_invoice.short_description = 'Sale'
    sale_invoice.admin_order_field = 'sale__invoice_number'

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
        'sale_invoice',
        'amount',
        'payment_method',
        'confirmation_status',
        'transaction_reference',
        'created_at',
    )
    list_filter = (
        'payment_method',
        'is_confirmed',
        ('created_at', admin.DateFieldListFilter),
        ('confirmed_at', admin.DateFieldListFilter),
    )
    search_fields = (
        'sale__invoice_number',
        'sale__transaction_id',
        'transaction_reference',
    )
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
    list_select_related = ('sale',)

    fieldsets = (
        ('Payment Information', {
            'fields': ('sale', 'amount', 'payment_method', 'transaction_reference')
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

    def sale_invoice(self, obj):
        return obj.sale.invoice_number or f"Sale #{obj.sale.id}"

    sale_invoice.short_description = 'Sale'
    sale_invoice.admin_order_field = 'sale__invoice_number'

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
        from django.utils import timezone
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
        'status',
        'item_count_display',
        'total_amount',
        'created_at',
        'updated_at',
    )
    list_filter = (
        'status',
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

