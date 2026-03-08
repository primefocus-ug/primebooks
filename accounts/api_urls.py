from django.urls import path
from . import api_views as views
from . import tracking_api
from django.views.generic import TemplateView
from . import general_tracker

urlpatterns = [
    # 1. Serves the HTML page
    path("tracker/", TemplateView.as_view(template_name="accounts/tracker_report.html"), name="tracker-report"),

    # 2. Serves the JSON data the HTML's JS calls
    path("report/", general_tracker.GeneralTrackerView.as_view(), name="general-report"),

    # ── Authentication ────────────────────────────────────────────────────────
    path('auth/register/',         views.RegisterView.as_view(),      name='register'),
    path('auth/login/',            views.LoginView.as_view(),          name='login'),
    path('auth/logout/',           views.LogoutView.as_view(),         name='logout'),
    path('auth/password/change/',  views.PasswordChangeView.as_view(), name='password-change'),
    path("track/", tracking_api.TrackingAPIView.as_view(), name="universal-track"),
    # ── Current-user profile ──────────────────────────────────────────────────
    path('auth/me/',                   views.MeView.as_view(),             name='me'),
    path('auth/me/signature/',         views.MySignatureView.as_view(),    name='my-signature'),
    path('auth/me/login-history/',     views.MyLoginHistoryView.as_view(), name='my-login-history'),

    # ── User management ───────────────────────────────────────────────────────
    path('users/',                     views.UserListCreateView.as_view(), name='user-list'),
    path('users/stats/',               views.UserStatsView.as_view(),      name='user-stats'),
    path('users/<int:pk>/',            views.UserDetailView.as_view(),     name='user-detail'),
    path('users/<int:pk>/activate/',   views.UserActivateView.as_view(),   name='user-activate'),
    path('users/<int:pk>/lock/',       views.LockUserView.as_view(),       name='user-lock'),
    path('users/<int:pk>/unlock/',     views.UnlockUserView.as_view(),     name='user-unlock'),

    # ── Role assignment ───────────────────────────────────────────────────────
    path('users/<int:pk>/roles/',              views.UserRolesView.as_view(),      name='user-roles'),
    path('users/<int:pk>/roles/assign/',       views.AssignRoleView.as_view(),     name='role-assign'),
    path('users/<int:pk>/roles/remove/',       views.RemoveRoleView.as_view(),     name='role-remove'),
    path('users/<int:pk>/roles/set-primary/',  views.SetPrimaryRoleView.as_view(), name='role-set-primary'),

    # ── Signature management (admin) ──────────────────────────────────────────
    path('users/<int:pk>/signature/',          views.UserSignatureAdminView.as_view(), name='user-signature'),
    path('users/<int:pk>/signature/verify/',   views.VerifySignatureView.as_view(),    name='signature-verify'),

    # ── Roles catalogue ───────────────────────────────────────────────────────
    path('roles/',          views.RoleListView.as_view(),   name='role-list'),
    path('roles/<int:pk>/', views.RoleDetailView.as_view(), name='role-detail'),

    # ── Audit logs ────────────────────────────────────────────────────────────
    path('audit-logs/',                views.AuditLogListView.as_view(),   name='audit-log-list'),
    path('audit-logs/<int:pk>/',       views.AuditLogDetailView.as_view(), name='audit-log-detail'),
    path('audit-logs/<int:pk>/review/', views.ReviewAuditLogView.as_view(), name='audit-log-review'),
]