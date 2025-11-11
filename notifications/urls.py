from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    # Main views
    path('', views.notification_list, name='notification_list'),
    path('preferences/', views.notification_preferences, name='preferences'),
    path('announcements/', views.active_announcements, name='announcements'),

    # Actions
    path('<int:pk>/read/', views.mark_as_read, name='mark_as_read'),
    path('<int:pk>/unread/', views.mark_as_unread, name='mark_as_unread'),
    path('<int:pk>/delete/', views.delete_notification, name='delete'),
    path('mark-all-read/', views.mark_all_as_read, name='mark_all_as_read'),
    path('delete-all-read/', views.delete_all_read, name='delete_all_read'),
    path('announcement/<int:pk>/dismiss/', views.dismiss_announcement, name='dismiss_announcement'),

    # API endpoints
    path('api/', views.notifications_api, name='notifications_apii'),
    path('api/count/', views.notifications_count, name='notifications_count'),
    path('api/notifications/', views.notiifications_api, name='notifications_api'),
]