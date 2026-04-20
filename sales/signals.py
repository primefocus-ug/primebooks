from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db.models import Sum, Count
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from decimal import Decimal
import logging
from django_tenants.utils import schema_context
from invoices.models import Invoice
from .tasks import fiscalize_invoice_async, send_document_notification, notify_admins_price_reduction
from push_notifications.tasks import notify_event

logger = logging.getLogger(__name__)

from .models import Sale


@receiver(pre_save, sender=Sale)
def track_sale_state(sender, instance, **kwargs):
    """Track sale state before save for comparison — stored on instance to be process-safe."""
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            instance._pre_save_state = {
                'document_type': old_instance.document_type,
                'status': old_instance.status,
                'payment_status': old_instance.payment_status,
                'is_fiscalized': old_instance.is_fiscalized,
                'total_amount': old_instance.total_amount,
            }
        except sender.DoesNotExist:
            instance._pre_save_state = {}
    else:
        instance._pre_save_state = {}


@receiver(post_save, sender=Sale)
def handle_sale_completion(sender, instance, created, **kwargs):
    """
    Handle sale completion with background processing.

    PUSH NOTIFICATION FIX:
    notify_event() reads connection.schema_name internally via
    _get_current_schema(). Calling it inside schema_context() causes that
    value to resolve as 'public', making notify_event silently bail out.
    All notify_event() calls are made BEFORE entering schema_context() so
    the connection is still on the correct tenant schema.

    FAN-OUT FIX:
    Only dispatches on `created=True` (brand-new rows) OR genuine status
    transitions to COMPLETED. Wrapped in transaction.on_commit() so the
    Celery task only runs after the DB transaction commits.
    """
    try:
        schema_name = instance.store.company.schema_name
        old_state = getattr(instance, '_pre_save_state', {})

        document_type = instance.document_type
        old_status = old_state.get('status')
        is_new_completion = (
            created and instance.status == 'COMPLETED'
        ) or (
            not created
            and old_status not in (None, 'COMPLETED')
            and instance.status == 'COMPLETED'
        )

        # ── Push notifications — BEFORE schema_context ────────────────────────
        # Must stay outside schema_context(). See docstring above.
        # notify_event() reads connection.schema_name internally; calling it
        # inside schema_context() makes it resolve to 'public' and silently bail.

        # ── 1. New sale / completion notification (all document types) ─────────
        if is_new_completion:
            try:
                TYPE_META = {
                    'RECEIPT':  ('New Sale 🛒',       'sale_created'),
                    'INVOICE':  ('New Invoice 🧾',    'sale_created'),
                    'PROFORMA': ('New Proforma 📋',   'sale_created'),
                    'ESTIMATE': ('New Estimate 📋',   'sale_created'),
                }
                title, notif_code = TYPE_META.get(
                    document_type, ('New Sale', 'sale_created')
                )
                notify_event(
                    notification_type_code=notif_code,
                    title=title,
                    body=f"{instance.document_number} — UGX {instance.total_amount:,.0f}",
                    url=f"/sales/{instance.pk}/",
                )
            except Exception as e:
                logger.warning(
                    f"Push notification failed for {document_type} {instance.pk}: {e}"
                )

        # ── 2. Invoice fiscalized — independent event, not an elif ────────────
        if (
            document_type == 'INVOICE'
            and instance.is_fiscalized
            and not old_state.get('is_fiscalized', False)
        ):
            try:
                notify_event(
                    notification_type_code='invoice_fiscalized',
                    title='Invoice Fiscalized ✅',
                    body=f"Invoice {instance.document_number} successfully sent to EFRIS",
                    url=f"/sales/{instance.pk}/",
                )
            except Exception as e:
                logger.warning(
                    f"Push notification failed for fiscalization {instance.pk}: {e}"
                )

        # ── Everything else inside schema_context ─────────────────────────────
        with schema_context(schema_name):
            if document_type == 'RECEIPT':
                if instance.status == 'COMPLETED' and is_new_completion:
                    send_receipt_ws_update(instance)
                    _sale_pk = instance.pk
                    _schema = schema_name
                    transaction.on_commit(
                        lambda: _dispatch_receipt_task(_sale_pk, _schema)
                    )

            elif document_type == 'INVOICE':
                handle_invoice_completion(instance, created, old_state)

            elif document_type in ['PROFORMA', 'ESTIMATE']:
                handle_proforma_completion(instance, created, old_state)

    except Exception as e:
        logger.error(
            f"Error in handle_sale_completion for sale {instance.pk}: {e}",
            exc_info=True
        )


def _dispatch_receipt_task(sale_pk, schema_name):
    """
    Thin wrapper so the on_commit lambda is a named function rather than an
    anonymous closure — easier to trace in logs and test.
    """
    from .tasks import process_receipt_async
    process_receipt_async.delay(sale_pk, schema_name=schema_name)


def send_receipt_ws_update(sale):
    """Send immediate WebSocket update for receipt completion.

    Guarded against None channel_layer — in desktop mode Django Channels is
    not configured so get_channel_layer() returns None.
    """
    try:
        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.debug("WebSocket channel layer not configured — skipping receipt WS update")
            return
        async_to_sync(channel_layer.group_send)(
            f'receipt_updates_{sale.store.id}',
            {
                'type': 'receipt.update',
                'data': {
                    'receipt_number': sale.document_number,
                    'total': float(sale.total_amount),
                    'customer': sale.customer.name if sale.customer else 'Walk-in',
                    'timestamp': timezone.now().isoformat()
                }
            }
        )
    except Exception as e:
        logger.warning(f"Failed to send WebSocket update: {e}")


def handle_receipt_completion(sale, created, old_state):
    """Handle receipt completion — notification dispatch only."""
    if not sale.status == 'COMPLETED':
        return

    send_document_notification.delay(
        sale_id=sale.id,
        notification_type='RECEIPT_CREATED',
        user_id=getattr(sale.created_by, 'pk', None)
    )

    logger.info(f"Receipt {sale.document_number} completed")


def handle_invoice_completion(sale, created, old_state):
    """Handle invoice completion"""
    store_config = sale.store.effective_efris_config
    is_new_completion = created or (old_state.get('status') != 'COMPLETED' and sale.status == 'COMPLETED')

    if is_new_completion:
        send_document_notification.delay(
            sale_id=sale.id,
            notification_type='INVOICE_SENT',
            user_id=getattr(sale.created_by, 'pk', None)
        )

        if not hasattr(sale, 'invoice_detail') or not sale.invoice_detail:
            try:
                Invoice.objects.get_or_create(
                    sale=sale,
                    defaults={
                        'store': sale.store,
                        'fiscalization_status': 'pending',
                        'created_by': sale.created_by,
                        'business_type': 'B2C',
                        'operator_name': sale.created_by.get_full_name() if sale.created_by else 'System',
                    }
                )
            except Exception as e:
                logger.error(f"Failed to create invoice detail for sale {sale.pk}: {e}")

        if should_fiscalize_invoice(sale):
            logger.info(f"Queueing invoice {sale.document_number} for EFRIS fiscalization")
            _sale_pk = sale.pk
            _user_pk = getattr(sale.created_by, 'pk', None)
            transaction.on_commit(
                lambda: fiscalize_invoice_async.delay(_sale_pk, user_id=_user_pk)
            )

    # NOTE: invoice_fiscalized push notification is handled in handle_sale_completion
    # above, outside schema_context, when is_fiscalized flips True on the Sale model.
    # The SalesNotifications service call remains here as it uses a different path.
    if sale.is_fiscalized and not old_state.get('is_fiscalized', False):
        from notifications.services import SalesNotifications
        try:
            SalesNotifications.notify_efris_fiscalized(sale)
            logger.info(f"EFRIS fiscalization notification sent for invoice {sale.document_number}")
        except Exception as e:
            logger.error(f"Failed to send fiscalization notification: {e}")


def handle_proforma_completion(sale, created, old_state):
    """Handle proforma/estimate completion"""
    if created:
        send_document_notification.delay(
            sale_id=sale.id,
            notification_type='PROFORMA_CREATED',
            user_id=getattr(sale.created_by, 'pk', None)
        )
        logger.info(f"{sale.get_document_type_display()} {sale.document_number} created")


def should_fiscalize_invoice(sale):
    """Determine if invoice should be fiscalized"""
    if sale.document_type != 'INVOICE':
        return False

    if not sale.store:
        logger.warning(f"Sale {sale.pk} has no store associated")
        return False

    store_config = sale.store.effective_efris_config

    if not store_config.get('enabled', False) or not store_config.get('is_active', False):
        logger.debug(f"Store {sale.store.name}: EFRIS not enabled or inactive")
        return False

    if not sale.store.can_fiscalize:
        logger.debug(f"Store {sale.store.name} cannot fiscalize transactions")
        return False

    total_amount = getattr(sale, 'total_amount', 0)
    if total_amount <= 0:
        logger.warning(f"Invoice {sale.pk} has zero or negative total amount")
        return False

    if getattr(sale, 'is_fiscalized', False):
        logger.debug(f"Invoice {sale.pk} is already fiscalized")
        return False

    if not store_config.get('auto_fiscalize_sales', True):
        logger.debug(f"Store {sale.store.name} has auto-fiscalization disabled")
        return False

    auto_fiscalize = getattr(settings, 'EFRIS_AUTO_FISCALIZE', True)
    if not auto_fiscalize:
        logger.debug("Auto-fiscalization is disabled in settings")
        return False

    return True


@receiver(pre_save, sender=Invoice)
def store_previous_invoice_status(sender, instance, **kwargs):
    """Store previous status for comparison in post_save signal"""
    try:
        if instance.pk:
            old_instance = Invoice.objects.get(pk=instance.pk)
            instance._previous_status = getattr(old_instance, 'status', None)
            instance._previous_fiscalization_status = getattr(old_instance, 'fiscalization_status', None)
        else:
            instance._previous_status = None
            instance._previous_fiscalization_status = None
    except Invoice.DoesNotExist:
        instance._previous_status = None
        instance._previous_fiscalization_status = None


@receiver(post_save, sender=Invoice)
def handle_invoice_changes(sender, instance, created, **kwargs):
    """Handle invoice creation and updates"""
    try:
        schema_name = instance.store.company.schema_name

        previous_status = getattr(instance, '_previous_status', None)
        previous_fiscal_status = getattr(instance, '_previous_fiscalization_status', None)
        current_fiscal_status = getattr(instance, 'fiscalization_status', None)

        # ── Push notification — BEFORE schema_context ─────────────────────────
        # notify_event() must not be called inside schema_context() or it sees
        # 'public' and silently skips. Fired here, before the with block.
        if (
            current_fiscal_status == 'fiscalized'
            and previous_fiscal_status
            and previous_fiscal_status != 'fiscalized'
            and instance.sale
        ):
            try:
                notify_event(
                    notification_type_code='invoice_fiscalized',
                    title='Invoice Fiscalized ✅',
                    body=f"Invoice {instance.sale.document_number} successfully sent to EFRIS",
                    url=f"/sales/{instance.sale.pk}/",
                )
            except Exception as e:
                logger.warning(
                    f"Push notification failed for fiscalization (Invoice path) {instance.pk}: {e}"
                )

        with schema_context(schema_name):
            if created:
                logger.info(f"New invoice detail created for sale {instance.sale.document_number}")

            if previous_status and previous_status != getattr(instance, 'status', None):
                handle_invoice_status_change(instance, previous_status)

            if previous_fiscal_status and previous_fiscal_status != current_fiscal_status:
                handle_fiscalization_status_change(instance, previous_fiscal_status)

    except Exception as e:
        logger.error(f"Error in handle_invoice_changes: {e}", exc_info=True)


def handle_invoice_status_change(invoice, previous_status):
    """Handle invoice status changes"""
    try:
        current_status = getattr(invoice, 'status', None)

        if current_status == 'SENT' and previous_status == 'DRAFT':
            if invoice.sale and should_fiscalize_invoice(invoice.sale):
                store_config = invoice.sale.store.effective_efris_config
                if store_config.get('enabled', False) and store_config.get('is_active', False):
                    logger.info(f"Fiscalizing invoice {invoice.sale.document_number} due to status change to SENT")
                    _sale_pk = invoice.sale.pk
                    _user_pk = getattr(invoice.created_by, 'pk', None)
                    transaction.on_commit(
                        lambda: fiscalize_invoice_async.delay(_sale_pk, user_id=_user_pk)
                    )
                else:
                    logger.debug(f"Store {invoice.sale.store.name} does not allow fiscalization")

        elif current_status == 'PAID' and invoice.sale:
            invoice.sale.payment_status = 'PAID'
            invoice.sale.save()

        elif current_status == 'CANCELLED' and getattr(invoice, 'is_fiscalized', False):
            logger.warning(
                f"Fiscalized invoice {invoice.sale.document_number} was cancelled. "
                f"Consider creating credit note."
            )

    except Exception as e:
        logger.error(f"Error in handle_invoice_status_change: {e}", exc_info=True)


def handle_fiscalization_status_change(invoice, previous_status):
    """Handle fiscalization status changes on the Invoice model.

    NOTE: the push notification for invoice_fiscalized is fired in
    handle_invoice_changes() BEFORE this function is called, so it correctly
    runs outside schema_context(). Do not add notify_event() here.
    """
    try:
        current_status = getattr(invoice, 'fiscalization_status', None)

        if current_status == 'fiscalized' and previous_status != 'fiscalized':
            if invoice.sale:
                invoice.sale.is_fiscalized = True
                invoice.sale.fiscalization_time = invoice.fiscalization_time
                invoice.sale.fiscalization_status = 'fiscalized'
                invoice.sale.efris_invoice_number = invoice.fiscal_document_number
                invoice.sale.verification_code = invoice.verification_code
                invoice.sale.qr_code = invoice.qr_code
                invoice.sale.save()
                logger.info(f"Updated sale {invoice.sale.document_number} with fiscalization data")

        elif current_status == 'failed' and invoice.sale:
            invoice.sale.fiscalization_status = 'failed'
            invoice.sale.save()

    except Exception as e:
        logger.error(f"Error in handle_fiscalization_status_change: {e}", exc_info=True)


def should_create_invoice(sale, user):
    """Determine if an invoice should be created for this sale"""
    if not sale.is_completed:
        return False

    store_config = sale.store.effective_efris_config

    if not store_config.get('auto_create_invoices', False):
        return False

    invoice_policy = getattr(sale.store, 'invoice_policy', 'MANUAL')

    if invoice_policy == 'MANUAL':
        return False
    elif invoice_policy == 'ALL':
        return True
    elif invoice_policy == 'B2B':
        if sale.customer and hasattr(sale.customer, 'get_efris_buyer_details'):
            buyer_details = sale.customer.get_efris_buyer_details()
            return buyer_details.get('buyerType') == "0"
        return False
    elif invoice_policy == 'EFRIS_ENABLED':
        return store_config.get('enabled', False) and store_config.get('is_active', False)

    return False


def create_invoice_from_sale(sale):
    """Create invoice from completed sale"""
    company = sale.store.company

    subtotal = sum(item.total_price for item in sale.items.all())
    tax_amount = sum(item.tax_amount for item in sale.items.all())
    discount_amount = sale.discount_amount or Decimal('0')
    total_amount = subtotal - discount_amount

    invoice = Invoice.objects.create(
        sale=sale,
        store=sale.store,
        invoice_number=generate_invoice_number(company),
        issue_date=timezone.now().date(),
        due_date=timezone.now().date() + timezone.timedelta(days=30),
        subtotal=subtotal,
        tax_amount=tax_amount,
        discount_amount=discount_amount,
        total_amount=total_amount,
        currency_code=sale.currency or 'UGX',
        status='SENT',
        fiscalization_status='pending',
        created_by=sale.created_by,
        document_type='INVOICE',
        auto_fiscalize=True
    )

    for sale_item in sale.items.all():
        invoice.items.create(
            product=sale_item.product if sale_item.item_type == 'PRODUCT' else None,
            service=sale_item.service if sale_item.item_type == 'SERVICE' else None,
            quantity=sale_item.quantity,
            unit_price=sale_item.unit_price,
            total_price=sale_item.total_price,
            tax_rate=getattr(sale_item, 'tax_rate', 'A'),
            tax_amount=sale_item.tax_amount,
            discount_amount=getattr(sale_item, 'discount_amount', None) or Decimal('0')
        )

    logger.info(f"Invoice {invoice.pk} created with {invoice.items.count()} items")
    return invoice


def generate_invoice_number(company):
    """Generate sequential invoice number — uses select_for_update to prevent race conditions."""
    from django.db import transaction as _tx
    current_year = timezone.now().year

    with _tx.atomic():
        last_invoice = Invoice.objects.select_for_update().filter(
            store__company=company,
            issue_date__year=current_year
        ).order_by('-pk').first()

        if last_invoice and getattr(last_invoice, 'invoice_number', None):
            try:
                parts = last_invoice.invoice_number.split('-')
                if len(parts) >= 3:
                    last_num = int(parts[-1])
                    next_num = last_num + 1
                else:
                    next_num = 1
            except (ValueError, IndexError):
                next_num = 1
        else:
            next_num = 1

    return f"INV-{current_year}-{next_num:04d}"


@receiver(post_save, sender=Sale)
def update_dashboard_on_sale(sender, instance, created, **kwargs):
    """
    Trigger tenant-specific dashboard WebSocket update when a new Sale is created.

    PERFORMANCE FIX: Only fires on created=True. Previously fired on every save,
    running two aggregation queries even for trivial field updates like
    update_fields=['payment_status'].
    """
    if not created:
        return

    try:
        company = getattr(instance.store, 'company', None)
        if not company:
            logger.error(f"Sale {instance.pk}: Store has no associated company.")
            return

        channel_layer = get_channel_layer()
        if channel_layer is None:
            logger.debug(
                f"[{company.schema_name}] WebSocket channel layer not configured — "
                f"skipping dashboard update for sale {instance.pk}"
            )
            return

        with schema_context(company.schema_name):
            today = instance.created_at.date()

            today_stats = Sale.objects.filter(
                store__company=company,
                created_at__date=today
            ).aggregate(
                total_sales=Count('id'),
                total_revenue=Sum('total_amount')
            )

            type_breakdown = list(
                Sale.objects.filter(
                    store__company=company,
                    created_at__date=today
                ).values('document_type').annotate(
                    count=Count('id'),
                    amount=Sum('total_amount')
                ).order_by('document_type')
            )

            async_to_sync(channel_layer.group_send)(
                f'dashboard_{company.schema_name}',
                {
                    'type': 'dashboard.update',
                    'data': {
                        'type': 'sale_update',
                        'total_sales': today_stats['total_sales'] or 0,
                        'total_revenue': float(today_stats['total_revenue'] or 0.0),
                        'document_type': instance.document_type,
                        'document_number': instance.document_number,
                        'sale_amount': float(instance.total_amount),
                        'type_breakdown': type_breakdown,
                    },
                }
            )

    except Exception as e:
        logger.warning(
            f"[{getattr(company, 'schema_name', 'unknown')}] "
            f"Dashboard update failed for sale {instance.pk}: {e}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# PRICE REDUCTION REQUESTS — notify admins on creation
# ─────────────────────────────────────────────────────────────────────────────

@receiver(post_save, sender='sales.PriceReductionRequest')
def handle_price_reduction_request_created(sender, instance, created, **kwargs):
    """
    Fires when a new PriceReductionRequest is saved with status=PENDING.
    Dispatches notify_admins_price_reduction via Celery so the email and
    FCM push happen asynchronously — same on_commit pattern as other tasks.

    SCHEMA NOTE:
    The PriceReductionRequest is created inside the tenant schema by the view.
    We read schema_name from the store's company — identical to how
    handle_sale_completion reads it.

    PUSH NOTIFICATION NOTE:
    notify_admins_price_reduction calls notify_event() INSIDE schema_context()
    (which is correct for tasks — the connection starts fresh). Do NOT call
    notify_event() here in the signal; that would hit the 'public' schema bug.
    The task handles both email and push together.
    """
    if not created:
        return

    if instance.status != 'PENDING':
        return

    try:
        schema_name = instance.store.company.schema_name
        request_id  = str(instance.id)

        # Use on_commit so the task only fires after the DB row is visible —
        # prevents the task from running before the INSERT commits.
        transaction.on_commit(
            lambda: notify_admins_price_reduction.delay(request_id, schema_name)
        )

        logger.info(
            f'Queued notify_admins_price_reduction for request {request_id} '
            f'({instance.item_name}) in {schema_name}'
        )

    except Exception as e:
        logger.error(
            f'Failed to queue price reduction notification '
            f'for request {instance.id}: {e}',
            exc_info=True
        )