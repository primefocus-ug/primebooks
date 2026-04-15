from django.urls import path
from . import views
from . import legal_views
from .views import TenantSignupView, SignupSuccessView, CheckSubdomainView,download_center
from public_router.signup_payment_views import (
    SignupPaymentInitiateView,
    SignupPaymentCallbackView,
    SignupPaymentCancelledView,
)

app_name = 'public_router'

urlpatterns = [
    path('login/select-tenant/', views.select_tenant_view, name='select_tenant'),
    path('llogin/', views.public_login_router, name='login'),
    path('login/bridge/', views.login_bridge, name='login_bridge'),
    path('api/find-tenant/', views.api_find_tenant, name='api_find_tenant'),
    path('', TenantSignupView.as_view(), name='signupt'),
    path(
            'signup/pay/<uuid:request_id>/',
            SignupPaymentInitiateView.as_view(),
            name='signup_payment_initiate',
        ),
        path(
            'signup/pay/<uuid:request_id>/callback/',
            SignupPaymentCallbackView.as_view(),
            name='signup_payment_callback',
        ),
        path(
            'signup/pay/<uuid:request_id>/cancelled/',
            SignupPaymentCancelledView.as_view(),
            name='signup_payment_cancelled',
        ),
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
    path('terms-of-service/',    legal_views.terms_view,       name='terms'),
    path('privacy-policy/',      legal_views.privacy_view,     name='privacy'),
    path('terms-of-service/pdf/', legal_views.terms_pdf_view,  name='terms_pdf'),
    path('privacy-policy/pdf/',  legal_views.privacy_pdf_view, name='privacy_pdf'),
]

