from django.shortcuts import redirect, get_object_or_404
from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from public_accounts.admin_site import public_admin, PublicModelAdmin
from company.models import SubscriptionPlan,Company,EFRISCommodityCategory,TenantEmailSettings,TenantInvoiceSettings,Domain
from django.shortcuts import redirect, get_object_or_404
from django.contrib import messages
from django.utils.html import format_html
from django.urls import reverse
import logging
from .models import Company

logger = logging.getLogger(__name__)

from django import forms
from datetime import timedelta


class CompanyAdminForm(forms.ModelForm):
    """Custom form for Company admin with validation"""

    class Meta:
        model = Company
        fields = '__all__'

    def clean(self):
        cleaned_data = super().clean()
        is_trial = cleaned_data.get('is_trial')
        subscription_starts_at = cleaned_data.get('subscription_starts_at')
        subscription_ends_at = cleaned_data.get('subscription_ends_at')

        # If converting from trial to paid, ensure dates are set
        if not is_trial and self.instance.pk:
            try:
                old_instance = Company.objects.get(pk=self.instance.pk)

                # Converting from trial to paid
                if old_instance.is_trial and not is_trial:
                    # Auto-set subscription dates if not provided
                    if not subscription_starts_at:
                        cleaned_data['subscription_starts_at'] = timezone.now().date()
                        self.add_error(
                            None,
                            forms.ValidationError(
                                'Converting from trial to paid subscription. '
                                'Subscription start date auto-set to today. '
                                'Please set subscription end date.',
                                code='trial_conversion'
                            )
                        )

                    if not subscription_ends_at:
                        # Suggest a default end date
                        start_date = subscription_starts_at or timezone.now().date()
                        suggested_end = start_date + timedelta(days=30)
                        self.add_error(
                            'subscription_ends_at',
                            forms.ValidationError(
                                f'Please set subscription end date. Suggested: {suggested_end}',
                                code='missing_end_date'
                            )
                        )
            except Company.DoesNotExist:
                pass

        # If not trial, ensure subscription end date is set
        if not is_trial and not subscription_ends_at:
            self.add_error(
                'subscription_ends_at',
                forms.ValidationError(
                    'Subscription end date is required for paid subscriptions.',
                    code='missing_subscription_end'
                )
            )

        return cleaned_data

class CompanyAdmin(PublicModelAdmin):
    """Admin interface for Company (Tenant)"""
    form_class = CompanyAdminForm
    # Add custom actions to the class
    actions = [
        'reactivate_companies',
        'suspend_companies',
        'enable_efris_bulk',
        'disable_efris_bulk',
        'extend_trial',
        'force_status_refresh',
    ]

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
        ('Company Identification', {
            'fields': ('company_id', 'schema_name', 'slug', 'plan', 'status', 'is_active')
        }),
        ('Company Details', {
            'fields': ('name', 'trading_name', 'description')
        }),
        ('Contact Information', {
            'fields': (
                'physical_address', 'postal_address', 'phone',
                'email', 'website'
            )
        }),
        ('Tax Information', {
            'fields': (
                'tin', 'brn', 'nin', 'is_vat_enabled',
                'preferred_currency'
            )
        }),
        ('Subscription & Billing', {
            'fields': (
                'is_trial', 'trial_ends_at', 'subscription_starts_at',
                'subscription_ends_at', 'grace_period_ends_at',
                'last_payment_date', 'next_billing_date',
                'payment_method', 'billing_email'
            )
        }),
        ('EFRIS Configuration', {
            'fields': (
                'efris_enabled', 'efris_is_production', 'efris_integration_mode',
                'efris_device_number', 'efris_certificate_data',
                'efris_auto_fiscalize_sales', 'efris_auto_sync_products'
            ),
            'classes': ('collapse',)
        }),
        ('EFRIS Status', {
            'fields': (
                'efris_is_active', 'efris_is_registered',
                'efris_last_sync', 'certificate_status'
            ),
            'classes': ('collapse',)
        }),
        ('Localization', {
            'fields': ('time_zone', 'locale', 'date_format', 'time_format'),
            'classes': ('collapse',)
        }),
        ('Branding', {
            'fields': ('logo', 'favicon', 'brand_colors'),
            'classes': ('collapse',)
        }),
        ('Security', {
            'fields': (
                'is_verified', 'verification_token',
                'two_factor_required', 'ip_whitelist'
            ),
            'classes': ('collapse',)
        }),
        ('Usage & Activity', {
            'fields': (
                'storage_used_mb', 'storage_usage_percentage',
                'api_calls_this_month', 'branches_count',
                'last_activity_at'
            ),
            'classes': ('collapse',)
        }),
        ('Admin Notes', {
            'fields': ('notes', 'tags'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'created_on'),
            'classes': ('collapse',)
        }),
    )

    def get_urls(self):
        """Add custom URLs for admin actions"""
        from django.urls import path

        # Get app_label and model_name
        app_label, model_name_lower = self.get_url_params()

        # Custom URL patterns with FULL namespace
        custom_urls = [
            path(
                f'{app_label}/{model_name_lower}/<path:pk>/reactivate/',
                self.admin_site.admin_view(self.reactivate_company_view),
                name=f'public_admin_{app_label}_{model_name_lower}_reactivate',
            ),
            path(
                f'{app_label}/{model_name_lower}/<path:pk>/suspend/',
                self.admin_site.admin_view(self.suspend_company_view),
                name=f'public_admin_{app_label}_{model_name_lower}_suspend',
            ),
            path(
                f'{app_label}/{model_name_lower}/<path:pk>/reactivate-users/',
                self.admin_site.admin_view(self.reactivate_all_users_view),
                name=f'public_admin_{app_label}_{model_name_lower}_reactivate_users',
            ),
            path(
                f'{app_label}/{model_name_lower}/<path:pk>/enable-efris/',
                self.admin_site.admin_view(self.enable_efris_view),
                name=f'public_admin_{app_label}_{model_name_lower}_enable_efris',
            ),
            path(
                f'{app_label}/{model_name_lower}/<path:pk>/disable-efris/',
                self.admin_site.admin_view(self.disable_efris_view),
                name=f'public_admin_{app_label}_{model_name_lower}_disable_efris',
            ),
            path(
                f'{app_label}/{model_name_lower}/<path:pk>/force-status-refresh/',
                self.admin_site.admin_view(self.force_status_refresh_view),
                name=f'public_admin_{app_label}_{model_name_lower}_force_status_refresh',
            ),
            path(
                f'{app_label}/{model_name_lower}/<path:pk>/extend-trial/',
                self.admin_site.admin_view(self.extend_trial_view),
                name=f'public_admin_{app_label}_{model_name_lower}_extend_trial',
            ),
        ]

        # Get base URLs from parent class
        base_urls = super().get_urls() if hasattr(super(), 'get_urls') else []

        return custom_urls + base_urls

    def change_view(self, request, pk):
        """Override change_view to add custom context"""
        response = super().change_view(request, pk)

        # If it's a TemplateResponse, add extra context
        if hasattr(response, 'context_data'):
            obj = response.context_data.get('object')
            if obj and isinstance(obj, Company):  # Check if it's a Company object
                app_label, model_name_lower = self.get_url_params()

                # Build custom URLs for the template
                response.context_data['custom_action_urls'] = {
                    'reactivate_company': reverse(f'public_admin:{app_label}_{model_name_lower}_reactivate', args=[pk]),
                    'suspend_company': reverse(f'public_admin:{app_label}_{model_name_lower}_suspend', args=[pk]),
                    'reactivate_all_users': reverse(f'public_admin:{app_label}_{model_name_lower}_reactivate_users',
                                                    args=[pk]),
                    'enable_efris': reverse(f'public_admin:{app_label}_{model_name_lower}_enable_efris', args=[pk]),
                    'disable_efris': reverse(f'public_admin:{app_label}_{model_name_lower}_disable_efris', args=[pk]),
                    'force_status_refresh': reverse(f'public_admin:{app_label}_{model_name_lower}_force_status_refresh',
                                                    args=[pk]),
                    'extend_trial': reverse(f'public_admin:{app_label}_{model_name_lower}_extend_trial', args=[pk]),
                }

                # The object is already in context as 'object'
                # You can also add it as 'original' for clarity
                response.context_data['original'] = obj

        return response

    def reactivate_company_view(self, request, pk):
        """View to reactivate company"""
        company = get_object_or_404(self.model, pk=pk)

        try:
            company.reactivate_company(reason=f"Reactivated by admin {request.user.email}")
            messages.success(request, f'Company "{company.display_name}" has been reactivated.')
            logger.info(f"Admin {request.user.email} reactivated company {company.company_id}")
        except Exception as e:
            messages.error(request, f'Error reactivating company: {str(e)}')
            logger.error(f"Error reactivating company {company.company_id}: {str(e)}")

        app_label, model_name_lower = self.get_url_params()
        return redirect(reverse(f'public_admin:public_admin_{app_label}_{model_name_lower}_change', args=[pk]))

    def suspend_company_view(self, request, pk):
        """View to suspend company"""
        company = get_object_or_404(self.model, pk=pk)

        try:
            company.deactivate_company(reason=f"Suspended by admin {request.user.email}")
            messages.success(request, f'Company "{company.display_name}" has been suspended.')
            logger.info(f"Admin {request.user.email} suspended company {company.company_id}")
        except Exception as e:
            messages.error(request, f'Error suspending company: {str(e)}')
            logger.error(f"Error suspending company {company.company_id}: {str(e)}")

        app_label, model_name_lower = self.get_url_params()
        return redirect(reverse(f'public_admin:public_admin_{app_label}_{model_name_lower}_change', args=[pk]))

    def reactivate_all_users_view(self, request, pk):
        """View to reactivate all users"""
        company = get_object_or_404(self.model, pk=pk)

        try:
            count = company.reactivate_all_users()
            messages.success(request, f'Reactivated {count} users for "{company.display_name}".')
            logger.info(f"Admin {request.user.email} reactivated {count} users for company {company.company_id}")
        except Exception as e:
            messages.error(request, f'Error reactivating users: {str(e)}')
            logger.error(f"Error reactivating users for company {company.company_id}: {str(e)}")

        app_label, model_name_lower = self.get_url_params()
        return redirect(reverse(f'public_admin:public_admin_{app_label}_{model_name_lower}_change', args=[pk]))

    def enable_efris_view(self, request, pk):
        """View to enable EFRIS"""
        company = get_object_or_404(self.model, pk=pk)

        try:
            company.enable_efris()
            messages.success(request, f'EFRIS enabled for "{company.display_name}".')
            logger.info(f"Admin {request.user.email} enabled EFRIS for company {company.company_id}")
        except Exception as e:
            messages.error(request, f'Error enabling EFRIS: {str(e)}')
            logger.error(f"Error enabling EFRIS for company {company.company_id}: {str(e)}")

        app_label, model_name_lower = self.get_url_params()
        return redirect(reverse(f'public_admin:public_admin_{app_label}_{model_name_lower}_change', args=[pk]))

    def disable_efris_view(self, request, pk):
        """View to disable EFRIS"""
        company = get_object_or_404(self.model, pk=pk)

        try:
            company.disable_efris(reason=f"Disabled by admin {request.user.email}")
            messages.success(request, f'EFRIS disabled for "{company.display_name}".')
            logger.info(f"Admin {request.user.email} disabled EFRIS for company {company.company_id}")
        except Exception as e:
            messages.error(request, f'Error disabling EFRIS: {str(e)}')
            logger.error(f"Error disabling EFRIS for company {company.company_id}: {str(e)}")

        app_label, model_name_lower = self.get_url_params()
        return redirect(reverse(f'public_admin:public_admin_{app_label}_{model_name_lower}_change', args=[pk]))

    def force_status_refresh_view(self, request, pk):
        """View to force status refresh"""
        company = get_object_or_404(self.model, pk=pk)

        try:
            company.force_status_refresh()
            messages.success(request, f'Status refreshed for "{company.display_name}".')
            logger.info(f"Admin {request.user.email} refreshed status for company {company.company_id}")
        except Exception as e:
            messages.error(request, f'Error refreshing status: {str(e)}')
            logger.error(f"Error refreshing status for company {company.company_id}: {str(e)}")

        app_label, model_name_lower = self.get_url_params()
        return redirect(reverse(f'public_admin:public_admin_{app_label}_{model_name_lower}_change', args=[pk]))

    def extend_trial_view(self, request, pk):
        """View to extend trial"""
        company = get_object_or_404(self.model, pk=pk)

        try:
            company.extend_trial(days=30)
            messages.success(request, f'Trial extended by 30 days for "{company.display_name}".')
            logger.info(f"Admin {request.user.email} extended trial for company {company.company_id}")
        except Exception as e:
            messages.error(request, f'Error extending trial: {str(e)}')
            logger.error(f"Error extending trial for company {company.company_id}: {str(e)}")

        app_label, model_name_lower = self.get_url_params()
        return redirect(reverse(f'public_admin:public_admin_{app_label}_{model_name_lower}_change', args=[pk]))

    # Bulk action methods
    def reactivate_companies(self, request, queryset):
        """Bulk reactivate companies"""
        count = 0
        for company in queryset:
            try:
                company.reactivate_company(reason=f"Reactivated by admin {request.user.email}")
                count += 1
            except Exception as e:
                messages.error(request, f'Error reactivating {company.display_name}: {str(e)}')

        messages.success(request, f'Successfully reactivated {count} company(ies).')
        return None

    def suspend_companies(self, request, queryset):
        """Bulk suspend companies"""
        count = 0
        for company in queryset:
            try:
                company.deactivate_company(reason=f"Suspended by admin {request.user.email}")
                count += 1
            except Exception as e:
                messages.error(request, f'Error suspending {company.display_name}: {str(e)}')

        messages.success(request, f'Successfully suspended {count} company(ies).')
        return None

    def enable_efris_bulk(self, request, queryset):
        """Bulk enable EFRIS"""
        count = 0
        for company in queryset:
            try:
                company.enable_efris()
                count += 1
            except Exception as e:
                messages.error(request, f'Error enabling EFRIS for {company.display_name}: {str(e)}')

        messages.success(request, f'Successfully enabled EFRIS for {count} company(ies).')
        return None

    def disable_efris_bulk(self, request, queryset):
        """Bulk disable EFRIS"""
        count = 0
        for company in queryset:
            try:
                company.disable_efris(reason=f"Disabled by admin {request.user.email}")
                count += 1
            except Exception as e:
                messages.error(request, f'Error disabling EFRIS for {company.display_name}: {str(e)}')

        messages.success(request, f'Successfully disabled EFRIS for {count} company(ies).')
        return None

    def force_status_refresh(self, request, queryset):
        """Bulk force status refresh"""
        count = 0
        for company in queryset:
            try:
                company.force_status_refresh()
                count += 1
            except Exception as e:
                messages.error(request, f'Error refreshing status for {company.display_name}: {str(e)}')

        messages.success(request, f'Successfully refreshed status for {count} company(ies).')
        return None

    def extend_trial(self, request, queryset):
        """Bulk extend trial"""
        count = 0
        for company in queryset:
            try:
                company.extend_trial(days=30)
                count += 1
            except Exception as e:
                messages.error(request, f'Error extending trial for {company.display_name}: {str(e)}')

        messages.success(request, f'Successfully extended trial for {count} company(ies).')
        return None

    # List view display methods
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

    get_access_status.short_description = 'Access Status'

    def get_efris_status(self, obj):
        """Display EFRIS status"""
        if not obj.efris_enabled:
            return format_html('<span style="color: gray;">Disabled</span>')
        elif obj.efris_is_active:
            return format_html('<span style="color: green;">✓ Active</span>')
        else:
            return format_html('<span style="color: orange;">Enabled (Inactive)</span>')

    get_efris_status.short_description = 'EFRIS Status'

    def storage_usage_percentage(self, obj):
        """Display storage usage percentage"""
        percentage = obj.storage_usage_percentage
        color = 'green' if percentage < 70 else 'orange' if percentage < 90 else 'red'
        return format_html(
            '<span style="color: {};">{:.1f}%</span>',
            color, percentage
        )

    storage_usage_percentage.short_description = 'Storage Usage'

    def branches_count(self, obj):
        """Display branch count"""
        count = obj.branches_count
        max_branches = obj.plan.max_branches if obj.plan else 0
        return f"{count}/{max_branches}"

    branches_count.short_description = 'Branches'

    def days_until_expiry(self, obj):
        """Display days until expiry"""
        days = obj.days_until_expiry
        if days < 0:
            return format_html('<span style="color: red;">Expired</span>')
        elif days < 7:
            return format_html('<span style="color: orange;">{} days</span>', days)
        return f"{days} days"

    days_until_expiry.short_description = 'Days Until Expiry'

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