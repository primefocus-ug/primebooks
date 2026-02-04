from django.urls import path
from . import ura
from . import stock
from . import goods
from . import version
from . import views_advanced
from inventory import view
from . import efris_export_views



app_name = 'efris'

urlpatterns = [
    # Dashboard & Configuration
    path('', ura.efris_dashboard, name='dashboard'),
    path('configuration/', ura.efris_configuration, name='configuration'),
    path('stock/dashboard/', view.EnhancedStockDashboardView.as_view(), name='stock_management_dashboard'),
    path('stock/dashboard/data/', view.stock_dashboard_data_api, name='stock_dashboard_data'),

    # Product Management
    path('products/', ura.product_list, name='product_list'),
    path('products/<int:product_id>/upload/', ura.product_upload, name='product_upload'),
    path('products/bulk-upload/', ura.product_bulk_upload, name='product_bulk_upload'),

    # Invoice Fiscalization
    path('invoices/', ura.invoice_list, name='invoice_list'),
    path('invoices/<int:invoice_id>/fiscalize/', ura.invoice_fiscalize, name='invoice_fiscalize'),
    path('invoices/<int:invoice_id>/', ura.invoice_detail, name='invoice_detail'),

    # Stock Management
    path('stock/', ura.stock_management, name='stock_management'),
    path('stock/<int:product_id>/sync/', ura.stock_sync, name='stock_sync'),

    # Commodity Categories
    path('categories/', ura.commodity_categories, name='commodity_categories'),
    path('categories/sync/', ura.sync_categories, name='sync_categories'),

    # Taxpayer Query
    path('taxpayer-query/', ura.taxpayer_query, name='taxpayer_query'),

    # Goods Inquiry
    path('goods-inquiry/', ura.goods_inquiry, name='goods_inquiry'),

    # Monitoring & Logs
    path('logs/', ura.api_logs, name='api_logs'),
    path('health/', ura.system_health, name='system_health'),

    # AJAX Endpoints
    path('ajax/test-connection/', ura.ajax_test_connection, name='ajax_test_connection'),
    path('ajax/product/<int:product_id>/status/', ura.ajax_product_status, name='ajax_product_status'),
    path('ajax/invoice/<int:invoice_id>/status/', ura.ajax_invoice_status, name='ajax_invoice_status'),
    path('ajax/dashboard-stats/', ura.ajax_dashboard_stats, name='ajax_dashboard_stats'),

    # Diagnostic Tools
    path('diagnostic/', ura.diagnostic_tool, name='diagnostic_tool'),
    path('upload-products/', ura.upload_products_to_efris, name='upload_products'),
    path('zreports/', goods.zreport_list, name='zreport_list'),
    path('zreports/<str:report_date_str>/generate/', goods.zreport_generate, name='zreport_generate'),
    path('zreports/upload/', goods.zreport_upload, name='zreport_upload'),
    path('ajax/test-connection/', goods.ajax_test_connection, name='ajax_test_connection'),
    path('ajax/product/<int:product_id>/status/', goods.ajax_product_status, name='ajax_product_status'),
    path('ajax/invoice/<int:invoice_id>/status/', goods.ajax_invoice_status, name='ajax_invoice_status'),
    path('ajax/dashboard-stats/', goods.ajax_dashboard_stats, name='ajax_dashboard_stats'),
    path('ajax/goods-search/', goods.ajax_goods_search, name='ajax_goods_search'),
    path('ajax/invoice/<int:invoice_id>/verify/', goods.ajax_invoice_verify, name='ajax_invoice_verify'),
    path('goods/inquiry/', goods.goods_inquiry, name='goods_inquiry'),
    path('goods/detail/<str:goods_id>/', goods.goods_detail, name='goods_detail'),
    path('goods/import/', goods.goods_import_to_product, name='goods_import'),
    path('goods/batch/', goods.goods_batch_query, name='goods_batch_query'),
    path('goods/sync/', goods.goods_sync_from_efris, name='goods_sync'),
    path('export-invoices/',
         efris_export_views.export_invoices_list_view,
         name='export_invoices_list'),
    path('products/<int:product_id>/configure-export/',
       efris_export_views.configure_product_for_export_view,
       name='configure_product_export'),

    path('api/export/sale-items/',
       efris_export_views.get_sale_items_export_api,
       name='get_sale_items_export_api'),

    path('export-invoices/create/',
         efris_export_views.create_export_invoice_view,
         name='create_export_invoice'),

    path('export-invoices/<str:invoice_no>/',
         efris_export_views.export_invoice_detail_view,
         name='export_invoice_detail'),

    path('export-invoices/<str:invoice_no>/submit-sad/',
         efris_export_views.submit_export_sad_view,
         name='submit_export_sad'),

    # Export API Endpoints
    path('api/export/check-clearance/',
         efris_export_views.check_export_clearance_api,
         name='check_export_clearance_api'),

    path('api/export/bulk-check-status/',
         efris_export_views.bulk_check_export_status,
         name='bulk_check_export_status'),

    path('api/export/exchange-rate/',
         efris_export_views.get_exchange_rate_for_export_api,
         name='get_exchange_rate_for_export_api'),
]




urlpatterns += [
    # Stock Management Dashboard
    path('stock/dashboard/', stock.stock_management_dashboard, name='stock_management_dashboar'),

    # Stock Query
    path('stock/query/<int:product_id>/', stock.stock_query_by_product, name='stock_query'),

    # Stock Increase (T131 - Op 101)
    path('stock/increase/<int:product_id>/', stock.stock_increase, name='stock_increase'),

    # Stock Decrease (T131 - Op 102)
    path('stock/decrease/<int:product_id>/', stock.stock_decrease, name='stock_decrease'),

    # Stock Transfer (T139)
    path('stock/transfer/', stock.stock_transfer, name='stock_transfer'),

    # Bulk Stock Sync
    path('stock/bulk-sync/', stock.bulk_stock_sync, name='bulk_stock_sync'),

    # Stock Records Query (T145/T147)
    path('stock/records/', stock.stock_records_query, name='stock_records_query'),

    # Stock Record Detail (T148)
    path('stock/record/<str:record_id>/', stock.stock_record_detail, name='stock_record_detail'),

    path('system-dictionary/', ura.system_dictionary, name='system_dictionary'),

    # View Category Details
    path('system-dictionary/<str:category>/', ura.system_dictionary_category, name='system_dictionary_category'),

    # Update Dictionary (AJAX)
    path('system-dictionary/update/', ura.system_dictionary_update, name='system_dictionary_update'),

    # Export Dictionary
    path('system-dictionary/export/', ura.system_dictionary_export, name='system_dictionary_export'),

    path('d/dashboard/', version.efris_dashboard_view, name='dashboard'),
    path('reports/', version.efris_reports_view, name='reports'),

    # Invoice Search and Query (T106, T107, T108)
    path('invoices/search/', version.invoice_search_view, name='invoice_search'),
    path('invoices/<str:invoice_no>/', version.invoice_detail_view, name='invoice_detail'),
    path('invoices/normal/list/', version.normal_invoices_view, name='normal_invoices'),

    # Credit/Debit Note Applications (T111, T112, T113, T114, T118, T120)
    path('credit-notes/applications/', version.credit_note_applications_view, name='credit_note_applications'),
    path('credit-notes/applications/<str:application_id>/', version.credit_note_application_detail_view,
         name='credit_note_application_detail'),
    path('credit-notes/approve/<str:application_id>/', version.approve_credit_note_application,
         name='approve_credit_note'),
    path('credit-notes/cancel/', version.cancel_credit_debit_note, name='cancel_credit_debit_note'),
    path('credit-notes/void/', version.void_credit_note_application, name='void_credit_note_application'),
    path('credit-note/apply/', views_advanced.credit_note_application,
         name='credit_note_application'),
    path('credit-note/status/<str:reference_no>/', views_advanced.credit_note_application_status,
         name='credit_note_application_status'),

    # AJAX API
    path('api/get-invoice-for-credit-note/', views_advanced.api_get_invoice_for_credit_note,
         name='api_get_invoice_for_credit_note'),

    # Exchange Rates (T121, T126)
    path('exchange-rates/', version.exchange_rates_view, name='exchange_rates'),

    # Excise Duty (T125)
    path('excise-duty/', version.excise_duty_list_view, name='excise_duty_list'),

    # Batch Upload (T129)
    path('batch/upload/', version.batch_invoice_upload_view, name='batch_invoice_upload'),
    path('batch/results/', version.batch_upload_results_view, name='batch_upload_results'),

    # API Endpoints
    path('api/exchange-rate/', version.get_exchange_rate_api, name='api_exchange_rate'),
    path('api/cancel-credit-note-detail/', version.query_cancel_credit_note_detail_api,
         name='api_cancel_credit_note_detail'),
    path('api/check-invoice-eligibility/', version.check_invoice_eligibility_api, name='api_check_invoice_eligibility'),
    path('api/search-invoices/', version.search_invoices_api, name='api_search_invoices'),

    # Export Functions
    path('export/invoices/csv/', version.export_invoices_csv, name='export_invoices_csv'),
    path('export/credit-notes/pdf/', version.export_credit_notes_pdf, name='export_credit_notes_pdf'),
    path('system/exception-logs/', version.exception_logs_view, name='exception_logs'),
    path('system/exception-logs/upload/', version.upload_exception_logs, name='upload_exception_logs'),
    path('system/upgrade/', version.system_upgrade_view, name='system_upgrade'),
    path('system/upgrade/download/', version.download_upgrade_files, name='download_upgrade_files'),
    path('system/category-updates/', version.commodity_category_updates_view, name='commodity_category_updates'),
    path('system/certificate-upload/', version.certificate_upload_view, name='certificate_upload'),
    path('system/branches/', version.branches_list_view, name='branches_list'),

    # Taxpayer Management
    path('taxpayer/exemption-check/', version.taxpayer_exemption_check_view, name='taxpayer_exemption_check'),

    # API Endpoints
    path('api/taxpayer/status/', version.check_taxpayer_status_api, name='api_taxpayer_status'),
    path('api/branches/', version.get_branches_api, name='api_branches'),

    # Advanced EFRIS Features
    path('advanced/commodity-category-date/', views_advanced.commodity_category_by_date,
         name='commodity_category_by_date'),
    path('advanced/fuel-types/', views_advanced.fuel_types_list,
         name='fuel_types_list'),
    path('advanced/shift-information/', views_advanced.upload_shift_information,
         name='upload_shift_information'),
    path('advanced/buyer-details-update/', views_advanced.update_buyer_details,
         name='update_buyer_details'),
    path('advanced/edc-invoice-inquiry/', views_advanced.edc_invoice_inquiry,
         name='edc_invoice_inquiry'),
    path('advanced/fuel-equipment/', views_advanced.fuel_equipment_query,
         name='fuel_equipment_query'),
    path('advanced/efd-location/', views_advanced.efd_location_query,
         name='efd_location_query'),
    path('advanced/frequent-contacts/', views_advanced.frequent_contacts_management,
         name='frequent_contacts_management'),
    path('advanced/hs-codes/', views_advanced.hs_code_list,
         name='hs_code_list'),
    path('advanced/invoice-remain/<str:invoice_no>/', views_advanced.invoice_remain_details,
         name='invoice_remain_details'),
    path("hs-codes/sync/", views_advanced.sync_hs_codes, name="sync_hs_codes"),

    path('advanced/invoice-remain/', views_advanced.invoice_remain_details,
         name='invoice_remain_details_search'),
    path('advanced/fdn-status/', views_advanced.fdn_status_query,
         name='fdn_status_query'),
    path('advanced/agent-relations/', views_advanced.agent_relations,
         name='agent_relations'),
    path('advanced/principal-agent-info/', views_advanced.principal_agent_info,
         name='principal_agent_info'),
    path('advanced/ussd-account/', views_advanced.ussd_account_creation,
         name='ussd_account_creation'),
    path('advanced/efd-transfer/', views_advanced.efd_transfer,
         name='efd_transfer'),
    path('advanced/negative-stock-config/', views_advanced.negative_stock_configuration,
         name='negative_stock_configuration'),

    # AJAX API Endpoints
    path('api/nozzle-status/', views_advanced.api_upload_nozzle_status,
         name='api_upload_nozzle_status'),
    path('api/device-issuing-status/', views_advanced.api_upload_device_issuing_status,
         name='api_upload_device_issuing_status'),
    path('api/fuel-pump-version/', views_advanced.api_query_fuel_pump_version,
         name='api_query_fuel_pump_version'),
    path('api/edc-uom-rates/', views_advanced.api_query_edc_uom_rates,
         name='api_query_edc_uom_rates'),
    path('api/edc-device-version/', views_advanced.api_query_edc_device_version,
         name='api_query_edc_device_version'),
]


