from django.db.models.signals import post_save
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
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone
from .tasks import setup_efris_for_company, sync_company_to_efris
from .models import Company
from branches.models import CompanyBranch
from sales.models import Sale
from stores.models import DeviceOperatorLog
from inventory.models import Stock
from accounts.models import CustomUser

logger = logging.getLogger(__name__)

class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder for Decimal types"""

    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


channel_layer = get_channel_layer()


@receiver(post_save, sender=Company)
def handle_company_efris_changes(sender, instance, created, **kwargs):
    """Handle EFRIS-related changes when company is saved"""

    if created:
        # New company created - schedule EFRIS setup if enabled
        if instance.efris_enabled:
            logger.info(f"Scheduling EFRIS setup for new company {instance.company_id}")
            setup_efris_for_company.delay(instance.company_id)
    else:
        # Existing company updated - check for EFRIS changes
        try:
            old_instance = Company.objects.get(pk=instance.pk)

            # Check if EFRIS was just enabled
            if not old_instance.efris_enabled and instance.efris_enabled:
                logger.info(f"EFRIS enabled for company {instance.company_id}")
                setup_efris_for_company.delay(instance.company_id)

            # Check if critical EFRIS fields changed
            efris_fields = ['tin', 'name', 'trading_name', 'email', 'phone', 'physical_address']
            if instance.efris_enabled and any(
                    getattr(old_instance, field) != getattr(instance, field)
                    for field in efris_fields
            ):
                logger.info(f"EFRIS data changed for company {instance.company_id}")
                sync_company_to_efris.delay(instance.company_id)

        except Company.DoesNotExist:
            # This shouldn't happen but handle gracefully
            pass


@receiver(pre_save, sender=Company)
def validate_efris_configuration(sender, instance, **kwargs):
    """Validate EFRIS configuration before saving"""

    if instance.efris_enabled:
        # Validate business data completeness
        can_use, errors = instance.can_use_efris()

        if not can_use:
            logger.warning(
                f"Company {instance.company_id} EFRIS validation failed: {errors}"
            )
            # Don't prevent saving, but log the issue
            # You could also set efris_is_active = False here


@receiver(post_save, sender=Sale)
def sale_created_handler(sender, instance, created, **kwargs):
    """Handle new sale creation - send real-time updates"""
    if not created:
        return

    try:
        # Get company from the store's branch
        company = instance.store.company

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
                    'branch_name': instance.store.company.name,
                    'timestamp': instance.created_at.isoformat()
                }
            }
        )

        # Send update to branch analytics if applicable
        async_to_sync(channel_layer.group_send)(
            f'branch_analytics_{instance.store.company.pk}',
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

    except Exception as e:
        print(f"Error sending sale update: {e}")


@receiver(post_save, sender=Stock)  # Updated sender
def inventory_updated_handler(sender, instance, created, **kwargs):
    """Handle inventory updates - send low stock alerts"""
    try:
        # Check if item is low stock or out of stock
        if instance.quantity <= instance.low_stock_threshold:
            company = instance.store.company

            alert_type = 'out_of_stock' if instance.quantity == 0 else 'low_stock'

            async_to_sync(channel_layer.group_send)(
                f'company_dashboard_{company.company_id}',
                {
                    'type': 'alert_notification',
                    'alert_type': alert_type,
                    'message': f"{instance.product.name if hasattr(instance, 'product') else 'Product'} is {'out of stock' if instance.quantity == 0 else 'running low'} at {instance.store.name}",
                    'data': {
                        'store_name': instance.store.name,
                        'branch_name': instance.store.company.name,
                        'quantity': float(instance.quantity),  # Ensure float conversion
                        'threshold': float(instance.low_stock_threshold)  # Ensure float conversion
                    }
                }
            )

    except Exception as e:
        print(f"Error sending inventory alert: {e}")


@receiver(post_save, sender=DeviceOperatorLog)
def device_activity_handler(sender, instance, created, **kwargs):
    """Handle device operator activities"""
    if not created:
        return

    try:
        company = instance.device.store.branch.company

        async_to_sync(channel_layer.group_send)(
            f'company_dashboard_{company.company_id}',
            {
                'type': 'dashboard_update',
                'data': {
                    'event_type': 'device_activity',
                    'user_name': instance.user.get_full_name() or instance.user.username,
                    'action': instance.action.replace('_', ' ').title(),
                    'store_name': instance.device.store.name,
                    'branch_name': instance.device.store.branch.name,
                    'timestamp': instance.timestamp.isoformat()
                }
            }
        )

    except Exception as e:
        print(f"Error sending device activity update: {e}")


@receiver(post_save, sender=CompanyBranch)
def branch_updated_handler(sender, instance, created, **kwargs):
    """Handle branch creation/updates"""
    try:
        event_type = 'branch_created' if created else 'branch_updated'

        async_to_sync(channel_layer.group_send)(
            f'company_dashboard_{instance.company.company_id}',
            {
                'type': 'branch_update',
                'branch_id': instance.id,
                'data': {
                    'event_type': event_type,
                    'branch_name': instance.name,
                    'branch_code': instance.code,
                    'is_active': instance.is_active,
                    'is_main_branch': instance.is_main_branch,
                    'location': instance.location
                }
            }
        )

    except Exception as e:
        print(f"Error sending branch update: {e}")


@receiver(post_save, sender=CustomUser)
def employee_updated_handler(sender, instance, created, **kwargs):
    """Handle employee creation/updates"""
    if instance.is_hidden or instance.is_saas_admin:
        return  # Don't send updates for hidden users

    try:
        event_type = 'employee_joined' if created else 'employee_updated'

        async_to_sync(channel_layer.group_send)(
            f'company_dashboard_{instance.company.company_id}',
            {
                'type': 'dashboard_update',
                'data': {
                    'event_type': event_type,
                    'user_name': instance.get_full_name() or instance.username,
                    'user_type': instance.user_type,
                    'is_active': instance.is_active,
                    'timestamp': instance.date_joined.isoformat() if created else instance.updated_at.isoformat() if hasattr(
                        instance, 'updated_at') else None
                }
            }
        )

    except Exception as e:
        print(f"Error sending employee update: {e}")


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
        print(f"Error sending performance alert: {e}")


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
        print(f"Error broadcasting company update: {e}")


@receiver(post_save, sender=Company)
def handle_company_status_change(sender, instance, **kwargs):
    """Send notifications when company status changes"""
    try:
        if kwargs.get('update_fields') and 'status' in kwargs['update_fields']:
            # Company status was updated
            if instance.status == 'EXPIRED':
                # Send expiration email - use the task from tasks.py
                from .tasks import send_expiration_notification
                send_expiration_notification.delay(instance.company_id)
            elif instance.status == 'SUSPENDED':
                # Send suspension email - use the task from tasks.py
                from .tasks import send_suspension_notification
                send_suspension_notification.delay(instance.company_id)
    except Exception as e:
        logger.error(f"Error handling company status change: {e}")
