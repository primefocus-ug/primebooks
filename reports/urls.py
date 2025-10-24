from django.urls import path, include, re_path
from . import views
from channels.routing import URLRouter
from . import consumers  # Assuming you have a consumers.py file

app_name = 'reports'

urlpatterns = [
    # Main dashboard
    path('', views.report_dashboard, name='dashboard'),

    # Core Reports
    path('sales/', views.sales_summary_report, name='sales_summary'),
    path('products/', views.product_performance_report, name='product_performance'),
    path('inventory/', views.inventory_status_report, name='inventory_status'),
    path('tax/', views.tax_report, name='tax_report'),
    path('analytics/', views.analytics_dashboard, name='analytics'),
    path('z-report/', views.z_report, name='z_report'),
    path('efris-compliance/', views.efris_compliance_report, name='efris_compliance'),
    path('price-lookup/', views.price_lookup_report, name='price_lookup'),
    path('cashier-performance/', views.cashier_performance_report, name='cashier_performance'),

    # Report Generation
    path('generate/<int:report_id>/', views.generate_report, name='generate_report'),

    # Export functionality
    path('export/<str:report_type>/', views.export_report, name='export_report'),

    # Saved reports management
    path('saved/', views.saved_reports_list, name='saved_reports'),
    path('saved/create/', views.create_saved_report, name='create_saved_report'),
    path('saved/<int:report_id>/', views.view_saved_report, name='view_saved_report'),
    path('saved/<int:report_id>/edit/', views.edit_saved_report, name='edit_saved_report'),
    path('saved/<int:report_id>/delete/', views.delete_saved_report, name='delete_saved_report'),
    path('saved/<int:report_id>/run/', views.run_saved_report, name='run_saved_report'),
    path('saved/<int:report_id>/toggle-favorite/', views.toggle_favorite_report, name='toggle_favorite_report'),

    # Report scheduling
    path('schedules/', views.report_schedules_list, name='schedules'),
    path('schedules/create/', views.create_schedule, name='create_schedule'),
    path('schedules/<int:schedule_id>/edit/', views.edit_schedule, name='edit_schedule'),
    path('schedules/<int:schedule_id>/delete/', views.delete_schedule, name='delete_schedule'),
    path('schedules/<int:schedule_id>/toggle/', views.toggle_schedule, name='toggle_schedule'),

    # Generated reports history
    path('history/', views.generated_reports_history, name='history'),
    path('history/<int:report_id>/download/', views.download_generated_report, name='download_report'),
    path('history/<int:report_id>/delete/', views.delete_generated_report, name='delete_generated_report'),

    # AJAX endpoints
    path('api/save/', views.save_report, name='api_save_report'),
    path('api/chart-data/', views.get_chart_data, name='api_chart_data'),
    path('api/quick-stats/', views.get_quick_stats, name='api_quick_stats'),
    path('api/filters/', views.get_filter_options, name='api_filter_options'),
    path('api/dashboard-stats/', views.get_dashboard_stats_ajax, name='api_dashboard_stats'),
    path('api/report-progress/<int:report_id>/', views.get_report_progress_ajax, name='api_report_progress'),
    path('api/cancel-report/<int:report_id>/', views.cancel_report_generation_ajax, name='api_cancel_report'),
    path('api/stock-alerts/', views.get_stock_alerts_ajax, name='ajax_alerts'),

    # Print views
    path('print/sales/<int:report_id>/', views.print_sales_report, name='print_sales'),
    path('print/inventory/', views.print_inventory_report, name='print_inventory'),
    path('print/tax/', views.print_tax_report, name='print_tax'),
]

# WebSocket routes
websocket_urlpatterns = [
    path('ws/reports/dashboard/', consumers.ReportDashboardConsumer.as_asgi(), name='ws_dashboard'),
    re_path(r'ws/reports/generation/(?P<report_id>\d+)/$', consumers.ReportGenerationConsumer.as_asgi(), name='ws_report_generation'),
]

# Combine HTTP and WebSocket routes
urlpatterns += [
    path('', URLRouter(websocket_urlpatterns)),
]