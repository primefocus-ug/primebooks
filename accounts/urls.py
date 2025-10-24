from django.urls import path
from . import views
from . import view
from . import saas

saas_admin_patterns = [
    path('admin/d/dashboard/', saas.saas_admin_dashboard, name='saas_admin_dashboard'),

    # Legacy redirect
    path('system/d/dashboard/', saas.system_admin_dashboard, name='system_admin_dashboard'),

    # Tenant Switching
    path('admin/switch-tenant/', saas.switch_tenant_view, name='switch_tenant_view'),
    path('admin/clear-tenant/', saas.clear_tenant_view, name='clear_tenant_view'),
    path('api/admin/stats/', saas.admin_quick_stats_api, name='admin_quick_stats_api'),
    # User Impersonation
    path('admin/impersonate/<int:user_id>/', views.saas_admin_user_impersonate, name='saas_admin_user_impersonate'),

    path('saas-admin/dashboard/', views.saas_admin_dashboard, name='saas_admin_dashboard'),
    path('saas-admin/switch-tenant/', views.switch_tenant_view, name='saas_admin_switch_tenant'),
    path('saas-admin/impersonate/<int:user_id>/', views.saas_admin_user_impersonate, name='saas_admin_impersonate'),
    path('saas-admin/stop-impersonation/', views.saas_admin_stop_impersonation, name='saas_admin_stop_impersonation'),
    path('saas-admin/system-settings/', views.saas_admin_system_settings, name='saas_admin_system_settings'),
    path('saas-admin/audit-log/', views.saas_admin_audit_log, name='saas_admin_audit_log'),
]

urlpatterns = [
    path('login/', views.custom_login, name='login'),
    path('logout/', views.custom_logout, name='custom_logout'),
    
    path('users/', views.UserListView.as_view(), name='user_list'),
    path('users/create/', views.UserCreateView.as_view(), name='user_create'),
    path('users/<int:pk>/', views.UserDetailView.as_view(), name='user_detail'),
    path('users/<int:pk>/edit/', views.UserUpdateView.as_view(), name='user_update'),
    path('users/<int:pk>/delete/', views.UserDeleteView.as_view(), name='user_delete'),
    path('users/<int:pk>/unlock/', views.unlock_user, name='unlock_user'),
    
    path('users/bulk-actions/', views.bulk_user_actions, name='bulk_user_actions'),
    path('users/export/', views.export_users, name='export_users'),
    
    path('profile/', views.user_profile, name='user_profile'),
    path('profile/upload-avatar/', views.upload_avatar_ajax, name='upload_avatar_ajax'),
    path('profile/delete-avatar/', views.delete_avatar, name='delete_avatar'),
    path('profile/export-data/', views.export_profile_data, name='export_profile_data'),
    path('profile/security/', views.user_security_settings, name='user_security_settings'),
    path('profile/notifications/', views.user_notification_settings, name='user_notification_settings'),
    path('profile/preferences/', views.user_preferences, name='user_preferences'),

    # Email and phone verification
    path('profile/verify-email/', views.verify_email, name='verify_email'),
    path('profile/verify-phone/', views.verify_phone, name='verify_phone'),
    path('profile/send-verification/', views.send_verification, name='send_verification'),

    # Two-factor authentication
    path('profile/enable-2fa/', views.enable_two_factor, name='enable_2fa'),
    path('profile/disable-2fa/', views.disable_two_factor, name='disable_2fa'),
    path("verify_2fa/", views.verify_2fa, name="verify_2fa"),
    path('profile/backup-codes/', views.generate_backup_codes, name='generate_backup_codes'),

    # Account management
    path('profile/deactivate/', views.deactivate_account, name='deactivate_account'),
    path('profile/download-data/', views.download_user_data, name='download_user_data'),

    path('profile/password/', views.change_password, name='change_password'),
    path('password-reset/', view.password_reset_request, name='password_reset_request'),
    path('password-reset-confirm/<uidb64>/<token>/', view.password_reset_confirm, name='password_reset_confirm'),
    path('profile/signature/', views.user_signature, name='user_signature'),
    
    path('security/two-factor/setup/', views.two_factor_setup, name='two_factor_setup'),
    path('security/two-factor/disable/', views.disable_two_factor, name='disable_two_factor'),
    
    path('analytics/', views.user_analytics, name='user_analytics'),
    path('analytics/export/', views.export_analytics_data, name='export_analytics_data'),
    
    path('api/quick-stats/', views.user_quick_stats, name='user_quick_stats'),
    path('api/check-username/', views.check_username_availability, name='check_username'),
    path('api/check-email/', views.check_email_availability, name='check_email'),
    path('system/',views.system_companies_list,name='system_companies_list'),
    path('roles/', view.role_list, name='role_list'),
    path('roles/creat/', views.RoleCreateView.as_view(), name='role-create'),
    path('roles/create/', view.role_create, name='role_create'),
    path('rols/<int:pk>/', views.RoleDetailView.as_view(), name='role_details'),
    path('roles/<int:pk>/', view.role_detail, name='role_detail'),
    path('roles/<int:pk>/edit/', views.RoleUpdateView.as_view(), name='role_edit'),
    path('roles/<int:pk>/delete/', views.RoleDeleteView.as_view(), name='role_delete'),
    path('roles/assign-users/', views.UserRoleAssignView.as_view(), name='assign_role_users'),

    # Advanced role management
    path('roles/bulk-assignment/', views.RoleBulkAssignmentView.as_view(), name='role_bulk_assignment'),
    path('roles/<int:pk>/analytics/', views.RoleAnalyticsView.as_view(), name='role_analytics'),
    path('roles/<int:pk>/history/', views.RoleHistoryView.as_view(), name='role_history'),
    path('roles/history/', views.RoleHistoryView.as_view(), name='all_role_history'),

    # AJAX/API endpoints
    path('roles/<int:pk>/toggle-active/', views.RoleToggleActiveView.as_view(), name='role_toggle_active'),
    path('roles/<int:pk>/permissions/', views.RolePermissionsAPIView.as_view(), name='role_permissions_api'),
    path('roles/autocomplete/', views.RoleAutocompleteView.as_view(), name='role_autocomplete'),
    path('roles/<int:pk>/permission/', view.role_permissions, name='role_permissions'),
    path('roles/<int:pk>/users/', view.role_users, name='role_users'),
    path('roles/<int:pk>/check-capacity/', view.role_check_capacity, name='role_check_capacity'),
    path('roles/<int:pk>/permission-preview/', view.role_permission_preview, name='role_permission_preview'),

] + saas_admin_patterns

account_management_urls = [
    # Privacy and data management
    path('profile/privacy/', views.privacy_settings, name='privacy_settings'),
    path('profile/data-export/', views.export_all_data, name='export_all_data'),
    path('profile/delete-account/', views.delete_account_request, name='delete_account_request'),

    # Activity and sessions
    path('profile/activity/', views.user_activity_log, name='user_activity_log'),
    path('profile/sessions/', views.active_sessions, name='active_sessions'),
    path('profile/revoke-session/<int:session_id>/', views.revoke_session, name='revoke_session'),

    # API tokens and integrations
    path('profile/api-tokens/', views.api_tokens, name='api_tokens'),
    path('profile/integrations/', views.user_integrations, name='user_integrations'),
]

urlpatterns += account_management_urls