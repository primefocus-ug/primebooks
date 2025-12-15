import json
import asyncio
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ObjectDoesNotExist
from stores.models import Store
from sales.models import Sale
from django_tenants.utils import schema_context



class StoreAnalyticsConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for store analytics real-time updates.
    Renamed from BranchAnalyticsConsumer to reflect Store model.
    """

    async def connect(self):
        # Get store ID from URL route (can still use 'branch_id' in URL for compatibility)
        self.store_id = self.scope['url_route']['kwargs'].get('store_id') or \
                        self.scope['url_route']['kwargs'].get('branch_id')
        self.store_group_name = f'store_analytics_{self.store_id}'

        # Check authentication and permissions
        user = self.scope["user"]
        if isinstance(user, AnonymousUser):
            await self.close(code=4001)
            return

        # Check if user has permission to view store
        has_permission = await self.check_store_permission(user, self.store_id)
        if not has_permission:
            await self.close(code=4003)
            return

        # Join store group
        await self.channel_layer.group_add(
            self.store_group_name,
            self.channel_name
        )

        await self.accept()

        # Send initial data
        await self.send_initial_data()

    async def disconnect(self, close_code):
        # Leave store group
        await self.channel_layer.group_discard(
            self.store_group_name,
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
            elif message_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def send_initial_data(self):
        """Send initial store analytics data."""
        try:
            analytics_data = await self.get_store_analytics()
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
            analytics_data = await self.get_store_analytics()
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

    async def sale_update(self, event):
        """Handle sale update notifications."""
        await self.send(text_data=json.dumps({
            'type': 'sale_update',
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

    async def inventory_update(self, event):
        """Handle inventory updates."""
        await self.send(text_data=json.dumps({
            'type': 'inventory_update',
            'data': event['data'],
            'timestamp': event.get('timestamp', asyncio.get_event_loop().time())
        }))

    @database_sync_to_async
    def check_store_permission(self, user, store_id):
        """Check if user has permission to view this store."""
        from company.models import Company

        try:
            schema_name = getattr(user.company, "schema_name", "public")
            with schema_context(schema_name):
                store = Store.objects.select_related('company').get(id=store_id)
                # Check if user belongs to the same company or is admin
                return (
                        user.company == store.company
                        or user.is_superuser
                        or user.has_perm('stores.view_store')
                        or user in store.staff.all()
                )
        except Store.DoesNotExist:
            return False

    @database_sync_to_async
    def get_store_analytics(self):
        """Get current store analytics data."""
        from django.utils import timezone
        from django.db.models import Sum, Count, Avg
        from datetime import timedelta
        from company.models import Company

        try:
            schema_name = getattr(self.scope["user"].company, "schema_name", "public")
            with schema_context(schema_name):
                store = Store.objects.select_related('company').get(id=self.store_id)

                thirty_days_ago = timezone.now().date() - timedelta(days=30)
                today = timezone.now().date()

                # Get 30-day metrics
                metrics_30d = Sale.objects.filter(
                    store=store,
                    created_at__date__gte=thirty_days_ago,
                    is_voided=False,
                    status__in=['COMPLETED', 'PAID']
                ).aggregate(
                    total_revenue=Sum('total_amount'),
                    total_sales=Count('id'),
                    avg_sale=Avg('total_amount')
                )

                # Get today's metrics
                today_metrics = Sale.objects.filter(
                    store=store,
                    created_at__date=today,
                    is_voided=False,
                    status__in=['COMPLETED', 'PAID']
                ).aggregate(
                    revenue=Sum('total_amount'),
                    count=Count('id')
                )

                return {
                    'store_id': self.store_id,
                    'store_name': store.name,
                    'store_code': store.code,
                    'is_main_store': store.is_main_branch,
                    'metrics_30d': {
                        'total_revenue': float(metrics_30d['total_revenue'] or 0),
                        'total_sales': metrics_30d['total_sales'] or 0,
                        'avg_sale': float(metrics_30d['avg_sale'] or 0),
                    },
                    'today': {
                        'revenue': float(today_metrics['revenue'] or 0),
                        'sales': today_metrics['count'] or 0
                    },
                    'status': {
                        'is_active': store.is_active,
                        'efris_enabled': store.efris_enabled,
                        'can_fiscalize': store.can_fiscalize,
                    },
                    'last_updated': timezone.now().isoformat()
                }

        except Exception as e:
            return {'error': str(e)}


class CompanyStoresConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for company-wide store analytics.
    Monitors all stores belonging to a company.
    """

    async def connect(self):
        self.company_id = self.scope['url_route']['kwargs']['company_id']
        self.company_group_name = f'company_stores_{self.company_id}'

        # Check authentication and permissions
        user = self.scope["user"]
        if isinstance(user, AnonymousUser):
            await self.close(code=4001)
            return

        has_permission = await self.check_company_permission(user, self.company_id)
        if not has_permission:
            await self.close(code=4003)
            return

        await self.channel_layer.group_add(
            self.company_group_name,
            self.channel_name
        )

        await self.accept()
        await self.send_initial_company_data()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.company_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            text_data_json = json.loads(text_data)
            message_type = text_data_json.get('type')

            if message_type == 'request_update':
                await self.send_company_update()
            elif message_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON format'
            }))

    async def send_initial_company_data(self):
        """Send initial company-wide data."""
        try:
            company_data = await self.get_company_analytics()
            await self.send(text_data=json.dumps({
                'type': 'initial_data',
                'data': company_data
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Failed to load company data: {str(e)}'
            }))

    async def send_company_update(self):
        """Send updated company data."""
        try:
            company_data = await self.get_company_analytics()
            await self.send(text_data=json.dumps({
                'type': 'company_update',
                'data': company_data,
                'timestamp': asyncio.get_event_loop().time()
            }))
        except Exception as e:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f'Failed to update company data: {str(e)}'
            }))

    # Group message handlers
    async def store_update(self, event):
        """Handle store updates."""
        await self.send(text_data=json.dumps({
            'type': 'store_update',
            'data': event['data']
        }))

    async def company_alert(self, event):
        """Handle company-wide alerts."""
        await self.send(text_data=json.dumps({
            'type': 'company_alert',
            'data': event['data'],
            'severity': event.get('severity', 'info')
        }))

    @database_sync_to_async
    def check_company_permission(self, user, company_id):
        """Check if user has permission to view this company."""
        from company.models import Company

        try:
            schema_name = getattr(user.company, "schema_name", "public")
            with schema_context(schema_name):
                company = Company.objects.get(company_id=company_id)
                return (
                        user.company == company
                        or user.is_superuser
                        or user.has_perm('company.view_company')
                )
        except Company.DoesNotExist:
            return False

    @database_sync_to_async
    def get_company_analytics(self):
        """Get company-wide analytics data."""
        from django.utils import timezone
        from django.db.models import Sum, Count, Avg
        from datetime import timedelta
        from company.models import Company

        try:
            schema_name = getattr(self.scope["user"].company, "schema_name", "public")
            with schema_context(schema_name):
                company = Company.objects.get(id=self.company_id)
                stores = Store.objects.filter(company=company, is_active=True)

                thirty_days_ago = timezone.now().date() - timedelta(days=30)

                # Get company-wide metrics
                store_ids = stores.values_list('id', flat=True)
                metrics = Sale.objects.filter(
                    store_id__in=store_ids,
                    created_at__date__gte=thirty_days_ago,
                    is_voided=False,
                    status__in=['COMPLETED', 'PAID']
                ).aggregate(
                    total_revenue=Sum('total_amount'),
                    total_sales=Count('id'),
                    avg_sale=Avg('total_amount')
                )

                # Get per-store performance
                store_performance = []
                for store in stores:
                    store_metrics = Sale.objects.filter(
                        store=store,
                        created_at__date__gte=thirty_days_ago,
                        is_voided=False,
                        status__in=['COMPLETED', 'PAID']
                    ).aggregate(
                        revenue=Sum('total_amount'),
                        sales=Count('id')
                    )

                    store_performance.append({
                        'id': store.id,
                        'name': store.name,
                        'code': store.code,
                        'is_main_store': store.is_main_branch,
                        'revenue': float(store_metrics['revenue'] or 0),
                        'sales': store_metrics['sales'] or 0,
                        'is_active': store.is_active,
                        'efris_enabled': store.efris_enabled
                    })

                return {
                    'company_id': self.company_id,
                    'company_name': company.name,
                    'metrics': {
                        'total_revenue': float(metrics['total_revenue'] or 0),
                        'total_sales': metrics['total_sales'] or 0,
                        'avg_sale': float(metrics['avg_sale'] or 0),
                        'active_stores': stores.count()
                    },
                    'stores': store_performance,
                    'last_updated': timezone.now().isoformat()
                }

        except Exception as e:
            return {'error': str(e)}


# Backward compatibility alias
BranchAnalyticsConsumer = StoreAnalyticsConsumer

