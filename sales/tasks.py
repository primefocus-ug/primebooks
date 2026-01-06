from celery import shared_task
from .models import Sale
from django.conf import settings
from django.utils.timezone import now
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from django.db import connection
import logging
import uuid
from django_tenants.utils import tenant_context, schema_context, get_tenant_model
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from invoices.models import Invoice
from efris.services import EFRISInvoiceService, create_efris_service
from efris.models import EFRISAPILog, FiscalizationAudit

logger = logging.getLogger(__name__)


class TenantResolver:
    @staticmethod
    def get_current_schema():
        try:
            return connection.schema_name
        except AttributeError:
            try:
                return getattr(connection, 'schema_name', None)
            except:
                return None

    @staticmethod
    def get_all_tenant_schemas():
        current_schema = TenantResolver.get_current_schema()

        try:
            with schema_context('public'):
                tenant_model = get_tenant_model()
                schemas = list(tenant_model.objects.exclude(
                    schema_name='public'
                ).values_list('schema_name', flat=True))

            if current_schema and current_schema != 'public':
                try:
                    connection.set_schema(current_schema)
                except Exception as restore_error:
                    logger.warning(f"Could not restore schema {current_schema}: {restore_error}")

            logger.debug(f"Found {len(schemas)} tenant schemas (current: {current_schema})")
            return schemas

        except Exception as e:
            logger.error(f"Error getting tenant schemas: {e}", exc_info=True)
            return []

    @staticmethod
    def find_sale_schema(sale_id):
        """Find the tenant schema for a sale"""
        current_schema = TenantResolver.get_current_schema()
        schemas = TenantResolver.get_all_tenant_schemas()

        if current_schema and current_schema != 'public':
            try:
                with schema_context(current_schema):
                    sale = Sale.objects.select_related(
                        'store__company', 'created_by', 'customer'
                    ).prefetch_related('items').get(id=sale_id)
                    logger.info(f"Found sale {sale_id} in current schema: {current_schema}")
                    return sale, current_schema
            except Sale.DoesNotExist:
                logger.debug(f"Sale {sale_id} not in current schema {current_schema}, searching others")
            except Exception as e:
                logger.debug(f"Error checking current schema {current_schema} for sale {sale_id}: {e}")

        # Search all other schemas
        for schema_name in schemas:
            if schema_name == current_schema:
                continue

            try:
                with schema_context(schema_name):
                    sale = Sale.objects.select_related(
                        'store__company', 'created_by', 'customer'
                    ).prefetch_related('items').get(id=sale_id)
                    logger.info(f"Found sale {sale_id} in schema: {schema_name}")

                    # Restore original schema
                    if current_schema and current_schema != 'public':
                        try:
                            connection.set_schema(current_schema)
                        except:
                            pass

                    return sale, schema_name
            except Sale.DoesNotExist:
                continue
            except Exception as e:
                logger.debug(f"Error checking schema {schema_name} for sale {sale_id}: {e}")
                continue

        logger.error(f"Sale {sale_id} not found in any tenant schema")

        # Restore original schema
        if current_schema and current_schema != 'public':
            try:
                connection.set_schema(current_schema)
            except:
                pass

        return None, None

    @staticmethod
    def resolve_company_from_sale(sale):
        """
        Resolve company from sale relationships
        """
        if sale.store and hasattr(sale.store, 'company'):
            return sale.store.company
        return None

@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def process_receipt_async(self, sale_id, user_id=None):
    """
    Process receipt asynchronously - handles stock updates, notifications, etc.
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        # Find sale and its tenant schema
        sale, tenant_schema = TenantResolver.find_sale_schema(sale_id)

        if not sale or not tenant_schema:
            logger.error(f"Receipt {sale_id} not found in any tenant schema")
            return {'success': False, 'message': 'Receipt not found'}

        with schema_context(tenant_schema):
            # Re-fetch sale with related data
            sale = Sale.objects.select_related(
                'store__company', 'customer', 'created_by'
            ).prefetch_related('items__product').get(id=sale_id)

            # Only process receipts
            if sale.document_type != 'RECEIPT':
                return {
                    'success': False,
                    'message': f'Not a receipt: {sale.document_type}'
                }

            logger.info(f"Processing receipt {sale.document_number} in background")

            # Process receipt-specific tasks
            results = {
                'stock_updated': False,
                'notifications_sent': False,
                'efris_processed': False
            }

            # 1. Update stock (if needed)
            if sale.items.filter(item_type='PRODUCT').exists():
                try:
                    results['stock_updated'] = True
                except Exception as e:
                    logger.error(f"Failed to update stock for receipt {sale_id}: {e}")

            # 2. Send notifications
            try:
                send_receipt_notification.delay(sale_id)
                results['notifications_sent'] = True
            except Exception as e:
                logger.warning(f"Failed to queue receipt notification: {e}")

            # 3. Process EFRIS if enabled and auto-fiscalize is on
            store_config = sale.store.effective_efris_config
            if (store_config.get('enabled', False) and
                    store_config.get('auto_fiscalize_receipts', False)):
                try:
                    # Fiscalize receipt in background
                    fiscalize_invoice_async.delay(sale_id, user_id)
                    results['efris_processed'] = True
                except Exception as e:
                    logger.warning(f"Failed to queue receipt fiscalization: {e}")

            return {
                'success': True,
                'message': f'Receipt {sale.document_number} processed successfully',
                'results': results,
                'schema': tenant_schema
            }

    except Exception as e:
        logger.error(f"Error processing receipt {sale_id}: {e}", exc_info=True)
        return {'success': False, 'message': str(e)}

    finally:
        # Restore schema
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except:
                pass


@shared_task
def send_receipt_notification(sale_id):
    """
    Send receipt notifications asynchronously
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        sale, tenant_schema = TenantResolver.find_sale_schema(sale_id)

        if not sale or not tenant_schema:
            return

        with schema_context(tenant_schema):
            sale = Sale.objects.select_related(
                'customer', 'created_by', 'store__company'
            ).get(id=sale_id)

            # Skip if not a receipt
            if sale.document_type != 'RECEIPT':
                return

            # Send email notification
            if sale.customer and sale.customer.email:
                try:
                    send_mail(
                        subject=f"Receipt {sale.document_number}",
                        message=f"Your receipt {sale.document_number} for {sale.total_amount} {sale.currency} has been processed.",
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[sale.customer.email],
                        fail_silently=True
                    )
                    logger.info(f"Receipt email sent to {sale.customer.email}")
                except Exception as e:
                    logger.error(f"Failed to send receipt email: {e}")

            # Send WebSocket notification for POS
            try:
                channel_layer = get_channel_layer()
                async_to_sync(channel_layer.group_send)(
                    f'pos_{sale.store.id}',
                    {
                        'type': 'receipt.completed',
                        'data': {
                            'receipt_number': sale.document_number,
                            'customer': sale.customer.name if sale.customer else 'Walk-in',
                            'total': float(sale.total_amount),
                            'timestamp': timezone.now().isoformat()
                        }
                    }
                )
            except Exception as e:
                logger.warning(f"Failed to send WebSocket notification: {e}")

    except Exception as e:
        logger.error(f"Error in send_receipt_notification: {e}")

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except:
                pass


@shared_task(bind=True)
def create_sale_background(self, form_data, user_id, task_id):
    """
    Create sale in background with progress updates
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        # Get user
        from django.contrib.auth import get_user_model
        from stores.models import Store
        from django.db import transaction
        from decimal import Decimal
        from inventory.models import Product,Service
        from sales.models import SaleItem,Payment
        from .signals import send_receipt_ws_update
        from .views import create_stock_movements
        import json
        User = get_user_model()

        # Find user's tenant schema
        user, user_schema = TenantResolver.find_user_schema(user_id)
        if not user or not user_schema:
            return {'success': False, 'error': 'User not found'}

        with schema_context(user_schema):
            # Update progress
            update_task_progress(task_id, 20, 'Validating data...')

            # Get company
            company = get_current_tenant_from_user(user)

            # Validate data
            update_task_progress(task_id, 30, 'Validating store and items...')

            try:
                store = Store.objects.get(
                    id=form_data['store'],
                    company=company,
                    is_active=True
                )
            except Store.DoesNotExist:
                update_task_progress(task_id, 100, 'Error: Invalid store', 'error')
                return {'success': False, 'error': 'Invalid store'}

            # Validate items
            try:
                items_data = json.loads(form_data.get('items_data', '[]'))
                if not items_data:
                    update_task_progress(task_id, 100, 'Error: No items', 'error')
                    return {'success': False, 'error': 'No items'}
            except json.JSONDecodeError:
                update_task_progress(task_id, 100, 'Error: Invalid items data', 'error')
                return {'success': False, 'error': 'Invalid items data'}

            # Create sale
            update_task_progress(task_id, 40, 'Creating sale record...')

            with transaction.atomic():
                # Create sale
                sale = Sale.objects.create(
                    store=store,
                    created_by=user,
                    customer_id=form_data.get('customer') if form_data.get('customer') else None,
                    document_type=form_data.get('document_type', 'RECEIPT'),
                    payment_method=form_data.get('payment_method', 'CASH'),
                    currency='UGX',
                    discount_amount=Decimal(form_data.get('discount_amount', '0')),
                    notes=form_data.get('notes', ''),
                    due_date=form_data.get('due_date'),
                    status='DRAFT',
                )

                # Add items
                update_task_progress(task_id, 50, 'Adding items to sale...')

                for item_data in items_data:
                    try:
                        item_type = item_data.get('item_type', 'PRODUCT')

                        if item_type == 'PRODUCT':
                            product = Product.objects.get(
                                id=item_data['product_id'],
                                is_active=True
                            )
                            SaleItem.objects.create(
                                sale=sale,
                                item_type='PRODUCT',
                                product=product,
                                quantity=Decimal(str(item_data.get('quantity', 1))),
                                unit_price=Decimal(str(item_data.get('unit_price', 0))),
                                tax_rate=item_data.get('tax_rate', 'A'),
                                discount=Decimal(str(item_data.get('discount', 0))),
                            )
                        elif item_type == 'SERVICE':
                            service = Service.objects.get(
                                id=item_data['service_id'],
                                is_active=True
                            )
                            SaleItem.objects.create(
                                sale=sale,
                                item_type='SERVICE',
                                service=service,
                                quantity=Decimal(str(item_data.get('quantity', 1))),
                                unit_price=Decimal(str(item_data.get('unit_price', 0))),
                                tax_rate=item_data.get('tax_rate', 'A'),
                                discount=Decimal(str(item_data.get('discount', 0))),
                            )
                    except (Product.DoesNotExist, Service.DoesNotExist) as e:
                        logger.error(f"Item not found: {e}")
                        continue

                # Update totals
                update_task_progress(task_id, 70, 'Calculating totals...')
                sale.update_totals()
                sale.status = 'COMPLETED' if sale.document_type == 'RECEIPT' else 'PENDING_PAYMENT'
                sale.save()

                # Handle payment
                if form_data.get('payment_amount'):
                    try:
                        amount = Decimal(form_data['payment_amount'])
                        if amount > 0:
                            Payment.objects.create(
                                sale=sale,
                                store=sale.store,
                                amount=amount,
                                payment_method=sale.payment_method,
                                transaction_reference=form_data.get('payment_reference', ''),
                                is_confirmed=True,
                                confirmed_at=timezone.now(),
                                created_by=sale.created_by
                            )
                    except Exception as e:
                        logger.error(f"Payment creation failed: {e}")

                # Send WebSocket update
                update_task_progress(task_id, 80, 'Sending notifications...')
                send_receipt_ws_update(sale)

                # Queue background processing
                update_task_progress(task_id, 90, 'Queueing background tasks...')

                if sale.document_type == 'RECEIPT':
                    process_receipt_async.delay(sale.pk, user_id)
                elif sale.document_type == 'INVOICE':
                    # Create stock movements for invoices
                    create_stock_movements(sale)

                    # Auto-fiscalization
                    store_config = sale.store.effective_efris_config
                    if store_config.get('enabled', False):
                        fiscalize_invoice_async.delay(sale.pk, user_id)

                # Final update
                update_task_progress(
                    task_id,
                    100,
                    f'{sale.get_document_type_display()} #{sale.document_number} created successfully!',
                    'completed',
                    sale_id=sale.pk
                )

                return {
                    'success': True,
                    'sale_id': sale.pk,
                    'document_number': sale.document_number,
                    'total_amount': float(sale.total_amount)
                }

    except Exception as e:
        logger.error(f"Background sale creation failed: {e}", exc_info=True)
        update_task_progress(task_id, 100, f'Error: {str(e)}', 'error')
        return {'success': False, 'error': str(e)}

    finally:
        # Restore schema
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except:
                pass


def update_task_progress(task_id, progress, message, status='processing', sale_id=None):
    """
    Update task progress (would typically use Django cache or database)
    """
    # Using cache (requires Django cache setup)
    from django.core.cache import cache

    task_data = {
        'status': status,
        'message': message,
        'progress': progress,
        'sale_id': sale_id,
        'updated_at': timezone.now().isoformat()
    }

    # Store in cache for 10 minutes
    cache.set(f'sale_task_{task_id}', task_data, 600)

    try:
        from django.contrib.sessions.models import Session
        # This is a simplified version - in production you'd need to find all relevant sessions
        pass
    except:
        pass

    # Send WebSocket update
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f'task_progress_{task_id}',
            {
                'type': 'task.progress',
                'data': task_data
            }
        )
    except Exception as e:
        logger.debug(f"WebSocket update failed: {e}")


def update_stock_for_receipt(sale):
    """Update stock for products in receipt - FIXED VERSION"""
    from inventory.models import Stock, StockMovement
    from django.db.models import F

    for item in sale.items.filter(item_type='PRODUCT'):
        if item.product:
            try:
                # Use update() instead of save() with F() expression
                updated = Stock.objects.filter(
                    product=item.product,
                    store=sale.store
                ).update(
                    quantity=F('quantity') - item.quantity
                )

                if updated:
                    # Refresh the stock object to get actual quantity
                    stock = Stock.objects.get(
                        product=item.product,
                        store=sale.store
                    )

                    # Create stock movement
                    StockMovement.objects.create(
                        product=item.product,
                        store=sale.store,
                        movement_type='SALE',
                        quantity=item.quantity,
                        reference=f"RECEIPT-{sale.document_number}",
                        unit_price=item.unit_price,
                        total_value=item.total_price,
                        created_by=sale.created_by,
                        notes=f"Receipt: {sale.document_number}"
                    )

                    # Force refresh of stock to clear F() expressions
                    stock.refresh_from_db()

                    logger.debug(f"Updated stock for {item.product.name}: -{item.quantity}")

                else:
                    # Create stock record if it doesn't exist
                    stock = Stock.objects.create(
                        product=item.product,
                        store=sale.store,
                        quantity=-item.quantity,  # Negative for initial stock
                        last_updated=timezone.now()
                    )

                    # Create stock movement
                    StockMovement.objects.create(
                        product=item.product,
                        store=sale.store,
                        movement_type='SALE',
                        quantity=item.quantity,
                        reference=f"RECEIPT-{sale.document_number}",
                        unit_price=item.unit_price,
                        total_value=item.total_price,
                        created_by=sale.created_by,
                        notes=f"Receipt: {sale.document_number} (initial stock)"
                    )

                    logger.debug(f"Created stock record for {item.product.name}")

            except Exception as e:
                logger.error(f"Failed to update stock for {item.product.name}: {e}")



@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def fiscalize_invoice_async(self, sale_id, user_id=None):
    """
    Fiscalize sale asynchronously - works for BOTH RECEIPTS and INVOICES
    """
    initial_schema = TenantResolver.get_current_schema()
    logger.info(
        f"Sale fiscalization task started for sale {sale_id} "
        f"(initial schema: {initial_schema}, task_id: {self.request.id})"
    )

    try:
        # Find sale and its tenant schema
        sale, tenant_schema = TenantResolver.find_sale_schema(sale_id)

        if not sale or not tenant_schema:
            logger.error(f"Sale {sale_id} not found in any tenant schema")
            return {
                'success': False,
                'message': 'Sale not found in any tenant',
                'schema': None
            }

        logger.info(f"Processing sale {sale_id} (type: {sale.document_type}) in tenant schema: {tenant_schema}")

        # Execute within the correct tenant context
        with schema_context(tenant_schema):
            # Re-fetch sale
            sale = Sale.objects.select_related(
                'store__company', 'customer', 'created_by'
            ).prefetch_related('items__product', 'items__service').get(id=sale_id)

            # Get user if provided
            user = None
            if user_id:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                try:
                    user = User.objects.get(pk=user_id)
                except User.DoesNotExist:
                    logger.warning(f"User {user_id} not found in schema {tenant_schema}")

            # Check if sale can be fiscalized
            if sale.document_type not in ['RECEIPT', 'INVOICE']:
                logger.warning(f"Sale {sale.document_number} ({sale.get_document_type_display()}) cannot be fiscalized")
                return {
                    'success': False,
                    'message': f'{sale.get_document_type_display()} cannot be fiscalized',
                    'schema': tenant_schema
                }

            # Check if already fiscalized
            if sale.is_fiscalized:
                logger.info(f"Sale {sale.document_number} is already fiscalized")

                # ✅ Even if already fiscalized, ensure stock movements are synced
                sale.fiscalize_and_sync_stock()

                return {
                    'success': True,
                    'message': 'Sale already fiscalized',
                    'fiscal_number': sale.efris_invoice_number,
                    'schema': tenant_schema
                }

            # Fiscalize sale
            try:
                from efris.services import EFRISInvoiceService

                efris_service = EFRISInvoiceService(company=sale.store.company)
                result = efris_service.fiscalize_sale(sale, user)

                success = result.get('success', False)
                message = result.get('message', 'Unknown error')
                error_code = result.get('error_code')

                # Handle duplicate invoice error (2253)
                if not success and '2253' in str(error_code or message):
                    logger.warning(
                        f"Sale {sale.document_number} already fiscalized on EFRIS. "
                        f"Extracting fiscal number from error message."
                    )

                    # Extract fiscal number from error message
                    import re
                    match = re.search(r'\((\d+)\)', message)
                    fiscal_doc_number = match.group(1) if match else ''

                    if fiscal_doc_number:
                        sale.efris_invoice_number = fiscal_doc_number
                        sale.verification_code = uuid.uuid4().hex[:8].upper()
                        sale.is_fiscalized = True
                        sale.fiscalization_time = timezone.now()
                        sale.fiscalization_status = 'fiscalized'

                        sale.save(update_fields=[
                            'efris_invoice_number', 'verification_code',
                            'is_fiscalized', 'fiscalization_time', 'fiscalization_status'
                        ])

                        # Update invoice detail if it exists
                        if sale.document_type == 'INVOICE' and hasattr(sale, 'invoice_detail') and sale.invoice_detail:
                            invoice = sale.invoice_detail
                            invoice.fiscal_document_number = fiscal_doc_number
                            invoice.fiscal_number = fiscal_doc_number
                            invoice.verification_code = sale.verification_code
                            invoice.is_fiscalized = True
                            invoice.fiscalization_time = sale.fiscalization_time
                            invoice.fiscalization_status = 'fiscalized'
                            invoice.save(update_fields=[
                                'fiscal_document_number', 'fiscal_number', 'verification_code',
                                'is_fiscalized', 'fiscalization_time', 'fiscalization_status'
                            ])

                        # ✅ IMPORTANT: Sync stock movements after fiscalization
                        sale.fiscalize_and_sync_stock()

                        logger.info(f"Recovered fiscalized sale {sale.document_number} (Fiscal #: {fiscal_doc_number})")

                        return {
                            'success': True,
                            'message': f'Sale already fiscalized (recovered): {fiscal_doc_number}',
                            'fiscal_number': fiscal_doc_number,
                            'document_type': sale.document_type,
                            'schema': tenant_schema
                        }

                if success:
                    # Extract EFRIS data
                    efris_data = result.get('data', {})

                    fiscal_doc_number = (
                            efris_data.get('invoice_no') or
                            efris_data.get('invoiceNo') or
                            efris_data.get('full_response', {}).get('basicInformation', {}).get('invoiceNo', '') or
                            efris_data.get('fiscal_document_number', '')
                    )

                    verification_code = (
                            efris_data.get('fiscal_code') or
                            efris_data.get('verification_code') or
                            efris_data.get('antifakeCode') or
                            efris_data.get('full_response', {}).get('basicInformation', {}).get('antifakeCode', '') or
                            uuid.uuid4().hex[:8].upper()
                    )

                    qr_code = (
                            efris_data.get('qrCode') or
                            efris_data.get('qr_code') or
                            efris_data.get('full_response', {}).get('summary', {}).get('qrCode', '') or
                            sale.qr_code
                    )

                    # Update sale fields
                    sale.efris_invoice_number = fiscal_doc_number
                    sale.verification_code = verification_code
                    sale.qr_code = qr_code
                    sale.is_fiscalized = True
                    sale.fiscalization_time = timezone.now()
                    sale.fiscalization_status = 'fiscalized'

                    sale.save(update_fields=[
                        'efris_invoice_number', 'verification_code', 'qr_code',
                        'is_fiscalized', 'fiscalization_time', 'fiscalization_status'
                    ])

                    # Update invoice detail if exists
                    if sale.document_type == 'INVOICE' and hasattr(sale, 'invoice_detail') and sale.invoice_detail:
                        try:
                            invoice = sale.invoice_detail
                            invoice.fiscal_document_number = fiscal_doc_number
                            invoice.fiscal_number = fiscal_doc_number
                            invoice.verification_code = verification_code
                            invoice.qr_code = qr_code
                            invoice.is_fiscalized = True
                            invoice.fiscalization_time = sale.fiscalization_time
                            invoice.fiscalization_status = 'fiscalized'

                            invoice.save(update_fields=[
                                'fiscal_document_number', 'fiscal_number', 'verification_code', 'qr_code',
                                'is_fiscalized', 'fiscalization_time', 'fiscalization_status'
                            ])

                            logger.info(f"Updated invoice detail for sale {sale.document_number}")
                        except Exception as invoice_update_error:
                            logger.error(f"Failed to update invoice detail: {invoice_update_error}")

                    # ✅ CRITICAL: Sync stock movements after successful fiscalization
                    sale.fiscalize_and_sync_stock()

                    logger.info(
                        f"✅ Successfully fiscalized {sale.get_document_type_display()} "
                        f"{sale.document_number} (Fiscal #: {fiscal_doc_number})"
                    )

                    return {
                        'success': True,
                        'message': message,
                        'fiscal_number': fiscal_doc_number,
                        'document_type': sale.document_type,
                        'document_number': sale.document_number,
                        'schema': tenant_schema
                    }
                else:
                    # Fiscalization failed
                    sale.fiscalization_status = 'failed'
                    sale.save(update_fields=['fiscalization_status'])

                    if sale.document_type == 'INVOICE' and hasattr(sale, 'invoice_detail') and sale.invoice_detail:
                        try:
                            invoice = sale.invoice_detail
                            invoice.fiscalization_status = 'failed'
                            invoice.save(update_fields=['fiscalization_status'])
                        except Exception as e:
                            logger.error(f"Failed to update invoice status: {e}")

                    # Retry logic
                    if self.request.retries < self.max_retries:
                        countdown = 60 * (2 ** self.request.retries)
                        logger.info(
                            f"Retrying fiscalization of sale {sale.document_number} "
                            f"in {countdown} seconds (attempt {self.request.retries + 1})"
                        )
                        raise self.retry(countdown=countdown, exc=Exception(message))

                    logger.error(f"Fiscalization failed for sale {sale.document_number}: {message}")
                    return {
                        'success': False,
                        'message': message,
                        'document_type': sale.document_type,
                        'schema': tenant_schema
                    }

            except Exception as efris_error:
                error_msg = f"EFRIS service error: {str(efris_error)}"
                logger.error(f"EFRIS service error for sale {sale_id}: {str(efris_error)}", exc_info=True)

                sale.fiscalization_status = 'failed'
                sale.save(update_fields=['fiscalization_status'])

                if sale.document_type == 'INVOICE' and hasattr(sale, 'invoice_detail') and sale.invoice_detail:
                    try:
                        invoice = sale.invoice_detail
                        invoice.fiscalization_status = 'failed'
                        invoice.fiscalization_error = error_msg
                        invoice.save(update_fields=['fiscalization_status', 'fiscalization_error'])
                    except Exception as e:
                        logger.error(f"Failed to update invoice status: {e}")

                # Retry on EFRIS errors (except duplicate errors)
                if self.request.retries < self.max_retries and '2253' not in str(efris_error):
                    countdown = 60 * (2 ** self.request.retries)
                    raise self.retry(countdown=countdown, exc=efris_error)

                return {
                    'success': False,
                    'message': error_msg,
                    'document_type': sale.document_type,
                    'schema': tenant_schema
                }

    except Exception as e:
        logger.error(f"Sale fiscalization task failed for sale {sale_id}: {str(e)}", exc_info=True)

        if 'tenant_schema' in locals() and tenant_schema:
            try:
                with schema_context(tenant_schema):
                    sale = Sale.objects.get(id=sale_id)
                    sale.fiscalization_status = 'failed'
                    sale.save(update_fields=['fiscalization_status'])

                    if sale.document_type == 'INVOICE' and hasattr(sale, 'invoice_detail') and sale.invoice_detail:
                        try:
                            invoice = sale.invoice_detail
                            invoice.fiscalization_status = 'failed'
                            invoice.save(update_fields=['fiscalization_status'])
                        except Exception as inv_error:
                            logger.error(f"Failed to update invoice status: {inv_error}")

            except Exception as update_error:
                logger.error(f"Failed to update sale status for sale {sale_id}: {update_error}")

        return {
            'success': False,
            'message': str(e),
            'schema': tenant_schema if 'tenant_schema' in locals() else None
        }

    finally:
        # Restore original schema context
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
                logger.debug(f"Restored schema context to {initial_schema}")
            except Exception as restore_error:
                logger.warning(f"Could not restore initial schema {initial_schema}: {restore_error}")



@shared_task
def convert_proforma_to_invoice(sale_id, due_date=None, terms=None, user_id=None):
    """
    Convert proforma/estimate to invoice
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        sale, tenant_schema = TenantResolver.find_sale_schema(sale_id)

        if not sale or not tenant_schema:
            logger.error(f"Sale {sale_id} not found in any tenant schema")
            return {'success': False, 'message': 'Sale not found'}

        with schema_context(tenant_schema):
            sale = Sale.objects.select_related('store__company').get(id=sale_id)

            # Validate sale type
            if sale.document_type not in ['PROFORMA', 'ESTIMATE']:
                return {
                    'success': False,
                    'message': f'Cannot convert {sale.get_document_type_display()} to invoice'
                }

            # Convert to invoice
            invoice_sale = sale.convert_to_invoice(due_date=due_date, terms=terms)

            logger.info(f"✅ Converted {sale.document_type} {sale.document_number} to invoice {invoice_sale.document_number}")

            return {
                'success': True,
                'message': f'Successfully converted to invoice {invoice_sale.document_number}',
                'invoice_sale_id': invoice_sale.id,
                'schema': tenant_schema
            }

    except Exception as e:
        logger.error(f"Error converting proforma to invoice for sale {sale_id}: {e}")
        return {'success': False, 'message': str(e)}

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except:
                pass


@shared_task
def sync_invoice_with_efris(invoice_id):
    """
    Self-resolving EFRIS sync task - automatically finds the correct tenant schema
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        invoice, tenant_schema = TenantResolver.find_invoice_schema(invoice_id)

        if not invoice or not tenant_schema:
            logger.error(f"Invoice {invoice_id} not found in any tenant schema for EFRIS sync")
            return

        logger.info(f"Syncing invoice {invoice_id} with EFRIS in schema: {tenant_schema}")

        with schema_context(tenant_schema):
            invoice = Invoice.objects.select_related(
                'store__company',
                'sale__store__company'
            ).get(pk=invoice_id)

            if not invoice.fiscal_document_number:
                logger.warning(f"Invoice {invoice.invoice_number} has no fiscal document number")
                return

            company = TenantResolver.resolve_company_from_invoice(invoice)
            if not company:
                logger.error(f"No company found for invoice {invoice_id}")
                return

            try:
                efris_service = EFRISInvoiceService(company)
                success, result = efris_service.query_invoices(
                    filters={'invoiceNo': invoice.fiscal_document_number}
                )

                if success and result.get('invoices'):
                    efris_invoice = result['invoices'][0]

                    updated = False
                    updates = {}

                    if efris_invoice.get('status') and efris_invoice['status'] != getattr(invoice, 'efris_status',
                                                                                          None):
                        invoice.efris_status = efris_invoice['status']
                        updates['efris_status'] = efris_invoice['status']
                        updated = True

                    if efris_invoice.get('verification_code') and efris_invoice[
                        'verification_code'] != invoice.verification_code:
                        invoice.verification_code = efris_invoice['verification_code']
                        updates['verification_code'] = efris_invoice['verification_code']
                        updated = True

                    if updated:
                        invoice.save(update_fields=list(updates.keys()))
                        logger.info(f"Updated invoice {invoice.invoice_number} from EFRIS sync: {list(updates.keys())}")

            except Exception as efris_error:
                logger.error(f"EFRIS sync failed for invoice {invoice_id}: {str(efris_error)}")

    except Exception as e:
        logger.error(f"Error in sync_invoice_with_efris for invoice {invoice_id}: {e}")

    finally:
        if initial_schema:
            try:
                connection.set_schema(initial_schema)
            except:
                pass


@shared_task
def send_fiscalization_notification(invoice_id, success=True, error=None):
    """
    Self-resolving notification task - automatically finds the correct tenant schema
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        invoice, tenant_schema = TenantResolver.find_invoice_schema(invoice_id)

        if not invoice or not tenant_schema:
            logger.error(f"Invoice {invoice_id} not found in any tenant schema for notification")
            return

        with schema_context(tenant_schema):
            invoice = Invoice.objects.select_related(
                'store__company',
                'sale__store__company',
                'created_by'
            ).get(pk=invoice_id)

            company = TenantResolver.resolve_company_from_invoice(invoice)

            if success:
                subject = f"Invoice {invoice.invoice_number} Successfully Fiscalized"
                message = (
                    f"Invoice {invoice.invoice_number} has been successfully fiscalized with EFRIS.\n"
                    f"Fiscal Document Number: {invoice.fiscal_document_number}\n"
                    f"Verification Code: {invoice.verification_code}\n"
                    f"Tenant: {tenant_schema}\n"
                )
            else:
                subject = f"Invoice {invoice.invoice_number} Fiscalization Failed"
                message = (
                    f"Invoice {invoice.invoice_number} fiscalization failed.\n"
                    f"Error: {error or 'Unknown error'}\n"
                    f"Tenant: {tenant_schema}\n"
                    f"Please check the invoice and retry manually.\n"
                )

            recipients = []
            if invoice.created_by and invoice.created_by.email:
                recipients.append(invoice.created_by.email)

            admin_emails = getattr(settings, 'EFRIS_ADMIN_EMAILS', [])
            recipients.extend(admin_emails)

            if recipients:
                try:
                    send_mail(
                        subject=subject,
                        message=message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=list(set(recipients)),
                        fail_silently=True
                    )
                    logger.info(f"Sent fiscalization notification for invoice {invoice_id}")
                except Exception as mail_error:
                    logger.error(f"Failed to send email notification: {mail_error}")

    except Exception as e:
        logger.error(f"Error in send_fiscalization_notification for invoice {invoice_id}: {e}")

    finally:
        if initial_schema:
            try:
                connection.set_schema(initial_schema)
            except:
                pass

@shared_task
def send_document_notification(sale_id, notification_type, user_id=None, send_email=False):  # Added send_email param
    """
    Send notification for document (receipt/invoice/proforma)
    """
    initial_schema = TenantResolver.get_current_schema()

    try:
        sale, tenant_schema = TenantResolver.find_sale_schema(sale_id)

        if not sale or not tenant_schema:
            logger.error(f"Sale {sale_id} not found in any tenant schema for notification")
            return

        with schema_context(tenant_schema):
            sale = Sale.objects.select_related(
                'store__company', 'customer', 'created_by'
            ).get(id=sale_id)

            # Get user if provided
            user = None
            if user_id:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.get(pk=user_id)

            # Determine notification type
            subject = ''
            message = ''

            if notification_type == 'RECEIPT_CREATED':
                subject = f"Receipt {sale.document_number} Created"
                message = f"Receipt {sale.document_number} has been created for {sale.total_amount} {sale.currency}"
            elif notification_type == 'INVOICE_SENT':
                subject = f"Invoice {sale.document_number} Sent"
                message = f"Invoice {sale.document_number} has been sent to customer. Due date: {sale.due_date}"
            elif notification_type == 'PROFORMA_CREATED':
                subject = f"Quotation {sale.document_number} Created"
                message = f"Quotation {sale.document_number} has been created for {sale.total_amount} {sale.currency}"

            # Add customer info if available
            if sale.customer:
                message += f"\nCustomer: {sale.customer.name}"

            # CHANGED: Only send email if explicitly requested
            if send_email:
                # Get recipients
                recipients = []
                if sale.created_by and sale.created_by.email:
                    recipients.append(sale.created_by.email)

                if user and user.email:
                    recipients.append(user.email)

                # Send email if recipients exist
                if recipients:
                    send_mail(
                        subject=subject,
                        message=message,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=list(set(recipients)),
                        fail_silently=True
                    )
                    logger.info(f"Sent {notification_type} email for sale {sale.document_number}")

            # Always log (for debugging)
            logger.info(f"Processed {notification_type} notification for sale {sale.document_number}")

    except Exception as e:
        logger.error(f"Error sending document notification for sale {sale_id}: {e}")

    finally:
        if initial_schema and initial_schema != 'public':
            try:
                connection.set_schema(initial_schema)
            except:
                pass

@shared_task
def bulk_fiscalize_pending_invoices_all_tenants():
    """
    Task to fiscalize pending invoices across all tenants
    """
    initial_schema = TenantResolver.get_current_schema()
    tenant_schemas = TenantResolver.get_all_tenant_schemas()

    results = {
        'tenants_processed': 0,
        'total_invoices_queued': 0,
        'tenant_results': []
    }

    for schema_name in tenant_schemas:
        try:
            tenant_result = bulk_fiscalize_pending_invoices_for_tenant(schema_name)
            results['tenant_results'].append({
                'schema': schema_name,
                'result': tenant_result
            })
            results['tenants_processed'] += 1
            results['total_invoices_queued'] += tenant_result.get('processed', 0)

        except Exception as e:
            logger.error(f"Error processing bulk fiscalization for tenant {schema_name}: {e}")
            results['tenant_results'].append({
                'schema': schema_name,
                'error': str(e)
            })

    logger.info(f"Bulk fiscalization completed: {results}")

    # Restore original schema
    if initial_schema:
        try:
            connection.set_schema(initial_schema)
        except:
            pass

    return results


def bulk_fiscalize_pending_invoices_for_tenant(schema_name):
    """
    Helper function to fiscalize pending invoices for a specific tenant
    """
    try:
        with schema_context(schema_name):
            from django.db import models

            pending_invoices = Invoice.objects.filter(
                fiscalization_status='pending',
                is_fiscalized=False
            ).select_related(
                'store__company',
                'sale__store__company'
            ).filter(
                models.Q(store__company__efris_enabled=True) |
                models.Q(sale__store__company__efris_enabled=True)
            )[:50]

            results = {
                'processed': 0,
                'errors': [],
                'schema': schema_name
            }

            for invoice in pending_invoices:
                try:
                    # Skip if recently failed (wait 1 hour)
                    if (hasattr(invoice, 'fiscalization_error') and invoice.fiscalization_error and
                            hasattr(invoice, 'updated_at') and invoice.updated_at and
                            (timezone.now() - invoice.updated_at).seconds < 3600):
                        continue

                    fiscalize_invoice_async.delay(invoice.pk)
                    results['processed'] += 1

                except Exception as e:
                    results['errors'].append({
                        'invoice_id': invoice.pk,
                        'error': str(e)
                    })

            logger.info(f"Bulk fiscalization queued for schema {schema_name}: {results['processed']} invoices")
            return results

    except Exception as e:
        logger.error(f"Error in bulk fiscalization for schema {schema_name}: {e}")
        return {'error': str(e), 'schema': schema_name, 'processed': 0}


@shared_task
def periodic_bulk_fiscalization():
    """
    Periodic task to run bulk fiscalization across all tenants
    """
    return bulk_fiscalize_pending_invoices_all_tenants()


@shared_task
def periodic_document_reports():
    """
    Periodic task to generate document reports across all tenants
    """
    from datetime import timedelta
    from .services import SalesDocumentService

    initial_schema = TenantResolver.get_current_schema()
    tenant_schemas = TenantResolver.get_all_tenant_schemas()
    yesterday = timezone.now().date() - timedelta(days=1)

    results = {
        'tenants_processed': 0,
        'reports_generated': 0
    }

    for schema_name in tenant_schemas:
        try:
            with schema_context(schema_name):
                # Get all active stores in this tenant
                from stores.models import Store
                stores = Store.objects.filter(is_active=True)

                for store in stores:
                    # Generate daily document summary
                    summary = SalesDocumentService.get_document_summary(
                        store=store,
                        start_date=yesterday,
                        end_date=yesterday
                    )

                    # Log the summary
                    logger.info(f"Daily document summary for store {store.name} in {schema_name}: {summary}")

                    results['reports_generated'] += 1

                results['tenants_processed'] += 1

        except Exception as e:
            logger.error(f"Error generating document reports for schema {schema_name}: {e}")

    logger.info(f"Periodic document reports completed: {results}")

    # Restore original schema
    if initial_schema:
        try:
            connection.set_schema(initial_schema)
        except:
            pass

    return results

@shared_task
def periodic_efris_sync():
    """
    Periodic task to sync EFRIS status for recent invoices across all tenants
    """
    from datetime import timedelta

    initial_schema = TenantResolver.get_current_schema()
    tenant_schemas = TenantResolver.get_all_tenant_schemas()
    cutoff_date = timezone.now() - timedelta(hours=24)

    results = {
        'tenants_processed': 0,
        'total_invoices_synced': 0,
        'tenant_results': []
    }

    for schema_name in tenant_schemas:
        try:
            with schema_context(schema_name):
                recent_invoices = Invoice.objects.filter(
                    is_fiscalized=True,
                    fiscal_document_number__isnull=False,
                    fiscalization_time__gte=cutoff_date
                ).values_list('id', flat=True)[:50]

                synced_count = 0
                for invoice_id in recent_invoices:
                    sync_invoice_with_efris.delay(invoice_id)
                    synced_count += 1

                results['tenant_results'].append({
                    'schema': schema_name,
                    'invoices_synced': synced_count
                })
                results['total_invoices_synced'] += synced_count

                if synced_count > 0:
                    logger.info(f"Queued {synced_count} invoices for EFRIS sync in {schema_name}")

        except Exception as e:
            logger.error(f"Error syncing EFRIS status for {schema_name}: {e}")
            results['tenant_results'].append({
                'schema': schema_name,
                'error': str(e)
            })

        results['tenants_processed'] += 1

    logger.info(f"EFRIS sync completed: {results}")

    # Restore original schema
    if initial_schema:
        try:
            connection.set_schema(initial_schema)
        except:
            pass

    return results


@shared_task
def send_payment_reminders():
    """Celery task to send pending payment reminders"""
    from sales.payment_reminders import PaymentReminder
    return PaymentReminder.send_pending_reminders()
