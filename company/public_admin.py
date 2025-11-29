from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from public_accounts.admin_site import public_admin, PublicModelAdmin
from company.models import SubscriptionPlan,Company,EFRISCommodityCategory,TenantEmailSettings,TenantInvoiceSettings,Domain

class SubscriptionPlanAdmin(PublicModelAdmin):
    """Admin interface for SubscriptionPlan"""

    list_display = [
        'name', 'display_name', 'price', 'billing_cycle',
        'max_users', 'max_branches', 'is_active', 'is_popular'
    ]
    list_filter = ['name', 'billing_cycle', 'is_active', 'is_popular', 'support_level']
    search_fields = ['name', 'display_name', 'description']
    ordering = ['sort_order', 'price']
    readonly_fields = ['created_at', 'updated_at', 'monthly_price']

    fieldsets = (
        (_('Plan Information'), {
            'fields': ('name', 'display_name', 'description', 'is_active', 'is_popular', 'sort_order')
        }),
        (_('Pricing'), {
            'fields': ('price', 'setup_fee', 'billing_cycle', 'trial_days', 'monthly_price')
        }),
        (_('Limits'), {
            'fields': (
                'max_users', 'max_branches', 'max_storage_gb',
                'max_api_calls_per_month', 'max_transactions_per_month'
            )
        }),
        (_('Features'), {
            'fields': (
                'can_use_api', 'can_export_data', 'can_use_integrations',
                'can_use_advanced_reports', 'can_use_multi_currency',
                'can_use_custom_branding', 'features'
            )
        }),
        (_('Support'), {
            'fields': ('support_level',)
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def monthly_price(self, obj):
        """Display monthly equivalent price"""
        return f"${obj.monthly_price:.2f}/month"
    monthly_price.short_description = _('Monthly Price')


class CompanyAdmin(PublicModelAdmin):
    """Admin interface for Company (Tenant)"""

    list_display = [
        'company_id', 'display_name', 'status', 'plan',
        'get_access_status', 'get_efris_status', 'is_active', 'created_at'
    ]
    list_filter = [
        'status', 'is_trial', 'is_active', 'efris_enabled',
        'efris_is_active', 'plan__name', 'preferred_currency'
    ]
    search_fields = [
        'company_id', 'name', 'trading_name', 'slug',
        'email', 'tin', 'brn', 'nin'
    ]
    ordering = ['-created_at']
    readonly_fields = [
        'company_id', 'schema_name', 'created_at', 'updated_at',
        'last_activity_at', 'efris_last_sync', 'storage_usage_percentage',
        'branches_count', 'days_until_expiry'
    ]

    fieldsets = (
        (_('Company Identification'), {
            'fields': ('company_id', 'schema_name', 'slug', 'plan', 'status', 'is_active')
        }),
        (_('Company Details'), {
            'fields': ('name', 'trading_name', 'description')
        }),
        (_('Contact Information'), {
            'fields': (
                'physical_address', 'postal_address', 'phone',
                'email', 'website'
            )
        }),
        (_('Tax Information'), {
            'fields': (
                'tin', 'brn', 'nin', 'is_vat_enabled',
                'vat_registration_date', 'preferred_currency'
            )
        }),
        (_('Subscription & Billing'), {
            'fields': (
                'is_trial', 'trial_ends_at', 'subscription_starts_at',
                'subscription_ends_at', 'grace_period_ends_at',
                'last_payment_date', 'next_billing_date',
                'payment_method', 'billing_email'
            )
        }),
        (_('EFRIS Configuration'), {
            'fields': (
                'efris_enabled', 'efris_is_production', 'efris_integration_mode',
                'efris_client_id', 'efris_api_key', 'efris_device_number',
                'efris_certificate_data', 'efris_auto_fiscalize_sales',
                'efris_auto_sync_products'
            ),
            'classes': ('collapse',)
        }),
        (_('EFRIS Status'), {
            'fields': (
                'efris_is_active', 'efris_is_registered',
                'efris_last_sync', 'certificate_status'
            ),
            'classes': ('collapse',)
        }),
        (_('Localization'), {
            'fields': ('time_zone', 'locale', 'date_format', 'time_format'),
            'classes': ('collapse',)
        }),
        (_('Branding'), {
            'fields': ('logo', 'favicon', 'brand_colors'),
            'classes': ('collapse',)
        }),
        (_('Security'), {
            'fields': (
                'is_verified', 'verification_token',
                'two_factor_required', 'ip_whitelist'
            ),
            'classes': ('collapse',)
        }),
        (_('Usage & Activity'), {
            'fields': (
                'storage_used_mb', 'storage_usage_percentage',
                'api_calls_this_month', 'branches_count',
                'last_activity_at'
            ),
            'classes': ('collapse',)
        }),
        (_('Admin Notes'), {
            'fields': ('notes', 'tags'),
            'classes': ('collapse',)
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at', 'created_on'),
            'classes': ('collapse',)
        }),
    )

    def get_access_status(self, obj):
        """Display access status with color coding"""
        status = obj.access_status_display
        colors = {
            'ACTIVE': 'green',
            'TRIAL': 'orange',
            'SUSPENDED': 'red',
            'EXPIRED': 'darkred'
        }
        color = colors.get(obj.status, 'gray')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color, status
        )
    get_access_status.short_description = _('Access Status')

    def get_efris_status(self, obj):
        """Display EFRIS status"""
        if not obj.efris_enabled:
            return format_html('<span style="color: gray;">Disabled</span>')
        elif obj.efris_is_active:
            return format_html('<span style="color: green;">✓ Active</span>')
        else:
            return format_html('<span style="color: orange;">Enabled (Inactive)</span>')
    get_efris_status.short_description = _('EFRIS Status')

    def storage_usage_percentage(self, obj):
        """Display storage usage percentage"""
        percentage = obj.storage_usage_percentage
        color = 'green' if percentage < 70 else 'orange' if percentage < 90 else 'red'
        return format_html(
            '<span style="color: {};">{:.1f}%</span>',
            color, percentage
        )
    storage_usage_percentage.short_description = _('Storage Usage')

    def branches_count(self, obj):
        """Display branch count"""
        count = obj.branches_count
        max_branches = obj.plan.max_branches if obj.plan else 0
        return f"{count}/{max_branches}"
    branches_count.short_description = _('Branches')

    def days_until_expiry(self, obj):
        """Display days until expiry"""
        days = obj.days_until_expiry
        if days < 0:
            return format_html('<span style="color: red;">Expired</span>')
        elif days < 7:
            return format_html('<span style="color: orange;">{} days</span>', days)
        return f"{days} days"
    days_until_expiry.short_description = _('Days Until Expiry')


class DomainAdmin(PublicModelAdmin):
    """Admin interface for Domain"""

    list_display = [
        'domain', 'tenant', 'is_primary', 'ssl_enabled',
        'redirect_to_primary', 'created_at'
    ]
    list_filter = ['is_primary', 'ssl_enabled', 'redirect_to_primary']
    search_fields = ['domain', 'tenant__name', 'tenant__company_id']
    ordering = ['-created_at']
    readonly_fields = ['created_at']

    fieldsets = (
        (_('Domain Information'), {
            'fields': ('domain', 'tenant', 'is_primary')
        }),
        (_('Configuration'), {
            'fields': ('ssl_enabled', 'redirect_to_primary')
        }),
        (_('Timestamps'), {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )


class TenantEmailSettingsAdmin(PublicModelAdmin):
    """Admin interface for TenantEmailSettings"""

    list_display = [
        'company', 'from_email', 'smtp_host', 'smtp_port',
        'is_active', 'is_verified', 'last_tested_at'
    ]
    list_filter = ['is_active', 'is_verified', 'use_tls', 'use_ssl']
    search_fields = ['company__name', 'from_email', 'smtp_host']
    ordering = ['-updated_at']
    readonly_fields = [
        'created_at', 'updated_at', 'last_tested_at', 'test_result'
    ]

    fieldsets = (
        (_('Company'), {
            'fields': ('company',)
        }),
        (_('SMTP Configuration'), {
            'fields': ('smtp_host', 'smtp_port', 'smtp_username', 'smtp_password')
        }),
        (_('Security Settings'), {
            'fields': ('use_tls', 'use_ssl', 'timeout')
        }),
        (_('Email Settings'), {
            'fields': ('from_email', 'from_name', 'reply_to_email')
        }),
        (_('Status'), {
            'fields': ('is_active', 'is_verified', 'test_result', 'last_tested_at')
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


class TenantInvoiceSettingsAdmin(PublicModelAdmin):
    """Admin interface for TenantInvoiceSettings"""

    list_display = [
        'company', 'invoice_prefix', 'invoice_template',
        'default_tax_rate', 'enable_efris', 'send_invoice_email'
    ]
    list_filter = ['invoice_template', 'send_invoice_email', 'enable_efris']
    search_fields = ['company__name', 'invoice_prefix', 'efris_tin']
    ordering = ['-updated_at']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        (_('Company'), {
            'fields': ('company',)
        }),
        (_('Invoice Numbering'), {
            'fields': (
                'invoice_prefix', 'invoice_number_start',
                'invoice_number_padding'
            )
        }),
        (_('Invoice Terms'), {
            'fields': (
                'default_payment_terms_days', 'invoice_notes',
                'invoice_terms'
            )
        }),
        (_('Invoice Design'), {
            'fields': ('show_company_logo', 'invoice_template')
        }),
        (_('Tax Settings'), {
            'fields': ('default_tax_rate', 'tax_name')
        }),
        (_('Email Settings'), {
            'fields': (
                'send_invoice_email', 'invoice_email_subject',
                'invoice_email_body'
            )
        }),
        (_('EFRIS Integration'), {
            'fields': (
                'enable_efris', 'efris_tin', 'efris_device_no',
                'efris_private_key'
            ),
            'classes': ('collapse',)
        }),
        (_('Timestamps'), {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


class EFRISCommodityCategoryAdmin(PublicModelAdmin):
    """Admin interface for EFRISCommodityCategory"""

    list_display = [
        'commodity_category_code', 'commodity_category_name',
        'type', 'rate', 'is_leaf_node', 'enable_status_code'
    ]
    list_filter = [
        'service_mark', 'is_leaf_node', 'is_zero_rate',
        'is_exempt', 'enable_status_code'
    ]
    search_fields = [
        'commodity_category_code', 'commodity_category_name',
        'parent_code'
    ]
    ordering = ['commodity_category_code']
    readonly_fields = ['last_synced']

    fieldsets = (
        (_('Category Information'), {
            'fields': (
                'commodity_category_code', 'parent_code',
                'commodity_category_name', 'commodity_category_level'
            )
        }),
        (_('Classification'), {
            'fields': ('service_mark', 'is_leaf_node', 'enable_status_code', 'exclusion')
        }),
        (_('Tax Information'), {
            'fields': (
                'rate', 'is_zero_rate', 'zero_rate_start_date',
                'zero_rate_end_date', 'is_exempt',
                'exempt_rate_start_date', 'exempt_rate_end_date'
            )
        }),
        (_('Sync Information'), {
            'fields': ('last_synced',),
            'classes': ('collapse',)
        }),
    )

    def type(self, obj):
        """Display category type"""
        return obj.type
    type.short_description = _('Type')


# Register models with public admin
public_admin.register(SubscriptionPlan, SubscriptionPlanAdmin, app_label='company')
public_admin.register(Company, CompanyAdmin, app_label='company')
public_admin.register(Domain, DomainAdmin, app_label='company')
public_admin.register(TenantEmailSettings, TenantEmailSettingsAdmin, app_label='company')
public_admin.register(TenantInvoiceSettings, TenantInvoiceSettingsAdmin, app_label='company')
public_admin.register(EFRISCommodityCategory, EFRISCommodityCategoryAdmin, app_label='company')