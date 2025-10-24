from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Sum, Count
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.conf import settings
from django.utils import timezone
from decimal import Decimal
import logging
from django_tenants.utils import schema_context
from invoices.models import Invoice
from .tasks import fiscalize_invoice_async, sync_invoice_with_efris

logger = logging.getLogger(__name__)

from .models import Sale


@receiver(post_save, sender=Sale)
def handle_sale_completion(sender, instance, created, **kwargs):
    """
    Handle sale completion and invoice generation
    """
    # Only process completed sales - use is_completed instead of status
    if not instance.is_completed:
        return

    # Skip if sale is voided or refunded
    if instance.is_voided or instance.is_refunded:
        return

    # Check if invoice already exists
    if hasattr(instance, 'invoice') and instance.invoice:
        return

    try:
        # Create invoice from sale
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
        logger.error(
            "Failed to process sale completion",
            extra={
                'sale_id': instance.pk,
                'error': str(e)
            }
        )


@receiver(post_save, sender=Invoice)
def handle_invoice_changes(sender, instance, created, **kwargs):
    """
    Handle invoice creation and updates
    """
    if created:
        logger.info(f"New invoice created: {getattr(instance, 'invoice_number', instance.pk)}")

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


def create_invoice_from_sale(sale):
    """
    Create invoice from completed sale
    """
    # Get company from sale
    company = sale.store.company

    # Calculate totals
    subtotal = sum(item.total_price for item in sale.items.all())
    tax_amount = sum(item.tax_amount for item in sale.items.all())
    discount_amount = sale.discount_amount or Decimal('0')
    total_amount = subtotal + tax_amount - discount_amount

    # Create invoice
    invoice = Invoice.objects.create(
        company=company,
        sale=sale,
        store=sale.store,
        customer=sale.customer,
        invoice_number=generate_invoice_number(company),
        issue_date=timezone.now().date(),
        due_date=timezone.now().date() + timezone.timedelta(days=30),
        subtotal=subtotal,
        tax_amount=tax_amount,
        discount_amount=discount_amount,
        total_amount=total_amount,
        currency_code=sale.currency or 'UGX',
        status='DRAFT',
        fiscalization_status='pending',
        created_by=sale.created_by,
        document_type='INVOICE',
        auto_fiscalize=True
    )

    # Copy sale items to invoice items
    for sale_item in sale.items.all():
        invoice.items.create(
            product=sale_item.product,
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
    """
    Determine if invoice should be fiscalized
    """
    # Get company from invoice
    company = None
    if hasattr(invoice, 'company') and invoice.store.company:
        company = invoice.store.company
    elif hasattr(invoice, 'sale') and invoice.sale:
        company = invoice.sale.store.company

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
    """
    Handle invoice status changes
    """
    current_status = getattr(invoice, 'status', None)

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
        # Handle cancellation of fiscalized invoice - may need credit note
        logger.warning(
            f"Fiscalized invoice {getattr(invoice, 'invoice_number', invoice.pk)} was cancelled. "
            f"Consider creating credit note."
        )


def generate_invoice_number(company):
    """
    Generate sequential invoice number
    """
    current_year = timezone.now().year

    # Get last invoice for the company in current year
    last_invoice = Invoice.objects.filter(
        company=company,
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
        # ✅ Get company from store
        company = getattr(instance.store, 'company', None)
        if not company:
            logger.error(f"Sale {instance.pk}: Store has no associated company.")
            return

        # ✅ Run inside the company’s tenant schema
        with schema_context(company.schema_name):
            today = instance.created_at.date()

            today_sales = Sale.objects.filter(
                store__company=company,
                created_at__date=today
            ).aggregate(
                total_sales=Count('id'),
                total_revenue=Sum('total_amount')
            )

            # ✅ Send to tenant-specific WebSocket group
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'dashboard_{company.schema_name}',  # 👈 use schema_name for isolation
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
        logger.error(f"[{getattr(company, 'schema_name', 'unknown')}] Dashboard update failed for sale {instance.pk}: {e}")



# Store previous status for comparison
@receiver(pre_save, sender=Invoice)
def store_previous_invoice_status(sender, instance, **kwargs):
    """
    Store previous status for comparison in post_save signal
    """
    try:
        if instance.pk:
            old_instance = Invoice.objects.get(pk=instance.pk)
            instance._previous_status = getattr(old_instance, 'status', None)
        else:
            instance._previous_status = None
    except Invoice.DoesNotExist:
        instance._previous_status = None