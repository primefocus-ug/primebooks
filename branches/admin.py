from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import CompanyBranch

# Register your models here.
class CompanyBranchInline(admin.TabularInline):
    model = CompanyBranch
    extra = 0
    fields = ('name', 'location',  'is_active', 'is_main_branch')
    readonly_fields = ('created_at', 'updated_at')
    show_change_link = True


@admin.register(CompanyBranch)
class CompanyBranchAdmin(admin.ModelAdmin):
    list_display = ('name', 'company', 'location',  'is_active', 'is_main_branch')
    list_filter = ('is_active', 'is_main_branch', 'company')
    search_fields = ('name', 'location', 'tin', 'company__name')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('company',)

    fieldsets = (
        (_('Basic Information'), {
            'fields': ('company', 'name', 'code', 'location')
        }),
        (_('Contact Information'), {
            'fields': ('phone', 'email')
        }),
        (_('Tax Information'), {
            'fields': ('tin', 'efris_device_number')
        }),
        (_('Status'), {
            'fields': ('is_active', 'is_main_branch')
        }),
        (_('Metadata'), {
            'fields': ('created_at', 'updated_at')
        }),
    )

