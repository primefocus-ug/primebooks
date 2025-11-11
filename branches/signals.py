from django.db.models.signals import post_save, pre_save
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
        store = instance.store
        company_id = store.company.pk if store.company else None
        timestamp = instance.created_at.timestamp() if hasattr(instance.created_at, 'timestamp') else None

        # Prepare sale data once
        sale_data = {
            'id': str(instance.id),
            'invoice_number': instance.invoice_number,
            'store_id': store.id,
            'store_name': store.name,
            'store_code': store.code,
            'company_id': company_id,
            'total_amount': float(instance.total_amount),
            'created_at': instance.created_at.isoformat(),
            'is_new': created
        }

        # Send updates to multiple groups efficiently
        updates = [
            # Store analytics
            (f'store_analytics_{store.id}', 'sale_created' if created else 'sale_update', sale_data, timestamp),
            # Store updates
            (f'store_updates_{store.id}', 'store_update', {
                'store_id': store.id,
                'update_type': 'sale',
                'sale_data': sale_data
            }, None)
        ]

        # Add company-wide update if company exists
        if company_id:
            updates.append((
                f'company_stores_{company_id}',
                'store_update',
                {
                    'company_id': company_id,
                    'store_id': store.id,
                    'update_type': 'sale',
                    'sale_data': sale_data
                },
                None
            ))

        for group_name, message_type, data, ts in updates:
            send_websocket_update(group_name, message_type, data, ts)

    except Exception as e:
        logger.error(f'Sale WebSocket update failed for sale {instance.id}: {e}')


@receiver(post_save, sender=Stock)
def inventory_updated(sender, instance, created, **kwargs):
    """Trigger WebSocket updates when inventory changes."""
    try:
        store = instance.store
        company_id = store.company.pk if store.company else None

        inventory_data = {
            'store_id': store.id,
            'store_name': store.name,
            'product_id': instance.product.id,
            'product_name': instance.product.name,
            'quantity': float(instance.quantity),
            'low_stock_threshold': float(instance.low_stock_threshold),
            'is_low_stock': instance.is_low_stock,
            'updated_at': instance.last_updated.isoformat() if hasattr(instance, 'last_updated') else None
        }

        # Always send to store analytics
        send_websocket_update(
            f'store_analytics_{store.id}',
            'inventory_update',
            inventory_data
        )

        # Send to company analytics if low stock
        if instance.is_low_stock and company_id:
            alert_data = {
                'alert_type': 'low_stock',
                'store_id': store.id,
                'store_name': store.name,
                'product_name': instance.product.name,
                'quantity': float(instance.quantity),
                'threshold': float(instance.low_stock_threshold)
            }

            send_websocket_update(
                f'company_stores_{company_id}',
                'company_alert',
                alert_data
            )

    except Exception as e:
        logger.error(f'Inventory WebSocket update failed: {e}')


@receiver(post_save, sender=Store)
def store_updated(sender, instance, created, **kwargs):
    """Trigger WebSocket updates when store is updated."""
    try:
        company_id = instance.company.pk if instance.company else None

        store_data = {
            'id': instance.id,
            'name': instance.name,
            'code': instance.code,
            'is_active': instance.is_active,
            'is_main_store': instance.is_main_branch,
            'efris_enabled': instance.efris_enabled,
            'company_id': company_id,
            'updated_at': instance.updated_at.isoformat() if hasattr(instance, 'updated_at') else None
        }

        # Send to store's own analytics
        send_websocket_update(
            f'store_analytics_{instance.id}',
            'store_update',
            store_data
        )

        # Send to company-wide analytics if company exists
        if company_id:
            send_websocket_update(
                f'company_stores_{company_id}',
                'store_update',
                store_data
            )

    except Exception as e:
        logger.error(f'Store WebSocket update failed: {e}')


@receiver(post_save, sender=Store)
def ensure_main_store(sender, instance, created, **kwargs):
    """Ensure there's always a main store for the company."""
    if created and instance.company:
        # Check if there's already a main store
        if not Store.objects.filter(company=instance.company, is_main_branch=True).exclude(id=instance.id).exists():
            instance.is_main_branch = True
            instance.save(update_fields=['is_main_branch'])


@receiver(post_save, sender=Stock)
def company_inventory_analytics(sender, instance, created, **kwargs):
    """
    Send comprehensive inventory analytics to company dashboard
    Only triggers on significant changes to reduce noise
    """
    try:
        # Only send updates for significant changes or low stock situations
        if not (instance.is_low_stock or getattr(instance, 'needs_reorder', False)):
            return

        store = instance.store
        company_id = store.company.pk if store.company else None

        if not company_id:
            return

        # Get company-wide inventory statistics
        from django.db.models import Count, Sum, F, Q
        company_inventory_stats = Stock.objects.filter(
            store__company_id=company_id
        ).aggregate(
            total_products=Count('id'),
            low_stock_count=Count('id', filter=Q(quantity__lte=F('low_stock_threshold'))),
            total_value=Sum(F('quantity') * F('product__cost_price')) or 0
        )

        analytics_data = {
            'company_id': company_id,
            'store_id': store.id,
            'store_name': store.name,
            'trigger_product': instance.product.name,
            'stats': {
                'total_products': company_inventory_stats['total_products'],
                'low_stock_count': company_inventory_stats['low_stock_count'],
                'total_value': float(company_inventory_stats['total_value'])
            },
            'updated_at': instance.last_updated.isoformat() if hasattr(instance, 'last_updated') else None
        }

        send_websocket_update(
            f'company_inventory_analytics_{company_id}',
            'inventory_analytics_update',
            analytics_data
        )

    except Exception as e:
        logger.error(f'Company inventory analytics update failed: {e}')
