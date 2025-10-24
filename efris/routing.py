from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/efris/company/(?P<company_id>\d+)/$', consumers.EFRISConsumer.as_asgi()),
]