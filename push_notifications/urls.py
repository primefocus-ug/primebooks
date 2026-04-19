from django.urls import path
from . import views

app_name = 'push_notifications'

urlpatterns = [
    path('subscribe/', views.save_subscription, name='subscribe'),
    path('vapid-key/', views.get_vapid_public_key, name='vapid_key'),
    path('my-preferences/', views.my_push_preferences, name='my_preferences'),
    path('manage/<int:user_id>/', views.manage_user_push_preferences, name='manage_user'),
]