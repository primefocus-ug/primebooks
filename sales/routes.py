from django.urls import path
from . import sales
from . import views
from . import view
from .views import  void_sale, process_refund, print_receipt

app_name = 'sales'

urlpatterns = [
# Enhanced sale creation
path('create/', sales.create_sale_enhanced, name='create_sale_enhanced'),
path('create/preview/', sales.show_preview, name='preview_sale'),

# Draft management
path('drafts/<int:pk>/edit/', sales.edit_draft, name='edit_draft'),
path('drafts/<int:pk>/delete/', view.delete_draft, name='delete_draft'),

# Sale management
path('', views.sale_list, name='sale_list'),
path('<int:pk>/', sale_detail, name='sale_detail'),
path('<int:pk>/void/', void_sale, name='void_sale'),
path('<int:pk>/refund/', process_refund, name='process_refund'),
path('<int:pk>/duplicate/', views.duplicate_sale, name='duplicate_sale'),

# Printing
path('<int:pk>/print/', print_receipt, name='print_receipt'),

# EFRIS
path('<int:pk>/efris/fiscalize/', views.fiscalize_sale, name='fiscalize_sale'),
path('<int:pk>/efris/certificate/', sales.download_efris_certificate, name='download_efris_certificate'),
path('<int:pk>/efris/details/', sales.efris_details, name='efris_details'),

# API endpoints
path('api/products/search/', sales.product_search, name='product_search'),
path('api/customers/search/', sales.customer_search, name='customer_search'),
path('api/services/search/', sales.service_search, name='service_search'),
path('api/stock/check/<int:product_id>/<int:store_id>/', sales.check_stock, name='check_stock'),
path('api/calculate/totals/', sales.calculate_totals, name='calculate_totals'),
path('api/save-draft/', sales.save_draft_ajax, name='save_draft_ajax'),
path('api/record-payment/<int:sale_id>/', sales.record_payment, name='record_payment_ajax'),
path('api/efris/validate/<int:sale_id>/', sales.validate_efris, name='validate_efris'),

# Reports
path('reports/summary/', sales.summary_report, name='summary_report'),
path('reports/detailed/', sales.detailed_report, name='detailed_report'),
path('export/<str:format>/', sales.export_sales, name='export_sales'),
]


