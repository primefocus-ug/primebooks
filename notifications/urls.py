from django.urls import path
from . import views

app_name = 'notifications'

urlpatterns = [
    # Notification List & Detail
    path('', views.notification_list, name='notification_list'),
    path('<int:pk>/', views.notification_detail, name='notification_detail'),

    # Notification Actions
    path('<int:pk>/read/', views.mark_as_read, name='mark_as_read'),
    path('<int:pk>/unread/', views.mark_as_unread, name='mark_as_unread'),
    path('<int:pk>/dismiss/', views.dismiss_notification, name='dismiss'),
    path('<int:pk>/delete/', views.delete_notification, name='delete'),

    # Bulk Actions
    path('mark-all-read/', views.mark_all_as_read, name='mark_all_as_read'),
    path('delete-all-read/', views.delete_all_read, name='delete_all_read'),
    path('bulk-action/', views.bulk_action, name='bulk_action'),

    # Preferences
    path('preferences/', views.notification_preferences, name='preferences'),

    # Announcements
    path('announcements/', views.announcement_list, name='announcements'),
    path('announcements/<int:pk>/dismiss/', views.dismiss_announcement, name='dismiss_announcement'),

    # API Endpoints
    path('api/notifications/', views.notifications_api, name='notifications_api'),
    path('api/count/', views.notifications_count, name='count'),
    path('api/announcements/', views.active_announcements_api, name='announcements_api'),
    path('api/stats/', views.notification_stats, name='stats'),

    # Admin Views (Staff Only)
    path('admin/dashboard/', views.admin_dashboard, name='admin_dashboard'),
    path('admin/templates/', views.admin_templates, name='admin_templates'),
    path('admin/categories/', views.admin_categories, name='admin_categories'),
    path('admin/announcements/', views.admin_announcements, name='admin_announcements'),
    path('admin/batches/', views.admin_batches, name='admin_batches'),
    path('admin/rules/', views.admin_rules, name='admin_rules'),
    path('admin/test/', views.test_notification, name='test_notification'),
]