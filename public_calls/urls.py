"""
public_support/urls.py

Add to tenancy/public_urls.py:
    path('saas-support/', include('public_support.urls')),
"""
from django.urls import path
from . import views

urlpatterns = [
    path('',                                                       views.saas_support_dashboard, name='saas_support_home'),
    path('api/sessions/',                                          views.all_sessions,           name='saas_support_sessions'),
    path('api/tenants/',                                           views.tenant_list,             name='saas_support_tenants'),
    path('api/session/<str:schema>/<str:session_token>/messages/', views.session_messages,        name='saas_support_messages'),
    path('api/session/<str:schema>/<str:session_token>/message/',  views.send_message,           name='saas_support_send'),
    path('api/session/<str:schema>/<str:session_token>/resolve/',  views.resolve_session,        name='saas_support_resolve'),
    path('api/session/<str:schema>/<str:session_token>/call/',     views.initiate_call,          name='saas_support_call'),
    path('api/queue-config/',                                          views.saas_agent_queue_config, name='saas_queue_config'),
    path('call/<str:call_room_id>/',                                   views.saas_call_room,           name='saas_call_room'),
]