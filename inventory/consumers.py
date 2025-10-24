import json
import asyncio
import logging
from typing import Optional, Dict, Any, List
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.core.serializers.json import DjangoJSONEncoder
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta, datetime

logger = logging.getLogger(__name__)


class BaseInventoryConsumer(AsyncWebsocketConsumer):
    """Base consumer with common functionality"""

    async def connect(self):
        from django.contrib.auth.models import AnonymousUser

        self.user = self.scope["user"]
        if isinstance(self.user, AnonymousUser) or not self.user.is_authenticated:
            await self.close(code=4001)  # Unauthorized
            return

        # Check user permissions
        if not await self.check_permissions():
            await self.close(code=4003)  # Forbidden
            return

        await self.setup_connection()
        await self.accept()
        await self.send_initial_data()

    async def setup_connection(self):
        """Override in subclasses"""
        pass

    async def send_initial_data(self):
        """Override in subclasses"""
        pass

    @database_sync_to_async
    def check_permissions(self) -> bool:
        """Check if user has required permissions"""
        return self.user.has_perm('inventory.view_product')

    async def send_error(self, error_message: str, error_code: str = "GENERAL_ERROR"):
        """Send standardized error message"""
        await self.send(text_data=json.dumps({
            'type': 'error',
            'error_code': error_code,
            'message': error_message,
            'timestamp': timezone.now().isoformat()
        }, cls=DjangoJSONEncoder))


class ImportProgressConsumer(BaseInventoryConsumer):
    """WebSocket consumer for real-time import progress updates"""

    async def setup_connection(self):
        try:
            self.import_session_id = int(self.scope['url_route']['kwargs']['session_id'])
        except (KeyError, ValueError):
            await self.close(code=4000)  # Bad request
            return

        # Verify session belongs to user
        if not await self.verify_session_ownership():
            await self.close(code=4003)  # Forbidden
            return

        self.room_group_name = f'import_{self.import_session_id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

    async def send_initial_data(self):
        """Send current import status"""
        await self.send_import_status()

    async def disconnect(self, close_code):
        # Leave room group
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')

            if message_type == 'get_status':
                await self.send_import_status()
            elif message_type == 'cancel_import':
                success = await self.cancel_import()
                await self.send(text_data=json.dumps({
                    'type': 'cancel_response',
                    'success': success,
                    'message': 'Import cancelled successfully' if success else 'Failed to cancel import'
                }))
            else:
                await self.send_error(f"Unknown message type: {message_type}", "UNKNOWN_MESSAGE_TYPE")

        except json.JSONDecodeError:
            await self.send_error('Invalid JSON format', "INVALID_JSON")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {str(e)}")
            await self.send_error('Internal server error', "INTERNAL_ERROR")

    async def send_import_status(self):
        """Send current import session status"""
        try:
            session_data = await self.get_import_session()
            if session_data:
                await self.send(text_data=json.dumps({
                    'type': 'import_status',
                    'data': session_data,
                    'timestamp': timezone.now().isoformat()
                }, cls=DjangoJSONEncoder))
            else:
                await self.send_error('Import session not found', "SESSION_NOT_FOUND")
        except Exception as e:
            logger.error(f"Error sending import status: {str(e)}")
            await self.send_error('Failed to fetch import status', "STATUS_ERROR")

    # WebSocket event handlers
    async def import_progress_update(self, event):
        """Send progress update to WebSocket"""
        await self.send(text_data=json.dumps({
            'type': 'progress_update',
            'data': event['data'],
            'timestamp': timezone.now().isoformat()
        }, cls=DjangoJSONEncoder))

    async def import_completed(self, event):
        """Send completion notification"""
        await self.send(text_data=json.dumps({
            'type': 'import_completed',
            'data': event['data'],
            'timestamp': timezone.now().isoformat()
        }, cls=DjangoJSONEncoder))

    async def import_error(self, event):
        """Send error notification"""
        await self.send(text_data=json.dumps({
            'type': 'import_error',
            'data': event['data'],
            'timestamp': timezone.now().isoformat()
        }, cls=DjangoJSONEncoder))

    @database_sync_to_async
    def verify_session_ownership(self) -> bool:
        """Verify that the import session belongs to the current user"""
        from .models import ImportSession

        try:
            ImportSession.objects.get(id=self.import_session_id, user=self.user)
            return True
        except ImportSession.DoesNotExist:
            return False

    @database_sync_to_async
    def get_import_session(self) -> Optional[Dict[str, Any]]:
        """Get import session data with caching"""
        from .models import ImportSession
        from .serializers import ImportSessionSerializer

        cache_key = f'import_session_{self.import_session_id}'
        cached_data = cache.get(cache_key)

        if cached_data and cached_data.get('status') not in ['processing']:
            return cached_data

        try:
            session = ImportSession.objects.select_related('user').get(
                id=self.import_session_id,
                user=self.user
            )
            serializer = ImportSessionSerializer(session)
            data = serializer.data

            # Cache completed sessions for longer
            cache_timeout = 300 if session.status == 'processing' else 1800
            cache.set(cache_key, data, cache_timeout)

            return data
        except ImportSession.DoesNotExist:
            return None

    @database_sync_to_async
    def cancel_import(self) -> bool:
        """Cancel import session with better error handling"""
        from .models import ImportSession

        try:
            session = ImportSession.objects.select_for_update().get(
                id=self.import_session_id,
                user=self.user
            )
            if session.status in ['pending', 'processing']:
                session.status = 'failed'
                session.error_message = 'Cancelled by user'
                session.completed_at = timezone.now()
                session.save(update_fields=['status', 'error_message', 'completed_at'])

                # Clear cache
                cache.delete(f'import_session_{self.import_session_id}')
                return True
        except ImportSession.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f"Error cancelling import: {str(e)}")

        return False


class InventoryDashboardConsumer(BaseInventoryConsumer):
    """WebSocket consumer for real-time dashboard updates"""

    async def setup_connection(self):
        self.room_group_name = f'inventory_dashboard_user_{self.user.id}'

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

    async def send_initial_data(self):
        """Send initial dashboard data"""
        await self.send_dashboard_data()

    async def disconnect(self, close_code):
        # Leave room group
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')

            if message_type == 'get_dashboard_data':
                await self.send_dashboard_data()
            elif message_type == 'subscribe_alerts':
                await self.send_stock_alerts()
            elif message_type == 'get_recent_movements':
                limit = text_data_json.get('limit', 10)
                await self.send_recent_movements(limit)
            else:
                await self.send_error(f"Unknown message type: {message_type}", "UNKNOWN_MESSAGE_TYPE")

        except json.JSONDecodeError:
            await self.send_error('Invalid JSON format', "INVALID_JSON")
        except Exception as e:
            logger.error(f"Error processing dashboard message: {str(e)}")
            await self.send_error('Internal server error', "INTERNAL_ERROR")

    async def send_dashboard_data(self):
        """Send dashboard statistics with caching"""
        try:
            stats = await self.get_dashboard_stats()
            await self.send(text_data=json.dumps({
                'type': 'dashboard_data',
                'data': stats,
                'timestamp': timezone.now().isoformat()
            }, cls=DjangoJSONEncoder))
        except Exception as e:
            logger.error(f"Error sending dashboard data: {str(e)}")
            await self.send_error('Failed to fetch dashboard data', "DASHBOARD_ERROR")

    async def send_stock_alerts(self):
        """Send stock alerts"""
        try:
            alerts = await self.get_stock_alerts()
            await self.send(text_data=json.dumps({
                'type': 'stock_alerts',
                'data': alerts,
                'count': len(alerts),
                'timestamp': timezone.now().isoformat()
            }, cls=DjangoJSONEncoder))
        except Exception as e:
            logger.error(f"Error sending stock alerts: {str(e)}")
            await self.send_error('Failed to fetch stock alerts', "ALERTS_ERROR")

    async def send_recent_movements(self, limit: int = 10):
        """Send recent stock movements"""
        try:
            movements = await self.get_recent_movements(limit)
            await self.send(text_data=json.dumps({
                'type': 'recent_movements',
                'data': movements,
                'count': len(movements),
                'timestamp': timezone.now().isoformat()
            }, cls=DjangoJSONEncoder))
        except Exception as e:
            logger.error(f"Error sending recent movements: {str(e)}")
            await self.send_error('Failed to fetch recent movements', "MOVEMENTS_ERROR")

    # WebSocket event handlers
    async def stock_update(self, event):
        """Send stock update notification"""
        await self.send(text_data=json.dumps({
            'type': 'stock_update',
            'data': event['data'],
            'timestamp': timezone.now().isoformat()
        }, cls=DjangoJSONEncoder))

    async def low_stock_alert(self, event):
        """Send low stock alert"""
        await self.send(text_data=json.dumps({
            'type': 'low_stock_alert',
            'data': event['data'],
            'timestamp': timezone.now().isoformat()
        }, cls=DjangoJSONEncoder))

    async def movement_notification(self, event):
        """Send stock movement notification"""
        await self.send(text_data=json.dumps({
            'type': 'movement_notification',
            'data': event['data'],
            'timestamp': timezone.now().isoformat()
        }, cls=DjangoJSONEncoder))

    @database_sync_to_async
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get dashboard statistics with caching"""
        cache_key = f'dashboard_stats_{self.user.id}'
        cached_stats = cache.get(cache_key)

        if cached_stats:
            return cached_stats

        from django.db.models import Count, Sum, F, Q
        from .models import Stock, Product, StockMovement

        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        # Get stats efficiently with single queries
        product_stats = Product.objects.filter(is_active=True).aggregate(
            total_products=Count('id'),
            total_active=Count('id', filter=Q(is_active=True))
        )

        stock_stats = Stock.objects.aggregate(
            total_stock_items=Count('id'),
            low_stock_count=Count('id', filter=Q(quantity__lte=F('low_stock_threshold'))),
            out_of_stock_count=Count('id', filter=Q(quantity=0)),
            total_stock_value=Sum(F('quantity') * F('product__cost_price')),
            critical_items=Count('id', filter=Q(quantity__lte=F('low_stock_threshold') / 2))
        )

        movement_stats = StockMovement.objects.aggregate(
            today_movements=Count('id', filter=Q(created_at__date=today)),
            week_movements=Count('id', filter=Q(created_at__date__gte=week_ago)),
            month_movements=Count('id', filter=Q(created_at__date__gte=month_ago))
        )

        stats = {
            'products': {
                'total': product_stats['total_products'] or 0,
                'active': product_stats['total_active'] or 0,
                'low_stock': stock_stats['low_stock_count'] or 0,
                'out_of_stock': stock_stats['out_of_stock_count'] or 0,
                'critical': stock_stats['critical_items'] or 0,
            },
            'inventory': {
                'total_items': stock_stats['total_stock_items'] or 0,
                'total_value': float(stock_stats['total_stock_value'] or 0),
                'low_stock_percentage': round(
                    (stock_stats['low_stock_count'] or 0) / max(stock_stats['total_stock_items'] or 1, 1) * 100, 2
                )
            },
            'movements': {
                'today': movement_stats['today_movements'] or 0,
                'this_week': movement_stats['week_movements'] or 0,
                'this_month': movement_stats['month_movements'] or 0,
            },
            'alerts': {
                'critical_count': stock_stats['out_of_stock_count'] or 0,
                'warning_count': (stock_stats['low_stock_count'] or 0) - (stock_stats['out_of_stock_count'] or 0)
            },
            'last_updated': timezone.now().isoformat()
        }

        # Cache for 2 minutes
        cache.set(cache_key, stats, 120)
        return stats

    @database_sync_to_async
    def get_stock_alerts(self) -> List[Dict[str, Any]]:
        """Get current stock alerts with caching"""
        cache_key = f'stock_alerts_{self.user.id}'
        cached_alerts = cache.get(cache_key)

        if cached_alerts:
            return cached_alerts

        from django.db.models import Q, F
        from .models import Stock

        alerts = Stock.objects.select_related(
            'product', 'store'
        ).filter(
            Q(quantity=0) | Q(quantity__lte=F('low_stock_threshold'))
        ).order_by('quantity', 'product__name')[:20]

        alert_data = []
        for alert in alerts:
            severity = 'critical' if alert.quantity == 0 else 'warning'
            if alert.quantity > 0 and alert.quantity <= (alert.low_stock_threshold / 2):
                severity = 'critical'

            alert_data.append({
                'id': alert.id,
                'product_name': alert.product.name,
                'product_sku': alert.product.sku,
                'store_name': alert.store.name,
                'current_stock': float(alert.quantity),
                'threshold': float(alert.low_stock_threshold),
                'unit_of_measure': alert.product.unit_of_measure,
                'severity': severity,
                'stock_percentage': round(
                    (alert.quantity / max(alert.low_stock_threshold, 1)) * 100, 1
                ),
                'cost_per_unit': float(alert.product.cost_price),
                'total_value_at_risk': float(alert.quantity * alert.product.cost_price)
            })

        # Cache for 1 minute
        cache.set(cache_key, alert_data, 60)
        return alert_data

    @database_sync_to_async
    def get_recent_movements(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent stock movements"""
        from .models import StockMovement

        movements = StockMovement.objects.select_related(
            'product', 'store', 'created_by'
        ).order_by('-created_at')[:limit]

        movement_data = []
        for movement in movements:
            movement_data.append({
                'id': movement.id,
                'product_name': movement.product.name,
                'product_sku': movement.product.sku,
                'store_name': movement.store.name,
                'movement_type': movement.movement_type,
                'movement_type_display': movement.get_movement_type_display(),
                'quantity': float(movement.quantity),
                'unit_price': float(movement.unit_price) if movement.unit_price else None,
                'total_value': float(movement.total_value) if movement.total_value else None,
                'reference': movement.reference or '',
                'created_at': movement.created_at.isoformat(),
                'created_by': {
                    'id': movement.created_by.id,
                    'username': movement.created_by.username,
                    'full_name': movement.created_by.get_full_name() or movement.created_by.username
                }
            })

        return movement_data


class StockLevelsConsumer(BaseInventoryConsumer):
    """WebSocket consumer for real-time stock level updates"""

    async def setup_connection(self):
        # Parse query string for filters
        query_string = self.scope.get('query_string', b'').decode('utf-8')
        self.filters = self._parse_query_params(query_string)

        self.room_group_name = self._get_room_name()

        # Join room group
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

    async def send_initial_data(self):
        """Send initial stock data"""
        await self.send_stock_levels()

    def _parse_query_params(self, query_string: str) -> Dict[str, str]:
        """Parse query parameters safely"""
        params = {}
        if query_string:
            try:
                for param in query_string.split('&'):
                    if '=' in param:
                        key, value = param.split('=', 1)
                        params[key] = value
            except Exception:
                pass
        return params

    def _get_room_name(self) -> str:
        """Generate room name based on filters"""
        room_name = f'stock_levels_user_{self.user.id}'

        if self.filters.get('store'):
            room_name += f'_store_{self.filters["store"]}'
        if self.filters.get('category'):
            room_name += f'_category_{self.filters["category"]}'

        return room_name

    async def disconnect(self, close_code):
        # Leave room group
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')

            if message_type == 'get_stock_levels':
                await self.send_stock_levels()
            elif message_type == 'update_filters':
                new_filters = text_data_json.get('filters', {})
                await self.update_filters(new_filters)
            elif message_type == 'get_product_stock':
                product_id = text_data_json.get('product_id')
                if product_id:
                    await self.send_product_stock(product_id)
            else:
                await self.send_error(f"Unknown message type: {message_type}", "UNKNOWN_MESSAGE_TYPE")

        except json.JSONDecodeError:
            await self.send_error('Invalid JSON format', "INVALID_JSON")
        except Exception as e:
            logger.error(f"Error processing stock levels message: {str(e)}")
            await self.send_error('Internal server error', "INTERNAL_ERROR")

    async def send_stock_levels(self):
        """Send current stock levels"""
        try:
            stock_data = await self.get_stock_levels()
            await self.send(text_data=json.dumps({
                'type': 'stock_levels',
                'data': stock_data,
                'filters': self.filters,
                'count': len(stock_data),
                'timestamp': timezone.now().isoformat()
            }, cls=DjangoJSONEncoder))
        except Exception as e:
            logger.error(f"Error sending stock levels: {str(e)}")
            await self.send_error('Failed to fetch stock levels', "STOCK_ERROR")

    async def send_product_stock(self, product_id: str):
        """Send stock levels for a specific product"""
        try:
            stock_data = await self.get_product_stock_levels(product_id)
            await self.send(text_data=json.dumps({
                'type': 'product_stock',
                'product_id': product_id,
                'data': stock_data,
                'timestamp': timezone.now().isoformat()
            }, cls=DjangoJSONEncoder))
        except Exception as e:
            logger.error(f"Error sending product stock: {str(e)}")
            await self.send_error('Failed to fetch product stock', "PRODUCT_STOCK_ERROR")

    # WebSocket event handlers
    async def stock_level_update(self, event):
        """Send stock level update"""
        await self.send(text_data=json.dumps({
            'type': 'stock_level_update',
            'data': event['data'],
            'timestamp': timezone.now().isoformat()
        }, cls=DjangoJSONEncoder))

    async def update_filters(self, new_filters: Dict[str, str]):
        """Update filters and rejoin appropriate room"""
        # Leave current room
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

        # Update filters and room name
        self.filters.update(new_filters)
        self.room_group_name = self._get_room_name()

        # Join new room
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        # Send updated data
        await self.send_stock_levels()

    @database_sync_to_async
    def get_stock_levels(self) -> List[Dict[str, Any]]:
        """Get stock levels data with filtering and caching"""
        cache_key = f'stock_levels_{hash(frozenset(self.filters.items()))}_{self.user.id}'
        cached_data = cache.get(cache_key)

        if cached_data:
            return cached_data

        from .models import Stock

        queryset = Stock.objects.select_related(
            'product', 'product__category', 'store'
        ).order_by('product__name')

        # Apply filters
        if self.filters.get('store'):
            try:
                store_id = int(self.filters['store'])
                queryset = queryset.filter(store_id=store_id)
            except ValueError:
                pass

        if self.filters.get('category'):
            try:
                category_id = int(self.filters['category'])
                queryset = queryset.filter(product__category_id=category_id)
            except ValueError:
                pass

        if self.filters.get('status'):
            status = self.filters['status']
            if status == 'low_stock':
                queryset = queryset.filter(quantity__lte=F('low_stock_threshold'))
            elif status == 'out_of_stock':
                queryset = queryset.filter(quantity=0)
            elif status == 'in_stock':
                queryset = queryset.filter(quantity__gt=F('low_stock_threshold'))

        # Limit results for performance
        stock_data = []
        for stock in queryset[:100]:
            stock_data.append({
                'id': stock.id,
                'product_id': stock.product.id,
                'product_name': stock.product.name,
                'product_sku': stock.product.sku,
                'category': stock.product.category.name if stock.product.category else None,
                'store_id': stock.store.id,
                'store_name': stock.store.name,
                'quantity': float(stock.quantity),
                'low_stock_threshold': float(stock.low_stock_threshold),
                'reorder_quantity': float(stock.reorder_quantity),
                'unit_of_measure': stock.product.unit_of_measure,
                'cost_price': float(stock.product.cost_price),
                'selling_price': float(stock.product.selling_price),
                'total_value': float(stock.quantity * stock.product.cost_price),
                'status': stock.status,
                'stock_percentage': stock.stock_percentage,
                'last_updated': stock.last_updated.isoformat() if stock.last_updated else None
            })

        # Cache for 30 seconds
        cache.set(cache_key, stock_data, 30)
        return stock_data

    @database_sync_to_async
    def get_product_stock_levels(self, product_id: str) -> List[Dict[str, Any]]:
        """Get stock levels for a specific product across all stores"""
        from .models import Stock

        try:
            product_id_int = int(product_id)
        except ValueError:
            return []

        stocks = Stock.objects.select_related('store').filter(
            product_id=product_id_int
        ).order_by('store__name')

        stock_data = []
        for stock in stocks:
            stock_data.append({
                'id': stock.id,
                'store_id': stock.store.id,
                'store_name': stock.store.name,
                'quantity': float(stock.quantity),
                'low_stock_threshold': float(stock.low_stock_threshold),
                'reorder_quantity': float(stock.reorder_quantity),
                'status': stock.status,
                'stock_percentage': stock.stock_percentage,
                'last_updated': stock.last_updated.isoformat() if stock.last_updated else None
            })

        return stock_data

    @database_sync_to_async
    def check_permissions(self) -> bool:
        """Check if user has required permissions for stock viewing"""
        return (
                self.user.has_perm('inventory.view_stock') and
                self.user.has_perm('inventory.view_product')
        )