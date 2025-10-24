from celery import shared_task
from django.utils import timezone
from .models import Customer, EFRISCustomerSync
from .services import CustomerEFRISService
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def register_customer_with_efris(self, customer_id):
    """Register customer with EFRIS"""
    try:
        customer = Customer.objects.get(id=customer_id)

        # Get company
        company = getattr(customer, 'company', None)
        if not company and hasattr(customer, 'store'):
            company = getattr(customer.store, 'company', None)

        if not company:
            return "No company found for customer"

        if not company.efris_enabled:
            return "EFRIS disabled for company"

        # Check if customer can be synced
        can_sync, error = customer.can_sync_to_efris()
        if not can_sync:
            return f"Customer sync validation failed: {error}"

        # Create sync record
        sync_record = EFRISCustomerSync.objects.create(
            customer=customer,
            sync_type='REGISTER',
            status='PENDING',
            request_payload=customer.get_efris_registration_payload()
        )

        service = CustomerEFRISService(company)
        result = service.register_customer(customer)

        if result['success']:
            sync_record.mark_success(
                response_data=result,
                efris_reference=result.get('reference')
            )

            logger.info(f"Customer {customer.name} registered with EFRIS successfully")
            return f"Registration successful: {result['message']}"
        else:
            sync_record.mark_failed(result['error'], should_retry=True)

            logger.error(f"Customer {customer.name} registration failed: {result['error']}")

            # Retry on certain errors
            if "connection" in result['error'].lower() or "timeout" in result['error'].lower():
                raise self.retry(countdown=60 * (2 ** self.request.retries))

            return f"Registration failed: {result['error']}"

    except Customer.DoesNotExist:
        return "Customer not found"
    except Exception as exc:
        logger.error(f"Customer registration task error: {exc}")

        # Update sync record if it exists
        try:
            sync_record.mark_failed(str(exc))
        except:
            pass

        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def enrich_customer_from_efris(self, customer_id):
    """Enrich customer data from EFRIS taxpayer information"""
    try:
        customer = Customer.objects.get(id=customer_id)

        if not getattr(customer, 'tin', None):
            return "Customer has no TIN for enrichment"

        # Get company
        company = getattr(customer, 'company', None)
        if not company and hasattr(customer, 'store'):
            company = getattr(customer.store, 'company', None)

        if not company or not company.efris_enabled:
            return "EFRIS not available for customer's company"

        service = CustomerEFRISService(company)
        success, message = service.enrich_customer(customer)

        if success:
            logger.info(f"Customer {customer.name} enriched from EFRIS: {message}")
            return f"Enrichment successful: {message}"
        else:
            logger.warning(f"Customer {customer.name} enrichment failed: {message}")

            # Retry on connection errors
            if "connection" in message.lower() or "timeout" in message.lower():
                raise self.retry(countdown=300)

            return f"Enrichment failed: {message}"

    except Customer.DoesNotExist:
        return "Customer not found"
    except Exception as exc:
        logger.error(f"Customer enrichment task error: {exc}")
        raise self.retry(exc=exc, countdown=300)


@shared_task(bind=True, max_retries=3)
def bulk_register_customers_with_efris(self, company_id, customer_ids=None, max_customers=20):
    """Bulk register customers with EFRIS"""
    try:
        from company.models import Company
        company = Company.objects.get(company_id=company_id)

        if not company.efris_enabled:
            return "EFRIS disabled for company"

        # Get customers to register
        if customer_ids:
            customers = Customer.objects.filter(id__in=customer_ids)
        else:
            # Get customers pending EFRIS registration
            customers = Customer.objects.filter(
                efris_status='NOT_REGISTERED'
            )

            # Add company filter based on your model structure
            if hasattr(Customer, 'company'):
                customers = customers.filter(company=company)
            elif hasattr(Customer, 'store'):
                customers = customers.filter(store__company=company)

            # Only customers in auto-sync groups or with TIN
            customers = customers.filter(
                Q(groups__auto_sync_to_efris=True) | Q(tin__isnull=False)
            ).distinct()

        customers = customers[:max_customers]  # Limit batch size

        if not customers:
            return "No customers to register"

        results = {'success': 0, 'failed': 0, 'errors': []}
        service = CustomerEFRISService(company)

        for customer in customers:
            can_sync, error = customer.can_sync_to_efris()
            if not can_sync:
                results['failed'] += 1
                results['errors'].append(f"{customer.name}: {error}")
                continue

            try:
                result = service.register_customer(customer)
                if result['success']:
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(f"{customer.name}: {result['error']}")
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f"{customer.name}: {str(e)}")

        message = f"Bulk registration completed: {results['success']} successful, {results['failed']} failed"
        logger.info(f"Bulk customer registration for company {company_id}: {message}")

        return {
            'message': message,
            'results': results
        }

    except Exception as exc:
        logger.error(f"Bulk customer registration task error: {exc}")
        raise self.retry(exc=exc, countdown=300)


@shared_task
def retry_failed_customer_syncs():
    """Retry failed customer EFRIS syncs"""
    try:
        # Get failed syncs that can be retried
        failed_syncs = EFRISCustomerSync.objects.filter(
            status='FAILED'
        ).select_related('customer')

        retry_count = 0
        for sync in failed_syncs:
            if sync.can_retry:
                if sync.sync_type == 'REGISTER':
                    register_customer_with_efris.delay(sync.customer.id)
                elif sync.sync_type == 'UPDATE':
                    # You could add update task here
                    pass

                retry_count += 1

        logger.info(f"Scheduled retry for {retry_count} failed customer syncs")
        return f"Retried {retry_count} failed syncs"

    except Exception as e:
        logger.error(f"Failed sync retry task error: {e}")
        return f"Retry task failed: {str(e)}"


@shared_task
def cleanup_old_customer_sync_records():
    """Clean up old customer sync records"""
    try:
        # Delete successful sync records older than 30 days
        cutoff_date = timezone.now() - timezone.timedelta(days=30)

        old_syncs = EFRISCustomerSync.objects.filter(
            status='SUCCESS',
            created_at__lt=cutoff_date
        )

        deleted_count = old_syncs.count()
        old_syncs.delete()

        logger.info(f"Cleaned up {deleted_count} old customer sync records")
        return f"Cleaned up {deleted_count} records"

    except Exception as e:
        logger.error(f"Cleanup task error: {e}")
        return f"Cleanup failed: {str(e)}"