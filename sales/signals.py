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
from .tasks import fiscalize_invoice_async, sync_invoice_with_efris

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
                'is_completed': old_instance.is_completed,
                'is_fiscalized': old_instance.is_fiscalized,
                'total_amount': old_instance.total_amount,
            }
        except sender.DoesNotExist:
            pass


@receiver(post_save, sender=Sale)
def handle_sale_completion(sender, instance, created, **kwargs):
    """
    Handle sale completion, invoice generation, and notifications
    """
    try:
        # Get tenant schema
        schema_name = instance.store.company.schema_name

        with schema_context(schema_name):
            # Get previous state
            state_key = f'sale_{instance.pk}'
            old_state = _pre_save_state.get(state_key, {})

            # Only process completed sales
            if not instance.is_completed:
                return

            # Skip if sale is voided or refunded
            if instance.is_voided or instance.is_refunded:
                return

            # Check if this is a new completion
            is_new_completion = created or (not old_state.get('is_completed', False))

            if is_new_completion:
                # ✅ Send sale completion notification
                from notifications.services import SalesNotifications
                try:
                    SalesNotifications.notify_sale_completed(instance)
                    logger.info(f"Sale completion notification sent for sale {instance.id}")
                except Exception as e:
                    logger.error(f"Failed to send sale completion notification: {e}")

            # Check if invoice already exists
            if hasattr(instance, 'invoice') and instance.invoice:
                return

            # Create invoice from sale if needed
            if should_create_invoice(instance, instance.created_by):
                try:
                    invoice = create_invoice_from_sale(instance)
                    logger.info(f"Created invoice {invoice.pk} for sale {instance.pk}")

                    # Queue for EFRIS fiscalization if enabled
                    if should_fiscalize_invoice(invoice):
                        logger.info(f"Queueing invoice {invoice.pk} for EFRIS fiscalization")
                        fiscalize_invoice_async.delay(
                            invoice.pk,
                            user_id=getattr(instance.created_by, 'pk', None)
                        )

                except Exception as e:
                    logger.error(f"Failed to create invoice for sale {instance.pk}: {e}")

            # Check for fiscalization status change
            if not created:
                if instance.is_fiscalized and not old_state.get('is_fiscalized', False):
                    # ✅ Just fiscalized - send notification
                    from notifications.services import SalesNotifications
                    try:
                        SalesNotifications.notify_efris_fiscalized(instance)
                        logger.info(f"EFRIS fiscalization notification sent for sale {instance.id}")
                    except Exception as e:
                        logger.error(f"Failed to send fiscalization notification: {e}")

            # Clean up tracked state
            if state_key in _pre_save_state:
                del _pre_save_state[state_key]

    except Exception as e:
        logger.error(
            f"Error in handle_sale_completion for sale {instance.pk}: {e}",
            exc_info=True
        )


@receiver(pre_save, sender=Invoice)
def store_previous_invoice_status(sender, instance, **kwargs):
    """Store previous status for comparison in post_save signal"""
    try:
        if instance.pk:
            old_instance = Invoice.objects.get(pk=instance.pk)
            instance._previous_status = getattr(old_instance, 'status', None)
        else:
            instance._previous_status = None
    except Invoice.DoesNotExist:
        instance._previous_status = None


@receiver(post_save, sender=Invoice)
def handle_invoice_changes(sender, instance, created, **kwargs):
    """Handle invoice creation and updates"""
    try:
        schema_name = instance.store.company.schema_name

        with schema_context(schema_name):
            if created:
                logger.info(f"New invoice created: {getattr(instance, 'invoice_number', instance.pk)}")

                # ✅ Send invoice creation notification (if applicable)
                if instance.sale and instance.sale.created_by:
                    from notifications.services import NotificationService
                    try:
                        NotificationService.create_from_template(
                            event_type='invoice_created',
                            recipient=instance.sale.created_by,
                            context={
                                'invoice_number': instance.invoice_number,
                                'total_amount': f'{instance.total_amount:,.0f}',
                                'customer_name': instance.sale.customer.name if instance.sale.customer else 'Walk-in',
                            },
                            related_object=instance,
                            tenant_schema=schema_name
                        )
                    except Exception as e:
                        logger.error(f"Failed to send invoice creation notification: {e}")

                # Auto-fiscalize if configured
                if should_fiscalize_invoice(instance):
                    logger.info(f"Auto-fiscalizing invoice {instance.pk}")
                    fiscalize_invoice_async.delay(
                        instance.pk,
                        user_id=getattr(instance.created_by, 'pk', None)
                    )

            # Handle status changes
            previous_status = getattr(instance, '_previous_status', None)
            if previous_status and previous_status != getattr(instance, 'status', None):
                handle_invoice_status_change(instance, previous_status)

    except Exception as e:
        logger.error(f"Error in handle_invoice_changes: {e}", exc_info=True)


def should_create_invoice(sale, user):
    """Determine if an invoice should be created for this sale"""
    if not sale.is_completed:
        return False

    company = sale.store.company

    # Check company invoice creation policy
    if not getattr(company, 'auto_create_invoices', False):
        return False

    invoice_policy = getattr(company, 'invoice_required_for', 'MANUAL')

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
        # Only create invoices if EFRIS is enabled
        return getattr(company, 'efris_enabled', False)

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


def should_fiscalize_invoice(invoice):
    """Determine if invoice should be fiscalized"""
    # Get company from invoice
    company = invoice.store.company

    if not company:
        logger.warning(f"Cannot determine company for invoice {invoice.pk}")
        return False

    # Check company EFRIS settings
    if not getattr(company, 'efris_enabled', False):
        logger.debug(f"EFRIS not enabled for company {company}")
        return False

    # Check invoice criteria
    total_amount = getattr(invoice, 'total_amount', 0)
    if total_amount <= 0:
        logger.warning(f"Invoice {invoice.pk} has zero or negative total amount")
        return False

    # Check if already fiscalized
    if getattr(invoice, 'is_fiscalized', False):
        logger.debug(f"Invoice {invoice.pk} is already fiscalized")
        return False

    if getattr(invoice, 'fiscalization_status', None) == 'fiscalized':
        logger.debug(f"Invoice {invoice.pk} fiscalization status is already 'fiscalized'")
        return False

    # Check configuration settings
    auto_fiscalize = getattr(settings, 'EFRIS_AUTO_FISCALIZE', True)
    if not auto_fiscalize:
        logger.debug("Auto-fiscalization is disabled in settings")
        return False

    # Check invoice auto_fiscalize setting
    invoice_auto_fiscalize = getattr(invoice, 'auto_fiscalize', True)
    if not invoice_auto_fiscalize:
        logger.debug(f"Auto-fiscalization disabled for invoice {invoice.pk}")
        return False

    return True


def handle_invoice_status_change(invoice, previous_status):
    """Handle invoice status changes"""
    try:
        schema_name = invoice.store.company.schema_name
        current_status = getattr(invoice, 'status', None)

        with schema_context(schema_name):
            if current_status == 'SENT' and previous_status == 'DRAFT':
                # Fiscalize when sent
                if should_fiscalize_invoice(invoice):
                    logger.info(f"Fiscalizing invoice {invoice.pk} due to status change to SENT")
                    fiscalize_invoice_async.delay(
                        invoice.pk,
                        user_id=getattr(invoice.created_by, 'pk', None)
                    )

            elif current_status == 'PAID' and getattr(invoice, 'is_fiscalized', False):
                # Sync with EFRIS when marked as paid
                logger.info(f"Syncing fiscalized invoice {invoice.pk} with EFRIS due to PAID status")
                sync_invoice_with_efris.delay(invoice.pk)

            elif current_status == 'CANCELLED' and getattr(invoice, 'is_fiscalized', False):
                # ✅ Send cancellation notification
                logger.warning(
                    f"Fiscalized invoice {getattr(invoice, 'invoice_number', invoice.pk)} was cancelled. "
                    f"Consider creating credit note."
                )

                # Notify admins
                from notifications.services import NotificationService
                admins = invoice.store.company.staff.filter(is_staff=True).only(
                    'id', 'email', 'first_name', 'last_name'
                )

                for admin in admins:
                    try:
                        NotificationService.create_notification(
                            recipient=admin,
                            title='Fiscalized Invoice Cancelled',
                            message=f'Invoice {invoice.invoice_number} was cancelled after fiscalization. Credit note may be required.',
                            notification_type='WARNING',
                            priority='HIGH',
                            related_object=invoice,
                            action_text='View Invoice',
                            action_url=f'/invoices/{invoice.id}/',
                            tenant_schema=schema_name
                        )
                    except Exception as e:
                        logger.error(f"Failed to send cancellation notification: {e}")

    except Exception as e:
        logger.error(f"Error in handle_invoice_status_change: {e}", exc_info=True)


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

            today_sales = Sale.objects.filter(
                store__company=company,
                created_at__date=today
            ).aggregate(
                total_sales=Count('id'),
                total_revenue=Sum('total_amount')
            )

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
                    },
                }
            )

    except Exception as e:
        logger.error(
            f"[{getattr(company, 'schema_name', 'unknown')}] "
            f"Dashboard update failed for sale {instance.pk}: {e}"
        )