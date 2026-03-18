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
    # Agent notification queue — new sessions, incoming calls (tenant dashboard)
    re_path(
        r'ws/support/agent/(?P<user_id>\d+)/$',
        consumers.AgentQueueConsumer.as_asgi(),
    ),
    # SaaS admin queue — subscribes to a specific tenant schema's queue
    # Used by the SaaS support dashboard at localhost:8000/saas-support/
    re_path(
        r'ws/support/saas-agent/(?P<schema_name>[\w-]+)/(?P<user_id>\d+)/$',
        consumers.SaaSAgentQueueConsumer.as_asgi(),
    ),
]