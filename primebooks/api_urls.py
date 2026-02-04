# api/urls.py (on your SERVER, not desktop app)
from django.urls import path
from primebooks.sync_api_views import (
    BulkDataDownloadView,
    ModelDataDownloadView,
    SyncStatusView,
)
from . api_views import DesktopLoginView, DesktopUserSyncView, DesktopCompanyDetailsView

urlpatterns = [
    # Desktop authentication endpoints
    path('desktop/auth/login/', DesktopLoginView.as_view(), name='desktop_login'),
    path('desktop/sync/user/<str:email>/', DesktopUserSyncView.as_view(), name='desktop_user_sync'),
    path('desktop/company/details/', DesktopCompanyDetailsView.as_view(), name='desktop_company_details'),
    # Bulk download - downloads all data at once
    path('desktop/sync/bulk-download/',
         BulkDataDownloadView.as_view(),
         name='desktop_bulk_download'),

    # Model-specific download
    path('desktop/sync/model/<str:model_name>/',
         ModelDataDownloadView.as_view(),
         name='desktop_model_download'),

    # Sync status
    path('desktop/sync/status/',
         SyncStatusView.as_view(),
         name='desktop_sync_status'),
]