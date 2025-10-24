from django.urls import path
from . import views

app_name = 'sales'

urlpatterns = [
    # Main Views
    path('', views.SalesListView.as_view(), name='sales_list'),
    path('create/', views.create_sale, name='create_sale'),
    path('create-customers-from/efris', views.create_customer_ajax,name='create_customer_ajax'),
    path('quick-sale/', views.quick_sale, name='quick_sale'),
    path('pos/', views.pos_interface, name='pos_interface'),
    path('analytics/', views.sales_analytics, name='analytics'),
    path('fiscalize/<int:sale_id>/', views.fiscalize_sale, name='fiscalize_sale'),
    path('efris-status/', views.sales_efris_status, name='efris_status'),
    
    # Sale Detail and Management
    path('<int:pk>/', views.SaleDetailView.as_view(), name='sale_detail'),
    path('<int:sale_id>/refund/', views.process_refund, name='process_refund'),
    path('<int:sale_id>/void/', views.void_sale, name='void_sale'),
    path('<int:sale_id>/print-receipt/', views.print_receipt, name='print_receipt'),
    
    # Cart Management (AJAX)
    path('add-to-cart/', views.add_to_cart, name='add_to_cart'),
    path('remove-from-cart/<int:item_id>/', views.remove_from_cart, name='remove_from_cart'),
    path('checkout-cart/', views.checkout_cart, name='checkout_cart'),
    
    # Search and Utility (AJAX)
    path('product-search/', views.search_products, name='product_search'),
    path('customer-search/', views.search_customers, name='customer_search'),
    path("<int:sale_id>/duplicate/", views.duplicate_sale, name="duplicate_sale"),
    path("<int:sale_id>/send-receipt/", views.send_receipt, name="send_receipt"),

    
    # Bulk Actions
    path('bulk-actions/', views.bulk_actions, name='bulk_actions'),
    
    # API Endpoints
    path('api/create-sale/', views.api_create_sale, name='api_create_sale'),
    path('api/store-sales/', views.store_sales_api, name='store_sales_api'),
]