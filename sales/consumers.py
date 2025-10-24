import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async



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