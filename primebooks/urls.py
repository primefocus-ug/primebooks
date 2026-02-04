# primebooks/urls.py
from django.urls import path
from . import views

app_name = 'primebooks'

urlpatterns = [
    # Root desktop path - redirect to login or dashboard
    path('', views.DesktopDashboardView.as_view(), name='dashboard'),

    # Authentication
    path('login/', views.DesktopLoginView.as_view(), name='login'),
    path('logout/', views.DesktopLogoutView.as_view(), name='logout'),

    # Syncing
    path('syncing/', views.DesktopSyncingView.as_view(), name='syncing'),
    path('sync-status/', views.DesktopSyncStatusView.as_view(), name='sync_status'),
    path('manual-sync/', views.DesktopManualSyncView.as_view(), name='manual_sync'),

]
