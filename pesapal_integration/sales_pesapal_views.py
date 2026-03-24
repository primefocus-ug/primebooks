"""
sales/pesapal_views.py
──────────────────────
Pesapal payment views wired into the sales system.

Two flows:
  A) POS redirect   — staff creates sale, Pesapal opens, customer pays,
                       browser redirects to sale detail page.
  B) Send link      — sale saved as PENDING, payment link sent to customer
                       via SMS/email, customer pays remotely.

Add to sales/urls.py:
    path('pesapal/initiate/<int:sale_id>/',
         initiate_pesapal_payment, name='initiate_pesapal_payment'),
    path('pesapal/callback/<int:sale_id>/',
         pesapal_sale_callback, name='pesapal_sale_callback'),
    path('pesapal/send-link/<int:sale_id>/',
         send_payment_link, name='send_payment_link'),
"""

import uuid
import logging

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from .models import Sale, Payment
from .models import TenantPaymentTransaction
from pesapal_integration.service import PesapalService
from pesapal_integration.invoice_payment_views import generate_invoice_payment_url

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_company_from_request(request):
    """Get tenant company — django-tenants sets it on the connection."""
    return getattr(request, 'tenant', None)


def _get_or_register_tenant_ipn(request, company) -> str | None:
    """Get IPN id for this tenant, registering if needed."""
    tenant_slug = company.schema_name
    ipn_url = request.build_absolute_uri(
        f'/pesapal/ipn/tenant/{tenant_slug}/'
    )
    svc = PesapalService.for_tenant(company)
    result = svc.get_or_register_ipn(ipn_url)
    if result['success']:
        # Cache on TenantPesapalConfig
        try:
            cfg = company.pesapal_config
            if not cfg.ipn_id:
                cfg.ipn_id = result['ipn_id']
                cfg.save(update_fields=['ipn_id'])
        except Exception:
            pass
        return result['ipn_id']
    logger.error('IPN registration failed for %s: %s', tenant_slug, result.get('error'))
    return None


def _build_billing_address(sale: Sale) -> dict:
    """Build Pesapal billing_address from Sale customer."""
    customer = sale.customer
    if customer:
        name_parts = (getattr(customer, 'name', '') or '').split(None, 1)
        return {
            'first_name':    name_parts[0][:50] if name_parts else '',
            'last_name':     name_parts[1][:50] if len(name_parts) > 1 else '',
            'email_address': getattr(customer, 'email', '') or '',
            'phone_number':  getattr(customer, 'phone', '') or '',
            'country_code':  'UG',
            'line_1':        getattr(customer, 'physical_address', '') or '',
        }
    return {
        'first_name':    'Walk-in',
        'last_name':     'Customer',
        'email_address': '',
        'phone_number':  '',
        'country_code':  'UG',
        'line_1':        '',
    }


def _create_tenant_transaction(
    company, sale, merchant_reference, tracking_id, redirect_url, flow
) -> None:
    """Record on public schema for IPN routing."""
    TenantPaymentTransaction.objects.create(
        tenant_schema      = company.schema_name,
        tenant             = company,
        merchant_reference = merchant_reference,
        order_tracking_id  = tracking_id,
        amount             = sale.total_amount,
        currency           = sale.currency or 'UGX',
        description        = f'{sale.get_document_type_display()} {sale.document_number}',
        payment_type       = 'INVOICE',
        object_type        = 'sale',
        object_id          = sale.pk,
        redirect_url       = redirect_url,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Option A — POS Redirect
# Called after the sale is already created (AJAX returns sale_id + redirect flag)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def initiate_pesapal_payment(request, sale_id: int):
    """
    AJAX endpoint called from the POS after a sale is created with
    payment_method=MOBILE_MONEY and pesapal_mode=redirect.

    Returns JSON:
      { success: true,  pesapal_url: '...',  sale_detail_url: '...' }
      { success: false, error: '...' }

    The JS then does: window.open(pesapal_url, '_blank') and
    window.location.href = sale_detail_url
    """
    company = _get_company_from_request(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context'}, status=400)

    sale = get_object_or_404(Sale, pk=sale_id)

    # Validate
    if sale.payment_status == 'PAID':
        return JsonResponse({'success': False, 'error': 'Sale already paid'}, status=400)

    amount      = float(sale.total_amount)
    currency    = sale.currency or 'UGX'
    description = f'{sale.get_document_type_display()} {sale.document_number}'

    # Merchant reference: PP-SALE-{pk}-{hex8}
    merchant_reference = f'PP-SALE-{sale.pk}-{uuid.uuid4().hex[:8].upper()}'

    # IPN
    ipn_id = _get_or_register_tenant_ipn(request, company)
    if not ipn_id:
        return JsonResponse({'success': False, 'error': 'Payment setup failed — IPN error'}, status=500)

    # Callback → sale detail page
    callback_url = request.build_absolute_uri(
        reverse('sales:pesapal_sale_callback', kwargs={'sale_id': sale_id})
    )
    cancellation_url = request.build_absolute_uri(
        reverse('sales:sale_detail', kwargs={'pk': sale_id})
    )

    svc = PesapalService.for_tenant(company)
    order_result = svc.submit_order(
        merchant_reference = merchant_reference,
        amount             = amount,
        currency           = currency,
        description        = description,
        notification_id    = ipn_id,
        billing_address    = _build_billing_address(sale),
        callback_url       = callback_url,
        cancellation_url   = cancellation_url,
        branch             = getattr(company, 'name', '')[:50],
    )

    if not order_result['success']:
        logger.error('Pesapal order failed for sale %s: %s', sale_id, order_result.get('error'))
        return JsonResponse({
            'success': False,
            'error':   order_result.get('error', 'Payment initiation failed'),
        }, status=502)

    # Record on public schema
    _create_tenant_transaction(
        company, sale,
        merchant_reference,
        order_result['order_tracking_id'],
        order_result['redirect_url'],
        'pos_redirect',
    )

    # Mark sale as awaiting payment
    sale.payment_status = 'PENDING'
    sale.save(update_fields=['payment_status'])

    sale_detail_url = request.build_absolute_uri(
        reverse('sales:sale_detail', kwargs={'pk': sale_id})
    )

    logger.info('Pesapal POS redirect | sale=%s | tracking=%s',
                sale_id, order_result['order_tracking_id'])

    return JsonResponse({
        'success':        True,
        'pesapal_url':    order_result['redirect_url'],
        'sale_detail_url': sale_detail_url,
        'tracking_id':    order_result['order_tracking_id'],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Option A — Callback  (Pesapal redirects browser here after payment)
# Verifies status then redirects to sale detail
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def pesapal_sale_callback(request, sale_id: int):
    """
    Pesapal redirects the customer/staff browser here after payment.
    Verifies payment status then redirects straight to the sale detail page.
    The sale detail page shows updated payment status.
    """
    company     = _get_company_from_request(request)
    tracking_id = request.GET.get('OrderTrackingId', '')

    sale_detail_url = reverse('sales:sale_detail', kwargs={'pk': sale_id})

    if not tracking_id:
        logger.warning('Pesapal callback for sale %s has no OrderTrackingId', sale_id)
        return redirect(sale_detail_url)

    svc           = PesapalService.for_tenant(company) if company else PesapalService()
    status_result = svc.get_transaction_status(tracking_id)

    if status_result['success']:
        STATUS_MAP = {1: 'PAID', 2: 'FAILED', 3: 'REFUNDED', 0: 'FAILED'}
        new_payment_status = STATUS_MAP.get(status_result.get('status_code'), 'FAILED')

        try:
            sale = Sale.objects.get(pk=sale_id)

            if new_payment_status == 'PAID' and sale.payment_status != 'PAID':
                # Create a confirmed Payment record
                Payment.objects.create(
                    sale               = sale,
                    store              = sale.store,
                    amount             = status_result.get('amount') or sale.total_amount,
                    payment_method     = 'MOBILE_MONEY',
                    transaction_reference = status_result.get('confirmation_code', tracking_id),
                    is_confirmed       = True,
                    confirmed_at       = timezone.now(),
                    created_by         = request.user,
                    payment_type       = 'FULL',
                    notes              = f'Pesapal | {status_result.get("payment_method","")} | {tracking_id}',
                )
                sale.update_payment_status()
                logger.info('Sale %s marked PAID via Pesapal callback', sale_id)

            elif new_payment_status == 'FAILED':
                sale.payment_status = 'PENDING'
                sale.save(update_fields=['payment_status'])
                logger.info('Sale %s payment FAILED via Pesapal callback', sale_id)

        except Sale.DoesNotExist:
            logger.error('Sale %s not found in Pesapal callback', sale_id)

        # Update public-schema transaction
        try:
            txn = TenantPaymentTransaction.objects.filter(
                order_tracking_id=tracking_id
            ).first()
            if txn:
                txn.status            = 'COMPLETED' if new_payment_status == 'PAID' else 'FAILED'
                txn.confirmation_code = status_result.get('confirmation_code', '')
                txn.payment_method    = status_result.get('payment_method', '')
                if new_payment_status == 'PAID':
                    txn.paid_at = timezone.now()
                txn.save()
        except Exception as exc:
            logger.error('TenantPaymentTransaction update error: %s', exc)

    # Always end up on sale detail
    return redirect(sale_detail_url)


# ─────────────────────────────────────────────────────────────────────────────
# Option B — Send Payment Link
# Sale already exists → generate token URL → send to customer
# ─────────────────────────────────────────────────────────────────────────────

@login_required
@require_POST
def send_payment_link(request, sale_id: int):
    """
    AJAX endpoint — generates a public Pesapal payment link for this sale
    and sends it to the customer via email and/or SMS.

    Returns JSON:
      { success: true,  payment_url: '...',  sent_to: 'email/phone/both' }
      { success: false, error: '...' }
    """
    company = _get_company_from_request(request)
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context'}, status=400)

    sale = get_object_or_404(Sale, pk=sale_id)

    if sale.payment_status == 'PAID':
        return JsonResponse({'success': False, 'error': 'Sale already paid'}, status=400)

    if not sale.customer:
        return JsonResponse({
            'success': False,
            'error': 'A customer must be selected to send a payment link.',
        }, status=400)

    customer = sale.customer
    email    = getattr(customer, 'email', '') or ''
    phone    = getattr(customer, 'phone', '') or ''

    if not email and not phone:
        return JsonResponse({
            'success': False,
            'error': 'Customer has no email or phone number on record.',
        }, status=400)

    # Build the public invoice payment URL
    # This reuses the existing InvoicePaymentView logic via the token URL
    payment_url = _build_sale_payment_url(request, company, sale)

    # Mark sale as pending payment if not already
    if sale.payment_status not in ('PENDING', 'PENDING_PAYMENT'):
        sale.payment_status = 'PENDING_PAYMENT'
        sale.save(update_fields=['payment_status'])

    sent_to = []

    # Send email
    if email:
        try:
            _send_payment_link_email(sale, customer, payment_url, company)
            sent_to.append('email')
        except Exception as exc:
            logger.error('Email send failed for sale %s: %s', sale_id, exc)

    # Send SMS (hook into your existing SMS service)
    if phone:
        try:
            _send_payment_link_sms(sale, customer, payment_url, phone)
            sent_to.append('SMS')
        except Exception as exc:
            logger.error('SMS send failed for sale %s: %s', sale_id, exc)

    if not sent_to:
        return JsonResponse({
            'success': False,
            'error': 'Could not send payment link — check email/SMS configuration.',
        }, status=500)

    logger.info('Payment link sent for sale %s to %s', sale_id, ', '.join(sent_to))

    return JsonResponse({
        'success':     True,
        'payment_url': payment_url,
        'sent_to':     ' & '.join(sent_to),
        'customer':    customer.name,
    })


def _build_sale_payment_url(request, company, sale: Sale) -> str:
    """
    Build a public payment URL for a sale.
    Uses the token-based invoice payment system we built.
    If the sale has an invoice_detail, use its pk.
    Otherwise create a direct sale payment URL.
    """
    # Try to get linked invoice pk
    invoice_pk = None
    try:
        invoice = sale.invoice_detail
        invoice_pk = invoice.pk
    except Exception:
        pass

    if invoice_pk:
        # Use the existing invoice payment URL system
        return generate_invoice_payment_url(
            request,
            tenant_slug = company.schema_name,
            invoice_pk  = invoice_pk,
        )
    else:
        # Generate a direct sale payment URL using the same token system
        from pesapal_integration.invoice_payment_views import _make_token
        token = _make_token(f'sale:{company.schema_name}', sale.pk)
        return request.build_absolute_uri(f'/pay/sale/{token}/')


def _send_payment_link_email(sale, customer, payment_url, company):
    """Send payment link email to customer."""
    from django.core.mail import send_mail
    from django.template.loader import render_to_string

    subject = f'Payment Link — {sale.document_number} | {company.name}'
    amount  = f'{sale.currency} {sale.total_amount:,.0f}'

    # Try template first, fall back to plain text
    try:
        html_body = render_to_string('sales/emails/payment_link.html', {
            'sale':        sale,
            'customer':    customer,
            'payment_url': payment_url,
            'company':     company,
            'amount':      amount,
        })
    except Exception:
        html_body = None

    plain_body = (
        f'Dear {customer.name},\n\n'
        f'Please complete your payment of {amount} for {sale.document_number}.\n\n'
        f'Click the link below to pay securely:\n{payment_url}\n\n'
        f'Thank you,\n{company.name}'
    )

    send_mail(
        subject      = subject,
        message      = plain_body,
        from_email   = settings.DEFAULT_FROM_EMAIL,
        recipient_list = [customer.email],
        html_message = html_body,
        fail_silently = False,
    )


def _send_payment_link_sms(sale, customer, payment_url, phone):
    """
    Send payment link via SMS.
    Hook into your existing SMS service here.
    Currently uses a stub — replace with your SMS provider.
    """
    message = (
        f'Hi {customer.name}, pay {sale.currency} {sale.total_amount:,.0f} '
        f'for {sale.document_number} via: {payment_url}'
    )

    # ── Hook your SMS provider here ──────────────────────────────────────────
    # Example with Africa's Talking:
    # import africastalking
    # africastalking.initialize(username, api_key)
    # sms = africastalking.SMS
    # sms.send(message, [phone])

    # Example with Twilio:
    # from twilio.rest import Client
    # client = Client(account_sid, auth_token)
    # client.messages.create(body=message, from_='+256...', to=phone)

    # For now — log it (replace with real SMS call)
    logger.info('SMS (stub) to %s: %s', phone, message)
    # Uncomment the line below if you have no SMS provider yet —
    # it will raise so the caller knows it wasn't actually sent:
    # raise NotImplementedError('SMS provider not configured')
