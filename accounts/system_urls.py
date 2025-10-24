from django.urls import path
from . import views

urlpatterns = [
    path('', views.system_dashboard, name='system_dashboard'),
    path('login/', views.system_admin_login, name='system_admin_login'),
    path('companies/', views.manage_companies, name='manage_companies'),
    path('companies/<int:company_id>/', views.company_detail, name='company_detail'),
]