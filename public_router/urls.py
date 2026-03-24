from django.urls import path
from . import views
from .views import TenantSignupView, SignupSuccessView, CheckSubdomainView,download_center


app_name = 'public_router'

urlpatterns = [
    path('login/select-tenant/', views.select_tenant_view, name='select_tenant'),
    path('llogin/', views.public_login_router, name='login'),
    path('login/bridge/', views.login_bridge, name='login_bridge'),
    path('api/find-tenant/', views.api_find_tenant, name='api_find_tenant'),
    path('', TenantSignupView.as_view(), name='signupt'),
    path('download-center/', download_center, name='download_center'),
    path('success/', SignupSuccessView.as_view(), name='signup_successt'),
    path('check-subdomain/', CheckSubdomainView.as_view(), name='check_subdomain'),
    path('health/', views.HealthCheckView.as_view(), name='health'),
    path('tutorials/', views.TutorialsView.as_view(), name='tutorials'),
    path('signup/', views.tenant_signup_view, name='signup'),
    path('signup/success/<uuid:request_id>/', views.signup_success_view, name='signup_success'),
    path('tenant-signups/', views.admin_tenant_signups_list, name='tenant_signups_list'),
    path('tenant-signups/<uuid:request_id>/', views.admin_tenant_signup_detail, name='tenant_signup_detail'),
    path('tenant-signups/<uuid:request_id>/approve/', views.admin_approve_signup, name='approve_signup'),
]

