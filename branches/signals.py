from django.db.models.signals import post_save
from django.dispatch import receiver
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from sales.models import Sale
from stores.models import Store
from inventory.models import Stock
import logging

logger = logging.getLogger(__name__)


def send_websocket_update(group_name, message_type, data, timestamp=None):
    """
    Utility function to handle WebSocket updates with error handling
    """
    channel_layer = get_channel_layer()
    if not channel_layer:
        return False

    try:
        message = {
            'type': message_type,
            'data': data
        }
        if timestamp:
            message['timestamp'] = timestamp

        async_to_sync(channel_layer.group_send)(group_name, message)
        return True
    except Exception as e:
        logger.error(f'WebSocket update failed for group {group_name}: {e}')
        return False


@receiver(post_save, sender=Sale)
def sale_created_or_updated(sender, instance, created, **kwargs):
    """Trigger WebSocket updates when a sale is created or updated."""
    if not instance.is_completed:
        return

    try:
        branch_id = instance.store.company.pk
        timestamp = instance.created_at.timestamp()

        # Prepare sale data once
        sale_data = {
            'id': str(instance.id),
            'invoice_number': instance.invoice_number,
            'store_id': instance.store.id,
            'store_name': instance.store.name,
            'branch_id': branch_id,
            'total_amount': float(instance.total_amount),
            'created_at': instance.created_at.isoformat(),
            'is_new': created
        }

        # Send updates to multiple groups efficiently
        updates = [
            (f'branch_analytics_{branch_id}', 'sale_created' if created else 'sale_update', sale_data, timestamp),
            (f'store_analytics_{instance.store.id}', 'store_sale_update', sale_data, timestamp),
            (f'store_updates_{instance.store.id}', 'store_update', {
                'store_id': instance.store.id,
                'update_type': 'sale',
                'sale_data': sale_data
            }, None)
        ]

        for group_name, message_type, data, ts in updates:
            send_websocket_update(group_name, message_type, data, ts)

    except Exception as e:
        logger.error(f'Sale WebSocket update failed for sale {instance.id}: {e}')


@receiver(post_save, sender=Stock)
def inventory_updated(sender, instance, created, **kwargs):
    """Trigger WebSocket updates when inventory changes."""
    try:
        inventory_data = {
            'store_id': instance.store.id,
            'product_id': instance.product.id,
            'product_name': instance.product.name,
            'quantity': float(instance.quantity),
            'low_stock_threshold': float(instance.low_stock_threshold),
            'is_low_stock': instance.is_low_stock,
            'updated_at': instance.last_updated.isoformat()
        }

        # Always send to store analytics
        send_websocket_update(
            f'store_analytics_{instance.store.id}',
            'inventory_update',
            inventory_data
        )

        # Send to branch analytics only if low stock
        if instance.is_low_stock:
            branch_id = instance.store.company.pk
            alert_data = {
                'alert_type': 'low_stock',
                'store_name': instance.store.name,
                'product_name': instance.product.name,
                'quantity': float(instance.quantity)
            }

            send_websocket_update(
                f'branch_analytics_{branch_id}',
                'performance_alert',
                alert_data
            )

    except Exception as e:
        logger.error(f'Inventory WebSocket update failed: {e}')


@receiver(post_save, sender=Store)
def store_updated(sender, instance, created, **kwargs):
    """Trigger WebSocket updates when store is updated."""
    try:
        branch_id = instance.branch.id

        store_data = {
            'id': instance.id,
            'name': instance.name,
            'code': instance.code,
            'is_active': instance.is_active,
            'efris_enabled': getattr(instance, 'efris_enabled', False),
            'branch_id': branch_id,
            'updated_at': instance.updated_at.isoformat() if hasattr(instance, 'updated_at') else None
        }

        send_websocket_update(
            f'branch_analytics_{branch_id}',
            'store_update',
            store_data
        )

    except Exception as e:
        logger.error(f'Store WebSocket update failed: {e}')


@receiver(post_save, sender=Store)
def ensure_main_branch(sender, instance, created, **kwargs):
    """Ensure there's always a main branch for the company."""
    if created and not instance.company.branches.filter(is_main_branch=True).exists():
        instance.is_main_branch = True
        instance.save(update_fields=['is_main_branch'])


@receiver(post_save, sender=Stock)
def branch_inventory_analytics(sender, instance, created, **kwargs):
    """
    Send comprehensive inventory analytics to branch dashboard
    Only triggers on significant changes to reduce noise
    """
    try:
        # Only send updates for significant changes or low stock situations
        if not (instance.is_low_stock or instance.needs_reorder):
            return

        branch_id = instance.store.company.pk

        # Get branch-wide inventory statistics
        from django.db.models import Count, Sum, F, Q
        branch_inventory_stats = Stock.objects.filter(
            store__branch_id=branch_id
        ).aggregate(
            total_products=Count('id'),
            low_stock_count=Count('id', filter=Q(quantity__lte=F('low_stock_threshold'))),
            total_value=Sum(F('quantity') * F('product__cost_price')) or 0
        )

        analytics_data = {
            'branch_id': branch_id,
            'store_id': instance.store.id,
            'store_name': instance.store.name,
            'trigger_product': instance.product.name,
            'stats': {
                'total_products': branch_inventory_stats['total_products'],
                'low_stock_count': branch_inventory_stats['low_stock_count'],
                'total_value': float(branch_inventory_stats['total_value'])
            },
            'updated_at': instance.last_updated.isoformat()
        }

        send_websocket_update(
            f'branch_inventory_analytics_{branch_id}',
            'inventory_analytics_update',
            analytics_data
        )

    except Exception as e:
        logger.error(f'Branch inventory analytics update failed: {e}')