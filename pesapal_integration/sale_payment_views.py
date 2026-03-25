"""
pesapal_integration/sale_payment_views.py
──────────────────────────────────────────
Public payment page for a Sale (no invoice required).
Used by Option B when the sale doesn't have a linked Invoice object.

Add to tenancy/public_urls.py:
    path('pay/sale/<str:token>/',
         SalePaymentView.as_view(), name='pay_sale'),
    path('pay/sale/<str:token>/callback/',
         SalePaymentCallbackView.as_view(), name='pay_sale_callback'),
    path('pay/sale/<str:token>/cancelled/',
         SalePaymentCancelledView.as_view(), name='pay_sale_cancelled'),
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
# Token helpers — sale:schema_name + sale_pk
# ─────────────────────────────────────────────────────────────────────────────

def _make_sale_token(tenant_slug: str, sale_pk: int) -> str:
    payload   = f'sale:{tenant_slug}:{sale_pk}'
    signature = hmac.new(
        settings.SECRET_KEY.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]
    return f'{payload.encode().hex()}:{signature}'


def _decode_sale_token(token: str):
    try:
        hex_payload, signature = token.rsplit(':', 1)
        payload = bytes.fromhex(hex_payload).decode()
        # format: sale:{tenant_slug}:{sale_pk}
        _, tenant_slug, sale_pk_str = payload.split(':', 2)
        sale_pk = int(sale_pk_str)

        expected = hmac.new(
            settings.SECRET_KEY.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()[:16]

        if not hmac.compare_digest(signature, expected):
            raise ValueError('Bad signature')

        return tenant_slug, sale_pk
    except Exception:
        raise Http404('Invalid payment link')


def _get_company(tenant_slug: str):
    from company.models import Company
    try:
        return Company.objects.get(schema_name=tenant_slug)
    except Company.DoesNotExist:
        raise Http404


def _switch_tenant(company):
    connection.set_tenant(company)


def _switch_public():
    connection.set_schema(get_public_schema_name())


def _get_sale(sale_pk: int):
    """Must be called inside tenant schema."""
    from sales.models import Sale
    try:
        return (Sale.objects
                .select_related('customer', 'store')
                .get(pk=sale_pk))
    except Sale.DoesNotExist:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# View 1 — Payment page
# ─────────────────────────────────────────────────────────────────────────────

class SalePaymentView(View):

    def get(self, request, token):
        tenant_slug, sale_pk = _decode_sale_token(token)
        company = _get_company(tenant_slug)

        _switch_tenant(company)
        try:
            sale = _get_sale(sale_pk)
            if not sale:
                raise Http404('Sale not found')

            already_paid = sale.payment_status == 'PAID'
            context = {
                'sale':        sale,
                'company':     company,
                'token':       token,
                'already_paid': already_paid,
                'amount':      sale.amount_outstanding if hasattr(sale, 'amount_outstanding') else sale.total_amount,
                'currency':    sale.currency or 'UGX',
            }
            return render(request, 'invoice_payment/sale_payment_page.html', context)
        finally:
            _switch_public()

    def post(self, request, token):
        tenant_slug, sale_pk = _decode_sale_token(token)
        company = _get_company(tenant_slug)

        _switch_tenant(company)
        try:
            sale = _get_sale(sale_pk)
            if not sale:
                raise Http404('Sale not found')

            if sale.payment_status == 'PAID':
                return redirect(f'/pay/sale/{token}/')

            amount   = float(sale.total_amount)
            currency = sale.currency or 'UGX'
            customer = sale.customer

            billing_address = {
                'first_name':    '',
                'last_name':     '',
                'email_address': '',
                'phone_number':  '',
                'country_code':  'UG',
            }
            if customer:
                name_parts = (getattr(customer, 'name', '') or '').split(None, 1)
                billing_address.update({
                    'first_name':    name_parts[0][:50] if name_parts else '',
                    'last_name':     name_parts[1][:50] if len(name_parts) > 1 else '',
                    'email_address': getattr(customer, 'email', '') or '',
                    'phone_number':  getattr(customer, 'phone', '') or '',
                })

            merchant_reference = f'PP-SALE-{sale_pk}-{uuid.uuid4().hex[:8].upper()}'
            description        = f'{sale.get_document_type_display()} {sale.document_number} | {company.name[:30]}'

        finally:
            _switch_public()

        # IPN + order
        svc     = PesapalService.for_tenant(company)
        ipn_url = request.build_absolute_uri(f'/pesapal/ipn/tenant/{tenant_slug}/')
        ipn_res = svc.get_or_register_ipn(ipn_url)

        if not ipn_res['success']:
            return render(request, 'invoice_payment/error.html', {
                'message': 'Payment setup failed. Please contact support.',
                'company': company,
            })

        callback_url     = request.build_absolute_uri(f'/pay/sale/{token}/callback/')
        cancellation_url = request.build_absolute_uri(f'/pay/sale/{token}/cancelled/')

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
            return render(request, 'invoice_payment/error.html', {
                'message': 'Could not initiate payment. Please try again later.',
                'company': company,
            })

        # Record on public schema
        TenantPaymentTransaction.objects.create(
            tenant_schema      = tenant_slug,
            tenant             = company,
            merchant_reference = merchant_reference,
            order_tracking_id  = order_result['order_tracking_id'],
            amount             = amount,
            currency           = currency,
            description        = description,
            payment_type       = 'INVOICE',
            object_type        = 'sale',
            object_id          = sale_pk,
            redirect_url       = order_result['redirect_url'],
        )

        logger.info('Sale payment initiated | tenant=%s sale=%s tracking=%s',
                    tenant_slug, sale_pk, order_result['order_tracking_id'])

        return redirect(order_result['redirect_url'])


# ─────────────────────────────────────────────────────────────────────────────
# View 2 — Callback
# ─────────────────────────────────────────────────────────────────────────────

class SalePaymentCallbackView(View):

    def get(self, request, token):
        tenant_slug, sale_pk = _decode_sale_token(token)
        company     = _get_company(tenant_slug)
        tracking_id = request.GET.get('OrderTrackingId', '')

        status_result = None
        sale_data     = {}

        if tracking_id:
            svc           = PesapalService.for_tenant(company)
            status_result = svc.get_transaction_status(tracking_id)

            if status_result['success'] and status_result.get('status_code') == 1:
                _switch_tenant(company)
                try:
                    sale = _get_sale(sale_pk)
                    if sale and sale.payment_status != 'PAID':
                        from sales.models import Payment
                        Payment.objects.create(
                            sale              = sale,
                            store             = sale.store,
                            amount            = status_result.get('amount') or sale.total_amount,
                            payment_method    = 'MOBILE_MONEY',
                            transaction_reference = status_result.get('confirmation_code', tracking_id),
                            is_confirmed      = True,
                            confirmed_at      = timezone.now(),
                            created_by        = None,
                            payment_type      = 'FULL',
                            notes             = f'Pesapal | {tracking_id}',
                        )
                        try:
                            sale.update_payment_status()
                        except Exception:
                            sale.payment_status = 'PAID'
                            sale.status = 'COMPLETED'
                            sale.save(update_fields=['payment_status', 'status'])

                    if sale:
                        sale_data = {
                            'number':   sale.document_number,
                            'amount':   sale.total_amount,
                            'currency': sale.currency or 'UGX',
                        }
                finally:
                    _switch_public()

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
                    logger.error('TxnUpdate error: %s', exc)

        return render(request, 'invoice_payment/callback.html', {
            'status_result': status_result,
            'invoice_data':  sale_data,
            'tracking_id':   tracking_id,
            'token':         token,
            'company':       company,
        })


# ─────────────────────────────────────────────────────────────────────────────
# View 3 — Cancelled
# ─────────────────────────────────────────────────────────────────────────────

class SalePaymentCancelledView(View):
    def get(self, request, token):
        tenant_slug, sale_pk = _decode_sale_token(token)
        company = _get_company(tenant_slug)
        return render(request, 'invoice_payment/cancelled.html', {
            'token': token, 'company': company,
        })
