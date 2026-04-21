from django.urls import path, include
from . import views
from rest_framework.routers import DefaultRouter
from .api_views import (
    SaleViewSet, PaymentViewSet, CartViewSet,
    ReceiptViewSet, ReportViewSet, search_hs_codes, browse_hs_codes, get_hs_code_details
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
# Cashier: submit a request
    path(
        'price-reduction-requests/',
        views.request_price_reduction,
        name='request_price_reduction',
    ),

    # Cashier: poll for status — MUST come before the <str:action> pattern
    path(
        'price-reduction-requests/<uuid:request_id>/status/',
        views.poll_price_reduction_status,
        name='poll_price_reduction_status',
    ),

    # Email link: token-authenticated approve/reject (no login required)
    path(
        'price-reduction-requests/<uuid:request_id>/token/<str:action>/',
        views.approve_reject_price_reduction_token,
        name='approve_reject_price_reduction_token',
    ),

    # Admin in-app: authenticated approve/reject
    path(
        'price-reduction-requests/<uuid:request_id>/admin/<str:action>/',
        views.approve_reject_price_reduction,
        name='approve_reject_price_reduction',
    ),
    path('', include(router.urls)),
    path('api/hs-codes/search/', search_hs_codes, name='search_hs_codes'),
    path('api/hs-codes/<str:hs_code>/', get_hs_code_details, name='hs_code_details'),
    path('api/hs-codes/browse/', browse_hs_codes, name='browse_hs_codes'),

]