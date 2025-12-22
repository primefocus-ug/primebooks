import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth import get_user_model

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

User = get_user_model()


class ExpenseConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time expense updates"""

    async def connect(self):
        """Handle WebSocket connection"""
        self.user = self.scope['user']
        self.expense_id = self.scope['url_route']['kwargs'].get('expense_id')

        if not self.user.is_authenticated:
            await self.close()
            return

        # Join user-specific group
        self.user_group_name = f'expense_user_{self.user.id}'
        await self.channel_layer.group_add(
            self.user_group_name,
            self.channel_name
        )

        # Join expense-specific room if expense_id is provided
        if self.expense_id:
            self.expense_group_name = f'expense_{self.expense_id}'
            await self.channel_layer.group_add(
                self.expense_group_name,
                self.channel_name
            )

        # Join company-wide expense group if user can approve
        if await self.can_approve_expenses():
            self.company_group_name = 'expense_approvers'
            await self.channel_layer.group_add(
                self.company_group_name,
                self.channel_name
            )

        await self.accept()

        # Send connection confirmation
        await self.send(text_data=json.dumps({
            'type': 'connection_established',
            'message': 'Connected to expense updates',
            'expense_id': self.expense_id
        }))

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection"""
        # Leave user group
        await self.channel_layer.group_discard(
            self.user_group_name,
            self.channel_name
        )

        # Leave expense group if applicable
        if hasattr(self, 'expense_group_name'):
            await self.channel_layer.group_discard(
                self.expense_group_name,
                self.channel_name
            )

        # Leave approvers group if applicable
        if hasattr(self, 'company_group_name'):
            await self.channel_layer.group_discard(
                self.company_group_name,
                self.channel_name
            )

    async def receive(self, text_data):
        """Handle incoming WebSocket messages"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')

            if message_type == 'ping':
                await self.send(text_data=json.dumps({
                    'type': 'pong'
                }))

            elif message_type == 'expense_status_check':
                expense_id = data.get('expense_id')
                if expense_id:
                    status = await self.get_expense_status(expense_id)
                    await self.send(text_data=json.dumps({
                        'type': 'expense_status',
                        'expense_id': expense_id,
                        'status': status
                    }))

        except json.JSONDecodeError:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Invalid JSON'
            }))

    # Receive messages from group
    async def expense_update(self, event):
        """Handle expense update events"""
        await self.send(text_data=json.dumps({
            'type': 'expense_update',
            'expense_id': event['expense_id'],
            'expense_number': event['expense_number'],
            'status': event['status'],
            'message': event['message'],
            'timestamp': event['timestamp']
        }))

    async def expense_comment(self, event):
        """Handle new comment events"""
        await self.send(text_data=json.dumps({
            'type': 'expense_comment',
            'expense_id': event['expense_id'],
            'comment': event['comment'],
            'user': event['user'],
            'timestamp': event['timestamp']
        }))

    async def expense_notification(self, event):
        """Handle expense notification events"""
        await self.send(text_data=json.dumps({
            'type': 'notification',
            'notification_type': event['notification_type'],
            'title': event['title'],
            'message': event['message'],
            'expense_id': event.get('expense_id'),
            'url': event.get('url'),
            'timestamp': event['timestamp']
        }))

    @database_sync_to_async
    def can_approve_expenses(self):
        """Check if user has permission to approve expenses"""
        return self.user.has_perm('expenses.approve_expense')

    @database_sync_to_async
    def get_expense_status(self, expense_id):
        """Get current status of an expense"""
        from .models import Expense
        try:
            expense = Expense.objects.get(id=expense_id)
            return expense.status
        except Expense.DoesNotExist:
            return None
        


class ExpenseApprovalConsumer(AsyncWebsocketConsumer):
    """Special consumer for approval dashboard updates"""
    
    async def connect(self):
        self.user = self.scope["user"]
        
        if self.user == AnonymousUser() or not await self.user_can_approve():
            await self.close()
            return
        
        self.approval_room = "expense_approval_dashboard"
        
        await self.channel_layer.group_add(
            self.approval_room,
            self.channel_name
        )
        
        await self.accept()
    
    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.approval_room,
            self.channel_name
        )
    
    async def approval_update(self, event):
        """Send approval dashboard update"""
        await self.send(text_data=json.dumps({
            'type': 'approval_update',
            'pending_count': event['pending_count'],
            'recent_activity': event.get('recent_activity', []),
            'timestamp': event['timestamp']
        }))
    
    @database_sync_to_async
    def user_can_approve(self):
        return self.user.has_perm('expenses.approve_expense')