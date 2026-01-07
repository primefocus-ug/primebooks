import os
import tempfile
import time
from typing import Dict, Any, List, Optional
from decimal import Decimal
from datetime import timedelta

from celery import shared_task, current_task, Task, group
from celery.exceptions import Retry, WorkerLostError
from celery.utils.log import get_task_logger
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.core.cache import cache
from django.conf import settings
from django.db.models import Sum, Count, F, Avg, Q, Max, Min
from celery import shared_task
from django.utils import timezone
from django_tenants.utils import schema_context, tenant_context
from django.contrib.auth import get_user_model
import logging
from efris.services import EnhancedEFRISAPIClient

from .models import ImportSession, Product, Stock, StockMovement, ImportLog, ImportResult
from .import_processors import AdvancedImportManager
from .signals import send_to_websocket, send_dashboard_update

logger = get_task_logger(__name__)


User = get_user_model()


def _is_efris_configured(company) -> bool:

    try:
        # Check if company has EFRIS config
        if not hasattr(company, 'efris_config'):
            return False

        # Check if EFRIS is enabled and configured
        efris_config = company.efris_config
        return (
                efris_config.is_active and
                efris_config.is_configured

        )
    except Exception as e:
        logger.warning(f"Error checking EFRIS configuration for company {company.name}: {str(e)}")
        return False


import logging
from celery import shared_task
from django.db import connection
from django_tenants.utils import schema_context, get_tenant_model

logger = logging.getLogger(__name__)


def get_company_efris_status(company):
    """
    Check company-level EFRIS configuration status.
    Only checks if EFRIS is enabled - rest is handled elsewhere.

    Args:
        company: Company instance

    Returns:
        dict: {
            'enabled': bool,
            'can_sync': bool,
            'errors': list
        }
    """
    status = {
        'enabled': False,
        'can_sync': False,
        'errors': []
    }

    try:
        # Check if EFRIS is enabled at company level
        if not company.efris_enabled:
            status['errors'].append('EFRIS is not enabled for this company')
            return status

        status['enabled'] = True
        status['can_sync'] = True

        return status

    except Exception as e:
        logger.error(f"Error checking company EFRIS status: {e}")
        status['errors'].append(f"Error checking EFRIS status: {str(e)}")
        return status


@shared_task(bind=True, max_retries=3)
def sync_service_to_efris_task(self, schema_name, service_id, user_id=None):
    """
    Celery task to sync a single service to EFRIS.
    Uses company-level EFRIS configuration.

    Args:
        schema_name: Tenant schema name
        service_id: Service ID to sync
        user_id: User ID who triggered the sync (optional)

    Returns:
        dict: Result of the sync operation
    """
    try:
        # Get company
        Company = get_tenant_model()
        company = Company.objects.get(schema_name=schema_name)

        # Check company-level EFRIS status
        efris_status = get_company_efris_status(company)

        if not efris_status['can_sync']:
            error_msg = f"EFRIS not enabled for company {company.name}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg,
                'errors': efris_status['errors'],
                'service_id': service_id,
                'company_name': company.name,
            }

        # Switch to tenant schema
        with schema_context(schema_name):
            from inventory.models import Service
            from efris.services import EFRISServiceManager
            from django.contrib.auth import get_user_model

            User = get_user_model()

            # Get service
            try:
                service = Service.objects.get(id=service_id)
            except Service.DoesNotExist:
                error_msg = f"Service with ID {service_id} not found"
                logger.error(error_msg)
                return {
                    'success': False,
                    'error': error_msg,
                    'service_id': service_id,
                }

            # Check if service is ready for EFRIS
            if not service.efris_configuration_complete:
                errors = service.get_efris_errors()
                error_msg = f"Service '{service.name}' not ready for EFRIS sync"
                logger.warning(f"{error_msg}: {errors}")
                return {
                    'success': False,
                    'error': error_msg,
                    'errors': errors,
                    'service_id': service_id,
                    'service_name': service.name,
                }

            # Check if EFRIS auto-sync is enabled
            if not service.efris_auto_sync_enabled:
                error_msg = f"EFRIS auto-sync disabled for service '{service.name}'"
                logger.warning(error_msg)
                return {
                    'success': False,
                    'error': error_msg,
                    'service_id': service_id,
                    'service_name': service.name,
                }

            # Get user if provided
            user = None
            if user_id:
                try:
                    user = User.objects.get(id=user_id)
                except User.DoesNotExist:
                    logger.warning(f"User with ID {user_id} not found")

            # Initialize EFRIS Service Manager with company
            manager = EFRISServiceManager(company)

            # Register service with EFRIS
            logger.info(
                f"Starting EFRIS sync for service '{service.name}' (ID: {service_id}) "
                f"in company '{company.name}'"
            )

            result = manager.register_service(service, user=user)

            if result.get('success'):
                logger.info(
                    f"Successfully synced service '{service.name}' to EFRIS. "
                    f"EFRIS Service ID: {result.get('efris_service_id')}"
                )
                return {
                    'success': True,
                    'message': result.get('message', 'Service synced successfully'),
                    'efris_service_id': result.get('efris_service_id'),
                    'service_id': service_id,
                    'service_name': service.name,
                    'service_code': service.code,
                    'company_name': company.name,
                }
            else:
                error_msg = result.get('error', 'Unknown error during sync')
                logger.error(
                    f"Failed to sync service '{service.name}' to EFRIS: {error_msg}"
                )

                # Retry on certain errors
                if 'network' in error_msg.lower() or 'timeout' in error_msg.lower():
                    raise self.retry(countdown=60 * (self.request.retries + 1))

                return {
                    'success': False,
                    'error': error_msg,
                    'details': result.get('details', {}),
                    'service_id': service_id,
                    'service_name': service.name,
                    'company_name': company.name,
                }

    except Exception as e:
        logger.error(
            f"Error in sync_service_to_efris_task for service {service_id}: {str(e)}",
            exc_info=True
        )

        # Retry on unexpected errors
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))

        return {
            'success': False,
            'error': f'Task failed after {self.max_retries} retries: {str(e)}',
            'service_id': service_id,
        }


@shared_task(bind=True)
def bulk_sync_services_to_efris_task(self, schema_name, service_ids, user_id=None):
    """
    Celery task to bulk sync multiple services to EFRIS.
    Uses company-level EFRIS configuration.

    Args:
        schema_name: Tenant schema name
        service_ids: List of service IDs to sync
        user_id: User ID who triggered the sync (optional)

    Returns:
        dict: Summary of sync results
    """
    try:
        # Get company
        Company = get_tenant_model()
        company = Company.objects.get(schema_name=schema_name)

        # Check company-level EFRIS status
        efris_status = get_company_efris_status(company)

        if not efris_status['can_sync']:
            error_msg = f"EFRIS not enabled for company {company.name}"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg,
                'errors': efris_status['errors'],
                'company_name': company.name,
                'total': len(service_ids),
                'successful': 0,
                'failed': len(service_ids),
            }

        results = {
            'total': len(service_ids),
            'successful': 0,
            'failed': 0,
            'skipped': 0,
            'results': [],
            'company_name': company.name,
        }

        # Switch to tenant schema
        with schema_context(schema_name):
            from inventory.models import Service
            from efris.services import EFRISServiceManager
            from django.contrib.auth import get_user_model

            User = get_user_model()

            # Get user if provided
            user = None
            if user_id:
                try:
                    user = User.objects.get(id=user_id)
                except User.DoesNotExist:
                    logger.warning(f"User with ID {user_id} not found")

            # Initialize EFRIS Service Manager
            manager = EFRISServiceManager(company)

            # Get all services
            services = Service.objects.filter(id__in=service_ids)

            logger.info(
                f"Starting bulk EFRIS sync for {services.count()} services "
                f"in company '{company.name}'"
            )

            # Process each service
            for service in services:
                service_result = {
                    'service_id': service.id,
                    'service_name': service.name,
                    'service_code': service.code,
                }

                try:
                    # Check if service is ready
                    if not service.efris_configuration_complete:
                        results['skipped'] += 1
                        service_result.update({
                            'status': 'skipped',
                            'reason': 'Configuration incomplete',
                            'errors': service.get_efris_errors()
                        })
                        results['results'].append(service_result)
                        continue

                    # Check if auto-sync is enabled
                    if not service.efris_auto_sync_enabled:
                        results['skipped'] += 1
                        service_result.update({
                            'status': 'skipped',
                            'reason': 'EFRIS auto-sync disabled'
                        })
                        results['results'].append(service_result)
                        continue

                    # Sync service
                    sync_result = manager.register_service(service, user=user)

                    if sync_result.get('success'):
                        results['successful'] += 1
                        service_result.update({
                            'status': 'success',
                            'efris_service_id': sync_result.get('efris_service_id'),
                            'message': sync_result.get('message', 'Synced successfully')
                        })
                        logger.info(
                            f"Successfully synced service '{service.name}' "
                            f"(EFRIS ID: {sync_result.get('efris_service_id')})"
                        )
                    else:
                        results['failed'] += 1
                        service_result.update({
                            'status': 'failed',
                            'error': sync_result.get('error', 'Unknown error'),
                            'details': sync_result.get('details', {})
                        })
                        logger.error(
                            f"Failed to sync service '{service.name}': "
                            f"{sync_result.get('error')}"
                        )

                    results['results'].append(service_result)

                except Exception as e:
                    results['failed'] += 1
                    service_result.update({
                        'status': 'failed',
                        'error': str(e)
                    })
                    results['results'].append(service_result)
                    logger.error(
                        f"Error syncing service '{service.name}': {str(e)}",
                        exc_info=True
                    )

            # Log summary
            logger.info(
                f"Bulk EFRIS sync completed for company '{company.name}': "
                f"{results['successful']} successful, {results['failed']} failed, "
                f"{results['skipped']} skipped out of {results['total']} total"
            )

            results['success'] = results['failed'] == 0
            return results

    except Exception as e:
        logger.error(
            f"Error in bulk_sync_services_to_efris_task: {str(e)}",
            exc_info=True
        )
        return {
            'success': False,
            'error': str(e),
            'total': len(service_ids) if service_ids else 0,
            'successful': 0,
            'failed': len(service_ids) if service_ids else 0,
            'skipped': 0,
        }


@shared_task
def auto_sync_pending_services_task(schema_name):
    """
    Background task to automatically sync all pending services to EFRIS.
    Can be scheduled to run periodically.

    Args:
        schema_name: Tenant schema name

    Returns:
        dict: Summary of sync results
    """
    try:
        # Get company
        Company = get_tenant_model()
        company = Company.objects.get(schema_name=schema_name)

        # Check company-level EFRIS status
        efris_status = get_company_efris_status(company)

        if not efris_status['can_sync']:
            logger.info(
                f"Auto-sync skipped for company '{company.name}': EFRIS not enabled"
            )
            return {
                'success': False,
                'error': 'EFRIS not enabled',
                'company_name': company.name,
            }

        # Switch to tenant schema
        with schema_context(schema_name):
            from inventory.models import Service

            # Get services pending upload
            pending_services = Service.objects.filter(
                is_active=True,
                efris_auto_sync_enabled=True,
                efris_is_uploaded=False,
                efris_configuration_complete=True
            )

            if not pending_services.exists():
                logger.info(
                    f"No pending services to sync for company '{company.name}'"
                )
                return {
                    'success': True,
                    'message': 'No pending services',
                    'company_name': company.name,
                    'total': 0,
                }

            logger.info(
                f"Auto-syncing {pending_services.count()} pending services "
                f"for company '{company.name}'"
            )

            # Use bulk sync task
            service_ids = list(pending_services.values_list('id', flat=True))
            result = bulk_sync_services_to_efris_task(schema_name, service_ids)

            return result

    except Exception as e:
        logger.error(f"Error in auto_sync_pending_services_task: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
        }

@shared_task
def refresh_service_from_efris_task(schema_name, service_id):
    """
    Refresh service data from EFRIS

    Args:
        schema_name: Tenant schema name
        service_id: Service ID to refresh
    """
    try:
        from company.models import Company
        from inventory.models import Service
        from efris.services import EnhancedEFRISAPIClient

        logger.info(f"Refreshing service {service_id} from EFRIS")

        company = Company.objects.get(schema_name=schema_name)

        with schema_context(schema_name):
            service = Service.objects.get(id=service_id)

            with EnhancedEFRISAPIClient(company) as client:
                result = client.refresh_service_from_efris(service)

            if result.get('success'):
                logger.info(f"Successfully refreshed service {service.name} from EFRIS")
                return {
                    'success': True,
                    'service_id': service.id,
                    'service_name': service.name,
                    'updates': result.get('updates', {})
                }
            else:
                logger.error(f"Failed to refresh service {service.name}: {result.get('error')}")
                return {
                    'success': False,
                    'service_id': service.id,
                    'error': result.get('error')
                }

    except Exception as e:
        logger.error(f"Refresh service task failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'service_id': service_id,
            'error': str(e)
        }


@shared_task
def validate_services_efris_compliance(schema_name):
    try:
        from company.models import Company
        from inventory.models import Service
        from efris.services import EFRISServiceManager

        logger.info(f"Validating services EFRIS compliance for {schema_name}")

        company = Company.objects.get(schema_name=schema_name)

        with schema_context(schema_name):
            services = Service.objects.filter(
                is_active=True,
                efris_auto_sync_enabled=True
            ).select_related('category')

            manager = EFRISServiceManager(company)

            report = {
                'total': services.count(),
                'compliant': 0,
                'non_compliant': 0,
                'issues': []
            }

            for service in services:
                is_valid, errors = manager.validate_service_for_efris(service)

                if is_valid:
                    report['compliant'] += 1
                else:
                    report['non_compliant'] += 1
                    report['issues'].append({
                        'service_id': service.id,
                        'service_name': service.name,
                        'service_code': service.code,
                        'errors': errors
                    })

            logger.info(
                f"Compliance validation completed: {report['compliant']}/{report['total']} "
                f"services compliant"
            )

            return report

    except Exception as e:
        logger.error(f"Compliance validation failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e)
        }



@shared_task(bind=True, max_retries=5)  # Increased retries for SALE movements
def sync_stock_movement_to_efris(self, movement_id: int, schema_name: str):
    """
    Sync stock movement to EFRIS T131.
    For SALE movements, ensures the sale is fiscalized first.
    """
    try:
        with schema_context(schema_name):
            from inventory.models import StockMovement
            from company.models import Company

            company = Company.objects.filter(schema_name=schema_name).first()
            if not company:
                logger.error(f"[{schema_name}] ❌ Company not found for schema")
                return None

            # Check if EFRIS is configured
            if not _is_efris_configured(company):
                logger.info(f"[{schema_name}] ⏭️ EFRIS not configured, skipping sync for movement {movement_id}")
                return {
                    'movement_id': movement_id,
                    'schema': schema_name,
                    'skipped': True,
                    'reason': 'EFRIS not configured'
                }

            movement = StockMovement.objects.select_related('product', 'store').get(pk=movement_id)

            # Check if already synced
            if movement.synced_to_efris:
                logger.info(f"[{schema_name}] ✅ Movement {movement_id} already synced")
                return {
                    'movement_id': movement_id,
                    'schema': schema_name,
                    'already_synced': True
                }

            # ✅ CRITICAL: For SALE movements, verify the sale is fiscalized
            if movement.movement_type == 'SALE' and movement.reference:
                from sales.models import Sale

                # Extract sale number from reference
                sale_number = movement.reference.replace('Sale #', '').strip()

                sale = Sale.objects.filter(
                    document_number=sale_number,
                    store=movement.store
                ).first()

                if not sale:
                    logger.warning(f"[{schema_name}] ⚠️ Sale {sale_number} not found for movement {movement_id}")
                    return {
                        'movement_id': movement_id,
                        'schema': schema_name,
                        'error': 'Sale not found',
                        'skipped': True
                    }

                if not sale.is_fiscalized:
                    logger.info(
                        f"[{schema_name}] ⏸️ Sale {sale_number} not yet fiscalized - "
                        f"deferring movement {movement_id} sync (attempt {self.request.retries + 1})"
                    )
                    # Retry later with exponential backoff
                    countdown = 30 * (2 ** self.request.retries)
                    raise self.retry(
                        countdown=countdown,
                        max_retries=10,  # More retries for waiting for fiscalization
                        exc=Exception(f"Sale {sale_number} not yet fiscalized")
                    )

                # Use the EFRIS invoice number from the sale
                fiscal_invoice_number = sale.efris_invoice_number
                if not fiscal_invoice_number:
                    logger.error(f"[{schema_name}] ❌ Sale {sale_number} fiscalized but no EFRIS invoice number")
                    raise Exception("Missing EFRIS invoice number")
            else:
                # For non-SALE movements, use the reference as invoice number
                fiscal_invoice_number = movement.reference

            # Initialize EFRIS client
            client = EnhancedEFRISAPIClient(company=company)

            # Authenticate and sync
            client.ensure_authenticated()

            # Pass the fiscal invoice number to the T131 sync
            result = client.t131_maintain_stock_from_movement(
                movement,
                invoice_number=fiscal_invoice_number
            )

            if result.get('success'):
                # Mark as synced
                movement.synced_to_efris = True
                movement.efris_synced_at = timezone.now()
                movement.efris_sync_attempted = True
                movement.efris_sync_error = ''
                movement.save(update_fields=[
                    'synced_to_efris', 'efris_synced_at',
                    'efris_sync_attempted', 'efris_sync_error'
                ])

                logger.info(f"[{schema_name}] ✅ EFRIS sync completed for movement {movement_id}")
                return {
                    'movement_id': movement_id,
                    'schema': schema_name,
                    'success': True,
                    'result': result
                }
            else:
                raise Exception(result.get('message', 'Sync failed'))

    except StockMovement.DoesNotExist:
        logger.error(f"[{schema_name}] ❌ StockMovement {movement_id} does not exist")
        return None

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[{schema_name}] 🔥 Error syncing StockMovement {movement_id}: {error_msg}", exc_info=True)

        # Mark as attempted with error
        try:
            with schema_context(schema_name):
                movement = StockMovement.objects.get(pk=movement_id)
                movement.efris_sync_attempted = True
                movement.efris_sync_error = error_msg[:500]  # Truncate if too long
                movement.save(update_fields=['efris_sync_attempted', 'efris_sync_error'])
        except:
            pass

        # Don't retry for configuration errors
        if any(x in error_msg.lower() for x in ['no efris_config', 'not configured', 'not found']):
            logger.info(f"[{schema_name}] ⏭️ Configuration error, not retrying: {error_msg}")
            return {
                'movement_id': movement_id,
                'schema': schema_name,
                'error': error_msg,
                'skipped': True
            }

        # Retry for "Invoice number does not exist" errors (sale might not be fiscalized yet)
        if 'invoice number does not exist' in error_msg.lower() or '2810' in error_msg:
            if self.request.retries < 10:  # More retries for this specific case
                countdown = 30 * (2 ** self.request.retries)
                logger.info(
                    f"[{schema_name}] 🔄 Retrying movement {movement_id} in {countdown}s (attempt {self.request.retries + 1})")
                raise self.retry(exc=e, countdown=countdown, max_retries=10)

        # Retry for other errors
        if self.request.retries < self.max_retries:
            countdown = 30 * (2 ** self.request.retries)
            logger.info(f"[{schema_name}] 🔄 Retrying movement {movement_id} in {countdown}s")
            raise self.retry(exc=e, countdown=countdown, max_retries=self.max_retries)

        return {
            'movement_id': movement_id,
            'schema': schema_name,
            'error': error_msg,
            'failed': True
        }


def _is_efris_configured(company):
    """Check if EFRIS is configured for the company"""
    try:
        return (
                hasattr(company, 'efris_config') and
                company.efris_config is not None and
                company.efris_config.enabled
        )
    except Exception:
        return False

class CallbackTask(Task):
    """Base task class with callback support"""

    def on_success(self, retval, task_id, args, kwargs):
        logger.info(f"Task {task_id} completed successfully")

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        logger.error(f"Task {task_id} failed: {exc}")

    def on_retry(self, exc, task_id, args, kwargs, einfo):
        logger.warning(f"Task {task_id} retrying: {exc}")


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def register_product_with_efris_async(
    self,
    product_id: int,
    company_id: int,
    schema_name: str
) -> Dict[str, Any]:
    """Asynchronously register a single product with EFRIS"""
    try:
        with schema_context(schema_name):
            from company.models import Company
            from efris.services import EnhancedEFRISAPIClient
            from efris.models import EFRISAPILog, FiscalizationAudit

            try:
                company = Company.objects.get(pk=company_id)
                product = Product.objects.get(pk=product_id)
            except (Company.DoesNotExist, Product.DoesNotExist) as e:
                logger.error(f"[{schema_name}] Record not found: {e}")
                return {
                    'success': False,
                    'product_id': product_id,
                    'error': str(e),
                    'schema_name': schema_name
                }

            # Check if EFRIS is configured
            if not _is_efris_configured(company):
                return {
                    'success': False,
                    'product_id': product_id,
                    'skipped': True,
                    'error': 'EFRIS not configured for this company',
                    'schema_name': schema_name
                }

            logger.info(
                f"[{schema_name}] Starting EFRIS registration for product {product.sku}"
            )

            if product.efris_is_uploaded:
                return {
                    'success': True,
                    'skipped': True,
                    'message': 'Product already registered',
                    'product_id': product_id,
                    'sku': product.sku,
                    'schema_name': schema_name
                }

            client = EnhancedEFRISAPIClient(company)
            result = client.register_product_with_efris(product)

            if result.get('success'):
                logger.info(
                    f"[{schema_name}] Successfully registered product {product.sku}"
                )

                _log_product_registration(company, product, True, result, schema_name)

                return {
                    'success': True,
                    'product_id': product_id,
                    'sku': product.sku,
                    'efris_goods_id': result.get('efris_goods_id'),
                    'efris_goods_code': result.get('efris_goods_code'),
                    'message': 'Product registered successfully',
                    'schema_name': schema_name
                }
            else:
                error_message = result.get('error', 'Unknown error')
                error_code = result.get('error_code')

                logger.error(
                    f"[{schema_name}] Failed to register product {product.sku}: "
                    f"{error_message}"
                )

                _log_product_registration(company, product, False, result, schema_name)

                # Don't retry configuration errors
                if "no efris_config" in error_message.lower() or "not configured" in error_message.lower():
                    return {
                        'success': False,
                        'product_id': product_id,
                        'sku': product.sku,
                        'error': error_message,
                        'error_code': error_code,
                        'skipped': True,
                        'schema_name': schema_name
                    }

                retryable_codes = ['99', 'TIMEOUT', 'CONNECTION_ERROR', '45']
                if error_code in retryable_codes and self.request.retries < self.max_retries:
                    raise self.retry(countdown=60 * (self.request.retries + 1))

                return {
                    'success': False,
                    'product_id': product_id,
                    'sku': product.sku,
                    'error': error_message,
                    'error_code': error_code,
                    'schema_name': schema_name
                }

    except Exception as e:
        logger.error(
            f"[{schema_name}] Unexpected error: {str(e)}",
            exc_info=True
        )

        # Don't retry configuration errors
        if "no efris_config" in str(e).lower() or "not configured" in str(e).lower():
            return {
                'success': False,
                'product_id': product_id,
                'error': str(e),
                'skipped': True,
                'schema_name': schema_name
            }

        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (self.request.retries + 1))

        return {
            'success': False,
            'product_id': product_id,
            'error': str(e),
            'schema_name': schema_name
        }


@shared_task(bind=True)
def bulk_register_products_with_efris_async(
    self,
    product_ids: List[int],
    company_id: int,
    schema_name: str,
    batch_size: int = 10
) -> Dict[str, Any]:
    """Bulk register multiple products with EFRIS"""
    logger.info(
        f"[{schema_name}] Starting bulk EFRIS registration for {len(product_ids)} products"
    )

    start_time = time.time()
    results = {
        'total': len(product_ids),
        'successful': 0,
        'failed': 0,
        'skipped': 0,
        'errors': [],
        'registered_products': [],
        'schema_name': schema_name
    }

    try:
        for i in range(0, len(product_ids), batch_size):
            batch = product_ids[i:i + batch_size]

            logger.info(
                f"[{schema_name}] Processing batch {i // batch_size + 1}"
            )

            job = group(
                register_product_with_efris_async.s(
                    product_id, company_id, schema_name
                )
                for product_id in batch
            )

            batch_results = job.apply_async()
            batch_results.get(timeout=300)

            for result in batch_results:
                if result.get('success'):
                    if result.get('skipped'):
                        results['skipped'] += 1
                    else:
                        results['successful'] += 1
                        results['registered_products'].append({
                            'product_id': result['product_id'],
                            'sku': result['sku'],
                            'efris_goods_id': result.get('efris_goods_id')
                        })
                else:
                    results['failed'] += 1
                    results['errors'].append({
                        'product_id': result.get('product_id'),
                        'sku': result.get('sku'),
                        'error': result.get('error')
                    })

            if i + batch_size < len(product_ids):
                time.sleep(2)

        duration = time.time() - start_time
        success_rate = (results['successful'] / results['total'] * 100) if results['total'] > 0 else 0

        logger.info(
            f"[{schema_name}] Bulk registration completed in {duration:.2f}s: "
            f"{results['successful']}/{results['total']} ({success_rate:.1f}%)"
        )

        return {
            'success': True,
            'duration_seconds': duration,
            'summary': results
        }

    except Exception as e:
        logger.error(f"[{schema_name}] Bulk registration failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'summary': results
        }


@shared_task
def register_new_products_with_efris(company_id: int, schema_name: str) -> Dict[str, Any]:
    """Scheduled task to register all new products"""
    try:
        with schema_context(schema_name):
            from company.models import Company

            company = Company.objects.get(pk=company_id)

            # Check if EFRIS is configured
            if not _is_efris_configured(company):
                return {
                    'success': False,
                    'message': 'EFRIS not configured for this company',
                    'schema_name': schema_name,
                    'skipped': True
                }

            if not company.efris_enabled:
                return {
                    'success': False,
                    'message': 'EFRIS not enabled',
                    'schema_name': schema_name,
                    'skipped': True
                }

            products = Product.objects.filter(
                is_active=True,
                efris_is_uploaded=False,
                efris_auto_sync_enabled=True
            ).values_list('id', flat=True)

            product_count = len(products)

            if product_count == 0:
                return {
                    'success': True,
                    'message': 'No products to register',
                    'total': 0,
                    'schema_name': schema_name
                }

            result = bulk_register_products_with_efris_async.delay(
                list(products),
                company_id,
                schema_name
            )

            return {
                'success': True,
                'message': f'Bulk registration started for {product_count} products',
                'task_id': result.id,
                'total': product_count,
                'schema_name': schema_name
            }

    except Exception as e:
        logger.error(f"[{schema_name}] Scheduled registration failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'schema_name': schema_name
        }


@shared_task(
    bind=True,
    base=CallbackTask,
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(ConnectionError, IOError, WorkerLostError),
)
def process_file_import(
    self,
    session_id: int,
    file_content: bytes,
    filename: str,
    schema_name: str
) -> Dict[str, Any]:
    """Asynchronously process file import with tenant context"""
    session = None
    temp_file_path = None

    try:
        with schema_context(schema_name):
            if not file_content:
                raise ValueError("File content is empty")

            if not filename:
                raise ValueError("Filename is required")

            try:
                session = ImportSession.objects.select_for_update().get(id=session_id)
            except ImportSession.DoesNotExist:
                logger.error(f"[{schema_name}] Import session {session_id} not found")
                return {'success': False, 'error': 'Import session not found'}

            if session.status == 'processing':
                return {'success': False, 'error': 'Import already in progress'}

            session.status = 'processing'
            session.started_at = timezone.now()
            session.save(update_fields=['status', 'started_at'])

            ImportLog.objects.create(
                session=session,
                level='info',
                message=f'Starting import process for file: {filename}',
                details={'file_size': len(file_content), 'task_id': self.request.id}
            )

            progress_data = {
                'id': session_id,
                'status': 'processing',
                'message': 'Starting import process...',
                'progress_percentage': 0,
                'schema_name': schema_name
            }

            send_to_websocket(f'import_{session_id}', 'import_progress_update', progress_data)

            file_extension = filename.split('.')[-1].lower() if '.' in filename else 'tmp'
            if file_extension not in ['csv', 'xlsx', 'xls']:
                raise ValueError(f"Unsupported file format: {file_extension}")

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=f'.{file_extension}',
                dir=getattr(settings, 'IMPORT_TEMP_DIR', None)
            ) as temp_file:
                temp_file.write(file_content)
                temp_file.flush()
                temp_file_path = temp_file.name

                self.update_state(
                    state='PROGRESS',
                    meta={'current': 10, 'total': 100, 'status': 'Processing file...'}
                )

                try:
                    import_manager = AdvancedImportManager(session, session.user)

                    def progress_callback(current: int, total: int, message: str):
                        percentage = int((current / total) * 80) + 10

                        self.update_state(
                            state='PROGRESS',
                            meta={
                                'current': current,
                                'total': total,
                                'status': message,
                                'percentage': percentage
                            }
                        )

                        progress_data = {
                            'id': session_id,
                            'status': 'processing',
                            'message': message,
                            'progress_percentage': percentage,
                            'processed_rows': current,
                            'total_rows': total,
                            'schema_name': schema_name
                        }
                        send_to_websocket(f'import_{session_id}', 'import_progress_update', progress_data)

                    with open(temp_file_path, 'rb') as file:
                        result = import_manager.process_import(file, progress_callback)

                    self.update_state(
                        state='PROGRESS',
                        meta={'current': 95, 'total': 100, 'status': 'Finalizing import...'}
                    )

                    session.refresh_from_db()

                    completion_data = {
                        'id': session_id,
                        'status': session.status,
                        'message': 'Import completed successfully!' if session.status == 'completed' else 'Import completed with errors',
                        'progress_percentage': 100,
                        'summary': {
                            'processed_rows': session.processed_rows,
                            'created_count': session.created_count,
                            'updated_count': session.updated_count,
                            'skipped_count': session.skipped_count,
                            'error_count': session.error_count,
                            'success_rate': session.success_rate,
                            'duration': str(session.duration) if session.duration else None
                        },
                        'result': result,
                        'schema_name': schema_name
                    }

                    send_to_websocket(f'import_{session_id}', 'import_completed', completion_data)
                    send_dashboard_update()

                    ImportLog.objects.create(
                        session=session,
                        level='success',
                        message='Import process completed successfully',
                        details=completion_data['summary']
                    )

                    return {
                        'success': True,
                        'session_id': session_id,
                        'result': result,
                        'summary': completion_data['summary'],
                        'schema_name': schema_name
                    }

                except Exception as processing_error:
                    logger.error(f"[{schema_name}] Import processing failed: {processing_error}", exc_info=True)

                    session.status = 'failed'
                    session.error_message = str(processing_error)
                    session.completed_at = timezone.now()
                    session.save(update_fields=['status', 'error_message', 'completed_at'])

                    ImportLog.objects.create(
                        session=session,
                        level='error',
                        message=f'Import processing failed: {str(processing_error)}',
                        details={'error_type': type(processing_error).__name__}
                    )

                    raise processing_error

    except Exception as exc:
        logger.error(f"[{schema_name}] Import task failed: {exc}", exc_info=True)

        if session:
            try:
                with schema_context(schema_name):
                    session.status = 'failed'
                    session.error_message = str(exc)
                    session.completed_at = timezone.now()
                    session.save(update_fields=['status', 'error_message', 'completed_at'])

                    ImportLog.objects.create(
                        session=session,
                        level='error',
                        message=f'Import task failed: {str(exc)}',
                        details={'error_type': type(exc).__name__}
                    )
            except Exception as save_error:
                logger.error(f"Failed to update session status: {save_error}")

        error_data = {
            'id': session_id,
            'status': 'failed',
            'error': str(exc),
            'message': f'Import failed: {str(exc)}',
            'schema_name': schema_name
        }
        send_to_websocket(f'import_{session_id}', 'import_error', error_data)

        if self.request.retries < self.max_retries and isinstance(exc, (ConnectionError, IOError)):
            raise self.retry(countdown=60, exc=exc)

        return {
            'success': False,
            'error': str(exc),
            'schema_name': schema_name
        }

    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as cleanup_error:
                logger.warning(f"Failed to clean up temp file: {cleanup_error}")

@shared_task(bind=True, base=CallbackTask)
def bulk_stock_adjustment(
    self,
    user_id: int,
    adjustments_data: List[Dict[str, Any]],
    schema_name: str,
    batch_reference: Optional[str] = None
) -> Dict[str, Any]:
    """Perform bulk stock adjustments with tenant context"""

    try:
        with schema_context(schema_name):
            from django.contrib.auth import get_user_model
            from stores.models import Store

            User = get_user_model()

            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return {'success': False, 'error': 'User not found'}

            if not adjustments_data:
                return {'success': False, 'error': 'No adjustments provided'}

            total_adjustments = len(adjustments_data)
            success_count = 0
            error_count = 0
            errors = []
            successful_adjustments = []

            batch_ref = batch_reference or f'BULK-{timezone.now().strftime("%Y%m%d%H%M%S")}'

            with transaction.atomic():
                for i, adj_data in enumerate(adjustments_data):
                    try:
                        # Update progress state every 10 items
                        if i % 10 == 0:
                            self.update_state(
                                state='PROGRESS',
                                meta={
                                    'current': i + 1,
                                    'total': total_adjustments,
                                    'status': f'Processing adjustment {i + 1} of {total_adjustments}'
                                }
                            )

                        # Validate required fields
                        required_fields = ['product_id', 'store_id', 'adjustment_type', 'quantity']
                        missing_fields = [f for f in required_fields if f not in adj_data]
                        if missing_fields:
                            raise ValueError(f"Missing required fields: {', '.join(missing_fields)}")

                        product_id = int(adj_data['product_id'])
                        store_id = int(adj_data['store_id'])
                        adjustment_type = adj_data['adjustment_type']
                        quantity = Decimal(str(adj_data['quantity']))
                        reason = adj_data.get('reason', 'Bulk adjustment')
                        notes = adj_data.get('notes', '')

                        if adjustment_type not in ['add', 'remove', 'set']:
                            raise ValueError(f"Invalid adjustment type: {adjustment_type}")

                        if quantity < 0:
                            raise ValueError("Quantity cannot be negative")

                        # Get product and store
                        try:
                            product = Product.objects.select_for_update().get(
                                id=product_id, is_active=True
                            )
                        except Product.DoesNotExist:
                            raise ValueError(f"Product with ID {product_id} not found or inactive")

                        try:
                            store = Store.objects.get(id=store_id, is_active=True)
                        except Store.DoesNotExist:
                            raise ValueError(f"Store with ID {store_id} not found or inactive")

                        # Get or create stock
                        stock, created = Stock.objects.get_or_create(
                            product=product,
                            store=store,
                            defaults={'quantity': Decimal('0')}
                        )

                        old_quantity = stock.quantity

                        # Determine new quantity and movement
                        if adjustment_type == 'add':
                            new_quantity = old_quantity + quantity
                            movement_quantity = quantity
                        elif adjustment_type == 'remove':
                            new_quantity = max(Decimal('0'), old_quantity - quantity)
                            movement_quantity = -(min(quantity, old_quantity))
                        elif adjustment_type == 'set':
                            new_quantity = quantity
                            movement_quantity = new_quantity - old_quantity
                        else:
                            raise ValueError(f"Invalid adjustment type: {adjustment_type}")

                        # Create stock movement
                        movement = StockMovement.objects.create(
                            product=product,
                            store=store,
                            movement_type='ADJUSTMENT',
                            quantity=movement_quantity,
                            reference=batch_ref,
                            notes=f'{reason}. {notes}'.strip(),
                            created_by=user
                        )

                        # Update stock quantity
                        stock.quantity = new_quantity
                        stock.save(update_fields=['quantity'])

                        # Prepare adjustment result
                        adjustment_result = {
                            'id': f"{product_id}_{store_id}",
                            'product_id': product_id,
                            'product_name': product.name,
                            'store_id': store_id,
                            'store_name': store.name,
                            'old_quantity': float(old_quantity),
                            'new_quantity': float(new_quantity),
                            'adjustment_quantity': float(movement_quantity),
                            'adjustment_type': adjustment_type,
                            'movement_id': movement.id,
                        }
                        successful_adjustments.append(adjustment_result)

                        # Notify via WebSocket
                        if abs(movement_quantity) > 0:
                            stock_update = {
                                'type': 'bulk_adjustment',
                                'stock_id': stock.id,
                                'product_name': product.name,
                                'store_name': store.name,
                                'old_quantity': float(old_quantity),
                                'new_quantity': float(new_quantity),
                                'adjustment_type': adjustment_type,
                                'user': user.get_full_name() or user.username,
                                'schema_name': schema_name,
                            }
                            send_to_websocket('inventory_dashboard', 'stock_update', stock_update)

                        success_count += 1

                    except (ValueError, TypeError, IntegrityError) as e:
                        error_count += 1
                        error_msg = f"Row {i + 1}: {str(e)}"
                        errors.append(error_msg)
                        logger.warning(f"[{schema_name}] Bulk adjustment error: {error_msg}")

                    except Exception as e:
                        error_count += 1
                        error_msg = f"Row {i + 1}: Unexpected error - {str(e)}"
                        errors.append(error_msg)
                        logger.error(f"[{schema_name}] Unexpected bulk adjustment error: {error_msg}", exc_info=True)

            # Compile result data
            result_data = {
                'success': success_count > 0,
                'batch_reference': batch_ref,
                'total_processed': total_adjustments,
                'success_count': success_count,
                'error_count': error_count,
                'success_rate': round((success_count / total_adjustments) * 100, 2)
                if total_adjustments > 0 else 0,
                'errors': errors[:20],
                'successful_adjustments': successful_adjustments[:10],
                'message': f'Bulk adjustment completed. Success: {success_count}, Errors: {error_count}',
                'schema_name': schema_name,
            }

            # Notify dashboard
            send_to_websocket('inventory_dashboard', 'bulk_operation_completed', result_data)
            if success_count > 0:
                send_dashboard_update()

            logger.info(
                f"[{schema_name}] Bulk stock adjustment completed. Success: {success_count}, Errors: {error_count}"
            )
            return result_data

    except Exception as e:
        logger.error(f"[{schema_name}] Bulk stock adjustment task failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'error_type': type(e).__name__,
            'schema_name': schema_name,
        }



@shared_task(base=CallbackTask)
def generate_low_stock_alerts(schema_name: str, threshold_multiplier: float = 1.0) -> Dict[str, Any]:
    """Generate and send low stock alerts with tenant context"""
    try:
        with schema_context(schema_name):
            critical_stocks = Stock.objects.select_related(
                'product', 'product__category', 'store'
            ).filter(
                Q(quantity=0) | Q(quantity__lte=F('low_stock_threshold') * threshold_multiplier)
            ).order_by('quantity', 'product__name')[:50]

            alerts = []
            critical_count = 0
            warning_count = 0

            for stock in critical_stocks:
                severity = 'critical' if stock.quantity == 0 or stock.quantity <= (
                        stock.low_stock_threshold / 2) else 'warning'

                if severity == 'critical':
                    critical_count += 1
                else:
                    warning_count += 1

                alert_data = {
                    'id': stock.id,
                    'product_id': stock.product.id,
                    'product_name': stock.product.name,
                    'product_sku': stock.product.sku,
                    'category': stock.product.category.name if stock.product.category else 'Uncategorized',
                    'store_id': stock.store.id,
                    'store_name': stock.store.name,
                    'current_stock': float(stock.quantity),
                    'threshold': float(stock.low_stock_threshold),
                    'reorder_quantity': float(stock.reorder_quantity),
                    'unit_of_measure': stock.product.unit_of_measure,
                    'severity': severity,
                    'stock_percentage': round((stock.quantity / max(stock.low_stock_threshold, 1)) * 100, 1),
                    'cost_per_unit': float(stock.product.cost_price),
                    'total_value_at_risk': float(stock.quantity * stock.product.cost_price),
                    'last_updated': stock.last_updated.isoformat() if stock.last_updated else None
                }
                alerts.append(alert_data)

            cache_key = f'{schema_name}_inventory_low_stock_alerts'
            cache.set(cache_key, alerts, timeout=300)

            alert_summary = {
                'total_alerts': len(alerts),
                'critical_count': critical_count,
                'warning_count': warning_count,
                'timestamp': timezone.now().isoformat(),
                'alerts': alerts,
                'schema_name': schema_name
            }

            if alerts:
                send_to_websocket('inventory_dashboard', 'low_stock_alert', alert_summary)
                logger.info(
                    f"[{schema_name}] Generated {len(alerts)} low stock alerts "
                    f"(Critical: {critical_count}, Warning: {warning_count})"
                )

            return {
                'success': True,
                'alert_count': len(alerts),
                'critical_count': critical_count,
                'warning_count': warning_count,
                'schema_name': schema_name
            }

    except Exception as e:
        logger.error(f"[{schema_name}] Low stock alert generation failed: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e), 'schema_name': schema_name}


@shared_task(base=CallbackTask)
def cleanup_old_import_sessions(schema_name: str, retention_days: int = 30) -> Dict[str, Any]:
    """Clean up old import sessions with tenant context"""
    try:
        with schema_context(schema_name):
            cutoff_date = timezone.now() - timedelta(days=retention_days)

            old_sessions = ImportSession.objects.filter(
                created_at__lt=cutoff_date
            ).prefetch_related('logs', 'results')

            deleted_sessions = 0
            deleted_logs = 0
            deleted_results = 0

            with transaction.atomic():
                for session in old_sessions:
                    log_count = session.logs.count()
                    result_count = session.results.count()

                    session.logs.all().delete()
                    session.results.all().delete()
                    session.delete()

                    deleted_sessions += 1
                    deleted_logs += log_count
                    deleted_results += result_count

            logger.info(
                f"[{schema_name}] Cleaned up {deleted_sessions} import sessions, "
                f"{deleted_logs} logs, and {deleted_results} results older than {retention_days} days"
            )

            return {
                'success': True,
                'deleted_sessions': deleted_sessions,
                'deleted_logs': deleted_logs,
                'deleted_results': deleted_results,
                'retention_days': retention_days,
                'schema_name': schema_name
            }

    except Exception as e:
        logger.error(f"[{schema_name}] Import session cleanup failed: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e), 'schema_name': schema_name}


@shared_task(base=CallbackTask)
def sync_efris_products(schema_name: str, batch_size: int = 50, dry_run: bool = False) -> Dict[str, Any]:
    """Synchronize products with EFRIS system"""
    try:
        with schema_context(schema_name):
            products_to_sync = Product.objects.filter(
                efris_auto_sync_enabled=True,
                efris_is_uploaded=False,
                is_active=True
            ).select_related('category', 'supplier')[:batch_size]

            if not products_to_sync:
                return {
                    'success': True,
                    'message': 'No products need EFRIS sync',
                    'synced_count': 0,
                    'error_count': 0,
                    'schema_name': schema_name
                }

            synced_count = 0
            error_count = 0
            errors = []

            for i, product in enumerate(products_to_sync):
                try:
                    if i % 10 == 0:
                        current_task.update_state(
                            state='PROGRESS',
                            meta={
                                'current': i + 1,
                                'total': len(products_to_sync),
                                'status': f'Syncing {product.name}'
                            }
                        )

                    efris_errors = product.get_efris_errors()
                    if efris_errors:
                        error_msg = f"Product {product.name} has EFRIS configuration errors: {', '.join(efris_errors)}"
                        errors.append(error_msg)
                        logger.warning(f"[{schema_name}] {error_msg}")
                        error_count += 1
                        continue

                    efris_data = product.get_efris_data()

                    if dry_run:
                        required_fields = ['goodsCode', 'goodsName', 'taxCategoryId', 'unitPrice']
                        missing_fields = [field for field in required_fields if not efris_data.get(field)]

                        if missing_fields:
                            error_msg = f"Product {product.name} missing EFRIS fields: {', '.join(missing_fields)}"
                            errors.append(error_msg)
                            error_count += 1
                        else:
                            synced_count += 1
                    else:
                        # Schedule actual EFRIS registration
                        from company.models import Company
                        company = Company.objects.get(schema_name=schema_name)

                        register_product_with_efris_async.delay(
                            product.id,
                            company.company_id,
                            schema_name
                        )
                        synced_count += 1

                except Exception as e:
                    error_count += 1
                    error_msg = f"EFRIS sync error for product {product.name}: {str(e)}"
                    errors.append(error_msg)
                    logger.error(f"[{schema_name}] {error_msg}", exc_info=True)

            result = {
                'success': synced_count > 0 or error_count == 0,
                'synced_count': synced_count,
                'error_count': error_count,
                'errors': errors[:10],
                'dry_run': dry_run,
                'processed_count': len(products_to_sync),
                'message': f"EFRIS sync completed. Synced: {synced_count}, Errors: {error_count}",
                'schema_name': schema_name
            }

            logger.info(f"[{schema_name}] {result['message']}")
            return result

    except Exception as e:
        logger.error(f"[{schema_name}] EFRIS sync task failed: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e), 'schema_name': schema_name}


@shared_task(base=CallbackTask)
def generate_inventory_reports(schema_name: str, include_trends: bool = True) -> Dict[str, Any]:
    """Generate comprehensive inventory reports with tenant context"""
    try:
        with schema_context(schema_name):
            report_timestamp = timezone.now()

            product_stats = Product.objects.aggregate(
                total_products=Count('id'),
                active_products=Count('id', filter=Q(is_active=True)),
                inactive_products=Count('id', filter=Q(is_active=False))
            )

            stock_stats = Stock.objects.aggregate(
                total_stock_items=Count('id'),
                low_stock_count=Count('id', filter=Q(quantity__lte=F('low_stock_threshold'))),
                out_of_stock_count=Count('id', filter=Q(quantity=0)),
                critical_count=Count('id', filter=Q(quantity__lte=F('low_stock_threshold') / 2)),
                total_stock_value=Sum(F('quantity') * F('product__cost_price')),
                total_selling_value=Sum(F('quantity') * F('product__selling_price')),
                avg_stock_level=Avg('quantity'),
                max_stock_level=Max('quantity'),
                min_stock_level=Min('quantity')
            )

            today = timezone.now().date()
            week_ago = today - timedelta(days=7)
            month_ago = today - timedelta(days=30)

            movement_stats = {
                'today': StockMovement.objects.filter(created_at__date=today).count(),
                'this_week': StockMovement.objects.filter(created_at__date__gte=week_ago).count(),
                'this_month': StockMovement.objects.filter(created_at__date__gte=month_ago).count(),
            }

            movement_breakdown = list(
                StockMovement.objects.filter(
                    created_at__date__gte=month_ago
                ).values('movement_type').annotate(
                    count=Count('id'),
                    total_quantity=Sum('quantity')
                ).order_by('-count')
            )

            category_stats = list(
                Stock.objects.select_related('product__category').values(
                    'product__category__name'
                ).annotate(
                    category_name=F('product__category__name'),
                    product_count=Count('product', distinct=True),
                    total_stock_value=Sum(F('quantity') * F('product__cost_price')),
                    avg_stock_level=Avg('quantity'),
                    low_stock_items=Count('id', filter=Q(quantity__lte=F('low_stock_threshold')))
                ).filter(category_name__isnull=False).order_by('-total_stock_value')
            )

            store_stats = list(
                Stock.objects.select_related('store').values(
                    'store__name'
                ).annotate(
                    store_name=F('store__name'),
                    product_count=Count('product', distinct=True),
                    total_stock_value=Sum(F('quantity') * F('product__cost_price')),
                    avg_stock_level=Avg('quantity'),
                    low_stock_items=Count('id', filter=Q(quantity__lte=F('low_stock_threshold')))
                ).order_by('-total_stock_value')
            )

            stats = {
                'products': product_stats,
                'inventory': {
                    **stock_stats,
                    'total_stock_value': float(stock_stats['total_stock_value'] or 0),
                    'total_selling_value': float(stock_stats['total_selling_value'] or 0),
                    'potential_profit': float(
                        (stock_stats['total_selling_value'] or 0) - (stock_stats['total_stock_value'] or 0)
                    ),
                    'avg_stock_level': float(stock_stats['avg_stock_level'] or 0),
                    'stock_turnover_indicator': movement_stats['this_month'] / max(
                        stock_stats['total_stock_items'] or 1, 1)
                },
                'movements': {
                    **movement_stats,
                    'breakdown': movement_breakdown
                },
                'analysis': {
                    'categories': category_stats,
                    'stores': store_stats,
                    'low_stock_percentage': round(
                        (stock_stats['low_stock_count'] or 0) / max(stock_stats['total_stock_items'] or 1, 1) * 100, 2
                    ),
                    'critical_percentage': round(
                        (stock_stats['critical_count'] or 0) / max(stock_stats['total_stock_items'] or 1, 1) * 100, 2
                    )
                },
                'generated_at': report_timestamp.isoformat(),
                'schema_name': schema_name
            }

            if include_trends:
                trends = generate_trend_analysis(schema_name)
                stats['trends'] = trends

            cache.set(f'{schema_name}_inventory_dashboard_stats', stats, timeout=300)
            cache.set(f'{schema_name}_inventory_category_stats', category_stats, timeout=600)
            cache.set(f'{schema_name}_inventory_store_stats', store_stats, timeout=600)

            logger.info(
                f"[{schema_name}] Generated comprehensive inventory reports with "
                f"{len(category_stats)} categories and {len(store_stats)} stores"
            )

            return {
                'success': True,
                'stats': stats,
                'report_timestamp': report_timestamp.isoformat(),
                'categories_analyzed': len(category_stats),
                'stores_analyzed': len(store_stats),
                'schema_name': schema_name
            }

    except Exception as e:
        logger.error(f"[{schema_name}] Report generation failed: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e), 'schema_name': schema_name}


@shared_task(base=CallbackTask)
def recalculate_stock_levels(schema_name: str, store_id: Optional[int] = None) -> Dict[str, Any]:
    """Recalculate stock levels based on movements"""
    try:
        with schema_context(schema_name):
            recalculated_count = 0
            error_count = 0
            adjustments_made = []

            stocks_query = Stock.objects.select_related('product', 'store')
            if store_id:
                stocks_query = stocks_query.filter(store_id=store_id)

            stocks = stocks_query.all()
            total_stocks = stocks.count()

            logger.info(f"[{schema_name}] Starting stock recalculation for {total_stocks} records")

            for i, stock in enumerate(stocks):
                try:
                    if i % 100 == 0 and hasattr(current_task, 'update_state'):
                        current_task.update_state(
                            state='PROGRESS',
                            meta={
                                'current': i + 1,
                                'total': total_stocks,
                                'status': f'Recalculating... ({i + 1}/{total_stocks})'
                            }
                        )

                    movements = StockMovement.objects.filter(
                        product=stock.product,
                        store=stock.store
                    )

                    inbound_movements = movements.filter(
                        movement_type__in=['PURCHASE', 'RETURN', 'TRANSFER_IN']
                    ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

                    outbound_movements = movements.filter(
                        movement_type__in=['SALE', 'TRANSFER_OUT']
                    ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

                    adjustments = movements.filter(
                        movement_type='ADJUSTMENT'
                    ).aggregate(total=Sum('quantity'))['total'] or Decimal('0')

                    calculated_quantity = inbound_movements - outbound_movements + adjustments
                    calculated_quantity = max(Decimal('0'), calculated_quantity)

                    if abs(calculated_quantity - stock.quantity) > Decimal('0.001'):
                        old_quantity = stock.quantity
                        stock.quantity = calculated_quantity
                        stock.save(update_fields=['quantity'])

                        adjustment_info = {
                            'stock_id': stock.id,
                            'product_name': stock.product.name,
                            'store_name': stock.store.name,
                            'old_quantity': float(old_quantity),
                            'new_quantity': float(calculated_quantity),
                            'difference': float(calculated_quantity - old_quantity)
                        }
                        adjustments_made.append(adjustment_info)
                        recalculated_count += 1

                except Exception as e:
                    error_count += 1
                    logger.error(
                        f"[{schema_name}] Error recalculating stock for "
                        f"{stock.product.name} at {stock.store.name}: {str(e)}"
                    )

            if recalculated_count > 0:
                send_dashboard_update()

            result = {
                'success': True,
                'processed_stocks': total_stocks,
                'recalculated_count': recalculated_count,
                'error_count': error_count,
                'adjustments_made': adjustments_made[:20],
                'store_filter': store_id,
                'message': f'Stock recalculation completed. {recalculated_count} adjustments made, {error_count} errors.',
                'schema_name': schema_name
            }

            logger.info(f"[{schema_name}] {result['message']}")
            return result

    except Exception as e:
        logger.error(f"[{schema_name}] Stock recalculation failed: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e), 'schema_name': schema_name}


@shared_task(base=CallbackTask)
def daily_inventory_maintenance(schema_name: str) -> Dict[str, Any]:
    """Comprehensive daily maintenance for inventory system"""
    try:
        maintenance_results = {}
        start_time = timezone.now()

        logger.info(f"[{schema_name}] Starting daily inventory maintenance")

        # 1. Clean up old import sessions
        cleanup_task = cleanup_old_import_sessions.delay(schema_name, retention_days=30)
        maintenance_results['cleanup'] = cleanup_task.get(timeout=300)

        # 2. Generate low stock alerts
        alerts_task = generate_low_stock_alerts.delay(schema_name)
        maintenance_results['alerts'] = alerts_task.get(timeout=180)

        # 3. Sync EFRIS products
        if getattr(settings, 'EFRIS_SYNC_ENABLED', False):
            efris_task = sync_efris_products.delay(schema_name, batch_size=100)
            maintenance_results['efris_sync'] = efris_task.get(timeout=600)

        # 4. Generate and cache reports
        reports_task = generate_inventory_reports.delay(schema_name, include_trends=True)
        maintenance_results['reports'] = reports_task.get(timeout=300)

        # 5. Recalculate stock levels (weekly on Sundays)
        if timezone.now().weekday() == 6:
            recalc_task = recalculate_stock_levels.delay(schema_name)
            maintenance_results['stock_recalculation'] = recalc_task.get(timeout=1800)

        end_time = timezone.now()
        duration = end_time - start_time

        summary = {
            'success': True,
            'duration_seconds': duration.total_seconds(),
            'completed_tasks': len([r for r in maintenance_results.values() if r.get('success', False)]),
            'failed_tasks': len([r for r in maintenance_results.values() if not r.get('success', True)]),
            'results': maintenance_results,
            'timestamp': end_time.isoformat(),
            'schema_name': schema_name
        }

        logger.info(f"[{schema_name}] Daily maintenance completed in {duration.total_seconds():.2f}s")
        return summary

    except Exception as e:
        logger.error(f"[{schema_name}] Daily maintenance failed: {str(e)}", exc_info=True)
        return {
            'success': False,
            'error': str(e),
            'timestamp': timezone.now().isoformat(),
            'schema_name': schema_name
        }


def generate_trend_analysis(schema_name: str) -> Dict[str, Any]:
    """Generate trend analysis for the past 30 days"""
    try:
        with schema_context(schema_name):
            from django.db.models.functions import TruncDate

            end_date = timezone.now().date()
            start_date = end_date - timedelta(days=30)

            daily_movements = list(
                StockMovement.objects.filter(
                    created_at__date__gte=start_date,
                    created_at__date__lte=end_date
                ).annotate(
                    date=TruncDate('created_at')
                ).values('date').annotate(
                    count=Count('id')
                ).order_by('date')
            )

            movement_trend = {
                'dates': [item['date'].isoformat() for item in daily_movements],
                'counts': [item['count'] for item in daily_movements]
            }

            return {
                'movement_trend': movement_trend,
                'analysis_period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'days': 30
                }
            }

    except Exception as e:
        logger.warning(f"[{schema_name}] Trend analysis failed: {str(e)}")
        return {}


def _log_product_registration(company, product, success: bool, result: Dict[str, Any], schema_name: str):
    """Log product registration to EFRIS API log"""
    try:
        from efris.models import EFRISAPILog, FiscalizationAudit

        EFRISAPILog.objects.create(
            company=company,
            interface_code='T130',
            status='SUCCESS' if success else 'FAILED',
            error_message=result.get('error') if not success else None,
            request_data={
                'product_id': product.id,
                'sku': product.sku,
                'name': product.name
            },
            response_data=result,
            duration_ms=result.get('duration_ms'),
            request_time=timezone.now()
        )

        FiscalizationAudit.objects.create(
            company=company,
            action='PRODUCT_REGISTER',
            efris_return_code=result.get('error_code') if not success else '00',
            efris_return_message=result.get('message', 'Product registered successfully'),
            request_payload={
                'product_id': product.id,
                'sku': product.sku
            },
            response_payload=result
        )

    except Exception as e:
        logger.error(f"[{schema_name}] Failed to log product registration: {str(e)}")