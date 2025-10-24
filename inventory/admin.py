from django.contrib import admin

from .models import Category, Supplier, Product, Stock, StockMovement


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'code',  'is_active', 'created_at', 'updated_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'code')
    ordering = ('name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'tin', 'contact_person', 'phone', 'email', 'country', 'is_active', 'created_at')
    list_filter = ('is_active', 'country', 'created_at')
    search_fields = ('name', 'tin', 'phone', 'email')
    ordering = ('name',)
    readonly_fields = ('created_at', 'updated_at')


class StockInline(admin.TabularInline):
    """Inline stock display in the Product admin."""
    model = Stock
    extra = 0
    fields = ('store', 'quantity', 'low_stock_threshold','reorder_quantity', 'last_updated')
    readonly_fields = ('last_updated',)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'sku',
        'barcode',
        'category',
        'supplier',
        'selling_price',
        'cost_price',
        'tax_rate',
        'efris_item_code',
        'efris_status_display',
        'efris_configuration_complete',
        'is_active',
        'created_at',
    )

    list_filter = (
        'category',
        'supplier',
        'tax_rate',
        'efris_is_uploaded',
        'efris_auto_sync_enabled',
        'efris_has_piece_unit',
        'is_active',
        'created_at'
    )

    search_fields = (
        'name',
        'sku',
        'barcode',
        'efris_goods_id',
        'efris_item_code'
    )

    ordering = ('name',)

    readonly_fields = (
        'created_at',
        'updated_at',
        'efris_status_display',
        'efris_configuration_complete',
        'total_stock',
        'stock_percentage',
        'efris_goods_code',
        'efris_goods_id',
        'efris_goods_name',
        'efris_tax_category_id',
        'efris_tax_rate',
        'efris_unit_of_measure_code',
        'final_price',
        'efris_upload_date'
    )

    inlines = [StockInline]

    fieldsets = (
        (None, {
            'fields': (
                'name', 'sku', 'barcode', 'category', 'supplier', 'description', 'image','efris_item_code'
            )
        }),
        ('Pricing & Tax', {
            'fields': (
                'selling_price', 'cost_price', 'discount_percentage',
                'final_price', 'tax_rate', 'excise_duty_rate'
            )
        }),
        ('Stock Details', {
            'fields': (
                'unit_of_measure', 'min_stock_level', 'total_stock',
                'stock_percentage', 'is_active'
            )
        }),
        ('EFRIS Configuration', {
            'fields': (
                'efris_auto_sync_enabled',
                'efris_excise_duty_code',
                'efris_has_piece_unit',
                'efris_piece_measure_unit',
                'efris_piece_unit_price',
                'efris_status_display',
                'efris_configuration_complete'
            )
        }),
        ('EFRIS Status (Read-only)', {
            'fields': (
                'efris_is_uploaded',
                'efris_upload_date',
                'efris_goods_id',
                'efris_goods_code',
                'efris_goods_name',
                'efris_tax_category_id',
                'efris_tax_rate',
                'efris_unit_of_measure_code'

            ),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': (
                'created_at', 'updated_at'
            ),
            'classes': ('collapse',)
        }),
    )

    actions = ['enable_efris_sync', 'disable_efris_sync', 'mark_for_efris_upload']

    def enable_efris_sync(self, request, queryset):
        """Admin action to enable EFRIS sync for selected products"""
        updated = queryset.update(efris_auto_sync_enabled=True)
        self.message_user(request, f"EFRIS sync enabled for {updated} product(s)")

    enable_efris_sync.short_description = "Enable EFRIS sync for selected products"

    def disable_efris_sync(self, request, queryset):
        """Admin action to disable EFRIS sync for selected products"""
        updated = queryset.update(efris_auto_sync_enabled=False)
        self.message_user(request, f"EFRIS sync disabled for {updated} product(s)")

    disable_efris_sync.short_description = "Disable EFRIS sync for selected products"

    def mark_for_efris_upload(self, request, queryset):
        """Admin action to mark products for EFRIS upload"""
        for product in queryset:
            product.mark_for_efris_upload()
        self.message_user(request, f"Marked {queryset.count()} product(s) for EFRIS upload")

    mark_for_efris_upload.short_description = "Mark for EFRIS upload"

    def get_queryset(self, request):
        """Optimize queryset for admin performance"""
        return super().get_queryset(request).select_related(
            'category', 'supplier'
        ).prefetch_related('store_inventory')

    def efris_status_display(self, obj):
        """Display EFRIS status in list view"""
        return obj.efris_status_display

    efris_status_display.short_description = 'EFRIS Status'

    def efris_configuration_complete(self, obj):
        """Display configuration status in list view"""
        return obj.efris_configuration_complete

    efris_configuration_complete.boolean = True
    efris_configuration_complete.short_description = 'EFRIS Ready'


@admin.register(Stock)
class StockAdmin(admin.ModelAdmin):
    list_display = ('product', 'store', 'quantity','low_stock_threshold',
        'reorder_quantity', 'status', 'last_updated')
    list_filter = ('store', 'product__category')
    search_fields = ('product__name', 'store__name')
    ordering = ('product__name',)
    readonly_fields = ('last_updated',)

    def status(self, obj):
        """Display human-readable stock status."""
        status_map = {
            'out_of_stock': '❌ Out of Stock',
            'low_stock': '⚠️ Low Stock',
            'in_stock': '✅ In Stock',
        }
        return status_map.get(obj.status, obj.status)

    status.admin_order_field = 'quantity'
    status.short_description = "Stock Status"


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        'movement_type',
        'product',
        'store',
        'quantity',
        'unit_price',
        'total_value',
        'reference',
        'created_by',
        'created_at',
    )
    list_filter = ('movement_type', 'store', 'created_at')
    search_fields = ('product__name', 'reference', 'store__name', 'created_by__username')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
