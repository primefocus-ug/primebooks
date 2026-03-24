from django.urls import path
from . import views
from . import view
from . import pos
from sales.sales_hub import SalesHubView
from sales.pesapal_views import (
    initiate_pesapal_payment,
    pesapal_sale_callback,
    send_payment_link,
)

# Add these 3 paths inside urlpatterns = [...]
path('pesapal/initiate/<int:sale_id>/',
     initiate_pesapal_payment,
     name='initiate_pesapal_payment'),

path('pesapal/callback/<int:sale_id>/',
     pesapal_sale_callback,
     name='pesapal_sale_callback'),

path('pesapal/send-link/<int:sale_id>/',
     send_payment_link,
     name='send_payment_link'),

from .view import drafts_list

app_name = 'sales'

urlpatterns = [
    # Main Views
    path('', SalesHubView.as_view(), name='sales_list'),
    path('create/', views.create_sale, name='create_sale'),
    path('email-draft/', view.email_draft, name='email_draft'),
    path('recent-customers/', views.recent_customers_api, name='recent_customers'),
    path('create-with-progress/', views.create_sale_with_progress, name='create_sale_with_progress'),
    path('task-status/<str:task_id>/', views.get_task_status, name='get_task_status'),
    path('create-customer-ajax/', views.create_customer_ajax,name='create_customer_ajax'),
    path('pos/', views.pos_interface, name='pos_interface'),
    path('analytics/', views.sales_analytics, name='analytics'),
    path('analytics/day-details/', views.analytics_day_details, name='analytics_day_details'),
    path('fiscalize/<int:sale_id>/', views.fiscalize_sale, name='fiscalize_sale'),
    path('efris-status/', views.sales_efris_status, name='efris_status'),
    path('quick/', pos.quick_sale_view, name='quick_sale'),
    path('pesapal/initiate/<int:sale_id>/',
         initiate_pesapal_payment,
         name='initiate_pesapal_payment'),

    path('pesapal/callback/<int:sale_id>/',
         pesapal_sale_callback,
         name='pesapal_sale_callback'),

    path('pesapal/send-link/<int:sale_id>/',
         send_payment_link,
         name='send_payment_link'),
    # API endpoints for Quick POS
    path('api/search-items/', pos.search_items_api, name='search_items_api'),
    path('api/customer-search/', pos.customer_search_api, name='customer_search_api'),
    path('api/create-sale/', pos.create_sale_api, name='create_sale_api'),
    path('api/recent-customers/', pos.recent_customers_api, name='recent_customers_api'),
    path('api/email-draft/', pos.email_draft, name='email_draft'),

    # Receipt view
    path('<int:sale_id>/receipt/', pos.sale_receipt_view, name='sale_receipt'),
    path('<int:sale_id>/add-payment/', views.add_payment, name='add_payment'),
    
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
    path('service-search/', views.search_services, name='service_search'),
    path('analytics/day-details/', views.analytics_day_details, name='analytics_day_details'),# NEW
    path('search-items/', views.search_products_and_services, name='search_items'),
    path('customer-search/', views.search_customers, name='customer_search'),
    path("<int:sale_id>/duplicate/", views.duplicate_sale, name="duplicate_sale"),
    path("<int:sale_id>/send-receipt/", views.send_receipt, name="send_receipt"),

    
    # Bulk Actions
    path('bulk-actions/', views.bulk_actions, name='bulk_actions'),
    
    # API Endpoints
    path('api/create-sale/', views.api_create_sale, name='api_create_sale'),
    path('api/store-sales/', views.store_sales_api, name='store_sales_api'),
]