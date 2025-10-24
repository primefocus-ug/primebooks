from django.urls import path, include
from django.views.generic import RedirectView
from . import view

app_name = 'efriss'

urlpatterns = [
    # Main dashboard and redirect
    path('', RedirectView.as_view(pattern_name='efris:dashboard', permanent=False), name='index'),
    path('dashboard/', view.EFRISDashboardView.as_view(), name='dashboard'),

    # Configuration and Setup
    path('configuration/', view.EFRISConfigurationView.as_view(), name='configuration'),
    path('setup-wizard/', view.EFRISSetupWizardView.as_view(), name='setup_wizard'),
    path('complete-setup/', view.EFRISCompleteSetupView.as_view(), name='complete_setup'),

    # Connection and Authentication
    path('test-connection/', view.EFRISTestConnectionView.as_view(), name='test_connection'),
    path('authenticate/', view.EFRISAuthenticationView.as_view(), name='authenticate'),

    # Invoice Operations
    path('invoices/', view.EFRISInvoiceOperationsView.as_view(), name='invoice_operations'),
    path('fiscalize-invoice/', view.EFRISFiscalizeInvoiceView.as_view(), name='fiscalize_invoice'),
    path('bulk-fiscalize/', view.EFRISBulkFiscalizeView.as_view(), name='bulk_fiscalize'),
    path('credit-note/', view.EFRISCreditNoteView.as_view(), name='credit_note'),
    path('query-invoices/', view.EFRISInvoiceQueryView.as_view(), name='query_invoices'),
    path('download-qr/<int:invoice_id>/', view.efris_download_qr_code, name='download_qr_code'),

    # Product Operations
    path('products/', view.EFRISProductOperationsView.as_view(), name='product_operations'),
    path('upload-products/', view.EFRISUploadProductsView.as_view(), name='upload_products'),
    path('goods-inquiry/', view.EFRISGoodsInquiryView.as_view(), name='goods_inquiry'),

    # Customer Operations
    path('customers/', view.EFRISCustomerOperationsView.as_view(), name='customer_operations'),
    path('query-taxpayer/', view.EFRISQueryTaxpayerView.as_view(), name='query_taxpayer'),

    # System Operations
    path('system-dictionary/', view.EFRISSystemDictionaryView.as_view(), name='system_dictionary'),
    path('system-dictionaries/', view.EFRISSystemDictionariesView.as_view(), name='system_dictionaries'),

    # Monitoring and Logs
    path('logs/', view.EFRISLogsView.as_view(), name='logs'),
    path('audit-trail/', view.EFRISAuditTrailView.as_view(), name='audit_trail'),
    path('metrics/', view.EFRISMetricsView.as_view(), name='metrics'),
    path('health-check/', view.EFRISHealthCheckView.as_view(), name='health_check'),
    path('export-logs/', view.EFRISExportLogsView.as_view(), name='export_logs'),

    # Utility endpoints
    path('api/test/', view.efris_api_test, name='api_test'),
    path('api/clear-cache/', view.efris_clear_cache, name='clear_cache'),

    # Debug (development only)
    path('debug/', view.EFRISDebugView.as_view(), name='debug'),
]

# Add API endpoints for different EFRIS interfaces
api_patterns = [
    # Authentication endpoints
    path('api/auth/server-time/', view.EFRISAuthenticationView.as_view(), {'action': 'get_server_time'},
         name='api_server_time'),
    path('api/auth/client-init/', view.EFRISAuthenticationView.as_view(), {'action': 'client_init'},
         name='api_client_init'),
    path('api/auth/login/', view.EFRISAuthenticationView.as_view(), {'action': 'login'}, name='api_login'),
    path('api/auth/symmetric-key/', view.EFRISAuthenticationView.as_view(), {'action': 'get_symmetric_key'},
         name='api_symmetric_key'),

    # Invoice endpoints
    path('api/invoices/fiscalize/', view.EFRISFiscalizeInvoiceView.as_view(), name='api_fiscalize_invoice'),
    path('api/invoices/bulk-fiscalize/', view.EFRISBulkFiscalizeView.as_view(), name='api_bulk_fiscalize'),
    path('api/invoices/query/', view.EFRISInvoiceQueryView.as_view(), name='api_query_invoices'),
    path('api/invoices/credit-note/', view.EFRISCreditNoteView.as_view(), name='api_credit_note'),

    # Product endpoints
    path('api/products/upload/', view.EFRISUploadProductsView.as_view(), name='api_upload_products'),
    path('api/products/inquiry/', view.EFRISGoodsInquiryView.as_view(), name='api_goods_inquiry'),

    # Customer endpoints
    path('api/customers/query-taxpayer/', view.EFRISQueryTaxpayerView.as_view(), name='api_query_taxpayer'),

    # System endpoints
    path('api/system/dictionary/', view.EFRISSystemDictionaryView.as_view(), name='api_system_dictionary'),
    path('api/system/health/', view.EFRISHealthCheckView.as_view(), name='api_health_check'),
]

urlpatterns += api_patterns