"""
routing.py — WebSocket URL patterns for the expenses app.

No functional changes needed; routes already match the updated consumers.
"""

from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # General expense updates for the authenticated user
    re_path(r'^ws/expenses/$', consumers.ExpenseConsumer.as_asgi()),
    # Expense-specific room (owner + approvers watching that expense)
    re_path(r'^ws/expenses/(?P<expense_id>\d+)/$', consumers.ExpenseConsumer.as_asgi()),
    # Approver dashboard (restricted to users with approve_expense permission)
    re_path(r'^ws/expenses/approvals/$', consumers.ExpenseApprovalConsumer.as_asgi()),
]