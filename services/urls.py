from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    ServiceViewSet, ServiceCategoryViewSet, ServiceTypeViewSet,
    ServiceAppointmentViewSet, ServicePackageViewSet, ServiceExecutionViewSet
)
from django.urls import path
from . import view

app_name = 'services'

router = DefaultRouter()
router.register(r'categories', ServiceCategoryViewSet, basename='service-category')
router.register(r'types', ServiceTypeViewSet, basename='service-type')
router.register(r'services', ServiceViewSet, basename='service')
router.register(r'appointments', ServiceAppointmentViewSet, basename='appointment')
router.register(r'packages', ServicePackageViewSet, basename='package')
router.register(r'executions', ServiceExecutionViewSet, basename='execution')


urlpatterns = [
    # Dashboard
    path('', view.services_dashboard, name='dashboard'),

    # Services
    path('services/', view.service_list, name='service_list'),
    path('services/create/', view.service_create, name='service_create'),
    path('services/<int:pk>/', view.service_detail, name='service_detail'),
    path('services/<int:pk>/update/', view.service_update, name='service_update'),
    path('services/<int:pk>/delete/', view.service_delete, name='service_delete'),

    # Appointments
    path('appointments/', view.appointment_list, name='appointment_list'),
    path('appointments/calendar/', view.appointment_calendar, name='appointment_calendar'),
    path('appointments/create/', view.appointment_create, name='appointment_create'),
    path('appointments/<int:pk>/', view.appointment_detail, name='appointment_detail'),
    path('appointments/<int:pk>/update-status/', view.appointment_update_status, name='appointment_update_status'),

    # Executions
    path('executions/', view.execution_list, name='execution_list'),
    path('executions/<int:pk>/', view.execution_detail, name='execution_detail'),
    path('executions/<int:pk>/update/', view.execution_update, name='execution_update'),

    # Packages
    path('packages/', view.package_list, name='package_list'),
    path('packages/<int:pk>/', view.package_detail, name='package_detail'),

    # Reports
    path('reports/', view.reports_dashboard, name='reports_dashboard'),

    # AJAX Endpoints
    path('ajax/service/<int:pk>/price/', view.get_service_price, name='get_service_price'),
    path('ajax/service/<int:pk>/availability/', view.check_availability, name='check_availability'),
    path('', include(router.urls)),
]



