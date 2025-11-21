from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CustomerViewSet, CustomerGroupViewSet, CustomerNoteViewSet
from . import views
from . import view

app_name = 'customers'

router = DefaultRouter()
router.register(r'customers', CustomerViewSet)
router.register(r'groups', CustomerGroupViewSet)
router.register(r'notes', CustomerNoteViewSet)

urlpatterns = [
    path('', views.CustomerDashboardView.as_view(), name='dashboard'),

    # Customer CRUD operations
    path('list/', views.CustomerListView.as_view(), name='customer_list'),  # Changed name for consistency
    path('create/', views.CustomerCreateView.as_view(), name='create'),
    path('<int:pk>/', views.CustomerDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.CustomerUpdateView.as_view(), name='update'),
    path('<int:pk>/delete/', views.CustomerDeleteView.as_view(), name='delete'),

    # Customer notes
    path('<int:pk>/add-note/', views.add_customer_note, name='add_note'),

    # Bulk operations
    path('bulk-action/', views.bulk_customer_action, name='bulk_action'),
    path('export/', views.export_customers, name='export'),

    # Customer Groups
    path('groups/', views.CustomerGroupListView.as_view(), name='group_list'),
    path('groups/create/', views.CustomerGroupCreateView.as_view(), name='group_create'),
    path('groups/<int:pk>/edit/', views.CustomerGroupUpdateView.as_view(), name='group_update'),
    path('groups/<int:pk>/delete/', views.CustomerGroupDeleteView.as_view(), name='group_delete'),

    # API endpoints
    path('api/autocomplete/', views.customer_autocomplete, name='autocomplete'),
    path('api/stats/', views.customer_stats_api, name='stats_api'),
    path('api/validate-field/', views.validate_customer_field, name='validate_field'),
    path('api/search-with-store/', views.customer_search_with_store, name='search_with_store'),
    path('api/store-customers/', views.get_store_customers, name='store_customers'),

    # Sample file downloads (must come BEFORE import/ to avoid conflicts)
    path('import/sample/csv/', view.download_sample_customers_csv, name='download_sample_csv'),
    path('import/sample/excel/', view.download_sample_customers_excel, name='download_sample_excel'),

    # Import views (validation and preview must come BEFORE main import)
    path('import/preview/', view.preview_customer_import, name='preview_import'),
    path('import/validate/', view.validate_customer_import, name='validate_import'),
    path('import/', view.customer_import, name='customer_import'),  # Main import - must be LAST
    # Export views
    path('export/csv/', view.export_customers_csv, name='export_csv'),
    path('export/excel/', view.export_customers_excel, name='export_excel'),
    path('export/pdf/', view.export_customers_pdf, name='export_pdf'),

    # API router (must be last)
    path('api/', include(router.urls)),
]