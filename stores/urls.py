# stores/urls.py

from django.urls import path
from . import views

app_name = 'stores'

urlpatterns = [
    # Dashboard
    path('', views.store_dashboard, name='dashboard'),
    path('dashboard/', views.store_dashboard, name='store_dashboard'),

    # Store CRUD
    path('stores/', views.StoreListView.as_view(), name='store_list'),
    path('stores/create/', views.StoreCreateView.as_view(), name='store_create'),
    path('stores/<int:pk>/', views.StoreDetailView.as_view(), name='store_detail'),
    path('stores/<int:pk>/edit/', views.StoreUpdateView.as_view(), name='store_edit'),
    path('stores/<int:pk>/delete/', views.StoreDeleteView.as_view(), name='store_delete'),

    # Staff Management
    path('stores/<int:pk>/staff/', views.manage_store_staff, name='manage_staff'),

    # Bulk Operations
    path('stores/bulk-actions/', views.bulk_store_actions, name='bulk_actions'),

    # Operating Hours
    path('operating-hours/create/', views.StoreOperatingHoursCreateView.as_view(), name='hours_create'),
    path('operating-hours/<int:pk>/edit/', views.StoreOperatingHoursUpdateView.as_view(), name='hours_edit'),

    # Devices
    path('devices/', views.StoreDeviceListView.as_view(), name='device_list'),
    path('devices/create/', views.StoreDeviceCreateView.as_view(), name='device_create'),
    path('devices/<int:pk>/', views.StoreDeviceDetailView.as_view(), name='device_detail'),
    path('devices/<int:pk>/edit/', views.StoreDeviceUpdateView.as_view(), name='device_edit'),
    path('devices/<int:device_id>/maintenance/', views.device_maintenance_update, name='device_maintenance'),

    # Inventory
    path('inventory/', views.StoreInventoryListView.as_view(), name='inventory_list'),
    path('inventory/add/', views.StoreInventoryCreateView.as_view(), name='inventory_create'),
    path('inventory/<int:pk>/', views.StoreInventoryDetailView.as_view(), name='inventory_detail'),
    path('inventory/<int:pk>/edit/', views.StoreInventoryUpdateView.as_view(), name='inventory_update'),
    path('inventory/<int:pk>/delete/', views.StoreInventoryDeleteView.as_view(), name='inventory_delete'),

    # AJAX/API endpoints
    path('api/inventory/search/', views.inventory_search_api, name='inventory_search_api'),
    path('api/inventory/<int:pk>/quick-update/', views.quick_quantity_update, name='quick_quantity_update'),
    path('api/inventory/low-stock-alerts/', views.low_stock_alert_api, name='low_stock_alert_api'),
    path('inventory/low-stock/', views.low_stock_alert, name='low_stock_alert'),

    # Analytics & Reports - ADDED/FIXED
    path('analytics/', views.store_analytics, name='analytics'),
    path('reports/generate/', views.generate_store_report, name='generate_report'),
    path('reports/export/<str:report_type>/', views.export_report_direct, name='export_report_direct'),
    path('map/', views.store_map_view, name='store_map'),

    # Device Logs
    path('logs/', views.DeviceOperatorLogListView.as_view(), name='device_logs'),

    # API Endpoints
    path('api/data/', views.store_api_data, name='api_data'),

    # POS Interface - ADDED
    path('pos/', views.pos_interface, name='pos_interface'),
    path('pos/product-search/', views.pos_product_search, name='pos_product_search'),
    path('pos/customer-search/', views.pos_customer_search, name='pos_customer_search'),
    path('pos/create-sale/', views.pos_create_sale, name='pos_create_sale'),
    path('pos/quick-customer/', views.pos_quick_customer, name='pos_quick_customer'),

    # Export
    path('export/', views.export_stores_data, name='export_data'),
    path('api/data/', views.store_api_data, name='store_api_data'),
    path('api/store/<int:store_id>/details/', views.store_details_api, name='store_details_api'),
    path('api/nearest/', views.nearest_stores_api, name='nearest_stores_api'),
    path('my-sessions/', views.user_sessions_view, name='user_sessions'),
    path('sessions/<int:session_id>/terminate/', views.terminate_session_view, name='terminate_session'),
    path('sessions/terminate-all/', views.terminate_all_sessions_view, name='terminate_all_sessions'),
    path('devices/<int:fingerprint_id>/trust/', views.trust_device_view, name='trust_device'),
    path('devices/<int:fingerprint_id>/remove/', views.remove_device_view, name='remove_device'),

    # API endpoints for AJAX
    path('api/sessions/active/', views.api_active_sessions, name='api_active_sessions'),
    path('api/sessions/<int:session_id>/extend/', views.api_extend_session, name='api_extend_session'),
    path('api/security/alerts/', views.api_security_alerts, name='api_security_alerts'),

    # Admin dashboards
    path('admin/device-sessions/', views.device_sessions_dashboard, name='device_sessions_dashboard'),
    path('admin/security-alerts/', views.security_alerts_view, name='security_alerts'),
    path('admin/security-alerts/<int:alert_id>/resolve/', views.resolve_security_alert, name='resolve_security_alert'),
    path('admin/device-fingerprints/', views.device_fingerprints_view, name='device_fingerprints'),

    # Reports
    path('reports/device-sessions/', views.device_session_report, name='device_session_report'),
    path('reports/security/', views.security_report, name='security_report'),
]