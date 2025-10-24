from django.urls import path
from . import views

app_name = 'inventory_api'

urlpatterns = [
    # Category endpoints
    path('categories/', views.CategoryListCreateView.as_view(), name='category-list-create'),
    path('categories/<int:pk>/', views.CategoryRetrieveUpdateDestroyView.as_view(), name='category-detail'),

    # Supplier endpoints
    path('suppliers/', views.SupplierListCreateView.as_view(), name='supplier-list-create'),
    path('suppliers/<int:pk>/', views.SupplierRetrieveUpdateDestroyView.as_view(), name='supplier-detail'),

    # Product endpoints
    path('products/', views.ProductListCreateView.as_view(), name='product-list-create'),
    path('products/<int:pk>/', views.ProductRetrieveUpdateDestroyView.as_view(), name='product-detail'),
    path('products/search/', views.product_search_api, name='product-search'),
    path('products/bulk-update/', views.bulk_update_products_api, name='product-bulk-update'),

    # Stock endpoints
    path('stock/', views.StockListCreateView.as_view(), name='stock-list-create'),
    path('stock/<int:pk>/', views.StockRetrieveUpdateDestroyView.as_view(), name='stock-detail'),
    path('stock/bulk-adjustment/', views.bulk_stock_adjustment_api, name='stock-bulk-adjustment'),

    # Stock movement endpoints
    path('movements/', views.StockMovementListCreateView.as_view(), name='movement-list-create'),
    path('movements/<int:pk>/', views.StockMovementRetrieveUpdateDestroyView.as_view(), name='movement-detail'),

    path('import-sessions/', views.ImportSessionListView.as_view(), name='import-session-list'),
    path('import-sessions/<int:pk>/', views.ImportSessionRetrieveView.as_view(), name='import-session-detail'),

    path('dashboard/stats/', views.dashboard_stats_api, name='dashboard-stats'),
    path('dashboard/low-stock-alerts/', views.low_stock_alert_api, name='low-stock-alerts'),
    path('dashboard/recent-movements/', views.recent_movements_api, name='recent-movements'),

    path('reports/inventory/', views.inventory_report_api, name='inventory-report'),
    path('reports/movements/', views.movement_report_api, name='movement-report'),
    path('reports/low-stock/', views.low_stock_report_api, name='low-stock-report'),
    path('reports/valuation/', views.valuation_report_api, name='valuation-report'),
]