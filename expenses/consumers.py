import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone


class ExpenseConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time expense updates"""

    async def connect(self):
        """Handle WebSocket connection"""
        self.user = self.scope['user']

        # Check if user is authenticated
        if not self.user.is_authenticated:
            await self.close()
            return

        # Get store_id from URL route
        self.store_id = self.scope['url_route']['kwargs'].get('store_id')

        # Verify user has access to this store
        has_access = await self.check_store_access(self.user, self.store_id)
        if not has_access:
            await self.close()
            return

        # Join store-specific expense group
        self.room_group_name = f'expenses_{self.store_id}'

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': 'Connected to expense updates',
            'store_id': self.store_id,
            'timestamp': timezone.now().isoformat()
        }))

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        """Handle messages from WebSocket"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'ping':
                # Respond to ping with pong
                await self.send(text_data=json.dumps({
                    'type': 'pong',
                    'timestamp': timezone.now().isoformat()
                }))

            elif message_type == 'subscribe_expense':
                # Subscribe to specific expense updates
                expense_id = data.get('expense_id')
                if expense_id:
                    expense_group = f'expense_{expense_id}'
                    await self.channel_layer.group_add(
                        expense_group,
                        self.channel_name
                    )
                    await self.send(text_data=json.dumps({
                        'type': 'subscribed',
                        'expense_id': expense_id,
                        'timestamp': timezone.now().isoformat()
                    }))

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON'
            }))

    async def expense_update(self, event):
        """Handle expense update events"""
        message = event['message']

        # Send message to WebSocket
        await self.send(text_data=json.dumps({
            'type': 'expense_update',
            'data': message
        }))

    async def expense_created(self, event):
        """Handle new expense creation"""
        await self.send(text_data=json.dumps({
            'type': 'expense_created',
            'data': event['message']
        }))

    async def expense_approved(self, event):
        """Handle expense approval"""
        await self.send(text_data=json.dumps({
            'type': 'expense_approved',
            'data': event['message']
        }))

    async def expense_rejected(self, event):
        """Handle expense rejection"""
        await self.send(text_data=json.dumps({
            'type': 'expense_rejected',
            'data': event['message']
        }))

    async def expense_paid(self, event):
        """Handle expense payment"""
        await self.send(text_data=json.dumps({
            'type': 'expense_paid',
            'data': event['message']
        }))

    async def budget_alert(self, event):
        """Handle budget alerts"""
        await self.send(text_data=json.dumps({
            'type': 'budget_alert',
            'data': event['message']
        }))

    @database_sync_to_async
    def check_store_access(self, user, store_id):
        """Check if user has access to store"""
        if not store_id:
            return False

        # Super admins and SaaS admins have access to all stores
        if user.is_superuser or user.is_saas_admin:
            return True

        # Check if user is assigned to this store
        if hasattr(user, 'stores'):
            return user.stores.filter(id=store_id).exists()

        return False


class BudgetConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for budget updates and alerts"""

    async def connect(self):
        """Handle WebSocket connection"""
        self.user = self.scope['user']

        if not self.user.is_authenticated:
            await self.close()
            return

        self.store_id = self.scope['url_route']['kwargs'].get('store_id')

        # Join budget updates group
        self.room_group_name = f'budgets_{self.store_id}'

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

        # Send current budget status
        await self.send_budget_summary()

    async def disconnect(self, close_code):
        """Handle disconnection"""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        """Handle incoming messages"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'get_budget_status':
                await self.send_budget_summary()

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON'
            }))

    async def send_budget_summary(self):
        """Send current budget summary"""
        budget_data = await self.get_budget_summary(self.store_id)

        await self.send(text_data=json.dumps({
            'type': 'budget_summary',
            'data': budget_data
        }))

    async def budget_warning(self, event):
        """Handle budget warning alerts"""
        await self.send(text_data=json.dumps({
            'type': 'budget_warning',
            'data': event['message']
        }))

    async def budget_critical(self, event):
        """Handle budget critical alerts"""
        await self.send(text_data=json.dumps({
            'type': 'budget_critical',
            'data': event['message']
        }))

    async def budget_exceeded(self, event):
        """Handle budget exceeded alerts"""
        await self.send(text_data=json.dumps({
            'type': 'budget_exceeded',
            'data': event['message']
        }))

    @database_sync_to_async
    def get_budget_summary(self, store_id):
        """Get budget summary for store"""
        from .models import Budget
        from django.db.models import Q
        from django.utils import timezone

        today = timezone.now().date()

        budgets = Budget.objects.filter(
            start_date__lte=today,
            end_date__gte=today,
            is_active=True
        )

        if store_id:
            budgets = budgets.filter(Q(store_id=store_id) | Q(store__isnull=True))

        summary = []
        for budget in budgets:
            summary.append({
                'id': budget.id,
                'name': budget.name,
                'category': budget.category.name,
                'allocated': str(budget.allocated_amount),
                'spent': str(budget.spent_amount),
                'remaining': str(budget.remaining_amount),
                'utilization': str(budget.utilization_percentage),
                'status': budget.status
            })

        return summary


class PettyCashConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for petty cash updates"""

    async def connect(self):
        """Handle connection"""
        self.user = self.scope['user']

        if not self.user.is_authenticated:
            await self.close()
            return

        self.store_id = self.scope['url_route']['kwargs'].get('store_id')

        # Join petty cash group
        self.room_group_name = f'petty_cash_{self.store_id}'

        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )

        await self.accept()

    async def disconnect(self, close_code):
        """Handle disconnection"""
        if hasattr(self, 'room_group_name'):
            await self.channel_layer.group_discard(
                self.room_group_name,
                self.channel_name
            )

    async def petty_cash_transaction(self, event):
        """Handle petty cash transaction updates"""
        await self.send(text_data=json.dumps({
            'type': 'petty_cash_transaction',
            'data': event['message']
        }))

    async def petty_cash_low(self, event):
        """Handle low petty cash alerts"""
        await self.send(text_data=json.dumps({
            'type': 'petty_cash_low',
            'data': event['message']
        }))