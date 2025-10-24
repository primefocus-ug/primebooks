from django.contrib import admin

from .models import Customer, CustomerGroup, CustomerNote


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'customer_type', 'tin', 'is_vat_registered', 'is_active')
    list_filter = ('customer_type', 'is_vat_registered', 'is_active')
    search_fields = ('name', 'tin', 'nin', 'brn', 'phone', 'email')
    fieldsets = (
        ('Basic Information', {
            'fields': ('customer_type', 'name')
        }),
        ('Contact Information', {
            'fields': ('email', 'phone', 'physical_address', 'postal_address', 'district', 'country')
        }),
        ('Tax Information', {
            'fields': ('tin', 'nin', 'brn', 'is_vat_registered')
        }),
        ('Financials', {
            'fields': ('credit_limit',)
        }),
        ('Status', {
            'fields': ('is_active',)
        }),
        ('Dates', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    readonly_fields = ('created_at', 'updated_at')


@admin.register(CustomerGroup)
class CustomerGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'discount_percentage', 'customer_count')
    search_fields = ('name', 'description')
    readonly_fields = ('created_at', 'updated_at', 'customer_count')

    def customer_count(self, obj):
        return obj.customers.count()
    customer_count.short_description = 'Customers'


@admin.register(CustomerNote)
class CustomerNoteAdmin(admin.ModelAdmin):
    list_display = ('customer', 'author', 'created_at', 'updated_at')
    search_fields = ('customer__name', 'author__email', 'note')
    readonly_fields = ('created_at', 'updated_at')
