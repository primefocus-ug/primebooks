from django.contrib import admin
from .models import (
    ServiceCategory, ServiceType, Service, ServicePricingTier,
    ServiceResource, ServicePackage, ServicePackageItem,
    ServiceAppointment, ServiceExecution, ServiceDiscount,
    StaffServiceSkill, ServiceReview
)


class ServicePricingTierInline(admin.TabularInline):
    model = ServicePricingTier
    extra = 1


class ServiceResourceInline(admin.TabularInline):
    model = ServiceResource
    extra = 1
    raw_id_fields = ['product']


@admin.register(ServiceCategory)
class ServiceCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'parent', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'description']


@admin.register(ServiceType)
class ServiceTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'pricing_type', 'is_active', 'created_at']
    list_filter = ['pricing_type', 'is_active']
    search_fields = ['name', 'description']


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = [
        'code', 'name', 'store', 'service_type', 'base_price',
        'is_active', 'requires_appointment'
    ]
    list_filter = [
        'is_active', 'service_type', 'category',
        'requires_appointment', 'is_recurring', 'store'
    ]
    search_fields = ['code', 'name', 'description']
    inlines = [ServicePricingTierInline, ServiceResourceInline]
    raw_id_fields = ['store', 'created_by']
    readonly_fields = ['created_at', 'updated_at']

