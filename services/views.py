from rest_framework import viewsets, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django_filters.rest_framework import DjangoFilterBackend
from django.utils import timezone
from django.db.models import Avg, Count, Q
from .models import (
    Service, ServiceCategory, ServiceType, ServiceAppointment,
    ServicePackage, ServiceExecution, ServiceDiscount
)
from .serializers import (
    ServiceSerializer, ServiceCategorySerializer, ServiceTypeSerializer,
    ServiceAppointmentSerializer, ServicePackageSerializer, ServiceExecutionSerializer
)


class ServiceCategoryViewSet(viewsets.ModelViewSet):
    queryset = ServiceCategory.objects.filter(is_active=True)
    serializer_class = ServiceCategorySerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']


class ServiceTypeViewSet(viewsets.ModelViewSet):
    queryset = ServiceType.objects.filter(is_active=True)
    serializer_class = ServiceTypeSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']


class ServiceViewSet(viewsets.ModelViewSet):
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'service_type', 'requires_appointment', 'is_recurring']
    search_fields = ['name', 'code', 'description', 'tags']
    ordering_fields = ['name', 'base_price', 'sort_order', 'created_at']

    @action(detail=True, methods=['get'])
    def pricing(self, request, pk=None):
        """Get pricing details for a service"""
        service = self.get_object()
        duration = request.query_params.get('duration_minutes')
        tier = request.query_params.get('tier_level')

        price = service.calculate_price(
            duration_minutes=int(duration) if duration else None,
            tier_level=int(tier) if tier else None
        )

        tax = service.calculate_tax(price)

        return Response({
            'service': service.name,
            'base_price': service.base_price,
            'calculated_price': price,
            'tax_amount': tax,
            'total': price + tax if not service.is_tax_inclusive else price,
            'pricing_type': service.service_type.pricing_type
        })

    @action(detail=True, methods=['get'])
    def availability(self, request, pk=None):
        """Check service availability"""
        service = self.get_object()
        date = request.query_params.get('date')

        if not date or not service.requires_appointment:
            return Response({'available': True})

        # Get appointments for the date
        appointments = ServiceAppointment.objects.filter(
            service=service,
            scheduled_date=date,
            status__in=['scheduled', 'confirmed', 'in_progress']
        )

        return Response({
            'service': service.name,
            'date': date,
            'booked_slots': appointments.count(),
            'appointments': ServiceAppointmentSerializer(appointments, many=True).data
        })

    @action(detail=False, methods=['get'])
    def featured(self, request):
        """Get featured services"""
        featured = Service.objects.filter(is_active=True, is_featured=True)
        serializer = self.get_serializer(featured, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def reviews(self, request, pk=None):
        """Get service reviews and ratings"""
        service = self.get_object()
        reviews = service.reviews.filter(is_published=True)

        avg_rating = reviews.aggregate(Avg('rating'))['rating__avg']
        rating_distribution = {
            i: reviews.filter(rating=i).count()
            for i in range(1, 6)
        }

        return Response({
            'service': service.name,
            'average_rating': round(avg_rating, 2) if avg_rating else None,
            'total_reviews': reviews.count(),
            'rating_distribution': rating_distribution,
            'reviews': [{
                'rating': r.rating,
                'review_text': r.review_text,
                'customer_name': r.customer_name,
                'created_at': r.created_at
            } for r in reviews.order_by('-created_at')[:10]]
        })


class ServiceAppointmentViewSet(viewsets.ModelViewSet):
    queryset = ServiceAppointment.objects.all()
    serializer_class = ServiceAppointmentSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'service', 'assigned_staff', 'scheduled_date']
    search_fields = ['appointment_number', 'customer_name', 'customer_email', 'customer_phone']
    ordering_fields = ['scheduled_date', 'scheduled_time', 'created_at']

    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """Confirm an appointment"""
        appointment = self.get_object()
        if appointment.status != ServiceAppointment.SCHEDULED:
            return Response(
                {'error': 'Only scheduled appointments can be confirmed'},
                status=status.HTTP_400_BAD_REQUEST
            )

        appointment.status = ServiceAppointment.CONFIRMED
        appointment.save()

        return Response(ServiceAppointmentSerializer(appointment).data)

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        """Start service execution"""
        appointment = self.get_object()

        if appointment.status not in [ServiceAppointment.SCHEDULED, ServiceAppointment.CONFIRMED]:
            return Response(
                {'error': 'Appointment cannot be started'},
                status=status.HTTP_400_BAD_REQUEST
            )

        appointment.status = ServiceAppointment.IN_PROGRESS
        appointment.actual_start_time = timezone.now()
        appointment.save()

        # Create service execution record
        execution = ServiceExecution.objects.create(
            appointment=appointment,
            service=appointment.service,
            performed_by=request.user,
            start_time=appointment.actual_start_time,
            status=ServiceExecution.IN_PROGRESS
        )

        return Response({
            'appointment': ServiceAppointmentSerializer(appointment).data,
            'execution': ServiceExecutionSerializer(execution).data
        })

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Complete an appointment"""
        appointment = self.get_object()

        if appointment.status != ServiceAppointment.IN_PROGRESS:
            return Response(
                {'error': 'Only in-progress appointments can be completed'},
                status=status.HTTP_400_BAD_REQUEST
            )

        appointment.status = ServiceAppointment.COMPLETED
        appointment.actual_end_time = timezone.now()
        appointment.save()

        # Update execution record
        if hasattr(appointment, 'execution'):
            execution = appointment.execution
            execution.status = ServiceExecution.COMPLETED
            execution.end_time = appointment.actual_end_time
            execution.save()

        return Response(ServiceAppointmentSerializer(appointment).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an appointment"""
        appointment = self.get_object()

        if appointment.status in [ServiceAppointment.COMPLETED, ServiceAppointment.CANCELLED]:
            return Response(
                {'error': 'Appointment cannot be cancelled'},
                status=status.HTTP_400_BAD_REQUEST
            )

        appointment.status = ServiceAppointment.CANCELLED
        appointment.cancellation_reason = request.data.get('reason', '')
        appointment.save()

        return Response(ServiceAppointmentSerializer(appointment).data)

    @action(detail=False, methods=['get'])
    def today(self, request):
        """Get today's appointments"""
        today = timezone.now().date()
        appointments = ServiceAppointment.objects.filter(
            scheduled_date=today
        ).order_by('scheduled_time')

        serializer = self.get_serializer(appointments, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def staff_schedule(self, request):
        """Get appointments for a specific staff member"""
        staff_id = request.query_params.get('staff_id')
        date = request.query_params.get('date', timezone.now().date())

        if not staff_id:
            return Response(
                {'error': 'staff_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        appointments = ServiceAppointment.objects.filter(
            assigned_staff_id=staff_id,
            scheduled_date=date
        ).order_by('scheduled_time')

        serializer = self.get_serializer(appointments, many=True)
        return Response(serializer.data)


class ServicePackageViewSet(viewsets.ModelViewSet):
    queryset = ServicePackage.objects.filter(is_active=True)
    serializer_class = ServicePackageSerializer
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code', 'description']
    ordering_fields = ['name', 'price', 'created_at']


class ServiceExecutionViewSet(viewsets.ModelViewSet):
    queryset = ServiceExecution.objects.all()
    serializer_class = ServiceExecutionSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['status', 'service', 'performed_by']
    search_fields = ['execution_number', 'work_description']
    ordering_fields = ['start_time', 'created_at']

    @action(detail=True, methods=['post'])
    def add_feedback(self, request, pk=None):
        """Add customer feedback to execution"""
        execution = self.get_object()

        execution.quality_rating = request.data.get('rating')
        execution.customer_feedback = request.data.get('feedback', '')
        execution.save()

        return Response(ServiceExecutionSerializer(execution).data)

    @action(detail=False, methods=['get'])
    def statistics(self, request):
        """Get execution statistics"""
        staff_id = request.query_params.get('staff_id')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        queryset = ServiceExecution.objects.filter(status=ServiceExecution.COMPLETED)

        if staff_id:
            queryset = queryset.filter(performed_by_id=staff_id)
        if start_date:
            queryset = queryset.filter(start_time__gte=start_date)
        if end_date:
            queryset = queryset.filter(start_time__lte=end_date)

        stats = queryset.aggregate(
            total_executions=Count('id'),
            avg_rating=Avg('quality_rating'),
            avg_duration=Avg('actual_duration_minutes')
        )

        return Response(stats)


