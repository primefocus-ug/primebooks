from django.contrib import admin
from .models import Expense, Budget


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['description', 'amount', 'user', 'date', 'payment_method', 'is_recurring', 'created_at']
    list_filter = ['date', 'payment_method', 'is_recurring', 'is_important', 'tags']
    search_fields = ['description', 'notes', 'user__username']
    date_hierarchy = 'date'
    readonly_fields = ['id', 'created_at', 'updated_at']

    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'user', 'amount', 'description', 'date')
        }),
        ('Organization', {
            'fields': ('tags', 'payment_method')
        }),
        ('Attachments', {
            'fields': ('receipt',)
        }),
        ('Additional Details', {
            'fields': ('notes', 'is_recurring', 'is_important')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ['name', 'user', 'amount', 'period', 'alert_threshold', 'is_active', 'created_at']
    list_filter = ['period', 'is_active', 'tags']
    search_fields = ['name', 'user__username']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'name', 'amount', 'period')
        }),
        ('Filters', {
            'fields': ('tags',)
        }),
        ('Alert Settings', {
            'fields': ('alert_threshold', 'is_active')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )