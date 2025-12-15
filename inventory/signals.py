from typing import Dict, Any, Optional
from django_tenants.utils import connection
from django.db.models.signals import post_save, post_delete, pre_save
from django.dispatch import receiver, Signal
from django.core.cache import cache
from django.utils import timezone
from django.db.models import Q, F, Count, Sum, Avg
from django.db import transaction
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django_tenants.utils import schema_context
from django.utils import timezone
from django_tenants.utils import schema_context
import logging
from .models import Service
from .models import Stock, StockMovement, Product, ImportSession, ImportLog
import structlog

# Import notification services
from notifications.services import (
    NotificationService,
    InventoryNotifications,
    SalesNotifications,
    CompanyNotifications
)

logger = structlog.get_logger(__name__)
channel_layer = get_channel_layer()

# Custom signals
bulk_stock_update = Signal()
inventory_alert = Signal()
efris_sync_required = Signal()

# Custom signals for service EFRIS operations
service_efris_sync_requested = Signal()
service_efris_synced = Signal()
service_efris_sync_failed = Signal()


@receiver(pre_save, sender=Service)
def service_pre_save_handler(sender, instance, **kwargs):
    """
    Pre-save handler for Service model
    Track changes that require EFRIS sync
    """
    if instance.pk:
        try:
            old_instance = Service.objects.get(pk=instance.pk)

            # Fields that trigger EFRIS update when changed
            efris_sensitive_fields = [
                'name', 'code', 'unit_price',
                'tax_rate', 'excise_duty_rate', 'unit_of_measure',
                'category_id', 'is_active'
            ]

            # Check if any EFRIS-sensitive field changed
            has_changes = any(
                getattr(old_instance, field) != getattr(instance, field)
                for field in efris_sensitive_fields
            )

            if has_changes and instance.efris_auto_sync_enabled:
                # Mark for re-sync
                if instance.efris_is_uploaded:
                    instance._efris_needs_update = True
                    logger.info(
                        f"Service {instance.name} marked for EFRIS update "
                        f"due to field changes"
                    )

        except Service.DoesNotExist:
            pass

    # Store old state for post-save comparison
    instance._old_efris_uploaded = getattr(
        Service.objects.filter(pk=instance.pk).first(),
        'efris_is_uploaded',
        False
    ) if instance.pk else False


@receiver(post_save, sender=Service)
def service_post_save_handler(sender, instance, created, **kwargs):
    """
    Post-save handler for Service model
    Triggers async EFRIS sync if needed
    """
    # Skip if we're in a migration or if auto-sync is disabled
    if kwargs.get('raw', False) or not instance.efris_auto_sync_enabled:
        return

    try:
        # Get tenant schema
        from django.db import connection
        schema_name = connection.schema_name

        # Check if EFRIS sync is needed
        should_sync = False
        sync_reason = None

        if created and not instance.efris_is_uploaded:
            should_sync = True
            sync_reason = 'NEW_SERVICE'
            logger.info(f"New service {instance.name} created, queueing EFRIS sync")

        elif hasattr(instance, '_efris_needs_update') and instance._efris_needs_update:
            should_sync = True
            sync_reason = 'SERVICE_UPDATED'
            logger.info(f"Service {instance.name} updated, queueing EFRIS sync")

        if should_sync:
            # Try to queue async task
            try:
                from .tasks import sync_service_to_efris_task

                # Delay to avoid race conditions
                task = sync_service_to_efris_task.apply_async(
                    args=[schema_name, instance.id],
                    countdown=2  # 2 second delay
                )

                logger.info(
                    f"EFRIS sync task queued for service {instance.name} "
                    f"(reason: {sync_reason}, task: {task.id})"
                )

                # Send custom signal
                service_efris_sync_requested.send(
                    sender=Service,
                    service=instance,
                    user=None
                )

            except ImportError:
                logger.warning(
                    f"Celery not available, skipping auto-sync for service {instance.name}"
                )

        # Clean up temporary attributes
        if hasattr(instance, '_efris_needs_update'):
            delattr(instance, '_efris_needs_update')

    except Exception as e:
        logger.error(f"Error in service post_save handler: {str(e)}", exc_info=True)


@receiver(post_delete, sender=Service)
def service_post_delete_handler(sender, instance, **kwargs):
    """
    Post-delete handler for Service model
    Log service deletion (EFRIS doesn't support deletion, just deactivation)
    """
    try:
        logger.info(
            f"Service deleted: {instance.name} (ID: {instance.id}, "
            f"Code: {instance.code}, EFRIS ID: {instance.efris_service_id})"
        )

        # If service was synced to EFRIS, log a warning
        if instance.efris_is_uploaded:
            logger.warning(
                f"Service {instance.name} was deleted but exists in EFRIS. "
                f"Consider deactivating instead of deleting."
            )

    except Exception as e:
        logger.error(f"Error in service post_delete handler: {str(e)}", exc_info=True)


@receiver(service_efris_synced)
def handle_service_efris_synced(sender, service, result, **kwargs):
    """
    Handler for successful EFRIS sync
    """
    try:
        logger.info(
            f"Service {service.name} successfully synced to EFRIS. "
            f"EFRIS Service ID: {result.get('efris_service_id')}"
        )

        # Update service with EFRIS data
        if not service.efris_is_uploaded:
            service.efris_is_uploaded = True
            service.efris_upload_date = timezone.now()

            efris_service_id = result.get('efris_service_id')
            if efris_service_id:
                service.efris_service_id = efris_service_id

            service.save(update_fields=[
                'efris_is_uploaded',
                'efris_upload_date',
                'efris_service_id'
            ])

    except Exception as e:
        logger.error(f"Error handling service_efris_synced: {str(e)}", exc_info=True)


@receiver(service_efris_sync_failed)
def handle_service_efris_sync_failed(sender, service, error, **kwargs):
    """
    Handler for failed EFRIS sync
    """
    try:
        logger.error(
            f"Service {service.name} EFRIS sync failed: {error}"
        )

        # Mark service as needing retry
        service.efris_is_uploaded = False
        service.save(update_fields=['efris_is_uploaded'])

    except Exception as e:
        logger.error(f"Error handling service_efris_sync_failed: {str(e)}", exc_info=True)


# ===========================================
# CATEGORY SIGNALS (affect services)
# ===========================================

from .models import Category


@receiver(post_save, sender=Category)
def category_post_save_handler(sender, instance, created, **kwargs):
    """
    When a category is updated, check if services need EFRIS re-sync
    """
    if kwargs.get('raw', False) or created:
        return

    try:
        # Only process service categories
        if instance.category_type != 'service':
            return

        # Check if EFRIS-related fields changed
        if instance.pk:
            old_instance = Category.objects.filter(pk=instance.pk).first()
            if not old_instance:
                return

            efris_changed = (
                    old_instance.efris_commodity_category_code !=
                    instance.efris_commodity_category_code
            )

            if efris_changed:
                # Get all active services in this category
                services_count = instance.services.filter(
                    is_active=True,
                    efris_auto_sync_enabled=True,
                    efris_is_uploaded=True
                ).count()

                if services_count > 0:
                    logger.info(
                        f"Category {instance.name} EFRIS settings changed. "
                        f"{services_count} service(s) may need re-sync."
                    )

                    # Mark services for re-sync
                    instance.services.filter(
                        is_active=True,
                        efris_auto_sync_enabled=True
                    ).update(efris_is_uploaded=False)

    except Exception as e:
        logger.error(f"Error in category post_save handler: {str(e)}", exc_info=True)


# ===========================================
# NOTIFICATION-ENABLED SIGNALS
# ===========================================

def get_current_schema():
    """Get current tenant schema name"""
    try:
        from django.db import connection
        return getattr(connection, 'schema_name', 'public')
    except Exception:
        return 'public'


@receiver(post_save, sender=StockMovement)
def trigger_efris_sync(sender, instance: StockMovement, created, **kwargs):
    """
    Trigger EFRIS sync when a StockMovement is created or updated.
    Skips SALE movements; runs inside the tenant schema context for all other types.
    """
    from .tasks import sync_stock_movement_to_efris

    # Only sync these types, excluding 'SALE'
    allowed_types = ['PURCHASE', 'RETURN', 'TRANSFER_IN', 'TRANSFER_OUT', 'ADJUSTMENT']

    if instance.movement_type not in allowed_types:
        if instance.movement_type == 'SALE':
            print(f"⏭️ Skipping EFRIS sync for SALE movement {instance.id}")
        return

    try:
        # `get_current_schema()` should return the current tenant schema string
        schema_name = get_current_schema()
        sync_stock_movement_to_efris.delay(instance.id, schema_name)
        print(f"🔁 Triggered EFRIS sync for movement {instance.id} in schema '{schema_name}'")
    except Exception as e:
        print(f"⚠️ Failed to trigger EFRIS sync for {instance.id}: {e}")


def send_to_websocket(group_name: str, message_type: str, data: Dict[str, Any],
                      user_specific: bool = False, user_id: Optional[int] = None) -> bool:
    """Send messages to WebSocket groups with error handling"""
    if not channel_layer:
        logger.warning("Channel layer not available, skipping WebSocket message")
        return False

    try:
        if user_specific and user_id:
            group_name = f"{group_name}_user_{user_id}"

        data['timestamp'] = data.get('timestamp', timezone.now().isoformat())

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                'type': message_type,
                'data': data
            }
        )
        logger.debug(f"Sent WebSocket message to {group_name}: {message_type}")
        return True

    except Exception as e:
        logger.error(f"Failed to send WebSocket message to {group_name}: {str(e)}")
        return False


@receiver(post_save, sender=Product)
def auto_register_product_with_efris(sender, instance, created, **kwargs):
    """Auto-register product with EFRIS when created"""
    if kwargs.get('raw', False):
        return

    try:
        company = _get_company_from_context()
        if not company:
            logger.warning(f"Cannot determine tenant for product {instance.sku}")
            return

        if not getattr(company, 'efris_enabled', False):
            return

        if not instance.efris_auto_sync_enabled or not instance.is_active:
            return

        if instance.efris_is_uploaded:
            return

        schema_name = company.schema_name

        from .tasks import register_product_with_efris_async

        transaction.on_commit(
            lambda: register_product_with_efris_async.apply_async(
                args=[instance.id, company.company_id, schema_name],
                countdown=5
            )
        )

        logger.info(
            f"[{schema_name}] Scheduled EFRIS registration for product {instance.sku}"
        )

    except Exception as e:
        logger.error(f"Failed to schedule EFRIS registration: {str(e)}", exc_info=True)


@receiver(pre_save, sender=Product)
def detect_efris_sync_enabled_change(sender, instance, **kwargs):
    """Detect when EFRIS auto-sync is enabled"""
    if not instance.pk:
        return

    try:
        previous = Product.objects.get(pk=instance.pk)
        if not previous.efris_auto_sync_enabled and instance.efris_auto_sync_enabled:
            if not instance.efris_is_uploaded:
                instance._efris_sync_just_enabled = True

    except Product.DoesNotExist:
        pass
    except Exception as e:
        logger.error(f"Error detecting EFRIS sync change: {str(e)}")


# inventory/signals.py - Fix the stock_level_updated signal

@receiver(post_save, sender=Stock)
def stock_level_updated(sender, instance: Stock, created: bool, **kwargs):
    """Handle stock level updates with tenant context and notifications"""
    if kwargs.get('raw', False):
        return

    try:
        schema_name = get_current_schema()

        significant_change = created
        if not created and hasattr(instance, '_original_values'):
            old_quantity = instance._original_values.get('quantity', 0)
            quantity_change = abs(instance.quantity - old_quantity)
            percentage_change = (quantity_change / max(old_quantity, 1)) * 100
            significant_change = quantity_change > 10 or percentage_change > 5

        stock_data = {
            'id': instance.id,
            'product_id': instance.product.id,
            'product_name': instance.product.name,
            'product_sku': instance.product.sku,
            'category': instance.product.category.name if instance.product.category else None,
            'store_id': instance.store.id,
            'store_name': instance.store.name,
            'quantity': float(instance.quantity),
            'low_stock_threshold': float(instance.low_stock_threshold),
            'reorder_quantity': float(instance.reorder_quantity),
            'unit_of_measure': instance.product.unit_of_measure,
            'cost_price': float(instance.product.cost_price),
            'selling_price': float(instance.product.selling_price),
            'total_value': float(instance.quantity * instance.product.cost_price),
            'status': instance.status,
            'stock_percentage': instance.stock_percentage,
            'last_updated': instance.last_updated.isoformat() if instance.last_updated else None,
            'action': 'created' if created else 'updated',
            'significant_change': significant_change,
            'schema_name': schema_name
        }

        if significant_change:
            send_to_websocket('stock_levels', 'stock_level_update', stock_data)

        send_to_websocket(f'stock_levels_store_{instance.store.id}', 'stock_level_update', stock_data)

        if instance.product.category:
            send_to_websocket(
                f'stock_levels_category_{instance.product.category.id}',
                'stock_level_update',
                stock_data
            )

        severity = determine_stock_severity(instance)
        if severity in ['critical', 'warning']:
            alert_data = {
                **stock_data,
                'severity': severity,
                'alert_type': 'stock_level',
                'message': get_stock_alert_message(instance, severity),
                'requires_action': severity == 'critical',
                'recommended_action': get_recommended_action(instance, severity)
            }

            send_to_websocket('inventory_dashboard', 'low_stock_alert', alert_data)
            inventory_alert.send(
                sender=Stock,
                stock=instance,
                severity=severity,
                alert_data=alert_data
            )

            # FIXED: Send notification only to superusers and high-priority users
            try:
                from django.contrib.auth import get_user_model
                User = get_user_model()

                # Get users who should receive notifications (superusers and priority >= 90)
                recipients = User.objects.filter(
                    Q(is_superuser=True) |
                    Q(primary_role__priority__gte=90)
                ).filter(is_active=True)

                for recipient in recipients:
                    if severity == 'critical':
                        # Use template-based notification for critical stock
                        NotificationService.create_from_template(
                            event_type='low_stock',
                            recipient=recipient,
                            context={
                                'product_name': instance.product.name,
                                'current_quantity': instance.quantity,
                                'threshold': instance.low_stock_threshold,
                                'store_name': instance.store.name,
                            },
                            related_object=instance,
                            priority='HIGH',
                            tenant_schema=schema_name
                        )
                    else:
                        # Use direct notification for warnings
                        NotificationService.create_notification(
                            recipient=recipient,
                            title=f'Stock Alert: {instance.product.name}',
                            message=get_stock_alert_message(instance, severity),
                            notification_type='WARNING',
                            priority='MEDIUM',
                            related_object=instance,
                            action_text='View Stock',
                            action_url=f'en/inventory/stock/{instance.id}/',
                            tenant_schema=schema_name
                        )
            except Exception as e:
                logger.error(f"Failed to send stock notification: {str(e)}")

        invalidate_stock_caches(instance, schema_name)

    except Exception as e:
        logger.error(f"Error in stock_level_updated: {str(e)}", exc_info=True)

@receiver(pre_save, sender=Stock)
def store_original_stock_values(sender, instance: Stock, **kwargs):
    """Store original values before save"""
    if instance.pk:
        try:
            original = Stock.objects.get(pk=instance.pk)
            instance._original_values = {
                'quantity': original.quantity,
                'low_stock_threshold': original.low_stock_threshold,
                'reorder_quantity': original.reorder_quantity
            }
        except Stock.DoesNotExist:
            instance._original_values = {}


@receiver(post_save, sender=StockMovement)
def stock_movement_created(sender, instance: StockMovement, created: bool, **kwargs):
    """Handle stock movement creation with notifications"""
    if not created or kwargs.get('raw', False):
        return

    try:
        schema_name = get_current_schema()

        movement_data = {
            'id': instance.id,
            'product_id': instance.product.id,
            'product_name': instance.product.name,
            'product_sku': instance.product.sku,
            'category': instance.product.category.name if instance.product.category else None,
            'store_id': instance.store.id,
            'store_name': instance.store.name,
            'movement_type': instance.movement_type,
            'movement_type_display': instance.get_movement_type_display(),
            'quantity': float(instance.quantity),
            'unit_price': float(instance.unit_price) if instance.unit_price else None,
            'total_value': float(instance.total_value) if instance.total_value else None,
            'unit_of_measure': instance.product.unit_of_measure,
            'reference': instance.reference or '',
            'notes': instance.notes or '',
            'created_at': instance.created_at.isoformat(),
            'created_by': {
                'id': instance.created_by.id,
                'username': instance.created_by.username,
                'full_name': instance.created_by.get_full_name() or instance.created_by.username
            } if instance.created_by else None,
            'impact': determine_movement_impact(instance),
            'schema_name': schema_name
        }

        send_to_websocket('inventory_dashboard', 'movement_notification', movement_data)
        send_to_websocket(
            f'inventory_dashboard_store_{instance.store.id}',
            'movement_notification',
            movement_data
        )

        if instance.created_by:
            send_to_websocket(
                'inventory_dashboard',
                'movement_notification',
                movement_data,
                user_specific=True,
                user_id=instance.created_by.id
            )

        # NOTIFICATION INTEGRATION: High value movement alerts
        if instance.total_value and instance.total_value > 1000:
            high_value_data = {
                **movement_data,
                'alert_type': 'high_value_movement',
                'message': f'High value {instance.get_movement_type_display().lower()}: {instance.product.name}'
            }
            send_to_websocket('inventory_dashboard', 'high_value_alert', high_value_data)

            # Notify store manager for high-value movements
            if instance.store.manager_name and instance.created_by != instance.store.manager_name:
                try:
                    NotificationService.create_notification(
                        recipient=instance.store.manager_name,
                        title=f'High Value {instance.get_movement_type_display()}',
                        message=f'{instance.quantity} units of {instance.product.name} valued at UGX {instance.total_value:,.0f}',
                        notification_type='INFO',
                        priority='MEDIUM',
                        related_object=instance,
                        action_text='View Movement',
                        action_url=f'/en/inventory/movements/',
                        tenant_schema=schema_name
                    )
                except Exception as e:
                    logger.error(f"Failed to send high-value movement notification: {str(e)}")

        update_movement_analytics(instance, schema_name)
        send_dashboard_update()

    except Exception as e:
        logger.error(f"Error in stock_movement_created: {str(e)}", exc_info=True)


@receiver(post_save, sender=Product)
def product_updated(sender, instance: Product, created: bool, **kwargs):
    """Handle product updates with notifications"""
    if kwargs.get('raw', False):
        return

    try:
        schema_name = get_current_schema()

        if created:
            product_data = {
                'id': instance.id,
                'name': instance.name,
                'sku': instance.sku,
                'category': instance.category.name if instance.category else None,
                'supplier': instance.supplier.name if instance.supplier else None,
                'selling_price': float(instance.selling_price),
                'cost_price': float(instance.cost_price),
                'is_active': instance.is_active,
                'action': 'created',
                'schema_name': schema_name
            }

            send_to_websocket('inventory_dashboard', 'product_created', product_data)

            # NOTIFICATION INTEGRATION: New product creation
            try:
                company = _get_company_from_context()
                if company and hasattr(company, 'staff'):
                    # Notify company admins about new product
                    admins = company.staff.filter(is_staff=True, is_active=True)
                    for admin in admins:
                        NotificationService.create_from_template(
                            event_type='product_added',
                            recipient=admin,
                            context={
                                'product_name': instance.name,
                                'product_sku': instance.sku,
                                'category': instance.category.name if instance.category else 'Uncategorized',
                                'supplier': instance.supplier.name if instance.supplier else 'No Supplier',
                            },
                            related_object=instance,
                            tenant_schema=schema_name
                        )
            except Exception as e:
                logger.error(f"Failed to send new product notification: {str(e)}")

        else:
            if hasattr(instance, '_original_values'):
                changes = detect_product_changes(instance)

                if changes:
                    product_data = {
                        'id': instance.id,
                        'name': instance.name,
                        'sku': instance.sku,
                        'changes': changes,
                        'action': 'updated',
                        'schema_name': schema_name
                    }

                    send_to_websocket('inventory_dashboard', 'product_updated', product_data)

                    if 'efris_is_uploaded' in changes:
                        handle_efris_status_change(instance, changes['efris_is_uploaded'])

                    if 'selling_price' in changes or 'cost_price' in changes:
                        handle_price_change(instance, changes)

                        # NOTIFICATION INTEGRATION: Price changes
                        try:
                            if instance.store and instance.store.manager_name:
                                old_price = changes.get('selling_price', {}).get('old', 0)
                                new_price = changes.get('selling_price', {}).get('new', 0)

                                if old_price != new_price:
                                    NotificationService.create_notification(
                                        recipient=instance.store.manager_name,
                                        title=f'Price Updated: {instance.name}',
                                        message=f'Price changed from UGX {old_price:,.0f} to UGX {new_price:,.0f}',
                                        notification_type='INFO',
                                        priority='LOW',
                                        related_object=instance,
                                        action_text='View Product',
                                        action_url=f'/inventory/products/{instance.id}/',
                                        tenant_schema=schema_name
                                    )
                        except Exception as e:
                            logger.error(f"Failed to send price change notification: {str(e)}")

        invalidate_product_caches(instance, schema_name)

    except Exception as e:
        logger.error(f"Error in product_updated: {str(e)}", exc_info=True)


@receiver(pre_save, sender=Product)
def store_original_product_values(sender, instance: Product, **kwargs):
    """Store original product values"""
    if instance.pk:
        try:
            original = Product.objects.get(pk=instance.pk)
            instance._original_values = {
                'name': original.name,
                'selling_price': original.selling_price,
                'cost_price': original.cost_price,
                'is_active': original.is_active,
                'efris_is_uploaded': original.efris_is_uploaded,
                'efris_auto_sync_enabled': original.efris_auto_sync_enabled
            }
        except Product.DoesNotExist:
            instance._original_values = {}


@receiver(post_save, sender=ImportSession)
def import_session_updated(sender, instance: ImportSession, created: bool, **kwargs):
    """Handle import session updates with notifications"""
    if kwargs.get('raw', False):
        return

    try:
        schema_name = get_current_schema()

        progress_percentage = 0
        if instance.total_rows > 0:
            progress_percentage = (instance.processed_rows / instance.total_rows) * 100
        elif instance.status == 'completed':
            progress_percentage = 100

        session_data = {
            'id': instance.id,
            'filename': instance.filename,
            'status': instance.status,
            'import_mode': instance.import_mode,
            'conflict_resolution': instance.conflict_resolution,
            'total_rows': instance.total_rows,
            'processed_rows': instance.processed_rows,
            'created_count': instance.created_count,
            'updated_count': instance.updated_count,
            'skipped_count': instance.skipped_count,
            'error_count': instance.error_count,
            'success_rate': instance.success_rate,
            'duration': str(instance.duration) if instance.duration else None,
            'error_message': instance.error_message,
            'started_at': instance.started_at.isoformat() if instance.started_at else None,
            'completed_at': instance.completed_at.isoformat() if instance.completed_at else None,
            'progress_percentage': round(progress_percentage, 2),
            'estimated_completion': estimate_completion_time(instance) if instance.status == 'processing' else None,
            'schema_name': schema_name
        }

        send_to_websocket(f'import_{instance.id}', 'import_progress_update', session_data)

        send_to_websocket(
            'inventory_dashboard',
            'import_progress_update',
            session_data,
            user_specific=True,
            user_id=instance.user.id
        )

        if instance.status in ['completed', 'failed']:
            completion_data = {
                **session_data,
                'message': get_import_completion_message(instance),
                'summary': {
                    'total_processed': instance.processed_rows,
                    'successful_operations': instance.created_count + instance.updated_count,
                    'failed_operations': instance.error_count,
                    'success_rate': instance.success_rate,
                    'duration': str(instance.duration) if instance.duration else None
                },
                'recommendations': get_import_recommendations(instance)
            }

            message_type = 'import_completed' if instance.status == 'completed' else 'import_failed'
            send_to_websocket(f'import_{instance.id}', message_type, completion_data)

            # NOTIFICATION INTEGRATION: Import completion
            try:
                if instance.user:
                    notification_type = 'SUCCESS' if instance.status == 'completed' else 'ERROR'
                    priority = 'MEDIUM' if instance.status == 'completed' else 'HIGH'

                    NotificationService.create_notification(
                        recipient=instance.user,
                        title=f'Import {instance.status.title()}',
                        message=get_import_completion_message(instance),
                        notification_type=notification_type,
                        priority=priority,
                        related_object=instance,
                        action_text='View Results',
                        action_url=f'/inventory/imports/{instance.id}/',
                        tenant_schema=schema_name
                    )
            except Exception as e:
                logger.error(f"Failed to send import completion notification: {str(e)}")

            if instance.created_count + instance.updated_count > 10:
                send_dashboard_update()

            cache.delete(f'{schema_name}_import_session_{instance.id}')

    except Exception as e:
        logger.error(f"Error in import_session_updated: {str(e)}", exc_info=True)


@receiver(post_save, sender=ImportLog)
def import_log_created(sender, instance: ImportLog, created: bool, **kwargs):
    """Handle import log creation"""
    if not created:
        return

    try:
        important_levels = ['error', 'warning', 'success']

        if instance.level in important_levels or instance.row_number:
            log_data = {
                'session_id': instance.session.id,
                'level': instance.level,
                'message': instance.message,
                'row_number': instance.row_number,
                'timestamp': instance.timestamp.isoformat(),
                'details': instance.details,
                'is_important': instance.level in ['error', 'success']
            }

            send_to_websocket(f'import_{instance.session.id}', 'import_log_update', log_data)

        if instance.level == 'error':
            track_import_errors(instance)

    except Exception as e:
        logger.error(f"Error in import_log_created: {str(e)}", exc_info=True)


@receiver(post_delete, sender=Product)
def product_deleted(sender, instance: Product, **kwargs):
    """Handle product deletion with notifications"""
    try:
        deletion_data = {
            'id': instance.id,
            'name': instance.name,
            'sku': instance.sku,
            'action': 'deleted',
            'message': f'Product "{instance.name}" has been deleted'
        }

        send_to_websocket('inventory_dashboard', 'product_deleted', deletion_data)

        # NOTIFICATION INTEGRATION: Product deletion
        try:
            schema_name = get_current_schema()
            company = _get_company_from_context()
            if company and hasattr(company, 'staff'):
                # Notify company admins about product deletion
                admins = company.staff.filter(is_staff=True, is_active=True)
                for admin in admins:
                    NotificationService.create_notification(
                        recipient=admin,
                        title='Product Deleted',
                        message=f'Product "{instance.name}" (SKU: {instance.sku}) has been deleted',
                        notification_type='WARNING',
                        priority='MEDIUM',
                        action_text='View Inventory',
                        action_url='/inventory/products/',
                        tenant_schema=schema_name
                    )
        except Exception as e:
            logger.error(f"Failed to send product deletion notification: {str(e)}")

        invalidate_product_caches(instance, get_current_schema())

    except Exception as e:
        logger.error(f"Error in product_deleted: {str(e)}", exc_info=True)


@receiver(bulk_stock_update)
def handle_bulk_stock_update(sender, **kwargs):
    """Handle bulk stock updates with notifications"""
    try:
        operation_data = kwargs.get('data', {})
        affected_count = kwargs.get('affected_count', 0)
        operation_type = kwargs.get('operation_type', 'bulk_update')
        user = kwargs.get('user')

        bulk_data = {
            'operation_type': operation_type,
            'affected_count': affected_count,
            'operation_data': operation_data,
            'user': {
                'id': user.id,
                'username': user.username,
                'full_name': user.get_full_name() or user.username
            } if user else None,
            'message': f'Bulk {operation_type} completed. {affected_count} items affected.',
            'success': affected_count > 0
        }

        send_to_websocket('inventory_dashboard', 'bulk_operation_completed', bulk_data)

        if user:
            send_to_websocket(
                'inventory_dashboard',
                'bulk_operation_completed',
                bulk_data,
                user_specific=True,
                user_id=user.id
            )

        # NOTIFICATION INTEGRATION: Bulk operation completion
        if user and affected_count > 0:
            try:
                schema_name = get_current_schema()
                NotificationService.create_notification(
                    recipient=user,
                    title=f'Bulk {operation_type.title()} Completed',
                    message=f'Successfully processed {affected_count} items',
                    notification_type='SUCCESS',
                    priority='LOW',
                    action_text='View Results',
                    action_url='/inventory/bulk-operations/',
                    tenant_schema=schema_name
                )
            except Exception as e:
                logger.error(f"Failed to send bulk operation notification: {str(e)}")

        if affected_count > 5:
            send_dashboard_update()

    except Exception as e:
        logger.error(f"Error in handle_bulk_stock_update: {str(e)}", exc_info=True)


@receiver(inventory_alert)
def handle_inventory_alert(sender, **kwargs):
    """Handle inventory alerts with notifications"""
    try:
        stock = kwargs.get('stock')
        severity = kwargs.get('severity', 'info')
        alert_data = kwargs.get('alert_data', {})

        logger.warning(f"Inventory alert: {severity} - {alert_data.get('message', 'Unknown alert')}")

        schema_name = get_current_schema()
        cache_key = f'{schema_name}_inventory_alerts_history'
        alerts_history = cache.get(cache_key, [])

        alert_record = {
            'timestamp': timezone.now().isoformat(),
            'severity': severity,
            'product_name': stock.product.name if stock else 'Unknown',
            'store_name': stock.store.name if stock else 'Unknown',
            'message': alert_data.get('message', ''),
            'data': alert_data
        }

        alerts_history.insert(0, alert_record)
        alerts_history = alerts_history[:100]
        cache.set(cache_key, alerts_history, timeout=86400)

        # NOTIFICATION INTEGRATION: Critical inventory alerts
        if severity == 'critical' and stock:
            try:
                # Notify store manager and company admins
                recipients = []
                if stock.store.manager_name:
                    recipients.append(stock.store.manager_name)

                # Add company admins
                company = _get_company_from_context()
                if company and hasattr(company, 'staff'):
                    admins = company.staff.filter(is_staff=True, is_active=True)
                    recipients.extend(admins)

                for recipient in set(recipients):
                    InventoryNotifications.notify_out_of_stock(stock.product, stock)
            except Exception as e:
                logger.error(f"Failed to send critical inventory alert: {str(e)}")

    except Exception as e:
        logger.error(f"Error in handle_inventory_alert: {str(e)}", exc_info=True)


@receiver(post_save, sender=Stock)
def handle_efris_stock_sync(sender, instance: Stock, created: bool, **kwargs):
    """Handle EFRIS stock synchronization"""
    try:
        if (hasattr(instance.store, 'report_stock_movements') and
                instance.store.report_stock_movements and
                hasattr(instance.store, 'efris_enabled') and
                instance.store.efris_enabled and
                instance.product.efris_auto_sync_enabled):

            if not created and hasattr(instance, '_original_values'):
                old_quantity = instance._original_values.get('quantity', 0)
                quantity_change = abs(instance.quantity - old_quantity)

                if quantity_change > 0:
                    instance.efris_sync_required = True
                    instance.save(update_fields=['efris_sync_required'])

                    efris_sync_required.send(
                        sender=Stock,
                        stock=instance,
                        change_type='stock_level',
                        old_quantity=old_quantity,
                        new_quantity=instance.quantity
                    )

    except Exception as e:
        logger.error(f"Error in EFRIS stock sync: {str(e)}", exc_info=True)


@receiver(efris_sync_required)
def queue_efris_sync_task(sender, **kwargs):
    """Queue EFRIS synchronization tasks"""
    try:
        stock = kwargs.get('stock')
        change_type = kwargs.get('change_type', 'unknown')

        if stock:
            from .tasks import sync_efris_products

            schema_name = connection.schema_name

            sync_efris_products.apply_async(
                kwargs={
                    'schema_name': schema_name,
                    'batch_size': 1,
                    'dry_run': False,
                },
                countdown=30
            )

            logger.info(f"[{schema_name}] Queued EFRIS sync for {stock.product.name} due to {change_type}")

    except Exception as e:
        logger.error(f"Error queuing EFRIS sync: {str(e)}", exc_info=True)


@receiver(post_save, sender=StockMovement)
def detect_batch_operations(sender, instance: StockMovement, created: bool, **kwargs):
    """Detect and handle batch operations"""
    if not created:
        return

    try:
        if instance.reference and instance.reference.startswith('BULK-'):
            schema_name = get_current_schema()
            cache_key = f'{schema_name}_batch_operation_{instance.reference}'
            batch_data = cache.get(cache_key, {'count': 0, 'movements': []})

            batch_data['count'] += 1
            batch_data['movements'].append({
                'id': instance.id,
                'product_name': instance.product.name,
                'store_name': instance.store.name,
                'quantity': float(instance.quantity),
                'timestamp': instance.created_at.isoformat()
            })

            cache.set(cache_key, batch_data, timeout=300)

            if batch_data['count'] >= 5 or batch_data['count'] % 10 == 0:
                batch_notification = {
                    'reference': instance.reference,
                    'count': batch_data['count'],
                    'latest_movements': batch_data['movements'][-3:],
                    'message': f'Batch operation in progress: {batch_data["count"]} items processed'
                }

                send_to_websocket(
                    'inventory_dashboard',
                    'batch_operation_progress',
                    batch_notification
                )

    except Exception as e:
        logger.error(f"Error in batch operation detection: {str(e)}", exc_info=True)


@receiver(post_save, sender=ImportSession)
def monitor_import_performance(sender, instance: ImportSession, created: bool, **kwargs):
    """Monitor import performance"""
    if instance.status == 'processing' and instance.started_at:
        try:
            elapsed = (timezone.now() - instance.started_at).total_seconds()

            if elapsed > 300 and instance.processed_rows > 0:
                processing_rate = instance.processed_rows / elapsed
                estimated_total_time = instance.total_rows / processing_rate

                if estimated_total_time > 1800:
                    performance_alert = {
                        'session_id': instance.id,
                        'filename': instance.filename,
                        'elapsed_time': elapsed,
                        'processing_rate': round(processing_rate, 2),
                        'estimated_total_time': estimated_total_time,
                        'message': 'Import is taking longer than expected',
                        'recommendation': 'Consider breaking large imports into smaller batches'
                    }

                    send_to_websocket(
                        f'import_{instance.id}',
                        'performance_warning',
                        performance_alert
                    )

        except Exception as e:
            logger.error(f"Error in import performance monitoring: {str(e)}")


@receiver(post_delete, sender=ImportSession)
def cleanup_import_data(sender, instance: ImportSession, **kwargs):
    """Clean up related import data"""
    try:
        schema_name = get_current_schema()
        cache_keys = [
            f'{schema_name}_import_session_{instance.id}',
            f'{schema_name}_import_logs_{instance.id}',
            f'{schema_name}_import_results_{instance.id}'
        ]

        for key in cache_keys:
            cache.delete(key)

        logger.info(f"Cleaned up import data for session {instance.id}")

    except Exception as e:
        logger.error(f"Error cleaning up import data: {str(e)}")


# Helper Functions

def _get_company_from_context():
    """Get company/tenant from current context"""
    try:
        from django.db import connection
        if hasattr(connection, 'tenant') and connection.tenant:
            return connection.tenant
        return None
    except Exception:
        return None


def send_dashboard_update():
    """Send dashboard statistics update"""
    try:
        schema_name = get_current_schema()
        cache_key = f'{schema_name}_dashboard_stats_update'
        if cache.get(cache_key):
            return

        today = timezone.now().date()
        week_ago = today - timezone.timedelta(days=7)
        month_ago = today - timezone.timedelta(days=30)

        product_stats = Product.objects.aggregate(
            total=Count('id', filter=Q(is_active=True)),
            inactive=Count('id', filter=Q(is_active=False))
        )

        stock_stats = Stock.objects.aggregate(
            total_items=Count('id'),
            low_stock=Count('id', filter=Q(quantity__lte=F('low_stock_threshold'))),
            out_of_stock=Count('id', filter=Q(quantity=0)),
            critical_stock=Count('id', filter=Q(quantity__lte=F('low_stock_threshold') / 2)),
            total_value=Sum(F('quantity') * F('product__cost_price')),
            avg_stock_level=Avg('quantity')
        )

        movement_stats = StockMovement.objects.aggregate(
            today=Count('id', filter=Q(created_at__date=today)),
            week=Count('id', filter=Q(created_at__date__gte=week_ago)),
            month=Count('id', filter=Q(created_at__date__gte=month_ago))
        )

        stats = {
            'products': {
                'total': product_stats['total'] or 0,
                'active': product_stats['total'] or 0,
                'inactive': product_stats['inactive'] or 0,
                'low_stock': stock_stats['low_stock'] or 0,
                'out_of_stock': stock_stats['out_of_stock'] or 0,
                'critical_stock': stock_stats['critical_stock'] or 0,
            },
            'inventory': {
                'total_items': stock_stats['total_items'] or 0,
                'total_value': float(stock_stats['total_value'] or 0),
                'avg_stock_level': float(stock_stats['avg_stock_level'] or 0),
                'stock_health': calculate_stock_health(stock_stats),
            },
            'movements': {
                'today': movement_stats['today'] or 0,
                'this_week': movement_stats['week'] or 0,
                'this_month': movement_stats['month'] or 0,
            },
            'alerts': {
                'critical_count': stock_stats['critical_stock'] or 0,
                'warning_count': (stock_stats['low_stock'] or 0) - (stock_stats['critical_stock'] or 0),
                'total_alerts': stock_stats['low_stock'] or 0,
            },
            'last_updated': timezone.now().isoformat(),
            'schema_name': schema_name
        }

        send_to_websocket('inventory_dashboard', 'dashboard_update', stats)
        cache.set(cache_key, True, timeout=30)
        cache.set(f'{schema_name}_dashboard_stats_cached', stats, timeout=120)

    except Exception as e:
        logger.error(f"Error in send_dashboard_update: {str(e)}", exc_info=True)


def determine_stock_severity(stock: Stock) -> str:
    """Determine stock alert severity"""
    if stock.quantity == 0:
        return 'critical'
    elif stock.quantity <= (stock.low_stock_threshold / 2):
        return 'critical'
    elif stock.quantity <= stock.low_stock_threshold:
        return 'warning'
    return 'normal'


def get_stock_alert_message(stock: Stock, severity: str) -> str:
    """Generate contextual alert message"""
    if severity == 'critical':
        if stock.quantity == 0:
            return f"{stock.product.name} is out of stock at {stock.store.name}"
        else:
            return f"{stock.product.name} is critically low at {stock.store.name} ({stock.quantity} remaining)"
    elif severity == 'warning':
        return f"{stock.product.name} is running low at {stock.store.name} ({stock.quantity} remaining)"
    return ""


def get_recommended_action(stock: Stock, severity: str) -> str:
    """Get recommended action for stock alert"""
    if severity == 'critical':
        return f"Order {stock.reorder_quantity} units immediately"
    elif severity == 'warning':
        return f"Consider ordering {stock.reorder_quantity} units"
    return ""


def determine_movement_impact(movement: StockMovement) -> str:
    """Determine impact level of stock movement"""
    if movement.total_value:
        value = abs(float(movement.total_value))
        if value > 5000:
            return 'high'
        elif value > 1000:
            return 'medium'
    return 'low'


def detect_product_changes(instance: Product) -> Dict[str, Any]:
    """Detect significant changes in product"""
    changes = {}

    if hasattr(instance, '_original_values'):
        original = instance._original_values

        for field in ['name', 'selling_price', 'cost_price', 'is_active', 'efris_is_uploaded']:
            old_value = original.get(field)
            new_value = getattr(instance, field)

            if old_value != new_value:
                changes[field] = {
                    'old': old_value,
                    'new': new_value
                }

    return changes


def handle_efris_status_change(product: Product, change: Dict[str, Any]):
    """Handle EFRIS status changes"""
    efris_data = {
        'product_id': product.id,
        'product_name': product.name,
        'product_sku': product.sku,
        'efris_status': product.efris_status_display,
        'was_uploaded': change['old'],
        'is_uploaded': change['new'],
        'change_type': 'uploaded' if change['new'] else 'reset'
    }

    send_to_websocket('inventory_dashboard', 'efris_status_update', efris_data)


def handle_price_change(product: Product, changes: Dict[str, Any]):
    """Handle product price changes"""
    price_data = {
        'product_id': product.id,
        'product_name': product.name,
        'product_sku': product.sku,
        'changes': changes,
        'message': f'Price updated for {product.name}'
    }

    send_to_websocket('inventory_dashboard', 'price_update', price_data)


def update_movement_analytics(movement: StockMovement, schema_name: str):
    """Update movement analytics in cache"""
    try:
        cache_key = f'{schema_name}_movement_analytics_daily'
        daily_data = cache.get(cache_key, {})

        today = timezone.now().date().isoformat()
        if today not in daily_data:
            daily_data[today] = {'count': 0, 'types': {}}

        daily_data[today]['count'] += 1
        movement_type = movement.movement_type
        if movement_type not in daily_data[today]['types']:
            daily_data[today]['types'][movement_type] = 0
        daily_data[today]['types'][movement_type] += 1

        if len(daily_data) > 30:
            oldest_date = min(daily_data.keys())
            del daily_data[oldest_date]

        cache.set(cache_key, daily_data, timeout=86400)

    except Exception as e:
        logger.error(f"Error updating movement analytics: {str(e)}")


def estimate_completion_time(session: ImportSession) -> Optional[str]:
    """Estimate import completion time"""
    if session.status != 'processing' or not session.started_at or session.processed_rows == 0:
        return None

    try:
        elapsed = (timezone.now() - session.started_at).total_seconds()
        processing_rate = session.processed_rows / elapsed
        remaining_rows = session.total_rows - session.processed_rows

        if processing_rate > 0:
            eta_seconds = remaining_rows / processing_rate
            eta = timezone.now() + timezone.timedelta(seconds=eta_seconds)
            return eta.isoformat()
    except:
        pass

    return None


def get_import_completion_message(session: ImportSession) -> str:
    """Generate import completion message"""
    if session.status == 'completed':
        return f'Import completed successfully! Processed {session.processed_rows} rows with {session.success_rate:.1f}% success rate.'
    elif session.status == 'failed':
        return f'Import failed: {session.error_message or "Unknown error"}'
    return f'Import {session.status}'


def get_import_recommendations(session: ImportSession) -> list:
    """Generate recommendations based on import results"""
    recommendations = []

    if session.error_count > 0:
        error_rate = (session.error_count / session.total_rows) * 100
        if error_rate > 20:
            recommendations.append("Consider reviewing your data format and column mapping")
        if error_rate > 50:
            recommendations.append("High error rate detected - please check import file structure")

    if session.skipped_count > session.created_count + session.updated_count:
        recommendations.append("Many items were skipped - consider using 'merge' conflict resolution")

    if session.success_rate == 100 and session.total_rows > 100:
        recommendations.append("Perfect import! Consider using this file as a template for future imports")

    return recommendations


def track_import_errors(log: ImportLog):
    """Track import error patterns"""
    try:
        schema_name = get_current_schema()
        cache_key = f'{schema_name}_import_error_patterns'
        error_patterns = cache.get(cache_key, {})

        error_type = 'general'
        message = log.message.lower()

        if 'missing' in message:
            error_type = 'missing_data'
        elif 'duplicate' in message:
            error_type = 'duplicate'
        elif 'invalid' in message:
            error_type = 'validation'
        elif 'not found' in message:
            error_type = 'not_found'

        if error_type not in error_patterns:
            error_patterns[error_type] = 0
        error_patterns[error_type] += 1

        cache.set(cache_key, error_patterns, timeout=3600)

    except Exception as e:
        logger.error(f"Error tracking import errors: {str(e)}")


def calculate_stock_health(stock_stats: Dict[str, Any]) -> str:
    """Calculate overall stock health indicator"""
    total_items = stock_stats.get('total_items', 0)
    if total_items == 0:
        return 'unknown'

    critical_percentage = (stock_stats.get('critical_stock', 0) / total_items) * 100
    low_stock_percentage = (stock_stats.get('low_stock', 0) / total_items) * 100

    if critical_percentage > 10:
        return 'critical'
    elif low_stock_percentage > 25:
        return 'poor'
    elif low_stock_percentage > 10:
        return 'fair'
    else:
        return 'good'


def invalidate_stock_caches(stock: Stock, schema_name: str):
    """Invalidate caches related to stock changes"""
    try:
        cache_keys = [
            f'{schema_name}_stock_levels_{stock.store.id}',
            f'{schema_name}_dashboard_stats_{stock.store.id}',
            f'{schema_name}_inventory_dashboard_stats',
            f'{schema_name}_low_stock_report',
            f'{schema_name}_product_stock_{stock.product.id}',
            f'{schema_name}_store_inventory_{stock.store.id}'
        ]

        for key in cache_keys:
            cache.delete(key)

    except Exception as e:
        logger.error(f"Error invalidating stock caches: {str(e)}")


def invalidate_product_caches(product: Product, schema_name: str):
    """Invalidate caches related to product changes"""
    try:
        cache_keys = [
            f'{schema_name}_product_details_{product.id}',
            f'{schema_name}_product_stock_levels_{product.id}',
            f'{schema_name}_inventory_dashboard_stats',
            f'{schema_name}_product_autocomplete_cache',
            f'{schema_name}_category_products_{product.category.id}' if product.category else None
        ]

        for key in cache_keys:
            if key:
                cache.delete(key)

    except Exception as e:
        logger.error(f"Error invalidating product caches: {str(e)}")


# ===========================================
# SIGNAL CONNECTORS
# ===========================================

def connect_service_signals():
    """
    Connect all service signals
    Call this in apps.py ready() method
    """
    # Signals are connected via decorators above
    logger.info("Service signals connected")


def disconnect_service_signals():
    """
    Disconnect service signals (useful for testing)
    """
    from django.db.models.signals import post_save, pre_save, post_delete

    post_save.disconnect(service_post_save_handler, sender=Service)
    pre_save.disconnect(service_pre_save_handler, sender=Service)
    post_delete.disconnect(service_post_delete_handler, sender=Service)
    post_save.disconnect(category_post_save_handler, sender=Category)

    logger.info("Service signals disconnected")