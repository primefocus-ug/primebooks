from django.contrib import admin
from django.urls import path, include
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from django.conf import settings
from django.conf.urls.static import static
from django.conf.urls.i18n import i18n_patterns
from errors import  views
from accounts import views as view

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/token/', TokenObtainPairView.as_view(), name='token_obtain_pair'),
    path('api/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('api/company/',include('company.api_urls')),
    path('notifications/', include('notifications.urls')),
    path('i18n/', include('django.conf.urls.i18n')),
    path('api/messaging/', include('messaging.api_urls')),
]
error_patterns = [
    path('403/', views.error_403_view, name='error_403'),
    path('404/', views.error_404_view, name='error_404'),
    path('500/', views.error_500_view, name='error_500'),
    path('502/', views.error_502_view, name='error_502'),
    path('503/', views.error_503_view, name='error_503'),
    path('error/<str:error_code>/', views.generic_error_view, name='generic_error'),
]

# Testing URLs (only in DEBUG mode)
if settings.DEBUG:
    error_patterns += [
        path('test-errors/', views.test_error_view, name='test_errors'),
        path('test-errors/<str:error_code>/', views.test_error_view, name='test_specific_error'),
    ]

urlpatterns += i18n_patterns(
    path('prime-book/', include('company.urls')),
    path('legal/',include('company.legal')),
    path('invoices/', include('invoices.urls')),
    path('accounts/', include('accounts.urls')),
    path('accounts/', include('allauth.urls')),
    path('accounts/social/', include('allauth.socialaccount.urls')),
    path('inventory/', include('inventory.urls')),
    path('sales/', include('sales.urls')),
    path('stores/', include('stores.urls')),
    path('alerts/',include('notifications.urls')),
    path('customers/', include('customers.urls')),
    path('reports/', include('reports.urls')),
    path('messaging/', include('messaging.urls')),
    path('expenses/', include('expenses.urls')),
    path('efris-man/',include('efris.ford')),
    path('efris/',include('efris.urls')),
    path('errors/', include((error_patterns, 'errors'), namespace='errors')),
    path('', view.user_dashboard, name='user_dashboard'),
)

urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = 'errors.views.error_403_view'
handler404 = 'errors.views.error_404_view'
handler500 = 'errors.views.error_500_view'