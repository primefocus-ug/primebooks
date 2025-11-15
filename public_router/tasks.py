from celery import shared_task
from django.db import transaction, connection
from django.utils import timezone
from django_tenants.utils import schema_context
from datetime import timedelta
import logging
import time
from celery.exceptions import SoftTimeLimitExceeded
from celery.utils.log import get_task_logger

from .models import TenantSignupRequest
from company.models import Company, Domain, SubscriptionPlan
from accounts.models import CustomUser

logger = logging.getLogger(__name__)



@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    soft_time_limit=240,  # 4 minutes soft limit
    time_limit=300,  # 5 minutes hard limit
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,  # Max 10 minutes between retries
    retry_jitter=True,
    acks_late=True,  # Acknowledge task after completion
    reject_on_worker_lost=True,
)
def create_tenant_async(self, signup_request_id, password):

    try:
        # Track execution time
        start_time = timezone.now()

        logger.info(f"Starting tenant creation for request {signup_request_id}")

        # Get signup request with lock
        try:
            signup_request = TenantSignupRequest.objects.select_for_update(
                nowait=False  # Wait for lock
            ).get(request_id=signup_request_id)
        except TenantSignupRequest.DoesNotExist:
            logger.error(f"Signup request {signup_request_id} not found")
            return {'success': False, 'error': 'Request not found'}

        # Skip if already completed
        if signup_request.status == 'COMPLETED':
            logger.info(f"Request {signup_request_id} already completed")
            return {
                'success': True,
                'company_id': signup_request.created_company_id,
                'already_completed': True
            }

        # Mark as processing
        signup_request.status = 'PROCESSING'
        signup_request.save(update_fields=['status', 'updated_at'])

        # Track metrics
        from .monitoring import track_signup_metrics
        track_signup_metrics(signup_request)

        # Create tenant with lock
        company = create_tenant_with_lock(signup_request, password)

        # Calculate execution time
        execution_time = (timezone.now() - start_time).total_seconds()

        # Update signup request
        signup_request.status = 'COMPLETED'
        signup_request.tenant_created = True
        signup_request.created_company_id = company.company_id
        signup_request.created_schema_name = company.schema_name
        signup_request.completed_at = timezone.now()
        signup_request.save()

        logger.info(
            f"Successfully created tenant {company.company_id} "
            f"in {execution_time:.2f}s for request {signup_request_id}"
        )

        # Send welcome email (async)
        send_welcome_email.delay(company.company_id, signup_request_id)

        return {
            'success': True,
            'company_id': company.company_id,
            'schema_name': company.schema_name,
            'execution_time': execution_time,
        }

    except SoftTimeLimitExceeded:
        logger.error(f"Tenant creation timed out for request {signup_request_id}")

        try:
            signup_request = TenantSignupRequest.objects.get(request_id=signup_request_id)
            signup_request.status = 'FAILED'
            signup_request.error_message = 'Operation timed out. Retrying...'
            signup_request.retry_count = self.request.retries
            signup_request.save()
        except:
            pass

        # Retry with longer delay
        raise self.retry(countdown=120)

    except Exception as e:
        logger.error(
            f"Failed to create tenant for request {signup_request_id}: {str(e)}",
            exc_info=True,
            extra={
                'signup_request_id': signup_request_id,
                'retry_count': self.request.retries,
            }
        )

        # Update signup request
        try:
            signup_request = TenantSignupRequest.objects.get(request_id=signup_request_id)
            signup_request.status = 'FAILED'
            signup_request.error_message = str(e)[:1000]  # Limit error message length
            signup_request.retry_count = self.request.retries
            signup_request.save()
        except Exception as save_error:
            logger.error(f"Failed to update signup request: {str(save_error)}")

        # Retry with backoff
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e)
        else:
            # Final failure - alert admins
            from .monitoring import alert_on_high_failure_rate
            alert_on_high_failure_rate()
            raise

def create_tenant_with_lock(signup_request, password):
    """
    Create tenant with database-level locking to prevent race conditions.

    Uses advisory locks for PostgreSQL.
    """

    schema_name = f"tenant_{signup_request.subdomain}"

    # Use PostgreSQL advisory lock to prevent concurrent creation
    lock_id = hash(schema_name) % 2147483647  # Convert to 32-bit int

    with connection.cursor() as cursor:
        # Acquire advisory lock (blocks if another process has it)
        cursor.execute("SELECT pg_advisory_lock(%s)", [lock_id])

        try:
            # Double-check schema doesn't exist
            if Company.objects.filter(schema_name=schema_name).exists():
                raise ValueError(f"Schema {schema_name} already exists")

            # Create tenant in atomic transaction
            with transaction.atomic():
                company = create_company(signup_request, schema_name)
                domain = create_domain(signup_request, company)
                admin_user = create_admin_user(signup_request, company, password)

            logger.info(f"Created tenant infrastructure for {schema_name}")
            return company

        finally:
            # Release advisory lock
            cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])


def create_company(signup_request, schema_name):
    """Create company/tenant"""

    # Get or create subscription plan
    plan, _ = SubscriptionPlan.objects.get_or_create(
        name=signup_request.selected_plan,
        defaults={
            'display_name': f'{signup_request.selected_plan.title()} Plan',
            'price': 0 if signup_request.selected_plan == 'FREE' else 50,
            'trial_days': 60 if signup_request.selected_plan == 'FREE' else 14,
            'max_users': 5 if signup_request.selected_plan == 'FREE' else 50,
            'max_branches': 1 if signup_request.selected_plan == 'FREE' else 10,
            'max_storage_gb': 1 if signup_request.selected_plan == 'FREE' else 50,
        }
    )

    # Create company
    company = Company.objects.create(
        schema_name=schema_name,
        name=signup_request.company_name,
        trading_name=signup_request.trading_name or signup_request.company_name,
        email=signup_request.email,
        phone=signup_request.phone,
        plan=plan,
        is_trial=True,
        trial_ends_at=timezone.now().date() + timedelta(days=plan.trial_days),
        status='TRIAL',
    )

    logger.info(f"Created company: {company.company_id}")
    return company


def create_domain(signup_request, company):
    """Create tenant domain"""

    from django.conf import settings

    base_domain = getattr(settings, 'BASE_DOMAIN', 'localhost')
    domain_name = f"{signup_request.subdomain}.{base_domain}"

    # Check if domain already exists (shouldn't happen with locks)
    if Domain.objects.filter(domain=domain_name).exists():
        raise ValueError(f"Domain {domain_name} already exists")

    domain = Domain.objects.create(
        tenant=company,
        domain=domain_name,
        is_primary=True,
        ssl_enabled=getattr(settings, 'USE_SSL', True)
    )

    logger.info(f"Created domain: {domain.domain}")
    return domain


def create_admin_user(signup_request, company, password):
    """Create admin user in tenant schema"""

    # Wait for schema to be fully created
    max_retries = 5
    for attempt in range(max_retries):
        try:
            with schema_context(company.schema_name):
                # Check if schema is ready
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
                break
        except Exception as e:
            if attempt < max_retries - 1:
                logger.warning(f"Schema not ready, retry {attempt + 1}/{max_retries}")
                time.sleep(2)
            else:
                raise e

    # Create admin user in tenant schema
    with schema_context(company.schema_name):
        # Check if user already exists (idempotency)
        existing_user = CustomUser.objects.filter(
            email=signup_request.admin_email
        ).first()

        if existing_user:
            logger.info(f"Admin user already exists: {existing_user.email}")
            return existing_user

        admin_user = CustomUser.objects.create_user(
            email=signup_request.admin_email,
            username=signup_request.admin_email.split('@')[0],
            password=password,
            first_name=signup_request.first_name,
            last_name=signup_request.last_name,
            phone_number=signup_request.admin_phone,
            company=company,
            user_type='COMPANY_ADMIN',
            company_admin=True,
            is_staff=True,
            is_superuser=True,
            is_active=True,
            email_verified=True
        )

        logger.info(f"Created admin user: {admin_user.email}")
        return admin_user


@shared_task
def send_welcome_email(company_id, signup_request_id):
    """Send welcome email after successful tenant creation"""

    try:
        from django.core.mail import send_mail
        from django.conf import settings

        company = Company.objects.get(company_id=company_id)
        signup_request = TenantSignupRequest.objects.get(request_id=signup_request_id)

        subject = f"Welcome to {company.display_name}!"
        message = f"""
        Hi {signup_request.first_name},

        Your workspace has been created successfully!

        Login URL: https://{signup_request.subdomain}.{settings.BASE_DOMAIN}/login/
        Email: {signup_request.admin_email}

        Your trial ends on: {company.trial_ends_at}

        Best regards,
        The Team
        """

        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [signup_request.admin_email],
            fail_silently=False,
        )

        logger.info(f"Sent welcome email to {signup_request.admin_email}")

    except Exception as e:
        logger.error(f"Failed to send welcome email: {str(e)}", exc_info=True)


@shared_task
def cleanup_failed_signups():
    """
    Periodic task to retry or cleanup failed signups.
    Run this every 5 minutes via Celery Beat.
    """

    from datetime import timedelta

    # Retry failed signups (less than 3 retries, failed in last hour)
    one_hour_ago = timezone.now() - timedelta(hours=1)

    failed_signups = TenantSignupRequest.objects.filter(
        status='FAILED',
        retry_count__lt=3,
        updated_at__gte=one_hour_ago
    )

    for signup in failed_signups:
        logger.info(f"Retrying failed signup: {signup.request_id}")
        # Get password from somewhere secure or mark for manual intervention
        # create_tenant_async.delay(str(signup.request_id), password)


@shared_task
def cleanup_stale_pending_signups():
    """
    Clean up signups stuck in PENDING/PROCESSING for more than 10 minutes.
    Run this every 15 minutes.
    """

    from datetime import timedelta

    ten_minutes_ago = timezone.now() - timedelta(minutes=10)

    stale_signups = TenantSignupRequest.objects.filter(
        status__in=['PENDING', 'PROCESSING'],
        created_at__lt=ten_minutes_ago
    )

    for signup in stale_signups:
        logger.warning(f"Stale signup detected: {signup.request_id}, marking as failed")
        signup.status = 'FAILED'
        signup.error_message = 'Processing timeout - please contact support'
        signup.save()