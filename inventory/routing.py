from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/inventory/import/(?P<session_id>\d+)/$', consumers.ImportProgressConsumer.as_asgi()),
    re_path(r'ws/inventory/dashboard/$', consumers.InventoryDashboardConsumer.as_asgi()),
    re_path(r'ws/inventory/stock-levels/$', consumers.StockLevelsConsumer.as_asgi()),
]