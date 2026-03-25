"""
pesapal_integration/ipn.py
───────────────────────────
Handles all inbound IPN calls from Pesapal.

Two URL patterns:
  /pesapal/ipn/platform/           ← SaaS billing (tenant pays you)
  /pesapal/ipn/tenant/<slug>/      ← Tenant collecting from their customers

Both are registered as CSRF-exempt public endpoints.
"""

import json
import logging

from django.db import connection
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils import timezone

from .models import PesapalIPNLog, TenantPaymentTransaction, PlatformInvoice
from pesapal_integration.service import PesapalService, STATUS_CODE_MAP

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Shared: parse IPN params from GET or POST
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ipn(request):
    if request.method == 'GET':
        return {
            'tracking_id':        request.GET.get('OrderTrackingId', ''),
            'merchant_reference': request.GET.get('OrderMerchantReference', ''),
            'notification_type':  request.GET.get('OrderNotificationType', 'IPNCHANGE'),
            'raw':                dict(request.GET),
        }
    try:
        body = json.loads(request.body.decode('utf-8'))
    except Exception:
        body = {}
    return {
        'tracking_id':        body.get('OrderTrackingId', ''),
        'merchant_reference': body.get('OrderMerchantReference', ''),
        'notification_type':  body.get('OrderNotificationType', 'IPNCHANGE'),
        'raw':                body,
    }


def _ipn_response(tracking_id, merchant_reference, notification_type, status=200):
    return JsonResponse({
        'orderNotificationType':  notification_type,
        'orderTrackingId':        tracking_id,
        'orderMerchantReference': merchant_reference,
        'status':                 status,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Flow 1 — Platform IPN  (tenant pays YOU)
# URL: /pesapal/ipn/platform/
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET', 'POST'])
def platform_ipn(request):
    """
    Handles Pesapal notifications for SaaS subscription payments
    AND module add-on payments.
    Runs entirely on the PUBLIC schema — no tenant switching needed.
    """
    params = _parse_ipn(request)
    tracking_id        = params['tracking_id']
    merchant_reference = params['merchant_reference']
    notification_type  = params['notification_type']

    logger.info('Platform IPN | type=%s | tracking=%s | ref=%s',
                notification_type, tracking_id, merchant_reference)

    log = PesapalIPNLog.objects.create(
        order_tracking_id        = tracking_id,
        order_merchant_reference = merchant_reference,
        order_notification_type  = notification_type,
        source                   = 'platform',
        raw_params               = params['raw'],
    )

    if not tracking_id:
        log.error = 'Missing OrderTrackingId'
        log.save(update_fields=['error'])
        return _ipn_response(tracking_id, merchant_reference, notification_type, 500)

    # Use platform keys
    svc = PesapalService()
    status_result = svc.get_transaction_status(tracking_id)

    if not status_result['success']:
        log.error = str(status_result.get('error', ''))
        log.save(update_fields=['error'])
        return _ipn_response(tracking_id, merchant_reference, notification_type, 500)

    # Update PlatformInvoice — handles both subscription and module payments
    _update_platform_invoice(tracking_id, merchant_reference, status_result)

    log.processed = True
    log.save(update_fields=['processed'])
    return _ipn_response(tracking_id, merchant_reference, notification_type, 200)


def _update_platform_invoice(tracking_id, merchant_reference, status_result):
    """
    Update PlatformInvoice and trigger the correct post-payment action:
      - plan set   → activate / renew subscription
      - module set → activate the module for the tenant
    """
    STATUS_MAP = {1: 'PAID', 2: 'FAILED', 3: 'REFUNDED', 0: 'FAILED'}
    new_status = STATUS_MAP.get(status_result.get('status_code'), 'FAILED')

    try:
        inv = PlatformInvoice.objects.filter(
            pesapal_tracking_id=tracking_id
        ).first() or PlatformInvoice.objects.filter(
            merchant_reference=merchant_reference
        ).first()

        if not inv:
            logger.warning('PlatformInvoice not found: tracking=%s ref=%s', tracking_id, merchant_reference)
            return

        inv.status               = new_status
        inv.pesapal_tracking_id  = tracking_id
        inv.pesapal_confirmation = status_result.get('confirmation_code', '') or inv.pesapal_confirmation
        inv.payment_method       = status_result.get('payment_method', '') or inv.payment_method
        inv.payment_account      = status_result.get('payment_account', '') or inv.payment_account

        if new_status == 'PAID' and not inv.paid_at:
            inv.paid_at = timezone.now()

        inv.save()

        if new_status == 'PAID':
            if inv.module_id:
                # Module add-on payment — activate the module
                _activate_module(inv)
            elif inv.plan_id:
                # Subscription payment — renew/activate plan
                _activate_subscription(inv)
            else:
                logger.warning(
                    'PlatformInvoice %s is PAID but has neither plan nor module — no action taken.',
                    inv.pk
                )

    except Exception as exc:
        logger.exception('Error updating PlatformInvoice for %s: %s', tracking_id, exc)


def _activate_subscription(platform_invoice: PlatformInvoice):
    """
    Activate / renew the company subscription after a successful payment.
    Hooks into your existing SubscriptionService.
    """
    try:
        company = platform_invoice.company
        plan    = platform_invoice.plan

        if not plan:
            logger.warning('PlatformInvoice %s has no plan — skipping subscription activation', platform_invoice.pk)
            return

        from company.services.subscription_service import SubscriptionService
        svc = SubscriptionService()
        result = svc.renew_subscription(
            company=company,
            billing_cycle=getattr(plan, 'billing_cycle', 'MONTHLY'),
            payment_method='MOBILE_MONEY',
            renewed_by=None,
        )
        if result.get('success'):
            logger.info('Subscription activated for %s via PlatformInvoice %s',
                        company.schema_name, platform_invoice.pk)
        else:
            logger.error('Subscription activation failed for %s: %s',
                         company.schema_name, result.get('message'))

    except Exception as exc:
        logger.exception('Error activating subscription for invoice %s: %s',
                         platform_invoice.pk, exc)


def _activate_module(platform_invoice: PlatformInvoice):
    """
    Activate a module for the tenant after a successful module payment via IPN.

    This is the background / fallback path — the browser callback in plug.py
    handles the happy path first.  This ensures activation even if the customer
    closes the browser before the callback page loads.

    Sets paid_through = payment date + MODULE_BILLING_DAYS so that the tenant
    can deactivate and reactivate for free within their billing window.
    """
    try:
        from company.models import CompanyModule
        from django.core.cache import cache
        from datetime import timedelta

        MODULE_BILLING_DAYS = 30   # keep in sync with plug.py

        company = platform_invoice.company
        module  = platform_invoice.module

        if not module:
            logger.warning('PlatformInvoice %s has no module — skipping module activation',
                           platform_invoice.pk)
            return

        cm, _ = CompanyModule.objects.get_or_create(company=company, module=module)

        # Always update paid_through, even if already active (e.g. renewal IPN)
        paid_through = (timezone.now() + timedelta(days=MODULE_BILLING_DAYS)).date()

        if cm.is_active:
            # Module was already on (callback beat IPN, or a renewal).
            # Just extend the billing window.
            cm.paid_through = paid_through
            cm.save(update_fields=['paid_through'])
            logger.info(
                'Module %s already active for %s — IPN extended paid_through to %s.',
                module.key, company.schema_name, paid_through,
            )
            return

        cm.activate(paid_through=paid_through)
        cache.delete(f'active_modules:{company.schema_name}')

        logger.info(
            'Module %s activated for %s via IPN (PlatformInvoice %s, paid_through=%s)',
            module.key, company.schema_name, platform_invoice.pk, paid_through,
        )

    except Exception as exc:
        logger.exception('Error activating module for invoice %s: %s',
                         platform_invoice.pk, exc)


# ─────────────────────────────────────────────────────────────────────────────
# Flow 2 & 3 — Tenant IPN  (tenant collecting from their customers)
# URL: /pesapal/ipn/tenant/<tenant_slug>/
# ─────────────────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(['GET', 'POST'])
def tenant_ipn(request, tenant_slug: str):
    """
    Handles Pesapal notifications for payments initiated by a specific tenant.
    Switches to the tenant schema to update the relevant invoice / sale.
    """
    params = _parse_ipn(request)
    tracking_id        = params['tracking_id']
    merchant_reference = params['merchant_reference']
    notification_type  = params['notification_type']

    logger.info('Tenant IPN | slug=%s | type=%s | tracking=%s | ref=%s',
                tenant_slug, notification_type, tracking_id, merchant_reference)

    # ── Resolve tenant from public schema ─────────────────────────────────────
    try:
        from company.models import Company
        company = Company.objects.get(schema_name=tenant_slug)
    except Company.DoesNotExist:
        logger.error('Tenant IPN: unknown tenant slug %s', tenant_slug)
        return _ipn_response(tracking_id, merchant_reference, notification_type, 500)

    log = PesapalIPNLog.objects.create(
        order_tracking_id        = tracking_id,
        order_merchant_reference = merchant_reference,
        order_notification_type  = notification_type,
        source                   = 'tenant',
        tenant_schema            = tenant_slug,
        raw_params               = params['raw'],
    )

    if not tracking_id:
        log.error = 'Missing OrderTrackingId'
        log.save(update_fields=['error'])
        return _ipn_response(tracking_id, merchant_reference, notification_type, 500)

    # ── Fetch status using tenant's (or platform) keys ────────────────────────
    svc = PesapalService.for_tenant(company)
    status_result = svc.get_transaction_status(tracking_id)

    if not status_result['success']:
        log.error = str(status_result.get('error', ''))
        log.save(update_fields=['error'])
        return _ipn_response(tracking_id, merchant_reference, notification_type, 500)

    # ── Update TenantPaymentTransaction on public schema ──────────────────────
    _update_tenant_transaction(
        company, tracking_id, merchant_reference, notification_type, status_result
    )

    # ── Switch to tenant schema and update Invoice / Sale ─────────────────────
    old_schema = connection.schema_name
    try:
        connection.set_tenant(company)
        _update_tenant_invoice(company, tracking_id, merchant_reference, notification_type, status_result)
    except Exception as exc:
        logger.exception('Error updating tenant invoice for %s / %s: %s',
                         tenant_slug, tracking_id, exc)
        log.error = str(exc)
        log.save(update_fields=['error'])
    finally:
        # Always restore public schema
        from django_tenants.utils import get_public_schema_name
        connection.set_schema(get_public_schema_name())

    log.processed = True
    log.save(update_fields=['processed'])
    return _ipn_response(tracking_id, merchant_reference, notification_type, 200)


def _update_tenant_transaction(company, tracking_id, merchant_reference, notification_type, status_result):
    """Update or create a TenantPaymentTransaction on the public schema."""
    STATUS_MAP = {1: 'COMPLETED', 2: 'FAILED', 3: 'REVERSED', 0: 'INVALID'}
    new_status = STATUS_MAP.get(status_result.get('status_code'), 'INVALID')

    try:
        txn = TenantPaymentTransaction.objects.filter(
            order_tracking_id=tracking_id
        ).first() or TenantPaymentTransaction.objects.filter(
            merchant_reference=merchant_reference,
            tenant=company,
        ).first()

        if not txn:
            logger.warning('TenantPaymentTransaction not found: %s / %s', tracking_id, merchant_reference)
            return

        txn.status            = new_status
        txn.status_code       = status_result.get('status_code')
        txn.order_tracking_id = tracking_id
        txn.confirmation_code = status_result.get('confirmation_code') or txn.confirmation_code
        txn.payment_method    = status_result.get('payment_method') or txn.payment_method
        txn.payment_account   = status_result.get('payment_account') or txn.payment_account
        txn.raw_response      = status_result.get('raw')

        if notification_type == 'RECURRING':
            txn.payment_type = 'SUBSCRIPTION'

        if new_status == 'COMPLETED' and not txn.paid_at:
            txn.paid_at = timezone.now()

        txn.save()

    except Exception as exc:
        logger.exception('Error updating TenantPaymentTransaction: %s', exc)


def _update_tenant_invoice(company, tracking_id, merchant_reference, notification_type, status_result):
    """
    Called INSIDE the tenant schema.
    Looks up the invoice/sale by merchant_reference and marks it paid.
    Hooks into your existing Invoice.apply_payment() method.
    """
    STATUS_MAP = {1: 'COMPLETED', 2: 'FAILED', 3: 'REVERSED', 0: 'INVALID'}
    new_status = STATUS_MAP.get(status_result.get('status_code'), 'INVALID')

    if new_status != 'COMPLETED':
        logger.info('Tenant invoice not updated — status is %s for %s', new_status, tracking_id)
        return

    try:
        # merchant_reference format: PP-INV-{invoice_pk}-{hex}
        # Try to resolve the invoice from the reference
        invoice = _resolve_invoice(merchant_reference)
        if not invoice:
            logger.warning('Could not resolve invoice for ref=%s in tenant=%s',
                           merchant_reference, company.schema_name)
            return

        # Already paid — skip
        if invoice.sale.payment_status == 'PAID':
            logger.info('Invoice %s already paid — skipping IPN update', invoice.pk)
            return

        amount = status_result.get('amount') or float(invoice.amount_outstanding)

        invoice.apply_payment(
            amount          = amount,
            payment_method  = 'MOBILE_MONEY',
            user            = None,
            transaction_ref = status_result.get('confirmation_code', tracking_id),
            notes           = f'Pesapal payment | tracking={tracking_id}',
        )

        logger.info('Invoice %s marked paid via Pesapal IPN (tenant=%s)',
                    invoice.pk, company.schema_name)

    except Exception as exc:
        logger.exception('Error marking tenant invoice paid for ref=%s: %s',
                         merchant_reference, exc)
        raise


def _resolve_invoice(merchant_reference: str):
    """
    Decode a merchant_reference back to an Invoice or Sale object.

    Supported formats:
      PP-INV-{pk}-{hex8}   → invoices.Invoice
      PP-SALE-{pk}-{hex8}  → sales.Sale  (no invoice, direct sale payment)
    """
    try:
        parts = merchant_reference.split('-')
        if len(parts) >= 3 and parts[0] == 'PP':
            obj_type = parts[1]
            obj_pk   = int(parts[2])

            if obj_type == 'INV':
                from invoices.models import Invoice
                return Invoice.objects.get(pk=obj_pk)

            elif obj_type == 'SALE':
                # Return a Sale-wrapper that mimics Invoice.apply_payment()
                from sales.models import Sale
                sale = Sale.objects.get(pk=obj_pk)
                return _SalePaymentProxy(sale)

    except Exception as exc:
        logger.debug('Could not resolve object from ref %s: %s', merchant_reference, exc)
    return None


class _SalePaymentProxy:
    """
    Thin wrapper around a Sale object so the IPN handler can call
    .apply_payment() just like it would on an Invoice.
    """
    def __init__(self, sale):
        self._sale = sale

    @property
    def amount_outstanding(self):
        return self._sale.amount_outstanding if hasattr(self._sale, 'amount_outstanding') \
               else self._sale.total_amount

    @property
    def sale(self):
        return self._sale

    def apply_payment(self, amount, payment_method, user, transaction_ref, notes=''):
        from sales.models import Payment
        from django.utils import timezone
        Payment.objects.create(
            sale                  = self._sale,
            store                 = self._sale.store,
            amount                = amount,
            payment_method        = 'MOBILE_MONEY',
            transaction_reference = transaction_ref,
            is_confirmed          = True,
            confirmed_at          = timezone.now(),
            created_by            = user,
            payment_type          = 'FULL',
            notes                 = notes,
        )
        try:
            self._sale.update_payment_status()
        except Exception:
            self._sale.payment_status = 'PAID'
            self._sale.status = 'COMPLETED'
            self._sale.save(update_fields=['payment_status', 'status'])