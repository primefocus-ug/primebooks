import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ObjectDoesNotExist
from .models import CompanyBranch
from sales.models import Sale
from stores.models import Store


class BranchAnalyticsConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for branch analytics real-time updates."""

    async def connect(self):
        # Get branch ID from URL route
        self.branch_id = self.scope['url_route']['kwargs']['branch_id']
        self.branch_group_name = f'branch_analytics_{self.branch_id}'

        # Check authentication and permissions
        user = self.scope["user"]
        if isinstance(user, AnonymousUser):
            await self.close(code=4001)
            return

        # Check if user has permission to view branch
        has_permission = await self.check_branch_permission(user, self.branch_id)
        if not has_permission:
            await self.close(code=4003)
            return

        # Join branch group
        await self.channel_layer.group_add(
            self.branch_group_name,
            self.channel_name
        )

        await self.accept()

        # Send initial data
        await self.send_initial_data()

    async def disconnect(self, close_code):
        # Leave branch group
        await self.channel_layer.group_discard(
            self.branch_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')

            if message_type == 'request_update':
                await self.send_analytics_update()
            elif message_type == 'subscribe_store':
                store_id = text_data_json.get('store_id')
                await self.subscribe_to_store(store_id)
            elif message_type == 'unsubscribe_store':
                store_id = text_data_json.get('store_id')
                await self.unsubscribe_from_store(store_id)

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def send_initial_data(self):
        """Send initial branch analytics data."""
        try:
            analytics_data = await self.get_branch_analytics()
            await self.send(text_data=json.dumps({
                'type': 'initial_data',
                'data': analytics_data
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Failed to load initial data: {str(e)}'
            }))

    async def send_analytics_update(self):
        """Send updated analytics data."""
        try:
            analytics_data = await self.get_branch_analytics()
            await self.send(text_data=json.dumps({
                'type': 'analytics_update',
                'data': analytics_data,
                'timestamp': asyncio.get_event_loop().time()
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Failed to update analytics: {str(e)}'
            }))

    async def subscribe_to_store(self, store_id):
        """Subscribe to specific store updates."""
        if not store_id:
            return

        store_group_name = f'store_updates_{store_id}'
        await self.channel_layer.group_add(
            store_group_name,
            self.channel_name
        )

        await self.send(text_data=json.dumps({
            'type': 'subscription_confirmed',
            'store_id': store_id
        }))

    async def unsubscribe_from_store(self, store_id):
        """Unsubscribe from specific store updates."""
        if not store_id:
            return

        store_group_name = f'store_updates_{store_id}'
        await self.channel_layer.group_discard(
            store_group_name,
            self.channel_name
        )

    # Group message handlers
    async def branch_update(self, event):
        """Handle branch update messages."""
        await self.send(text_data=json.dumps({
            'type': 'branch_update',
            'data': event['data'],
            'timestamp': event.get('timestamp', asyncio.get_event_loop().time())
        }))

    async def store_update(self, event):
        """Handle store update messages."""
        await self.send(text_data=json.dumps({
            'type': 'store_update',
            'data': event['data'],
            'timestamp': event.get('timestamp', asyncio.get_event_loop().time())
        }))

    async def sale_created(self, event):
        """Handle new sale notifications."""
        await self.send(text_data=json.dumps({
            'type': 'sale_created',
            'data': event['data'],
            'timestamp': event.get('timestamp', asyncio.get_event_loop().time())
        }))

    async def performance_alert(self, event):
        """Handle performance alerts."""
        await self.send(text_data=json.dumps({
            'type': 'performance_alert',
            'data': event['data'],
            'severity': event.get('severity', 'info'),
            'timestamp': event.get('timestamp', asyncio.get_event_loop().time())
        }))

    @database_sync_to_async
    def check_branch_permission(self, user, branch_id):
        """Check if user has permission to view this branch."""
        try:
            branch = CompanyBranch.objects.get(id=branch_id)
            # Check if user belongs to the same company or is admin
            return (user.company == branch.company or
                    user.is_superuser or
                    user.has_perm('branches.view_companybranch'))
        except CompanyBranch.DoesNotExist:
            return False

    @database_sync_to_async
    def get_branch_analytics(self):
        """Get current branch analytics data."""
        from django.utils import timezone
        from django.db.models import Sum, Count, Avg
        from datetime import timedelta

        try:
            branch = CompanyBranch.objects.get(id=self.branch_id)
            stores = branch.stores.all()
            store_ids = stores.values_list('id', flat=True)

            thirty_days_ago = timezone.now().date() - timedelta(days=30)

            # Get metrics
            metrics = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                is_completed=True
            ).aggregate(
                total_revenue=Sum('total_amount'),
                total_sales=Count('id'),
                avg_sale=Avg('total_amount')
            )

            # Get store performance
            store_performance = []
            for store in stores:
                store_metrics = Sale.objects.filter(
                    store=store,
                    created_at__date__gte=thirty_days_ago,
                    is_voided=False,
                    is_completed=True
                ).aggregate(
                    revenue=Sum('total_amount'),
                    sales=Count('id')
                )

                store_performance.append({
                    'id': store.id,
                    'name': store.name,
                    'revenue': float(store_metrics['revenue'] or 0),
                    'sales': store_metrics['sales'] or 0,
                    'is_active': store.is_active
                })

            return {
                'branch_id': self.branch_id,
                'metrics': {
                    'total_revenue': float(metrics['total_revenue'] or 0),
                    'total_sales': metrics['total_sales'] or 0,
                    'avg_sale': float(metrics['avg_sale'] or 0),
                },
                'stores': store_performance,
                'last_updated': timezone.now().isoformat()
            }

        except Exception as e:
            return {'error': str(e)}


class StoreAnalyticsConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for individual store analytics."""

    async def connect(self):
        self.store_id = self.scope['url_route']['kwargs']['store_id']
        self.store_group_name = f'store_analytics_{self.store_id}'

        # Check authentication and permissions
        user = self.scope["user"]
        if isinstance(user, AnonymousUser):
            await self.close(code=4001)
            return

        has_permission = await self.check_store_permission(user, self.store_id)
        if not has_permission:
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(
            self.store_group_name,
            self.channel_name
        )

        await self.accept()
        await self.send_initial_store_data()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.store_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')

            if message_type == 'request_update':
                await self.send_store_update()
            elif message_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def send_initial_store_data(self):
        """Send initial store data."""
        try:
            store_data = await self.get_store_analytics()
            await self.send(text_data=json.dumps({
                'type': 'initial_data',
                'data': store_data
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Failed to load store data: {str(e)}'
            }))

    async def send_store_update(self):
        """Send updated store data."""
        try:
            store_data = await self.get_store_analytics()
            await self.send(text_data=json.dumps({
                'type': 'store_update',
                'data': store_data,
                'timestamp': asyncio.get_event_loop().time()
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Failed to update store data: {str(e)}'
            }))

    # Group message handlers
    async def store_sale_update(self, event):
        """Handle store sale updates."""
        await self.send(text_data=json.dumps({
            'type': 'sale_update',
            'data': event['data']
        }))

    async def inventory_update(self, event):
        """Handle inventory updates."""
        await self.send(text_data=json.dumps({
            'type': 'inventory_update',
            'data': event['data']
        }))

    @database_sync_to_async
    def check_store_permission(self, user, store_id):
        """Check if user has permission to view this store."""
        try:
            store = Store.objects.select_related('branch').get(id=store_id)
            return (user.company == store.branch.company or
                    user.is_superuser or
                    user in store.staff.all())
        except Store.DoesNotExist:
            return False

    @database_sync_to_async
    def get_store_analytics(self):
        """Get current store analytics data."""
        from django.utils import timezone
        from django.db.models import Sum, Count
        from datetime import timedelta

        try:
            store = Store.objects.get(id=self.store_id)
            today = timezone.now().date()

            # Today's sales
            today_sales = Sale.objects.filter(
                store=store,
                created_at__date=today,
                is_voided=False,
                is_completed=True
            ).aggregate(
                revenue=Sum('total_amount'),
                count=Count('id')
            )

            return {
                'store_id': self.store_id,
                'store_name': store.name,
                'today_revenue': float(today_sales['revenue'] or 0),
                'today_sales': today_sales['count'] or 0,
                'is_active': store.is_active,
                'last_updated': timezone.now().isoformat()
            }

        except Exception as e:
            return {'error': str(e)}


