from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/cart/(?P<cart_id>[^/]+)/$', consumers.CartConsumer.as_asgi()),
    re_path(r'ws/sales/(?P<company_id>[^/]+)/$', consumers.SalesConsumer.as_asgi()),
    re_path(r'ws/sales/task-progress/(?P<task_id>[^/]+)/$', consumers.SaleProgressConsumer.as_asgi()),
]