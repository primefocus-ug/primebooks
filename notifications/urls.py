from django.urls import path
from .views import notifications_api

app_name='notifications'

urlpatterns = [
    path('api/notifications/', notifications_api, name='notifications_api'),
]
