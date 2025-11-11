from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.views.decorators.http import require_http_methods, require_POST
from django.http import JsonResponse, HttpResponse
from django.urls import reverse_lazy, reverse
from django.db.models import Q, Count, Sum, Avg
from django.core.paginator import Paginator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
import json
import logging

from .models import Service, Category
from .forms import ServiceForm, ServiceQuickCreateForm, ServiceFilterForm, ServiceBulkActionForm
from company.models import EFRISCommodityCategory

logger = logging.getLogger(__name__)


# ===========================================
# SERVICE LIST VIEW
# ===========================================

class ServiceListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """
    List view for services with DataTables integration.
    Supports AJAX requests for server-side processing.
    """
    model = Service
    template_name = 'inventory/service_list.html'
    context_object_name = 'services'
    permission_required = 'inventory.view_service'
    paginate_by = 25

    def get_queryset(self):
        queryset = Service.objects.select_related(
            'category', 'created_by'
        ).prefetch_related(
            'category__efris_commodity_category'
        )

        # Apply filters
        search = self.request.GET.get('search', '')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(description__icontains=search)
            )

        category_id = self.request.GET.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)

        tax_rate = self.request.GET.get('tax_rate')
        if tax_rate:
            queryset = queryset.filter(tax_rate=tax_rate)

        efris_status = self.request.GET.get('efris_status')
        if efris_status == 'uploaded':
            queryset = queryset.filter(efris_is_uploaded=True)
        elif efris_status == 'pending':
            queryset = queryset.filter(
                efris_is_uploaded=False,
                efris_auto_sync_enabled=True
            )
        elif efris_status == 'disabled':
            queryset = queryset.filter(efris_auto_sync_enabled=False)

        is_active = self.request.GET.get('is_active')
        if is_active == 'true':
            queryset = queryset.filter(is_active=True)
        elif is_active == 'false':
            queryset = queryset.filter(is_active=False)

        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = ServiceFilterForm(self.request.GET)
        context['total_services'] = Service.objects.count()
        context['active_services'] = Service.objects.filter(is_active=True).count()
        context['efris_uploaded'] = Service.objects.filter(efris_is_uploaded=True).count()
        return context


# ===========================================
# SERVICE DATATABLE API
# ===========================================

@login_required
@require_http_methods(["GET"])
def service_datatable_api(request):
    """
    API endpoint for DataTables server-side processing.
    Returns JSON data for the service list table.
    """
    try:
        # DataTables parameters
        draw = int(request.GET.get('draw', 1))
        start = int(request.GET.get('start', 0))
        length = int(request.GET.get('length', 25))
        search_value = request.GET.get('search[value]', '')

        # Base queryset
        queryset = Service.objects.select_related('category', 'created_by')

        # Apply search
        if search_value:
            queryset = queryset.filter(
                Q(name__icontains=search_value) |
                Q(code__icontains=search_value) |
                Q(description__icontains=search_value) |
                Q(category__name__icontains=search_value)
            )

        # Total records
        total_records = Service.objects.count()
        filtered_records = queryset.count()

        # Ordering
        order_column_index = int(request.GET.get('order[0][column]', 0))
        order_direction = request.GET.get('order[0][dir]', 'asc')

        order_columns = ['name', 'code', 'category__name', 'unit_price', 'created_at']
        if order_column_index < len(order_columns):
            order_column = order_columns[order_column_index]
            if order_direction == 'desc':
                order_column = f'-{order_column}'
            queryset = queryset.order_by(order_column)

        # Pagination
        queryset = queryset[start:start + length]

        # Build data
        data = []
        for service in queryset:
            # EFRIS status badge
            if not service.efris_auto_sync_enabled:
                efris_badge = '<span class="badge bg-secondary">Disabled</span>'
            elif service.efris_is_uploaded:
                efris_badge = '<span class="badge bg-success">✓ Uploaded</span>'
            else:
                efris_badge = '<span class="badge bg-warning">Pending</span>'

            # Active status
            status_badge = (
                '<span class="badge bg-success">Active</span>' if service.is_active
                else '<span class="badge bg-danger">Inactive</span>'
            )

            # Actions
            actions = f'''
                <div class="btn-group btn-group-sm" role="group">
                    <button type="button" class="btn btn-info btn-sm edit-service" 
                            data-id="{service.id}" title="Edit">
                        <i class="bi bi-pencil"></i>
                    </button>
                    <a href="{reverse('inventory:service_detail', args=[service.id])}" 
                       class="btn btn-primary btn-sm" title="View">
                        <i class="bi bi-eye"></i>
                    </a>
                    <button type="button" class="btn btn-danger btn-sm delete-service" 
                            data-id="{service.id}" title="Delete">
                        <i class="bi bi-trash"></i>
                    </button>
                </div>
            '''

            data.append({
                'id': service.id,
                'name': service.name,
                'code': service.code,
                'category': service.category.name if service.category else '-',
                'unit_price': f'UGX {service.unit_price:,.2f}',
                'final_price': f'UGX {service.final_price:,.2f}',
                'efris_status': efris_badge,
                'status': status_badge,
                'actions': actions,
            })

        return JsonResponse({
            'draw': draw,
            'recordsTotal': total_records,
            'recordsFiltered': filtered_records,
            'data': data
        })

    except Exception as e:
        logger.error(f"Error in service_datatable_api: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# ===========================================
# SERVICE CREATE VIEW
# ===========================================

class ServiceCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """Create view for services (modal-based)"""
    model = Service
    form_class = ServiceForm
    permission_required = 'inventory.add_service'
    template_name = 'inventory/service_form.html'

    def get_success_url(self):
        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return reverse('inventory:service_list')
        return reverse('inventory:service_detail', args=[self.object.pk])

    def form_valid(self, form):
        try:
            form.instance.created_by = self.request.user
            response = super().form_valid(form)

            logger.info(
                f"Service created successfully: {form.instance.name} "
                f"(ID: {form.instance.id}) by {self.request.user}"
            )

            if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Service created successfully!',
                    'service': {
                        'id': self.object.id,
                        'name': self.object.name,
                        'code': self.object.code,
                    }
                })

            messages.success(self.request, _('Service created successfully!'))
            return response

        except Exception as e:
            logger.error(f"Error creating service: {str(e)}")

            if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'errors': {'non_field_errors': [str(e)]}
                }, status=400)

            messages.error(self.request, _('Error creating service. Please try again.'))
            return self.form_invalid(form)

    def form_invalid(self, form):
        logger.error(f"Service form validation failed: {form.errors}")

        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'errors': form.errors
            }, status=400)

        for field, errors in form.errors.items():
            for error in errors:
                messages.error(self.request, f"{field}: {error}")

        return super().form_invalid(form)


# ===========================================
# SERVICE UPDATE VIEW
# ===========================================

class ServiceUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Update view for services (modal-based)"""
    model = Service
    form_class = ServiceForm
    permission_required = 'inventory.change_service'
    template_name = 'inventory/service_form.html'

    def get_success_url(self):
        return reverse('inventory:service_detail', args=[self.object.pk])

    def form_valid(self, form):
        try:
            response = super().form_valid(form)

            logger.info(
                f"Service updated successfully: {form.instance.name} "
                f"(ID: {form.instance.id}) by {self.request.user}"
            )

            if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': 'Service updated successfully!',
                    'service': {
                        'id': self.object.id,
                        'name': self.object.name,
                        'code': self.object.code,
                    }
                })

            messages.success(self.request, _('Service updated successfully!'))
            return response

        except Exception as e:
            logger.error(f"Error updating service: {str(e)}")

            if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'errors': {'non_field_errors': [str(e)]}
                }, status=400)

            messages.error(self.request, _('Error updating service. Please try again.'))
            return self.form_invalid(form)

    def form_invalid(self, form):
        logger.error(f"Service update form validation failed: {form.errors}")

        if self.request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'success': False,
                'errors': form.errors
            }, status=400)

        return super().form_invalid(form)


# ===========================================
# SERVICE DETAIL VIEW
# ===========================================

class ServiceDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """Detail view for services"""
    model = Service
    template_name = 'inventory/service_detail.html'
    context_object_name = 'service'
    permission_required = 'inventory.view_service'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        service = self.object

        # EFRIS configuration errors (if any)
        context['efris_errors'] = service.get_efris_errors()
        context['efris_config_complete'] = service.efris_configuration_complete

        # Get EFRIS category details
        if service.category and service.category.efris_commodity_category:
            context['efris_category'] = service.category.efris_commodity_category

        return context


# ===========================================
# SERVICE DELETE VIEW
# ===========================================

class ServiceDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    """Delete view for services"""
    model = Service
    permission_required = 'inventory.delete_service'
    success_url = reverse_lazy('inventory:service_list')

    def delete(self, request, *args, **kwargs):
        service = self.get_object()
        service_name = service.name

        try:
            response = super().delete(request, *args, **kwargs)

            logger.info(
                f"Service deleted: {service_name} (ID: {service.id}) "
                f"by {request.user}"
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Service "{service_name}" deleted successfully!'
                })

            messages.success(request, _(f'Service "{service_name}" deleted successfully!'))
            return response

        except Exception as e:
            logger.error(f"Error deleting service: {str(e)}")

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=400)

            messages.error(request, _('Error deleting service. Please try again.'))
            return redirect('inventory:service_list')


# ===========================================
# SERVICE API ENDPOINTS
# ===========================================

@login_required
@require_http_methods(["GET"])
def service_detail_api(request, pk):
    """Get service details as JSON"""
    try:
        service = Service.objects.select_related('category').get(pk=pk)

        data = {
            'id': service.id,
            'name': service.name,
            'code': service.code,
            'description': service.description,
            'category_id': service.category_id,
            'category_name': service.category.name if service.category else None,
            'unit_price': str(service.unit_price),
            'discount_percentage': str(service.discount_percentage),
            'final_price': str(service.final_price),
            'tax_rate': service.tax_rate,
            'excise_duty_rate': str(service.excise_duty_rate),
            'unit_of_measure': service.unit_of_measure,
            'image_url': service.image.url if service.image else None,
            'efris_auto_sync_enabled': service.efris_auto_sync_enabled,
            'efris_is_uploaded': service.efris_is_uploaded,
            'efris_status_display': service.efris_status_display,
            'is_active': service.is_active,
            'created_at': service.created_at.isoformat(),
        }

        return JsonResponse(data)

    except Service.DoesNotExist:
        return JsonResponse({'error': 'Service not found'}, status=404)
    except Exception as e:
        logger.error(f"Error in service_detail_api: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_http_methods(["GET"])
def service_search_api(request):
    """Search services API for autocomplete"""
    query = request.GET.get('q', '')
    limit = int(request.GET.get('limit', 20))

    services = Service.objects.filter(
        Q(name__icontains=query) | Q(code__icontains=query),
        is_active=True
    )[:limit]

    results = [
        {
            'id': service.id,
            'name': service.name,
            'code': service.code,
            'unit_price': str(service.unit_price),
            'final_price': str(service.final_price),
        }
        for service in services
    ]

    return JsonResponse({'results': results})


# ===========================================
# BULK ACTIONS
# ===========================================

@login_required
@permission_required('inventory.change_service')
@require_POST
def service_bulk_actions(request):
    """Handle bulk actions on services"""
    try:
        form = ServiceBulkActionForm(request.POST)

        if not form.is_valid():
            return JsonResponse({
                'success': False,
                'errors': form.errors
            }, status=400)

        action = form.cleaned_data['action']
        service_ids = form.cleaned_data['service_ids']

        services = Service.objects.filter(id__in=service_ids)
        count = services.count()

        if action == 'activate':
            services.update(is_active=True)
            message = f'{count} service(s) activated successfully'

        elif action == 'deactivate':
            services.update(is_active=False)
            message = f'{count} service(s) deactivated successfully'

        elif action == 'enable_efris':
            for service in services:
                try:
                    service.enable_efris_sync()
                except ValueError as e:
                    logger.warning(f"Could not enable EFRIS for {service.name}: {e}")
            message = f'EFRIS sync enabled for {count} service(s)'

        elif action == 'disable_efris':
            for service in services:
                service.disable_efris_sync()
            message = f'EFRIS sync disabled for {count} service(s)'

        elif action == 'mark_for_upload':
            for service in services:
                service.mark_for_efris_upload()
            message = f'{count} service(s) marked for EFRIS upload'

        elif action == 'delete':
            if not request.user.has_perm('inventory.delete_service'):
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied'
                }, status=403)
            services.delete()
            message = f'{count} service(s) deleted successfully'

        else:
            return JsonResponse({
                'success': False,
                'error': 'Invalid action'
            }, status=400)

        logger.info(f"Bulk action '{action}' performed on {count} services by {request.user}")

        return JsonResponse({
            'success': True,
            'message': message,
            'count': count
        })

    except Exception as e:
        logger.error(f"Error in service_bulk_actions: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ===========================================
# EFRIS SYNC
# ===========================================

@login_required
@permission_required('inventory.change_service')
@require_POST
def service_efris_sync(request, pk):
    """
    Manually trigger EFRIS sync for a service.
    Uses async task if available, otherwise synchronous.
    """
    try:
        service = get_object_or_404(Service, pk=pk)

        # Check if service is ready for EFRIS
        if not service.efris_configuration_complete:
            errors = service.get_efris_errors()
            return JsonResponse({
                'success': False,
                'error': 'Service not ready for EFRIS sync',
                'errors': errors
            }, status=400)

        # Get tenant schema
        from django_tenants.utils import schema_context
        schema_name = request.tenant.schema_name

        # Try async task, fall back to sync
        try:
            from .tasks import sync_service_to_efris_task
            task = sync_service_to_efris_task.delay(
                schema_name=schema_name,
                service_id=service.id,
                user_id=request.user.id
            )

            logger.info(f"Service {service.name} queued for EFRIS sync (task: {task.id})")

            return JsonResponse({
                'success': True,
                'message': f'Service "{service.name}" queued for EFRIS sync',
                'task_id': task.id,
                'status': 'pending'
            })

        except ImportError:
            # Celery not available, run synchronously
            logger.warning("Celery not available, running sync synchronously")

            from company.models import Company
            from efris.api_client import EFRISServiceManager

            company = Company.objects.get(schema_name=schema_name)

            with schema_context(schema_name):
                manager = EFRISServiceManager(company)
                result = manager.register_service(service, user=request.user)

            if result.get('success'):
                return JsonResponse({
                    'success': True,
                    'message': result.get('message', 'Service synced successfully'),
                    'efris_service_id': result.get('efris_service_id')
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': result.get('error', 'Sync failed')
                }, status=400)

    except Exception as e:
        logger.error(f"Error syncing service to EFRIS: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@permission_required('inventory.change_service')
@require_POST
def service_bulk_efris_sync(request):
    """
    Bulk sync services to EFRIS
    """
    try:
        service_ids = request.POST.getlist('service_ids[]')

        if not service_ids:
            return JsonResponse({
                'success': False,
                'error': 'No services selected'
            }, status=400)

        # Get tenant schema
        from django_tenants.utils import schema_context
        schema_name = request.tenant.schema_name

        # Try async task
        try:
            from .tasks import bulk_sync_services_to_efris_task
            task = bulk_sync_services_to_efris_task.delay(
                schema_name=schema_name,
                service_ids=service_ids,
                user_id=request.user.id
            )

            logger.info(f"Bulk sync queued for {len(service_ids)} services (task: {task.id})")

            return JsonResponse({
                'success': True,
                'message': f'{len(service_ids)} service(s) queued for EFRIS sync',
                'task_id': task.id,
                'count': len(service_ids)
            })

        except ImportError:
            # Run synchronously
            from company.models import Company
            from efris.api_client import bulk_register_services_with_efris

            company = Company.objects.get(schema_name=schema_name)

            with schema_context(schema_name):
                results = bulk_register_services_with_efris(company)

            return JsonResponse({
                'success': True,
                'message': f'Synced {results["successful"]}/{results["total"]} services',
                'results': results
            })

    except Exception as e:
        logger.error(f"Bulk EFRIS sync error: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def check_efris_task_status(request, task_id):
    """
    Check the status of an EFRIS task
    """
    try:
        from celery.result import AsyncResult

        task = AsyncResult(task_id)

        if task.ready():
            result = task.result
            return JsonResponse({
                'status': 'completed',
                'success': result.get('success', False) if isinstance(result, dict) else True,
                'result': result
            })
        elif task.failed():
            return JsonResponse({
                'status': 'failed',
                'error': str(task.info)
            })
        else:
            return JsonResponse({
                'status': 'pending',
                'state': task.state
            })

    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'error': str(e)
        }, status=500)