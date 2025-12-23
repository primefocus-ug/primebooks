from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db.models import Sum, Count
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import logging
from django_tenants.utils import schema_context
from invoices.models import Invoice
from .tasks import fiscalize_invoice_async, send_document_notification

logger = logging.getLogger(__name__)

from .models import Sale

# Track previous state for comparison
_pre_save_state = {}


@receiver(pre_save, sender=Sale)
def track_sale_state(sender, instance, **kwargs):
    """Track sale state before save for comparison"""
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            _pre_save_state[f'sale_{instance.pk}'] = {
                'document_type': old_instance.document_type,
                'status': old_instance.status,
                'payment_status': old_instance.payment_status,
                'is_fiscalized': old_instance.is_fiscalized,
                'total_amount': old_instance.total_amount,
            }
        except sender.DoesNotExist:
            pass


# Update in your signals.py or wherever post_save signals are defined

@receiver(post_save, sender=Sale)
def handle_sale_completion(sender, instance, created, **kwargs):
    """
    Handle sale completion with background processing
    """
    try:
        # Get tenant schema
        schema_name = instance.store.company.schema_name

        with schema_context(schema_name):
            # Get previous state
            state_key = f'sale_{instance.pk}'
            old_state = _pre_save_state.get(state_key, {})

            # Handle different document types
            document_type = instance.document_type

            if document_type == 'RECEIPT':
                # For receipts, only handle minimal synchronous tasks
                if instance.status == 'COMPLETED':
                    # Send immediate WebSocket update for POS
                    send_receipt_ws_update(instance)

                    # Queue background processing
                    from .tasks import process_receipt_async
                    process_receipt_async.delay(instance.pk)

            elif document_type == 'INVOICE':
                handle_invoice_completion(instance, created, old_state)

            elif document_type in ['PROFORMA', 'ESTIMATE']:
                handle_proforma_completion(instance, created, old_state)

            # Clean up tracked state
            if state_key in _pre_save_state:
                del _pre_save_state[state_key]

    except Exception as e:
        logger.error(
            f"Error in handle_sale_completion for sale {instance.pk}: {e}",
            exc_info=True
        )


def send_receipt_ws_update(sale):
    """Send immediate WebSocket update for receipt completion"""
    try:
        channel_layer = get_channel_layer()
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
    """Handle receipt completion"""
    if not sale.status == 'COMPLETED':
        return

    # Send receipt notification
    send_document_notification.delay(
        sale_id=sale.id,
        notification_type='RECEIPT_CREATED',
        user_id=getattr(sale.created_by, 'pk', None)
    )

    logger.info(f"Receipt {sale.document_number} completed")

def handle_invoice_completion(sale, created, old_state):
    """Handle invoice completion"""
    # Check if this is a new completion
    store_config = sale.store.effective_efris_config

    # Check if EFRIS is enabled for this store
    efris_enabled = store_config.get('enabled', False) and store_config.get('is_active', False)
    is_new_completion = created or (old_state.get('status') != 'COMPLETED' and sale.status == 'COMPLETED')

    if is_new_completion:
        # Send invoice notification
        send_document_notification.delay(
            sale_id=sale.id,
            notification_type='INVOICE_SENT',
            user_id=getattr(sale.created_by, 'pk', None)
        )

        # Create invoice detail if not exists
        if not hasattr(sale, 'invoice_detail') or not sale.invoice_detail:
            from invoices.models import Invoice
            try:
                Invoice.objects.create(
                    sale=sale,
                    store=sale.store,
                    status='SENT',
                    fiscalization_status='pending',
                    created_by=sale.created_by
                )
            except Exception as e:
                logger.error(f"Failed to create invoice detail for sale {sale.pk}: {e}")

        # Check if should auto-fiscalize
        if should_fiscalize_invoice(sale):
            logger.info(f"Queueing invoice {sale.document_number} for EFRIS fiscalization")
            fiscalize_invoice_async.delay(
                sale.pk,
                user_id=getattr(sale.created_by, 'pk', None)
            )

    # Check for fiscalization status change
    if sale.is_fiscalized and not old_state.get('is_fiscalized', False):
        # Send fiscalization notification
        from notifications.services import SalesNotifications
        try:
            SalesNotifications.notify_efris_fiscalized(sale)
            logger.info(f"EFRIS fiscalization notification sent for invoice {sale.document_number}")
        except Exception as e:
            logger.error(f"Failed to send fiscalization notification: {e}")


def handle_proforma_completion(sale, created, old_state):
    """Handle proforma/estimate completion"""
    if created:
        # Send proforma notification
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

    # Check if sale has a store
    if not sale.store:
        logger.warning(f"Sale {sale.pk} has no store associated")
        return False

    # Get store's effective EFRIS configuration
    store_config = sale.store.effective_efris_config

    # Check if EFRIS is enabled and active for this store
    if not store_config.get('enabled', False) or not store_config.get('is_active', False):
        logger.debug(f"Store {sale.store.name}: EFRIS not enabled or inactive")
        return False

    # Check if store can fiscalize
    if not sale.store.can_fiscalize:
        logger.debug(f"Store {sale.store.name} cannot fiscalize transactions")
        return False

    # Check sale criteria
    total_amount = getattr(sale, 'total_amount', 0)
    if total_amount <= 0:
        logger.warning(f"Invoice {sale.pk} has zero or negative total amount")
        return False

    # Check if already fiscalized
    if getattr(sale, 'is_fiscalized', False):
        logger.debug(f"Invoice {sale.pk} is already fiscalized")
        return False

    # Check auto-fiscalization from store config
    if not store_config.get('auto_fiscalize_sales', True):
        logger.debug(f"Store {sale.store.name} has auto-fiscalization disabled")
        return False

    # Check global settings
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

        with schema_context(schema_name):
            if created:
                logger.info(f"New invoice detail created for sale {instance.sale.document_number}")

                # Update related sale
                if instance.sale:
                    instance.sale.save()  # This will trigger sale signals

            # Handle status changes
            previous_status = getattr(instance, '_previous_status', None)
            previous_fiscal_status = getattr(instance, '_previous_fiscalization_status', None)

            if previous_status and previous_status != getattr(instance, 'status', None):
                handle_invoice_status_change(instance, previous_status)

            if previous_fiscal_status and previous_fiscal_status != getattr(instance, 'fiscalization_status', None):
                handle_fiscalization_status_change(instance, previous_fiscal_status)

    except Exception as e:
        logger.error(f"Error in handle_invoice_changes: {e}", exc_info=True)

def handle_invoice_status_change(invoice, previous_status):
    """Handle invoice status changes"""
    try:
        current_status = getattr(invoice, 'status', None)

        if current_status == 'SENT' and previous_status == 'DRAFT':
            # Fiscalize when sent
            if invoice.sale and should_fiscalize_invoice(invoice.sale):
                # Check if store allows fiscalization
                store_config = invoice.sale.store.effective_efris_config
                if store_config.get('enabled', False) and store_config.get('is_active', False):
                    logger.info(f"Fiscalizing invoice {invoice.sale.document_number} due to status change to SENT")
                    fiscalize_invoice_async.delay(
                        invoice.sale.pk,
                        user_id=getattr(invoice.created_by, 'pk', None)
                    )
                else:
                    logger.debug(f"Store {invoice.sale.store.name} does not allow fiscalization")

        elif current_status == 'PAID' and invoice.sale:
            # Update sale payment status
            invoice.sale.payment_status = 'PAID'
            invoice.sale.save()

        elif current_status == 'CANCELLED' and getattr(invoice, 'is_fiscalized', False):
            # Notify about cancelled fiscalized invoice
            logger.warning(
                f"Fiscalized invoice {invoice.sale.document_number} was cancelled. "
                f"Consider creating credit note."
            )

    except Exception as e:
        logger.error(f"Error in handle_invoice_status_change: {e}", exc_info=True)


def handle_fiscalization_status_change(invoice, previous_status):
    """Handle fiscalization status changes"""
    try:
        current_status = getattr(invoice, 'fiscalization_status', None)

        if current_status == 'fiscalized' and previous_status != 'fiscalized':
            # Update related sale
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
            # Update sale failure status
            invoice.sale.fiscalization_status = 'failed'
            invoice.sale.save()

    except Exception as e:
        logger.error(f"Error in handle_fiscalization_status_change: {e}", exc_info=True)


def should_create_invoice(sale, user):
    """Determine if an invoice should be created for this sale"""
    if not sale.is_completed:
        return False

    # Get store's effective configuration
    store_config = sale.store.effective_efris_config

    # Check if store auto-creates invoices
    if not store_config.get('auto_create_invoices', False):
        return False

    # Check store's invoice policy
    invoice_policy = getattr(sale.store, 'invoice_policy', 'MANUAL')

    if invoice_policy == 'MANUAL':
        return False
    elif invoice_policy == 'ALL':
        return True
    elif invoice_policy == 'B2B':
        # Use customer's EFRIS mixin method to determine business type
        if sale.customer and hasattr(sale.customer, 'get_efris_buyer_details'):
            buyer_details = sale.customer.get_efris_buyer_details()
            return buyer_details.get('buyerType') == "0"  # B2B
        return False
    elif invoice_policy == 'EFRIS_ENABLED':
        # Only create invoices if EFRIS is enabled for this store
        return store_config.get('enabled', False) and store_config.get('is_active', False)

    return False


def create_invoice_from_sale(sale):
    """Create invoice from completed sale"""
    company = sale.store.company

    # Calculate totals
    subtotal = sum(item.total_price for item in sale.items.all())
    tax_amount = sum(item.tax_amount for item in sale.items.all())
    discount_amount = sale.discount_amount or Decimal('0')
    total_amount = subtotal + tax_amount - discount_amount

    # Create invoice
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

    # Copy sale items to invoice items
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
    """Generate sequential invoice number"""
    current_year = timezone.now().year

    # Get last invoice for the company in current year
    last_invoice = Invoice.objects.filter(
        store__company=company,
        issue_date__year=current_year
    ).order_by('-pk').first()

    if last_invoice and getattr(last_invoice, 'invoice_number', None):
        try:
            # Extract number from format like "INV-2024-0001"
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
    """
    if not created:
        return  # Only send updates for newly created sales

    try:
        # Get company from store
        company = getattr(instance.store, 'company', None)
        if not company:
            logger.error(f"Sale {instance.pk}: Store has no associated company.")
            return

        # Run inside the company's tenant schema
        with schema_context(company.schema_name):
            today = instance.created_at.date()

            # Get today's sales summary by document type
            today_sales = Sale.objects.filter(
                store__company=company,
                created_at__date=today
            ).aggregate(
                total_sales=Count('id'),
                total_revenue=Sum('total_amount')
            )

            # Get breakdown by document type
            type_breakdown = Sale.objects.filter(
                store__company=company,
                created_at__date=today
            ).values('document_type').annotate(
                count=Count('id'),
                amount=Sum('total_amount')
            ).order_by('document_type')

            # Send to tenant-specific WebSocket group
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'dashboard_{company.schema_name}',
                {
                    'type': 'dashboard.update',
                    'data': {
                        'type': 'sale_update',
                        'total_sales': today_sales['total_sales'] or 0,
                        'total_revenue': float(today_sales['total_revenue'] or 0.0),
                        'document_type': instance.document_type,
                        'document_number': instance.document_number,
                        'sale_amount': float(instance.total_amount),
                        'type_breakdown': list(type_breakdown),
                    },
                }
            )

    except Exception as e:
        logger.error(
            f"[{getattr(company, 'schema_name', 'unknown')}] "
            f"Dashboard update failed for sale {instance.pk}: {e}"
        )