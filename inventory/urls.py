from django.urls import path
from . import views
from . import importt
from . import efris_api
from .serviced import (
    ServiceListView, ServiceCreateView, ServiceUpdateView,
    ServiceDeleteView, ServiceDetailView,
    service_list_api, service_detail_api,service_statistics_api, service_search_api,
    service_bulk_actions, service_efris_sync
)
from .efris_api import (  # All from efris_api.py
    EFRISCategoryAutocompleteView,
    EFRISCategoryDetailView,
    EFRISCategoryStatsView,
)

app_name = 'inventory'

urlpatterns = [
    # Dashboard
    path('', views.inventory_dashboard, name='dashboard'),
    path('category/create/ajax/', views.category_create_ajax, name='category_create_ajax'),
    path('api/categories/<int:pk>/toggle-status/', views.toggle_category_status, name='category_toggle_status'),
    path('supplier/create/ajax/', views.supplier_create_ajax, name='supplier_create_ajax'),
    path('stock/<int:pk>/update/', views.StockUpdateView.as_view(), name='stock_update'),

    # Services
    path('services/', ServiceListView.as_view(), name='service_list'),
    path('services/add/', ServiceCreateView.as_view(), name='service_create'),
    path('services/<int:pk>/', ServiceDetailView.as_view(), name='service_detail'),
    path('services/<int:pk>/edit/', ServiceUpdateView.as_view(), name='service_update'),
    path('services/<int:pk>/delete/', ServiceDeleteView.as_view(), name='service_delete'),

    # Service API Endpoints
    path('api/services/', service_list_api, name='service_list_api'),
    path('api/services/statistics/', service_statistics_api, name='service_statistics_api'),
    path('api/services/<int:pk>/', service_detail_api, name='service_detail_api'),
    path('api/services/search/', service_search_api, name='service_search_api'),
    path('api/services/bulk-actions/', service_bulk_actions, name='service_bulk_actions'),
    path('api/services/<int:pk>/efris-sync/', service_efris_sync, name='service_efris_sync'),
    # Categories
    path('categories/', views.CategoryListView.as_view(), name='category_list'),
    path('categories/add/', views.CategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/edit/', views.CategoryUpdateView.as_view(), name='category_update'),
    path('categories/<int:pk>/delete/', views.CategoryDeleteView.as_view(), name='category_delete'),
    path('categories/<int:pk>/', views.CategoryDetailView.as_view(), name='category_detail'),

    # EFRIS Category API (NEW - Fixed order to prevent conflicts)
    path('api/efris-categories/autocomplete/',
         EFRISCategoryAutocompleteView.as_view(),
         name='efris_category_autocomplete'),
    path('api/efris-categories/stats/',
         EFRISCategoryStatsView.as_view(),
         name='efris_category_stats'),
    path('api/efris-categories/<str:code>/',
         EFRISCategoryDetailView.as_view(),
         name='efris_category_detail'),

    # Category API (User's categories - must come after EFRIS to avoid conflicts)
    path('api/categories/<int:pk>/',
         views.CategoryDetailAPIView.as_view(),
         name='category_detail_api'),

    path('efris/category-tree/', efris_api.EFRISCategoryTreeView.as_view(), name='efris_category_tree'),
    path('efris/category-children/', efris_api.EFRISCategoryChildrenView.as_view(), name='efris_category_children'),
    path('efris/category-results/', efris_api.EFRISCategoryResultsView.as_view(), name='efris_category_results'),
    path('efris/popular-categories/', efris_api.EFRISPopularCategoriesView.as_view(), name='efris_popular_categories'),
    path('efris/search-enhanced/', efris_api.EFRISCategorySearchEnhancedView.as_view(), name='efris_category_search_enhanced'),
    path('api/efris/clear-cache/', efris_api.ClearEFRISCacheView.as_view(), name='clear_efris_cache'),

    # Legacy endpoints (keep for backward compatibility)
    path('api/efris-categories/search/',
         views.efris_category_search,
         name='efris_category_search'),

    # Suppliers
    path('suppliers/', views.SupplierListView.as_view(), name='supplier_list'),
    path('suppliers/add/', views.SupplierCreateView.as_view(), name='supplier_create'),
    path('suppliers/<int:pk>/edit/', views.SupplierUpdateView.as_view(), name='supplier_update'),
    path('suppliers/<int:pk>/', views.SupplierDetailView.as_view(), name='supplier_detail'),

    # Products
    path('products/', views.ProductListView.as_view(), name='product_list'),
    path('products/add/', views.ProductCreateView.as_view(), name='product_create'),
    path('products/<int:pk>/', views.ProductDetailView.as_view(), name='product_detail'),
    path('products/<int:pk>/edit/', views.ProductUpdateView.as_view(), name='product_update'),
    path('products/<int:product_id>/barcode/', views.barcode_generator, name='barcode_generator'),
    path('product/delete/<int:pk>/', views.ProductDeleteView.as_view(), name='product_delete'),

    # Stock Management
    path('stock/', views.StockListView.as_view(), name='stock_list'),
    path('stock-adjustment/', views.StockAdjustmentView.as_view(), name='stock_adjustment'),
    path('quick-adjust/<int:stock_id>/', views.QuickStockAdjustmentRedirectView.as_view(), name='quick_adjust'),
    path('stock/current/', views.current_stock_api, name='current_stock_api'),
    path('stock/adjustments/recent/', views.recent_adjustments_api, name='recent_adjustments_api'),
    path('stock/export/', views.stock_export, name='stock_export'),
    path('stock/import/', importt.stock_import, name='stock_import'),
    path('dashboard/', views.StockDashboardView.as_view(), name='stock_dashboard'),
    path('api/dashboard-data/', views.stock_dashboard_data, name='stock_dashboard_data'),
    path('api/stock/', views.stock_api_view, name='stock_api'),
    path('api/stock/<int:stock_id>/', views.stock_api_view, name='stock_api_detail'),
    path('api/product/<int:product_id>/', views.product_api_view, name='product_api'),
    path('stock/create/', views.StockCreateView.as_view(), name='stock_create'),
    path('stock/<int:pk>/physical-count/', views.stock_physical_count, name='stock_physical_count'),

    # API endpoints
    path('api/product/<int:pk>/', views.product_detail_api, name='product_detail_api'),

    # Stock Movements
    path('movements/', views.StockMovementListView.as_view(), name='movement_list'),
    path('movements/add/', views.StockMovementCreateView.as_view(), name='movement_create'),
    path('movements/<int:pk>/edit/', views.StockMovementUpdateView.as_view(), name='movement_update'),
    path('api/movements/<int:pk>/', views.movement_detail_api, name='movement_detail_api'),

    # Bulk Operations
    path('products/bulk-actions/', views.bulk_product_actions, name='bulk_actions'),
    path('products/export/', views.export_products, name='export_products'),
    path('export/', importt.export_products_selection, name='export_products_selection'),
    path('export/csv/', importt.export_products_csv, name='export_products_csv'),
    path('export/excel/', importt.export_products_excel, name='export_products_excel'),
    path('bulk-import/', views.bulk_import_products, name='bulk_import'),
    path('api/analyze-import-file/', views.analyze_import_file, name='analyze_import_file'),
    path('api/process-bulk-import/', views.process_bulk_import, name='process_bulk_import'),
    path('api/download-template/<str:template_type>/', views.download_template, name='download_template'),
    path('api/products/up/', views.bulk_update_products_api, name="bulk_update_products_api"),
    path('api/dashboard/stats/', views.dashboard_stats_api, name='dashboard_stats_api'),
    path('api/dashboard/alerts/', views.stock_alerts_api, name='stock_alerts_api'),
    path('api/dashboard/movements/', views.recent_movements_api, name='recent_movements_api'),
    path('api/dashboard/top-products/', views.top_products_api, name='top_products_api'),
    path('api/dashboard/category-distribution/', views.category_distribution_api, name='category_distribution_api'),

    # Reports
    path('reports/low-stock/', views.low_stock_report, name='low_stock_report'),
    path('reports/valuation/', views.inventory_valuation_report, name='valuation_report'),
    path('reports/movements/', views.movement_analytics, name='movement_analytics'),
    path('reports/stock/print/', views.print_stock_report, name='print_stock_report'),

    # AJAX Endpoints
    path('api/products/autocomplete/', views.product_autocomplete, name='product_autocomplete'),
    path('api/products/<int:product_id>/', views.get_product_details, name='product_details_api'),
    path('api/products/stock/info/', views.get_product_stock_info, name="get_product_stock_info"),
    path('api/product-details/ug/<int:product_id>/', views.get_product_details, name="get_product_details"),
    path('api/bulk/stockadjustment/', views.bulk_stock_adjustment_api, name='bulk_stock_adjustment_api'),
    path('import-sessions/', views.import_sessions, name='import_sessions'),
    path('api/product/search/', views.product_search_api, name="product_search_api"),
    path('import-sessions/<int:session_id>/', views.import_session_detail, name='import_session_detail'),
    path('import-sessions/<int:session_id>/retry/', views.retry_import_session, name='retry_import_session'),
    path('api/import-sessions/<int:session_id>/status/', views.import_session_status_api,
         name='import_session_status_api'),
    path('stock/import/', views.stock_import, name='stock_import'),
    path('stock/import/session/<int:session_id>/', views.import_session_detail, name='import_session_detail'),

    # Sample File Downloads
    path('stock/import/sample/products-csv/', importt.download_sample_products_csv,
         name='download_sample_products_csv'),
    path('stock/import/sample/products-excel/', importt.download_sample_products_excel,
         name='download_sample_products_excel'),
    path('stock/import/sample/stock-csv/', importt.download_sample_stock_only_csv,
         name='download_sample_stock_only_csv'),
    path('stock/import/sample/stock-excel/', importt.download_sample_stock_only_excel,
         name='download_sample_stock_only_excel'),
    path('ajax/stock-details/<int:stock_id>/', views.stock_details_ajax, name='stock_details_ajax'),
    # Import Validation and Preview
    path('stock/import/preview/', importt.preview_import, name='preview_import'),
    path('stock/import/validate/', importt.validate_import_data, name='validate_import_data'),
    path('products/add/modal/', views.ProductCreateModalView.as_view(), name='product_create_modal'),
    path('products/add/ajax/', views.ProductCreateAjaxView.as_view(), name='product_create_ajax'),
    path('products/import/', views.product_import, name='product_import'),

    # Sample downloads for product import
    path('products/import/sample-csv/',
         importt.download_sample_products_only_csv,
         name='download_sample_products_csv'),
    path('products/import/sample-excel/',
         importt.download_sample_products_only_excel,
         name='download_sample_products_excel'),
    path('transfers/', views.StockTransferListView.as_view(), name='transfer_list'),
    path('transfers/create/', views.StockTransferCreateView.as_view(), name='transfer_create'),
    path('transfers/<int:pk>/', views.StockTransferDetailView.as_view(), name='transfer_detail'),
    path('transfers/<int:pk>/approve/', views.approve_transfer, name='transfer_approve'),
    path('transfers/<int:pk>/complete/', views.complete_transfer, name='transfer_complete'),
    path('transfers/<int:pk>/cancel/', views.cancel_transfer, name='transfer_cancel'),

    # AJAX endpoints
    path('api/product-availability/', views.check_product_availability, name='product_availability'),
]

