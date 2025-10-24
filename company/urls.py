from django.urls import path, include
from . import views
from branches.views import (BranchCreateView,BranchDeleteView,BranchDetailView,BranchListView,BranchUpdateView, GetBranchesAjaxView,branch_staff_overview, branch_revenue_data, export_branch_data,branch_analytics,
    generate_branch_report,branch_store_stats,branch_performance)

app_name = 'companies'

# Company URLs
company_patterns = [
    path('prime/dashboard', views.CompanyListView.as_view(), name='company_list'),
    path('create/', views.CompanyCreateView.as_view(), name='company_create'),
    path('export/', views.ExportCompaniesView.as_view(), name='company_export'),
    path('<slug:company_id>/', views.CompanyDetailView.as_view(), name='company_detail'),
    path('<slug:company_id>/update/', views.CompanyUpdateView.as_view(), name='company_update'),
    path('<slug:company_id>/delete/', views.CompanyDeleteView.as_view(), name='company_delete'),
    path('expired/', views.company_expired_view, name='company_expired'),
    path('suspended/', views.company_suspended_view, name='company_suspended'),
    path('grace-period/', views.company_suspended_view, name='company_grace_period'),
    path('deactivated/', views.company_deactivated_view, name='company_deactivated'),
    path("<slug:company_id>/action/", views.company_action, name="company_action"),

    # Admin actions
    path('admin/suspend/<str:company_id>/', views.admin_suspend_company, name='admin_suspend_company'),
    path('admin/reactivate/<str:company_id>/', views.admin_reactivate_company, name='admin_reactivate_company'),

    # Billing and subscription management
    path('billing/', views.billing_view, name='billing'),
    path('upgrade/', views.upgrade_plan_view, name='upgrade_plan'),
    path('api/company/<str:company_id>/metrics/', views.CompanyMetricsAPIView.as_view(), name='company_metrics_api'),
    path('api/company/<str:company_id>/status/', views.CompanyStatusAPIView.as_view(), name='company_status_api'),
    path('branches/<int:branch_id>/analytics/', views.BranchAnalyticsAPIView.as_view(), name='branch_analytics_api'),

]

branch_patterns = [
    path('', BranchListView.as_view(), name='branch_list'),
    path('create/', BranchCreateView.as_view(), name='branch_create'),
    path('<int:pk>/', BranchDetailView.as_view(), name='branch_detail'),
    path('<int:pk>/update/', BranchUpdateView.as_view(), name='branch_update'),
    path('<int:pk>/delete/', BranchDeleteView.as_view(), name='branch_delete'),
    path('<int:branch_id>/analytics/', branch_analytics, name='branch_analytics'),
    path('<int:branch_id>/store-stats/', branch_store_stats, name='branch_store_stats'),
    path('<int:branch_id>/performance/', branch_performance, name='branch_performance'),
    path('<int:branch_id>/staff-overview/', branch_staff_overview, name='branch_staff_overview'),
    path('<int:branch_id>/revenue-data/', branch_revenue_data, name='branch_revenue_data'),

    # Export and reporting endpoints
    path('<int:branch_id>/export/', export_branch_data, name='export_branch_data'),
    path('<int:branch_id>/generate-report/', generate_branch_report, name='generate_branch_report'),
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
    path('', views.DashboardView.as_view(), name='dashboard'),

    # Grouped sections
    path('companies/', include(company_patterns)),
    path('domains/', include(domain_patterns)),
    path('branches/', include(branch_patterns)),
    path('employees/',include(employee_patterns)),


    # Advanced search
    path('search/', views.AdvancedSearchView.as_view(), name='advanced_search'),
]
