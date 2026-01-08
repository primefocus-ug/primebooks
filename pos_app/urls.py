from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .auth import (
    LoginView, LogoutView, RefreshTokenView,
    HealthCheckView, CurrentUserView, ValidateSessionView
)
from .inventory import (
    ProductViewSet, ServiceViewSet, CategoryViewSet,
    StockViewSet, StockMovementViewSet
)
from .sales import SaleViewSet, CustomerViewSet
from . import views

app_name = 'pos_app'

# API Router for ViewSets
router = DefaultRouter()
router.register(r'products', ProductViewSet, basename='product')
router.register(r'services', ServiceViewSet, basename='service')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'stock', StockViewSet, basename='stock')
router.register(r'stock-movements', StockMovementViewSet, basename='stock-movement')
router.register(r'sales', SaleViewSet, basename='sale')
router.register(r'customers', CustomerViewSet, basename='customer')

urlpatterns = [
    # Main POS Interface
    path('', views.pos_index, name='pos_index'),

    # Authentication Endpoints
    path('api/auth/login/', LoginView.as_view(), name='api_login'),
    path('api/auth/logout/', LogoutView.as_view(), name='api_logout'),
    path('api/auth/refresh/', RefreshTokenView.as_view(), name='api_refresh'),
    path('api/auth/me/', CurrentUserView.as_view(), name='api_current_user'),
    path('api/auth/validate/', ValidateSessionView.as_view(), name='api_validate_session'),

    # Health Check (for offline detection)
    path('api/health/', HealthCheckView.as_view(), name='api_health'),

    # Inventory API
    path('api/inventory/', include((router.urls, 'inventory'))),

    # Sales API
    path('api/sales/', include((router.urls, 'sales'))),

    # Customers API
    path('api/customers/', include((router.urls, 'customers'))),
]