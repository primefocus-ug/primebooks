from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from .models import Category, Supplier, Product, Stock, StockMovement, Service

from inventory.models import (
   ProductBundle, BarcodeLabel, ScanSession, ScanEvent
)

@admin.register(ProductBundle)
class ProductBundleAdmin(admin.ModelAdmin):
   list_display = ['parent_product', 'child_product', 'child_qty', 'is_separate_product']
   list_filter = ['is_separate_product', 'is_active']

@admin.register(BarcodeLabel)
class BarcodeLabelAdmin(admin.ModelAdmin):
   list_display = ['product', 'quantity', 'label_size', 'status', 'created_at']
   list_filter = ['status', 'label_size']
   actions = ['mark_printed']

@admin.register(ScanSession)
class ScanSessionAdmin(admin.ModelAdmin):
   list_display = ['user', 'mode', 'store', 'total_scans', 'status', 'started_at']
   list_filter = ['mode', 'status']


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'code', 'category', 'unit_price', 'final_price',
        'tax_rate', 'efris_status_badge', 'is_active', 'created_at'
    ]
    list_filter = [
        'is_active', 'tax_rate', 'efris_is_uploaded',
        'efris_auto_sync_enabled', 'category'
    ]
    search_fields = ['name', 'code', 'description']
    readonly_fields = [
        'efris_status_display', 'efris_commodity_category_name',
        'efris_is_uploaded', 'efris_upload_date', 'efris_service_id',
        'created_at', 'updated_at', 'efris_configuration_status'
    ]

    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name', 'code', 'category', 'description', 'image', 'is_active')
        }),
        (_('Pricing'), {
            'fields': ('unit_price', 'unit_of_measure')
        }),
        (_('Tax Configuration'), {
            'fields': ('tax_rate', 'excise_duty_rate')
        }),
        (_('EFRIS Information'), {
            'fields': (
                'efris_commodity_category_name',
                'efris_auto_sync_enabled',
                'efris_status_display',
                'efris_is_uploaded',
                'efris_upload_date',
                'efris_service_id',
                'efris_configuration_status'
            ),
            'classes': ('collapse',)
        }),
        (_('System Information'), {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    actions = [
        'mark_for_efris_upload',
        'enable_efris_sync',
        'disable_efris_sync',
        'activate_services',
        'deactivate_services'
    ]

    def efris_status_badge(self, obj):
        """Display EFRIS status as a colored badge"""
        if not obj.efris_auto_sync_enabled:
            color = 'gray'
            text = '⏸️ Sync Disabled'
        elif obj.efris_is_uploaded:
            color = 'green'
            text = '✅ Uploaded'
        else:
            color = 'orange'
            text = '⏳ Pending'

        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 10px; border-radius: 3px;">{}</span>',
            color, text
        )

    efris_status_badge.short_description = 'EFRIS Status'

    def efris_configuration_status(self, obj):
        """Display EFRIS configuration status with errors if any"""
        if obj.efris_configuration_complete:
            return format_html(
                '<span style="color: green;">✅ Configuration Complete</span>'
            )
        else:
            errors = obj.get_efris_errors()
            error_list = '<br>'.join(f'• {error}' for error in errors)
            return format_html(
                '<span style="color: red;">❌ Configuration Incomplete</span><br>'
                '<div style="margin-top: 10px; padding: 10px; '
                'background-color: #fff3cd; border-left: 3px solid #ffc107;">'
                '{}</div>',
                error_list
            )

    efris_configuration_status.short_description = 'EFRIS Configuration'

    # Actions
    def mark_for_efris_upload(self, request, queryset):
        count = 0
        for service in queryset:
            service.mark_for_efris_upload()
            count += 1
        self.message_user(request, f'{count} service(s) marked for EFRIS upload.')

    mark_for_efris_upload.short_description = 'Mark selected for EFRIS upload'

    def enable_efris_sync(self, request, queryset):
        count = 0
        errors = []
        for service in queryset:
            try:
                service.enable_efris_sync()
                count += 1
            except ValueError as e:
                errors.append(f"{service.name}: {str(e)}")

        if count:
            self.message_user(request, f'EFRIS sync enabled for {count} service(s).')
        if errors:
            self.message_user(
                request,
                f'Errors: {"; ".join(errors)}',
                level='error'
            )

    enable_efris_sync.short_description = 'Enable EFRIS sync'

    def disable_efris_sync(self, request, queryset):
        count = queryset.count()
        for service in queryset:
            service.disable_efris_sync()
        self.message_user(request, f'EFRIS sync disabled for {count} service(s).')

    disable_efris_sync.short_description = 'Disable EFRIS sync'

    def activate_services(self, request, queryset):
        count = queryset.update(is_active=True)
        self.message_user(request, f'{count} service(s) activated.')

    activate_services.short_description = 'Activate selected services'

    def deactivate_services(self, request, queryset):
        count = queryset.update(is_active=False)
        self.message_user(request, f'{count} service(s) deactivated.')

    deactivate_services.short_description = 'Deactivate selected services'

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Limit category choices to service categories only"""
        if db_field.name == "category":
            kwargs["queryset"] = Category.objects.filter(
                category_type='service',
                is_active=True
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'category_type', 'code',
        'efris_commodity_category_code',
        'product_count', 'service_count',
        'efris_status_badge', 'is_active'
    ]
    list_filter = [
        'category_type', 'is_active',
        'efris_is_uploaded', 'efris_auto_sync'
    ]
    search_fields = ['name', 'code', 'efris_commodity_category_code']

    fieldsets = (
        (_('Basic Information'), {
            'fields': ('name', 'code', 'category_type', 'description', 'is_active')
        }),
        (_('EFRIS Configuration'), {
            'fields': (
                'efris_commodity_category_code',
                'efris_auto_sync',
                'efris_is_uploaded',
                'efris_upload_date',
                'efris_category_id'
            )
        }),
    )

    def service_count(self, obj):
        """Count of active services in this category"""
        if obj.category_type == 'service':
            count = obj.services.filter(is_active=True).count()
            return format_html(
                '<a href="{}?category__id__exact={}">{} services</a>',
                reverse('admin:inventory_service_changelist'),
                obj.id,
                count
            )
        return '-'

    service_count.short_description = 'Services'

    def efris_status_badge(self, obj):
        """Display EFRIS status as a colored badge"""
        if not obj.efris_auto_sync:
            color = 'gray'
            text = '⏸️ Disabled'
        elif obj.efris_is_uploaded:
            color = 'green'
            text = '✅ Synced'
        else:
            color = 'orange'
            text = '⏳ Pending'

        return format_html(
            '<span style="background-color: {}; color: white; '
            'padding: 3px 10px; border-radius: 3px;">{}</span>',
            color, text
        )

    efris_status_badge.short_description = 'EFRIS Status'


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
    """
    Admin configuration for Product with full EFRIS & export support
    """

    # =========================================================
    # LIST VIEW
    # =========================================================
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
        'is_export_product',
        'is_active',
        'created_at',
    )

    search_fields = (
        'name',
        'sku',
        'barcode',
        'efris_goods_id',
        'efris_item_code',
    )

    ordering = ('name',)

    # =========================================================
    # READ-ONLY FIELDS
    # =========================================================
    readonly_fields = (
        'created_at',
        'updated_at',

        # Stock & pricing calculations
        'total_stock',
        'stock_percentage',
        'final_price',

        # EFRIS derived / API fields
        'efris_status_display',
        'efris_configuration_complete',
        'efris_is_uploaded',
        'efris_upload_date',
        'efris_goods_id',
        'efris_goods_code',
        'efris_goods_name',
        'efris_tax_category_id',
        'efris_tax_rate',
        'efris_unit_of_measure_code',
    )

    inlines = [StockInline]

    # =========================================================
    # FIELDSETS (NO DUPLICATES — SYSTEM CHECK SAFE)
    # =========================================================
    fieldsets = (

        # -----------------------------------------------------
        # BASIC PRODUCT INFO
        # -----------------------------------------------------
        (None, {
            'fields': (
                'name',
                'sku',
                'barcode',
                'category',
                'supplier',
                'description',
                'image',
                'efris_item_code',
            )
        }),

        # -----------------------------------------------------
        # PRICING, TAX & EXPORT SETTINGS
        # -----------------------------------------------------
        ('Pricing, Tax & Export', {
            'fields': (
                'selling_price',
                'cost_price',
                'discount_percentage',
                'final_price',
                'tax_rate',
                'excise_duty_rate',

                # Export classification
                'is_export_product',
                'hs_code',
                'hs_name',

                # Customs pricing
                'efris_customs_measure_unit',
                'efris_customs_unit_price',
                'efris_package_scaled_value_customs',
                'efris_customs_scaled_value',
            )
        }),

        # -----------------------------------------------------
        # STOCK & AVAILABILITY
        # -----------------------------------------------------
        ('Stock Details', {
            'fields': (
                'unit_of_measure',
                'min_stock_level',
                'total_stock',
                'stock_percentage',
                'is_active',
            )
        }),

        # -----------------------------------------------------
        # EFRIS CONFIGURATION (EDITABLE)
        # -----------------------------------------------------
        ('EFRIS Configuration', {
            'fields': (
                'efris_auto_sync_enabled',
                'efris_excise_duty_code',

                # Piece / package units
                'efris_has_piece_unit',
                'efris_piece_measure_unit',
                'efris_piece_unit_price',
                'efris_package_scaled_value',
                'efris_piece_scaled_value',

                # Other units
                'efris_has_other_units',

                # Configuration status
                'efris_status_display',
                'efris_configuration_complete',
            )
        }),

        # -----------------------------------------------------
        # EFRIS STATUS (READ-ONLY)
        # -----------------------------------------------------
        ('EFRIS Status (Read-only)', {
            'fields': (
                'efris_is_uploaded',
                'efris_upload_date',
                'efris_goods_id',
                'efris_goods_code',
                'efris_goods_name',
                'efris_tax_category_id',
                'efris_tax_rate',
                'efris_unit_of_measure_code',
            ),
            'classes': ('collapse',),
        }),

        # -----------------------------------------------------
        # METADATA
        # -----------------------------------------------------
        ('Metadata', {
            'fields': (
                'created_at',
                'updated_at',
            ),
            'classes': ('collapse',),
        }),
    )

    # =========================================================
    # ADMIN ACTIONS
    # =========================================================
    actions = (
        'enable_efris_sync',
        'disable_efris_sync',
        'mark_for_efris_upload',
    )

    def enable_efris_sync(self, request, queryset):
        updated = queryset.update(efris_auto_sync_enabled=True)
        self.message_user(request, f"EFRIS sync enabled for {updated} product(s).")

    enable_efris_sync.short_description = "Enable EFRIS sync for selected products"

    def disable_efris_sync(self, request, queryset):
        updated = queryset.update(efris_auto_sync_enabled=False)
        self.message_user(request, f"EFRIS sync disabled for {updated} product(s).")

    disable_efris_sync.short_description = "Disable EFRIS sync for selected products"

    def mark_for_efris_upload(self, request, queryset):
        for product in queryset:
            product.mark_for_efris_upload()
        self.message_user(
            request,
            f"Marked {queryset.count()} product(s) for EFRIS upload."
        )

    mark_for_efris_upload.short_description = "Mark selected products for EFRIS upload"

    # =========================================================
    # QUERYSET OPTIMIZATION
    # =========================================================
    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related('category', 'supplier')
            .prefetch_related('store_inventory')
        )

    # =========================================================
    # DISPLAY HELPERS
    # =========================================================
    def efris_status_display(self, obj):
        return obj.efris_status_display

    efris_status_display.short_description = "EFRIS Status"

    def efris_configuration_complete(self, obj):
        return obj.efris_configuration_complete

    efris_configuration_complete.boolean = True
    efris_configuration_complete.short_description = "EFRIS Ready"


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
