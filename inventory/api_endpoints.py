"""
Inventory API URL Configuration
Complete routing for all inventory endpoints
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from inventory.servicee.scanner_views import scan_session_page
from inventory.servicee.label_pdf_view import label_pdf_view
from inventory.servicee.scanner_views import (
   BarcodeScanView, StockReceiveView,
   QuickProductCreateView, ScanSessionView, BarcodeLabelView,
)
from .api_views import (
    EFRISCommodityCategoryViewSet,
    CategoryViewSet,
    ServiceViewSet,
    SupplierViewSet,
    ProductViewSet,
    StockViewSet,
    StockMovementViewSet,
    ImportSessionViewSet,
    ReportViewSet,StockTransferViewSet,
            product_availability,
            current_stock_api,
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
router.register(r'transfers', StockTransferViewSet, basename='transfer')
router.register(r'stock-movements', StockMovementViewSet, basename='stock-movement')
router.register(r'imports', ImportSessionViewSet, basename='import')
router.register(r'reports', ReportViewSet, basename='report')

app_name = 'inventory_api'

urlpatterns = [
    path('', include(router.urls)),
    path('product-availability/', product_availability, name='product-availability'),
    path('current-stock/',        current_stock_api,    name='current-stock'),
    path('inventory/scan/', scan_session_page, name='scan-session'),
    path('inventory/labels/print/', label_pdf_view, name='label-pdf'),
    # API
    path('api/scan/barcode/', BarcodeScanView.as_view(), name='api-scan-barcode'),
    path('api/scan/receive-stock/', StockReceiveView.as_view(), name='api-scan-receive-stock'),
    path('api/scan/quick-create/', QuickProductCreateView.as_view(), name='api-scan-quick-create'),
    path('api/scan/session/', ScanSessionView.as_view(), name='api-scan-session'),
    path('api/scan/session/<int:pk>/complete/',
         ScanSessionView.as_view(), name='api-scan-session-complete'),
    path('api/scan/labels/', BarcodeLabelView.as_view(), name='api-scan-labels'),
]