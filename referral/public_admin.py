from django.utils.translation import gettext_lazy as _
from django.utils.html import format_html
from django.contrib import messages
from public_accounts.admin_site import public_admin, PublicModelAdmin
from .models import Partner, ReferralSignup


class PartnerAdmin(PublicModelAdmin):
    list_display = ['full_name', 'email', 'referral_code', 'approval_badge', 'status_badge', 'date_joined']
    list_filter = ['is_approved', 'is_active', 'date_joined']
    search_fields = ['full_name', 'email', 'referral_code', 'company_name']
    readonly_fields = ['date_joined', 'last_login', 'referral_code']
    ordering = ['-date_joined']
    exclude = ['password', 'last_login']

    fieldsets = (
        (_('Account'), {
            'fields': ('email', 'full_name', 'phone', 'company_name')
        }),
        (_('Status'), {
            'fields': ('is_active', 'is_approved', 'is_staff')
        }),
        (_('Referral'), {
            'fields': ('referral_code', 'commission_rate')
        }),
        (_('Metadata'), {
            'fields': ('date_joined', 'last_login'),
            'classes': ('collapse',)
        }),
    )

    actions = ['approve_partners', 'revoke_approval']

    def approval_badge(self, obj):
        if obj.is_approved:
            return format_html('<span class="badge bg-success">{}</span>', _('Approved'))
        return format_html('<span class="badge bg-warning">{}</span>', _('Pending'))
    approval_badge.short_description = _('Approval')
    approval_badge.admin_order_field = 'is_approved'

    def status_badge(self, obj):
        if obj.is_active:
            return format_html('<span class="badge bg-success">{}</span>', _('Active'))
        return format_html('<span class="badge bg-secondary">{}</span>', _('Inactive'))
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'is_active'

    def approve_partners(self, request, queryset):
        updated = queryset.update(is_approved=True)
        self.message_user(request, _('{} partner(s) approved.').format(updated), messages.SUCCESS)
    approve_partners.short_description = _("Approve selected partners")

    def revoke_approval(self, request, queryset):
        updated = queryset.update(is_approved=False)
        self.message_user(request, _('{} partner(s) approval revoked.').format(updated), messages.WARNING)
    revoke_approval.short_description = _("Revoke approval for selected partners")


class ReferralSignupAdmin(PublicModelAdmin):
    list_display = ['company_name', 'partner', 'status_badge', 'commission_amount', 'commission_paid', 'registered_at']
    list_filter = ['status', 'commission_paid', 'registered_at']
    search_fields = ['company_name', 'company_email', 'referral_code_used', 'partner__email']
    readonly_fields = ['registered_at', 'completed_at', 'referral_code_used']
    ordering = ['-registered_at']

    fieldsets = (
        (_('Referral'), {
            'fields': ('partner', 'referral_code_used')
        }),
        (_('Company'), {
            'fields': ('company_name', 'company_email', 'tenant_schema_name', 'subdomain')
        }),
        (_('Status'), {
            'fields': ('status', 'registered_at', 'completed_at')
        }),
        (_('Commission'), {
            'fields': ('commission_amount', 'commission_paid'),
        }),
    )

    actions = ['mark_commission_paid']

    def status_badge(self, obj):
        colors = {'pending': 'warning', 'completed': 'success', 'cancelled': 'secondary'}
        return format_html(
            '<span class="badge bg-{}">{}</span>',
            colors.get(obj.status, 'secondary'),
            obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    def mark_commission_paid(self, request, queryset):
        updated = queryset.update(commission_paid=True)
        self.message_user(request, _('{} commission(s) marked as paid.').format(updated), messages.SUCCESS)
    mark_commission_paid.short_description = _("Mark commission as paid")


public_admin.register(Partner, PartnerAdmin, app_label='referral')
public_admin.register(ReferralSignup, ReferralSignupAdmin, app_label='referral')