from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/branch/(?P<branch_id>\d+)/analytics/$', consumers.BranchAnalyticsConsumer.as_asgi()),
    re_path(r'ws/store/(?P<store_id>\d+)/analytics/$', consumers.StoreAnalyticsConsumer.as_asgi()),
]