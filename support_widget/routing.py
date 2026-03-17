from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # Visitor widget + agent dashboard chat
    re_path(
        r'ws/support/(?P<session_token>[0-9a-f-]+)/$',
        consumers.SupportChatConsumer.as_asgi(),
    ),
    # WebRTC signaling — visitor & agent exchange SDP/ICE
    re_path(
        r'ws/support/call/(?P<call_room_id>[0-9a-f-]+)/$',
        consumers.SignalingConsumer.as_asgi(),
    ),
    # Agent notification queue — new sessions, incoming calls
    re_path(
        r'ws/support/agent/(?P<user_id>\d+)/$',
        consumers.AgentQueueConsumer.as_asgi(),
    ),
]