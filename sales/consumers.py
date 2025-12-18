from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser



class CartConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        from django.contrib.auth.models import AnonymousUser
        self.user = self.scope["user"]
        if self.user == AnonymousUser():
            await self.close()
            return

        self.cart_id = self.scope['url_route']['kwargs']['cart_id']
        self.cart_group_name = f'cart_{self.cart_id}'

        # Verify user has access to this cart
        if not await self.verify_cart_access():
            await self.close()
            return

        await self.channel_layer.group_add(
            self.cart_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.cart_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        data = json.loads(text_data)
        event_type = data.get('type')

        if event_type == 'cart_update':
            await self.channel_layer.group_send(
                self.cart_group_name,
                {
                    'type': 'cart_update',
                    'message': data.get('message')
                }
            )

    async def cart_update(self, event):
        message = event['message']
        await self.send(text_data=json.dumps({
            'type': 'cart_update',
            'message': message
        }))

    @database_sync_to_async
    def verify_cart_access(self):
        from sales.models import Cart
        try:
            cart = Cart.objects.get(id=self.cart_id)
            if self.user.is_superuser:
                return True
            if hasattr(self.user, 'employee_profile'):
                return cart.user == self.user or cart.store in self.user.employee_profile.company.stores.all()
            return cart.user == self.user
        except Cart.DoesNotExist:
            return False


class SalesConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        from django.contrib.auth.models import AnonymousUser
        self.user = self.scope["user"]
        if self.user == AnonymousUser():
            await self.close()
            return

        self.company_id = self.scope['url_route']['kwargs']['company_id']
        self.sales_group_name = f'sales_{self.company_id}'

        # Verify user has access to this company's sales
        if not await self.verify_company_access():
            await self.close()
            return

        await self.channel_layer.group_add(
            self.sales_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.sales_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        data = json.loads(text_data)
        event_type = data.get('type')

        if event_type == 'sale_update':
            await self.channel_layer.group_send(
                self.sales_group_name,
                {
                    'type': 'sale_update',
                    'message': data.get('message')
                }
            )

    async def sale_update(self, event):
        message = event['message']
        await self.send(text_data=json.dumps({
            'type': 'sale_update',
            'message': message
        }))

    @database_sync_to_async
    def verify_company_access(self):
        try:
            if self.user.is_superuser:
                return True
            if hasattr(self.user, 'employee_profile'):
                return str(self.user.employee_profile.company.id) == self.company_id
            return False
        except Exception:
            return False



class SaleProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.task_id = self.scope['url_route']['kwargs']['task_id']
        self.group_name = f'task_progress_{self.task_id}'

        # Check authentication (optional)
        user = self.scope.get('user')
        if isinstance(user, AnonymousUser):
            await self.close()
            return

        # Join task group
        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )

        await self.accept()

        # Send initial state if available
        initial_data = await self.get_initial_task_data()
        if initial_data:
            await self.send(text_data=json.dumps(initial_data))

    @database_sync_to_async
    def get_initial_task_data(self):
        """Get initial task data from cache"""
        from django.core.cache import cache
        return cache.get(f'sale_task_{self.task_id}')

    async def disconnect(self, close_code):
        # Leave task group
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def task_progress(self, event):
        """Receive progress update and forward to WebSocket"""
        await self.send(text_data=json.dumps(event['data']))