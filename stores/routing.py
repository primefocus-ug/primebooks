from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path("ws/stores-updates/", consumers.CompanyConsumer.as_asgi()),
]