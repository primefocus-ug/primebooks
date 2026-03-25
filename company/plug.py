from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.utils import timezone
from django.core.cache import cache

from company.models import AvailableModule, CompanyModule
from pesapal_integration.service import PesapalService
from pesapal_integration.models import PlatformInvoice

import uuid
import logging
from datetime import timedelta

logger = logging.getLogger(__name__)

# How many days a paid module activation lasts.
# IPN/callback set paid_through = payment_date + MODULE_BILLING_DAYS.
MODULE_BILLING_DAYS = 30


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _check_module_dependencies(module, company_module_map):
    for dep in module.dependencies.all():
        cm = company_module_map.get(dep.id)
        if not cm or not cm.is_active:
            return False
    return True


def _has_pending_payment(company, module):
    return PlatformInvoice.objects.filter(
        company=company,
        module=module,
        status='PENDING',
    ).exists()


def _clear_module_cache(schema_name):
    cache.delete(f'active_modules:{schema_name}')


# ─────────────────────────────────────────────────────────────────────────────
# Module Store — listing
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def module_store(request):
    all_modules = AvailableModule.objects.filter(
        is_publicly_available=True
    ).prefetch_related('dependencies')

    company_module_map = {
        cm.module_id: cm
        for cm in CompanyModule.objects.filter(
            company=request.tenant
        ).select_related('module')
    }

    modules_with_status = []
    for module in all_modules:
        cm = company_module_map.get(module.id)
        modules_with_status.append({
            'module':             module,
            'is_active':          cm.is_active if cm else False,
            'activated_at':       cm.activated_at if cm else None,
            'deactivated_at':     cm.deactivated_at if cm else None,
            'paid_through':       cm.paid_through if cm else None,
            # True when inactive but still inside the paid billing window.
            # Controls which button the template renders.
            'within_paid_period': cm.within_paid_period if cm else False,
            'dependencies_met':   _check_module_dependencies(module, company_module_map),
            'is_paid':            module.monthly_price > 0,
            'has_pending_payment': _has_pending_payment(request.tenant, module),
        })

    return render(request, 'company/module_store.html', {
        'modules_with_status': modules_with_status,
        'title': 'App Store',
    })


# ─────────────────────────────────────────────────────────────────────────────
# Free-module activation
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def activate_module(request, module_key):
    if request.method != 'POST':
        return redirect('companies:module_store')

    module = get_object_or_404(AvailableModule, key=module_key)

    if module.monthly_price > 0:
        messages.warning(
            request,
            f"'{module.label}' requires payment. Use the payment button to activate it."
        )
        return redirect('companies:module_store')

    for dep in module.dependencies.all():
        dep_active = CompanyModule.objects.filter(
            company=request.tenant, module=dep, is_active=True,
        ).exists()
        if not dep_active:
            messages.error(
                request,
                f"'{module.label}' requires '{dep.label}' to be activated first."
            )
            return redirect('companies:module_store')

    cm, _ = CompanyModule.objects.get_or_create(
        company=request.tenant, module=module,
    )
    cm.activate()   # free module — no paid_through
    _clear_module_cache(request.tenant.schema_name)

    messages.success(request, f'✅ {module.label} has been activated!')
    return redirect('companies:module_store')


# ─────────────────────────────────────────────────────────────────────────────
# Free reactivation within paid window
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def reactivate_module(request, module_key):
    """
    Reactivate a paid module that was temporarily deactivated while the
    billing window is still open.  No Pesapal interaction.
    URL: POST companies/app-store/reactivate/<module_key>/
    """
    if request.method != 'POST':
        return redirect('companies:module_store')

    module  = get_object_or_404(AvailableModule, key=module_key)
    company = request.tenant
    cm      = CompanyModule.objects.filter(company=company, module=module).first()

    if not cm:
        messages.error(request, f"No record found for '{module.label}'.")
        return redirect('companies:module_store')

    if cm.is_active:
        messages.info(request, f'{module.label} is already active.')
        return redirect('companies:module_store')

    if not cm.within_paid_period:
        messages.warning(
            request,
            f"Your paid period for '{module.label}' has expired. "
            "Please complete a new payment to reactivate."
        )
        return redirect('companies:module_store')

    for dep in module.dependencies.all():
        dep_active = CompanyModule.objects.filter(
            company=company, module=dep, is_active=True,
        ).exists()
        if not dep_active:
            messages.error(
                request,
                f"'{module.label}' requires '{dep.label}' to be activated first."
            )
            return redirect('companies:module_store')

    # Reactivate — paid_through is deliberately NOT changed here
    cm.activate()
    _clear_module_cache(company.schema_name)

    logger.info('Module %s reactivated within paid period for %s (paid_through=%s)',
                module_key, company.schema_name, cm.paid_through)

    messages.success(
        request,
        f'✅ {module.label} reactivated — '
        f'paid until {cm.paid_through.strftime("%d %b %Y")}.'
    )
    return redirect('companies:module_store')


# ─────────────────────────────────────────────────────────────────────────────
# Deactivation
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def deactivate_module(request, module_key):
    """
    Switch a module OFF.
    paid_through is preserved so reactivation within the window is free.
    """
    if request.method != 'POST':
        return redirect('companies:module_store')

    module = get_object_or_404(AvailableModule, key=module_key)

    dependants = AvailableModule.objects.filter(dependencies=module)
    for dep in dependants:
        dep_active = CompanyModule.objects.filter(
            company=request.tenant, module=dep, is_active=True,
        ).exists()
        if dep_active:
            messages.error(
                request,
                f"Cannot deactivate '{module.label}' — "
                f"'{dep.label}' depends on it. Deactivate '{dep.label}' first."
            )
            return redirect('companies:module_store')

    cm = get_object_or_404(CompanyModule, company=request.tenant, module=module)
    cm.deactivate()   # paid_through is untouched inside deactivate()
    _clear_module_cache(request.tenant.schema_name)

    if cm.within_paid_period:
        messages.warning(
            request,
            f"⚠️ {module.label} deactivated. "
            f"Reactivate for free any time before "
            f"{cm.paid_through.strftime('%d %b %Y')}."
        )
    else:
        messages.warning(request, f'⚠️ {module.label} has been deactivated.')

    return redirect('companies:module_store')


# ─────────────────────────────────────────────────────────────────────────────
# Paid-module payment flow
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def initiate_module_payment(request, module_key):
    """
    Step 1 — Create PlatformInvoice, submit to Pesapal, redirect tenant.
    URL: POST companies/app-store/pay/<module_key>/
    """
    if request.method != 'POST':
        return redirect('companies:module_store')

    module  = get_object_or_404(AvailableModule, key=module_key, is_publicly_available=True)
    company = request.tenant

    if module.monthly_price <= 0:
        return redirect('companies:activate_module', module_key=module_key)

    cm = CompanyModule.objects.filter(company=company, module=module).first()

    if cm and cm.is_active:
        messages.info(request, f'{module.label} is already active.')
        return redirect('companies:module_store')

    # Belt-and-suspenders: if they somehow reach this URL while still in the
    # paid window, just reactivate for free rather than charging them again.
    if cm and cm.within_paid_period:
        messages.info(request, f"'{module.label}' reactivated — still within your paid period.")
        cm.activate()
        _clear_module_cache(company.schema_name)
        return redirect('companies:module_store')

    for dep in module.dependencies.all():
        dep_active = CompanyModule.objects.filter(
            company=company, module=dep, is_active=True,
        ).exists()
        if not dep_active:
            messages.error(
                request,
                f"'{module.label}' requires '{dep.label}' to be activated first."
            )
            return redirect('companies:module_store')

    if _has_pending_payment(company, module):
        messages.warning(
            request,
            f"A payment for '{module.label}' is already in progress. "
            "Please complete it or wait a few minutes before trying again."
        )
        return redirect('companies:module_store')

    amount             = float(module.monthly_price)
    currency           = 'UGX'
    merchant_reference = f'MOD-{module_key.upper()[:20]}-{uuid.uuid4().hex[:8].upper()}'
    description        = f'Module: {module.label} | {company.name[:40]}'

    user = request.user
    billing_address = {
        'email_address': getattr(user, 'email', '') or '',
        'phone_number':  getattr(user, 'phone', '') or '',
        'first_name':    (getattr(user, 'first_name', '') or getattr(user, 'username', ''))[:50],
        'last_name':     getattr(user, 'last_name', '')[:50],
        'country_code':  'UG',
    }

    svc     = PesapalService()
    ipn_url = request.build_absolute_uri('/pesapal/ipn/platform/')
    ipn_res = svc.get_or_register_ipn(ipn_url)

    if not ipn_res['success']:
        logger.error('IPN registration failed: tenant=%s module=%s err=%s',
                     company.schema_name, module_key, ipn_res.get('error'))
        messages.error(request, 'Payment setup failed. Please try again or contact support.')
        return redirect('companies:module_store')

    callback_url     = request.build_absolute_uri(
        reverse('companies:module_payment_callback', kwargs={'module_key': module_key})
    )
    cancellation_url = request.build_absolute_uri(
        reverse('companies:module_payment_cancelled', kwargs={'module_key': module_key})
    )

    order_result = svc.submit_order(
        merchant_reference = merchant_reference,
        amount             = amount,
        currency           = currency,
        description        = description,
        notification_id    = ipn_res['ipn_id'],
        billing_address    = billing_address,
        callback_url       = callback_url,
        cancellation_url   = cancellation_url,
        branch             = company.name[:50],
    )

    if not order_result['success']:
        logger.error('Order submission failed: tenant=%s module=%s err=%s',
                     company.schema_name, module_key, order_result.get('error'))
        messages.error(request, 'Could not initiate payment. Please try again later.')
        return redirect('companies:module_store')

    PlatformInvoice.objects.create(
        company             = company,
        module              = module,
        plan                = None,
        amount              = amount,
        currency            = currency,
        description         = description,
        merchant_reference  = merchant_reference,
        pesapal_tracking_id = order_result['order_tracking_id'],
        redirect_url        = order_result['redirect_url'],
        status              = 'PENDING',
    )

    logger.info('Module payment initiated | tenant=%s module=%s tracking=%s',
                company.schema_name, module_key, order_result['order_tracking_id'])

    return redirect(order_result['redirect_url'])


@login_required
def module_payment_callback(request, module_key):
    """
    Step 2 — Pesapal redirects here after payment.
    URL: GET companies/app-store/pay/<module_key>/callback/?OrderTrackingId=...
    """
    module      = get_object_or_404(AvailableModule, key=module_key)
    company     = request.tenant
    tracking_id = request.GET.get('OrderTrackingId', '')

    if not tracking_id:
        messages.error(request, 'Payment verification failed — no tracking ID received.')
        return redirect('companies:module_store')

    svc           = PesapalService()
    status_result = svc.get_transaction_status(tracking_id)

    if not status_result['success']:
        logger.error('Status check failed: tenant=%s tracking=%s err=%s',
                     company.schema_name, tracking_id, status_result.get('error'))
        messages.error(request, 'Could not verify payment status. Please contact support.')
        return redirect('companies:module_store')

    status_code = status_result.get('status_code')

    if status_code == 1:
        paid_through = (timezone.now() + timedelta(days=MODULE_BILLING_DAYS)).date()

        cm, _ = CompanyModule.objects.get_or_create(company=company, module=module)
        if not cm.is_active:
            cm.activate(paid_through=paid_through)
            _clear_module_cache(company.schema_name)
            logger.info('Module %s activated for %s via callback (tracking=%s, paid_through=%s)',
                        module_key, company.schema_name, tracking_id, paid_through)
        else:
            # IPN beat the callback — just ensure paid_through is set
            cm.paid_through = paid_through
            cm.save(update_fields=['paid_through'])

        try:
            inv = PlatformInvoice.objects.filter(
                pesapal_tracking_id=tracking_id, company=company,
            ).first()
            if inv and inv.status != 'PAID':
                inv.status               = 'PAID'
                inv.pesapal_confirmation = status_result.get('confirmation_code', '')
                inv.payment_method       = status_result.get('payment_method', '')
                inv.payment_account      = status_result.get('payment_account', '')
                inv.paid_at              = timezone.now()
                inv.save()
        except Exception as exc:
            logger.error('PlatformInvoice update error in callback: %s', exc)

        messages.success(
            request,
            f'✅ {module.label} activated! '
            f'Subscription runs until {paid_through.strftime("%d %b %Y")}.'
        )
        return redirect('companies:module_store')

    status_description = status_result.get('status_description', 'Unknown')
    logger.warning('Module payment not completed: tenant=%s module=%s status=%s tracking=%s',
                   company.schema_name, module_key, status_description, tracking_id)

    messages.error(
        request,
        f"Payment was not completed (status: {status_description}). "
        "No charge was made. You can try again from the App Store."
    )
    return redirect('companies:module_store')


@login_required
def module_payment_cancelled(request, module_key):
    """Pesapal redirects here when the user cancels."""
    module      = get_object_or_404(AvailableModule, key=module_key)
    tracking_id = request.GET.get('OrderTrackingId', '')

    if tracking_id:
        PlatformInvoice.objects.filter(
            pesapal_tracking_id=tracking_id,
            company=request.tenant,
            status='PENDING',
        ).update(status='CANCELLED')

    messages.warning(request, f"Payment for '{module.label}' was cancelled. No charge was made.")
    return redirect('companies:module_store')