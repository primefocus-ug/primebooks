from django.urls import path
from . import views, api_views

app_name = 'expenses'

urlpatterns = [

    # ------------------------------------------------------------------
    # Dashboard & analytics
    # ------------------------------------------------------------------
    path('', views.dashboard, name='dashboard'),
    path('analytics/', views.analytics, name='analytics'),
    path('reports/', views.reports_dashboard, name='reports_dashboard'),

    # ------------------------------------------------------------------
    # Expense CRUD
    # ------------------------------------------------------------------
    path('list/', views.expense_list, name='expense_list'),
    path('create/', views.expense_create, name='expense_create'),
    path('<int:pk>/', views.expense_detail, name='expense_detail'),
    path('<int:pk>/edit/', views.expense_edit, name='expense_edit'),
    path('<int:pk>/delete/', views.expense_delete, name='expense_delete'),

    # ------------------------------------------------------------------
    # Bulk actions
    # ------------------------------------------------------------------
    path('bulk/', views.expense_bulk_action, name='expense_bulk_action'),

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------
    path('export/csv/', views.export_expenses_csv, name='export_expenses_csv'),
    path('export/pdf/', views.export_expenses_pdf, name='export_expenses_pdf'),

    # ------------------------------------------------------------------
    # Approval workflow
    # ------------------------------------------------------------------
    path('<int:pk>/submit/', views.expense_submit, name='expense_submit'),
    path('<int:pk>/approve/', views.expense_approve, name='expense_approve'),
    path('<int:pk>/reject/', views.expense_reject, name='expense_reject'),
    path('approvals/', views.approval_dashboard, name='approval_dashboard'),

    # ------------------------------------------------------------------
    # Budgets
    # ------------------------------------------------------------------
    path('budgets/', views.budget_list, name='budget_list'),
    path('budgets/create/', views.budget_create, name='budget_create'),
    path('budgets/<int:pk>/edit/', views.budget_edit, name='budget_edit'),
    path('budgets/<int:pk>/delete/', views.budget_delete, name='budget_delete'),

    # ------------------------------------------------------------------
    # Internal AJAX helpers (views.py)
    # ------------------------------------------------------------------
    path('api/tags/', views.api_tag_suggestions, name='api_tag_suggestions'),
    path('api/quick-stats/', views.api_quick_stats, name='api_quick_stats'),
    path('api/budget-status/', views.api_budget_status, name='api_budget_status'),

    # ------------------------------------------------------------------
    # API endpoints (api_views.py)
    # ------------------------------------------------------------------
    path('api/stats/', api_views.expense_stats_api, name='api_expense_stats'),
    path('api/chart-data/', api_views.expense_chart_data_api, name='api_chart_data'),
    path('api/search/', api_views.expense_search_api, name='api_expense_search'),
    path('api/budgets/', api_views.budget_status_api, name='api_budget_status_v2'),
    path('api/approval-queue/', api_views.approval_queue_api, name='api_approval_queue'),
    path('api/bulk/', api_views.bulk_action_api, name='api_bulk_action'),
    path('api/<int:pk>/approve/', api_views.quick_approve_api, name='api_quick_approve'),
    path('api/<int:pk>/reject/', api_views.quick_reject_api, name='api_quick_reject'),
]