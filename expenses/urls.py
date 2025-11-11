from django.urls import path
from . import views, api_views

app_name = 'expenses'

urlpatterns = [
    # Main views
    path('', views.expense_dashboard, name='dashboard'),
    path('list/', views.expense_list, name='expense_list'),
    path('create/', views.expense_create, name='expense_create'),
    path('<int:pk>/', views.expense_detail, name='expense_detail'),
    path('<int:pk>/edit/', views.expense_edit, name='expense_edit'),
    path('<int:pk>/delete/', views.expense_delete, name='expense_delete'),
    path('<int:pk>/submit/', views.expense_submit, name='expense_submit'),
    path('<int:pk>/approve/', views.expense_approve, name='expense_approve'),
    path('<int:pk>/reject/', views.expense_reject, name='expense_reject'),
    path('<int:pk>/pay/', views.expense_mark_paid, name='expense_mark_paid'),
    path('<int:pk>/comment/', views.expense_add_comment, name='add_comment'),
    path('<int:pk>/attachment/<int:attachment_id>/delete/', views.expense_delete_attachment, name='delete_attachment'),
    
    # Bulk actions
    path('bulk-action/', views.expense_bulk_action, name='bulk_action'),
    
    # Reports and exports
    path('reports/', views.expense_reports, name='reports'),
    path('export/', views.expense_export, name='export'),

    path('categories/', views.ExpenseCategoryListView.as_view(), name='category_list'),
    path('categories/create/', views.ExpenseCategoryCreateView.as_view(), name='category_create'),
    path('categories/<int:pk>/edit/', views.ExpenseCategoryUpdateView.as_view(), name='category_edit'),
    path('categories/<int:pk>/delete/', views.ExpenseCategoryDeleteView.as_view(), name='category_delete'),
    path('categories/<int:pk>/toggle-active/', views.category_toggle_active, name='category_toggle_active'),
    path('categories/<int:pk>/expenses/', views.category_expenses, name='category_expenses'),
    path('categories/budget-report/', views.category_budget_report, name='category_budget_report'),

    # Category API endpoints
    path('api/categories/', views.category_list_api, name='api_category_list'),
    path('api/categories/<int:pk>/budget-utilization/', views.category_budget_utilization_api, name='api_category_budget_utilization'),
    
        
    # New API endpoints
    path('api/quick-stats/', views.expense_quick_stats, name='api_quick_stats'),
    path('api/category-summary/', views.expense_category_summary, name='api_category_summary'),
]