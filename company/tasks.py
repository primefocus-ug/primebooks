from celery import shared_task
from celery.schedules import crontab
from django.utils import timezone
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.db.models import Q, Sum, Count, Avg, F
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from datetime import timedelta
from decimal import Decimal
from django_tenants.utils import tenant_context, schema_context
from django.core.serializers.json import DjangoJSONEncoder
import logging
from .models import Company
from sales.models import Sale
from stores.models import Store, DeviceOperatorLog
from accounts.models import CustomUser
from inventory.models import Stock
from .company_services import CompanyEFRISService

logger = logging.getLogger(__name__)
channel_layer = get_channel_layer()


@shared_task(bind=True, max_retries=3)
def setup_efris_for_company(self, company_id):
    """Setup EFRIS integration for a company"""
    try:
        from company.models import Company
        from company.company_services import setup_efris_for_company as setup_efris_service

        logger.info(f"Scheduling EFRIS setup for new company {company_id}")

        company = Company.objects.get(company_id=company_id)

        if not company.efris_enabled:
            logger.info(f"EFRIS disabled for company {company_id}, skipping setup")
            return "EFRIS disabled"

        # Call the service function (returns a dictionary)
        setup_result = setup_efris_service(company)

        if setup_result['success']:
            logger.info(
                f"EFRIS setup completed for company {company_id}: "
                f"{len(setup_result['steps_completed'])} steps completed"
            )
            return setup_result.get('message', 'Setup successful')
        else:
            error_message = '; '.join(setup_result.get('errors', ['Unknown error']))
            logger.error(f"EFRIS setup failed for company {company_id}: {error_message}")

            # Retry on certain errors
            if any(keyword in error_message.lower() for keyword in ['authentication', 'connection', 'network']):
                logger.warning(f"Retrying EFRIS setup for company {company_id} due to transient error")
                raise self.retry(countdown=60 * (2 ** self.request.retries))

            return f"Setup failed: {error_message}"

    except Company.DoesNotExist:
        logger.error(f"Company {company_id} not found for EFRIS setup")
        return "Company not found"
    except Exception as exc:
        logger.error(f"EFRIS setup error for company {company_id}: {exc}", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2 ** self.request.retries))


@shared_task(bind=True, max_retries=3)
def sync_company_to_efris(self, company_id):
    """Sync company data changes to EFRIS"""
    try:
        company = Company.objects.get(company_id=company_id)

        if not company.efris_enabled or not company.efris_is_active:
            return "EFRIS not active"

        service = CompanyEFRISService(company)

        # Test connection first
        connected, message = service.test_connection()
        if not connected:
            logger.warning(f"EFRIS connection failed for company {company_id}: {message}")
            raise self.retry(countdown=300)  # Retry in 5 minutes

        # Update last sync time
        company.update_efris_sync(sync_successful=True)

        logger.info(f"Company {company_id} synced with EFRIS successfully")
        return "Sync successful"

    except Company.DoesNotExist:
        return "Company not found"
    except Exception as exc:
        logger.error(f"Company EFRIS sync error: {exc}")
        raise self.retry(exc=exc, countdown=300)


@shared_task
def check_efris_status_for_companies():
    """Periodic task to check EFRIS status for all enabled companies"""
    companies = Company.objects.filter(
        efris_enabled=True,
        is_active=True
    )

    results = {'checked': 0, 'errors': 0, 'warnings': []}

    for company in companies:
        try:
            service = CompanyEFRISService(company)
            connected, message = service.test_connection()

            if not connected:
                results['errors'] += 1
                results['warnings'].append(f"Company {company.company_id}: {message}")
            else:
                results['checked'] += 1

        except Exception as e:
            results['errors'] += 1
            results['warnings'].append(f"Company {company.company_id}: {str(e)}")

    logger.info(f"EFRIS status check completed: {results}")
    return results

@shared_task
def check_performance_alerts():
    """Background task to check performance and send alerts"""
    try:
        # Query companies from public schema
        companies = Company.objects.filter(is_active=True)
        thirty_days_ago = timezone.now().date() - timedelta(days=30)

        for company in companies:
            with tenant_context(company):
                # Check for underperforming branches
                # Store IS the branch — each Store is its own entity, no sub-stores relation
                branches = Store.objects.filter(company=company, is_active=True)

                for branch in branches:
                    # Check sales activity directly against this store
                    recent_sales = Sale.objects.filter(
                        store_id=branch.id,
                        created_at__date__gte=thirty_days_ago,
                        is_voided=False,
                        status__in=['COMPLETED', 'PAID']
                    ).count()

                    # Alert if no sales in 7 days
                    week_ago = timezone.now().date() - timedelta(days=7)
                    week_sales = Sale.objects.filter(
                        store_id=branch.id,
                        created_at__date__gte=week_ago,
                        is_voided=False,
                        status__in=['COMPLETED', 'PAID']
                    ).count()

                    if week_sales == 0 and recent_sales > 0:  # Was active but now inactive
                        send_performance_alert(
                            company.company_id,
                            'branch_inactive',
                            f"Branch '{branch.name}' has no sales in the last 7 days",
                            {
                                'branch_id': branch.id,
                                'branch_name': branch.name,
                                'days_inactive': 7
                            }
                        )

                # Check inventory levels across company
                all_stores = Store.objects.filter(company=company)
                critical_stock_items = Stock.objects.filter(
                    store__in=all_stores,
                    quantity=0
                ).count()

                if critical_stock_items > 10:  # Alert if more than 10 items out of stock
                    send_performance_alert(
                        company.company_id,
                        'critical_inventory',
                        f"{critical_stock_items} items are completely out of stock across your stores",
                        {'out_of_stock_count': critical_stock_items}
                    )

    except Exception as e:
        logger.error(f"Error in performance alerts task: {e}")


@shared_task
def update_company_metrics():
    """Background task to update and broadcast company metrics"""
    try:
        # Query companies from public schema
        companies = Company.objects.filter(is_active=True)

        for company in companies:
            # Switch to tenant context for tenant-specific queries
            with tenant_context(company):
                # Calculate updated metrics
                branches_count = Store.objects.filter(company=company).count()
                active_branches = Store.objects.filter(company=company, is_active=True).count()

            # Broadcast updated metrics (outside tenant context since it's just WebSocket)
            broadcast_company_update(company.company_id, {
                'event_type': 'metrics_refresh',
                'total_branches': branches_count,
                'active_branches': active_branches,
                'timestamp': timezone.now().isoformat()
            })

    except Exception as e:
        logger.error(f"Error in metrics update task: {e}")


@shared_task
def cleanup_old_websocket_data():
    """Clean up old WebSocket-related data if needed"""
    try:
        # Clean up old channel layer data
        if channel_layer:
            # Get groups that might need cleanup
            # This is implementation-specific to your channel layer backend

            # For Redis channel layer, we can clean up old group data
            try:
                import redis
                from django.conf import settings

                # Get Redis connection from channel layer config
                channel_config = getattr(settings, 'CHANNEL_LAYERS', {}).get('default', {})
                redis_config = channel_config.get('CONFIG', {})

                if redis_config and 'hosts' in redis_config:
                    host, port = redis_config['hosts'][0] if isinstance(redis_config['hosts'][0], tuple) else (
                        redis_config['hosts'][0], 6379)

                    r = redis.Redis(host=host, port=port, decode_responses=True)

                    # Clean up old WebSocket groups (older than 1 hour)
                    cutoff_time = timezone.now() - timedelta(hours=1)
                    cutoff_timestamp = cutoff_time.timestamp()

                    # Pattern to match WebSocket group keys
                    patterns = [
                        'asgi:group:company_dashboard_*',
                        'asgi:group:branch_analytics_*'
                    ]

                    cleaned_count = 0
                    for pattern in patterns:
                        keys = r.keys(pattern)
                        for key in keys:
                            # Check if key is old (this is Redis-specific)
                            try:
                                ttl = r.ttl(key)
                                if ttl == -1 or ttl > 3600:  # No TTL or TTL > 1 hour
                                    # Check last activity
                                    last_activity = r.hget(key, 'last_activity')
                                    if last_activity and float(last_activity) < cutoff_timestamp:
                                        r.delete(key)
                                        cleaned_count += 1
                            except (ValueError, TypeError):
                                # Invalid timestamp, delete key
                                r.delete(key)
                                cleaned_count += 1

                    logger.info(f"Cleaned up {cleaned_count} old WebSocket groups")

            except ImportError:
                logger.warning("Redis not available for WebSocket cleanup")
            except Exception as redis_error:
                logger.error(f"Redis cleanup error: {redis_error}")

        # Clean up old session data related to WebSockets
        cleanup_old_websocket_sessions()

        # Clean up old activity logs for each tenant
        companies = Company.objects.filter(is_active=True)
        for company in companies:
            with tenant_context(company):
                cleanup_old_activity_logs()

        logger.info("WebSocket cleanup completed successfully")

    except Exception as e:
        logger.error(f"Error in WebSocket cleanup task: {e}")


def cleanup_old_websocket_sessions():
    """Clean up old WebSocket-related session data"""
    try:
        from django.contrib.sessions.models import Session

        # Delete sessions older than 7 days (this is in public schema)
        week_ago = timezone.now() - timedelta(days=7)
        old_sessions = Session.objects.filter(expire_date__lt=week_ago)
        deleted_count = old_sessions.count()
        old_sessions.delete()

        logger.info(f"Cleaned up {deleted_count} old sessions")

    except Exception as e:
        logger.error(f"Error cleaning up sessions: {e}")


def cleanup_old_activity_logs():
    """Clean up old activity logs to prevent database bloat (tenant context required)"""
    try:
        # Keep only last 30 days of device logs
        thirty_days_ago = timezone.now() - timedelta(days=30)
        old_logs = DeviceOperatorLog.objects.filter(timestamp__lt=thirty_days_ago)
        deleted_count = old_logs.count()
        old_logs.delete()

        logger.info(f"Cleaned up {deleted_count} old device operator logs")

    except Exception as e:
        logger.error(f"Error cleaning up activity logs: {e}")


@shared_task
def check_company_access_status():
    """Periodic task to check and update company access status"""
    # This runs on public schema since Company is in public schema
    companies = Company.objects.all()
    total_checked = 0
    total_updated = 0
    total_deactivated = 0

    for company in companies:
        total_checked += 1
        old_is_active = company.is_active

        if company.check_and_update_access_status():
            total_updated += 1
            if not company.is_active and old_is_active:
                total_deactivated += 1
                logger.warning(f"Auto-deactivated company {company.company_id}")

    logger.info(f"Checked {total_checked} companies, updated {total_updated}, deactivated {total_deactivated}")
    return {
        'checked': total_checked,
        'updated': total_updated,
        'deactivated': total_deactivated
    }


@shared_task
def send_expiration_warnings():
    """Send warnings to companies approaching expiration"""
    warning_days = [7, 3, 1]  # Send warnings at these day intervals
    today = timezone.now().date()

    for days in warning_days:
        warning_date = today + timedelta(days=days)

        # Find companies expiring on warning date (public schema query)
        expiring_companies = Company.objects.filter(
            is_active=True,
            status__in=['ACTIVE', 'TRIAL']
        ).filter(
            Q(
                is_trial=True,
                trial_ends_at=warning_date
            ) | Q(
                is_trial=False,
                subscription_ends_at=warning_date
            )
        )

        for company in expiring_companies:
            try:
                # billing_email and email are on the public-schema Company model —
                # no tenant_context switch needed here.
                recipient_emails = []
                if company.billing_email:
                    recipient_emails.append(company.billing_email)
                if company.email:
                    recipient_emails.append(company.email)
                recipient_emails = list(set(recipient_emails))

                if recipient_emails:
                    send_mail(
                        subject=f"Your subscription expires in {days} days",
                        message=f"Dear {company.display_name},\n\nYour subscription will expire in {days} days. Please renew to continue using our services.",
                        from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
                        recipient_list=recipient_emails,
                        fail_silently=False,
                    )
                    logger.info(f"Sent {days}-day warning to company {company.company_id}")
                else:
                    logger.warning(f"No email addresses found for company {company.company_id}")

            except Exception as e:
                logger.error(f"Failed to send warning to company {company.company_id}: {str(e)}")


def send_performance_alert(company_id, alert_type, message, data=None):
    """Send performance alerts to company dashboard"""
    try:
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'company_dashboard_{company_id}',
                {
                    'type': 'alert_notification',
                    'alert_type': alert_type,
                    'message': message,
                    'data': data or {}
                }
            )
    except Exception as e:
        logger.error(f"Error sending performance alert: {e}")


def broadcast_company_update(company_id, update_data):
    """Broadcast general company updates"""
    try:
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'company_dashboard_{company_id}',
                {
                    'type': 'dashboard_update',
                    'data': update_data
                }
            )
    except Exception as e:
        logger.error(f"Error broadcasting company update: {e}")


@shared_task
def send_expiration_notification(company_id):
    """Send email notification for expired companies"""
    try:
        # Query company from public schema
        company = Company.objects.get(company_id=company_id)

        # Switch to tenant context to query users
        with tenant_context(company):
            # Get company admins to notify
            admins = CustomUser.objects.filter(
                company=company,
                company_admin=True,
                is_active=True,
                is_hidden=False,
                email__isnull=False
            ).exclude(email='')

            if not admins.exists():
                logger.warning(f"No admins found to notify for expired company: {company.name}")
                return

            # Prepare email content
            subject = f"Account Expired - {company.trading_name or company.name}"

            context = {
                'company': company,
                'company_name': company.trading_name or company.name,
                'expiry_date': company.trial_ends_at or company.subscription_ends_at,
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@primefocusug.tech'),
                'login_url': getattr(settings, 'FRONTEND_URL', 'https://primefocusug.tech') + '/login/',
                'renewal_url': getattr(settings, 'FRONTEND_URL', 'https://primefocusug.tech') + '/billing/',
                'site_name': getattr(settings, 'SITE_NAME', 'Your Business Platform'),
                'year': timezone.now().year,
            }

            # Render email templates
            html_content = render_to_string('emails/company_expired.html', context)
            text_content = render_to_string('emails/company_expired.txt', context)

            # Send to all admins
            recipient_list = list(admins.values_list('email', flat=True))

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            to=recipient_list
        )
        msg.attach_alternative(html_content, "text/html")

        # Add company branding if available
        if hasattr(company, 'logo') and company.logo:
            try:
                with open(company.logo.path, 'rb') as f:
                    msg.attach('logo.png', f.read(), 'image/png')
                    msg.mixed_subtype = 'related'
            except Exception as logo_error:
                logger.warning(f"Could not attach company logo: {logo_error}")

        msg.send()

        # Send WebSocket notification
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'company_dashboard_{company.company_id}',
                {
                    'type': 'alert_notification',
                    'alert_type': 'account_expired',
                    'message': 'Your account has expired. Please renew to continue using the service.',
                    'data': {
                        'expiry_date': (company.trial_ends_at or company.subscription_ends_at).isoformat() if (
                                company.trial_ends_at or company.subscription_ends_at) else None,
                        'renewal_required': True
                    }
                }
            )

        logger.info(f"Expiration notification sent to {len(recipient_list)} recipients for company: {company.name}")

        # Update company last notification timestamp if field exists
        if hasattr(company, 'last_notification_sent'):
            company.last_notification_sent = timezone.now()
            company.save(update_fields=['last_notification_sent'])

    except Company.DoesNotExist:
        logger.error(f"Company not found for expiration notification: {company_id}")
    except Exception as e:
        logger.error(f"Error sending expiration notification for company {company_id}: {e}")


@shared_task
def send_suspension_notification(company_id, reason="Payment overdue"):
    """Send email notification for suspended companies"""
    try:
        # Query company from public schema
        company = Company.objects.get(company_id=company_id)

        # Switch to tenant context to query users
        with tenant_context(company):
            # Get company admins to notify
            admins = CustomUser.objects.filter(
                company=company,
                company_admin=True,
                is_active=True,
                is_hidden=False,
                email__isnull=False
            ).exclude(email='')

            if not admins.exists():
                logger.warning(f"No admins found to notify for suspended company: {company.name}")
                return

            # Prepare email content
            subject = f"Account Suspended - {company.trading_name or company.name}"

            context = {
                'company': company,
                'company_name': company.trading_name or company.name,
                'suspension_reason': reason,
                'suspension_date': timezone.now().date(),
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@example.com'),
                'support_phone': getattr(settings, 'SUPPORT_PHONE', '+1-234-567-8900'),
                'login_url': getattr(settings, 'FRONTEND_URL', 'https://yoursite.com') + '/login/',
                'billing_url': getattr(settings, 'FRONTEND_URL', 'https://yoursite.com') + '/billing/',
                'site_name': getattr(settings, 'SITE_NAME', 'Your Business Platform'),
                'year': timezone.now().year,
            }

            # Render email templates
            html_content = render_to_string('emails/company_suspended.html', context)
            text_content = render_to_string('emails/company_suspended.txt', context)

            # Send to all admins
            recipient_list = list(admins.values_list('email', flat=True))

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            to=recipient_list
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()

        # Send WebSocket notification
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'company_dashboard_{company.company_id}',
                {
                    'type': 'alert_notification',
                    'alert_type': 'account_suspended',
                    'message': f'Your account has been suspended: {reason}',
                    'data': {
                        'suspension_reason': reason,
                        'suspension_date': timezone.now().isoformat(),
                        'action_required': True
                    }
                }
            )

        logger.info(f"Suspension notification sent to {len(recipient_list)} recipients for company: {company.name}")

        # Update company last notification timestamp if field exists
        if hasattr(company, 'last_notification_sent'):
            company.last_notification_sent = timezone.now()
            company.save(update_fields=['last_notification_sent'])

    except Company.DoesNotExist:
        logger.error(f"Company not found for suspension notification: {company_id}")
    except Exception as e:
        logger.error(f"Error sending suspension notification for company {company_id}: {e}")


@shared_task
def send_trial_ending_notification(company_id, days_left):
    """Send notification when trial is ending soon"""
    try:
        # Query company from public schema
        company = Company.objects.get(company_id=company_id)

        if not company.is_trial:
            return  # Not a trial company

        # Switch to tenant context to query users
        with tenant_context(company):
            # Get company admins
            admins = CustomUser.objects.filter(
                company=company,
                company_admin=True,
                is_active=True,
                is_hidden=False,
                email__isnull=False
            ).exclude(email='')

            if not admins.exists():
                return

            subject = f"Trial Ending Soon - {company.trading_name or company.name}"

            context = {
                'company': company,
                'company_name': company.trading_name or company.name,
                'days_left': days_left,
                'trial_end_date': company.trial_ends_at,
                'upgrade_url': getattr(settings, 'FRONTEND_URL', 'https://yoursite.com') + '/upgrade/',
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@example.com'),
                'site_name': getattr(settings, 'SITE_NAME', 'Your Business Platform'),
                'year': timezone.now().year,
            }

            html_content = render_to_string('emails/trial_ending.html', context)
            text_content = render_to_string('emails/trial_ending.txt', context)

            recipient_list = list(admins.values_list('email', flat=True))

        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@example.com'),
            to=recipient_list
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()

        # Send WebSocket notification
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'company_dashboard_{company.company_id}',
                {
                    'type': 'alert_notification',
                    'alert_type': 'trial_ending',
                    'message': f'Your trial ends in {days_left} days. Upgrade to continue using the service.',
                    'data': {
                        'days_left': days_left,
                        'trial_end_date': company.trial_ends_at.isoformat() if company.trial_ends_at else None,
                        'upgrade_required': True
                    }
                }
            )

        logger.info(f"Trial ending notification sent for company: {company.name}")

    except Company.DoesNotExist:
        logger.error(f"Company not found for trial ending notification: {company_id}")
    except Exception as e:
        logger.error(f"Error sending trial ending notification: {e}")


@shared_task
def check_trial_expirations():
    """Check for companies with trials ending soon and send notifications"""
    try:
        today = timezone.now().date()

        # Companies with trials ending in 7 days (public schema query)
        seven_days_from_now = today + timedelta(days=7)
        companies_7_days = Company.objects.filter(
            is_trial=True,
            trial_ends_at=seven_days_from_now,
            status='TRIAL'
        )

        for company in companies_7_days:
            send_trial_ending_notification.delay(company.company_id, 7)

        # Companies with trials ending in 3 days
        three_days_from_now = today + timedelta(days=3)
        companies_3_days = Company.objects.filter(
            is_trial=True,
            trial_ends_at=three_days_from_now,
            status='TRIAL'
        )

        for company in companies_3_days:
            send_trial_ending_notification.delay(company.company_id, 3)

        # Companies with trials ending tomorrow
        tomorrow = today + timedelta(days=1)
        companies_tomorrow = Company.objects.filter(
            is_trial=True,
            trial_ends_at=tomorrow,
            status='TRIAL'
        )

        for company in companies_tomorrow:
            send_trial_ending_notification.delay(company.company_id, 1)

        # Companies with expired trials
        expired_companies = Company.objects.filter(
            is_trial=True,
            trial_ends_at__lt=today,
            status='TRIAL'
        )

        for company in expired_companies:
            # Update status and send expiration notification
            company.status = 'EXPIRED'
            company.save(update_fields=['status'])
            send_expiration_notification.delay(company.company_id)

        logger.info(
            f"Processed trial expiration checks: 7d={companies_7_days.count()}, 3d={companies_3_days.count()}, 1d={companies_tomorrow.count()}, expired={expired_companies.count()}")

    except Exception as e:
        logger.error(f"Error checking trial expirations: {e}")


@shared_task
def check_subscription_expirations():
    """Check for companies with subscriptions ending soon"""
    try:
        today = timezone.now().date()

        # Companies with subscriptions ending in 7 days (public schema query)
        seven_days_from_now = today + timedelta(days=7)
        companies_7_days = Company.objects.filter(
            is_trial=False,
            subscription_ends_at=seven_days_from_now,
            status='ACTIVE'
        )

        for company in companies_7_days:
            # Send renewal reminder
            send_renewal_reminder.delay(company.company_id, 7)

        # Companies with expired subscriptions
        expired_companies = Company.objects.filter(
            subscription_ends_at__lt=today,
            status='ACTIVE'
        )

        for company in expired_companies:
            company.status = 'EXPIRED'
            company.save(update_fields=['status'])
            send_expiration_notification.delay(company.company_id)

        logger.info(
            f"Processed subscription expiration checks: 7d={companies_7_days.count()}, expired={expired_companies.count()}")

    except Exception as e:
        logger.error(f"Error checking subscription expirations: {e}")


@shared_task
def send_renewal_reminder(company_id, days_left):
    """Send subscription renewal reminder"""
    try:
        # Query company from public schema
        company = Company.objects.get(company_id=company_id)

        # Switch to tenant context to query users
        with tenant_context(company):
            admins = CustomUser.objects.filter(
                company=company,
                company_admin=True,
                is_active=True,
                is_hidden=False,
                email__isnull=False
            ).exclude(email='')

            if not admins.exists():
                return f"No admins found for company {company_id}"

            subject = f"Subscription Renewal Required - {company.trading_name or company.name}"

            context = {
                'company': company,
                'company_name': company.trading_name or company.name,
                'days_left': days_left,
                'renewal_date': company.subscription_ends_at,
                'billing_url': getattr(settings, 'FRONTEND_URL', 'https://yoursite.com') + '/billing/',
                'support_email': getattr(settings, 'SUPPORT_EMAIL', 'support@example.com'),
                'site_name': getattr(settings, 'SITE_NAME', 'Your Business Platform'),
                'year': timezone.now().year,
            }

            # Render both HTML and plain text email content
            html_content = render_to_string('emails/renewal_reminder.html', context)
            text_content = render_to_string('emails/renewal_reminder.txt', context)

            recipient_list = list(admins.values_list('email', flat=True))

        # Build the email (outside tenant context)
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'no-reply@yoursite.com'),
            to=recipient_list
        )
        msg.attach_alternative(html_content, "text/html")
        msg.send()

        # Send WebSocket notification
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f'company_dashboard_{company.company_id}',
                {
                    'type': 'alert_notification',
                    'alert_type': 'renewal_reminder',
                    'message': f'Your subscription expires in {days_left} days. Please renew to continue service.',
                    'data': {
                        'days_left': days_left,
                        'renewal_date': company.subscription_ends_at.isoformat() if company.subscription_ends_at else None,
                        'renewal_required': True
                    }
                }
            )

        logger.info(f"Renewal reminder sent for company: {company.name}")
        return f"Renewal reminder sent to {len(recipient_list)} admin(s) for company {company_id}"

    except Company.DoesNotExist:
        return f"Company with ID {company_id} does not exist"
    except Exception as e:
        error_msg = f"Error sending renewal reminder: {str(e)}"
        logger.error(error_msg)
        return error_msg


class DecimalEncoder(DjangoJSONEncoder):
    """Custom JSON encoder to handle Decimal types"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


@shared_task(name='company.tasks.send_periodic_analytics_update')
def send_periodic_analytics_update():
    """
    Send periodic analytics updates to all connected company dashboards
    """
    try:
        channel_layer = get_channel_layer()
        # Query companies from public schema
        companies = Company.objects.filter(is_active=True)
        successful_updates = 0
        failed_updates = 0

        for company in companies:
            try:
                # Calculate metrics within tenant context
                metrics = calculate_company_metrics(company)

                # Only broadcast if metrics were calculated successfully
                if 'error' not in metrics:
                    # Broadcast outside tenant context (WebSocket operations)
                    room_group_name = f'company_dashboard_{company.company_id}'
                    async_to_sync(channel_layer.group_send)(
                        room_group_name,
                        {
                            'type': 'dashboard_update',
                            'data': metrics
                        }
                    )
                    successful_updates += 1
                else:
                    failed_updates += 1
                    logger.warning(
                        f"Skipped broadcasting for company {company.company_id} due to metrics calculation error")

            except Exception as company_error:
                failed_updates += 1
                logger.error(
                    f"Error processing company {company.company_id}: {company_error}"
                )
                continue

        return f"Updated analytics for {successful_updates} companies, {failed_updates} failed"

    except Exception as e:
        logger.error(f"Error in send_periodic_analytics_update: {e}")
        return f"Error: {str(e)}"


def calculate_company_metrics(company):
    """Calculate real-time metrics for a company"""
    try:
        # Check if company has a valid schema first
        if not company.schema_name or company.schema_name == 'public':
            logger.warning(f"Company {company.company_id} has invalid schema name: {company.schema_name}")
            return {
                'company_id': company.company_id,
                'today_revenue': 0.0,
                'today_sales_count': 0,
                'recent_activities': [],
                'inventory_alerts': {
                    'low_stock_items': 0,
                    'out_of_stock_items': 0
                },
                'active_users_count': 0,
                'timestamp': timezone.now().isoformat(),
                'schema_warning': f"Invalid schema: {company.schema_name}"
            }

        # All database queries MUST be within tenant context
        with tenant_context(company):
            # Test if the schema has required tables by doing a simple query
            try:
                # Quick test to see if Sale table exists and is accessible
                Sale.objects.exists()
            except Exception as schema_error:
                logger.error(f"Schema validation failed for company {company.company_id}: {schema_error}")
                return {
                    'company_id': company.company_id,
                    'today_revenue': 0.0,
                    'today_sales_count': 0,
                    'recent_activities': [],
                    'inventory_alerts': {
                        'low_stock_items': 0,
                        'out_of_stock_items': 0
                    },
                    'active_users_count': 0,
                    'timestamp': timezone.now().isoformat(),
                    'error': f"Schema not ready: {str(schema_error)}"
                }

            now = timezone.now()
            today = now.date()

            # Get all stores for the company (with error handling)
            try:
                all_stores = Store.objects.filter(company=company)
                store_ids = all_stores.values_list('id', flat=True)
            except Exception as store_error:
                logger.error(f"Error getting stores for company {company.company_id}: {store_error}")
                store_ids = []

            # Current day sales (with error handling)
            try:
                if store_ids:
                    today_sales = Sale.objects.filter(
                        store_id__in=store_ids,
                        created_at__date=today,
                        is_voided=False,
                        status__in=['COMPLETED', 'PAID']
                    ).aggregate(
                        revenue=Sum('total_amount'),
                        count=Count('id')
                    )
                else:
                    today_sales = {'revenue': 0, 'count': 0}
            except Exception as sales_error:
                logger.error(f"Error calculating today's sales for company {company.company_id}: {sales_error}")
                today_sales = {'revenue': 0, 'count': 0}

            # Recent activity (last hour) with error handling
            recent_activities = []
            try:
                if store_ids:
                    hour_ago = now - timedelta(hours=1)

                    # Recent sales
                    recent_sales = Sale.objects.filter(
                        store_id__in=store_ids,
                        created_at__gte=hour_ago,
                        is_voided=False,
                        status__in=['COMPLETED', 'PAID']
                    ).select_related('store__company').order_by('-created_at')[:5]

                    for sale in recent_sales:
                        recent_activities.append({
                            'type': 'sale',
                            'description': f"Sale of {float(sale.total_amount)} at {sale.store.name}",
                            'timestamp': sale.created_at.isoformat(),
                            'amount': float(sale.total_amount),
                            'store_name': sale.store.name,
                            'branch_name': sale.store.company.name,
                            'status': sale.status,  # Added status to response
                            'document_type': sale.document_type  # Added document type
                        })

                    # Recent device activities
                    try:
                        recent_logs = DeviceOperatorLog.objects.filter(
                            device__store__in=all_stores,
                            timestamp__gte=hour_ago
                        ).select_related('user', 'device__store__company').order_by('-timestamp')[:3]

                        for log in recent_logs:
                            recent_activities.append({
                                'type': 'device_activity',
                                'description': f"{log.user.get_full_name()} {log.action.replace('_', ' ').lower()}",
                                'timestamp': log.timestamp.isoformat(),
                                'user_name': log.user.get_full_name(),
                                'store_name': log.device.store.name,
                                'branch_name': log.device.store.company.name
                            })
                    except Exception:
                        # DeviceOperatorLog might not exist in all schemas
                        pass

                    # Sort activities by timestamp
                    recent_activities.sort(key=lambda x: x['timestamp'], reverse=True)

            except Exception as activity_error:
                logger.error(f"Error getting recent activities for company {company.company_id}: {activity_error}")

            # Inventory alerts with error handling
            low_stock_count = 0
            out_of_stock_count = 0
            try:
                if all_stores.exists():
                    low_stock_count = Stock.objects.filter(
                        store__in=all_stores,
                        quantity__lte=F('low_stock_threshold')
                    ).count()

                    out_of_stock_count = Stock.objects.filter(
                        store__in=all_stores,
                        quantity=0
                    ).count()
            except Exception as inventory_error:
                logger.error(f"Error getting inventory alerts for company {company.company_id}: {inventory_error}")

            # Active users count with error handling
            active_users_count = 0
            try:
                active_users_count = CustomUser.objects.filter(
                    company=company,
                    is_active=True,
                    last_activity_at__gte=now - timedelta(minutes=15)
                ).count()
            except Exception as user_error:
                logger.error(f"Error getting active users for company {company.company_id}: {user_error}")

            # ADDITIONAL METRICS: Today's invoices and receipts (optional)
            try:
                if store_ids:
                    # Today's invoices
                    today_invoices = Sale.objects.filter(
                        store_id__in=store_ids,
                        created_at__date=today,
                        is_voided=False,
                        document_type='INVOICE',
                        status__in=['COMPLETED', 'PAID', 'PARTIALLY_PAID', 'PENDING_PAYMENT']
                    ).aggregate(
                        revenue=Sum('total_amount'),
                        count=Count('id')
                    )

                    # Today's receipts
                    today_receipts = Sale.objects.filter(
                        store_id__in=store_ids,
                        created_at__date=today,
                        is_voided=False,
                        document_type='RECEIPT',
                        status__in=['COMPLETED', 'PAID']
                    ).aggregate(
                        revenue=Sum('total_amount'),
                        count=Count('id')
                    )
                else:
                    today_invoices = {'revenue': 0, 'count': 0}
                    today_receipts = {'revenue': 0, 'count': 0}
            except Exception:
                today_invoices = {'revenue': 0, 'count': 0}
                today_receipts = {'revenue': 0, 'count': 0}

            return {
                'company_id': company.company_id,
                'today_revenue': float(today_sales['revenue'] or 0),
                'today_sales_count': today_sales['count'] or 0,
                'today_invoice_revenue': float(today_invoices['revenue'] or 0),
                'today_invoice_count': today_invoices['count'] or 0,
                'today_receipt_revenue': float(today_receipts['revenue'] or 0),
                'today_receipt_count': today_receipts['count'] or 0,
                'recent_activities': recent_activities[:8],
                'inventory_alerts': {
                    'low_stock_items': low_stock_count,
                    'out_of_stock_items': out_of_stock_count
                },
                'active_users_count': active_users_count,
                'timestamp': now.isoformat()
            }

    except Exception as e:
        logger.error(f"Error calculating metrics for company {company.company_id}: {e}")
        return {
            'company_id': company.company_id,
            'today_revenue': 0.0,
            'today_sales_count': 0,
            'today_invoice_revenue': 0.0,
            'today_invoice_count': 0,
            'today_receipt_revenue': 0.0,
            'today_receipt_count': 0,
            'recent_activities': [],
            'inventory_alerts': {
                'low_stock_items': 0,
                'out_of_stock_items': 0
            },
            'active_users_count': 0,
            'timestamp': timezone.now().isoformat(),
            'error': str(e)
        }

@shared_task(name='company.tasks.send_branch_analytics_update')
def send_branch_analytics_update(branch_id):
    """Send analytics updates for a specific branch"""
    try:
        from stores.models import Store

        channel_layer = get_channel_layer()

        # Query branch from public schema first to get company reference
        branch = Store.objects.select_related('company').get(id=branch_id)

        # Switch to tenant context for tenant-specific queries
        with tenant_context(branch.company):
            stores = branch.stores.all()
            store_ids = stores.values_list('id', flat=True)

            now = timezone.now()
            today = now.date()

            # Today's metrics
            today_metrics = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date=today,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                revenue=Sum('total_amount'),
                sales_count=Count('id')
            )

            # Last hour metrics
            hour_ago = now - timedelta(hours=1)
            last_hour_sales = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__gte=hour_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).count()

            metrics = {
                'branch_id': branch.id,
                'today_revenue': float(today_metrics['revenue'] or 0),
                'today_sales_count': today_metrics['sales_count'] or 0,
                'last_hour_sales': last_hour_sales,
                'timestamp': now.isoformat()
            }

        # Send to branch analytics WebSocket group (outside tenant context)
        room_group_name = f'branch_analytics_{branch_id}'

        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {
                'type': 'analytics_update',
                'data': metrics
            }
        )

        # Also send to company dashboard
        company_room_group_name = f'company_dashboard_{branch.company.company_id}'

        async_to_sync(channel_layer.group_send)(
            company_room_group_name,
            {
                'type': 'branch_update',
                'branch_id': branch_id,
                'data': metrics
            }
        )

        return f"Updated analytics for branch {branch.name}"

    except Exception as e:
        logger.error(f"Error in send_branch_analytics_update: {e}")
        return f"Error: {str(e)}"


@shared_task(name='company.tasks.cleanup_old_analytics_data')
def cleanup_old_analytics_data():
    """Clean up old analytics data to prevent database bloat"""
    try:
        # Define cleanup thresholds
        ninety_days_ago = timezone.now() - timedelta(days=90)

        # Clean up old device logs for all companies
        companies = Company.objects.filter(is_active=True)
        total_deleted = 0

        for company in companies:
            with tenant_context(company):
                deleted_logs = DeviceOperatorLog.objects.filter(
                    timestamp__lt=ninety_days_ago
                ).delete()
                total_deleted += deleted_logs[0]  # Count of deleted objects

        return f"Cleaned up {total_deleted} old device logs across all companies"

    except Exception as e:
        logger.error(f"Error in cleanup_old_analytics_data: {e}")
        return f"Error: {str(e)}"


@shared_task(name='company.tasks.generate_daily_reports')
def generate_daily_reports():
    """Generate daily analytics reports for all companies"""
    try:
        companies = Company.objects.filter(is_active=True)
        reports_sent = 0

        for company in companies:
            try:
                # Generate report data within tenant context
                report_data = calculate_company_metrics(company)

                # Here you could save to database, send email, etc.
                # For now, just log the report
                logger.info(f"Daily report for {company.name}: {report_data}")

                reports_sent += 1

            except Exception as company_error:
                logger.error(f"Error generating report for {company.name}: {company_error}")
                continue

        return f"Generated daily reports for {reports_sent} companies"

    except Exception as e:
        logger.error(f"Error in generate_daily_reports: {e}")
        return f"Error: {str(e)}"


@shared_task(name='company.tasks.send_inventory_alerts')
def send_inventory_alerts():
    """Send inventory alerts for low stock and out of stock items"""
    try:
        channel_layer = get_channel_layer()
        companies = Company.objects.filter(is_active=True)

        for company in companies:
            try:
                # Switch to tenant context for tenant-specific queries
                with tenant_context(company):
                    all_stores = Store.objects.filter(company=company)

                    # Check for low stock items
                    low_stock_items = Stock.objects.filter(
                        store__in=all_stores,
                        quantity__lte=F('low_stock_threshold'),
                        quantity__gt=0
                    ).select_related('product', 'store')

                    # Check for out of stock items
                    out_of_stock_items = Stock.objects.filter(
                        store__in=all_stores,
                        quantity=0
                    ).select_related('product', 'store')

                    if low_stock_items.exists() or out_of_stock_items.exists():
                        alert_data = {
                            'low_stock_count': low_stock_items.count(),
                            'out_of_stock_count': out_of_stock_items.count(),
                            'low_stock_items': [
                                {
                                    'product_name': item.product.name,
                                    'store_name': item.store.name,
                                    'current_quantity': item.quantity,
                                    'threshold': item.low_stock_threshold
                                } for item in low_stock_items[:5]  # Limit to first 5
                            ],
                            'out_of_stock_items': [
                                {
                                    'product_name': item.product.name,
                                    'store_name': item.store.name
                                } for item in out_of_stock_items[:5]  # Limit to first 5
                            ]
                        }

                        # Send alert to company dashboard (outside tenant context)
                        room_group_name = f'company_dashboard_{company.company_id}'

                        async_to_sync(channel_layer.group_send)(
                            room_group_name,
                            {
                                'type': 'alert_notification',
                                'alert_type': 'inventory',
                                'message': f"Inventory alerts: {low_stock_items.count()} low stock, {out_of_stock_items.count()} out of stock",
                                'data': alert_data
                            }
                        )

            except Exception as company_error:
                logger.error(f"Error checking inventory for company {company.company_id}: {company_error}")
                continue

        return f"Checked inventory alerts for {companies.count()} companies"

    except Exception as e:
        logger.error(f"Error in send_inventory_alerts: {e}")
        return f"Error: {str(e)}"