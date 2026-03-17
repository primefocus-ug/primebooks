"""
support_widget/urls.py

Include in your tenant urls.py:
    path('support/', include('support_widget.urls')),
"""

from django.urls import path
from . import views

urlpatterns = [
    # ── Widget config (public) ─────────────────────────────────────────
    path('config/',                   views.widget_config,     name='sw_config'),

    # ── Visitor session (public) ───────────────────────────────────────
    path('session/',                  views.create_session,    name='sw_create_session'),
    path('session/<str:session_token>/', views.update_session, name='sw_update_session'),

    # ── FAQ (public) ───────────────────────────────────────────────────
    path('faq/',                      views.search_faq,        name='sw_faq'),

    # ── Calls (public — visitor has no login) ─────────────────────────
    path('call/create/',              views.create_call,       name='sw_create_call'),
    path('call/<str:call_room_id>/recording/', views.upload_recording, name='sw_upload_recording'),
    path('call/<str:call_room_id>/',  views.CallRoomView.as_view(),    name='sw_call_room'),

    # ── Agent — session management ─────────────────────────────────────
    path('agent/sessions/',           views.agent_sessions,    name='sw_agent_sessions'),
    path('agent/status/',             views.agent_set_status,  name='sw_agent_status'),
    path('agent/calls/',              views.agent_calls,       name='sw_agent_calls'),
    path('agent/unread/',             views.agent_unread_count, name='sw_agent_unread'),
    path('agent/session/<str:session_token>/messages/', views.session_messages, name='sw_session_messages'),
    path('agent/session/<str:session_token>/resolve/',  views.resolve_session,  name='sw_resolve_session'),
    path('agent/dashboard/',          views.AgentDashboardView.as_view(), name='sw_agent_dashboard'),
]