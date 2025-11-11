from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/expenses/$', consumers.ExpenseConsumer.as_asgi()),
    re_path(r'ws/expenses/approvals/$', consumers.ExpenseApprovalConsumer.as_asgi()),
]