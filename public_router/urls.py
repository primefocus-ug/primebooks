from django.urls import path
from . import views
from .views import TenantSignupView, SignupSuccessView, CheckSubdomainView


app_name = 'public_router'

urlpatterns = [
    path('llogin/', views.public_login_router, name='login'),
    path('login/bridge/', views.login_bridge, name='login_bridge'),
    path('api/find-tenant/', views.api_find_tenant, name='api_find_tenant'),
    path('', TenantSignupView.as_view(), name='signupt'),
    path('success/', SignupSuccessView.as_view(), name='signup_successt'),
    path('check-subdomain/', CheckSubdomainView.as_view(), name='check_subdomain'),
    path('health/', views.HealthCheckView.as_view(), name='health'),
    path('signup/', views.tenant_signup_view, name='signup'),
    path('signup/success/<uuid:request_id>/', views.signup_success_view, name='signup_success'),
]

