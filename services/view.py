from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q, Count, Sum, Avg
from django.http import JsonResponse
from django.utils import timezone
from django.core.paginator import Paginator
from datetime import datetime, timedelta
from decimal import Decimal

from .models import (
    Service, ServiceCategory, ServiceType, ServiceAppointment,
    ServicePackage, ServiceExecution, ServiceDiscount, ServiceReview,
    StaffServiceSkill, ServicePricingTier
)
from .forms import (
    ServiceForm, ServiceAppointmentForm, ServiceExecutionForm,
    ServicePackageForm, ServiceReviewForm
)


# ==================== Dashboard ====================
@login_required
def services_dashboard(request):
    """Main services dashboard - tenant-aware"""
    today = timezone.now().date()

    # Get today's appointments for this tenant
    today_appointments = ServiceAppointment.objects.filter(
        scheduled_date=today
    ).select_related('service', 'assigned_staff')

    # Statistics
    total_services = Service.objects.filter(is_active=True).count()
    active_appointments = ServiceAppointment.objects.filter(
        status__in=['scheduled', 'confirmed', 'in_progress']
    ).count()
    completed_today = ServiceAppointment.objects.filter(
        scheduled_date=today,
        status='completed'
    ).count()

    # Revenue today
    revenue_today = ServiceAppointment.objects.filter(
        scheduled_date=today,
        status='completed'
    ).aggregate(total=Sum('total_amount'))['total'] or 0

    # Upcoming appointments
    upcoming = ServiceAppointment.objects.filter(
        scheduled_date__gte=today,
        status__in=['scheduled', 'confirmed']
    ).order_by('scheduled_date', 'scheduled_time')[:10]

    # Top services this month
    start_of_month = today.replace(day=1)
    top_services = Service.objects.filter(
        appointments__scheduled_date__gte=start_of_month,
        appointments__status='completed'
    ).annotate(
        bookings=Count('appointments')
    ).order_by('-bookings')[:5]

    context = {
        'today_appointments': today_appointments,
        'total_services': total_services,
        'active_appointments': active_appointments,
        'completed_today': completed_today,
        'revenue_today': revenue_today,
        'upcoming': upcoming,
        'top_services': top_services,
    }

    return render(request, 'services/dashboard.html', context)


# ==================== Service Management ====================
@login_required
def service_list(request):
    """List all services - tenant-aware"""
    services = Service.objects.filter(is_active=True).select_related(
        'category', 'service_type'
    )

    # Filtering
    category_id = request.GET.get('category')
    service_type_id = request.GET.get('service_type')
    search = request.GET.get('search')

    if category_id:
        services = services.filter(category_id=category_id)
    if service_type_id:
        services = services.filter(service_type_id=service_type_id)
    if search:
        services = services.filter(
            Q(name__icontains=search) |
            Q(code__icontains=search) |
            Q(description__icontains=search)
        )

    # Pagination
    paginator = Paginator(services, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    categories = ServiceCategory.objects.filter(is_active=True)
    service_types = ServiceType.objects.filter(is_active=True)

    context = {
        'page_obj': page_obj,
        'categories': categories,
        'service_types': service_types,
        'selected_category': category_id,
        'selected_type': service_type_id,
        'search_query': search,
    }

    return render(request, 'services/service_list.html', context)


@login_required
def service_detail(request, pk):
    """Service detail view - tenant-aware"""
    service = get_object_or_404(Service, pk=pk)

    # Get pricing tiers
    pricing_tiers = service.pricing_tiers.filter(is_active=True)

    # Get resources
    resources = service.resources.all()

    # Get reviews
    reviews = service.reviews.filter(is_published=True).order_by('-created_at')[:10]
    avg_rating = reviews.aggregate(Avg('rating'))['rating__avg']

    # Get upcoming appointments
    upcoming_appointments = service.appointments.filter(
        scheduled_date__gte=timezone.now().date(),
        status__in=['scheduled', 'confirmed']
    ).order_by('scheduled_date', 'scheduled_time')[:5]

    # Get staff who can perform this service
    skilled_staff = StaffServiceSkill.objects.filter(
        service=service,
        is_active=True
    ).select_related('staff')

    context = {
        'service': service,
        'pricing_tiers': pricing_tiers,
        'resources': resources,
        'reviews': reviews,
        'avg_rating': avg_rating,
        'upcoming_appointments': upcoming_appointments,
        'skilled_staff': skilled_staff,
    }

    return render(request, 'services/service_detail.html', context)


@login_required
def service_create(request):
    """Create new service - tenant-aware"""
    if request.method == 'POST':
        form = ServiceForm(request.POST, request.FILES)
        if form.is_valid():
            service = form.save(commit=False)
            service.created_by = request.user
            service.save()
            messages.success(request, f'Service "{service.name}" created successfully!')
            return redirect('services:service_detail', pk=service.pk)
    else:
        form = ServiceForm()

    context = {'form': form, 'action': 'Create'}
    return render(request, 'services/service_form.html', context)


@login_required
def service_update(request, pk):
    """Update service - tenant-aware"""
    service = get_object_or_404(Service, pk=pk)

    if request.method == 'POST':
        form = ServiceForm(request.POST, request.FILES, instance=service)
        if form.is_valid():
            form.save()
            messages.success(request, f'Service "{service.name}" updated successfully!')
            return redirect('services:service_detail', pk=service.pk)
    else:
        form = ServiceForm(instance=service)

    context = {'form': form, 'service': service, 'action': 'Update'}
    return render(request, 'services/service_form.html', context)


@login_required
def service_delete(request, pk):
    """Soft delete service - tenant-aware"""
    service = get_object_or_404(Service, pk=pk)

    if request.method == 'POST':
        service.is_active = False
        service.save()
        messages.success(request, f'Service "{service.name}" deleted successfully!')
        return redirect('services:service_list')

    context = {'service': service}
    return render(request, 'services/service_confirm_delete.html', context)


# ==================== Appointment Management ====================
@login_required
def appointment_list(request):
    """List appointments - tenant-aware"""
    appointments = ServiceAppointment.objects.select_related(
        'service', 'assigned_staff'
    ).order_by('-scheduled_date', '-scheduled_time')

    # Filtering
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    service_id = request.GET.get('service')
    staff_id = request.GET.get('staff')

    if status:
        appointments = appointments.filter(status=status)
    if date_from:
        appointments = appointments.filter(scheduled_date__gte=date_from)
    if date_to:
        appointments = appointments.filter(scheduled_date__lte=date_to)
    if service_id:
        appointments = appointments.filter(service_id=service_id)
    if staff_id:
        appointments = appointments.filter(assigned_staff_id=staff_id)

    # Pagination
    paginator = Paginator(appointments, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    services = Service.objects.filter(is_active=True, requires_appointment=True)

    context = {
        'page_obj': page_obj,
        'services': services,
        'status_choices': ServiceAppointment.STATUS_CHOICES,
    }

    return render(request, 'services/appointment_list.html', context)


@login_required
def appointment_calendar(request):
    """Calendar view for appointments - tenant-aware"""
    # Get month and year from request
    year = int(request.GET.get('year', timezone.now().year))
    month = int(request.GET.get('month', timezone.now().month))

    # Get appointments for the month
    start_date = datetime(year, month, 1).date()
    if month == 12:
        end_date = datetime(year + 1, 1, 1).date()
    else:
        end_date = datetime(year, month + 1, 1).date()

    appointments = ServiceAppointment.objects.filter(
        scheduled_date__gte=start_date,
        scheduled_date__lt=end_date
    ).select_related('service', 'assigned_staff')

    # Group by date
    appointments_by_date = {}
    for appointment in appointments:
        date_key = appointment.scheduled_date.strftime('%Y-%m-%d')
        if date_key not in appointments_by_date:
            appointments_by_date[date_key] = []
        appointments_by_date[date_key].append(appointment)

    context = {
        'year': year,
        'month': month,
        'appointments_by_date': appointments_by_date,
        'current_date': timezone.now().date(),
    }

    return render(request, 'services/appointment_calendar.html', context)


@login_required
def appointment_create(request):
    """Create appointment - tenant-aware"""
    if request.method == 'POST':
        form = ServiceAppointmentForm(request.POST)
        if form.is_valid():
            appointment = form.save(commit=False)
            appointment.created_by = request.user
            appointment.save()
            messages.success(request, f'Appointment {appointment.appointment_number} created!')
            return redirect('services:appointment_detail', pk=appointment.pk)
    else:
        # Pre-fill with service if provided
        service_id = request.GET.get('service')
        initial = {}
        if service_id:
            initial['service'] = service_id
        form = ServiceAppointmentForm(initial=initial)

    context = {'form': form, 'action': 'Create'}
    return render(request, 'services/appointment_form.html', context)


@login_required
def appointment_detail(request, pk):
    """Appointment detail view - tenant-aware"""
    appointment = get_object_or_404(ServiceAppointment, pk=pk)

    # Get execution if exists
    execution = None
    if hasattr(appointment, 'execution'):
        execution = appointment.execution

    context = {
        'appointment': appointment,
        'execution': execution,
    }

    return render(request, 'services/appointment_detail.html', context)


@login_required
def appointment_update_status(request, pk):
    """Update appointment status - AJAX endpoint"""
    if request.method == 'POST':
        appointment = get_object_or_404(ServiceAppointment, pk=pk)
        new_status = request.POST.get('status')

        if new_status in dict(ServiceAppointment.STATUS_CHOICES):
            old_status = appointment.status
            appointment.status = new_status

            # Handle status-specific logic
            if new_status == ServiceAppointment.IN_PROGRESS:
                appointment.actual_start_time = timezone.now()

                # Create execution record
                ServiceExecution.objects.get_or_create(
                    appointment=appointment,
                    defaults={
                        'service': appointment.service,
                        'performed_by': request.user,
                        'start_time': appointment.actual_start_time,
                        'status': ServiceExecution.IN_PROGRESS
                    }
                )

            elif new_status == ServiceAppointment.COMPLETED:
                appointment.actual_end_time = timezone.now()

                # Update execution
                if hasattr(appointment, 'execution'):
                    execution = appointment.execution
                    execution.end_time = appointment.actual_end_time
                    execution.status = ServiceExecution.COMPLETED
                    execution.save()

            elif new_status == ServiceAppointment.CANCELLED:
                appointment.cancellation_reason = request.POST.get('reason', '')

            appointment.save()

            return JsonResponse({
                'success': True,
                'message': f'Status updated from {old_status} to {new_status}',
                'new_status': new_status
            })

        return JsonResponse({'success': False, 'message': 'Invalid status'}, status=400)

    return JsonResponse({'success': False, 'message': 'Invalid request'}, status=400)


# ==================== Service Execution ====================
@login_required
def execution_list(request):
    """List service executions - tenant-aware"""
    executions = ServiceExecution.objects.select_related(
        'service', 'performed_by', 'appointment'
    ).order_by('-start_time')

    # Filtering
    status = request.GET.get('status')
    staff_id = request.GET.get('staff')

    if status:
        executions = executions.filter(status=status)
    if staff_id:
        executions = executions.filter(performed_by_id=staff_id)

    # Pagination
    paginator = Paginator(executions, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'status_choices': ServiceExecution.STATUS_CHOICES,
    }

    return render(request, 'services/execution_list.html', context)


@login_required
def execution_detail(request, pk):
    """Execution detail view - tenant-aware"""
    execution = get_object_or_404(ServiceExecution, pk=pk)

    context = {'execution': execution}
    return render(request, 'services/execution_detail.html', context)


@login_required
def execution_update(request, pk):
    """Update execution - tenant-aware"""
    execution = get_object_or_404(ServiceExecution, pk=pk)

    if request.method == 'POST':
        form = ServiceExecutionForm(request.POST, instance=execution)
        if form.is_valid():
            form.save()
            messages.success(request, 'Execution updated successfully!')
            return redirect('services:execution_detail', pk=execution.pk)
    else:
        form = ServiceExecutionForm(instance=execution)

    context = {'form': form, 'execution': execution}
    return render(request, 'services/execution_form.html', context)


# ==================== Service Packages ====================
@login_required
def package_list(request):
    """List service packages - tenant-aware"""
    packages = ServicePackage.objects.filter(is_active=True).prefetch_related('items__service')

    context = {'packages': packages}
    return render(request, 'services/package_list.html', context)


@login_required
def package_detail(request, pk):
    """Package detail view - tenant-aware"""
    package = get_object_or_404(ServicePackage, pk=pk)
    items = package.items.select_related('service')

    context = {
        'package': package,
        'items': items,
        'total_value': package.calculate_total_value(),
        'savings': package.calculate_savings(),
    }

    return render(request, 'services/package_detail.html', context)


# ==================== Reports ====================
@login_required
def reports_dashboard(request):
    """Reports dashboard - tenant-aware"""
    today = timezone.now().date()
    start_date = request.GET.get('start_date', (today - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date = request.GET.get('end_date', today.strftime('%Y-%m-%d'))

    # Revenue statistics
    appointments = ServiceAppointment.objects.filter(
        scheduled_date__range=[start_date, end_date],
        status='completed'
    )

    total_revenue = appointments.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
    total_appointments = appointments.count()
    avg_appointment_value = total_revenue / total_appointments if total_appointments > 0 else 0

    # Service performance
    service_stats = Service.objects.filter(
        appointments__scheduled_date__range=[start_date, end_date],
        appointments__status='completed'
    ).annotate(
        bookings=Count('appointments'),
        revenue=Sum('appointments__total_amount')
    ).order_by('-revenue')[:10]

    # Staff performance
    from django.contrib.auth import get_user_model
    User = get_user_model()
    staff_stats = User.objects.filter(
        service_appointments__scheduled_date__range=[start_date, end_date],
        service_appointments__status='completed'
    ).annotate(
        appointments_count=Count('service_appointments'),
        revenue=Sum('service_appointments__total_amount')
    ).order_by('-revenue')[:10]

    # Daily revenue trend
    from django.db.models.functions import TruncDate
    daily_revenue = appointments.annotate(
        date=TruncDate('scheduled_date')
    ).values('date').annotate(
        revenue=Sum('total_amount'),
        count=Count('id')
    ).order_by('date')

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'total_revenue': total_revenue,
        'total_appointments': total_appointments,
        'avg_appointment_value': avg_appointment_value,
        'service_stats': service_stats,
        'staff_stats': staff_stats,
        'daily_revenue': list(daily_revenue),
    }

    return render(request, 'services/reports_dashboard.html', context)


# ==================== AJAX Endpoints ====================
@login_required
def get_service_price(request, pk):
    """Get service price with calculations - AJAX"""
    service = get_object_or_404(Service, pk=pk)
    duration = request.GET.get('duration_minutes')
    tier = request.GET.get('tier_level')

    price = service.calculate_price(
        duration_minutes=int(duration) if duration else None,
        tier_level=int(tier) if tier else None
    )

    tax = service.calculate_tax(price)
    total = price + tax if not service.is_tax_inclusive else price

    return JsonResponse({
        'base_price': float(service.base_price),
        'calculated_price': float(price),
        'tax_amount': float(tax),
        'total': float(total),
        'tax_rate': float(service.tax_rate),
        'is_tax_inclusive': service.is_tax_inclusive
    })


@login_required
def check_availability(request, pk):
    """Check service availability - AJAX"""
    service = get_object_or_404(Service, pk=pk)
    date = request.GET.get('date')
    time = request.GET.get('time')
    staff_id = request.GET.get('staff_id')

    if not date:
        return JsonResponse({'available': True})

    # Check if slot is available
    filters = {
        'service': service,
        'scheduled_date': date,
        'status__in': ['scheduled', 'confirmed', 'in_progress']
    }

    if time:
        filters['scheduled_time'] = time
    if staff_id:
        filters['assigned_staff_id'] = staff_id

    existing = ServiceAppointment.objects.filter(**filters).exists()

    return JsonResponse({
        'available': not existing,
        'service': service.name,
        'date': date,
        'time': time
    })
