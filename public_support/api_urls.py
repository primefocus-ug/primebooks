from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api_views import SupportTicketViewSet

router = DefaultRouter()
router.register(r"support-tickets", SupportTicketViewSet, basename="support-tickets")

urlpatterns = [
    path("", include(router.urls)),
]