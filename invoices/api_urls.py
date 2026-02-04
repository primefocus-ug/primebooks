# invoices/api_urls.py
"""
API URL Configuration for Invoices Application
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import (
    InvoiceViewSet,
    InvoicePaymentViewSet,
    InvoiceTemplateViewSet
)

router = DefaultRouter()

router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'invoice-payments', InvoicePaymentViewSet, basename='invoice-payment')
router.register(r'invoice-templates', InvoiceTemplateViewSet, basename='invoice-template')

app_name = 'invoices_api'

urlpatterns = [
    path('', include(router.urls)),
]