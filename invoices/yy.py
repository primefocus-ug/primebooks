from django.urls import path
from . import nash

app_name = 'invoice'

urlpatterns = [
    # Invoice CRUD
    path('', nash.invoice_list, name='invoice_lists'),
    path('create/', nash.invoice_create, name='invoice_creates'),
    path('<int:pk>/preview/', nash.invoice_preview, name='invoice_preview'),
    path('<int:pk>/print/', nash.invoice_print, name='invoice_print'),
    path('<int:pk>/download-pdf/', nash.invoice_download_pdf, name='invoice_download_pdf'),
    path('<int:pk>/', nash.invoice_detail, name='invoice_detail'),
    path('<int:pk>/edit/', nash.invoice_edit, name='invoice_edit'),
    path('<int:pk>/delete/', nash.invoice_delete, name='invoice_delete'),

    # Invoice Actions
    path('<int:pk>/mark-sent/', nash.invoice_mark_sent, name='invoice_mark_sent'),
    path('<int:pk>/mark-paid/', nash.invoice_mark_paid, name='invoice_mark_paid'),
    path('<int:pk>/cancel/', nash.invoice_cancel, name='invoice_cancel'),

    # API Endpoints
    path('api/product/<int:product_id>/', nash.get_product_details, name='get_product_details'),
    path('api/service/<int:service_id>/', nash.get_service_details, name='get_service_details'),
    path('api/search/products/', nash.search_products, name='search_products'),
    path('api/search/services/', nash.search_services, name='search_services'),
]