from django.urls import path
from . import views

app_name = 'expenses'

urlpatterns = [
    # Dashboard
    path('', views.expense_dashboard, name='dashboard'),

    # Expense URLs
    path('expenses/', views.ExpenseListView.as_view(), name='expense_list'),
    path('expenses/create/', views.create_expense, name='expense_create'),
    path('expenses/<int:pk>/', views.ExpenseDetailView.as_view(), name='expense_detail'),
    path('expenses/<int:pk>/update/', views.update_expense, name='expense_update'),
    path('expenses/<int:pk>/approve/', views.approve_expense, name='expense_approve'),
    path('expenses/<int:pk>/reject/', views.reject_expense, name='expense_reject'),
    path('expenses/<int:pk>/pay/', views.mark_expense_paid, name='expense_pay'),
    path('expenses/<int:pk>/cancel/', views.cancel_expense, name='expense_cancel'),

    # Vendor URLs
    path('vendors/', views.VendorListView.as_view(), name='vendor_list'),
    path('vendors/create/', views.create_vendor, name='vendor_create'),
    path('vendors/<int:pk>/', views.VendorDetailView.as_view(), name='vendor_detail'),
    path('vendors/<int:pk>/update/', views.update_vendor, name='vendor_update'),

    # Budget URLs
    path('budgets/', views.BudgetListView.as_view(), name='budget_list'),
    path('budgets/dashboard/', views.budget_dashboard, name='budget_dashboard'),

    # Reports
    path('reports/', views.expense_reports, name='reports'),
    path('reports/export/', views.export_expenses, name='export_expenses'),

    # API Endpoints
    path('api/stats/', views.get_expense_stats_api, name='api_expense_stats'),
    path('api/check-budget/', views.check_budget_availability, name='api_check_budget'),
]