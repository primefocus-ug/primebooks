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
# Paid-module payment flow  (single module)
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


# ─────────────────────────────────────────────────────────────────────────────
# Cart payment flow  (multiple modules, single Pesapal transaction)
# ─────────────────────────────────────────────────────────────────────────────

@login_required
def initiate_cart_payment(request):
    """
    Step 1 — Accept a list of module_keys, validate each, then create ONE
    combined Pesapal order for the total amount.

    URL: POST companies/app-store/cart/pay/

    The form posts:  module_keys=crm&module_keys=payroll&module_keys=...
    (one hidden input per module, all named 'module_keys').
    """
    if request.method != 'POST':
        return redirect('companies:module_store')

    company      = request.tenant
    module_keys  = request.POST.getlist('module_keys')

    if not module_keys:
        messages.warning(request, 'Your cart is empty — please add at least one module.')
        return redirect('companies:module_store')

    # ── Deduplicate ──────────────────────────────────────────────────────────
    module_keys = list(dict.fromkeys(module_keys))   # preserves order, removes dupes

    # ── Fetch & validate each module ────────────────────────────────────────
    company_module_map = {
        cm.module_id: cm
        for cm in CompanyModule.objects.filter(company=company).select_related('module')
    }

    valid_modules   = []   # AvailableModule instances that pass all checks
    skipped_labels  = []   # labels skipped with a reason (already active / pending / etc.)

    for key in module_keys:
        try:
            module = AvailableModule.objects.prefetch_related('dependencies').get(
                key=key, is_publicly_available=True
            )
        except AvailableModule.DoesNotExist:
            logger.warning('Cart: unknown module key "%s" for tenant %s', key, company.schema_name)
            continue

        if module.monthly_price <= 0:
            # Free modules should not be in the cart, skip silently
            continue

        cm = company_module_map.get(module.id)

        if cm and cm.is_active:
            skipped_labels.append(f'{module.label} (already active)')
            continue

        if cm and cm.within_paid_period:
            # Re-activate for free instead of charging again
            cm.activate()
            _clear_module_cache(company.schema_name)
            skipped_labels.append(f'{module.label} (reactivated free — still in paid period)')
            continue

        if _has_pending_payment(company, module):
            skipped_labels.append(f'{module.label} (payment already pending)')
            continue

        # Check dependencies
        dep_ok = True
        for dep in module.dependencies.all():
            dep_cm = company_module_map.get(dep.id)
            if not dep_cm or not dep_cm.is_active:
                skipped_labels.append(f'{module.label} (requires {dep.label} first)')
                dep_ok = False
                break
        if not dep_ok:
            continue

        valid_modules.append(module)

    # Notify user of any skipped modules
    if skipped_labels:
        messages.warning(
            request,
            'Some modules were skipped: ' + '; '.join(skipped_labels)
        )

    if not valid_modules:
        messages.info(request, 'No modules needed payment — nothing to charge.')
        return redirect('companies:module_store')

    # ── Build combined order ─────────────────────────────────────────────────
    total_amount       = sum(float(m.monthly_price) for m in valid_modules)
    keys_slug          = '-'.join(m.key.upper()[:10] for m in valid_modules)[:40]
    merchant_reference = f'CART-{keys_slug}-{uuid.uuid4().hex[:8].upper()}'
    module_names       = ', '.join(m.label for m in valid_modules)
    description        = f'App Store: {module_names[:80]} | {company.name[:30]}'
    currency           = 'UGX'

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
        logger.error('Cart IPN registration failed: tenant=%s err=%s',
                     company.schema_name, ipn_res.get('error'))
        messages.error(request, 'Payment setup failed. Please try again or contact support.')
        return redirect('companies:module_store')

    # Encode all module keys into the callback URL so we know what to activate
    cart_keys_param = ','.join(m.key for m in valid_modules)
    callback_url     = request.build_absolute_uri(
        reverse('companies:cart_payment_callback')
    ) + f'?cart_keys={cart_keys_param}'
    cancellation_url = request.build_absolute_uri(
        reverse('companies:cart_payment_cancelled')
    ) + f'?cart_keys={cart_keys_param}'

    order_result = svc.submit_order(
        merchant_reference = merchant_reference,
        amount             = total_amount,
        currency           = currency,
        description        = description,
        notification_id    = ipn_res['ipn_id'],
        billing_address    = billing_address,
        callback_url       = callback_url,
        cancellation_url   = cancellation_url,
        branch             = company.name[:50],
    )

    if not order_result['success']:
        logger.error('Cart order submission failed: tenant=%s err=%s',
                     company.schema_name, order_result.get('error'))
        messages.error(request, 'Could not initiate payment. Please try again later.')
        return redirect('companies:module_store')

    # ── Create one PlatformInvoice per module (linked to same tracking ID) ───
    tracking_id  = order_result['order_tracking_id']
    redirect_url = order_result['redirect_url']

    for module in valid_modules:
        PlatformInvoice.objects.create(
            company             = company,
            module              = module,
            plan                = None,
            amount              = float(module.monthly_price),
            currency            = currency,
            description         = f'Cart: {module.label} | {company.name[:40]}',
            merchant_reference  = merchant_reference,
            pesapal_tracking_id = tracking_id,
            redirect_url        = redirect_url,
            status              = 'PENDING',
        )

    logger.info(
        'Cart payment initiated | tenant=%s modules=%s total=%.2f tracking=%s',
        company.schema_name, cart_keys_param, total_amount, tracking_id,
    )

    return redirect(redirect_url)


@login_required
def cart_payment_callback(request):
    """
    Pesapal redirects here after a cart (multi-module) payment.
    URL: GET companies/app-store/cart/callback/?OrderTrackingId=...&cart_keys=crm,payroll
    """
    company     = request.tenant
    tracking_id = request.GET.get('OrderTrackingId', '')
    cart_keys   = request.GET.get('cart_keys', '')

    if not tracking_id or not cart_keys:
        messages.error(request, 'Payment verification failed — missing parameters.')
        return redirect('companies:module_store')

    svc           = PesapalService()
    status_result = svc.get_transaction_status(tracking_id)

    if not status_result['success']:
        logger.error('Cart status check failed: tenant=%s tracking=%s err=%s',
                     company.schema_name, tracking_id, status_result.get('error'))
        messages.error(request, 'Could not verify payment status. Please contact support.')
        return redirect('companies:module_store')

    status_code = status_result.get('status_code')

    if status_code == 1:
        paid_through   = (timezone.now() + timedelta(days=MODULE_BILLING_DAYS)).date()
        activated      = []

        for key in cart_keys.split(','):
            key = key.strip()
            if not key:
                continue
            try:
                module = AvailableModule.objects.get(key=key)
            except AvailableModule.DoesNotExist:
                continue

            cm, _ = CompanyModule.objects.get_or_create(company=company, module=module)
            if not cm.is_active:
                cm.activate(paid_through=paid_through)
                activated.append(module.label)
            else:
                cm.paid_through = paid_through
                cm.save(update_fields=['paid_through'])

        _clear_module_cache(company.schema_name)

        # Mark invoices as paid
        try:
            PlatformInvoice.objects.filter(
                pesapal_tracking_id=tracking_id,
                company=company,
                status='PENDING',
            ).update(
                status               = 'PAID',
                pesapal_confirmation = status_result.get('confirmation_code', ''),
                payment_method       = status_result.get('payment_method', ''),
                payment_account      = status_result.get('payment_account', ''),
                paid_at              = timezone.now(),
            )
        except Exception as exc:
            logger.error('Cart PlatformInvoice update error: %s', exc)

        logger.info('Cart payment succeeded: tenant=%s modules=%s tracking=%s paid_through=%s',
                    company.schema_name, cart_keys, tracking_id, paid_through)

        if activated:
            labels = ', '.join(activated)
            messages.success(
                request,
                f'✅ {len(activated)} module(s) activated: {labels}. '
                f'Subscriptions run until {paid_through.strftime("%d %b %Y")}.'
            )
        else:
            messages.info(request, 'Payment received — all selected modules are already active.')

        return redirect('companies:module_store')

    # Payment not complete
    status_description = status_result.get('status_description', 'Unknown')
    logger.warning('Cart payment not completed: tenant=%s status=%s tracking=%s',
                   company.schema_name, status_description, tracking_id)

    messages.error(
        request,
        f"Payment was not completed (status: {status_description}). "
        "No charge was made. You can try again from the App Store."
    )
    return redirect('companies:module_store')


@login_required
def cart_payment_cancelled(request):
    """Pesapal redirects here when user cancels a cart payment."""
    tracking_id = request.GET.get('OrderTrackingId', '')
    cart_keys   = request.GET.get('cart_keys', '')

    if tracking_id:
        PlatformInvoice.objects.filter(
            pesapal_tracking_id=tracking_id,
            company=request.tenant,
            status='PENDING',
        ).update(status='CANCELLED')

    module_count = len([k for k in cart_keys.split(',') if k.strip()]) if cart_keys else 0
    messages.warning(
        request,
        f"Cart payment cancelled ({module_count} module(s)). No charge was made."
    )
    return redirect('companies:module_store')