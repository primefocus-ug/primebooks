from django.urls import path, include
from . import company_views as views
from .views.subscription_views import get_subscription_limits, SubscriptionDashboardView,SubscriptionPlansView, SubscriptionRenewView,SubscriptionCancelView,SubscriptionUpgradeView,SubscriptionDowngradeView
from . import view
from . import create_tenantt
from .views.billing_views import BillingHistoryView,BillingSettingsView,InvoiceDetailView,DownloadInvoiceView,PaymentMethodsView,AddPaymentMethodView,RemovePaymentMethodView,ProcessPaymentView,ExportInvoicesView
from .views.analytics_views import DashboardView
from branches.views import (BranchCreateView,BranchDeleteView,BranchDetailView,BranchListView,BranchUpdateView, GetBranchesAjaxView,branch_staff_overview, branch_revenue_data, export_branch_data,branch_analytics,
    generate_branch_report,branch_store_stats,branch_performance,GetCompanyBranchesView,ExportBranchesView)

app_name = 'companies'

# Company URLs
company_patterns = [
    path('prime/dashboard', views.CompanyListView.as_view(), name='company_list'),
    path('subscription/limits/', get_subscription_limits, name='subscription_limits'),
    path('subscription/', SubscriptionDashboardView.as_view(), name='subscription_dashboard'),
    path('subscription/plans/', SubscriptionPlansView.as_view(), name='subscription_plans'),
    path('expired/', views.company_expired_view, name='company_expired'),
    path('suspended/', views.company_suspended_view, name='company_suspended'),
    path('grace-period/', views.company_suspended_view, name='company_grace_period'),
    path('deactivated/', views.company_deactivated_view, name='company_deactivated'),

    path('subscription/upgrade/<int:plan_id>/', SubscriptionUpgradeView.as_view(), name='subscription_upgrade'),
    path('subscription/upgrade/<int:plan_id>/cost/', SubscriptionUpgradeView.as_view(), name='upgrade_cost'),
    path('subscription/downgrade/<int:plan_id>/', SubscriptionDowngradeView.as_view(), name='subscription_downgrade'),
    path('subscription/downgrade/<int:plan_id>/validate/', SubscriptionDowngradeView.as_view(),
         name='downgrade_validate'),
    path('subscription/renew/', SubscriptionRenewView.as_view(), name='subscription_renew'),
    path('subscription/cancel/', SubscriptionCancelView.as_view(), name='subscription_cancel'),

    # Billing & Invoices
    path('billing/history/', BillingHistoryView.as_view(), name='billing_history'),
    path('billing/invoice/<str:invoice_id>/', InvoiceDetailView.as_view(), name='invoice_detail'),
    path('billing/invoice/<str:invoice_id>/download/', DownloadInvoiceView.as_view(), name='invoice_download'),
    path('billing/payment-methods/', PaymentMethodsView.as_view(), name='payment_methods'),
    path('billing/payment-methods/add/', AddPaymentMethodView.as_view(), name='add_payment_method'),
    path('billing/payment-methods/remove/', RemovePaymentMethodView.as_view(), name='remove_payment_method'),
    path('billing/process-payment/', ProcessPaymentView.as_view(), name='process_payment'),
    path('billing/settings/', BillingSettingsView.as_view(), name='billing_settings'),
    path('billing/export/', ExportInvoicesView.as_view(), name='export_invoices'),

    path('plans/', SubscriptionPlansView.as_view(),name='subscription_plans'),
    path('create/', views.CompanyCreateView.as_view(), name='company_create'),
    path('create-tenant/', create_tenantt.create_tenant_view, name='create_tenant'),
    path('primebooks-creator/',view.create_company,name='create_company'),
    path('export/', views.ExportCompaniesView.as_view(), name='company_export'),
    path('admin/suspend/<str:company_id>/', views.admin_suspend_company, name='admin_suspend_company'),
    path('admin/reactivate/<str:company_id>/', views.admin_reactivate_company, name='admin_reactivate_company'),

    # Billing and subscription management
    path('billing/', views.billing_view, name='billing'),
    path('upgrade/', views.upgrade_plan_view, name='upgrade_plan'),
    path('api/company/<str:company_id>/metrics/', views.CompanyMetricsAPIView.as_view(), name='company_metrics_api'),
    path('api/company/<str:company_id>/status/', views.CompanyStatusAPIView.as_view(), name='company_status_api'),
    path('branches/<int:store_id>/analytics/', views.BranchAnalyticsAPIView.as_view(), name='branch_analytics_api'),
    path('<slug:company_id>/', views.CompanyDetailView.as_view(), name='company_detail'),
    path('<slug:company_id>/update/', views.CompanyUpdateView.as_view(), name='company_update'),
    path('<slug:company_id>/delete/', views.CompanyDeleteView.as_view(), name='company_delete'),
    path("<slug:company_id>/action/", views.company_action, name="company_action"),

]

branch_patterns = [
    path('', BranchListView.as_view(), name='branch_list'),
    path('create/', BranchCreateView.as_view(), name='branch_create'),
    # AJAX endpoints
    path('ajax/get-branches/', GetBranchesAjaxView.as_view(), name='get_branches_ajax'),
    path('ajax/company-branches/', GetCompanyBranchesView.as_view(), name='get_company_branches'),
    path('export-csv/', ExportBranchesView.as_view(), name='export_branches'),
    path('<int:pk>/', BranchDetailView.as_view(), name='branch_detail'),
    path('<int:pk>/update/', BranchUpdateView.as_view(), name='branch_update'),
    path('<int:pk>/delete/', BranchDeleteView.as_view(), name='branch_delete'),

    # Analytics and Stats endpoints
    path('<int:store_id>/analytics/', branch_analytics, name='branch_analytics'),
    path('<int:store_id>/store-stats/', branch_store_stats, name='branch_store_stats'),
    path('<int:store_id>/performance/', branch_performance, name='branch_performance'),
    path('<int:store_id>/staff-overview/', branch_staff_overview, name='branch_staff_overview'),
    path('<int:store_id>/revenue-data/', branch_revenue_data, name='branch_revenue_data'),

    # Export and reporting endpoints
    path('<int:store_id>/export/', export_branch_data, name='export_branch_data'),
    path('<int:store_id>/generate-report/', generate_branch_report, name='generate_branch_report'),

]
employee_patterns = [
    path('export/', views.ExportEmployeesView.as_view(), name='employee_export'),
    path('<str:company_id>/', views.EmployeeListView.as_view(), name='employee_list'),
    path('<str:company_id>/create/', views.EmployeeCreateView.as_view(), name='employee_create'),
    path('<str:company_id>/<int:pk>/', views.EmployeeDetailView.as_view(), name='employee_detail'),
    path('<int:pk>/update/', views.EmployeeUpdateView.as_view(), name='employee_update'),
    path('<int:pk>/delete/', views.EmployeeDeleteView.as_view(), name='employee_delete'),
]

domain_patterns = [
    path('', views.DomainListView.as_view(), name='domain_list'),
    path('create/', views.DomainCreateView.as_view(), name='domain_create'),
    path('<int:pk>/update/', views.DomainUpdateView.as_view(), name='domain_update'),
    path('<int:pk>/delete/', views.DomainDeleteView.as_view(), name='domain_delete'),
]


urlpatterns = [
    # Dashboard
    path('', DashboardView.as_view(), name='dashboard'),

    # Grouped sections
    path('companies/', include(company_patterns)),
    path('domains/', include(domain_patterns)),
    path('branches/', include(branch_patterns)),
    path('employees/',include(employee_patterns)),


    # Advanced search
    path('search/', views.AdvancedSearchView.as_view(), name='advanced_search'),
]
