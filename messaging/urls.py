from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views
from . import views_html
from . import admin_views

app_name = 'messaging'

urlpatterns = [
    # -----------------------
    # User (HTML) Messaging Views
    # -----------------------
    path('', views_html.messaging_index, name='index'),
    path('conversation/<int:conversation_id>/', views_html.conversation_detail, name='conversation_detail'),
    path('create/', views_html.create_conversation, name='create_conversation'),
    path('conversation/<int:conversation_id>/mark-read/', views_html.mark_all_read, name='mark_all_read'),

    # AJAX / utility endpoints
    path('users/search/', views_html.user_search, name='user_search'),
    path('notifications/count/', views_html.notifications_count, name='notifications_count'),

    # -----------------------
    # Admin Dashboard and Management
    # -----------------------
    path('admin/', admin_views.admin_dashboard, name='admin_dashboard'),
    path('admin/conversations/', admin_views.admin_conversations_list, name='admin_conversations'),
    path('admin/conversation/<int:conversation_id>/', admin_views.admin_conversation_detail, name='admin_conversation_detail'),

    # Announcements
    path('admin/announcements/', admin_views.admin_announcements, name='admin_announcements'),
    path('admin/announcements/create/', admin_views.admin_create_announcement, name='admin_create_announcement'),

    # Audit logs
    path('admin/audit-log/', admin_views.admin_audit_log, name='admin_audit_log'),

    # Statistics
    path('admin/statistics/', admin_views.admin_statistics, name='admin_statistics'),
    path('admin/statistics/export/', admin_views.export_statistics_csv, name='export_statistics'),

    # -----------------------
    # Legal Access Management
    # -----------------------
    path('admin/legal-requests/', admin_views.legal_requests_list, name='legal_requests'),
    path('admin/legal-request/<int:request_id>/', admin_views.legal_request_detail, name='legal_request_detail'),
    path('admin/legal-request/create/', admin_views.create_legal_request, name='create_legal_request'),
    path('admin/legal-request/<int:request_id>/approve/', admin_views.approve_legal_request, name='approve_legal_request'),
    path('admin/legal-request/<int:request_id>/deny/', admin_views.deny_legal_request, name='deny_legal_request'),
    path('admin/legal-request/<int:request_id>/export/', admin_views.export_legal_messages, name='export_legal_messages'),
    path('admin/legal-request/<int:request_id>/download/', admin_views.download_legal_export, name='download_legal_export'),
]
