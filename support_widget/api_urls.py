"""
support_widget/api_urls.py

Include in your tenant urls.py:
    path('api/support/', include('support_widget.api_urls')),

Keep the existing web URLs separate:
    path('support/', include('support_widget.urls')),
"""

from django.urls import path
from . import api_views

urlpatterns = [

    # ── Widget config ──────────────────────────────────────────────────────────
    path('config/',            api_views.APIWidgetConfig.as_view(),    name='api_sw_config'),
    path('ice-config/',        api_views.APIIceConfig.as_view(),       name='api_sw_ice_config'),

    # ── FAQ ────────────────────────────────────────────────────────────────────
    path('faq/',               api_views.APIFAQList.as_view(),         name='api_sw_faq'),

    # ── Visitor session ────────────────────────────────────────────────────────
    path('session/',           api_views.APISessionCreate.as_view(),   name='api_sw_session_create'),
    path('session/<str:session_token>/',
                               api_views.APISessionDetail.as_view(),   name='api_sw_session_detail'),
    path('session/<str:session_token>/messages/',
                               api_views.APISessionMessages.as_view(), name='api_sw_session_messages'),
    path('session/<str:session_token>/message/',
                               api_views.APIVisitorSendMessage.as_view(), name='api_sw_visitor_message'),
    path('session/<str:session_token>/typing/',
                               api_views.APIVisitorTyping.as_view(),   name='api_sw_visitor_typing'),
    path('session/<str:session_token>/request-agent/',
                               api_views.APIRequestAgent.as_view(),    name='api_sw_request_agent'),

    # ── Calls ──────────────────────────────────────────────────────────────────
    path('call/create/',       api_views.APICallCreate.as_view(),      name='api_sw_call_create'),
    path('call/<str:call_room_id>/consent/',
                               api_views.APICallConsent.as_view(),     name='api_sw_call_consent'),
    path('call/<str:call_room_id>/end/',
                               api_views.APICallEnd.as_view(),         name='api_sw_call_end'),
    path('call/<str:call_room_id>/recording/',
                               api_views.APICallRecordingUpload.as_view(), name='api_sw_call_recording'),

    # ── Agent — profile & status ───────────────────────────────────────────────
    path('agent/me/',          api_views.APIAgentMe.as_view(),         name='api_sw_agent_me'),
    path('agent/status/',      api_views.APIAgentSetStatus.as_view(),  name='api_sw_agent_status'),
    path('agent/unread/',      api_views.APIAgentUnread.as_view(),     name='api_sw_agent_unread'),
    path('agent/calls/',       api_views.APIAgentCalls.as_view(),      name='api_sw_agent_calls'),

    # ── Agent — session management ─────────────────────────────────────────────
    path('agent/sessions/',    api_views.APIAgentSessions.as_view(),   name='api_sw_agent_sessions'),
    path('agent/session/<str:session_token>/',
                               api_views.APIAgentSessionDetail.as_view(), name='api_sw_agent_session_detail'),
    path('agent/session/<str:session_token>/message/',
                               api_views.APIAgentSendMessage.as_view(),   name='api_sw_agent_message'),
    path('agent/session/<str:session_token>/typing/',
                               api_views.APIAgentTyping.as_view(),        name='api_sw_agent_typing'),
    path('agent/session/<str:session_token>/resolve/',
                               api_views.APIAgentResolveSession.as_view(), name='api_sw_agent_resolve'),
    path('agent/session/<str:session_token>/assign/',
                               api_views.APIAgentAssignSession.as_view(), name='api_sw_agent_assign'),

    # ── Mobile push tokens ─────────────────────────────────────────────────────
    path('push-token/',        api_views.APIPushToken.as_view(),       name='api_sw_push_token'),
]