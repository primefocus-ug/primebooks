from django.db import transaction
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
import logging
from django.db.models import Q
from django.contrib.auth import get_user_model
from django_tenants.utils import schema_context, get_tenant_model

from .models import (
    Notification, NotificationTemplate, NotificationPreference,
    NotificationCategory, NotificationLog, NotificationRule
)
User=get_user_model()
logger = logging.getLogger(__name__)


class NotificationService:
    """
    Central service for creating and sending notifications with tenant support
    """

    @staticmethod
    def get_tenant_schema(user=None, related_object=None):
        """Get tenant schema from user or related object"""
        try:
            # Try to get schema from related object first
            if related_object:
                if hasattr(related_object, 'tenant') and related_object.tenant:
                    return related_object.tenant.schema_name
                if hasattr(related_object, 'company') and related_object.company:
                    return related_object.company.schema_name
                if hasattr(related_object, 'store') and related_object.store:
                    if hasattr(related_object.store, 'company'):
                        return related_object.store.company.schema_name

            # Try to get from user
            if user:
                if hasattr(user, 'tenant') and user.tenant:
                    return user.tenant.schema_name
                if hasattr(user, 'company') and user.company:
                    return user.company.schema_name
                # Try to get from user's profile/staff relationships
                if hasattr(user, 'staff_profile'):
                    if hasattr(user.staff_profile, 'company'):
                        return user.staff_profile.company.schema_name

            # Fallback to current schema
            from django.db import connection
            schema = connection.schema_name
            if schema and schema != 'public':
                return schema

        except Exception as e:
            logger.error(f"Error getting tenant schema: {e}")

        return None

    @staticmethod
    def create_notification(
            recipient,
            title,
            message,
            notification_type='INFO',
            category=None,
            template=None,
            related_object=None,
            action_text='',
            action_url='',
            priority='MEDIUM',
            metadata=None,
            expires_at=None,
            channels=None,
            tenant_schema=None
    ):
        """Create a notification with tenant context"""

        if channels is None:
            channels = ['in_app']

        # Determine tenant schema
        schema_name = tenant_schema or NotificationService.get_tenant_schema(
            user=recipient,
            related_object=related_object
        )

        if not schema_name:
            logger.error("Cannot determine tenant schema for notification")
            return None

        try:
            with schema_context(schema_name):
                # Get or create user preferences
                prefs, _ = NotificationPreference.objects.get_or_create(
                    user=recipient,
                    defaults={
                        'email_enabled': True,
                        'push_enabled': True,
                        'in_app_enabled': True,
                    }
                )

                # Create notification FIRST
                notification = Notification.objects.create(
                    recipient=recipient,
                    category=category,
                    template=template,
                    notification_type=notification_type,
                    title=title,
                    message=message,
                    action_text=action_text,
                    action_url=action_url or '',
                    priority=priority,
                    metadata=metadata or {},
                    expires_at=expires_at,
                    tenant_id=schema_name,
                )

                # Link related object - FIX FOR CHARFIELD PRIMARY KEYS
                if related_object:
                    from django.contrib.contenttypes.models import ContentType

                    # Get content type
                    content_type = ContentType.objects.get_for_model(related_object)

                    # Get object ID - ensure it's a string for CharField primary keys
                    object_id = str(related_object.pk)

                    # Update the notification with content type and object_id
                    notification.content_type = content_type
                    notification.object_id = object_id

                    # Use save() instead of update_fields to ensure proper saving
                    notification.save()

                # Send through channels
                for channel in channels:
                    if prefs.should_send_notification(category=category, channel=channel):
                        NotificationService._send_via_channel(notification, channel, schema_name)

                return notification

        except Exception as e:
            logger.error(f"Error creating notification: {e}", exc_info=True)
            return None

    @staticmethod
    def create_from_template(
            event_type,
            recipient,
            context,
            related_object=None,
            priority=None,
            tenant_schema=None
    ):
        """
        Create notification from template with tenant context

        Args:
            event_type: Template event type identifier
            recipient: User to receive notification
            context: Dictionary of context variables for template rendering
            related_object: Related model instance
            priority: Override template priority
            tenant_schema: Explicit tenant schema name

        Returns:
            Notification instance or None
        """

        # Determine tenant schema
        schema_name = tenant_schema or NotificationService.get_tenant_schema(
            user=recipient,
            related_object=related_object
        )

        if not schema_name:
            logger.error("Cannot determine tenant schema for template notification")
            return None

        try:
            with schema_context(schema_name):
                try:
                    template = NotificationTemplate.objects.get(
                        event_type=event_type,
                        is_active=True
                    )
                except NotificationTemplate.DoesNotExist:
                    logger.warning(f"No active template found for event_type: {event_type}")
                    return None

                # Render template
                rendered = template.render(context)

                # Determine channels
                channels = []
                if template.send_in_app:
                    channels.append('in_app')
                if template.send_email:
                    channels.append('email')
                if template.send_sms:
                    channels.append('sms')
                if template.send_push:
                    channels.append('push')

                # Create notification
                notification = NotificationService.create_notification(
                    recipient=recipient,
                    title=rendered['title'],
                    message=rendered['message'],
                    notification_type='INFO',
                    category=template.category,
                    template=template,
                    related_object=related_object,
                    action_text=template.action_text,
                    action_url=rendered.get('action_url', ''),
                    priority=priority or template.priority,
                    metadata={'rendered_context': context, 'event_type': event_type},
                    channels=channels,
                    tenant_schema=schema_name
                )

                # Send email if needed
                if notification and 'email' in channels and rendered.get('email_subject'):
                    NotificationService._send_email(
                        notification,
                        rendered['email_subject'],
                        rendered.get('email_body', rendered['message']),
                        schema_name
                    )

                return notification

        except Exception as e:
            logger.error(f"Error creating notification from template: {e}", exc_info=True)
            return None

    @staticmethod
    def _send_via_channel(notification, channel, schema_name):
        """Send notification through specific channel with tenant context"""
        try:
            if channel == 'in_app':
                NotificationService._send_in_app(notification, schema_name)
            elif channel == 'email':
                NotificationService._send_email(notification, schema_name=schema_name)
            elif channel == 'sms':
                NotificationService._send_sms(notification, schema_name)
            elif channel == 'push':
                NotificationService._send_push(notification, schema_name)
        except Exception as e:
            logger.error(f"Error sending notification via {channel}: {e}", exc_info=True)

    @staticmethod
    def _send_in_app(notification, schema_name):
        """Send in-app notification via WebSocket with tenant context"""
        with schema_context(schema_name):
            try:
                channel_layer = get_channel_layer()
                if channel_layer:
                    # Use schema-aware group name
                    group_name = f'notifications_{schema_name}_{notification.recipient.id}'

                    async_to_sync(channel_layer.group_send)(
                        group_name,
                        {
                            'type': 'notification_message',
                            'notification': {
                                'id': notification.id,
                                'title': notification.title,
                                'message': notification.message,
                                'notification_type': notification.notification_type,
                                'priority': notification.priority,
                                'action_text': notification.action_text,
                                'action_url': notification.action_url,
                                'created_at': notification.created_at.isoformat(),
                                'schema_name': schema_name
                            }
                        }
                    )

                notification.is_sent = True
                notification.sent_at = timezone.now()
                notification.save(update_fields=['is_sent', 'sent_at'])

                # Log delivery
                NotificationLog.objects.create(
                    notification=notification,
                    channel='in_app',
                    status='SENT',
                    sent_at=timezone.now()
                )

            except Exception as e:
                logger.error(f"Failed to send in-app notification: {e}", exc_info=True)
                NotificationLog.objects.create(
                    notification=notification,
                    channel='in_app',
                    status='FAILED',
                    error_message=str(e)
                )

    @staticmethod
    def _send_email(notification, subject=None, body=None, schema_name=None):
        """Send email notification with tenant context"""
        if not schema_name:
            schema_name = NotificationService.get_tenant_schema(user=notification.recipient)

        with schema_context(schema_name):
            try:
                subject = subject or notification.title
                body = body or notification.message
                recipient_email = notification.recipient.email

                if not recipient_email:
                    raise ValueError("Recipient has no email address")

                # Add tenant context to email subject
                tenant_subject = f"[{schema_name}] {subject}" if schema_name != 'public' else subject

                send_mail(
                    subject=tenant_subject,
                    message=body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[recipient_email],
                    fail_silently=False,
                )

                notification.sent_via_email = True
                notification.email_sent_at = timezone.now()
                notification.save(update_fields=['sent_via_email', 'email_sent_at'])

                # Log delivery
                NotificationLog.objects.create(
                    notification=notification,
                    channel='email',
                    status='SENT',
                    sent_at=timezone.now()
                )

            except Exception as e:
                logger.error(f"Failed to send email notification: {e}", exc_info=True)
                NotificationLog.objects.create(
                    notification=notification,
                    channel='email',
                    status='FAILED',
                    error_message=str(e)
                )

    @staticmethod
    def _send_sms(notification, schema_name):
        """Send SMS notification with tenant context"""
        with schema_context(schema_name):
            try:
                # TODO: Implement SMS sending logic
                # Example using a service like Twilio or AfricasTalking

                phone_number = getattr(notification.recipient, 'phone_number', None)
                if not phone_number:
                    raise ValueError("Recipient has no phone number")

                # Your SMS sending logic here
                # sms_service.send(phone_number, notification.message)

                notification.sent_via_sms = True
                notification.sms_sent_at = timezone.now()
                notification.save(update_fields=['sent_via_sms', 'sms_sent_at'])

                NotificationLog.objects.create(
                    notification=notification,
                    channel='sms',
                    status='SENT',
                    sent_at=timezone.now()
                )

            except Exception as e:
                logger.error(f"Failed to send SMS notification: {e}", exc_info=True)
                NotificationLog.objects.create(
                    notification=notification,
                    channel='sms',
                    status='FAILED',
                    error_message=str(e)
                )

    @staticmethod
    def _send_push(notification, schema_name):
        """Send push notification with tenant context"""
        with schema_context(schema_name):
            try:
                # TODO: Implement push notification logic
                # Example using Firebase Cloud Messaging or OneSignal

                # Your push notification logic here
                # push_service.send(notification.recipient.device_tokens, notification.title, notification.message)

                notification.sent_via_push = True
                notification.push_sent_at = timezone.now()
                notification.save(update_fields=['sent_via_push', 'push_sent_at'])

                NotificationLog.objects.create(
                    notification=notification,
                    channel='push',
                    status='SENT',
                    sent_at=timezone.now()
                )

            except Exception as e:
                logger.error(f"Failed to send push notification: {e}", exc_info=True)
                NotificationLog.objects.create(
                    notification=notification,
                    channel='push',
                    status='FAILED',
                    error_message=str(e)
                )

    @staticmethod
    def mark_all_as_read(user, tenant_schema=None):
        """Mark all notifications as read for a user with tenant context"""
        schema_name = tenant_schema or NotificationService.get_tenant_schema(user=user)

        if not schema_name:
            logger.error("Cannot determine tenant schema for mark_all_as_read")
            return 0

        with schema_context(schema_name):
            try:
                count = Notification.objects.filter(
                    recipient=user,
                    is_read=False
                ).update(
                    is_read=True,
                    read_at=timezone.now()
                )
                return count
            except Exception as e:
                logger.error(f"Error marking all as read: {e}", exc_info=True)
                return 0

    @staticmethod
    def get_unread_count(user, category=None, tenant_schema=None):
        """Get unread notification count with tenant context"""
        schema_name = tenant_schema or NotificationService.get_tenant_schema(user=user)

        if not schema_name:
            logger.error("Cannot determine tenant schema for get_unread_count")
            return 0

        with schema_context(schema_name):
            try:
                queryset = Notification.objects.filter(
                    recipient=user,
                    is_read=False,
                    is_dismissed=False
                )

                if category:
                    queryset = queryset.filter(category=category)

                return queryset.count()
            except Exception as e:
                logger.error(f"Error getting unread count: {e}", exc_info=True)
                return 0

    @staticmethod
    def get_recent_notifications(user, limit=10, category=None, tenant_schema=None):
        """Get recent notifications for user with tenant context"""
        schema_name = tenant_schema or NotificationService.get_tenant_schema(user=user)

        if not schema_name:
            logger.error("Cannot determine tenant schema for get_recent_notifications")
            return []

        with schema_context(schema_name):
            try:
                queryset = Notification.objects.filter(
                    recipient=user,
                    is_dismissed=False
                ).select_related('category', 'template')

                if category:
                    queryset = queryset.filter(category=category)

                return list(queryset[:limit])
            except Exception as e:
                logger.error(f"Error getting recent notifications: {e}", exc_info=True)
                return []

    @staticmethod
    def retry_failed_notification(notification_log_id, tenant_schema=None):
        """Retry a failed notification"""
        if not tenant_schema:
            # Try to get schema from the log
            try:
                log = NotificationLog.objects.using('public').get(id=notification_log_id)
                tenant_schema = log.notification.tenant_id
            except NotificationLog.DoesNotExist:
                logger.error(f"NotificationLog {notification_log_id} not found")
                return False

        with schema_context(tenant_schema):
            try:
                log = NotificationLog.objects.get(id=notification_log_id)

                if not log.can_retry():
                    logger.warning(f"Cannot retry notification log {notification_log_id}")
                    return False

                # Increment retry count
                log.retry_count += 1
                log.status = 'PENDING'
                log.save(update_fields=['retry_count', 'status'])

                # Retry sending
                NotificationService._send_via_channel(
                    log.notification,
                    log.channel,
                    tenant_schema
                )

                return True

            except Exception as e:
                logger.error(f"Error retrying notification: {e}", exc_info=True)
                return False


# Domain-specific notification helpers with tenant context

class SalesNotifications:
    """Notifications for sales events with tenant support"""

    @staticmethod
    def notify_sale_completed(sale):
        """Notify when sale is completed"""
        try:
            # Get tenant schema from sale
            schema_name = sale.store.company.schema_name

            # Get the appropriate document number based on type
            if sale.document_type == 'RECEIPT' and hasattr(sale, 'receipt_detail'):
                doc_number = sale.receipt_detail.receipt_number
            else:
                doc_number = sale.document_number

            # Notify cashier
            if sale.created_by:
                NotificationService.create_from_template(
                    event_type='sale_completed',
                    recipient=sale.created_by,
                    context={
                        'sale_id': sale.id,
                        'document_number': doc_number,  # Changed from invoice_number
                        'invoice_number': doc_number,  # Keep for backward compatibility in templates
                        'total_amount': f'{sale.total_amount:,.0f}',
                        'customer_name': sale.customer.name if sale.customer else 'Walk-in',
                        'store_name': sale.store.name,
                        'document_type': sale.document_type.lower(),
                        'document_type_display': sale.get_document_type_display(),
                    },
                    related_object=sale,
                    tenant_schema=schema_name
                )

            # Get high value threshold from settings or company settings
            high_value_threshold = getattr(settings, 'HIGH_VALUE_SALE_THRESHOLD', 1000000)
            if hasattr(sale.store.company, 'high_value_threshold'):
                high_value_threshold = sale.store.company.high_value_threshold

            # Notify store manager if high-value sale
            if sale.total_amount > high_value_threshold:
                manager = sale.store.manager
                if manager:
                    NotificationService.create_notification(
                        recipient=manager,
                        title='High-Value Sale Alert',
                        message=f'Large sale of UGX {sale.total_amount:,.0f} completed at {sale.store.name}',
                        notification_type='INFO',
                        priority='HIGH',
                        related_object=sale,
                        action_text='View Sale',
                        action_url=f'/sales/{sale.id}/',
                        tenant_schema=schema_name
                    )

        except Exception as e:
            logger.error(f"Error in notify_sale_completed: {e}", exc_info=True)

    @staticmethod
    def notify_efris_fiscalized(sale):
        """Notify when sale is fiscalized with EFRIS"""
        try:
            schema_name = sale.store.company.schema_name

            # Get the appropriate document number
            doc_number = sale.document_number

            if sale.created_by:
                NotificationService.create_from_template(
                    event_type='efris_fiscalized',
                    recipient=sale.created_by,
                    context={
                        'document_number': doc_number,  # Changed from invoice_number
                        'invoice_number': doc_number,  # Keep for backward compatibility
                        'fiscal_number': sale.efris_invoice_number,
                        'verification_code': sale.verification_code,
                        'document_type': sale.document_type.lower(),
                    },
                    related_object=sale,
                    priority='SUCCESS',
                    tenant_schema=schema_name
                )

        except Exception as e:
            logger.error(f"Error in notify_efris_fiscalized: {e}", exc_info=True)

    @staticmethod
    def notify_efris_failed(sale, error_message):
        """Notify when EFRIS fiscalization fails"""
        try:
            schema_name = sale.store.company.schema_name

            # Get the appropriate document number
            doc_number = sale.document_number

            # Notify cashier
            if sale.created_by:
                NotificationService.create_notification(
                    recipient=sale.created_by,
                    title='EFRIS Fiscalization Failed',
                    message=f'{sale.get_document_type_display()} {doc_number} failed to fiscalize: {error_message}',
                    notification_type='ERROR',
                    priority='HIGH',
                    related_object=sale,
                    action_text='Retry',
                    action_url=f'/sales/{sale.id}/fiscalize/',
                    tenant_schema=schema_name
                )

            # Notify company admins
            with schema_context(schema_name):
                company_admins = sale.store.company.staff.filter(
                    is_staff=True
                ).only('id', 'email', 'first_name', 'last_name')

                for admin in company_admins:
                    NotificationService.create_notification(
                        recipient=admin,
                        title='EFRIS Error - Action Required',
                        message=f'EFRIS fiscalization failed at {sale.store.name}',
                        notification_type='ERROR',
                        priority='URGENT',
                        related_object=sale,
                        tenant_schema=schema_name
                    )

        except Exception as e:
            logger.error(f"Error in notify_efris_failed: {e}", exc_info=True)

    @staticmethod
    def notify_sale_voided(sale, voided_by, reason):
        """Notify when a sale is voided"""
        try:
            schema_name = sale.store.company.schema_name

            # Get the appropriate document number
            doc_number = sale.document_number

            # Notify the original cashier
            if sale.created_by and sale.created_by != voided_by:
                NotificationService.create_notification(
                    recipient=sale.created_by,
                    title='Sale Voided',
                    message=f'Your {sale.get_document_type_display().lower()} {doc_number} was voided by {voided_by.get_full_name()}. Reason: {reason}',
                    notification_type='WARNING',
                    priority='MEDIUM',
                    related_object=sale,
                    tenant_schema=schema_name
                )

            # Notify store manager
            manager = sale.store.manager
            if manager and manager != voided_by:
                NotificationService.create_notification(
                    recipient=manager,
                    title='Sale Voided',
                    message=f'{sale.get_document_type_display()} {doc_number} voided at {sale.store.name}',
                    notification_type='WARNING',
                    priority='HIGH',
                    related_object=sale,
                    tenant_schema=schema_name
                )

        except Exception as e:
            logger.error(f"Error in notify_sale_voided: {e}", exc_info=True)

    @staticmethod
    def notify_sale_refunded(sale, refunded_by):
        """Notify when a sale is refunded"""
        try:
            schema_name = sale.store.company.schema_name

            # Get the appropriate document number
            doc_number = sale.document_number

            # Notify the original cashier
            if sale.created_by and sale.created_by != refunded_by:
                NotificationService.create_notification(
                    recipient=sale.created_by,
                    title='Sale Refunded',
                    message=f'Your {sale.get_document_type_display().lower()} {doc_number} was refunded by {refunded_by.get_full_name()}',
                    notification_type='INFO',
                    priority='MEDIUM',
                    related_object=sale,
                    tenant_schema=schema_name
                )

            # Notify store manager for large refunds
            if sale.total_amount > 500000:  # UGX 500,000 threshold
                manager = sale.store.manager
                if manager and manager != refunded_by:
                    NotificationService.create_notification(
                        recipient=manager,
                        title='Large Refund Processed',
                        message=f'Refund of UGX {sale.total_amount:,.0f} processed at {sale.store.name}',
                        notification_type='WARNING',
                        priority='HIGH',
                        related_object=sale,
                        tenant_schema=schema_name
                    )

        except Exception as e:
            logger.error(f"Error in notify_sale_refunded: {e}", exc_info=True)


class InventoryNotifications:
    """Notifications for inventory events with tenant support"""

    @staticmethod
    def notify_low_stock(product, stock_item):
        """Notify when product stock is low - only to high-priority users"""
        try:
            schema_name = stock_item.store.company.schema_name

            # Get high-priority recipients
            from django.contrib.auth import get_user_model
            User = get_user_model()

            recipients = User.objects.filter(
                Q(is_superuser=True) |
                Q(primary_role__priority__gte=90)
            ).filter(is_active=True)

            # Create notifications for each high-priority recipient
            for recipient in recipients:
                NotificationService.create_from_template(
                    event_type='low_stock',
                    recipient=recipient,
                    context={
                        'product_name': product.name,
                        'current_quantity': stock_item.quantity,
                        'threshold': stock_item.low_stock_threshold,
                        'store_name': stock_item.store.name,
                    },
                    related_object=product,
                    priority='WARNING',
                    tenant_schema=schema_name
                )

        except Exception as e:
            logger.error(f"Error in notify_low_stock: {str(e)}", exc_info=True)

    @staticmethod
    def notify_out_of_stock(product, stock_item):
        """Notify when product is out of stock - only to high-priority users"""
        try:
            schema_name = stock_item.store.company.schema_name

            # Get high-priority recipients
            from django.contrib.auth import get_user_model
            User = get_user_model()

            recipients = User.objects.filter(
                Q(is_superuser=True) |
                Q(primary_role__priority__gte=90)
            ).filter(is_active=True)

            # Create notifications for each high-priority recipient
            for recipient in recipients:
                NotificationService.create_from_template(
                    event_type='out_of_stock',
                    recipient=recipient,
                    context={
                        'product_name': product.name,
                        'store_name': stock_item.store.name,
                    },
                    related_object=product,
                    priority='HIGH',
                    tenant_schema=schema_name
                )

        except Exception as e:
            logger.error(f"Error in notify_out_of_stock: {str(e)}", exc_info=True)

class CompanyNotifications:
    """Notifications for company/subscription events with tenant support"""

    @staticmethod
    def notify_subscription_expiring(company, days_remaining):
        """Notify when subscription is expiring"""
        try:
            schema_name = company.schema_name

            with schema_context(schema_name):
                # Notify company admins
                admins = company.staff.filter(is_staff=True).only(
                    'id', 'email', 'first_name', 'last_name'
                )

                for admin in admins:
                    NotificationService.create_from_template(
                        event_type='subscription_expiring',
                        recipient=admin,
                        context={
                            'company_name': company.name,
                            'days_remaining': days_remaining,
                            'expiry_date': company.subscription_ends_at.strftime('%Y-%m-%d'),
                        },
                        related_object=company,
                        priority='URGENT',
                        tenant_schema=schema_name
                    )

        except Exception as e:
            logger.error(f"Error in notify_subscription_expiring: {e}", exc_info=True)

    @staticmethod
    def notify_trial_ending(company, days_remaining):
        """Notify when trial is ending"""
        try:
            schema_name = company.schema_name

            with schema_context(schema_name):
                admins = company.staff.filter(is_staff=True).only(
                    'id', 'email', 'first_name', 'last_name'
                )

                for admin in admins:
                    NotificationService.create_from_template(
                        event_type='trial_ending',
                        recipient=admin,
                        context={
                            'company_name': company.name,
                            'days_remaining': days_remaining,
                            'trial_ends': company.trial_ends_at.strftime('%Y-%m-%d'),
                        },
                        related_object=company,
                        priority='HIGH',
                        tenant_schema=schema_name
                    )

        except Exception as e:
            logger.error(f"Error in notify_trial_ending: {e}", exc_info=True)


class SecurityNotifications:
    """Notifications for security events with tenant support"""

    @staticmethod
    def notify_suspicious_activity(user, alert):
        """Notify user of suspicious activity"""
        try:
            schema_name = NotificationService.get_tenant_schema(user=user)

            if schema_name:
                NotificationService.create_notification(
                    recipient=user,
                    title='Suspicious Activity Detected',
                    message=f'Unusual activity detected: {alert.description}',
                    notification_type='ALERT',
                    priority='URGENT',
                    related_object=alert,
                    action_text='Review Activity',
                    action_url=f'/security/alerts/{alert.id}/',
                    channels=['in_app', 'email'],
                    tenant_schema=schema_name
                )

        except Exception as e:
            logger.error(f"Error in notify_suspicious_activity: {e}", exc_info=True)

    @staticmethod
    def notify_new_device_login(user, session):
        """Notify user of new device login"""
        try:
            schema_name = NotificationService.get_tenant_schema(user=user)

            if schema_name:
                NotificationService.create_notification(
                    recipient=user,
                    title='New Device Login',
                    message=f'Login detected from {session.browser_name} on {session.os_name}',
                    notification_type='INFO',
                    priority='MEDIUM',
                    related_object=session,
                    action_text='View Details',
                    action_url='/account/security/',
                    channels=['in_app', 'email'],
                    tenant_schema=schema_name
                )

        except Exception as e:
            logger.error(f"Error in notify_new_device_login: {e}", exc_info=True)


class MessagingNotifications:
    """Notifications for messaging events with tenant support"""

    @staticmethod
    def notify_new_message(recipient, message, conversation):
        """Notify user of new message"""
        try:
            schema_name = NotificationService.get_tenant_schema(user=recipient)

            if schema_name:
                NotificationService.create_notification(
                    recipient=recipient,
                    title=f'New message from {message.sender.get_full_name()}',
                    message=f'in {conversation.name or "Direct message"}',
                    notification_type='INFO',
                    priority='MEDIUM',
                    related_object=message,
                    action_text='View Message',
                    action_url=f'/messages/conversation/{conversation.id}/',
                    channels=['in_app', 'push'],
                    tenant_schema=schema_name
                )

        except Exception as e:
            logger.error(f"Error in notify_new_message: {e}", exc_info=True)

    @staticmethod
    def notify_mention(recipient, message, conversation):
        """Notify user when mentioned in message"""
        try:
            schema_name = NotificationService.get_tenant_schema(user=recipient)

            if schema_name:
                NotificationService.create_from_template(
                    event_type='message_mention',
                    recipient=recipient,
                    context={
                        'sender_name': message.sender.get_full_name(),
                        'conversation_name': conversation.name or 'conversation',
                    },
                    related_object=message,
                    priority='HIGH',
                    tenant_schema=schema_name
                )

        except Exception as e:
            logger.error(f"Error in notify_mention: {e}", exc_info=True)


# Utility function to send notifications across all tenant schemas
class CrossTenantNotifications:
    """Send notifications across multiple tenant schemas"""

    @staticmethod
    def notify_all_companies(event_type, context_generator, user_filter=None):
        """
        Send notification to all companies

        Args:
            event_type: Template event type
            context_generator: Function that takes company and user, returns context dict
            user_filter: Optional Q object or dict for filtering users within each company
        """
        try:
            TenantModel = get_tenant_model()

            for tenant in TenantModel.objects.exclude(schema_name='public'):
                try:
                    with schema_context(tenant.schema_name):
                        # Get users to notify
                        users = User.objects.filter(is_active=True)

                        if user_filter:
                            if hasattr(user_filter, 'resolve_expression'):  # Q object
                                users = users.filter(user_filter)
                            else:  # dict
                                users = users.filter(**user_filter)

                        for user in users:
                            try:
                                context = context_generator(tenant, user)
                                NotificationService.create_from_template(
                                    event_type=event_type,
                                    recipient=user,
                                    context=context,
                                    tenant_schema=tenant.schema_name
                                )
                            except Exception as e:
                                logger.error(
                                    f"Error sending notification to user {user.id} in tenant {tenant.schema_name}: {e}"
                                )

                except Exception as e:
                    logger.error(f"Error processing tenant {tenant.schema_name}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error in notify_all_companies: {e}", exc_info=True)