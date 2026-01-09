from django.urls import path
from . import views

app_name = 'expenses'

urlpatterns = [
    # Dashboard
    path('', views.dashboard, name='dashboard'),

    # Expenses
    path('list/', views.expense_list, name='expense_list'),
    path('create/', views.expense_create, name='expense_create'),
    path('<int:pk>/edit/', views.expense_edit, name='expense_edit'),
    path('<int:pk>/delete/', views.expense_delete, name='expense_delete'),

    # Analytics
    path('analytics/', views.analytics, name='analytics'),

    # Budgets
    path('budgets/', views.budget_list, name='budget_list'),
    path('budgets/create/', views.budget_create, name='budget_create'),
    path('budgets/<int:pk>/edit/', views.budget_edit, name='budget_edit'),
    path('budgets/<int:pk>/delete/', views.budget_delete, name='budget_delete'),

    # API Endpoints
    path('api/tags/', views.api_tag_suggestions, name='api_tag_suggestions'),
    path('api/quick-stats/', views.api_quick_stats, name='api_quick_stats'),
    path('api/budget-status/', views.api_budget_status, name='api_budget_status'),
]