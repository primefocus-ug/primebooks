from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django.apps import apps
import logging

from .models import EFRISConfiguration, EFRISNotification, EFRISSyncQueue
from .websocket_manager import websocket_manager, EFRISWebSocketEvent
from sales.tasks import fiscalize_invoice_async
from .tasks import (
    upload_products_async,
    validate_customer_tin_async,
    sync_stock_to_efris_async,
    process_efris_queue_async
)

logger = logging.getLogger(__name__)


def create_efris_notification(company, title: str, message: str,
                              notification_type: str = 'info', priority: str = 'normal'):
    """Create EFRIS notification and broadcast it via WebSocket"""
    try:
        notification = EFRISNotification.objects.create(
            company=company,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority
        )

        # Broadcast notification via WebSocket
        websocket_manager.send_notification(
            company.pk, title, message, notification_type, priority,
            metadata={'notification_id': notification.pk}
        )

        return notification

    except Exception as e:
        logger.error(f"Failed to create EFRIS notification: {e}")
        return None


# Sales and Invoice Signals
@receiver(post_save, sender='sales.Sale')
def handle_sale_completion_for_efris(sender, instance, created, **kwargs):
    """Handle completed sales for auto-fiscalization with enhanced validation"""
    if not instance.is_completed or instance.transaction_type != 'SALE':
        return

    try:
        company = instance.store.company
        if not company.efris_enabled or not getattr(company, 'efris_auto_fiscalize_sales', False):
            return

        # Validate sale amount before proceeding
        if instance.total_amount <= 0:
            logger.warning(
                f"Skipping EFRIS processing for sale {instance.id} - zero or negative amount: {instance.total_amount}")
            return

        # Check if sale can be fiscalized
        can_fiscalize, reason = instance.can_fiscalize()
        if not can_fiscalize:
            logger.warning(f"Sale {instance.id} cannot be fiscalized: {reason}")
            return

        # Check if sale already has an invoice
        invoice = None
        if hasattr(instance, 'invoice') and instance.invoice:
            invoice = instance.invoice
        else:
            # Create invoice from sale
            invoice = instance._create_invoice_if_needed()

        if invoice and invoice.total_amount > 0:
            # Queue for fiscalization
            if not getattr(invoice, 'is_fiscalized', False):
                _queue_invoice_fiscalization(invoice, company, priority=1)

                logger.info(
                    f"Queued {'sale' if invoice == instance else 'invoice'} {getattr(invoice, 'invoice_number', invoice.id)} for fiscalization")
        else:
            logger.error(
                f"Failed to create valid invoice for sale {instance.id} - invoice amount: {getattr(invoice, 'total_amount', 'N/A')}")

        # Broadcast sale completion event via WebSocket
        websocket_manager.broadcast_event(
            EFRISWebSocketEvent(
                event_type='sale_completed',
                data={
                    'sale_id': instance.pk,
                    'sale_number': getattr(instance, 'invoice_number', f'SALE-{instance.pk}'),
                    'total_amount': str(instance.total_amount),
                    'auto_fiscalize_queued': bool(invoice and invoice.total_amount > 0),
                    'fiscalization_status': 'queued' if invoice and invoice.total_amount > 0 else 'skipped'
                },
                company_id=company.pk,
                event_category='sale'
            )
        )

    except Exception as e:
        logger.error(f"Error handling sale completion for EFRIS: {e}")


@receiver(post_save, sender='invoices.Invoice')
def handle_invoice_creation_for_efris(sender, instance, created, **kwargs):
    """Handle new invoices for auto-fiscalization"""
    if not created:
        return

    try:
        # Get company safely through the relationships
        company = None
        if instance.store:
            company = instance.store.company
        elif instance.sale and instance.sale.store:
            company = instance.sale.store.company

        if not company or not company.efris_enabled:
            return

        # Auto-fiscalize if conditions are met
        if (instance.status in ['SENT', 'PAID'] and
                not instance.is_fiscalized and
                instance.document_type == 'INVOICE' and
                getattr(company, 'efris_auto_fiscalize_invoices', False)):
            _queue_invoice_fiscalization(instance, company, priority=1)

            # Create notification
            create_efris_notification(
                company,
                'Invoice Queued for Fiscalization',
                f'Invoice {instance.invoice_number} has been queued for automatic fiscalization.',
                'info'
            )

    except Exception as e:
        logger.error(f"Error handling invoice creation for EFRIS: {e}")


# Product Management Signals
@receiver(post_save, sender='inventory.Product')
def handle_product_changes_for_efris(sender, instance, created, **kwargs):
    """Handle product changes for EFRIS sync"""
    try:
        # Get company from current tenant or product's stores
        company = None

        try:
            from django_tenants.utils import get_current_tenant
            company = get_current_tenant()
        except ImportError:
            # If not using django-tenants, try to get company from product's stores
            if hasattr(instance, 'stores') and instance.stores.exists():
                company = instance.stores.first().company

        if not company or not company.efris_enabled:
            return

        if created and getattr(instance, 'efris_auto_sync_enabled', True):
            # Queue new product for upload
            _queue_product_upload(instance, company, priority=2)

            websocket_manager.broadcast_product_status(
                company.pk, [instance.pk], 'queued',
                f'Product {instance.name} queued for EFRIS upload',
                product_name=instance.name, sku=instance.sku
            )

        elif not created and getattr(instance, '_efris_needs_update', False):
            # Product was updated, queue for re-upload if already uploaded
            if getattr(instance, 'efris_is_uploaded', False):
                _queue_product_upload(instance, company, priority=3, is_update=True)

                websocket_manager.broadcast_product_status(
                    company.pk, [instance.pk], 'update_queued',
                    f'Product {instance.name} queued for EFRIS update',
                    product_name=instance.name, sku=instance.sku
                )

    except Exception as e:
        logger.error(f"Error handling product changes for EFRIS: {e}")


@receiver(pre_save, sender='inventory.Product')
def track_product_efris_changes(sender, instance, **kwargs):
    """Track changes to EFRIS-relevant product fields"""
    if not instance.pk:
        return

    try:
        Product = apps.get_model('inventory', 'Product')
        old_instance = Product.objects.get(pk=instance.pk)

        # Fields that affect EFRIS
        efris_fields = [
            'name', 'sku', 'selling_price', 'cost_price', 'tax_rate',
            'unit_of_measure', 'efris_commodity_category_id', 'excise_duty_rate',
            'efris_goods_name', 'efris_goods_code', 'efris_unit_of_measure_code'
        ]

        # Check if any EFRIS-relevant fields changed
        for field in efris_fields:
            old_value = getattr(old_instance, field, None)
            new_value = getattr(instance, field, None)

            if old_value != new_value:
                instance._efris_needs_update = True
                instance._efris_changed_fields = getattr(instance, '_efris_changed_fields', [])
                instance._efris_changed_fields.append(field)
                break

    except Product.DoesNotExist:
        pass  # New product
    except Exception as e:
        logger.error(f"Error tracking product EFRIS changes: {e}")


# Customer Management Signals
@receiver(post_save, sender='customers.Customer')
def handle_customer_changes_for_efris(sender, instance, created, **kwargs):
    """Handle customer changes for EFRIS validation"""
    try:
        # Get company from current tenant
        company = None

        try:
            from django_tenants.utils import get_current_tenant
            company = get_current_tenant()
        except ImportError:
            # Fallback for non-tenant setups
            pass

        if not company or not company.efris_enabled:
            return

        # If customer has TIN and is business type, validate with EFRIS
        if (getattr(instance, 'customer_type', '') == 'BUSINESS' and
                getattr(instance, 'tin', None) and
                not getattr(instance, '_efris_tin_validated', False)):
            _queue_customer_validation(instance, company)

            websocket_manager.broadcast_event(
                EFRISWebSocketEvent(
                    event_type='customer_tin_validation_queued',
                    data={
                        'customer_id': instance.pk,
                        'customer_name': instance.name,
                        'tin': instance.tin,
                        'queued_for_validation': True
                    },
                    company_id=company.pk,
                    event_category='customer'
                )
            )

    except Exception as e:
        logger.error(f"Error handling customer changes for EFRIS: {e}")


# Stock Management Signals
@receiver(post_save, sender='inventory.Stock')
def handle_stock_changes_for_efris(sender, instance, created, **kwargs):
    """Handle stock changes for EFRIS sync"""
    try:
        if not instance.store or not hasattr(instance.store, 'company'):
            return

        company = instance.store.company
        if not company.efris_enabled or not getattr(company, 'efris_sync_stock', False):
            return

        # Only sync stock for EFRIS-uploaded products
        if getattr(instance.product, 'efris_is_uploaded', False):
            _queue_stock_sync(instance, company)

    except Exception as e:
        logger.error(f"Error handling stock changes for EFRIS: {e}")


# Configuration Management Signals
@receiver(post_save, sender='company.Company')
def setup_efris_configuration(sender, instance, created, **kwargs):
    """Set up EFRIS configuration when company enables EFRIS"""

    # Skip if EFRIS not enabled
    if not getattr(instance, 'efris_enabled', False):
        return

    # Skip if company is not active (e.g., during suspension/reactivation)
    if hasattr(instance, 'is_active') and not instance.is_active:
        return

    # Skip if we're in public schema (this signal runs in public schema)
    from django.db import connection
    if hasattr(connection, 'schema_name') and connection.schema_name == 'public':
        # We need to run this in tenant schema context
        from django_tenants.utils import schema_context

        try:
            with schema_context(instance.schema_name):
                from efris.models import EFRISConfiguration

                # Check if EFRIS table exists in this tenant
                with connection.cursor() as cursor:
                    cursor.execute("""
                                   SELECT EXISTS (SELECT 1
                                                  FROM information_schema.tables
                                                  WHERE table_schema = %s
                                                    AND table_name = 'efris_efrisconfiguration')
                                   """, [instance.schema_name])

                    if not cursor.fetchone()[0]:
                        logger.warning(f"EFRIS table doesn't exist in schema {instance.schema_name}")
                        return

                config, config_created = EFRISConfiguration.objects.get_or_create(
                    company=instance,
                    defaults={
                        'environment': 'sandbox',
                        'mode': 'online',
                        'app_id': 'AP04',
                        'version': '1.1.20191201',
                        'device_mac': 'FFFFFFFFFFFF',
                        'api_url': 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation',
                        'timeout_seconds': 30,
                        'max_retry_attempts': 3,
                        'auto_sync_enabled': True,
                        'auto_fiscalize': True,
                        'is_active': True
                    }
                )

                if config_created:
                    logger.info(f"Created EFRIS configuration for company {instance.display_name}")

                    # Create welcome notification in tenant schema
                    create_efris_notification(
                        instance,
                        'EFRIS Integration Enabled',
                        'EFRIS has been enabled for your company. Please configure your certificates and settings.',
                        'info',
                        'high'
                    )

        except Exception as e:
            logger.error(f"Failed to create EFRIS configuration for {instance.display_name}: {e}")
            return

    else:
        # We're already in tenant schema (shouldn't happen for company.Company)
        logger.warning(
            f"setup_efris_configuration called in non-public schema: {getattr(connection, 'schema_name', 'unknown')}")


@receiver(pre_save, sender=EFRISConfiguration)
def validate_efris_configuration_changes(sender, instance, **kwargs):
    """Validate and set defaults for EFRIS configuration"""
    # Set API URL based on environment
    if not instance.api_url:
        if instance.environment == 'production':
            instance.api_url = 'https://efris.ura.go.ug/efrisws/ws/taapp/getInformation'
        else:
            instance.api_url = 'https://efristest.ura.go.ug/efrisws/ws/taapp/getInformation'

    # Ensure device number format
    if instance.device_number and not instance.device_number.endswith('_01'):
        if instance.company.tin:
            instance.device_number = f"{instance.company.tin}_01"

def _queue_invoice_fiscalization(invoice, company, priority: int = 1):
    """Queue invoice for fiscalization with WebSocket updates"""
    try:
        # Get invoice details safely
        invoice_number = getattr(invoice, 'invoice_number', None) or getattr(invoice, 'number', f'INV-{invoice.pk}')
        total_amount = getattr(invoice, 'total_amount', 0)

        # Get customer name safely from the correct relationship
        customer_name = 'Unknown Customer'
        if hasattr(invoice, 'sale') and invoice.sale and hasattr(invoice.sale, 'customer') and invoice.sale.customer:
            customer_name = invoice.sale.customer.name

        queue_item, created = EFRISSyncQueue.objects.get_or_create(
            company=company,
            sync_type='invoice_fiscalize',
            object_id=invoice.pk,
            object_type='invoice',
            status__in=['pending', 'processing'],
            defaults={
                'status': 'pending',
                'priority': priority,
                'scheduled_at': timezone.now(),
                'task_data': {
                    'invoice_number': invoice_number,
                    'total_amount': str(total_amount),
                    'customer_name': customer_name,
                    'created_by_signal': True
                }
            }
        )

        if created:
            # Broadcast queue event
            websocket_manager.broadcast_queue_status(
                company.pk, queue_item.pk, 'invoice_fiscalize',
                invoice.pk, 'queued', f'Invoice {invoice_number} queued for fiscalization'
            )


            if priority == 1:
                fiscalize_invoice_async.delay(invoice.pk)

            logger.info(f"Queued invoice {invoice_number} for fiscalization")

    except Exception as e:
        logger.error(f"Failed to queue invoice fiscalization: {e}")




def _create_and_queue_invoice_from_sale(sale, company):
    """Create invoice from sale and queue for fiscalization"""
    try:
        # Import here to avoid circular imports
        from sales.services import SalesEFRISService  # Fixed import path

        service = SalesEFRISService(company)
        can_create, message, invoice = service.create_invoice_for_fiscalization(
            sale, sale.created_by
        )

        if can_create and invoice:
            # Queue for fiscalization if needed
            logger.info(f"Created invoice {invoice.invoice_number} for sale {sale.id}")
            return True
        else:
            logger.warning(f"Cannot create invoice for sale {sale.id}: {message}")
            return False

    except Exception as e:
        logger.error(f"Error creating invoice from sale {sale.id}: {e}")
        return False

def _queue_product_upload(product, company, priority: int = 2, is_update: bool = False):
    """Queue product for EFRIS upload"""
    try:
        sync_type = 'product_update' if is_update else 'product_upload'

        queue_item, created = EFRISSyncQueue.objects.get_or_create(
            company=company,
            sync_type=sync_type,
            object_id=product.pk,
            object_type='product',
            status__in=['pending', 'processing'],
            defaults={
                'status': 'pending',
                'priority': priority,
                'scheduled_at': timezone.now(),
                'task_data': {
                    'product_name': product.name,
                    'sku': getattr(product, 'sku', ''),
                    'selling_price': str(getattr(product, 'selling_price', 0)),
                    'is_update': is_update,
                    'created_by_signal': True
                }
            }
        )

        if created:
            # Process high priority items immediately
            if priority <= 2:
                upload_products_async.delay(company.pk, [product.pk])

            logger.info(f"Queued product {product.name} for {'update' if is_update else 'upload'}")

    except Exception as e:
        logger.error(f"Failed to queue product upload: {e}")


def _queue_customer_validation(customer, company):
    """Queue customer TIN validation"""
    try:
        queue_item, created = EFRISSyncQueue.objects.get_or_create(
            company=company,
            sync_type='customer_validate',
            object_id=customer.pk,
            object_type='customer',
            status__in=['pending', 'processing'],
            defaults={
                'status': 'pending',
                'priority': 3,  # Low priority
                'scheduled_at': timezone.now(),
                'task_data': {
                    'customer_name': customer.name,
                    'tin': getattr(customer, 'tin', ''),
                    'customer_type': getattr(customer, 'customer_type', ''),
                    'created_by_signal': True
                }
            }
        )

        if created:
            validate_customer_tin_async.delay(company.pk, customer.pk)
            logger.info(f"Queued customer {customer.name} TIN validation")

    except Exception as e:
        logger.error(f"Failed to queue customer validation: {e}")


def _queue_stock_sync(stock, company):
    """Queue stock synchronization"""
    try:
        queue_item, created = EFRISSyncQueue.objects.get_or_create(
            company=company,
            sync_type='stock_sync',
            object_id=stock.pk,
            object_type='stock',
            status__in=['pending', 'processing'],
            defaults={
                'status': 'pending',
                'priority': 4,  # Lowest priority
                'scheduled_at': timezone.now() + timezone.timedelta(minutes=5),  # Slight delay
                'task_data': {
                    'product_name': stock.product.name,
                    'store_name': stock.store.name,
                    'quantity': str(stock.quantity),
                    'created_by_signal': True
                }
            }
        )

        if created:
            logger.info(f"Queued stock sync for {stock.product.name}")

    except Exception as e:
        logger.error(f"Failed to queue stock sync: {e}")


def create_efris_notification(company, title: str, message: str,
                              notification_type: str = 'info', priority: str = 'normal'):
    """Create EFRIS notification and broadcast it via WebSocket"""
    try:
        notification = EFRISNotification.objects.create(
            company=company,
            title=title,
            message=message,
            notification_type=notification_type,
            priority=priority
        )

        # Broadcast notification via WebSocket
        websocket_manager.send_notification(
            company.pk, title, message, notification_type, priority,
            metadata={'notification_id': notification.pk}
        )

        return notification

    except Exception as e:
        logger.error(f"Failed to create EFRIS notification: {e}")
        return None


# Update existing signals to use WebSocket manager
@receiver(post_save, sender=apps.get_model('sales', 'Sale'))
def handle_sale_completion_for_efris(sender, instance, created, **kwargs):
    """Handle completed sales for auto-fiscalization with WebSocket updates"""
    if not instance.is_completed or instance.transaction_type != 'SALE':
        return

    try:
        company = instance.store.company
        if not company.efris_enabled or not company.efris_auto_fiscalize_sales:
            return

        # Check if sale already has an invoice
        if hasattr(instance, 'invoice') and instance.invoice:
            if not instance.invoice.is_fiscalized:
                _queue_invoice_fiscalization(instance.invoice, company, priority=1)
        else:
            # Create invoice first, then fiscalize
            _create_and_queue_invoice_from_sale(instance, company)

        # Broadcast sale completion event via WebSocket
        websocket_manager.broadcast_event(
            EFRISWebSocketEvent(
                event_type='sale_completed',
                data={
                    'sale_id': instance.pk,
                    'sale_number': instance.invoice_number or f"SALE-{instance.pk}",
                    'total_amount': str(instance.total_amount),
                    'auto_fiscalize_queued': True
                },
                company_id=company.pk,
                event_category='sale'
            )
        )

    except Exception as e:
        logger.error(f"Error handling sale completion for EFRIS: {e}")




