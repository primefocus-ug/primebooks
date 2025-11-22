from celery import shared_task
from django.utils import timezone
from django.db.models import F
from django_tenants.utils import schema_context, get_tenant_model
import logging

from .models import Notification, NotificationLog, NotificationBatch
from .services import NotificationService, CompanyNotifications

logger = logging.getLogger(__name__)


@shared_task
def send_notification_batch(batch_id, tenant_schema):
    """
    Send a batch of notifications
    """
    try:
        with schema_context(tenant_schema):
            batch = NotificationBatch.objects.get(id=batch_id)

            if batch.status != 'SCHEDULED':
                logger.warning(f"Batch {batch_id} is not scheduled, status: {batch.status}")
                return

            batch.status = 'SENDING'
            batch.started_at = timezone.now()
            batch.save(update_fields=['status', 'started_at'])

            recipients = batch.recipients.all()
            sent_count = 0
            failed_count = 0

            for recipient in recipients:
                try:
                    if batch.template:
                        # Use template
                        notification = NotificationService.create_from_template(
                            event_type=batch.template.event_type,
                            recipient=recipient,
                            context=batch.context_data or {},
                            tenant_schema=tenant_schema
                        )
                    else:
                        # Use context_data directly
                        context = batch.context_data or {}
                        notification = NotificationService.create_notification(
                            recipient=recipient,
                            title=context.get('title', 'Notification'),
                            message=context.get('message', ''),
                            notification_type=context.get('type', 'INFO'),
                            priority=context.get('priority', 'MEDIUM'),
                            tenant_schema=tenant_schema
                        )

                    if notification:
                        sent_count += 1
                    else:
                        failed_count += 1

                except Exception as e:
                    logger.error(f"Failed to send notification to {recipient.id}: {e}")
                    failed_count += 1

            batch.sent_count = sent_count
            batch.failed_count = failed_count
            batch.status = 'COMPLETED'
            batch.completed_at = timezone.now()
            batch.save(update_fields=['sent_count', 'failed_count', 'status', 'completed_at'])

            logger.info(f"Batch {batch_id} completed. Sent: {sent_count}, Failed: {failed_count}")

    except NotificationBatch.DoesNotExist:
        logger.error(f"NotificationBatch {batch_id} not found")
    except Exception as e:
        logger.error(f"Error sending notification batch {batch_id}: {e}", exc_info=True)

        # Mark batch as failed
        try:
            with schema_context(tenant_schema):
                batch = NotificationBatch.objects.get(id=batch_id)
                batch.status = 'FAILED'
                batch.completed_at = timezone.now()
                batch.save(update_fields=['status', 'completed_at'])
        except:
            pass


@shared_task
def retry_failed_notifications():
    """
    Retry failed notifications across all tenants
    """
    try:
        TenantModel = get_tenant_model()

        for tenant in TenantModel.objects.exclude(schema_name='public'):
            try:
                with schema_context(tenant.schema_name):
                    # Get failed notifications that can be retried
                    failed_logs = NotificationLog.objects.filter(
                        status='FAILED',
                        retry_count__lt=F('max_retries'),
                        created_at__gte=timezone.now() - timezone.timedelta(hours=24)
                    )

                    for log in failed_logs[:100]:  # Limit to 100 per run
                        try:
                            NotificationService.retry_failed_notification(
                                log.id,
                                tenant.schema_name
                            )
                        except Exception as e:
                            logger.error(f"Failed to retry notification {log.id}: {e}")

            except Exception as e:
                logger.error(f"Error processing tenant {tenant.schema_name}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Error in retry_failed_notifications: {e}", exc_info=True)


@shared_task
def clean_old_notifications():
    """
    Clean up old read notifications and expired notifications across all tenants
    """
    try:
        TenantModel = get_tenant_model()
        cutoff_date = timezone.now() - timezone.timedelta(days=90)

        for tenant in TenantModel.objects.exclude(schema_name='public'):
            try:
                with schema_context(tenant.schema_name):
                    # Delete old read notifications
                    deleted_read = Notification.objects.filter(
                        is_read=True,
                        read_at__lt=cutoff_date
                    ).delete()

                    # Delete expired notifications
                    deleted_expired = Notification.objects.filter(
                        expires_at__lt=timezone.now()
                    ).delete()

                    logger.info(
                        f"Tenant {tenant.schema_name}: Deleted {deleted_read[0]} old read "
                        f"and {deleted_expired[0]} expired notifications"
                    )

            except Exception as e:
                logger.error(f"Error cleaning tenant {tenant.schema_name}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Error in clean_old_notifications: {e}", exc_info=True)


@shared_task
def check_overdue_invoices():
    """
    Check for overdue invoices and send notifications across all tenants
    """
    try:
        from invoices.models import Invoice
        TenantModel = get_tenant_model()

        for tenant in TenantModel.objects.exclude(schema_name='public'):
            try:
                with schema_context(tenant.schema_name):
                    # Get overdue invoices that haven't been notified today
                    today = timezone.now().date()

                    overdue_invoices = Invoice.objects.filter(
                        status='PENDING',
                        due_date__lt=today,
                        is_overdue_notified=False  # Assuming you add this field
                    )

                    for invoice in overdue_invoices:
                        # Notify relevant users
                        if invoice.sale and invoice.sale.created_by:
                            NotificationService.create_from_template(
                                event_type='invoice_overdue',
                                recipient=invoice.sale.created_by,
                                context={
                                    'invoice_number': invoice.invoice_number,
                                    'due_date': invoice.due_date.strftime('%Y-%m-%d'),
                                    'days_overdue': (today - invoice.due_date).days,
                                    'amount': f'{invoice.total_amount:,.0f}',
                                },
                                related_object=invoice,
                                priority='HIGH',
                                tenant_schema=tenant.schema_name
                            )

                        # Mark as notified
                        invoice.is_overdue_notified = True
                        invoice.save(update_fields=['is_overdue_notified'])

            except Exception as e:
                logger.error(f"Error checking invoices for tenant {tenant.schema_name}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Error in check_overdue_invoices: {e}", exc_info=True)


@shared_task
def check_subscription_expiry():
    """
    Check for expiring subscriptions and send notifications
    """
    try:
        from company.models import Company

        today = timezone.now().date()
        check_days = [30, 14, 7, 3, 1]

        companies = Company.objects.filter(
            subscription_ends_at__isnull=False,
            status='ACTIVE'
        )

        for company in companies:
            days_remaining = (company.subscription_ends_at - today).days

            if days_remaining in check_days:
                # Check if already notified today
                last_notification = Notification.objects.filter(
                    tenant_id=company.schema_name,
                    template__event_type='subscription_expiring',
                    created_at__date=today
                ).exists()

                if not last_notification:
                    CompanyNotifications.notify_subscription_expiring(company, days_remaining)

    except Exception as e:
        logger.error(f"Error in check_subscription_expiry: {e}", exc_info=True)


@shared_task
def check_trial_expiry():
    """
    Check for expiring trials and send notifications
    """
    try:
        from company.models import Company

        today = timezone.now().date()
        check_days = [7, 3, 1]

        companies = Company.objects.filter(
            is_trial=True,
            trial_ends_at__isnull=False,
            status='ACTIVE'
        )

        for company in companies:
            days_remaining = (company.trial_ends_at - today).days

            if days_remaining in check_days:
                # Check if already notified today
                last_notification = Notification.objects.filter(
                    tenant_id=company.schema_name,
                    template__event_type='trial_ending',
                    created_at__date=today
                ).exists()

                if not last_notification:
                    CompanyNotifications.notify_trial_ending(company, days_remaining)

    except Exception as e:
        logger.error(f"Error in check_trial_expiry: {e}", exc_info=True)


@shared_task
def send_digest_notifications():
    """
    Send digest notifications to users who have enabled them
    """
    try:
        from .models import NotificationPreference
        from django.contrib.auth import get_user_model

        User = get_user_model()
        TenantModel = get_tenant_model()

        today = timezone.now()
        current_day = today.strftime('%A').upper()

        for tenant in TenantModel.objects.exclude(schema_name='public'):
            try:
                with schema_context(tenant.schema_name):
                    # Get users with digest enabled
                    preferences = NotificationPreference.objects.filter(
                        digest_enabled=True
                    ).select_related('user')

                    for pref in preferences:
                        should_send = False

                        if pref.digest_frequency == 'DAILY':
                            should_send = True
                        elif pref.digest_frequency == 'WEEKLY' and current_day == 'MONDAY':
                            should_send = True
                        elif pref.digest_frequency == 'MONTHLY' and today.day == 1:
                            should_send = True

                        if should_send:
                            # Get unread notifications
                            unread = Notification.objects.filter(
                                recipient=pref.user,
                                is_read=False,
                                is_dismissed=False
                            )[:10]

                            if unread.exists():
                                # Send digest notification
                                NotificationService.create_notification(
                                    recipient=pref.user,
                                    title=f'You have {unread.count()} unread notifications',
                                    message='Check your notifications for updates.',
                                    notification_type='INFO',
                                    priority='LOW',
                                    action_text='View Notifications',
                                    action_url='/notifications/',
                                    channels=['email'],
                                    tenant_schema=tenant.schema_name
                                )

            except Exception as e:
                logger.error(f"Error sending digests for tenant {tenant.schema_name}: {e}", exc_info=True)

    except Exception as e:
        logger.error(f"Error in send_digest_notifications: {e}", exc_info=True)


