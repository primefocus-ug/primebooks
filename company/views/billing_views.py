import csv
import logging
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse, Http404, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import ListView, DetailView, TemplateView
from datetime import timedelta

from ..models import Company
from pesapal_integration.models import PlatformInvoice
from pesapal_integration.service import PesapalService

logger = logging.getLogger(__name__)


def _get_platform_ipn_id() -> str:
    """
    Get or register the platform IPN ID.
    Cached in Django cache after first run.
    """
    from django.conf import settings
    from django.core.cache import cache

    cached = cache.get('platform_pesapal_ipn_id')
    if cached:
        return cached

    svc     = PesapalService()
    ipn_url = settings.PESAPAL_PLATFORM_IPN_URL
    result  = svc.get_or_register_ipn(ipn_url)
    if result['success']:
        cache.set('platform_pesapal_ipn_id', result['ipn_id'], timeout=None)
        return result['ipn_id']

    raise RuntimeError(f"Could not register platform IPN: {result.get('error')}")


# ─────────────────────────────────────────────────────────────────────────────
# Initiate payment — tenant clicks "Pay Now" for their subscription
# ─────────────────────────────────────────────────────────────────────────────

class InitiateSubscriptionPaymentView(LoginRequiredMixin, View):
    """
    Creates a PlatformInvoice and redirects the tenant admin to Pesapal.
    Called from the subscription upgrade / renew / dashboard pages.

    POST params:
      plan_id        - SubscriptionPlan pk
      billing_cycle  - MONTHLY / QUARTERLY / YEARLY
    """

    def post(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({'success': False, 'message': 'No company found'}, status=404)

        plan_id       = request.POST.get('plan_id') or kwargs.get('plan_id')
        billing_cycle = request.POST.get('billing_cycle', 'MONTHLY').upper()

        try:
            from .models import SubscriptionPlan
            plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)
        except Exception:
            return JsonResponse({'success': False, 'message': 'Plan not found'}, status=404)

        amount      = plan.price
        currency    = getattr(plan, 'currency', 'UGX')
        description = f'{plan.display_name} Subscription ({billing_cycle.title()})'

        # Create the platform invoice first
        platform_invoice = PlatformInvoice.objects.create(
            company     = company,
            plan        = plan,
            amount      = amount,
            currency    = currency,
            description = description,
        )

        # Build billing address from company / user
        billing_address = {
            'email_address': company.billing_email or request.user.email or '',
            'phone_number':  getattr(company, 'phone', '') or '',
            'first_name':    request.user.first_name or company.name[:50],
            'last_name':     request.user.last_name or '',
            'country_code':  getattr(company, 'country_code', 'UG') or 'UG',
            'line_1':        getattr(company, 'physical_address', '') or '',
        }

        svc = PesapalService()

        callback_url     = request.build_absolute_uri(
            reverse('companies:platform_payment_callback')
        )
        cancellation_url = request.build_absolute_uri(
            reverse('companies:subscription_dashboard')
        )

        try:
            ipn_id = _get_platform_ipn_id()
        except Exception as exc:
            logger.error('Could not get platform IPN ID: %s', exc)
            messages.error(request, 'Payment setup failed. Please try again.')
            return redirect('companies:subscription_plans')

        order_result = svc.submit_order(
            merchant_reference = platform_invoice.merchant_reference,
            amount             = float(amount),
            currency           = currency,
            description        = description,
            notification_id    = ipn_id,
            billing_address    = billing_address,
            callback_url       = callback_url,
            cancellation_url   = cancellation_url,
            branch             = company.name[:50] if hasattr(company, 'name') else '',
        )

        if not order_result['success']:
            platform_invoice.status = 'FAILED'
            platform_invoice.save(update_fields=['status'])
            logger.error('Pesapal order failed for company %s: %s',
                         company.schema_name, order_result.get('error'))
            messages.error(request, 'Could not initiate payment. Please try again.')
            return redirect('companies:subscription_plans')

        platform_invoice.pesapal_tracking_id = order_result['order_tracking_id']
        platform_invoice.redirect_url        = order_result['redirect_url']
        platform_invoice.save(update_fields=['pesapal_tracking_id', 'redirect_url'])

        logger.info('Platform payment initiated for %s | invoice=%s | tracking=%s',
                    company.schema_name,
                    platform_invoice.invoice_number,
                    order_result['order_tracking_id'])

        return redirect(order_result['redirect_url'])


# ─────────────────────────────────────────────────────────────────────────────
# Callback — customer browser lands here after Pesapal payment
# ─────────────────────────────────────────────────────────────────────────────

class PlatformPaymentCallbackView(LoginRequiredMixin, View):
    """
    Pesapal redirects the tenant admin here after payment.
    Verifies status via GetTransactionStatus then shows result.
    """

    def get(self, request, *args, **kwargs):
        tracking_id        = request.GET.get('OrderTrackingId', '')
        merchant_reference = request.GET.get('OrderMerchantReference', '')

        context = {
            'tracking_id':        tracking_id,
            'merchant_reference': merchant_reference,
            'status_result':      None,
            'platform_invoice':   None,
        }

        if tracking_id:
            svc           = PesapalService()
            status_result = svc.get_transaction_status(tracking_id)
            context['status_result'] = status_result

            if status_result['success']:
                STATUS_MAP = {1: 'PAID', 2: 'FAILED', 3: 'REFUNDED', 0: 'FAILED'}
                new_status = STATUS_MAP.get(status_result.get('status_code'), 'FAILED')

                try:
                    inv = PlatformInvoice.objects.filter(
                        pesapal_tracking_id=tracking_id
                    ).first() or PlatformInvoice.objects.filter(
                        merchant_reference=merchant_reference
                    ).first()

                    if inv:
                        inv.status               = new_status
                        inv.pesapal_confirmation = status_result.get('confirmation_code', '') or inv.pesapal_confirmation
                        inv.payment_method       = status_result.get('payment_method', '') or inv.payment_method
                        if new_status == 'PAID' and not inv.paid_at:
                            inv.paid_at = timezone.now()
                        inv.save()
                        context['platform_invoice'] = inv

                        if new_status == 'PAID':
                            from pesapal_integration.ipn import _activate_subscription
                            _activate_subscription(inv)

                except Exception as exc:
                    logger.error('Callback update error: %s', exc)

        return render(request, 'pesapal_billing/platform_callback.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# Billing History
# ─────────────────────────────────────────────────────────────────────────────

class BillingHistoryView(LoginRequiredMixin, ListView):
    template_name       = 'company/billing/history.html'
    context_object_name = 'invoices'
    paginate_by         = 20

    def get_queryset(self):
        company = getattr(self.request.user, 'company', None)
        if not company:
            return PlatformInvoice.objects.none()
        return PlatformInvoice.objects.filter(company=company).order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = getattr(self.request.user, 'company', None)
        if company:
            from django.db.models import Sum
            context['company']           = company
            context['current_plan']      = company.plan
            context['next_billing_date'] = company.next_billing_date
            context['total_paid'] = (
                PlatformInvoice.objects
                .filter(company=company, status='PAID')
                .aggregate(t=Sum('amount'))['t'] or 0
            )
        return context


class PlatformInvoiceDetailView(LoginRequiredMixin, DetailView):
    template_name       = 'pesapal_billing/platform_invoice_detail.html'
    context_object_name = 'invoice'

    def get_object(self, queryset=None):
        company = getattr(self.request.user, 'company', None)
        if not company:
            raise Http404
        return get_object_or_404(
            PlatformInvoice,
            pk=self.kwargs['pk'],
            company=company,
        )


class DownloadInvoiceView(LoginRequiredMixin, View):
    """
    Download invoice as PDF
    """

    def get(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            raise Http404("No company found")

        invoice_id = kwargs.get('invoice_id') or kwargs.get('pk')
        invoice = get_object_or_404(PlatformInvoice, pk=invoice_id, company=company)

        # TODO: Generate actual PDF using reportlab or weasyprint
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = (
            f'attachment; filename="invoice_{invoice.invoice_number}.pdf"'
        )
        response.write(b'%PDF-1.4 Placeholder Invoice PDF')
        return response


class PaymentMethodsView(LoginRequiredMixin, TemplateView):
    """
    Manage payment methods
    """
    template_name = 'company/billing/payment_methods.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = getattr(self.request.user, 'company', None)

        if company:
            context['company'] = company
            context['current_payment_method'] = company.payment_method
            context['payment_methods'] = self._get_payment_methods(company)

        return context

    def _get_payment_methods(self, company):
        """
        Get saved payment methods
        TODO: Integrate with payment gateway to fetch saved cards/methods
        """
        methods = []

        if company.payment_method:
            methods.append({
                'id': 'pm_default',
                'type': company.payment_method,
                'is_default': True,
                'details': f'{company.payment_method.title()} (Default)',
            })

        return methods


class AddPaymentMethodView(LoginRequiredMixin, View):
    """
    Add new payment method
    """

    def post(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        payment_type = request.POST.get('payment_type', '').strip()
        if not payment_type:
            return JsonResponse({
                'success': False,
                'message': 'Payment type is required'
            }, status=400)

        # TODO: Integrate with payment gateway
        # Example for Stripe:
        # stripe.PaymentMethod.attach(
        #     payment_method_id,
        #     customer=company.stripe_customer_id,
        # )

        company.payment_method = payment_type
        company.save(update_fields=['payment_method'])

        logger.info(f"Payment method added for company {company.company_id}")

        return JsonResponse({
            'success': True,
            'message': 'Payment method added successfully'
        })


class RemovePaymentMethodView(LoginRequiredMixin, View):
    """
    Remove payment method
    """

    def post(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        method_id = request.POST.get('method_id')

        # TODO: Remove from payment gateway

        return JsonResponse({
            'success': True,
            'message': 'Payment method removed successfully'
        })


class ProcessPaymentView(LoginRequiredMixin, View):
    """
    Process a payment — delegates to InitiateSubscriptionPaymentView (Pesapal).
    Kept for backwards-compatibility with any existing URL references.
    """

    def post(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        plan_id = request.POST.get('plan_id') or kwargs.get('plan_id')
        if not plan_id:
            return JsonResponse({
                'success': False,
                'message': 'plan_id is required'
            }, status=400)

        view = InitiateSubscriptionPaymentView()
        view.request = request
        return view.post(request, plan_id=plan_id)


class BillingSettingsView(LoginRequiredMixin, TemplateView):
    """
    Manage billing settings
    """
    template_name = 'company/billing/settings.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = getattr(self.request.user, 'company', None)

        if company:
            context['company'] = company
            context['billing_email'] = company.billing_email or company.email
            context['billing_address'] = company.physical_address

        return context

    def post(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        # Update billing settings — validate email format before persisting
        billing_email = request.POST.get('billing_email', '').strip()
        if billing_email:
            if '@' not in billing_email or '.' not in billing_email.split('@')[-1]:
                return JsonResponse({
                    'success': False,
                    'message': 'Invalid email address format'
                }, status=400)
            company.billing_email = billing_email
            company.save(update_fields=['billing_email'])

        return JsonResponse({
            'success': True,
            'message': 'Billing settings updated successfully'
        })


class ExportInvoicesView(LoginRequiredMixin, View):
    """
    Export invoices as CSV
    """

    def get(self, request, *args, **kwargs):
        company = getattr(request.user, 'company', None)
        if not company:
            raise Http404("No company found")

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = (
            f'attachment; filename="invoices_{company.company_id}.csv"'
        )

        writer = csv.writer(response)
        writer.writerow(['Invoice Number', 'Date', 'Amount', 'Currency', 'Status', 'Description'])

        invoices = PlatformInvoice.objects.filter(company=company).order_by('-created_at')
        for invoice in invoices:
            writer.writerow([
                invoice.invoice_number,
                invoice.created_at.strftime('%Y-%m-%d'),
                invoice.amount,
                invoice.currency,
                invoice.status,
                invoice.description,
            ])

        return response