from django.urls import path
from .views import (
    AnalyticsDashboardView,
    RealtimeAnalyticsView,
    ConversionsView,
    EventsView,
    SourcesView,
    PagesView,
    TrackEventView,
    AnalyticsAPIView
)

app_name = 'public_analytics'

urlpatterns = [
    # Dashboard
    path('', AnalyticsDashboardView.as_view(), name='dashboard'),

    # Views
    path('realtime/', RealtimeAnalyticsView.as_view(), name='realtime'),
    path('conversions/', ConversionsView.as_view(), name='conversions'),
    path('events/', EventsView.as_view(), name='events'),
    path('sources/', SourcesView.as_view(), name='sources'),
    path('pages/', PagesView.as_view(), name='pages'),

    # API
    path('api/data/', AnalyticsAPIView.as_view(), name='api_data'),
    path('api/track/', TrackEventView.as_view(), name='track_event'),
]