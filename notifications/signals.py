from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from django_tenants.utils import schema_context, get_public_schema_name
from django.db import connection
import logging

from .services import (
    NotificationService,
    SalesNotifications,
    InventoryNotifications,
    CompanyNotifications,
    SecurityNotifications,
    MessagingNotifications
)

logger = logging.getLogger(__name__)

# Track previous state for comparison
_pre_save_state = {}


def should_process_signal():
    """
    Determine if we should process signals in the current schema context.
    Only process in tenant schemas, not in public schema.
    """
    current_schema = connection.schema_name
    public_schema = get_public_schema_name()

    return current_schema and current_schema != public_schema


def with_tenant_safety(signal_handler):
    """
    Decorator to make signal handlers tenant-safe.
    Only executes the handler when in a tenant schema context.
    """

    def wrapper(sender, instance, **kwargs):
        if not should_process_signal():
            logger.debug(f"Skipping {signal_handler.__name__} in schema: {connection.schema_name}")
            return

        try:
            return signal_handler(sender, instance, **kwargs)
        except Exception as e:
            logger.error(f"Error in {signal_handler.__name__}: {e}", exc_info=True)

    return wrapper


# ============= PRE-SAVE HANDLERS (for state tracking) =============

@receiver(pre_save, sender='sales.Sale')
@with_tenant_safety
def track_sale_state(sender, instance, **kwargs):
    """Track sale state before save for comparison"""
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            _pre_save_state[f'sale_{instance.pk}'] = {
                'is_fiscalized': old_instance.is_fiscalized,
                'is_completed': old_instance.is_completed,
            }
        except sender.DoesNotExist:
            pass


@receiver(pre_save, sender='inventory.Stock')
@with_tenant_safety
def track_stock_state(sender, instance, **kwargs):
    """Track stock state before save"""
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            _pre_save_state[f'stock_{instance.pk}'] = {
                'quantity': old_instance.quantity,
                'was_low_stock': old_instance.is_low_stock if hasattr(old_instance, 'is_low_stock') else False,
            }
        except sender.DoesNotExist:
            pass


@receiver(pre_save, sender='company.Company')
def track_company_state(sender, instance, **kwargs):
    """Track company state before save - special handling for public schema"""
    # Company model is in public schema, so we don't use the tenant safety decorator
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            _pre_save_state[f'company_{instance.pk}'] = {
                'status': old_instance.status,
                'subscription_ends_at': old_instance.subscription_ends_at,
            }
        except sender.DoesNotExist:
            pass


@receiver(pre_save, sender='reports.GeneratedReport')
@with_tenant_safety
def track_report_state(sender, instance, **kwargs):
    """Track report state before save"""
    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)
            _pre_save_state[f'report_{instance.pk}'] = {
                'status': old_instance.status,
            }
        except sender.DoesNotExist:
            pass


# ============= SALES NOTIFICATIONS =============

@receiver(post_save, sender='sales.Sale')
@with_tenant_safety
def notify_sale_events(sender, instance, created, **kwargs):
    """Notify on sale events"""
    try:
        # Get tenant schema from sale
        schema_name = instance.store.company.schema_name

        with schema_context(schema_name):
            if created and instance.is_completed:
                # New completed sale
                SalesNotifications.notify_sale_completed(instance)

            elif not created:
                # Check for EFRIS fiscalization
                state_key = f'sale_{instance.pk}'
                old_state = _pre_save_state.get(state_key, {})

                if instance.is_fiscalized and not old_state.get('is_fiscalized', False):
                    # Just fiscalized
                    SalesNotifications.notify_efris_fiscalized(instance)

                # Clean up tracked state
                if state_key in _pre_save_state:
                    del _pre_save_state[state_key]

    except Exception as e:
        logger.error(f"Error in notify_sale_events: {e}", exc_info=True)


@receiver(post_save, sender='invoices.Invoice')
@with_tenant_safety
def notify_invoice_events(sender, instance, created, **kwargs):
    """Notify on invoice events"""
    try:
        if not created:
            return

        # Determine schema
        schema_name = None
        if hasattr(instance, 'sale') and instance.sale:
            schema_name = instance.sale.store.company.schema_name
        elif hasattr(instance, 'company'):
            schema_name = instance.company.schema_name

        if not schema_name:
            logger.warning("Cannot determine schema for invoice notification")
            return

        with schema_context(schema_name):
            # New invoice created
            if instance.sale and instance.sale.created_by:
                NotificationService.create_from_template(
                    event_type='invoice_created',
                    recipient=instance.sale.created_by,
                    context={
                        'invoice_number': instance.invoice_number,
                        'total_amount': f'{instance.total_amount:,.0f}',
                        'customer_name': instance.customer.name if instance.customer else 'N/A',
                    },
                    related_object=instance,
                    tenant_schema=schema_name
                )

    except Exception as e:
        logger.error(f"Error in notify_invoice_events: {e}", exc_info=True)


# ============= INVENTORY NOTIFICATIONS =============

@receiver(post_save, sender='inventory.Stock')
@with_tenant_safety
def notify_stock_levels(sender, instance, created, **kwargs):
    """Notify on stock level changes"""
    try:
        schema_name = instance.store.company.schema_name

        with schema_context(schema_name):
            if not created:
                state_key = f'stock_{instance.pk}'
                old_state = _pre_save_state.get(state_key, {})
                old_quantity = old_state.get('quantity', instance.quantity)

                # Check low stock (only if quantity decreased)
                if hasattr(instance, 'is_low_stock') and instance.is_low_stock:
                    if not old_state.get('was_low_stock', False):
                        InventoryNotifications.notify_low_stock(instance.product, instance)

                # Check out of stock (only if just became zero)
                if instance.quantity == 0 and old_quantity > 0:
                    InventoryNotifications.notify_out_of_stock(instance.product, instance)

                # Clean up tracked state
                if state_key in _pre_save_state:
                    del _pre_save_state[state_key]

    except Exception as e:
        logger.error(f"Error in notify_stock_levels: {e}", exc_info=True)


@receiver(post_save, sender='inventory.Product')
@with_tenant_safety
def notify_product_events(sender, instance, created, **kwargs):
    """Notify on product events"""
    try:
        if not created:
            return

        # You can add product creation notifications here if needed
        # For example, notify inventory managers when new products are added

    except Exception as e:
        logger.error(f"Error in notify_product_events: {e}", exc_info=True)


# ============= COMPANY/SUBSCRIPTION NOTIFICATIONS =============

@receiver(post_save, sender='company.Company')
def notify_company_events(sender, instance, created, **kwargs):
    """Notify on company/subscription events - special handling for public schema"""
    try:
        if created:
            return

        schema_name = instance.schema_name
        state_key = f'company_{instance.pk}'
        old_state = _pre_save_state.get(state_key, {})

        # Use schema context for tenant-specific operations
        with schema_context(schema_name):
            # Check subscription expiry
            if instance.subscription_ends_at:
                days_remaining = (instance.subscription_ends_at - timezone.now().date()).days

                if days_remaining in [30, 14, 7, 3, 1]:
                    CompanyNotifications.notify_subscription_expiring(instance, days_remaining)

            # Check trial expiry
            if instance.is_trial and instance.trial_ends_at:
                days_remaining = (instance.trial_ends_at - timezone.now().date()).days

                if days_remaining in [7, 3, 1]:
                    CompanyNotifications.notify_trial_ending(instance, days_remaining)

            # Check suspension (only if status just changed to SUSPENDED)
            if instance.status == 'SUSPENDED' and old_state.get('status') != 'SUSPENDED':
                admins = instance.staff.filter(is_staff=True).only(
                    'id', 'email', 'first_name', 'last_name'
                )

                for admin in admins:
                    NotificationService.create_notification(
                        recipient=admin,
                        title='Company Account Suspended',
                        message=f'{instance.name} has been suspended. Contact support for details.',
                        notification_type='ALERT',
                        priority='URGENT',
                        related_object=instance,
                        channels=['in_app', 'email'],
                        tenant_schema=schema_name
                    )

        # Clean up tracked state
        if state_key in _pre_save_state:
            del _pre_save_state[state_key]

    except Exception as e:
        logger.error(f"Error in notify_company_events: {e}", exc_info=True)


# ============= SECURITY NOTIFICATIONS =============

@receiver(post_save, sender='stores.UserDeviceSession')
@with_tenant_safety
def notify_device_sessions(sender, instance, created, **kwargs):
    """Notify on new device sessions"""
    try:
        if not created:
            return

        if not hasattr(instance, 'is_new_device') or not instance.is_new_device:
            return

        SecurityNotifications.notify_new_device_login(instance.user, instance)

    except Exception as e:
        logger.error(f"Error in notify_device_sessions: {e}", exc_info=True)


@receiver(post_save, sender='stores.SecurityAlert')
@with_tenant_safety
def notify_security_alerts(sender, instance, created, **kwargs):
    """Notify on security alerts"""
    try:
        if not created:
            return

        schema_name = None
        if hasattr(instance, 'store') and instance.store:
            schema_name = instance.store.company.schema_name
        elif hasattr(instance, 'company') and instance.company:
            schema_name = instance.company.schema_name

        if not schema_name:
            logger.warning("Cannot determine schema for security alert")
            return

        with schema_context(schema_name):
            # Notify the user
            SecurityNotifications.notify_suspicious_activity(instance.user, instance)

            # Also notify admins for high-severity alerts
            if hasattr(instance, 'severity') and instance.severity in ['HIGH', 'CRITICAL']:
                if hasattr(instance, 'store') and instance.store:
                    # FIX 1: Use User model with company filter
                    from django.contrib.auth import get_user_model
                    User = get_user_model()

                    admins = User.objects.filter(
                        company=instance.store.company,  # This assumes User has a 'company' field
                        is_staff=True,
                        is_active=True
                    ).only('id', 'email', 'first_name', 'last_name')

                    # If that doesn't work, try:
                    # FIX 2: Use staff from all company stores
                    admins = User.objects.filter(
                        stores__company=instance.store.company,
                        is_staff=True,
                        is_active=True
                    ).distinct().only('id', 'email', 'first_name', 'last_name')

                    for admin in admins:
                        NotificationService.create_notification(
                            recipient=admin,
                            title=f'Security Alert: {instance.title}',
                            message=f'{instance.user.get_full_name()} - {instance.description}',
                            notification_type='ALERT',
                            priority='HIGH',
                            related_object=instance,
                            action_text='Review',
                            action_url=f'/security/alerts/{instance.id}/',
                            tenant_schema=schema_name
                        )

    except Exception as e:
        logger.error(f"Error in notify_security_alerts: {e}", exc_info=True)


# ============= MESSAGING NOTIFICATIONS =============

@receiver(post_save, sender='messaging.Message')
@with_tenant_safety
def notify_new_messages(sender, instance, created, **kwargs):
    """Notify on new messages"""
    try:
        if not created:
            return

        if hasattr(instance, 'is_deleted') and instance.is_deleted:
            return

        schema_name = None
        if hasattr(instance, 'conversation') and instance.conversation:
            if hasattr(instance.conversation, 'company'):
                schema_name = instance.conversation.company.schema_name

        if not schema_name:
            schema_name = NotificationService.get_tenant_schema(user=instance.sender)

        if not schema_name:
            logger.warning("Cannot determine schema for message notification")
            return

        with schema_context(schema_name):
            # Notify all conversation participants except sender
            if hasattr(instance, 'conversation') and instance.conversation:
                participants = instance.conversation.participants.filter(
                    is_active=True
                ).exclude(user=instance.sender).select_related('user')

                for participant in participants:
                    # Skip if user has muted conversation
                    if hasattr(participant, 'is_muted') and participant.is_muted:
                        continue

                    MessagingNotifications.notify_new_message(
                        recipient=participant.user,
                        message=instance,
                        conversation=instance.conversation
                    )

            # Notify mentioned users
            if hasattr(instance, 'mentioned_users'):
                for mentioned_user in instance.mentioned_users.all():
                    if mentioned_user != instance.sender:
                        MessagingNotifications.notify_mention(
                            recipient=mentioned_user,
                            message=instance,
                            conversation=instance.conversation
                        )

    except Exception as e:
        logger.error(f"Error in notify_new_messages: {e}", exc_info=True)


# ============= PAYMENT NOTIFICATIONS =============

@receiver(post_save, sender='sales.Payment')
@with_tenant_safety
def notify_payment_events(sender, instance, created, **kwargs):
    """Notify on payment events"""
    try:
        if not created:
            return

        if not hasattr(instance, 'is_confirmed') or not instance.is_confirmed:
            return

        schema_name = instance.sale.store.company.schema_name

        with schema_context(schema_name):
            # Payment received
            if instance.sale.created_by:
                NotificationService.create_from_template(
                    event_type='payment_received',
                    recipient=instance.sale.created_by,
                    context={
                        'amount': f'{instance.amount:,.0f}',
                        'payment_method': instance.get_payment_method_display() if hasattr(instance,
                                                                                           'get_payment_method_display') else instance.payment_method,
                        'invoice_number': instance.sale.invoice_number,
                    },
                    related_object=instance,
                    tenant_schema=schema_name
                )

    except Exception as e:
        logger.error(f"Error in notify_payment_events: {e}", exc_info=True)


# ============= REPORT NOTIFICATIONS =============

@receiver(post_save, sender='reports.GeneratedReport')
@with_tenant_safety
def notify_report_generated(sender, instance, created, **kwargs):
    """Notify when report is generated"""
    try:
        if created:
            return

        state_key = f'report_{instance.pk}'
        old_state = _pre_save_state.get(state_key, {})

        # Only notify if status just changed to COMPLETED
        if instance.status == 'COMPLETED' and old_state.get('status') != 'COMPLETED':
            schema_name = None
            if hasattr(instance, 'company'):
                schema_name = instance.company.schema_name

            if schema_name and instance.generated_by:
                with schema_context(schema_name):
                    file_size_kb = instance.file_size / 1024 if hasattr(instance,
                                                                        'file_size') and instance.file_size else 0

                    NotificationService.create_from_template(
                        event_type='report_generated',
                        recipient=instance.generated_by,
                        context={
                            'report_name': instance.report.name if hasattr(instance, 'report') else 'Report',
                            'file_size': f'{file_size_kb:.2f} KB',
                        },
                        related_object=instance,
                        priority='LOW',
                        tenant_schema=schema_name
                    )

        # Clean up tracked state
        if state_key in _pre_save_state:
            del _pre_save_state[state_key]

    except Exception as e:
        logger.error(f"Error in notify_report_generated: {e}", exc_info=True)


# ============= EFRIS NOTIFICATIONS =============

@receiver(post_save, sender='efris.FiscalizationAudit')
@with_tenant_safety
def notify_efris_events(sender, instance, created, **kwargs):
    """Notify on EFRIS events"""
    try:
        if not created:
            return

        if not hasattr(instance, 'action') or instance.action != 'FISCALIZE':
            return

        if instance.success or not hasattr(instance, 'invoice') or not instance.invoice:
            return

        schema_name = None
        if hasattr(instance.invoice, 'sale') and instance.invoice.sale:
            schema_name = instance.invoice.sale.store.company.schema_name

        if schema_name and instance.invoice.sale and instance.invoice.sale.created_by:
            # Fiscalization failed
            error_msg = getattr(instance, 'error_message', 'Unknown error')
            SalesNotifications.notify_efris_failed(
                instance.invoice.sale,
                error_msg
            )

    except Exception as e:
        logger.error(f"Error in notify_efris_events: {e}", exc_info=True)


# Helper function to connect all signals
def connect_notification_signals():
    """
    Call this in apps.py ready() method to ensure signals are connected
    This is automatically called when the module is imported
    """
    logger.info("Notification signals connected")