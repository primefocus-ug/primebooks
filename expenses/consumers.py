"""
consumers.py — Django Channels WebSocket consumers for the expenses app

Improvements over original:
  1. ExpenseConsumer.get_expense_status now verifies the requesting user owns
     (or can approve) the expense before returning data.
  2. "Reviewing" presence states — approvers can broadcast that they are
     actively reviewing a specific expense.
  3. Heartbeat / reconnection support — clients can send a ping every N seconds
     to keep the connection alive; the server echoes pong with a server timestamp.
  4. ExpenseApprovalConsumer gains a `reviewing_expense` handler so the dashboard
     can show which expenses are currently being reviewed.
"""

import json
import logging
from datetime import datetime

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.utils import timezone

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# ExpenseConsumer
# ---------------------------------------------------------------------------

class ExpenseConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for real-time expense updates."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        self.user = self.scope["user"]
        self.expense_id = self.scope["url_route"]["kwargs"].get("expense_id")

        if not self.user.is_authenticated:
            await self.close()
            return

        # Personal group — always joined
        self.user_group_name = f"expense_user_{self.user.id}"
        await self.channel_layer.group_add(self.user_group_name, self.channel_name)

        # Expense-specific group
        if self.expense_id:
            self.expense_group_name = f"expense_{self.expense_id}"
            await self.channel_layer.group_add(self.expense_group_name, self.channel_name)

        # Approver-wide group
        if await self.can_approve_expenses():
            self.company_group_name = "expense_approvers"
            await self.channel_layer.group_add(self.company_group_name, self.channel_name)

        await self.accept()

        await self.send(text_data=json.dumps({
            "type": "connection_established",
            "message": "Connected to expense updates",
            "expense_id": self.expense_id,
            "server_time": timezone.now().isoformat(),
        }))

    async def disconnect(self, close_code):
        # Leave personal group
        if hasattr(self, "user_group_name"):
            await self.channel_layer.group_discard(self.user_group_name, self.channel_name)

        # Leave expense group
        if hasattr(self, "expense_group_name"):
            await self.channel_layer.group_discard(self.expense_group_name, self.channel_name)

        # Leave approvers group
        if hasattr(self, "company_group_name"):
            await self.channel_layer.group_discard(self.company_group_name, self.channel_name)

        # Clear any "reviewing" presence flag this user set
        if self.expense_id:
            await self._broadcast_stop_reviewing(self.expense_id)

    # ------------------------------------------------------------------
    # Incoming messages
    # ------------------------------------------------------------------

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self._send_error("Invalid JSON")
            return

        message_type = data.get("type")

        # ---- ping / heartbeat ----
        if message_type == "ping":
            await self.send(text_data=json.dumps({
                "type": "pong",
                "server_time": timezone.now().isoformat(),
            }))

        # ---- status check ----
        elif message_type == "expense_status_check":
            expense_id = data.get("expense_id")
            if not expense_id:
                await self._send_error("expense_id required")
                return

            # Security: verify the requester may see this expense
            allowed, status = await self.get_expense_status_secure(expense_id)
            if not allowed:
                await self._send_error("Permission denied or expense not found", code=403)
                return

            await self.send(text_data=json.dumps({
                "type": "expense_status",
                "expense_id": expense_id,
                "status": status,
            }))

        # ---- approver: mark expense as being reviewed ----
        elif message_type == "start_reviewing":
            expense_id = data.get("expense_id")
            if expense_id and await self.can_approve_expenses():
                await self._broadcast_start_reviewing(expense_id)

        # ---- approver: stop reviewing ----
        elif message_type == "stop_reviewing":
            expense_id = data.get("expense_id")
            if expense_id and await self.can_approve_expenses():
                await self._broadcast_stop_reviewing(expense_id)

        else:
            await self._send_error(f"Unknown message type: {message_type}")

    # ------------------------------------------------------------------
    # Group event handlers (called by channel layer)
    # ------------------------------------------------------------------

    async def expense_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "expense_update",
            "expense_id": event["expense_id"],
            "expense_number": event["expense_number"],
            "status": event["status"],
            "message": event["message"],
            "timestamp": event["timestamp"],
        }))

    async def expense_comment(self, event):
        await self.send(text_data=json.dumps({
            "type": "expense_comment",
            "expense_id": event["expense_id"],
            "comment": event["comment"],
            "user": event["user"],
            "timestamp": event["timestamp"],
        }))

    async def expense_notification(self, event):
        await self.send(text_data=json.dumps({
            "type": "notification",
            "notification_type": event["notification_type"],
            "title": event["title"],
            "message": event["message"],
            "expense_id": event.get("expense_id"),
            "url": event.get("url"),
            "timestamp": event["timestamp"],
        }))

    async def expense_reviewing(self, event):
        """
        Sent to the expense-specific group so the owner (or other approvers)
        can see that someone is actively reviewing this expense.
        """
        await self.send(text_data=json.dumps({
            "type": "expense_reviewing",
            "expense_id": event["expense_id"],
            "reviewer": event["reviewer"],
            "is_reviewing": event["is_reviewing"],
            "timestamp": event["timestamp"],
        }))

    # ------------------------------------------------------------------
    # Presence helpers
    # ------------------------------------------------------------------

    async def _broadcast_start_reviewing(self, expense_id):
        group = f"expense_{expense_id}"
        await self.channel_layer.group_send(group, {
            "type": "expense_reviewing",
            "expense_id": expense_id,
            "reviewer": str(self.user),
            "is_reviewing": True,
            "timestamp": timezone.now().isoformat(),
        })

    async def _broadcast_stop_reviewing(self, expense_id):
        group = f"expense_{expense_id}"
        await self.channel_layer.group_send(group, {
            "type": "expense_reviewing",
            "expense_id": expense_id,
            "reviewer": str(self.user),
            "is_reviewing": False,
            "timestamp": timezone.now().isoformat(),
        })

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    async def _send_error(self, message: str, code: int = 400):
        await self.send(text_data=json.dumps({
            "type": "error",
            "code": code,
            "message": message,
        }))

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    @database_sync_to_async
    def can_approve_expenses(self) -> bool:
        return self.user.has_perm("expenses.approve_expense")

    @database_sync_to_async
    def get_expense_status_secure(self, expense_id) -> tuple[bool, str | None]:
        """
        Returns (allowed, status).

        The request is allowed if the user owns the expense OR has the
        approve_expense permission.  Returns (False, None) when the expense
        does not exist or the user has no access.
        """
        from .models import Expense

        try:
            expense = Expense.objects.get(pk=expense_id)
        except Expense.DoesNotExist:
            return False, None

        is_owner = expense.user_id == self.user.pk
        is_approver = self.user.has_perm("expenses.approve_expense")

        if is_owner or is_approver:
            return True, expense.status

        return False, None


# ---------------------------------------------------------------------------
# ExpenseApprovalConsumer
# ---------------------------------------------------------------------------

class ExpenseApprovalConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for the approver dashboard.

    Extra features vs. original:
      • Shows which expenses are currently being reviewed (presence state).
      • Broadcasts reviewer activity to all connected approvers.
    """

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self):
        self.user = self.scope["user"]

        if isinstance(self.user, AnonymousUser) or not await self.user_can_approve():
            await self.close()
            return

        self.approval_room = "expense_approval_dashboard"
        await self.channel_layer.group_add(self.approval_room, self.channel_name)
        await self.accept()

        # Send initial pending count on connect
        pending = await self.get_pending_count()
        await self.send(text_data=json.dumps({
            "type": "connection_established",
            "pending_count": pending,
            "server_time": timezone.now().isoformat(),
        }))

    async def disconnect(self, close_code):
        if hasattr(self, "approval_room"):
            await self.channel_layer.group_discard(self.approval_room, self.channel_name)

    # ------------------------------------------------------------------
    # Incoming messages
    # ------------------------------------------------------------------

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            return

        message_type = data.get("type")

        if message_type == "ping":
            await self.send(text_data=json.dumps({
                "type": "pong",
                "server_time": timezone.now().isoformat(),
            }))

        elif message_type == "start_reviewing":
            expense_id = data.get("expense_id")
            if expense_id:
                # Notify the expense owner's group
                await self.channel_layer.group_send(
                    f"expense_{expense_id}",
                    {
                        "type": "expense_reviewing",
                        "expense_id": expense_id,
                        "reviewer": str(self.user),
                        "is_reviewing": True,
                        "timestamp": timezone.now().isoformat(),
                    },
                )
                # Also broadcast to all approvers so the dashboard reflects presence
                await self.channel_layer.group_send(
                    self.approval_room,
                    {
                        "type": "reviewer_presence",
                        "expense_id": expense_id,
                        "reviewer": str(self.user),
                        "is_reviewing": True,
                        "timestamp": timezone.now().isoformat(),
                    },
                )

        elif message_type == "stop_reviewing":
            expense_id = data.get("expense_id")
            if expense_id:
                await self.channel_layer.group_send(
                    f"expense_{expense_id}",
                    {
                        "type": "expense_reviewing",
                        "expense_id": expense_id,
                        "reviewer": str(self.user),
                        "is_reviewing": False,
                        "timestamp": timezone.now().isoformat(),
                    },
                )
                await self.channel_layer.group_send(
                    self.approval_room,
                    {
                        "type": "reviewer_presence",
                        "expense_id": expense_id,
                        "reviewer": str(self.user),
                        "is_reviewing": False,
                        "timestamp": timezone.now().isoformat(),
                    },
                )

    # ------------------------------------------------------------------
    # Group event handlers
    # ------------------------------------------------------------------

    async def approval_update(self, event):
        await self.send(text_data=json.dumps({
            "type": "approval_update",
            "pending_count": event["pending_count"],
            "recent_activity": event.get("recent_activity", []),
            "timestamp": event["timestamp"],
        }))

    async def reviewer_presence(self, event):
        """Broadcast to all approvers which expense is being reviewed."""
        await self.send(text_data=json.dumps({
            "type": "reviewer_presence",
            "expense_id": event["expense_id"],
            "reviewer": event["reviewer"],
            "is_reviewing": event["is_reviewing"],
            "timestamp": event["timestamp"],
        }))

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    @database_sync_to_async
    def user_can_approve(self) -> bool:
        return self.user.has_perm("expenses.approve_expense")

    @database_sync_to_async
    def get_pending_count(self) -> int:
        from .models import Expense
        return Expense.objects.filter(status__in=("submitted", "under_review")).count()