from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from django.utils.html import format_html
from django.contrib.admin import SimpleListFilter
from django.utils import timezone
from accounts.models import CustomUser
import logging


from .models import Company,TenantEmailSettings,TenantInvoiceSettings, Domain, EFRISCommodityCategory

logger = logging.getLogger(__name__)

admin.site.register(TenantInvoiceSettings)
admin.site.register(TenantEmailSettings)
@admin.register(EFRISCommodityCategory)
class EFRISCommodityCategoryAdmin(admin.ModelAdmin):
    list_display = (
        'commodity_category_code',
        'commodity_category_name',
        'parent_code',
        'commodity_category_level',
        'type',  # human-readable Product/Service
        'rate',
        'is_leaf_node',
        'is_zero_rate',
        'zero_rate_start_date',
        'zero_rate_end_date',
        'is_exempt',
        'exempt_rate_start_date',
        'exempt_rate_end_date',
        'enable_status_code',
        'exclusion',
        'last_synced',
    )
    search_fields = (
        'commodity_category_code',
        'commodity_category_name',
        'parent_code',
    )
    list_filter = (
        'is_exempt',
        'is_leaf_node',
        'is_zero_rate',
        'service_mark',  # Product/Service
        'enable_status_code',
    )
    ordering = ('commodity_category_code',)
    readonly_fields = ('last_synced',)


@admin.register(Domain)
class DomainAdmin(TenantAdminMixin,admin.ModelAdmin):
    list_display = ('domain', 'tenant', 'is_primary')
    search_fields = ('domain', 'tenant__name')
    list_filter = ('is_primary',)


class CompanyStatusFilter(SimpleListFilter):
    title = 'Access Status'
    parameter_name = 'access_status'

    def lookups(self, request, model_admin):
        return (
            ('active', 'Active Access'),
            ('trial', 'Trial'),
            ('expired', 'Expired'),
            ('suspended', 'Suspended'),
            ('grace', 'Grace Period'),
            ('archived', 'Archived'),
        )

    def queryset(self, request, queryset):
        today = timezone.now().date()
        if self.value() == 'active':
            return queryset.filter(is_active=True, status='ACTIVE')
        elif self.value() == 'trial':
            return queryset.filter(is_active=True, status='TRIAL')
        elif self.value() == 'expired':
            return queryset.filter(status='EXPIRED')
        elif self.value() == 'suspended':
            return queryset.filter(status='SUSPENDED')
        elif self.value() == 'grace':
            return queryset.filter(
                status='SUSPENDED',
                grace_period_ends_at__gte=today
            )
        elif self.value() == 'archived':
            return queryset.filter(status='ARCHIVED')
        return queryset

@admin.register(Company)
class CompanyAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = [
        'company_id', 'display_name', 'status_badge', 'access_status_display',
        'plan', 'subscription_ends_at', 'grace_period_ends_at', 'users_count',
        'branches_count_display', 'efris_status_display', 'last_activity_at'
    ]
    list_filter = [
        CompanyStatusFilter, 'status', 'plan', 'is_trial', 'efris_enabled',
        'efris_is_active', 'created_at'
    ]
    search_fields = ['company_id', 'name', 'trading_name', 'email', 'tin']
    readonly_fields = [
        'company_id', 'schema_name', 'created_at', 'updated_at',
        'access_status_display', 'users_count', 'branches_count_display',
        'efris_status_display', 'storage_usage_percentage'
    ]

    fieldsets = (
        ('Company Information', {
            'fields': (
                'company_id', 'name', 'trading_name', 'slug', 'description',
                'email', 'phone', 'website', 'physical_address', 'postal_address'
            )
        }),
        ('Tax Information', {
            'fields': (
                'tin', 'brn', 'nin', 'vat_registration_number',
                'vat_registration_date', 'preferred_currency'
            )
        }),
        ('Subscription', {
            'fields': (
                'plan', 'status', 'is_active', 'is_trial', 'trial_ends_at',
                'subscription_starts_at', 'subscription_ends_at',
                'grace_period_ends_at', 'last_payment_date', 'next_billing_date',
                'billing_email'
            )
        }),
        ('EFRIS Integration', {
            'fields': (
                'efris_enabled', 'efris_is_production', 'efris_integration_mode',
                'efris_client_id', 'efris_api_key', 'efris_device_number',
                'efris_certificate_data', 'efris_auto_fiscalize_sales',
                'efris_auto_sync_products', 'efris_is_active',
                'efris_is_registered', 'efris_last_sync', 'efris_status_display'
            ),
            'classes': ('collapse',)
        }),
        ('Status & Usage', {
            'fields': (
                'access_status_display', 'users_count', 'branches_count_display',
                'storage_used_mb', 'storage_usage_percentage',
                'api_calls_this_month', 'last_activity_at'
            ),
            'classes': ('collapse',)
        }),
        ('Branding & Localization', {
            'fields': (
                'logo', 'favicon', 'brand_colors', 'time_zone', 'locale',
                'date_format', 'time_format'
            ),
            'classes': ('collapse',)
        }),
        ('Security', {
            'fields': ('is_verified', 'verification_token', 'two_factor_required', 'ip_whitelist'),
            'classes': ('collapse',)
        }),
        ('System', {
            'fields': ('schema_name', 'created_at', 'updated_at', 'tags'),
            'classes': ('collapse',)
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        })
    )

    actions = [
        'suspend_companies', 'reactivate_companies', 'reallow_companies',
        'check_access_status', 'extend_grace_period', 'enable_efris',
        'disable_efris'
    ]

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)

        # Explicitly make optional fields not required
        optional_fields = [
            'brand_colors',
            'logo',
            'favicon',
            'description',
            'website',
            'postal_address',
            'ip_whitelist',
            'tags',
            'brn',
            'nin',
            'vat_registration_number',
            'efris_certificate_data',
        ]

        for field in optional_fields:
            if field in form.base_fields:
                form.base_fields[field].required = False

        return form

    def status_badge(self, obj):
        colors = {
            'ACTIVE': 'green',
            'TRIAL': 'blue',
            'SUSPENDED': 'orange',
            'EXPIRED': 'red',
            'ARCHIVED': 'gray'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, obj.get_status_display()
        )

    status_badge.short_description = 'Status'

    def users_count(self, obj):
        count = CustomUser.objects.filter(company=obj).count()
        max_users = obj.plan.max_users if obj.plan else 0
        if max_users:
            percentage = (count / max_users) * 100
            color = 'red' if percentage > 80 else 'orange' if percentage > 60 else 'green'
            return format_html(
                '<span style="color: {};">{}/{}</span>',
                color, count, max_users
            )
        return count

    users_count.short_description = 'Users'

    def branches_count_display(self, obj):
        count = obj.branches_count
        max_branches = obj.plan.max_branches if obj.plan else 0
        if max_branches:
            percentage = (count / max_branches) * 100
            color = 'red' if percentage > 80 else 'orange' if percentage > 60 else 'green'
            return format_html(
                '<span style="color: {};">{}/{}</span>',
                color, count, max_branches
            )
        return count

    branches_count_display.short_description = 'Branches'

    def suspend_companies(self, request, queryset):
        count = 0
        for company in queryset:
            if company.is_active:
                company.suspend_for_misbehavior(
                    "Suspended via admin action",
                    suspended_by=request.user
                )
                count += 1
        self.message_user(request, f"Suspended {count} companies.")
        logger.warning(f"Admin {request.user} suspended {count} companies via bulk action")

    suspend_companies.short_description = "Suspend selected companies"

    def reactivate_companies(self, request, queryset):
        count = 0
        for company in queryset:
            if not company.is_active:
                company.reactivate_company("Reactivated via admin action")
                count += 1
        self.message_user(request, f"Reactivated {count} companies.")
        logger.info(f"Admin {request.user} reactivated {count} companies via bulk action")

    reactivate_companies.short_description = "Reactivate selected companies"

    def reallow_companies(self, request, queryset):
        count = 0
        for company in queryset:
            if not company.is_active or company.status in ['SUSPENDED', 'EXPIRED']:
                company.reallow_company(
                    reason="Reallowed via admin action",
                    days=30,
                    grace_days=7
                )
                count += 1
        self.message_user(request, f"Reallowed {count} companies with new subscription.")
        logger.info(f"Admin {request.user} reallowed {count} companies via bulk action")

    reallow_companies.short_description = "Reallow selected companies with 30-day subscription"

    def check_access_status(self, request, queryset):
        updated_count = 0
        for company in queryset:
            if company.check_and_update_access_status():
                updated_count += 1
        self.message_user(request, f"Checked {queryset.count()} companies, updated {updated_count}.")
        logger.info(f"Admin {request.user} checked access status for {queryset.count()} companies, updated {updated_count}")

    check_access_status.short_description = "Check and update access status"

    def extend_grace_period(self, request, queryset):
        count = 0
        for company in queryset:
            if company.status in ['SUSPENDED', 'EXPIRED']:
                company.extend_grace_period(days=7)
                count += 1
        self.message_user(request, f"Extended grace period for {count} companies by 7 days.")
        logger.info(f"Admin {request.user} extended grace period for {count} companies")

    extend_grace_period.short_description = "Extend grace period by 7 days"

    def enable_efris(self, request, queryset):
        count = 0
        for company in queryset:
            try:
                if not company.efris_enabled:
                    company.enable_efris(validate=True)
                    count += 1
            except ValueError as e:
                self.message_user(request, f"Failed to enable EFRIS for {company.display_name}: {str(e)}", level='error')
        self.message_user(request, f"Enabled EFRIS for {count} companies.")
        logger.info(f"Admin {request.user} enabled EFRIS for {count} companies")

    enable_efris.short_description = "Enable EFRIS integration"

    def disable_efris(self, request, queryset):
        count = 0
        for company in queryset:
            if company.efris_enabled:
                company.disable_efris("Disabled via admin action")
                count += 1
        self.message_user(request, f"Disabled EFRIS for {count} companies.")
        logger.info(f"Admin {request.user} disabled EFRIS for {count} companies")

    disable_efris.short_description = "Disable EFRIS integration"

    def get_readonly_fields(self, request, obj=None):
        # Allow editing schema_name for new objects
        if obj is None:
            return [f for f in self.readonly_fields if f != 'schema_name']
        return self.readonly_fields