"""
pesapal_integration/invoice_payment_views.py
─────────────────────────────────────────────
Public invoice payment flow.
No login required — customer receives a URL and pays directly.

URL patterns to add to your main urls.py (outside tenant middleware):
    path('pay/invoice/<str:token>/',
         InvoicePaymentView.as_view(), name='pay_invoice'),
    path('pay/invoice/<str:token>/callback/',
         InvoicePaymentCallbackView.as_view(), name='pay_invoice_callback'),
    path('pay/invoice/<str:token>/cancelled/',
         InvoicePaymentCancelledView.as_view(), name='pay_invoice_cancelled'),
"""

import hashlib
import hmac
import logging
import uuid

from django.conf import settings
from django.db import connection
from django.http import Http404
from django.shortcuts import render, redirect
from django.utils import timezone
from django.views import View
from django_tenants.utils import get_public_schema_name

from .models import TenantPaymentTransaction
from pesapal_integration.service import PesapalService

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Token helpers — encode / decode invoice pk + tenant into a signed URL token
# ─────────────────────────────────────────────────────────────────────────────

def _make_token(tenant_slug: str, invoice_pk: int) -> str:
    """
    Create a signed token: base16(tenant_slug:invoice_pk):hmac
    so that the public URL cannot be guessed or tampered with.
    """
    payload   = f'{tenant_slug}:{invoice_pk}'
    signature = hmac.new(
        settings.SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f'{payload.encode().hex()}:{signature}'


def _decode_token(token: str):
    """
    Returns (tenant_slug, invoice_pk) or raises Http404.
    """
    try:
        hex_payload, signature = token.rsplit(':', 1)
        payload   = bytes.fromhex(hex_payload).decode()
        tenant_slug, invoice_pk_str = payload.split(':', 1)
        invoice_pk = int(invoice_pk_str)

        expected_sig = hmac.new(
            settings.SECRET_KEY.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()[:16]

        if not hmac.compare_digest(signature, expected_sig):
            raise ValueError('Invalid signature')

        return tenant_slug, invoice_pk
    except Exception:
        raise Http404('Invalid payment link')


def generate_invoice_payment_url(request, tenant_slug: str, invoice_pk: int) -> str:
    """
    Call this from inside a tenant view to produce the public payment URL
    to embed in the invoice email / PDF.
    """
    token = _make_token(tenant_slug, invoice_pk)
    return request.build_absolute_uri(f'/pay/invoice/{token}/')


# ─────────────────────────────────────────────────────────────────────────────
# Helpers to switch into / out of a tenant schema
# ─────────────────────────────────────────────────────────────────────────────

def _get_company(tenant_slug: str):
    from company.models import Company
    try:
        return Company.objects.get(schema_name=tenant_slug)
    except Company.DoesNotExist:
        raise Http404('Company not found')


def _switch_tenant(company):
    connection.set_tenant(company)


def _switch_public():
    connection.set_schema(get_public_schema_name())


def _get_invoice_in_tenant(invoice_pk: int):
    """Must be called AFTER switching to the tenant schema."""
    from invoices.models import Invoice
    try:
        return Invoice.objects.select_related('sale', 'sale__customer', 'sale__store').get(pk=invoice_pk)
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# View 1 — Show invoice summary + "Pay Now" button
# ─────────────────────────────────────────────────────────────────────────────

class InvoicePaymentView(View):
    """
    Public page — shows invoice details and initiates Pesapal redirect.
    GET  → show invoice summary
    POST → create order, redirect to Pesapal
    """

    def _get_context(self, token):
        tenant_slug, invoice_pk = _decode_token(token)
        company = _get_company(tenant_slug)

        _switch_tenant(company)
        try:
            invoice = _get_invoice_in_tenant(invoice_pk)
            if not invoice:
                raise Http404('Invoice not found')
            return company, invoice, tenant_slug, invoice_pk
        finally:
            _switch_public()

    def get(self, request, token, *args, **kwargs):
        tenant_slug, invoice_pk = _decode_token(token)
        company = _get_company(tenant_slug)

        _switch_tenant(company)
        try:
            invoice = _get_invoice_in_tenant(invoice_pk)
            if not invoice:
                raise Http404('Invoice not found')

            # Check if already paid
            already_paid = invoice.sale.payment_status == 'PAID'

            context = {
                'invoice':      invoice,
                'company':      company,
                'token':        token,
                'already_paid': already_paid,
                'amount':       invoice.amount_outstanding,
                'currency':     invoice.currency_code,
            }
            return render(request, 'invoice_payment/payment_page.html', context)
        finally:
            _switch_public()

    def post(self, request, token, *args, **kwargs):
        tenant_slug, invoice_pk = _decode_token(token)
        company = _get_company(tenant_slug)

        _switch_tenant(company)
        try:
            invoice = _get_invoice_in_tenant(invoice_pk)
            if not invoice:
                raise Http404('Invoice not found')

            if invoice.sale.payment_status == 'PAID':
                return redirect(f'/pay/invoice/{token}/')

            amount   = float(invoice.amount_outstanding)
            currency = invoice.currency_code or 'UGX'
            customer = invoice.customer

            billing_address = {
                'email_address': getattr(customer, 'email', '') or '',
                'phone_number':  getattr(customer, 'phone', '') or '',
                'first_name':    (getattr(customer, 'name', '') or '').split()[0][:50],
                'last_name':     ' '.join((getattr(customer, 'name', '') or '').split()[1:])[:50],
                'country_code':  'UG',
            }

            # Merchant reference: PP-INV-{pk}-{hex8}
            merchant_reference = f'PP-INV-{invoice_pk}-{uuid.uuid4().hex[:8].upper()}'
            description        = f'Invoice {invoice.invoice_number} | {company.name[:40]}'

        finally:
            _switch_public()

        # Get IPN id for this tenant
        svc     = PesapalService.for_tenant(company)
        ipn_url = _build_tenant_ipn_url(request, tenant_slug)
        ipn_res = svc.get_or_register_ipn(ipn_url)

        if not ipn_res['success']:
            logger.error('IPN registration failed for %s: %s', tenant_slug, ipn_res.get('error'))
            return render(request, 'invoice_payment/error.html', {
                'message': 'Payment setup failed. Please contact support.'
            })

        # Update tenant config with ipn_id if using own keys
        try:
            cfg = company.pesapal_config
            if not cfg.ipn_id:
                cfg.ipn_id = ipn_res['ipn_id']
                cfg.save(update_fields=['ipn_id'])
        except Exception:
            pass

        callback_url     = request.build_absolute_uri(f'/pay/invoice/{token}/callback/')
        cancellation_url = request.build_absolute_uri(f'/pay/invoice/{token}/cancelled/')

        order_result = svc.submit_order(
            merchant_reference = merchant_reference,
            amount             = amount,
            currency           = currency,
            description        = description,
            notification_id    = ipn_res['ipn_id'],
            billing_address    = billing_address,
            callback_url       = callback_url,
            cancellation_url   = cancellation_url,
            branch             = getattr(company, 'name', '')[:50],
        )

        if not order_result['success']:
            logger.error('Order submission failed for tenant %s invoice %s: %s',
                         tenant_slug, invoice_pk, order_result.get('error'))
            return render(request, 'invoice_payment/error.html', {
                'message': 'Could not initiate payment. Please try again later.'
            })

        # Record the transaction on public schema
        TenantPaymentTransaction.objects.create(
            tenant_schema      = tenant_slug,
            tenant             = company,
            merchant_reference = merchant_reference,
            order_tracking_id  = order_result['order_tracking_id'],
            amount             = amount,
            currency           = currency,
            description        = description,
            payment_type       = 'INVOICE',
            object_type        = 'invoice',
            object_id          = invoice_pk,
            redirect_url       = order_result['redirect_url'],
        )

        logger.info('Invoice payment initiated | tenant=%s invoice=%s tracking=%s',
                    tenant_slug, invoice_pk, order_result['order_tracking_id'])

        return redirect(order_result['redirect_url'])


def _build_tenant_ipn_url(request, tenant_slug: str) -> str:
    """Build the absolute IPN URL for this tenant."""
    return request.build_absolute_uri(f'/pesapal/ipn/tenant/{tenant_slug}/')


# ─────────────────────────────────────────────────────────────────────────────
# View 2 — Callback  (customer browser lands here after payment)
# ─────────────────────────────────────────────────────────────────────────────

class InvoicePaymentCallbackView(View):
    """
    No login required.
    Verifies payment status and shows result to customer.
    """

    def get(self, request, token, *args, **kwargs):
        tenant_slug, invoice_pk = _decode_token(token)
        company     = _get_company(tenant_slug)
        tracking_id = request.GET.get('OrderTrackingId', '')

        status_result = None
        invoice_data  = {}

        if tracking_id:
            svc           = PesapalService.for_tenant(company)
            status_result = svc.get_transaction_status(tracking_id)

            if status_result['success'] and status_result.get('status_code') == 1:
                # Mark as paid inside tenant schema
                _switch_tenant(company)
                try:
                    invoice = _get_invoice_in_tenant(invoice_pk)
                    if invoice and invoice.sale.payment_status != 'PAID':
                        amount = status_result.get('amount') or float(invoice.amount_outstanding)
                        try:
                            invoice.apply_payment(
                                amount          = amount,
                                payment_method  = 'MOBILE_MONEY',
                                user            = None,
                                transaction_ref = status_result.get('confirmation_code', tracking_id),
                                notes           = f'Pesapal online payment | tracking={tracking_id}',
                            )
                        except Exception as e:
                            logger.error('apply_payment error: %s', e)

                    if invoice:
                        invoice_data = {
                            'number':   invoice.invoice_number,
                            'amount':   invoice.total_amount,
                            'currency': invoice.currency_code,
                        }
                finally:
                    _switch_public()

                # Update TenantPaymentTransaction
                try:
                    txn = TenantPaymentTransaction.objects.filter(
                        order_tracking_id=tracking_id
                    ).first()
                    if txn:
                        txn.status            = 'COMPLETED'
                        txn.confirmation_code = status_result.get('confirmation_code', '')
                        txn.payment_method    = status_result.get('payment_method', '')
                        txn.paid_at           = timezone.now()
                        txn.save()
                except Exception as exc:
                    logger.error('TenantPaymentTransaction update error: %s', exc)

        context = {
            'status_result': status_result,
            'invoice_data':  invoice_data,
            'tracking_id':   tracking_id,
            'token':         token,
            'company':       company,
        }
        return render(request, 'invoice_payment/callback.html', context)


# ─────────────────────────────────────────────────────────────────────────────
# View 3 — Cancelled
# ─────────────────────────────────────────────────────────────────────────────

class InvoicePaymentCancelledView(View):
    def get(self, request, token, *args, **kwargs):
        tenant_slug, invoice_pk = _decode_token(token)
        company = _get_company(tenant_slug)
        return render(request, 'invoice_payment/cancelled.html', {
            'token':   token,
            'company': company,
        })
