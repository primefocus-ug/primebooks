# primebooks/api_urls.py - ADD THIS LINE
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from primebooks.sync_api_views import (
    BulkDataDownloadView,
    ModelDataDownloadView,
    SyncStatusView,
    ChangesDownloadView,
    UploadChangesView,
)
from .api_views import (
    DesktopLoginView,
    DesktopUserSyncView,
    DesktopCompanyDetailsView,
    health_check
)

urlpatterns = [
    # =========================================================================
    # AUTHENTICATION ENDPOINTS
    # =========================================================================
    path('desktop/auth/login/',
         DesktopLoginView.as_view(),
         name='desktop_login'),

    # ✅ ADD THIS - Token refresh endpoint
    path('token/refresh/',
         TokenRefreshView.as_view(),
         name='token_refresh'),

    path('desktop/sync/user/<str:email>/',
         DesktopUserSyncView.as_view(),
         name='desktop_user_sync'),

    path('desktop/company/details/',
         DesktopCompanyDetailsView.as_view(),
         name='desktop_company_details'),

    # =========================================================================
    # HEALTH CHECK
    # =========================================================================
    path('health/',
         health_check,
         name='api_health'),

    # =========================================================================
    # SYNC ENDPOINTS
    # =========================================================================

    path('desktop/sync/bulk-download/',
         BulkDataDownloadView.as_view(),
         name='desktop_bulk_download'),

    path('desktop/sync/changes/',
         ChangesDownloadView.as_view(),
         name='desktop_sync_changes'),

    path('desktop/sync/upload/',
         UploadChangesView.as_view(),
         name='desktop_sync_upload'),

    path('desktop/sync/model/<str:model_name>/',
         ModelDataDownloadView.as_view(),
         name='desktop_model_download'),

    path('desktop/sync/status/',
         SyncStatusView.as_view(),
         name='desktop_sync_status'),
]