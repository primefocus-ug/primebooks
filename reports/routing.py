from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/reports/dashboard/$', consumers.ReportDashboardConsumer.as_asgi()),
    re_path(r'ws/reports/generation/(?P<report_id>\d+)/$', consumers.ReportGenerationConsumer.as_asgi()),
]