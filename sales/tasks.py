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
    def find_invoice_schema(invoice_id):
        current_schema = TenantResolver.get_current_schema()
        schemas = TenantResolver.get_all_tenant_schemas()

        if current_schema and current_schema != 'public':
            try:
                with schema_context(current_schema):
                    invoice = Invoice.objects.select_related(
                        'sale__customer',
                        'sale__store__company',
                        'fiscalized_by',
                        'created_by'
                    ).get(pk=invoice_id)
                    logger.info(f"Found invoice {invoice_id} in current schema: {current_schema}")
                    return invoice, current_schema
            except Invoice.DoesNotExist:
                logger.debug(f"Invoice {invoice_id} not in current schema {current_schema}, searching others")
            except Exception as e:
                logger.debug(f"Error checking current schema {current_schema} for invoice {invoice_id}: {e}")

        # Search all other schemas
        for schema_name in schemas:
            if schema_name == current_schema:
                continue

            try:
                with schema_context(schema_name):
                    invoice = Invoice.objects.select_related(
                        'sale__customer',
                        'sale__store__company',
                        'fiscalized_by',
                        'created_by'
                    ).get(pk=invoice_id)
                    logger.info(f"Found invoice {invoice_id} in schema: {schema_name}")

                    if current_schema and current_schema != 'public':
                        try:
                            connection.set_schema(current_schema)
                        except:
                            pass

                    return invoice, schema_name
            except Invoice.DoesNotExist:
                continue
            except Exception as e:
                logger.debug(f"Error checking schema {schema_name} for invoice {invoice_id}: {e}")
                continue

        logger.error(f"Invoice {invoice_id} not found in any tenant schema")

        if current_schema and current_schema != 'public':
            try:
                connection.set_schema(current_schema)
            except:
                pass

        return None, None

    @staticmethod
    def find_sale_schema(sale_id):
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
    def resolve_company_from_invoice(invoice):
        """
        Resolve company from invoice relationships
        """
        company = None

        if invoice.store and hasattr(invoice.store, 'company'):
            company = invoice.store.company
        elif invoice.sale and invoice.sale.store and hasattr(invoice.sale.store, 'company'):
            company = invoice.sale.store.company
        elif hasattr(invoice, 'company'):
            company = invoice.company

        return company


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def fiscalize_invoice_async(self, invoice_id, user_id=None):
    """
    Self-resolving fiscalization task - automatically finds the correct tenant schema
    Now with improved schema context management
    """
    # Capture the schema context at task start
    initial_schema = TenantResolver.get_current_schema()
    logger.info(
        f"Fiscalization task started for invoice {invoice_id} "
        f"(initial schema: {initial_schema}, task_id: {self.request.id})"
    )

    try:
        # Step 1: Find the invoice and its tenant schema
        invoice, tenant_schema = TenantResolver.find_invoice_schema(invoice_id)

        if not invoice or not tenant_schema:
            logger.error(
                f"Invoice {invoice_id} not found in any tenant schema "
                f"(searched from schema: {initial_schema})"
            )
            return {
                'success': False,
                'message': 'Invoice not found in any tenant',
                'schema': None,
                'initial_schema': initial_schema
            }

        logger.info(f"Processing invoice {invoice_id} in tenant schema: {tenant_schema}")

        # Step 2: Execute fiscalization within the correct tenant context
        with schema_context(tenant_schema):
            # Re-fetch invoice to ensure we have fresh data and all relationships
            invoice = Invoice.objects.select_related(
                'sale__customer',
                'sale__store__company',
                'fiscalized_by',
                'created_by'
            ).get(pk=invoice_id)

            # Get user if provided
            user = None
            if user_id:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                try:
                    user = User.objects.get(pk=user_id)
                except User.DoesNotExist:
                    logger.warning(f"User {user_id} not found in schema {tenant_schema}")

            # Check if already fiscalized
            if invoice.is_fiscalized:
                logger.info(f"Invoice {invoice.invoice_number} is already fiscalized")
                return {
                    'success': True,
                    'message': 'Invoice already fiscalized',
                    'fiscal_number': invoice.fiscal_document_number,
                    'schema': tenant_schema
                }

            # Resolve company
            company = TenantResolver.resolve_company_from_invoice(invoice)

            if not company:
                logger.error(f"No company found for invoice {invoice_id}")
                return {
                    'success': False,
                    'message': 'No company found for invoice',
                    'schema': tenant_schema
                }

            # Check if company has EFRIS enabled
            if not getattr(company, 'efris_enabled', False):
                logger.warning(f"EFRIS not enabled for company {company.company_id}")
                return {
                    'success': False,
                    'message': 'EFRIS not enabled for this company',
                    'schema': tenant_schema
                }

            # Validate invoice amounts
            if not invoice.total_amount or invoice.total_amount <= 0:
                error_msg = f"Invalid invoice amount: {invoice.total_amount}"
                logger.error(f"Invalid invoice amount for invoice {invoice_id}: {invoice.total_amount}")
                invoice.fiscalization_status = 'failed'
                invoice.fiscalization_error = error_msg
                invoice.save(update_fields=['fiscalization_status', 'fiscalization_error'])
                return {
                    'success': False,
                    'message': error_msg,
                    'schema': tenant_schema
                }

            # Fiscalize with EFRIS
            try:
                efris_service = EFRISInvoiceService(company)
                result = efris_service.fiscalize_invoice(invoice, user)
                logger.debug(f"fiscalize_invoice result for invoice {invoice_id}: {result} (type: {type(result)})")

                success = result.get('success', False)
                message = result.get('message', 'Unknown error')
                error_code = result.get('error_code')

                # CRITICAL: Handle duplicate invoice error (2253)
                if not success and '2253' in str(error_code or message):
                    logger.warning(
                        f"Invoice {invoice.invoice_number} already fiscalized on EFRIS. "
                        f"Extracting fiscal number from error message."
                    )

                    # Extract fiscal number from error message
                    import re
                    match = re.search(r'\((\d+)\)', message)
                    fiscal_doc_number = match.group(1) if match else ''

                    if fiscal_doc_number:
                        invoice.fiscal_document_number = fiscal_doc_number
                        invoice.fiscalization_status = 'fiscalized'
                        invoice.is_fiscalized = True
                        invoice.fiscalization_time = timezone.now()
                        invoice.fiscalization_error = None

                        if user:
                            invoice.fiscalized_by = user

                        update_fields = [
                            'fiscal_document_number',
                            'fiscalization_status',
                            'is_fiscalized',
                            'fiscalization_time',
                            'fiscalization_error',
                            'fiscalized_by'
                        ]

                        invoice.save(update_fields=update_fields)

                        logger.info(
                            f"Successfully recovered fiscalized invoice {invoice.invoice_number} "
                            f"(Fiscal #: {fiscal_doc_number})"
                        )

                        return {
                            'success': True,
                            'message': f'Invoice already fiscalized (recovered): {fiscal_doc_number}',
                            'fiscal_number': fiscal_doc_number,
                            'schema': tenant_schema
                        }
                    else:
                        invoice.fiscalization_status = 'needs_review'
                        invoice.fiscalization_error = 'Duplicate on EFRIS but fiscal number not found'
                        invoice.save(update_fields=['fiscalization_status', 'fiscalization_error'])

                        return {
                            'success': False,
                            'message': 'Invoice needs manual review - duplicate on EFRIS',
                            'schema': tenant_schema
                        }

                if success:
                    # --- Extract EFRIS response data ---
                    efris_data = result.get('data', {})

                    # Fiscal document number
                    fiscal_doc_number = (
                            efris_data.get('invoice_no') or
                            efris_data.get('full_response', {}).get('basicInformation', {}).get('invoiceNo', '')
                    )

                    # --- Update Invoice fields ---
                    invoice.fiscal_document_number = fiscal_doc_number
                    invoice.fiscal_number = fiscal_doc_number  # backward compatibility
                    invoice.verification_code = (
                            efris_data.get('fiscal_code') or
                            efris_data.get('verification_code') or
                            uuid.uuid4().hex[:8].upper()  # fallback if missing
                    )
                    invoice.qr_code = (
                            efris_data.get('qrCode') or
                            efris_data.get('qr_code') or
                            invoice.qr_code
                    )
                    invoice.fiscalization_status = 'fiscalized'
                    invoice.is_fiscalized = True
                    invoice.fiscalization_time = timezone.now()
                    invoice.fiscalization_error = None

                    if user:
                        invoice.fiscalized_by = user

                    # Optional: EFRIS invoice id (if model supports it)
                    if hasattr(invoice, 'efris_invoice_id'):
                        invoice.efris_invoice_id = efris_data.get('invoice_id', '')

                    # Determine which fields to update
                    update_fields = [
                        'fiscal_document_number',
                        'fiscal_number',
                        'verification_code',
                        'qr_code',
                        'fiscalization_status',
                        'is_fiscalized',
                        'fiscalization_time',
                        'fiscalization_error',
                        'fiscalized_by',
                    ]
                    if hasattr(invoice, 'efris_invoice_id'):
                        update_fields.append('efris_invoice_id')

                    # --- Save Invoice ---
                    invoice.save(update_fields=update_fields)

                    # --- Sync related Sale model (if any) ---
                    if hasattr(invoice, 'sale') and invoice.sale:
                        sale = invoice.sale
                        sale.fiscal_number = invoice.fiscal_document_number
                        sale.qr_code = invoice.qr_code
                        sale.verification_code = invoice.verification_code
                        sale.is_fiscalized = True
                        sale.fiscalization_status = 'fiscalized'
                        sale.fiscalization_time = timezone.now()

                        # If Sale has tracking fields like fiscalized_by
                        if hasattr(sale, 'fiscalized_by') and user:
                            sale.fiscalized_by = user

                        sale.save(update_fields=[
                            'fiscal_number',
                            'qr_code',
                            'verification_code',
                            'is_fiscalized',
                            'fiscalization_status',
                            'fiscalization_time',
                            *(['fiscalized_by'] if hasattr(sale, 'fiscalized_by') else [])
                        ])

                        logger.info(
                            f"✅ Synchronized fiscalization data to Sale {sale.id} for Invoice {invoice.invoice_number}"
                        )

                    # --- Optional: send notification ---
                    if getattr(settings, 'EFRIS_SEND_NOTIFICATIONS', False):
                        send_fiscalization_notification.delay(invoice_id, success=True)

                    logger.info(
                        f"✅ Successfully fiscalized Invoice {invoice.invoice_number} "
                        f"(Fiscal #: {fiscal_doc_number}) in schema {tenant_schema}"
                    )

                    return {
                        'success': True,
                        'message': message,
                        'fiscal_number': fiscal_doc_number,
                        'schema': tenant_schema
                    }
                else:
                    invoice.fiscalization_status = 'failed'
                    invoice.fiscalization_error = message
                    invoice.save(update_fields=['fiscalization_status', 'fiscalization_error'])

                    # Retry logic (but NOT for duplicate errors)
                    if self.request.retries < self.max_retries:
                        countdown = 60 * (2 ** self.request.retries)
                        logger.info(
                            f"Retrying fiscalization of invoice {invoice.invoice_number} "
                            f"in {countdown} seconds (attempt {self.request.retries + 1})"
                        )
                        raise self.retry(countdown=countdown, exc=Exception(message))

                    if getattr(settings, 'EFRIS_SEND_NOTIFICATIONS', False):
                        send_fiscalization_notification.delay(invoice_id, success=False, error=message)

                    logger.error(f"Fiscalization failed for invoice {invoice.invoice_number}: {message}")
                    return {
                        'success': False,
                        'message': message,
                        'schema': tenant_schema
                    }

            except Exception as efris_error:
                error_msg = f"EFRIS service error: {str(efris_error)}"
                logger.error(f"EFRIS service error for invoice {invoice_id}: {str(efris_error)}", exc_info=True)

                invoice.fiscalization_status = 'failed'
                invoice.fiscalization_error = error_msg
                invoice.save(update_fields=['fiscalization_status', 'fiscalization_error'])

                # Retry on EFRIS errors (but not duplicates)
                if self.request.retries < self.max_retries and '2253' not in str(efris_error):
                    countdown = 60 * (2 ** self.request.retries)
                    logger.info(
                        f"Retrying fiscalization of invoice {invoice.invoice_number} "
                        f"in {countdown} seconds (attempt {self.request.retries + 1})"
                    )
                    raise self.retry(countdown=countdown, exc=efris_error)

                return {
                    'success': False,
                    'message': error_msg,
                    'schema': tenant_schema
                }

    except Exception as e:
        logger.error(f"Fiscalization task failed for invoice {invoice_id}: {str(e)}", exc_info=True)

        # Try to update invoice status if we know the schema
        if 'tenant_schema' in locals() and tenant_schema:
            try:
                with schema_context(tenant_schema):
                    invoice = Invoice.objects.get(pk=invoice_id)
                    invoice.fiscalization_status = 'failed'
                    invoice.fiscalization_error = str(e)
                    invoice.save(update_fields=['fiscalization_status', 'fiscalization_error'])
            except Exception as update_error:
                logger.error(f"Failed to update invoice status for invoice {invoice_id}: {update_error}")

        return {
            'success': False,
            'message': str(e),
            'schema': tenant_schema if 'tenant_schema' in locals() else None
        }

    finally:
        # Ensure we restore the original schema context if needed
        current_final_schema = TenantResolver.get_current_schema()
        if initial_schema and initial_schema != current_final_schema:
            try:
                if initial_schema != 'public':
                    connection.set_schema(initial_schema)
                    logger.debug(f"Restored schema context to {initial_schema}")
            except Exception as restore_error:
                logger.warning(f"Could not restore initial schema {initial_schema}: {restore_error}")


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