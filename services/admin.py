# from django.contrib import admin
# from .models import (
#     ServiceCategory, ServiceType, Service, ServicePricingTier,
#     ServiceResource, ServicePackage, ServicePackageItem,
#     ServiceAppointment, ServiceExecution, ServiceDiscount,
#     StaffServiceSkill, ServiceReview
# )
#
#
# class ServicePricingTierInline(admin.TabularInline):
#     model = ServicePricingTier
#     extra = 1
#
#
# class ServiceResourceInline(admin.TabularInline):
#     model = ServiceResource
#     extra = 1
#     raw_id_fields = ['product']
#
#
# @admin.register(ServiceCategory)
# class ServiceCategoryAdmin(admin.ModelAdmin):
#     list_display = ['name', 'parent', 'is_active', 'created_at']
#     list_filter = ['is_active', 'created_at']
#     search_fields = ['name', 'description']
#
#
# @admin.register(ServiceType)
# class ServiceTypeAdmin(admin.ModelAdmin):
#     list_display = ['name', 'pricing_type', 'is_active', 'created_at']
#     list_filter = ['pricing_type', 'is_active']
#     search_fields = ['name', 'description']
#
#
# @admin.register(Service)
# class ServiceAdmin(admin.ModelAdmin):
#     list_display = ['code', 'name', 'service_type', 'base_price', 'is_active', 'requires_appointment']
#     list_filter = ['is_active', 'service_type', 'category', 'requires_appointment', 'is_recurring']
#     search_fields = ['code', 'name', 'description']
#     inlines = [ServicePricingTierInline, ServiceResourceInline]
#     readonly_fields = ['created_at', 'updated_at']
#     fieldsets = (
#         ('Basic Information', {
#             'fields': ('name', 'code', 'description', 'category', 'service_type', 'image')
#         }),
#         ('Pricing', {
#             'fields': ('base_price', 'cost_price', 'hourly_rate', 'tax_rate', 'is_tax_inclusive')
#         }),
#         ('Scheduling', {
#             'fields': ('default_duration', 'requires_appointment', 'allow_online_booking', 'max_advance_booking_days')
#         }),
#         ('Recurrence', {
#             'fields': ('is_recurring', 'recurrence_interval'),
#             'classes': ('collapse',)
#         }),
#         ('Staff & Resources', {
#             'fields': ('requires_staff', 'staff_commission_rate', 'consumes_inventory')
#         }),
#         ('Status & Metadata', {
#             'fields': ('is_active', 'is_featured', 'available_online', 'tags', 'sort_order', 'created_by')
#         }),
#         ('Timestamps', {
#             'fields': ('created_at', 'updated_at'),
#             'classes': ('collapse',)
#         }),
#     )
#
#
# class ServicePackageItemInline(admin.TabularInline):
#     model = ServicePackageItem
#     extra = 1
#
#
# @admin.register(ServicePackage)
# class ServicePackageAdmin(admin.ModelAdmin):
#     list_display = ['code', 'name', 'price', 'discount_percentage', 'is_active']
#     list_filter = ['is_active', 'created_at']
#     search_fields = ['code', 'name', 'description']
#     inlines = [ServicePackageItemInline]
#
#
# @admin.register(ServiceAppointment)
# class ServiceAppointmentAdmin(admin.ModelAdmin):
#     list_display = ['appointment_number', 'service', 'customer_name', 'scheduled_date', 'scheduled_time', 'status',
#                     'assigned_staff']
#     list_filter = ['status', 'scheduled_date', 'assigned_staff']
#     search_fields = ['appointment_number', 'customer_name', 'customer_email', 'customer_phone']
#     readonly_fields = ['appointment_number', 'created_at', 'updated_at']
#     date_hierarchy = 'scheduled_date'
#
#
# @admin.register(ServiceExecution)
# class ServiceExecutionAdmin(admin.ModelAdmin):
#     list_display = ['execution_number', 'service', 'performed_by', 'start_time', 'status', 'quality_rating']
#     list_filter = ['status', 'start_time', 'performed_by', 'quality_rating']
#     search_fields = ['execution_number', 'work_description']
#     readonly_fields = ['execution_number', 'actual_duration_minutes', 'created_at', 'updated_at']
#     date_hierarchy = 'start_time'
#
#
# @admin.register(ServiceDiscount)
# class ServiceDiscountAdmin(admin.ModelAdmin):
#     list_display = ['code', 'name', 'discount_type', 'value', 'start_date', 'end_date', 'is_active', 'uses_count']
#     list_filter = ['discount_type', 'is_active', 'start_date', 'end_date']
#     search_fields = ['code', 'name']
#     filter_horizontal = ['services', 'categories']
#
#
# @admin.register(StaffServiceSkill)
# class StaffServiceSkillAdmin(admin.ModelAdmin):
#     list_display = ['staff', 'service', 'proficiency_level', 'certification_number', 'certification_expiry',
#                     'is_active']
#     list_filter = ['proficiency_level', 'is_active', 'certification_expiry']
#     search_fields = ['staff__username', 'staff__first_name', 'staff__last_name', 'service__name',
#                      'certification_number']
#
#
# @admin.register(ServiceReview)
# class ServiceReviewAdmin(admin.ModelAdmin):
#     list_display = ['service', 'customer_name', 'rating', 'staff_rating', 'is_verified', 'is_published', 'created_at']
#     list_filter = ['rating', 'is_verified', 'is_published', 'created_at']
#     search_fields = ['customer_name', 'review_text', 'service__name']
#     readonly_fields = ['helpful_count', 'created_at', 'updated_at']
#
