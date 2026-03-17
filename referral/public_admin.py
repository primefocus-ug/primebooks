"""
referral/public_admin.py
========================
Full-featured admin for the Partner Referral programme.
Wired into PublicAdminSite (public_accounts/admin_site.py).

Compatibility with PublicAdminSite / PublicModelAdmin:
  - No TemplateResponse — uses plain render()
  - No self.admin_site.each_context() — pass 'user' and 'app_configs' manually
  - No self.message_user() — use messages.success/warning/error(request, ...)
  - get_urls() returns custom URL list only; PublicAdminSite prepends it automatically
    Do NOT call super().get_urls() — PublicModelAdmin has no such method
  - admin_view() wraps views with permission check: self.admin_site.admin_view(view)
  - URL namespace is 'public_admin': reverse('public_admin:referral_partner_detail')
  - Standard list/change URL names: public_admin_{app_label}_{model_name}_list/change
"""


import csv
import json
from collections import defaultdict
from datetime import timedelta, date
from decimal import Decimal

from django.contrib import messages
from django.core.mail import send_mail
from django.db.models import Count, Sum, Q, Avg
from django.db.models.functions import TruncMonth, TruncDate
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.conf import settings

from public_accounts.admin_site import public_admin, PublicModelAdmin
from .models import Partner, ReferralSignup


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _send_partner_email(partner, subject, body):
    """Send an email to a partner. Silently skips if email is not configured."""
    try:
        from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@primebooks.com')
        send_mail(subject, body, from_email, [partner.email], fail_silently=True)
    except Exception:
        pass


def _approval_email_body(partner):
    return (
        f"Hi {partner.full_name},\n\n"
        f"Great news — your PrimeBooks Partner account has been approved!\n\n"
        f"Your referral code is: {partner.referral_code}\n\n"
        f"Log in to your dashboard to get your shareable link and QR code:\n"
        f"https://primebooks.sale/partners/dashboard/\n\n"
        f"Start sharing and earning today.\n\n"
        f"— The PrimeBooks Team"
    )


def _rejection_email_body(partner):
    return (
        f"Hi {partner.full_name},\n\n"
        f"Thank you for applying to the PrimeBooks Partner Programme.\n\n"
        f"Unfortunately we're unable to approve your account at this time. "
        f"If you believe this is an error, please contact us on WhatsApp: +256 785 230 670 "
        f"or email primefocusug@gmail.com.\n\n"
        f"— The PrimeBooks Team"
    )


def _commission_paid_email_body(partner, amount, referrals_count):
    return (
        f"Hi {partner.full_name},\n\n"
        f"Good news! A commission payment has been processed for your account.\n\n"
        f"Amount: UGX {amount:,.0f}\n"
        f"Referrals covered: {referrals_count}\n\n"
        f"Log in to view your earnings breakdown:\n"
        f"https://primebooks.sale/partners/earnings/\n\n"
        f"Thank you for being a valued PrimeBooks partner.\n\n"
        f"— The PrimeBooks Team"
    )


# ─────────────────────────────────────────────────────────────
# CSV export helpers
# ─────────────────────────────────────────────────────────────

def _export_partners_csv(queryset):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="partners-export.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Full Name', 'Email', 'Phone', 'Company', 'Referral Code',
        'Approved', 'Active', 'Commission Rate (%)',
        'Total Referrals', 'Completed', 'Pending',
        'Total Earned (UGX)', 'Total Paid (UGX)', 'Pending Payout (UGX)',
        'Date Joined',
    ])
    for p in queryset:
        writer.writerow([
            p.full_name, p.email, p.phone, p.company_name, p.referral_code,
            'Yes' if p.is_approved else 'No',
            'Yes' if p.is_active else 'No',
            p.commission_rate,
            p.total_referrals, p.successful_referrals, p.pending_referrals,
            p.total_earned, p.total_paid, p.total_pending_payout,
            p.date_joined.strftime('%Y-%m-%d'),
        ])
    return response


def _export_referrals_csv(queryset):
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="referrals-export.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Company Name', 'Company Email', 'Partner Name', 'Partner Email',
        'Referral Code Used', 'Status',
        'Registered At', 'Completed At',
        'Commission (UGX)', 'Commission Paid', 'Commission Paid At',
        'UTM Source', 'Subdomain',
    ])
    for r in queryset:
        writer.writerow([
            r.company_name, r.company_email,
            r.partner.full_name if r.partner else '',
            r.partner.email if r.partner else '',
            r.referral_code_used, r.status,
            r.registered_at.strftime('%Y-%m-%d %H:%M'),
            r.completed_at.strftime('%Y-%m-%d %H:%M') if r.completed_at else '',
            r.commission_amount,
            'Yes' if r.commission_paid else 'No',
            r.commission_paid_at.strftime('%Y-%m-%d') if r.commission_paid_at else '',
            r.utm_source, r.subdomain,
        ])
    return response


def _export_payout_report_csv(queryset):
    """One row per partner with unpaid commission totals — for payment processing."""
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="payout-report.csv"'
    writer = csv.writer(response)
    writer.writerow([
        'Partner Name', 'Email', 'Phone', 'Company',
        'Unpaid Referrals Count', 'Total Owed (UGX)', 'Commission Rate (%)',
    ])
    partner_ids = queryset.values_list('partner_id', flat=True).distinct()
    for pid in partner_ids:
        if not pid:
            continue
        try:
            p = Partner.objects.get(pk=pid)
        except Partner.DoesNotExist:
            continue
        unpaid = queryset.filter(partner=p, commission_paid=False, status='completed')
        total_owed = unpaid.aggregate(t=Sum('commission_amount'))['t'] or Decimal('0')
        if total_owed > 0:
            writer.writerow([
                p.full_name, p.email, p.phone, p.company_name,
                unpaid.count(), total_owed, p.commission_rate,
            ])
    return response


# ─────────────────────────────────────────────────────────────
# PartnerAdmin
# ─────────────────────────────────────────────────────────────

class PartnerAdmin(PublicModelAdmin):
    list_display = [
        'full_name', 'email', 'referral_code',
        'approval_badge', 'status_badge',
        'commission_rate', 'referral_stats', 'earnings_display',
        'date_joined',
    ]
    list_filter = ['is_approved', 'is_active', 'date_joined']
    search_fields = ['full_name', 'email', 'referral_code', 'company_name']
    readonly_fields = ['date_joined', 'last_login', 'referral_code', 'stats_panel']
    ordering = ['-date_joined']
    exclude = ['password']

    fieldsets = (
        (_('Account'), {
            'fields': ('email', 'full_name', 'phone', 'company_name')
        }),
        (_('Status'), {
            'fields': ('is_active', 'is_approved', 'is_staff')
        }),
        (_('Referral & Commission'), {
            'fields': ('referral_code', 'commission_rate')
        }),
        (_('Card Branding'), {
            'fields': ('ad_tagline', 'ad_promo_text'),
            'classes': ('collapse',),
        }),
        (_('Stats (read-only)'), {
            'fields': ('stats_panel',),
        }),
        (_('Metadata'), {
            'fields': ('date_joined', 'last_login'),
            'classes': ('collapse',),
        }),
    )

    actions = [
        'approve_partners',
        'revoke_approval',
        'deactivate_partners',
        'set_commission_5',
        'set_commission_10',
        'set_commission_15',
        'export_partners_csv',
    ]

    # ── Custom URLs ──────────────────────────────────────────
    # PublicAdminSite.get_urls() calls model_admin.get_urls() and prepends
    # the result before standard CRUD URLs. Do NOT call super().get_urls()
    # here — PublicModelAdmin has no get_urls(); doing so would crash.
    def get_urls(self):
        return [
            path(
                'referral/dashboard/',
                self.admin_site.admin_view(self.referral_dashboard_view),
                name='referral_dashboard',
            ),
            path(
                'referral/analytics/',
                self.admin_site.admin_view(self.analytics_view),
                name='referral_analytics',
            ),
            path(
                'referral/partner/<uuid:pk>/detail/',
                self.admin_site.admin_view(self.partner_detail_view),
                name='referral_partner_detail',
            ),
        ]

    # ── Dashboard view ──
    def referral_dashboard_view(self, request):
        now = timezone.now()
        thirty_days_ago = now - timedelta(days=30)
        seven_days_ago = now - timedelta(days=7)

        total_partners = Partner.objects.count()
        approved_partners = Partner.objects.filter(is_approved=True).count()
        pending_approval = Partner.objects.filter(is_approved=False, is_active=True).count()

        total_referrals = ReferralSignup.objects.count()
        completed_referrals = ReferralSignup.objects.filter(status='completed').count()
        pending_referrals = ReferralSignup.objects.filter(status='pending').count()

        total_commission = ReferralSignup.objects.filter(
            status='completed'
        ).aggregate(t=Sum('commission_amount'))['t'] or Decimal('0')
        unpaid_commission = ReferralSignup.objects.filter(
            status='completed', commission_paid=False
        ).aggregate(t=Sum('commission_amount'))['t'] or Decimal('0')

        # This month
        this_month_referrals = ReferralSignup.objects.filter(
            registered_at__gte=now.replace(day=1, hour=0, minute=0, second=0)
        ).count()
        last_30d_signups = ReferralSignup.objects.filter(registered_at__gte=thirty_days_ago).count()
        last_7d_signups = ReferralSignup.objects.filter(registered_at__gte=seven_days_ago).count()

        conversion_rate = (
            round(completed_referrals / total_referrals * 100, 1) if total_referrals else 0
        )

        # Top 5 partners by completed referrals
        top_partners = (
            Partner.objects.filter(is_approved=True)
            .annotate(
                completed=Count('referrals', filter=Q(referrals__status='completed')),
                total=Count('referrals'),
                earned=Sum('referrals__commission_amount', filter=Q(referrals__status='completed')),
            )
            .order_by('-completed')[:8]
        )

        # Recent applications (unapproved partners)
        recent_applications = Partner.objects.filter(
            is_approved=False, is_active=True
        ).order_by('-date_joined')[:10]

        # Recent referrals
        recent_referrals = ReferralSignup.objects.select_related('partner').order_by('-registered_at')[:10]

        # Daily signups last 30 days (for sparkline)
        daily_data = (
            ReferralSignup.objects
            .filter(registered_at__gte=thirty_days_ago)
            .annotate(day=TruncDate('registered_at'))
            .values('day')
            .annotate(count=Count('id'))
            .order_by('day')
        )
        daily_map = {str(d['day']): d['count'] for d in daily_data}
        days_30 = [(thirty_days_ago + timedelta(days=i)).date() for i in range(31)]
        sparkline_labels = [d.strftime('%b %d') for d in days_30]
        sparkline_values = [daily_map.get(str(d), 0) for d in days_30]

        context = {
            'user': request.user,
            'app_configs': self.admin_site.app_configs,
            'title': 'Referral Programme Dashboard',
            'total_partners': total_partners,
            'approved_partners': approved_partners,
            'pending_approval': pending_approval,
            'total_referrals': total_referrals,
            'completed_referrals': completed_referrals,
            'pending_referrals': pending_referrals,
            'conversion_rate': conversion_rate,
            'total_commission': total_commission,
            'unpaid_commission': unpaid_commission,
            'this_month_referrals': this_month_referrals,
            'last_30d_signups': last_30d_signups,
            'last_7d_signups': last_7d_signups,
            'top_partners': top_partners,
            'recent_applications': recent_applications,
            'recent_referrals': recent_referrals,
            'sparkline_labels': json.dumps(sparkline_labels),
            'sparkline_values': json.dumps(sparkline_values),
        }
        return render(request, 'admin/referral/dashboard.html', context)

    # ── Analytics view ──
    def analytics_view(self, request):
        now = timezone.now()
        twelve_months_ago = now - timedelta(days=365)

        # Monthly referral counts by status
        monthly = (
            ReferralSignup.objects
            .filter(registered_at__gte=twelve_months_ago)
            .annotate(month=TruncMonth('registered_at'))
            .values('month', 'status')
            .annotate(count=Count('id'))
            .order_by('month')
        )
        monthly_map = defaultdict(lambda: {'pending': 0, 'completed': 0, 'cancelled': 0})
        for row in monthly:
            label = row['month'].strftime('%b %Y')
            monthly_map[label][row['status']] += row['count']

        chart_labels = list(monthly_map.keys())
        chart_completed = [monthly_map[m]['completed'] for m in chart_labels]
        chart_pending = [monthly_map[m]['pending'] for m in chart_labels]
        chart_cancelled = [monthly_map[m]['cancelled'] for m in chart_labels]

        # Monthly commission earned
        monthly_commission = (
            ReferralSignup.objects
            .filter(status='completed', registered_at__gte=twelve_months_ago)
            .annotate(month=TruncMonth('registered_at'))
            .values('month')
            .annotate(total=Sum('commission_amount'))
            .order_by('month')
        )
        commission_map = {row['month'].strftime('%b %Y'): float(row['total'] or 0) for row in monthly_commission}
        chart_commission = [commission_map.get(m, 0) for m in chart_labels]

        # UTM source breakdown
        utm_breakdown = (
            ReferralSignup.objects
            .values('utm_source')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        utm_labels = [r['utm_source'] or 'direct' for r in utm_breakdown]
        utm_counts = [r['count'] for r in utm_breakdown]

        # Partner performance table
        partner_perf = (
            Partner.objects.filter(is_approved=True)
            .annotate(
                completed=Count('referrals', filter=Q(referrals__status='completed')),
                total_refs=Count('referrals'),
                earned=Sum('referrals__commission_amount', filter=Q(referrals__status='completed')),
            )
            .order_by('-completed')
        )

        context = {
            'user': request.user,
            'app_configs': self.admin_site.app_configs,
            'title': 'Referral Analytics',
            'chart_labels': json.dumps(chart_labels),
            'chart_completed': json.dumps(chart_completed),
            'chart_pending': json.dumps(chart_pending),
            'chart_cancelled': json.dumps(chart_cancelled),
            'chart_commission': json.dumps(chart_commission),
            'utm_labels': json.dumps(utm_labels),
            'utm_counts': json.dumps(utm_counts),
            'partner_perf': partner_perf,
        }
        return render(request, 'admin/referral/analytics.html', context)

    # ── Per-partner detail view ──
    def partner_detail_view(self, request, pk):
        partner = get_object_or_404(Partner, pk=pk)

        if request.method == 'POST':
            action = request.POST.get('action')

            if action == 'approve':
                partner.is_approved = True
                partner.save()
                _send_partner_email(partner, 'Your PrimeBooks Partner account is approved!', _approval_email_body(partner))
                messages.success(request, f'{partner.full_name} approved. Notification email sent.')

            elif action == 'reject':
                partner.is_approved = False
                partner.is_active = False
                partner.save()
                _send_partner_email(partner, 'Update on your PrimeBooks Partner application', _rejection_email_body(partner))
                messages.warning(request, f'{partner.full_name} rejected and deactivated.')

            elif action == 'set_commission':
                try:
                    rate = Decimal(request.POST.get('commission_rate', '0'))
                    partner.commission_rate = rate
                    partner.save()
                    messages.success(request, f'Commission rate updated to {rate}%.')
                except Exception:
                    messages.error(request, 'Invalid commission rate.')

            elif action == 'pay_all':
                unpaid = partner.referrals.filter(status='completed', commission_paid=False)
                total_owed = unpaid.aggregate(t=Sum('commission_amount'))['t'] or Decimal('0')
                count = unpaid.count()
                if count:
                    from django.utils import timezone as tz
                    unpaid.update(commission_paid=True, commission_paid_at=tz.now())
                    _send_partner_email(
                        partner,
                        'Commission payment processed — PrimeBooks',
                        _commission_paid_email_body(partner, total_owed, count)
                    )
                    messages.success(request, f'Marked {count} referral(s) paid (UGX {total_owed:,.0f}). Email sent.')
                else:
                    messages.info(request, 'No unpaid commissions to process.')

            return redirect(
                reverse('public_admin:referral_partner_detail', kwargs={'pk': pk})
            )

        referrals = partner.referrals.order_by('-registered_at')
        unpaid_total = partner.referrals.filter(
            status='completed', commission_paid=False
        ).aggregate(t=Sum('commission_amount'))['t'] or Decimal('0')

        context = {
            'user': request.user,
            'app_configs': self.admin_site.app_configs,
            'title': f'Partner: {partner.full_name}',
            'partner': partner,
            'referrals': referrals,
            'unpaid_total': unpaid_total,
        }
        return render(request, 'admin/referral/partner_detail.html', context)

    # ── List column helpers ──
    def referral_stats(self, obj):
        total = obj.total_referrals
        completed = obj.successful_referrals
        return format_html(
            '<span style="font-size:0.8rem">'
            '<span style="color:#22c55e;font-weight:600">{}</span>'
            '<span style="color:#666"> / {}</span>'
            '</span>',
            completed, total
        )
    referral_stats.short_description = _('Done/Total')

    def earnings_display(self, obj):
        earned = obj.total_earned
        if earned:
            return format_html(
                '<span style="font-size:0.82rem;color:#6b78ff;font-weight:500">UGX {:,.0f}</span>',
                earned
            )
        return format_html('<span style="color:#555">—</span>')
    earnings_display.short_description = _('Earned')

    def approval_badge(self, obj):
        if obj.is_approved:
            return format_html(
                '<span style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e44;'
                'padding:2px 8px;border-radius:20px;font-size:0.75rem">✓ Approved</span>'
            )
        return format_html(
            '<span style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b44;'
            'padding:2px 8px;border-radius:20px;font-size:0.75rem">⏳ Pending</span>'
        )
    approval_badge.short_description = _('Approval')
    approval_badge.admin_order_field = 'is_approved'

    def status_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e44;'
                'padding:2px 8px;border-radius:20px;font-size:0.75rem">Active</span>'
            )
        return format_html(
            '<span style="background:#55555522;color:#888;border:1px solid #44444444;'
            'padding:2px 8px;border-radius:20px;font-size:0.75rem">Inactive</span>'
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'is_active'

    def stats_panel(self, obj):
        if not obj.pk:
            return '—'
        return format_html(
            '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:1rem;padding:1rem;'
            'background:#1a1a1a;border-radius:6px;border:1px solid #333">'
            '<div><div style="font-size:0.7rem;color:#888;text-transform:uppercase;margin-bottom:4px">Total</div>'
            '<div style="font-size:1.4rem;font-weight:300;color:#fff">{}</div></div>'
            '<div><div style="font-size:0.7rem;color:#888;text-transform:uppercase;margin-bottom:4px">Completed</div>'
            '<div style="font-size:1.4rem;font-weight:300;color:#22c55e">{}</div></div>'
            '<div><div style="font-size:0.7rem;color:#888;text-transform:uppercase;margin-bottom:4px">Earned</div>'
            '<div style="font-size:1.4rem;font-weight:300;color:#6b78ff">UGX {:,.0f}</div></div>'
            '</div>',
            obj.total_referrals, obj.successful_referrals, obj.total_earned
        )
    stats_panel.short_description = _('Performance')

    # ── Actions ──
    def approve_partners(self, request, queryset):
        updated = 0
        for partner in queryset.filter(is_approved=False):
            partner.is_approved = True
            partner.save()
            _send_partner_email(partner, 'Your PrimeBooks Partner account is approved!', _approval_email_body(partner))
            updated += 1
        messages.success(
            request,
            _('{} partner(s) approved and notified by email.').format(updated)
        )
    approve_partners.short_description = _('✓ Approve selected & send email')

    def revoke_approval(self, request, queryset):
        updated = queryset.update(is_approved=False)
        messages.warning(request, _('{} partner(s) approval revoked.').format(updated))
    revoke_approval.short_description = _('✕ Revoke approval')

    def deactivate_partners(self, request, queryset):
        updated = queryset.update(is_active=False)
        messages.warning(request, _('{} partner(s) deactivated.').format(updated))
    deactivate_partners.short_description = _('Deactivate selected partners')

    def set_commission_5(self, request, queryset):
        queryset.update(commission_rate=Decimal('5.00'))
        messages.success(request, _('Commission rate set to 5% for {} partner(s).').format(queryset.count()))
    set_commission_5.short_description = _('Set commission → 5%')

    def set_commission_10(self, request, queryset):
        queryset.update(commission_rate=Decimal('10.00'))
        messages.success(request, _('Commission rate set to 10% for {} partner(s).').format(queryset.count()))
    set_commission_10.short_description = _('Set commission → 10%')

    def set_commission_15(self, request, queryset):
        queryset.update(commission_rate=Decimal('15.00'))
        messages.success(request, _('Commission rate set to 15% for {} partner(s).').format(queryset.count()))
    set_commission_15.short_description = _('Set commission → 15%')

    def export_partners_csv(self, request, queryset):
        return _export_partners_csv(queryset)
    export_partners_csv.short_description = _('⬇ Export selected to CSV')


# ─────────────────────────────────────────────────────────────
# ReferralSignupAdmin
# ─────────────────────────────────────────────────────────────

class ReferralSignupAdmin(PublicModelAdmin):
    list_display = [
        'company_name', 'partner_link', 'status_badge',
        'commission_display', 'paid_badge',
        'utm_source', 'registered_at',
    ]
    list_filter = ['status', 'commission_paid', 'utm_source', 'registered_at']
    search_fields = ['company_name', 'company_email', 'referral_code_used', 'partner__email', 'partner__full_name']
    readonly_fields = ['registered_at', 'completed_at', 'referral_code_used', 'commission_paid_at']
    ordering = ['-registered_at']
    date_hierarchy = 'registered_at'

    fieldsets = (
        (_('Referral'), {
            'fields': ('partner', 'referral_code_used', 'utm_source', 'utm_campaign')
        }),
        (_('Company'), {
            'fields': ('company_name', 'company_email', 'tenant_schema_name', 'subdomain')
        }),
        (_('Status'), {
            'fields': ('status', 'registered_at', 'completed_at')
        }),
        (_('Commission'), {
            'fields': ('commission_amount', 'commission_paid', 'commission_paid_at'),
        }),
    )

    actions = [
        'mark_completed',
        'mark_cancelled',
        'mark_commission_paid',
        'recalculate_commissions',
        'export_referrals_csv',
        'export_payout_report',
    ]

    def partner_link(self, obj):
        if not obj.partner:
            return format_html('<span style="color:#555">—</span>')
        url = reverse('public_admin:referral_partner_detail', kwargs={'pk': obj.partner.pk})
        return format_html(
            '<a href="{}" style="color:#6b78ff;text-decoration:none">{}</a>',
            url, obj.partner.full_name
        )
    partner_link.short_description = _('Partner')

    def commission_display(self, obj):
        if obj.commission_amount:
            return format_html(
                '<span style="color:#6b78ff;font-weight:500;font-size:0.82rem">UGX {:,.0f}</span>',
                obj.commission_amount
            )
        return format_html('<span style="color:#555">—</span>')
    commission_display.short_description = _('Commission')
    commission_display.admin_order_field = 'commission_amount'

    def paid_badge(self, obj):
        if obj.status != 'completed':
            return format_html('<span style="color:#555;font-size:0.78rem">N/A</span>')
        if obj.commission_paid:
            return format_html(
                '<span style="background:#22c55e22;color:#22c55e;border:1px solid #22c55e44;'
                'padding:2px 8px;border-radius:20px;font-size:0.75rem">✓ Paid</span>'
            )
        return format_html(
            '<span style="background:#f59e0b22;color:#f59e0b;border:1px solid #f59e0b44;'
            'padding:2px 8px;border-radius:20px;font-size:0.75rem">⏳ Unpaid</span>'
        )
    paid_badge.short_description = _('Payout')
    paid_badge.admin_order_field = 'commission_paid'

    def status_badge(self, obj):
        cfg = {
            'pending':   ('#f59e0b', '⏳'),
            'completed': ('#22c55e', '✓'),
            'cancelled': ('#ef4444', '✕'),
        }
        color, icon = cfg.get(obj.status, ('#888', '?'))
        return format_html(
            '<span style="background:{0}22;color:{0};border:1px solid {0}44;'
            'padding:2px 8px;border-radius:20px;font-size:0.75rem">{1} {2}</span>',
            color, icon, obj.get_status_display()
        )
    status_badge.short_description = _('Status')
    status_badge.admin_order_field = 'status'

    # ── Actions ──
    def mark_completed(self, request, queryset):
        count = 0
        for ref in queryset.filter(status='pending'):
            ref.mark_completed()
            count += 1
        messages.success(
            request,
            _('{} referral(s) marked completed. Commissions auto-calculated.').format(count)
        )
    mark_completed.short_description = _('✓ Mark selected as Completed')

    def mark_cancelled(self, request, queryset):
        updated = queryset.update(status='cancelled')
        messages.warning(request, _('{} referral(s) marked cancelled.').format(updated))
    mark_cancelled.short_description = _('✕ Mark selected as Cancelled')

    def mark_commission_paid(self, request, queryset):
        now = timezone.now()
        updated = 0
        partner_ids = set()
        for ref in queryset.filter(status='completed', commission_paid=False):
            ref.commission_paid = True
            ref.commission_paid_at = now
            ref.save()
            if ref.partner_id:
                partner_ids.add(ref.partner_id)
            updated += 1
        # Send email per partner
        for pid in partner_ids:
            try:
                p = Partner.objects.get(pk=pid)
                unpaid_count = queryset.filter(partner=p, commission_paid=True).count()
                total = queryset.filter(partner=p, commission_paid=True).aggregate(
                    t=Sum('commission_amount'))['t'] or Decimal('0')
                _send_partner_email(
                    p,
                    'Commission payment processed — PrimeBooks',
                    _commission_paid_email_body(p, total, unpaid_count)
                )
            except Partner.DoesNotExist:
                pass
        messages.success(
            request,
            _('{} commission(s) marked paid. Partners notified.').format(updated)
        )
    mark_commission_paid.short_description = _('💰 Mark commission paid & notify partners')

    def recalculate_commissions(self, request, queryset):
        count = 0
        for ref in queryset.filter(status='completed'):
            if ref.partner and ref.partner.commission_rate:
                base = Decimal('50000.00')
                ref.commission_amount = (base * ref.partner.commission_rate / Decimal('100')).quantize(Decimal('0.01'))
                ref.save()
                count += 1
        messages.success(request, _('Recalculated commission for {} referral(s).').format(count))
    recalculate_commissions.short_description = _('↻ Recalculate commissions from partner rate')

    def export_referrals_csv(self, request, queryset):
        return _export_referrals_csv(queryset)
    export_referrals_csv.short_description = _('⬇ Export selected referrals to CSV')

    def export_payout_report(self, request, queryset):
        return _export_payout_report_csv(queryset)
    export_payout_report.short_description = _('⬇ Export payout report (unpaid commissions)')


# ─────────────────────────────────────────────────────────────
# Register
# ─────────────────────────────────────────────────────────────

public_admin.register(Partner, PartnerAdmin, app_label='referral')
public_admin.register(ReferralSignup, ReferralSignupAdmin, app_label='referral')