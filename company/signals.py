from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from decimal import Decimal
import json
import logging
from django.core.exceptions import ValidationError
from django.db import transaction

from .models import Company
from stores.models import Store, DeviceOperatorLog
from accounts.models import CustomUser
from sales.models import Sale
from inventory.models import Stock

logger = logging.getLogger(__name__)


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder for Decimal types"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


channel_layer = get_channel_layer()


# ============================================================================
# USER LIMIT ENFORCEMENT
# ============================================================================

@receiver(pre_save, sender=CustomUser)
def check_user_limit_on_create(sender, instance, **kwargs):
    """
    Prevent user creation if limit reached.
    Uses SELECT FOR UPDATE to prevent race conditions.
    """
    # Only check on new user creation
    if instance.pk:
        return

    # Skip for users without company
    if not instance.company:
        return

    # Skip for SaaS admins
    if getattr(instance, 'is_saas_admin', False):
        return

    company = instance.company

    # Check if plan exists
    if not company.plan:
        raise ValidationError('Company has no active plan')

    # Get fresh company with lock to prevent race conditions
    try:
        with transaction.atomic():
            # Lock the company row to prevent concurrent user creation
            locked_company = Company.objects.select_for_update().get(
                pk=company.pk
            )

            # Count existing ACTIVE users (not hidden)
            current_users = CustomUser.objects.filter(
                company=locked_company,
                is_active=True,  # FIXED: Added is_active check
                is_hidden=False
            ).count()

            # Check limit
            if current_users >= locked_company.plan.max_users:
                raise ValidationError(
                    f'User limit reached ({current_users}/{locked_company.plan.max_users}). '
                    f'Please upgrade your plan to add more users.'
                )

    except Company.DoesNotExist:
        raise ValidationError('Company not found')


@receiver(post_save, sender=CustomUser)
def clear_user_cache_on_save(sender, instance, created, **kwargs):
    """Clear company user count cache when user is created or updated"""
    if not instance.company:
        return

    # Clear the user count cache
    instance.company.clear_user_count_cache()

    # If user status changed, also clear general cache
    if not created:
        instance.company._clear_cache()


@receiver(post_delete, sender=CustomUser)
def clear_user_cache_on_delete(sender, instance, **kwargs):
    """Clear company user count cache when user is deleted"""
    if not instance.company:
        return

    # Clear the user count cache
    instance.company.clear_user_count_cache()
    instance.company._clear_cache()


# ============================================================================
# BRANCH/STORE LIMIT ENFORCEMENT
# ============================================================================

@receiver(pre_save, sender=Store)
def check_branch_limit_on_create(sender, instance, **kwargs):
    """
    Prevent branch/store creation if limit reached.
    Uses SELECT FOR UPDATE to prevent race conditions.
    """
    # Only check on new store creation
    if instance.pk:
        return

    # Skip for stores without company
    if not instance.company:
        return

    company = instance.company

    # Check if plan exists
    if not company.plan:
        raise ValidationError('Company has no active plan')

    # Get fresh company with lock to prevent race conditions
    try:
        with transaction.atomic():
            # Lock the company row to prevent concurrent branch creation
            locked_company = Company.objects.select_for_update().get(
                pk=company.pk
            )

            # Count existing active branches
            current_branches = Store.objects.filter(
                company=locked_company,
                is_active=True  # FIXED: Added is_active check
            ).count()

            # Check limit
            if current_branches >= locked_company.plan.max_branches:
                raise ValidationError(
                    f'Branch limit reached ({current_branches}/{locked_company.plan.max_branches}). '
                    f'Please upgrade your plan to add more branches.'
                )

    except Company.DoesNotExist:
        raise ValidationError('Company not found')


@receiver(post_save, sender=Store)
def clear_branch_cache_on_save(sender, instance, created, **kwargs):
    """Clear company branch count cache when store is created or updated"""
    if not instance.company:
        return

    # Clear the branch count cache
    instance.company._clear_cache()


@receiver(post_delete, sender=Store)
def clear_branch_cache_on_delete(sender, instance, **kwargs):
    """Clear company branch count cache when store is deleted"""
    if not instance.company:
        return

    # Clear the branch count cache
    instance.company._clear_cache()


# ============================================================================
# EFRIS SIGNALS
# ============================================================================

@receiver(post_save, sender=Company)
def handle_company_efris_changes(sender, instance, created, **kwargs):
    """Handle EFRIS-related changes when company is saved"""

    # Import here to avoid circular imports
    from company.tasks import setup_efris_for_company, sync_company_to_efris

    if created:
        # New company created - schedule EFRIS setup if enabled
        if instance.efris_enabled:
            logger.info(f"New company created with EFRIS enabled: {instance.company_id}")

            # Schedule task to run AFTER the transaction commits
            transaction.on_commit(
                lambda: setup_efris_for_company.apply_async(
                    args=[instance.company_id],
                    countdown=5,
                )
            )

            logger.info(
                f"Scheduled EFRIS setup task for company {instance.company_id} "
                f"(will run in 5 seconds after transaction commits)"
            )
        else:
            logger.info(f"New company created without EFRIS: {instance.company_id}")

    else:
        # Existing company updated - check for EFRIS changes.
        # NOTE: We cannot reliably fetch "old" values in post_save because the DB
        # already holds the new values. Instead we rely on _pre_save_efris_enabled
        # which is stored on the instance by the pre_save signal below.
        try:
            # Retrieve old EFRIS state captured by pre_save signal
            old_efris_enabled = getattr(instance, '_pre_save_efris_enabled', instance.efris_enabled)

            # Check if EFRIS was just enabled
            if not old_efris_enabled and instance.efris_enabled:
                logger.info(f"EFRIS enabled for existing company {instance.company_id}")

                transaction.on_commit(
                    lambda: setup_efris_for_company.apply_async(
                        args=[instance.company_id],
                        countdown=2,
                    )
                )

            # Check if critical EFRIS fields changed (use update_fields hint when available)
            elif instance.efris_enabled:
                update_fields = kwargs.get('update_fields')
                efris_fields = ['tin', 'name', 'trading_name', 'email', 'phone', 'physical_address']
                if update_fields is not None:
                    fields_changed = [f for f in efris_fields if f in update_fields]
                else:
                    # update_fields not provided - assume something may have changed
                    fields_changed = efris_fields  # conservative: trigger sync

                if fields_changed:
                    logger.info(
                        f"EFRIS data changed for company {instance.company_id}: "
                        f"fields={', '.join(fields_changed)}"
                    )

                    transaction.on_commit(
                        lambda: sync_company_to_efris.apply_async(
                            args=[instance.company_id],
                            countdown=1,
                        )
                    )

        except Exception as e:
            logger.error(
                f"Error in EFRIS change handler for company {instance.company_id}: {e}",
                exc_info=True
            )


@receiver(pre_save, sender=Company)
def capture_efris_state_before_save(sender, instance, **kwargs):
    """
    Capture the current efris_enabled value BEFORE the save so that
    handle_company_efris_changes (post_save) can compare old vs new correctly.
    The DB still holds the old value here, so we fetch it once and stash it
    on the instance as a private attribute.
    """
    if instance.pk:
        try:
            old = Company.objects.only('efris_enabled').get(pk=instance.pk)
            instance._pre_save_efris_enabled = old.efris_enabled
        except Company.DoesNotExist:
            instance._pre_save_efris_enabled = instance.efris_enabled
    else:
        # New instance — treat as "was not enabled"
        instance._pre_save_efris_enabled = False


@receiver(pre_save, sender=Company)
def validate_efris_configuration(sender, instance, **kwargs):
    """Validate EFRIS configuration before saving"""

    if instance.efris_enabled:
        # Check configuration completeness
        errors = instance.get_efris_configuration_errors()

        if errors:
            logger.warning(
                f"Company {instance.company_id} EFRIS validation failed: {', '.join(errors)}"
            )
            # Don't prevent saving, but log the issue
            # You could also set efris_is_active = False here


# ============================================================================
# COMPANY STATUS CHANGE SIGNALS
# ============================================================================

@receiver(post_save, sender=Company)
def handle_company_status_change(sender, instance, **kwargs):
    """Send notifications when company status changes"""
    try:
        update_fields = kwargs.get('update_fields')

        if update_fields and 'status' in update_fields:
            # Company status was updated
            if instance.status == 'EXPIRED':
                # Send expiration email
                from .tasks import send_expiration_notification
                transaction.on_commit(
                    lambda: send_expiration_notification.delay(instance.company_id)
                )

            elif instance.status == 'SUSPENDED':
                # Send suspension email
                from .tasks import send_suspension_notification
                transaction.on_commit(
                    lambda: send_suspension_notification.delay(instance.company_id)
                )

    except Exception as e:
        logger.error(f"Error handling company status change: {e}", exc_info=True)


# ============================================================================
# REAL-TIME WEBSOCKET SIGNALS
# ============================================================================

@receiver(post_save, sender=Stock)
def inventory_updated_handler(sender, instance, created, **kwargs):
    """Handle inventory updates - send low stock alerts"""
    # ✅ Skip in desktop mode
    if getattr(settings, 'DESKTOP_MODE', False):
        return

    try:
        # Check if item is low stock or out of stock
        if instance.quantity <= instance.low_stock_threshold:
            company = instance.store.company
            alert_type = 'out_of_stock' if instance.quantity == 0 else 'low_stock'

            # ✅ Check channel layer exists
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync

            channel_layer = get_channel_layer()

            if not channel_layer:
                logger.debug("Channel layer not available, skipping WebSocket")
                return

            async_to_sync(channel_layer.group_send)(
                f'company_dashboard_{company.company_id}',
                {
                    'type': 'alert_notification',
                    'alert_type': alert_type,
                    'message': f"{instance.product.name if hasattr(instance, 'product') else 'Product'} is {'out of stock' if instance.quantity == 0 else 'running low'} at {instance.store.name}",
                    'data': {
                        'store_name': instance.store.name,
                        'quantity': float(instance.quantity),
                        'threshold': float(instance.low_stock_threshold)
                    }
                }
            )

    except ImportError:
        logger.debug("Channels not installed, skipping WebSocket")
    except Exception as e:
        logger.debug(f"WebSocket update failed: {e}")


@receiver(post_save, sender=Sale)
def sale_created_handler(sender, instance, created, **kwargs):
    """Handle new sale creation - send real-time updates"""
    if not created:
        return

    # ✅ Skip in desktop mode
    if getattr(settings, 'DESKTOP_MODE', False):
        return

    try:
        company = instance.store.company

        # ✅ Check channel layer exists
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync

        channel_layer = get_channel_layer()

        if not channel_layer:
            logger.debug("Channel layer not available, skipping WebSocket")
            return

        # Send update to company dashboard
        async_to_sync(channel_layer.group_send)(
            f'company_dashboard_{company.company_id}',
            {
                'type': 'dashboard_update',
                'data': {
                    'event_type': 'new_sale',
                    'sale_id': instance.id,
                    'amount': float(instance.total_amount),
                    'store_name': instance.store.name,
                    'branch_name': instance.store.name,
                    'timestamp': instance.created_at.isoformat()
                }
            }
        )

        # Send update to branch analytics
        async_to_sync(channel_layer.group_send)(
            f'branch_analytics_{instance.store.pk}',
            {
                'type': 'analytics_update',
                'data': {
                    'event_type': 'new_sale',
                    'sale_amount': float(instance.total_amount),
                    'store_name': instance.store.name,
                    'timestamp': instance.created_at.isoformat()
                }
            }
        )

    except ImportError:
        logger.debug("Channels not installed, skipping WebSocket")
    except Exception as e:
        logger.debug(f"WebSocket update failed: {e}")


@receiver(post_save, sender=DeviceOperatorLog)
def device_activity_handler(sender, instance, created, **kwargs):
    """Handle device operator activities"""
    if not created:
        return

    try:
        if not instance.device or not instance.device.store:
            return

        store = instance.device.store
        if not store.company:
            return

        company = store.company
        company_id = company.company_id

        user_name = instance.user.get_full_name() or instance.user.username

        if not channel_layer:
            logger.debug("Channel layer not available, skipping device activity WebSocket")
            return

        async_to_sync(channel_layer.group_send)(
            f'company_dashboard_{company_id}',
            {
                'type': 'dashboard_update',
                'data': {
                    'event_type': 'device_activity',
                    'user_name': user_name,
                    'action': instance.action.replace('_', ' ').title(),
                    'store_name': store.name,
                    'timestamp': instance.timestamp.isoformat(),
                    'device_name': instance.device.name if instance.device else 'Unknown Device'
                }
            }
        )

    except Exception as e:
        logger.error(f"Error sending device activity update: {e}", exc_info=True)


@receiver(post_save, sender=CustomUser)
def employee_updated_handler(sender, instance, created, **kwargs):
    """Handle employee creation/updates"""
    if getattr(instance, 'is_hidden', False) or getattr(instance, 'is_saas_admin', False):
        return

    if not instance.company:
        return

    try:
        event_type = 'employee_joined' if created else 'employee_updated'

        if not channel_layer:
            logger.debug("Channel layer not available, skipping employee update WebSocket")
            return

        async_to_sync(channel_layer.group_send)(
            f'company_dashboard_{instance.company.company_id}',
            {
                'type': 'dashboard_update',
                'data': {
                    'event_type': event_type,
                    'user_name': instance.get_full_name() or instance.username,
                    'user_role': getattr(instance.primary_role, 'name', None) if hasattr(instance,
                                                                                         'primary_role') else None,
                    'is_active': instance.is_active,
                    'timestamp': instance.date_joined.isoformat() if created else timezone.now().isoformat(),
                },
            },
        )

    except Exception as e:
        logger.error(f"Error sending employee update: {e}", exc_info=True)


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def send_performance_alert(company_id, alert_type, message, data=None):
    """Send performance alerts to company dashboard"""
    try:
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
        logger.error(f"Error sending performance alert: {e}", exc_info=True)


def broadcast_company_update(company_id, update_data):
    """Broadcast general company updates"""
    try:
        async_to_sync(channel_layer.group_send)(
            f'company_dashboard_{company_id}',
            {
                'type': 'dashboard_update',
                'data': update_data
            }
        )
    except Exception as e:
        logger.error(f"Error broadcasting company update: {e}", exc_info=True)