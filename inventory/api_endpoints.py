"""
Inventory API URL Configuration
Complete routing for all inventory endpoints
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import (
    EFRISCommodityCategoryViewSet,
    CategoryViewSet,
    ServiceViewSet,
    SupplierViewSet,
    ProductViewSet,
    StockViewSet,
    StockMovementViewSet,
    ImportSessionViewSet,
    ReportViewSet
)

# Create router
router = DefaultRouter()

# Register viewsets
router.register(r'efris-categories', EFRISCommodityCategoryViewSet, basename='efris-category')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'services', ServiceViewSet, basename='service')
router.register(r'suppliers', SupplierViewSet, basename='supplier')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'stock', StockViewSet, basename='stock')
router.register(r'stock-movements', StockMovementViewSet, basename='stock-movement')
router.register(r'imports', ImportSessionViewSet, basename='import')
router.register(r'reports', ReportViewSet, basename='report')

app_name = 'inventory_api'

urlpatterns = [
    path('', include(router.urls)),
]