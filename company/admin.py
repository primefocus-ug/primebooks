from django.contrib import admin
from django.contrib.admin import SimpleListFilter
from .models import EFRISCommodityCategory


class CategoryTypeFilter(SimpleListFilter):
    """Filter by category type (Product/Service)"""
    title = 'Category Type'
    parameter_name = 'service_mark'

    def lookups(self, request, model_admin):
        return [
            ('101', 'Product'),
            ('102', 'Service'),
        ]

    def queryset(self, request, queryset):
        if self.value() == '101':
            return queryset.filter(service_mark='101')
        if self.value() == '102':
            return queryset.filter(service_mark='102')
        return queryset


class LeafNodeFilter(SimpleListFilter):
    """Filter by leaf node status"""
    title = 'Leaf Node'
    parameter_name = 'is_leaf_node'

    def lookups(self, request, model_admin):
        return [
            ('101', 'Yes'),
            ('102', 'No'),
        ]

    def queryset(self, request, queryset):
        if self.value() == '101':
            return queryset.filter(is_leaf_node='101')
        if self.value() == '102':
            return queryset.filter(is_leaf_node='102')
        return queryset


class ZeroRateFilter(SimpleListFilter):
    """Filter by zero rate status"""
    title = 'Zero Rate'
    parameter_name = 'is_zero_rate'

    def lookups(self, request, model_admin):
        return [
            ('101', 'Yes'),
            ('102', 'No'),
        ]

    def queryset(self, request, queryset):
        if self.value() == '101':
            return queryset.filter(is_zero_rate='101')
        if self.value() == '102':
            return queryset.filter(is_zero_rate='102')
        return queryset


class ExemptFilter(SimpleListFilter):
    """Filter by exempt status"""
    title = 'Exempt'
    parameter_name = 'is_exempt'

    def lookups(self, request, model_admin):
        return [
            ('101', 'Yes'),
            ('102', 'No'),
        ]

    def queryset(self, request, queryset):
        if self.value() == '101':
            return queryset.filter(is_exempt='101')
        if self.value() == '102':
            return queryset.filter(is_exempt='102')
        return queryset


class StatusFilter(SimpleListFilter):
    """Filter by enable status"""
    title = 'Status'
    parameter_name = 'enable_status_code'

    def lookups(self, request, model_admin):
        return [
            ('1', 'Enabled'),
            ('0', 'Disabled'),
        ]

    def queryset(self, request, queryset):
        if self.value() == '1':
            return queryset.filter(enable_status_code='1')
        if self.value() == '0':
            return queryset.filter(enable_status_code='0')
        return queryset


@admin.register(EFRISCommodityCategory)
class EFRISCommodityCategoryAdmin(admin.ModelAdmin):
    """Admin configuration for EFRIS Commodity Categories"""

    list_display = [
        'commodity_category_code',
        'commodity_category_name',
        'commodity_category_level',
        'parent_code_display',
        'type_display',
        'rate_display',
        'is_leaf_node_display',
        'enable_status_display',
        'last_synced'
    ]

    list_filter = [
        CategoryTypeFilter,
        LeafNodeFilter,
        ZeroRateFilter,
        ExemptFilter,
        StatusFilter,
        'commodity_category_level',
        'last_synced'
    ]

    search_fields = [
        'commodity_category_code',
        'commodity_category_name',
        'parent_code'
    ]

    readonly_fields = [
        'last_synced',
        'type_display'
    ]

    fieldsets = (
        ('Basic Information', {
            'fields': (
                'commodity_category_code',
                'commodity_category_name',
                'parent_code',
                'commodity_category_level',
                'type_display'
            )
        }),
        ('Tax Information', {
            'fields': (
                'rate',
                'service_mark',
                'is_zero_rate',
                'zero_rate_start_date',
                'zero_rate_end_date',
                'is_exempt',
                'exempt_rate_start_date',
                'exempt_rate_end_date',
            )
        }),
        ('Status Information', {
            'fields': (
                'is_leaf_node',
                'enable_status_code',
                'exclusion',
                'last_synced'
            )
        }),
    )

    list_per_page = 50
    list_max_show_all = 1000
    show_full_result_count = True

    def parent_code_display(self, obj):
        """Display parent code with meaningful text"""
        if not obj.parent_code or obj.parent_code == '0':
            return 'Top Level'
        return obj.parent_code

    parent_code_display.short_description = 'Parent'
    parent_code_display.admin_order_field = 'parent_code'

    def type_display(self, obj):
        """Display human-readable type"""
        return obj.type

    type_display.short_description = 'Type'

    def rate_display(self, obj):
        """Display rate with percentage"""
        if obj.rate is not None:
            return f"{obj.rate}%"
        return "N/A"

    rate_display.short_description = 'VAT Rate'
    rate_display.admin_order_field = 'rate'

    def is_leaf_node_display(self, obj):
        """Display leaf node status with icon-like text"""
        return "✓" if obj.is_leaf_node == '101' else "✗"

    is_leaf_node_display.short_description = 'Leaf'
    is_leaf_node_display.admin_order_field = 'is_leaf_node'

    def enable_status_display(self, obj):
        """Display enable status with icon-like text"""
        if obj.enable_status_code == '1':
            return "✅"
        elif obj.enable_status_code == '0':
            return "❌"
        return "?"

    enable_status_display.short_description = 'Status'
    enable_status_display.admin_order_field = 'enable_status_code'

    def get_queryset(self, request):
        """Optimize queryset for admin performance"""
        return super().get_queryset(request).select_related()

    def has_add_permission(self, request):
        """Prevent adding categories from admin (since they're synced)"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Prevent deleting categories from admin (since they're synced)"""
        return False

    def get_readonly_fields(self, request, obj=None):
        """Make most fields readonly since data is synced"""
        if obj:  # editing an existing object
            return [field.name for field in obj._meta.fields] + ['type_display']
        return self.readonly_fields