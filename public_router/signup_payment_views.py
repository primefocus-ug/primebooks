"""
public_router/signup_payment_views.py
──────────────────────────────────────
Pesapal payment gate for new tenant signups.

FIX: The original version tried to create a PlatformInvoice with company=None,
which violates the NOT NULL constraint on company_id.  PlatformInvoice is for
tenants that already exist.  Pre-signup payments are tracked using
TenantPaymentTransaction (public schema, tenant FK is nullable) with a
sentinel tenant_schema value of 'SIGNUP:<request_id>' so they are never
confused with live tenant transactions.

Flow:
  1. tenant_signup_view  → status=PENDING_PAYMENT → redirect here (GET)
  2. GET  → show order summary + "Pay Securely" button
  3. POST → register IPN, submit order to Pesapal, save tracking ID → redirect
  4. Pesapal callback → SignupPaymentCallbackView
       ├─ OK   → status=PROCESSING → queue create_tenant_async → processing page
       └─ fail → status=PAYMENT_FAILED → retry page
  5. Cancelled → SignupPaymentCancelledView

URL wiring (public urls.py):
    path('signup/pay/<uuid:request_id>/',
         SignupPaymentInitiateView.as_view(), name='signup_payment_initiate'),
    path('signup/pay/<uuid:request_id>/callback/',
         SignupPaymentCallbackView.as_view(), name='signup_payment_callback'),
    path('signup/pay/<uuid:request_id>/cancelled/',
         SignupPaymentCancelledView.as_view(), name='signup_payment_cancelled'),
"""

import logging
import uuid as uuid_mod

from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from pesapal_integration.models import TenantPaymentTransaction
from pesapal_integration.service import PesapalService
from public_router.models import TenantSignupRequest, TenantApprovalWorkflow

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_plan(signup: TenantSignupRequest):
    """Resolve the SubscriptionPlan for this signup."""
    # Direct FK on signup
    if hasattr(signup, 'plan') and getattr(signup, 'plan_id', None):
        return signup.plan
    # CharField fallback
    from company.models import SubscriptionPlan
    if signup.selected_plan:
        return SubscriptionPlan.objects.filter(
            name=signup.selected_plan, is_active=True
        ).first()
    return None


def _get_or_create_txn(signup: TenantSignupRequest) -> TenantPaymentTransaction:
    """
    Return an existing PENDING TenantPaymentTransaction for this signup,
    or create one.  Idempotent — safe if the user navigates back and re-submits.

    We use TenantPaymentTransaction rather than PlatformInvoice because the
    company doesn't exist yet and PlatformInvoice.company_id is NOT NULL.
    TenantPaymentTransaction.tenant is nullable.

    The sentinel tenant_schema 'SIGNUP:<uuid>' keeps these rows clearly
    separated from real tenant transactions.
    """
    sentinel = f'SIGNUP:{signup.request_id}'

    existing = TenantPaymentTransaction.objects.filter(
        tenant_schema=sentinel,
        status='PENDING',
    ).first()
    if existing:
        return existing

    plan     = _get_plan(signup)
    amount   = float(plan.price) if (plan and hasattr(plan, 'price')) else 0.0
    currency = getattr(plan, 'currency', 'UGX') if plan else 'UGX'
    plan_name = plan.name if plan else (signup.selected_plan or 'Plan')

    merchant_reference = (
        f'SIGNUP-{str(signup.request_id).replace("-","")[:20]}'
        f'-{uuid_mod.uuid4().hex[:6].upper()}'
    )

    txn = TenantPaymentTransaction(
        tenant_schema      = sentinel,
        tenant             = None,      # company doesn't exist yet; field is nullable
        merchant_reference = merchant_reference,
        amount             = amount,
        currency           = currency,
        description        = f'Primebooks {plan_name} — {signup.company_name[:40]}',
        payment_type       = 'ONE_TIME',
        object_type        = 'signup',
        object_id          = None,
        status             = 'PENDING',
    )
    txn.save()
    return txn


def _public_base_url(request) -> str:
    return request.build_absolute_uri('/').rstrip('/')


# ─────────────────────────────────────────────────────────────────────────────
# View 1 — Initiate payment (GET = summary page, POST = redirect to Pesapal)
# ─────────────────────────────────────────────────────────────────────────────

class SignupPaymentInitiateView(View):
    template_name = 'public_router/signup_payment.html'

    def _get_signup(self, request_id):
        signup = get_object_or_404(TenantSignupRequest, request_id=request_id)
        if signup.status not in ('PENDING_PAYMENT', 'PAYMENT_FAILED'):
            raise Http404('This signup is not awaiting payment.')
        return signup

    def get(self, request, request_id):
        signup   = self._get_signup(request_id)
        plan     = _get_plan(signup)
        amount   = float(plan.price) if (plan and hasattr(plan, 'price')) else 0.0
        currency = getattr(plan, 'currency', 'UGX') if plan else 'UGX'
        return render(request, self.template_name, {
            'signup': signup, 'plan': plan,
            'amount': amount, 'currency': currency,
        })

    def post(self, request, request_id):
        signup   = self._get_signup(request_id)
        plan     = _get_plan(signup)
        amount   = float(plan.price) if (plan and hasattr(plan, 'price')) else 0.0
        currency = getattr(plan, 'currency', 'UGX') if plan else 'UGX'

        billing_address = {
            'first_name':    (signup.first_name  or '')[:50],
            'last_name':     (signup.last_name   or '')[:50],
            'email_address': signup.admin_email  or signup.email or '',
            'phone_number':  (signup.admin_phone or signup.phone or '')[:20],
            'country_code':  (signup.country     or 'UG')[:2].upper(),
        }

        with transaction.atomic():
            txn = _get_or_create_txn(signup)

        merchant_reference = txn.merchant_reference
        description        = txn.description

        # ── Pesapal: IPN + order ──────────────────────────────────────────
        svc     = PesapalService()
        ipn_url = request.build_absolute_uri('/pesapal/ipn/platform/')
        ipn_res = svc.get_or_register_ipn(ipn_url)

        if not ipn_res['success']:
            logger.error('IPN registration failed for signup %s: %s',
                         request_id, ipn_res.get('error'))
            return render(request, 'public_router/error.html', {
                'message': 'Payment setup failed. Please try again or contact support.',
            })

        base             = _public_base_url(request)
        callback_url     = f'{base}/signup/pay/{request_id}/callback/'
        cancellation_url = f'{base}/signup/pay/{request_id}/cancelled/'

        order_result = svc.submit_order(
            merchant_reference = merchant_reference,
            amount             = amount,
            currency           = currency,
            description        = description,
            notification_id    = ipn_res['ipn_id'],
            billing_address    = billing_address,
            callback_url       = callback_url,
            cancellation_url   = cancellation_url,
            branch             = 'Primebooks',
        )

        if not order_result['success']:
            logger.error('Order submission failed for signup %s: %s',
                         request_id, order_result.get('error'))
            return render(request, 'public_router/error.html', {
                'message': 'Could not initiate payment. Please try again.',
            })

        with transaction.atomic():
            txn.order_tracking_id = order_result['order_tracking_id']
            txn.redirect_url      = order_result.get('redirect_url', '')
            txn.save(update_fields=['order_tracking_id', 'redirect_url', 'updated_at'])

        logger.info('Signup payment initiated | signup=%s tracking=%s',
                    request_id, order_result['order_tracking_id'])

        return redirect(order_result['redirect_url'])


# ─────────────────────────────────────────────────────────────────────────────
# View 2 — Callback (Pesapal returns the user here)
# ─────────────────────────────────────────────────────────────────────────────

class SignupPaymentCallbackView(View):
    template_name = 'public_router/signup_payment_callback.html'

    def get(self, request, request_id):
        signup      = get_object_or_404(TenantSignupRequest, request_id=request_id)
        tracking_id = request.GET.get('OrderTrackingId', '')

        if not tracking_id:
            logger.warning('Callback missing OrderTrackingId | signup=%s', request_id)
            return render(request, self.template_name, {
                'signup': signup, 'success': False,
                'message': 'Payment could not be verified. Please contact support.',
            })

        svc           = PesapalService()
        status_result = svc.get_transaction_status(tracking_id)

        if not status_result['success']:
            logger.error('Status check failed | signup=%s tracking=%s error=%s',
                         request_id, tracking_id, status_result.get('error'))
            return render(request, self.template_name, {
                'signup': signup, 'success': False,
                'message': 'Could not verify payment status. Please contact support.',
            })

        status_code = status_result.get('status_code')
        paid = (status_code == 1)

        # ── Update audit record ───────────────────────────────────────────
        sentinel = f'SIGNUP:{signup.request_id}'
        txn = (
            TenantPaymentTransaction.objects.filter(
                tenant_schema=sentinel, order_tracking_id=tracking_id,
            ).first()
            or TenantPaymentTransaction.objects.filter(
                tenant_schema=sentinel,
            ).order_by('-created_at').first()
        )

        if txn:
            txn.order_tracking_id = tracking_id
            txn.confirmation_code = status_result.get('confirmation_code', '')
            txn.payment_method    = status_result.get('payment_method', '')
            txn.payment_account   = status_result.get('payment_account', '')
            txn.status            = 'COMPLETED' if paid else 'FAILED'
            txn.raw_response      = status_result.get('raw')
            if paid:
                txn.paid_at = timezone.now()
            txn.save()

        if not paid:
            with transaction.atomic():
                signup.status = 'PAYMENT_FAILED'
                signup.save(update_fields=['status', 'updated_at'])

            logger.warning('Payment not completed | signup=%s tracking=%s code=%s',
                           request_id, tracking_id, status_code)
            return render(request, self.template_name, {
                'signup':    signup,
                'success':   False,
                'message': (
                    f'Your payment was not successful '
                    f'({status_result.get("status_description", "unknown")}). '
                    'Please try again.'
                ),
                'retry_url': f'/signup/pay/{request_id}/',
            })

        # ── Payment confirmed — provision the tenant ──────────────────────
        with transaction.atomic():
            refreshed = TenantSignupRequest.objects.select_for_update().get(
                request_id=request_id
            )
            if refreshed.status not in ('PROCESSING', 'COMPLETED'):
                refreshed.status = 'PROCESSING'
                refreshed.save(update_fields=['status', 'updated_at'])

                workflow = TenantApprovalWorkflow.objects.filter(
                    signup_request=refreshed
                ).first()
                if not workflow:
                    from public_router.views import _generate_secure_password
                    TenantApprovalWorkflow.objects.create(
                        signup_request     = refreshed,
                        generated_password = _generate_secure_password(),
                        reviewed_at        = timezone.now(),
                        approval_notes     = 'Auto-approved after Pesapal payment.',
                    )
            else:
                logger.info('Signup %s already %s — skipping re-queue',
                            request_id, refreshed.status)

        from public_router.tasks import create_tenant_async
        create_tenant_async.apply_async(args=[str(signup.request_id)], countdown=0)

        logger.info('Payment CONFIRMED — provisioning queued | signup=%s tracking=%s',
                    request_id, tracking_id)

        request.session['signup_request_id'] = str(signup.request_id)

        base = _public_base_url(request)
        return render(request, self.template_name, {
            'signup':       signup,
            'success':      True,
            'tracking_id':  tracking_id,
            'message':      'Payment confirmed! Your workspace is being set up.',
            'redirect_url': f'{base}/signup/processing/{signup.request_id}/',
        })


# ─────────────────────────────────────────────────────────────────────────────
# View 3 — Cancelled
# ─────────────────────────────────────────────────────────────────────────────

class SignupPaymentCancelledView(View):
    def get(self, request, request_id):
        signup = get_object_or_404(TenantSignupRequest, request_id=request_id)
        if signup.status not in ('PROCESSING', 'COMPLETED'):
            signup.status = 'PENDING_PAYMENT'
            signup.save(update_fields=['status', 'updated_at'])
        return render(request, 'public_router/signup_payment_cancelled.html', {
            'signup':    signup,
            'retry_url': f'/signup/pay/{request_id}/',
        })