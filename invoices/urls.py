from django.urls import path
from . import views

app_name = 'invoices'

urlpatterns = [
    # Dashboard and main views
    path('', views.invoice_dashboard, name='dashboard'),
    path('list/', views.InvoiceListView.as_view(), name='list'),
    path('analytics/', views.invoice_analytics, name='analytics'),
    path('bulk-fiscalize/', views.bulk_fiscalize_invoices, name='bulk_fiscalize'),
    path('efris-dashboard/', views.efris_status_dashboard, name='efris_dashboard'),

    # Invoice CRUD operations
    path('create/', views.InvoiceCreateView.as_view(), name='create'),
    path('<int:pk>/', views.InvoiceDetailView.as_view(), name='detail'),
    path('<int:pk>/edit/', views.InvoiceUpdateView.as_view(), name='edit'),
    path('<int:pk>/duplicate/', views.duplicate_invoice, name='duplicate'),
    path('<int:pk>/print/', views.invoice_print_view, name='print'),

    # Payment operations
    path('<int:pk>/add-payment/', views.add_payment, name='add_payment'),
    path('payments/', views.PaymentListView.as_view(), name='payments'),

    # Fiscalization
    path('<int:pk>/fiscalize/', views.fiscalize_invoice, name='fiscalize'),
    path('fiscalization-audit/', views.FiscalizationAuditView.as_view(), name='fiscalization_audit'),

    # Bulk operations
    path('bulk-actions/', views.bulk_actions, name='bulk_actions'),
    path('api/dashboard/chart-data/', views.dashboard_chart_data, name='dashboard_chart_data'),
    path('api/dashboard/metrics/', views.dashboard_metrics, name='dashboard_metrics'),
    path('api/analytics/', views.analytics_api, name='analytics_api'),

    # Export functions
    path('export/csv/', views.export_invoices_csv, name='export_csv'),
    path('export/pdf/', views.export_invoices_pdf, name='export_pdf'),

    # Templates
    path('templates/', views.InvoiceTemplateListView.as_view(), name='templates'),
    path('templates/create/', views.InvoiceTemplateCreateView.as_view(), name='template_create'),

    # AJAX endpoints
    path('ajax/status/', views.ajax_invoice_status, name='ajax_status'),
]