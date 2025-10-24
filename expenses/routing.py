from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/expenses/(?P<store_id>\w+)/$', consumers.ExpenseConsumer.as_asgi()),
    re_path(r'ws/budgets/(?P<store_id>\w+)/$', consumers.BudgetConsumer.as_asgi()),
    re_path(r'ws/petty-cash/(?P<store_id>\w+)/$', consumers.PettyCashConsumer.as_asgi()),
]