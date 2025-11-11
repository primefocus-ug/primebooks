from django.urls import path
from . import views

app_name = 'public_router'

urlpatterns = [
    path('llogin/', views.public_login_router, name='login'),
    path('login/bridge/', views.login_bridge, name='login_bridge'),
    path('api/find-tenant/', views.api_find_tenant, name='api_find_tenant'),
]