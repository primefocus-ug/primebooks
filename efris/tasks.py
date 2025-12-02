from celery import shared_task, group
from django.utils import timezone
from django.apps import apps
from celery import shared_task, group, chord
from django.utils import timezone
from django.db import transaction
from django.core.cache import cache
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from .services import (
    EnhancedEFRISAPIClient,
    EFRISProductService,
    EFRISInvoiceService,
    EFRISCustomerService,
    EFRISHealthChecker
)
from .models import EFRISSyncQueue, EFRISAPILog, FiscalizationAudit

logger = logging.getLogger(__name__)

from celery import shared_task
from django_tenants.utils import schema_context
from .services import sync_commodity_categories


@shared_task(bind=True, max_retries=3)
def sync_categories_async(self, company_id, schema_name):
    """Async task to sync categories"""
    from company.models import Company

    try:
        with schema_context(schema_name):
            company = Company.objects.get(id=company_id)
            result = sync_commodity_categories(company)

            return {
                'success': result['success'],
                'total_fetched': result.get('total_fetched', 0),
                'error': result.get('error')
            }
    except Exception as e:
        logger.error(f"Category sync failed: {e}", exc_info=True)
        # Retry with exponential backoff
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))

# Helper functions for broadcasting and notifications
def broadcast_efris_event(company_id: int, event_type: str, data: dict):
    """Broadcast EFRIS events via WebSocket"""
    try:
        from .websocket_manager import websocket_manager
        from .websocket_manager import EFRISWebSocketEvent

        event = EFRISWebSocketEvent(
            event_type=event_type,
            data=data,
            company_id=company_id,
            event_category='task'
        )

        websocket_manager.broadcast_event(event)

    except Exception as e:
        logger.error(f"Failed to broadcast EFRIS event: {e}")


def create_efris_notification(company, title: str, message: str,
                              notification_type: str = 'info', priority: str = 'normal'):
    """Create EFRIS notification and broadcast it"""
    try:
        from .models import EFRISNotification
        from .websocket_manager import websocket_manager

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

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def fiscalize_invoice_async(self, invoice_id,user=None):
    """
    Celery task to fiscalize invoice with EFRIS
    """
    try:
        from invoices.models import Invoice

        invoice = Invoice.objects.get(id=invoice_id)
        company = invoice.company

        # Check if company has EFRIS enabled
        if not getattr(company, 'efris_enabled', False):
            logger.warning(f"EFRIS not enabled for company {company.name}")
            return {
                'success': False,
                'message': 'EFRIS not enabled for this company'
            }

        # Initialize EFRIS service
        service = EFRISInvoiceService(company)

        # Call fiscalize_invoice
        result = service.fiscalize_invoice(invoice)
        logger.debug(f"fiscalize_invoice result for invoice {invoice_id}: {result} (type: {type(result)})")

        # Check result
        if result.get('success'):
            logger.info(
                f"Invoice {invoice.number} fiscalized successfully: "
                f"{result.get('message')}"
            )

            # Update invoice status if needed
            if hasattr(invoice, 'is_fiscalized'):
                invoice.is_fiscalized = True
                invoice.fiscalization_time = timezone.now()
                invoice.save(update_fields=['is_fiscalized', 'fiscalization_time'])

        else:
            logger.error(
                f"Failed to fiscalize invoice {invoice.number}: "
                f"{result.get('message')}"
            )

        return result

    except Invoice.DoesNotExist:
        error_msg = f"Invoice {invoice_id} not found"
        logger.error(error_msg)
        return {'success': False, 'message': error_msg}

    except Exception as e:
        error_msg = f"EFRIS service error for invoice {invoice_id}: {str(e)}"
        logger.error(error_msg, exc_info=True)
        if self.request.retries < self.max_retries:
            raise self.retry(countdown=300, exc=e)
        return {'success': False, 'message': error_msg}


@shared_task(bind=True, max_retries=2)
def upload_products_async(self, company_id: int, product_ids: List[int]) -> Dict[str, Any]:
    """Upload products to EFRIS asynchronously"""
    try:
        Company = apps.get_model('company', 'Company')
        Product = apps.get_model('inventory', 'Product')

        company = Company.objects.get(pk=company_id)
        products = Product.objects.filter(pk__in=product_ids)

        if not products.exists():
            return {'success': False, 'error': 'No products found'}

        # Broadcast upload started
        broadcast_efris_event(company_id, 'product_upload_started', {
            'product_ids': product_ids,
            'product_count': products.count()
        })

        # Upload products
        service = EFRISProductService(company)
        success, message = service.upload_products(list(products))

        # Broadcast result
        broadcast_efris_event(company_id, 'product_upload_completed', {
            'product_ids': product_ids,
            'success': success,
            'message': message
        })

        # Create notification
        if success:
            create_efris_notification(
                company,
                'Products Uploaded Successfully',
                f'{products.count()} products have been uploaded to EFRIS.',
                'success'
            )
        else:
            create_efris_notification(
                company,
                'Product Upload Failed',
                f'Failed to upload products: {message}',
                'error'
            )

        return {
            'success': success,
            'message': message,
            'product_ids': product_ids,
            'uploaded_count': products.count() if success else 0
        }

    except Exception as e:
        logger.error(f"Product upload task failed: {e}")

        broadcast_efris_event(company_id, 'product_upload_error', {
            'product_ids': product_ids,
            'error': str(e)
        })

        if self.request.retries < self.max_retries:
            raise self.retry(countdown=120, exc=e)

        return {
            'success': False,
            'error': str(e),
            'product_ids': product_ids
        }


@shared_task
def validate_customer_tin_async(company_id: int, customer_id: int) -> Dict[str, Any]:
    """Validate customer TIN with EFRIS"""
    try:
        Company = apps.get_model('company', 'Company')
        Customer = apps.get_model('customers', 'Customer')

        company = Company.objects.get(pk=company_id)
        customer = Customer.objects.get(pk=customer_id)

        service = EFRISCustomerService(company)
        success, message_or_data = service.query_taxpayer(customer.tin)

        if success and isinstance(message_or_data, dict):
            # Update customer with EFRIS data
            customer._efris_tin_validated = True
            customer.save()

            broadcast_efris_event(company_id, 'customer_tin_validated', {
                'customer_id': customer_id,
                'customer_name': customer.name,
                'tin': customer.tin,
                'validation_success': True,
                'taxpayer_data': message_or_data
            })

            create_efris_notification(
                company,
                'Customer TIN Validated',
                f'TIN for {customer.name} has been validated successfully.',
                'success'
            )
        else:
            broadcast_efris_event(company_id, 'customer_tin_validation_failed', {
                'customer_id': customer_id,
                'customer_name': customer.name,
                'tin': customer.tin,
                'error': message_or_data if isinstance(message_or_data, str) else 'Unknown error'
            })

        return {
            'success': success,
            'customer_id': customer_id,
            'data': message_or_data
        }

    except Exception as e:
        logger.error(f"Customer TIN validation failed: {e}")
        return {
            'success': False,
            'error': str(e),
            'customer_id': customer_id
        }


@shared_task
def sync_stock_to_efris_async(company_id: int, stock_ids: List[int]) -> Dict[str, Any]:
    """Synchronize stock levels to EFRIS"""
    try:
        Company = apps.get_model('company', 'Company')
        Stock = apps.get_model('inventory', 'Stock')

        company = Company.objects.get(pk=company_id)
        stocks = Stock.objects.filter(pk__in=stock_ids).select_related('product', 'store')

        if not stocks.exists():
            return {'success': False, 'error': 'No stock records found'}

        # Build stock data for EFRIS
        stock_data = []
        for stock in stocks:
            if getattr(stock.product, 'efris_is_uploaded', False):
                stock_data.append({
                    'goodsCode': getattr(stock.product, 'efris_goods_code', stock.product.sku),
                    'goodsName': getattr(stock.product, 'efris_goods_name', stock.product.name),
                    'stockQuantity': str(stock.quantity),
                    'unitOfMeasure': getattr(stock.product, 'efris_unit_of_measure_code', 'U'),
                    'unitPrice': str(stock.product.selling_price),
                    'storeName': stock.store.name,
                    'operationType': '103'  # Stock update
                })

        if not stock_data:
            return {'success': True, 'message': 'No EFRIS-uploaded products in stock list', 'synced_count': 0}

        # Use T131 interface for stock maintenance
        with EnhancedEFRISAPIClient(company) as client:
            response = client._make_request('T131', {'stockDetails': stock_data})

            if response.success:
                # Update stock sync timestamps
                stocks.update(last_efris_sync=timezone.now())

                create_efris_notification(
                    company,
                    'Stock Synchronized',
                    f'Successfully synchronized {len(stock_data)} stock records to EFRIS.',
                    'success'
                )

                broadcast_efris_event(company_id, 'stock_sync_completed', {
                    'stock_ids': stock_ids,
                    'synced_count': len(stock_data),
                    'success': True
                })

                return {
                    'success': True,
                    'message': 'Stock synchronized successfully',
                    'synced_count': len(stock_data)
                }
            else:
                broadcast_efris_event(company_id, 'stock_sync_failed', {
                    'stock_ids': stock_ids,
                    'error': response.error_message
                })

                return {
                    'success': False,
                    'error': response.error_message,
                    'attempted_count': len(stock_data)
                }

    except Exception as e:
        logger.error(f"Stock sync task failed: {e}")
        return {
            'success': False,
            'error': str(e),
            'stock_ids': stock_ids
        }


@shared_task
def process_efris_queue_async() -> Dict[str, Any]:
    """Process EFRIS sync queue with real-time updates."""
    results = {
        'processed': 0,
        'successful': 0,
        'failed': 0,
        'details': []
    }

    # Get pending items (batch of 20, optimized queryset)
    pending_items = EFRISSyncQueue.objects.filter(
        status='pending',
        scheduled_at__lte=timezone.now()
    ).select_related('company').order_by('priority', 'scheduled_at')[:20]

    if not pending_items:
        logger.info("No pending EFRIS queue items to process.")
        return results

    for item in pending_items:
        with transaction.atomic():  # Ensure database consistency
            try:
                # Update status to processing
                item.status = 'processing'
                item.started_at = timezone.now()
                item.save()

                # Broadcast processing started
                broadcast_efris_event(
                    item.company.pk,
                    'queue_item_processing',
                    {
                        'queue_item_id': item.pk,
                        'sync_type': item.sync_type,
                        'object_id': item.object_id
                    }
                )

                success = False
                error_message = ""

                # Process based on sync type
                if item.sync_type == 'invoice_fiscalize':
                    try:
                        Invoice = apps.get_model('invoices', 'Invoice')
                        invoice = Invoice.objects.get(id=item.object_id)
                        service = EFRISInvoiceService(item.company)
                        result = service.fiscalize_invoice(invoice)
                        success = result.get('success', False)
                        error_message = result.get('message', 'Fiscalization failed')
                    except Invoice.DoesNotExist:
                        error_message = "Invoice not found"
                    except Exception as e:
                        error_message = f"Invoice fiscalization error: {str(e)}"
                        logger.exception(f"Invoice fiscalization failed for queue item {item.pk}: {e}")

                elif item.sync_type in ['product_upload', 'product_update']:
                    try:
                        Product = apps.get_model('inventory', 'Product')
                        product = Product.objects.get(id=item.object_id)
                        with EnhancedEFRISAPIClient(item.company) as client:
                            result = client.register_product_with_efris(product)
                            success = result.get('success', False)
                            error_message = result.get('error', 'Product registration failed')
                    except Product.DoesNotExist:
                        error_message = "Product not found"
                    except Exception as e:
                        error_message = f"Product sync error: {str(e)}"
                        logger.exception(f"Product sync failed for queue item {item.pk}: {e}")

                elif item.sync_type == 'customer_validate':
                    try:
                        Customer = apps.get_model('customers', 'Customer')
                        customer = Customer.objects.get(id=item.object_id)
                        service = EFRISCustomerService(item.company)
                        query_result = service.query_taxpayer(customer.tin)

                        if isinstance(query_result, tuple) and len(query_result) == 2:
                            result_success, result_data = query_result
                            success = result_success
                            error_message = result_data if not success and isinstance(result_data,
                                                                                      str) else 'Validation failed'
                        else:
                            error_message = f"Unexpected query_taxpayer return format: {type(query_result)}"
                    except Customer.DoesNotExist:
                        error_message = "Customer not found"
                    except Exception as e:
                        error_message = f"Customer validation error: {str(e)}"
                        logger.exception(f"Customer validation failed for queue item {item.pk}: {e}")

                elif item.sync_type == 'stock_sync':
                    try:
                        Stock = apps.get_model('inventory', 'Stock')
                        stock = Stock.objects.get(id=item.object_id)
                        result = sync_stock_to_efris_async(item.company.pk, [stock.pk])
                        success = result.get('success', False)
                        error_message = result.get('error', 'Stock sync failed') if not success else ""
                    except Stock.DoesNotExist:
                        error_message = "Stock record not found"
                    except Exception as e:
                        error_message = f"Stock sync error: {str(e)}"
                        logger.exception(f"Stock sync failed for queue item {item.pk}: {e}")

                # Update item status
                if success:
                    item.status = 'completed'
                    item.completed_at = timezone.now()
                    results['successful'] += 1
                else:
                    if item.retry_count < 3:  # Max 3 retries
                        item.status = 'retry'
                        item.retry_count += 1
                        item.next_retry_at = timezone.now() + timedelta(minutes=30 * (2 ** item.retry_count))
                    else:
                        item.status = 'failed'
                        item.completed_at = timezone.now()
                    item.error_message = error_message
                    results['failed'] += 1

                item.save()
                results['processed'] += 1

                # Broadcast completion
                broadcast_efris_event(
                    item.company.pk,
                    'queue_item_completed',
                    {
                        'queue_item_id': item.pk,
                        'sync_type': item.sync_type,
                        'object_id': item.object_id,
                        'success': success,
                        'message': error_message if not success else 'Completed successfully'
                    }
                )

                results['details'].append({
                    'id': item.pk,
                    'sync_type': item.sync_type,
                    'success': success,
                    'message': error_message if not success else 'Completed'
                })

            except Exception as e:
                logger.exception(f"Unexpected error processing queue item {item.pk}: {e}")
                item.status = 'failed'
                item.error_message = f"Unexpected error: {str(e)}"
                item.completed_at = timezone.now()
                item.save()
                results['failed'] += 1
                results['processed'] += 1
                results['details'].append({
                    'id': item.pk,
                    'sync_type': item.sync_type,
                    'success': False,
                    'message': f"Unexpected error: {str(e)}"
                })

    logger.info(f"EFRIS queue processing complete: {results}")
    return results


@shared_task
def sync_system_dictionaries_all_companies() -> List[Dict[str, Any]]:
    """Sync system dictionaries for all EFRIS-enabled companies"""
    Company = apps.get_model('company', 'Company')
    companies = Company.objects.filter(efris_enabled=True, is_active=True)

    results = []

    for company in companies:
        try:
            with EnhancedEFRISAPIClient(company) as client:
                response = client.get_system_dictionary()

                result = {
                    'company_id': company.pk,
                    'company_name': company.display_name,
                    'success': response.success,
                    'message': response.error_message if not response.success else 'Synchronized successfully'
                }

                # Broadcast sync completion
                broadcast_efris_event(company.pk, 'dictionary_sync_completed', {
                    'success': response.success,
                    'message': result['message']
                })

                # Create notification
                if response.success:
                    create_efris_notification(
                        company,
                        'System Dictionaries Synchronized',
                        'EFRIS system dictionaries have been updated successfully.',
                        'success'
                    )
                else:
                    create_efris_notification(
                        company,
                        'Dictionary Sync Failed',
                        f'Failed to sync system dictionaries: {result["message"]}',
                        'warning'
                    )

                results.append(result)

        except Exception as e:
            logger.error(f"Dictionary sync failed for company {company.pk}: {e}")
            results.append({
                'company_id': company.pk,
                'company_name': company.display_name,
                'success': False,
                'message': str(e)
            })

    return results


@shared_task
def run_efris_health_check_all_companies() -> List[Dict[str, Any]]:
    """Run health checks for all EFRIS-enabled companies"""
    Company = apps.get_model('company', 'Company')
    companies = Company.objects.filter(efris_enabled=True, is_active=True)

    results = []

    for company in companies:
        try:
            health_checker = EFRISHealthChecker(company)
            health_status = health_checker.check_system_health()

            result = {
                'company_id': company.pk,
                'company_name': company.display_name,
                'overall_status': health_status['overall_status'],
                'checks': health_status['checks'],
                'timestamp': health_status['timestamp']
            }

            # Broadcast health status
            broadcast_efris_event(company.pk, 'health_check_completed', {
                'overall_status': health_status['overall_status'],
                'checks': health_status['checks']
            })

            # Create notification for unhealthy systems
            if health_status['overall_status'] != 'healthy':
                failed_checks = [
                    check_name for check_name, check in health_status['checks'].items()
                    if not check.get('healthy', False)
                ]

                create_efris_notification(
                    company,
                    'EFRIS System Health Alert',
                    f'EFRIS system health check failed: {", ".join(failed_checks)}',
                    'warning',
                    'high'
                )

            results.append(result)

        except Exception as e:
            logger.error(f"Health check failed for company {company.pk}: {e}")
            results.append({
                'company_id': company.pk,
                'company_name': company.display_name,
                'overall_status': 'error',
                'error': str(e),
                'timestamp': timezone.now().isoformat()
            })

    return results


@shared_task
def cleanup_old_efris_logs(days_to_keep: int = 90) -> Dict[str, int]:
    """Clean up old EFRIS API logs and sync queue items"""
    from datetime import timedelta

    cutoff_date = timezone.now() - timedelta(days=days_to_keep)

    # Clean up API logs
    deleted_logs = EFRISAPILog.objects.filter(
        created_at__lt=cutoff_date
    ).delete()[0]

    # Clean up completed sync queue items
    deleted_queue_items = EFRISSyncQueue.objects.filter(
        status__in=['completed', 'failed'],
        completed_at__lt=cutoff_date
    ).delete()[0]

    # Clean up old audit records (keep longer - 6 months)
    audit_cutoff = timezone.now() - timedelta(days=180)
    deleted_audits = FiscalizationAudit.objects.filter(
        created_at__lt=audit_cutoff
    ).delete()[0]

    logger.info(
        f"EFRIS cleanup completed: {deleted_logs} logs, {deleted_queue_items} queue items, {deleted_audits} audits deleted")

    return {
        'deleted_logs': deleted_logs,
        'deleted_queue_items': deleted_queue_items,
        'deleted_audits': deleted_audits,
        'cutoff_date': cutoff_date.isoformat()
    }


@shared_task
def bulk_fiscalize_invoices_async(company_id: int, invoice_ids: List[int], user_id: int = None) -> Dict[str, Any]:
    """Bulk fiscalize multiple invoices asynchronously"""
    try:
        Company = apps.get_model('company', 'Company')
        Invoice = apps.get_model('invoices', 'Invoice')

        company = Company.objects.get(pk=company_id)
        invoices = Invoice.objects.filter(pk__in=invoice_ids)

        if not invoices.exists():
            return {'success': False, 'error': 'No invoices found'}

        # Broadcast bulk operation started
        broadcast_efris_event(company_id, 'bulk_fiscalization_started', {
            'invoice_ids': invoice_ids,
            'invoice_count': invoices.count()
        })

        # Use invoice service for bulk processing
        service = EFRISInvoiceService(company)
        User = apps.get_model('accounts', 'CustomUser') if user_id else None
        user = User.objects.get(pk=user_id) if user_id and User else None

        bulk_result = service.bulk_fiscalize_invoices(list(invoices), user)

        # Broadcast completion
        broadcast_efris_event(company_id, 'bulk_fiscalization_completed', {
            'invoice_ids': invoice_ids,
            'total_invoices': bulk_result['total_invoices'],
            'successful_count': bulk_result['successful_count'],
            'failed_count': bulk_result['failed_count'],
            'success': bulk_result['success']
        })

        # Create summary notification
        if bulk_result['success']:
            create_efris_notification(
                company,
                'Bulk Fiscalization Completed',
                f'Successfully fiscalized {bulk_result["successful_count"]} out of {bulk_result["total_invoices"]} invoices.',
                'success'
            )
        else:
            create_efris_notification(
                company,
                'Bulk Fiscalization Completed with Errors',
                f'Fiscalized {bulk_result["successful_count"]} out of {bulk_result["total_invoices"]} invoices. {bulk_result["failed_count"]} failed.',
                'warning',
                'high'
            )

        return bulk_result

    except Exception as e:
        logger.error(f"Bulk fiscalization task failed: {e}")

        broadcast_efris_event(company_id, 'bulk_fiscalization_error', {
            'invoice_ids': invoice_ids,
            'error': str(e)
        })

        return {
            'success': False,
            'error': str(e),
            'invoice_ids': invoice_ids
        }


@shared_task
def retry_failed_sync_items() -> Dict[str, Any]:
    """Retry failed sync queue items that are eligible for retry"""
    from datetime import timedelta

    # Get items that are ready for retry
    retry_items = EFRISSyncQueue.objects.filter(
        status='retry',
        next_retry_at__lte=timezone.now(),
        retry_count__lt=3
    ).select_related('company')[:10]  # Limit to 10 items per run

    results = {
        'processed': 0,
        'successful': 0,
        'failed': 0,
        'details': []
    }

    for item in retry_items:
        try:
            # Reset status for retry
            item.status = 'pending'
            item.scheduled_at = timezone.now()
            item.save()

            # Add back to queue processing
            queue_result = process_efris_queue_async()

            # Find our item in the results
            item_result = next((r for r in queue_result.get('details', []) if r.get('id') == item.id), None)

            if item_result:
                results['processed'] += 1
                if item_result.get('success'):
                    results['successful'] += 1
                else:
                    results['failed'] += 1

                results['details'].append({
                    'id': item.id,
                    'sync_type': item.sync_type,
                    'retry_attempt': item.retry_count,
                    'success': item_result.get('success', False),
                    'message': item_result.get('message', 'Retry processed')
                })

        except Exception as e:
            logger.error(f"Failed to retry sync item {item.id}: {e}")

            # Mark as failed after retry attempt
            item.status = 'failed'
            item.error_message = f"Retry failed: {str(e)}"
            item.completed_at = timezone.now()
            item.save()

            results['processed'] += 1
            results['failed'] += 1
            results['details'].append({
                'id': item.id,
                'sync_type': item.sync_type,
                'retry_attempt': item.retry_count,
                'success': False,
                'message': f"Retry failed: {str(e)}"
            })

    return results


# Periodic tasks setup
@shared_task
def efris_periodic_maintenance():
    """Run periodic maintenance tasks for EFRIS"""
    logger.info("Starting EFRIS periodic maintenance")

    # Run health checks
    health_results = run_efris_health_check_all_companies.delay()

    # Process pending queue items
    queue_results = process_efris_queue_async.delay()

    # Retry failed items
    retry_results = retry_failed_sync_items.delay()

    # Sync dictionaries (less frequent)
    if timezone.now().hour in [2, 14]:  # Run twice daily at 2 AM and 2 PM
        dict_results = sync_system_dictionaries_all_companies.delay()

    # Cleanup old logs (daily at 3 AM)
    if timezone.now().hour == 3:
        cleanup_results = cleanup_old_efris_logs.delay()

    logger.info("EFRIS periodic maintenance tasks scheduled")

    return {
        'timestamp': timezone.now().isoformat(),
        'tasks_scheduled': [
            'health_checks',
            'queue_processing',
            'retry_failed_items'
        ]
    }


# Task result processing
@shared_task
def process_efris_task_result(task_id: str, task_name: str, result: dict):
    """Process and store task results for monitoring"""
    try:
        # Log task completion
        logger.info(f"EFRIS task {task_name} completed", extra={
            'task_id': task_id,
            'task_name': task_name,
            'success': result.get('success', False),
            'result': result
        })

        # Store results in cache for dashboard
        from django.core.cache import cache

        cache_key = f"efris_task_result_{task_id}"
        cache.set(cache_key, {
            'task_name': task_name,
            'result': result,
            'completed_at': timezone.now().isoformat()
        }, timeout=3600)  # Keep for 1 hour

        return {'status': 'result_processed', 'task_id': task_id}

    except Exception as e:
        logger.error(f"Failed to process task result: {e}")
        return {'status': 'error', 'error': str(e)}


@shared_task
def process_efris_sync_queue():
    """
    Process EFRIS sync queue by triggering per-tenant tasks
    """
    from django_tenants.utils import get_tenant_model

    TenantModel = get_tenant_model()

    try:
        # Get all active tenants with EFRIS enabled
        active_tenants = TenantModel.objects.filter(
            is_active=True,
            efris_enabled=True
        )

        if not active_tenants.exists():
            logger.info("No active tenants with EFRIS enabled")
            return {
                'success': True,
                'message': 'No active EFRIS-enabled tenants',
                'tasks_triggered': 0
            }

        # Trigger async task for each tenant
        task_ids = []
        for tenant in active_tenants:
            task = process_efris_queue_for_tenant.delay(tenant.schema_name)
            task_ids.append(task.id)

        logger.info(f"Triggered EFRIS queue processing for {len(task_ids)} tenants")

        return {
            'success': True,
            'tasks_triggered': len(task_ids),
            'task_ids': task_ids,
            'tenants': [tenant.schema_name for tenant in active_tenants]
        }

    except Exception as e:
        logger.error(f"Error triggering tenant tasks: {e}")
        return {
            'success': False,
            'error': str(e),
            'tasks_triggered': 0
        }


@shared_task
def process_efris_queue_for_tenant(schema_name):
    """
    Process EFRIS queue for a specific tenant schema
    """
    from django_tenants.utils import tenant_context, get_tenant_model

    TenantModel = get_tenant_model()

    try:
        tenant = TenantModel.objects.get(schema_name=schema_name)

        with tenant_context(tenant):
            logger.info(f"Processing EFRIS queue for tenant: {schema_name}")
            return process_efris_queue_async()

    except TenantModel.DoesNotExist:
        logger.error(f"Tenant with schema {schema_name} not found")
        return {
            'success': False,
            'error': f'Tenant {schema_name} not found',
            'processed': 0
        }
    except Exception as e:
        logger.error(f"Error processing queue for tenant {schema_name}: {e}")
        return {
            'success': False,
            'error': str(e),
            'processed': 0
        }
#==== stock tasks ===========================================================================================================================================================================================================

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def sync_stock_to_efris_task(self, stock_id: int, operation_type: str = 'update'):
    """
    T131: Sync individual stock record to EFRIS

    Args:
        stock_id: Stock record ID
        operation_type: 'increase' or 'decrease' or 'update'

    Returns:
        Dict with sync result
    """
    from inventory.models import Stock
    from efris.services import EnhancedEFRISAPIClient
    from django_tenants.utils import schema_context

    try:
        stock = Stock.objects.select_related(
            'product', 'store', 'product__category', 'product__supplier'
        ).get(id=stock_id)

        company = stock.store.company

        # Skip if EFRIS not enabled
        if not company.efris_enabled:
            return {
                'success': True,
                'skipped': True,
                'reason': 'EFRIS not enabled'
            }

        # Skip if product not uploaded to EFRIS
        if not stock.product.efris_is_uploaded or not stock.product.efris_goods_id:
            return {
                'success': False,
                'error': 'Product not uploaded to EFRIS',
                'product_sku': stock.product.sku
            }

        with schema_context(company.schema_name):
            with EnhancedEFRISAPIClient(company) as client:
                # Build stock item data
                stock_item = {
                    "commodityGoodsId": stock.product.efris_goods_id,
                    "goodsCode": stock.product.efris_goods_code,
                    "measureUnit": client._map_unit_to_efris(stock.product.unit_of_measure),
                    "quantity": str(float(stock.quantity)),
                    "unitPrice": str(float(stock.product.cost_price)),
                    "remarks": f"Stock sync for {stock.store.name}"
                }

                # Determine operation
                if operation_type == 'increase':
                    result = client.t131_maintain_stock(
                        operation_type="101",  # Increase
                        stock_items=[stock_item],
                        stock_in_type="104",  # Opening Stock
                        supplier_name=stock.product.supplier.name if stock.product.supplier else stock.store.name,
                        supplier_tin=stock.product.supplier.tin if stock.product.supplier else None,
                        branch_id=getattr(stock.store, 'efris_branch_id', None)
                    )
                else:
                    # Default to updating current stock
                    result = client.t131_maintain_stock(
                        operation_type="101",  # Increase to current level
                        stock_items=[stock_item],
                        stock_in_type="104",  # Opening Stock
                        supplier_name=stock.store.name,
                        branch_id=getattr(stock.store, 'efris_branch_id', None)
                    )

                # Check result
                if isinstance(result, list) and len(result) > 0:
                    first_result = result[0]
                    if first_result.get('returnCode') == '00':
                        # Mark as synced
                        stock.mark_efris_synced()

                        logger.info(
                            f"✅ Stock synced to EFRIS: {stock.product.sku} at {stock.store.name}"
                        )

                        return {
                            'success': True,
                            'stock_id': stock_id,
                            'product_sku': stock.product.sku,
                            'store': stock.store.name,
                            'quantity': float(stock.quantity)
                        }
                    else:
                        error_msg = first_result.get('returnMessage', 'Unknown error')
                        logger.error(f"❌ EFRIS sync failed: {error_msg}")

                        return {
                            'success': False,
                            'error': error_msg,
                            'error_code': first_result.get('returnCode')
                        }
                else:
                    return {
                        'success': False,
                        'error': 'Invalid response from EFRIS'
                    }

    except Stock.DoesNotExist:
        logger.error(f"Stock {stock_id} not found")
        return {'success': False, 'error': 'Stock not found'}

    except Exception as e:
        logger.error(f"Stock sync failed: {e}", exc_info=True)

        # Retry on network errors
        if 'connection' in str(e).lower() or 'timeout' in str(e).lower():
            raise self.retry(exc=e)

        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def bulk_sync_stocks_to_efris(store_id: Optional[int] = None, product_ids: Optional[List[int]] = None):
    """
    Bulk sync multiple stock records to EFRIS

    Args:
        store_id: Optional store filter
        product_ids: Optional product IDs filter
    """
    from inventory.models import Stock

    try:
        # Build queryset
        stocks = Stock.objects.filter(
            efris_sync_required=True
        ).select_related('product', 'store')

        if store_id:
            stocks = stocks.filter(store_id=store_id)

        if product_ids:
            stocks = stocks.filter(product_id__in=product_ids)

        # Limit to avoid overwhelming EFRIS
        stocks = stocks[:100]

        if not stocks.exists():
            return {
                'success': True,
                'message': 'No stocks need syncing',
                'total': 0
            }

        # Create tasks for each stock
        tasks = group(
            sync_stock_to_efris_task.s(stock.id)
            for stock in stocks
        )

        # Execute in parallel
        result = tasks.apply_async()

        logger.info(f"Started bulk sync for {stocks.count()} stock records")

        return {
            'success': True,
            'total_queued': stocks.count(),
            'task_id': result.id
        }

    except Exception as e:
        logger.error(f"Bulk sync failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


@shared_task(bind=True, max_retries=2)
def process_stock_movement_to_efris(self, movement_id: int):
    """
    T131: Process stock movement and sync to EFRIS

    Args:
        movement_id: StockMovement ID
    """
    from inventory.models import StockMovement
    from efris.services import EnhancedEFRISAPIClient
    from django_tenants.utils import schema_context

    try:
        movement = StockMovement.objects.select_related(
            'product', 'store', 'product__supplier'
        ).get(id=movement_id)

        company = movement.store.company

        # Skip if EFRIS not enabled
        if not company.efris_enabled:
            return {'success': True, 'skipped': True}

        # Skip if product not in EFRIS
        if not movement.product.efris_goods_id:
            return {
                'success': False,
                'error': 'Product not in EFRIS',
                'product_sku': movement.product.sku
            }

        with schema_context(company.schema_name):
            with EnhancedEFRISAPIClient(company) as client:
                # Use the helper method from services
                result = client.t131_maintain_stock_from_movement(
                    movement=movement,
                    supplier_name=movement.product.supplier.name if movement.product.supplier else None,
                    supplier_tin=movement.product.supplier.tin if movement.product.supplier else None
                )

                if isinstance(result, list) and len(result) > 0:
                    first_result = result[0]

                    if first_result.get('returnCode') == '00':
                        logger.info(
                            f"✅ Movement synced to EFRIS: {movement.movement_type} "
                            f"for {movement.product.sku}"
                        )

                        return {
                            'success': True,
                            'movement_id': movement_id,
                            'movement_type': movement.movement_type,
                            'quantity': float(movement.quantity)
                        }
                    else:
                        error_msg = first_result.get('returnMessage', 'Unknown error')
                        logger.error(f"❌ Movement sync failed: {error_msg}")

                        return {
                            'success': False,
                            'error': error_msg,
                            'error_code': first_result.get('returnCode')
                        }

                return {'success': False, 'error': 'Invalid EFRIS response'}

    except StockMovement.DoesNotExist:
        return {'success': False, 'error': 'Movement not found'}

    except Exception as e:
        logger.error(f"Movement processing failed: {e}", exc_info=True)

        if 'connection' in str(e).lower():
            raise self.retry(exc=e)

        return {'success': False, 'error': str(e)}


@shared_task(bind=True, max_retries=2)
def process_stock_transfer_to_efris(self, movement_id: int, destination_branch_id: str):
    """
    T139: Process stock transfer between branches in EFRIS

    Args:
        movement_id: StockMovement ID (TRANSFER_OUT type)
        destination_branch_id: Destination store's EFRIS branch ID
    """
    from inventory.models import StockMovement
    from efris.services import EnhancedEFRISAPIClient
    from django_tenants.utils import schema_context

    try:
        movement = StockMovement.objects.select_related(
            'product', 'store'
        ).get(id=movement_id)

        if movement.movement_type != 'TRANSFER_OUT':
            return {
                'success': False,
                'error': 'Movement must be TRANSFER_OUT type'
            }

        company = movement.store.company

        with schema_context(company.schema_name):
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t139_transfer_stock_from_movement(
                    movement=movement,
                    destination_branch_id=destination_branch_id
                )

                if isinstance(result, list) and len(result) > 0:
                    first_result = result[0]

                    if first_result.get('returnCode') == '00':
                        logger.info(
                            f"✅ Transfer synced to EFRIS: {movement.product.sku} "
                            f"to branch {destination_branch_id}"
                        )

                        return {
                            'success': True,
                            'movement_id': movement_id,
                            'quantity': float(movement.quantity),
                            'destination_branch': destination_branch_id
                        }
                    else:
                        return {
                            'success': False,
                            'error': first_result.get('returnMessage', 'Unknown error'),
                            'error_code': first_result.get('returnCode')
                        }

                return {'success': False, 'error': 'Invalid EFRIS response'}

    except Exception as e:
        logger.error(f"Transfer processing failed: {e}", exc_info=True)

        if 'connection' in str(e).lower():
            raise self.retry(exc=e)

        return {'success': False, 'error': str(e)}


# ============================================================================
# STOCK ALERTS & MONITORING
# ============================================================================

@shared_task
def check_low_stock_levels():
    """
    Check all stores for low stock levels and send notifications
    """
    from inventory.models import Stock
    from django.contrib.auth import get_user_model

    User = get_user_model()

    try:
        # Get all low stock items
        low_stock_items = Stock.get_low_stock_items()

        if not low_stock_items.exists():
            return {
                'success': True,
                'message': 'No low stock items',
                'count': 0
            }

        # Group by store and company
        alerts = {}

        for stock in low_stock_items:
            company_id = stock.store.company_id
            store_name = stock.store.name

            key = f"{company_id}_{store_name}"

            if key not in alerts:
                alerts[key] = {
                    'company': stock.store.company,
                    'store': stock.store,
                    'items': []
                }

            alerts[key]['items'].append({
                'product': stock.product.name,
                'sku': stock.product.sku,
                'current_stock': float(stock.quantity),
                'threshold': float(stock.low_stock_threshold),
                'stock_percentage': stock.stock_percentage
            })

        # Send notifications
        notifications_sent = 0

        for key, alert_data in alerts.items():
            # Get store managers/admins
            users = User.objects.filter(
                company=alert_data['company'],
                is_active=True,
                # Add role filter as needed
            )

            for user in users:
                # Send notification (implement your notification system)
                send_low_stock_notification.delay(
                    user_id=user.id,
                    store_id=alert_data['store'].id,
                    items=alert_data['items']
                )
                notifications_sent += 1

        logger.info(
            f"Low stock check complete: {len(alerts)} stores, "
            f"{notifications_sent} notifications sent"
        )

        return {
            'success': True,
            'stores_with_alerts': len(alerts),
            'total_low_stock_items': low_stock_items.count(),
            'notifications_sent': notifications_sent
        }

    except Exception as e:
        logger.error(f"Low stock check failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def send_low_stock_notification(user_id: int, store_id: int, items: List[Dict]):
    """
    Send low stock notification to user

    Args:
        user_id: User ID
        store_id: Store ID
        items: List of low stock items
    """
    from django.contrib.auth import get_user_model
    from stores.models import Store
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    User = get_user_model()

    try:
        user = User.objects.get(id=user_id)
        store = Store.objects.get(id=store_id)

        # Send WebSocket notification
        channel_layer = get_channel_layer()

        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"user_{user_id}",
                {
                    'type': 'stock_alert',
                    'message': {
                        'type': 'low_stock',
                        'store': store.name,
                        'store_id': store_id,
                        'items': items,
                        'count': len(items),
                        'timestamp': timezone.now().isoformat()
                    }
                }
            )

        # You can also send email/SMS here

        logger.info(f"Low stock notification sent to user {user_id}")

        return {'success': True}

    except Exception as e:
        logger.error(f"Notification failed: {e}")
        return {'success': False, 'error': str(e)}


@shared_task
def generate_stock_reorder_suggestions():
    """
    Generate reorder suggestions for items below reorder quantity
    """
    from inventory.models import Stock

    try:
        reorder_items = Stock.get_reorder_items()

        suggestions = []

        for stock in reorder_items:
            # Calculate suggested order quantity
            avg_daily_usage = calculate_average_daily_usage(stock)
            lead_time_days = getattr(stock.product.supplier, 'lead_time_days', 7) if stock.product.supplier else 7
            safety_stock = float(stock.low_stock_threshold)

            suggested_quantity = (avg_daily_usage * lead_time_days) + safety_stock

            suggestions.append({
                'product_id': stock.product.id,
                'product_name': stock.product.name,
                'sku': stock.product.sku,
                'store_id': stock.store.id,
                'store_name': stock.store.name,
                'current_stock': float(stock.quantity),
                'reorder_level': float(stock.reorder_quantity),
                'suggested_order_qty': suggested_quantity,
                'supplier': stock.product.supplier.name if stock.product.supplier else None,
                'estimated_cost': float(stock.product.cost_price) * suggested_quantity
            })

        # Cache suggestions for 24 hours
        cache.set('stock_reorder_suggestions', suggestions, 86400)

        logger.info(f"Generated {len(suggestions)} reorder suggestions")

        return {
            'success': True,
            'suggestions_count': len(suggestions),
            'suggestions': suggestions
        }

    except Exception as e:
        logger.error(f"Reorder suggestions failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


def calculate_average_daily_usage(stock) -> float:
    """Calculate average daily usage for a stock item"""
    from inventory.models import StockMovement
    from datetime import timedelta

    # Get movements for last 30 days
    thirty_days_ago = timezone.now() - timedelta(days=30)

    outbound_movements = StockMovement.objects.filter(
        product=stock.product,
        store=stock.store,
        movement_type__in=['SALE', 'TRANSFER_OUT'],
        created_at__gte=thirty_days_ago
    )

    total_outbound = sum(abs(float(m.quantity)) for m in outbound_movements)

    return total_outbound / 30.0 if total_outbound > 0 else 1.0


# ============================================================================
# EFRIS STOCK QUERY TASKS
# ============================================================================

@shared_task
def query_efris_stock_for_product(product_id: int):
    """
    T128: Query EFRIS stock for a product

    Args:
        product_id: Product ID
    """
    from inventory.models import Product
    from efris.services import EnhancedEFRISAPIClient
    from django_tenants.utils import schema_context

    try:
        product = Product.objects.select_related('category').get(id=product_id)

        if not product.efris_goods_id:
            return {
                'success': False,
                'error': 'Product not in EFRIS'
            }

        company = product.category.company if hasattr(product.category, 'company') else None

        if not company or not company.efris_enabled:
            return {'success': False, 'error': 'EFRIS not enabled'}

        with schema_context(company.schema_name):
            with EnhancedEFRISAPIClient(company) as client:
                result = client.t128_query_stock_by_goods_id(
                    efris_goods_id=product.efris_goods_id
                )

                if result:
                    logger.info(f"✅ EFRIS stock queried for {product.sku}")

                    return {
                        'success': True,
                        'product_id': product_id,
                        'sku': product.sku,
                        'efris_data': result
                    }
                else:
                    return {
                        'success': False,
                        'error': 'No data returned from EFRIS'
                    }

    except Product.DoesNotExist:
        return {'success': False, 'error': 'Product not found'}

    except Exception as e:
        logger.error(f"EFRIS stock query failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


# ============================================================================
# PERIODIC TASKS (Configure in settings)
# ============================================================================

@shared_task
def hourly_stock_sync():
    """
    Hourly task to sync pending stocks to EFRIS
    """
    from inventory.models import Stock

    try:
        # Get stocks that need syncing
        pending_stocks = Stock.objects.filter(
            efris_sync_required=True,
            product__efris_is_uploaded=True
        ).select_related('store__company')

        # Group by company
        companies = set(stock.store.company for stock in pending_stocks)

        results = {}

        for company in companies:
            if not company.efris_enabled:
                continue

            company_stocks = [s for s in pending_stocks if s.store.company == company]

            # Queue sync tasks
            result = bulk_sync_stocks_to_efris.delay(
                store_id=None,
                product_ids=[s.product_id for s in company_stocks]
            )

            results[company.name] = {
                'queued': len(company_stocks),
                'task_id': result.id
            }

        return {
            'success': True,
            'companies_processed': len(results),
            'results': results
        }

    except Exception as e:
        logger.error(f"Hourly sync failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def daily_stock_reconciliation():
    """
    Daily task to reconcile stock levels
    """
    from inventory.models import Stock

    try:
        # Get all active stocks
        stocks = Stock.objects.select_related('product', 'store')

        reconciliation_report = {
            'total_stocks': stocks.count(),
            'discrepancies': [],
            'low_stock_count': 0,
            'negative_stock_count': 0
        }

        for stock in stocks:
            # Check for negative stock
            if stock.quantity < 0:
                reconciliation_report['negative_stock_count'] += 1
                reconciliation_report['discrepancies'].append({
                    'product': stock.product.sku,
                    'store': stock.store.name,
                    'quantity': float(stock.quantity),
                    'issue': 'negative_stock'
                })

            # Check for low stock
            if stock.is_low_stock:
                reconciliation_report['low_stock_count'] += 1

        # Cache report
        cache.set('daily_stock_reconciliation', reconciliation_report, 86400)

        logger.info(
            f"Daily reconciliation complete: {reconciliation_report['total_stocks']} stocks checked"
        )

        return {
            'success': True,
            'report': reconciliation_report
        }

    except Exception as e:
        logger.error(f"Daily reconciliation failed: {e}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }