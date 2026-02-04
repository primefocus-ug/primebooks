from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import (
    SaleViewSet, PaymentViewSet, CartViewSet,
    ReceiptViewSet, ReportViewSet
)

# Create router
router = DefaultRouter()

# Register viewsets
router.register(r'sales', SaleViewSet, basename='sale')
router.register(r'payments', PaymentViewSet, basename='payment')
router.register(r'carts', CartViewSet, basename='cart')
router.register(r'receipts', ReceiptViewSet, basename='receipt')
router.register(r'reports', ReportViewSet, basename='report')

app_name = 'sales_api'

urlpatterns = [
    path('', include(router.urls)),
    ]