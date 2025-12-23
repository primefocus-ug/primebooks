from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet, CustomerGroupViewSet, CustomerNoteViewSet
# Import everything from views.py with an alias
from . import views as customers_views
# Import everything from view.py with an alias
from . import view as import_export_views

app_name = 'customers'

router = DefaultRouter()
router.register(r'customers', CustomerViewSet)
router.register(r'groups', CustomerGroupViewSet)
router.register(r'notes', CustomerNoteViewSet)

urlpatterns = [
    path('', customers_views.CustomerDashboardView.as_view(), name='dashboard'),

    # Customer CRUD operations - from views.py
    path('list/', customers_views.CustomerListView.as_view(), name='customer_list'),
    path('create/', customers_views.CustomerCreateView.as_view(), name='create'),
    path('store/<int:store_id>/credit-info/', customers_views.store_customer_credit_info, name='store_credit_info'),
    path('credit-report/', customers_views.CustomerCreditReportView.as_view(), name='credit_report'),
    path('export-credit-report/', customers_views.export_credit_report, name='export_credit_report'),
    path('bulk-update-credit-limits/', customers_views.bulk_update_credit_limits, name='bulk_update_credit_limits'),

    # Update existing customers_views
    path('<int:pk>/update-credit-status/', customers_views.CustomerViewSet.as_view({'post': 'update_credit_status'}),
         name='customer_update_credit_status'),
    path('<int:pk>/check-credit/', customers_views.CustomerViewSet.as_view({'post': 'check_credit'}),
         name='customer_check_credit'),
    path('credit-report-api/', customers_views.CustomerViewSet.as_view({'get': 'credit_report'}), name='credit_report_api'),
    path('<int:pk>/', customers_views.CustomerDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', customers_views.CustomerUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', customers_views.CustomerDeleteView.as_view(), name='delete'),

    # Customer notes - from views.py
    path('<int:pk>/add-note/', customers_views.add_customer_note, name='add_note'),

    # Bulk operations - from views.py
    path('bulk-action/', customers_views.bulk_customer_action, name='bulk_action'),

    # Import/Export operations - from view.py
    path('import/', import_export_views.customer_import, name='customer_import'),

    # Sample file downloads - from view.py
    path('import/sample/csv/', import_export_views.download_sample_customers_csv, name='download_sample_csv'),
    path('import/sample/excel/', import_export_views.download_sample_customers_excel, name='download_sample_excel'),
    path('import/preview/', import_export_views.preview_customer_import, name='preview_import'),
    path('import/validate/', import_export_views.validate_customer_import, name='validate_import'),

    # Export views - from view.py
    path('export/csv/', import_export_views.export_customers_csv, name='export_csv'),
    path('export/excel/', import_export_views.export_customers_excel, name='export_excel'),
    path('export/pdf/', import_export_views.export_customers_pdf, name='export_pdf'),

    # API endpoints - from views.py
    path('api/autocomplete/', customers_views.customer_autocomplete, name='autocomplete'),
    path('api/stats/', customers_views.customer_stats_api, name='stats_api'),
    path('api/validate-field/', customers_views.validate_customer_field, name='validate_field'),
    path('api/search-with-store/', customers_views.customer_search_with_store, name='search_with_store'),
    path('api/store-customers/', customers_views.get_store_customers, name='store_customers'),

    # Customer Groups - from views.py
    path('groups/', customers_views.CustomerGroupListView.as_view(), name='group_list'),
    path('groups/create/', customers_views.CustomerGroupCreateView.as_view(), name='group_create'),
    path('groups/<int:pk>/edit/', customers_views.CustomerGroupUpdateView.as_view(), name='group_update'),
    path('groups/<int:pk>/delete/', customers_views.CustomerGroupDeleteView.as_view(), name='group_delete'),

    # eFRIS operations - from views.py
    path('efris/dashboard/', customers_views.EFRISCustomerDashboardView.as_view(), name='efris_dashboard'),
    path('<int:pk>/sync-efris/', customers_views.sync_customer_to_efris, name='sync_efris'),
    path('api/efris-status/', customers_views.efris_sync_status_api, name='efris_status_api'),
    path('efris/sync/<int:sync_id>/retry/', customers_views.retry_failed_efris_sync, name='retry_efris_sync'),

    # Export from views.py (general export)
    path('export/', customers_views.export_customers, name='export'),

    # API router (must be last)
    path('api/', include(router.urls)),
]