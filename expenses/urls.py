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
    path('<int:pk>/submit/', views.expense_submit, name='expense_submit'),
    path('<int:pk>/approve/', views.expense_approve, name='expense_approve'),
    path('<int:pk>/reject/', views.expense_reject, name='expense_reject'),
    path('<int:pk>/pay/', views.expense_mark_paid, name='expense_mark_paid'),
    path('<int:pk>/comment/', views.expense_add_comment, name='add_comment'),
    path('<int:pk>/attachment/<int:attachment_id>/delete/', views.expense_delete_attachment, name='delete_attachment'),

    # Reports and exports
    path('reports/', views.expense_reports, name='reports'),
    path('export/', views.expense_export, name='export'),

    # API endpoints
    path('api/stats/', api_views.expense_stats_api, name='api_stats'),
    path('api/category-stats/', api_views.expense_category_stats_api, name='api_category_stats'),
    path('api/chart-data/', api_views.expense_chart_data_api, name='api_chart_data'),
    path('api/search/', api_views.expense_search_api, name='api_search'),
    path('api/budget-utilization/', api_views.budget_utilization_api, name='api_budget_utilization'),
    path('api/<int:pk>/quick-approve/', api_views.quick_approve_api, name='api_quick_approve'),
    path('api/bulk-action/', api_views.bulk_action_api, name='api_bulk_action'),
    path('api/check-number/', api_views.check_expense_number_api, name='api_check_number'),
]