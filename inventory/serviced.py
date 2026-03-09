from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib import messages
from django.views.generic import ListView, CreateView, UpdateView, DeleteView, DetailView
from django.views.decorators.http import require_http_methods, require_POST
from django.http import JsonResponse, HttpResponse
from django.urls import reverse_lazy, reverse
from django.db.models import Q, Count, Sum, Avg
from django.db import transaction
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
    List view for services with pagination and filtering.
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

        # 🔥 CRITICAL FIX: Filter categories by type='service'
        context['categories'] = Category.objects.filter(
            category_type='service',
            is_active=True
        ).order_by('name')

        # Get filter parameters for the template
        context['current_search'] = self.request.GET.get('search', '')
        context['current_category'] = self.request.GET.get('category', '')
        context['current_tax_rate'] = self.request.GET.get('tax_rate', '')
        context['current_efris_status'] = self.request.GET.get('efris_status', '')
        context['current_is_active'] = self.request.GET.get('is_active', '')

        # Debug logging
        logger.info(f"📊 Service categories in context: {context['categories'].count()}")
        for cat in context['categories']:
            logger.info(f"  - {cat.name} (Type: {cat.category_type}, ID: {cat.id})")

        return context


# ===========================================
# SERVICE LIST API (for AJAX loading)
# ===========================================

@login_required
@require_http_methods(["GET"])
def service_list_api(request):
    """
    API endpoint for fetching services with pagination and filters.
    Returns JSON data for client-side rendering.
    """
    try:
        # Get pagination parameters
        page = int(request.GET.get('page', 1))
        per_page = int(request.GET.get('per_page', 25))

        # Base queryset
        queryset = Service.objects.select_related('category', 'created_by')

        # Apply search
        search_value = request.GET.get('search', '')
        if search_value:
            queryset = queryset.filter(
                Q(name__icontains=search_value) |
                Q(code__icontains=search_value) |
                Q(description__icontains=search_value) |
                Q(category__name__icontains=search_value)
            )

        # Apply filters
        category_id = request.GET.get('category')
        if category_id:
            queryset = queryset.filter(category_id=category_id)

        tax_rate = request.GET.get('tax_rate')
        if tax_rate:
            queryset = queryset.filter(tax_rate=tax_rate)

        efris_status = request.GET.get('efris_status')
        if efris_status == 'uploaded':
            queryset = queryset.filter(efris_is_uploaded=True)
        elif efris_status == 'pending':
            queryset = queryset.filter(
                efris_is_uploaded=False,
                efris_auto_sync_enabled=True
            )
        elif efris_status == 'disabled':
            queryset = queryset.filter(efris_auto_sync_enabled=False)

        is_active = request.GET.get('is_active')
        if is_active == 'true':
            queryset = queryset.filter(is_active=True)
        elif is_active == 'false':
            queryset = queryset.filter(is_active=False)

        # Get ordering
        order_by = request.GET.get('order_by', '-created_at')
        valid_order_fields = ['name', '-name', 'code', '-code', 'unit_price',
                              '-unit_price', 'created_at', '-created_at']
        if order_by in valid_order_fields:
            queryset = queryset.order_by(order_by)

        # Total records
        total_records = queryset.count()

        # Paginate
        paginator = Paginator(queryset, per_page)
        page_obj = paginator.get_page(page)

        # Build data
        data = []
        for service in page_obj:
            # EFRIS status
            if not service.efris_auto_sync_enabled:
                efris_status = 'disabled'
                efris_status_text = 'Disabled'
            elif service.efris_is_uploaded:
                efris_status = 'uploaded'
                efris_status_text = 'Uploaded'
            else:
                efris_status = 'pending'
                efris_status_text = 'Pending'

            data.append({
                'id': service.id,
                'name': service.name,
                'code': service.code,
                'description': service.description or '',
                'category': {
                    'id': service.category.id if service.category else None,
                    'name': service.category.name if service.category else '-'
                },
                'unit_price': float(service.unit_price),
                'unit_price_formatted': f'{service.unit_price:,.2f}',
                'final_price': float(service.final_price),
                'final_price_formatted': f'{service.final_price:,.2f}',
                'tax_rate': service.tax_rate,
                'efris_status': efris_status,
                'efris_status_text': efris_status_text,
                'is_active': service.is_active,
                'created_at': service.created_at.isoformat(),
                'detail_url': reverse('inventory:service_detail', args=[service.id]),
                'edit_url': reverse('inventory:service_update', args=[service.id]),
                'delete_url': reverse('inventory:service_delete', args=[service.id]),
            })

        return JsonResponse({
            'success': True,
            'data': data,
            'pagination': {
                'page': page_obj.number,
                'per_page': per_page,
                'total_pages': paginator.num_pages,
                'total_records': total_records,
                'has_previous': page_obj.has_previous(),
                'has_next': page_obj.has_next(),
                'previous_page': page_obj.previous_page_number() if page_obj.has_previous() else None,
                'next_page': page_obj.next_page_number() if page_obj.has_next() else None,
            }
        })

    except Exception as e:
        logger.error(f"Error in service_list_api: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ===========================================
# SERVICE CREATE VIEW
# ===========================================

class ServiceCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """Create view for services (modal-based)"""
    model = Service
    form_class = ServiceForm
    permission_required = 'inventory.add_service'
    template_name = 'inventory/service_form.html'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        # Add company for VAT enforcement
        kwargs['company'] = self.request.tenant
        # Add EFRIS status
        kwargs['efris_enabled'] = self.request.tenant.efris_enabled
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # 🔥 CRITICAL FIX: Add service categories to context
        context['categories'] = Category.objects.filter(
            category_type='service',
            is_active=True
        ).order_by('name')

        context['form_type'] = 'service'

        # Debug logging
        logger.info(f"📋 Service create form categories: {context['categories'].count()}")

        return context

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
                        'unit_price': float(self.object.unit_price),
                        'final_price': float(self.object.final_price),
                        'detail_url': reverse('inventory:service_detail', args=[self.object.id]),
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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.request.tenant
        kwargs['efris_enabled'] = self.request.tenant.efris_enabled
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # 🔥 CRITICAL FIX: Add service categories to context
        context['categories'] = Category.objects.filter(
            category_type='service',
            is_active=True
        ).order_by('name')

        context['form_type'] = 'service'

        return context

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
                        'unit_price': float(self.object.unit_price),
                        'final_price': float(self.object.final_price),
                        'detail_url': reverse('inventory:service_detail', args=[self.object.id]),
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
    template_name = 'inventory/service_confirm_delete.html'
    success_url = reverse_lazy('inventory:service_list')

    def post(self, request, *args, **kwargs):
        """
        Override post() instead of delete() — required in Django 4+.
        delete() is no longer called on POST; post() is the correct hook.
        """
        service = self.get_object()
        service_name = service.name

        try:
            service.delete()

            logger.info(
                f"Service deleted: {service_name} (ID: {service.pk}) "
                f"by {request.user}"
            )

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Service "{service_name}" deleted successfully!'
                })

            messages.success(request, _(f'Service "{service_name}" deleted successfully!'))
            return redirect(self.success_url)

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

        return JsonResponse({
            'success': True,
            'data': data
        })

    except Service.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Service not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error in service_detail_api: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def service_search_api(request):
    """Search services API for autocomplete"""
    query = request.GET.get('q', '')
    limit = int(request.GET.get('limit', 20))

    services = Service.objects.filter(
        Q(name__icontains=query) | Q(code__icontains=query),
        is_active=True
    ).select_related('category')[:limit]

    results = [
        {
            'id': service.id,
            'name': service.name,
            'code': service.code,
            'unit_price': str(service.unit_price),
            'final_price': str(service.final_price),
            'category': service.category.name if service.category else None,
        }
        for service in services
    ]

    return JsonResponse({
        'success': True,
        'results': results
    })


# ===========================================
# BULK ACTIONS
# ===========================================

@login_required
@permission_required('inventory.change_service')
@require_POST
@transaction.atomic
def service_bulk_actions(request):
    """Handle bulk actions on services"""
    try:
        action = request.POST.get('action')
        service_ids = request.POST.getlist('service_ids[]')

        if not action:
            return JsonResponse({
                'success': False,
                'error': 'No action specified'
            }, status=400)

        if not service_ids:
            return JsonResponse({
                'success': False,
                'error': 'No services selected'
            }, status=400)

        services = Service.objects.filter(id__in=service_ids)
        count = services.count()

        if count == 0:
            return JsonResponse({
                'success': False,
                'error': 'No services found'
            }, status=404)

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
import logging
from django.contrib.auth.decorators import login_required, permission_required
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.db import connection
from django_tenants.utils import schema_context, get_tenant_model

logger = logging.getLogger(__name__)


def get_company_efris_status(company):
    """
    Check company-level EFRIS configuration status.
    Only checks if EFRIS is enabled - rest is handled elsewhere.

    Args:
        company: Company instance

    Returns:
        dict: {
            'enabled': bool,
            'can_sync': bool,
            'errors': list
        }
    """
    status = {
        'enabled': False,
        'can_sync': False,
        'errors': []
    }

    try:
        # Check if EFRIS is enabled at company level
        if not company.efris_enabled:
            status['errors'].append('EFRIS is not enabled for this company')
            return status

        status['enabled'] = True
        status['can_sync'] = True

        return status

    except Exception as e:
        logger.error(f"Error checking company EFRIS status: {e}")
        status['errors'].append(f"Error checking EFRIS status: {str(e)}")
        return status


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

        # Get current company
        Company = get_tenant_model()
        company = Company.objects.get(schema_name=connection.schema_name)

        # Check company-level EFRIS status
        efris_status = get_company_efris_status(company)

        if not efris_status['can_sync']:
            return JsonResponse({
                'success': False,
                'error': 'EFRIS is not enabled for this company',
                'errors': efris_status['errors']
            }, status=400)

        # Check if service is ready for EFRIS
        if not service.efris_configuration_complete:
            errors = service.get_efris_errors()
            return JsonResponse({
                'success': False,
                'error': 'Service is not ready for EFRIS sync',
                'errors': errors,
                'details': {
                    'service_name': service.name,
                    'service_code': service.code,
                }
            }, status=400)

        # Check if service has EFRIS auto-sync enabled
        if not service.efris_auto_sync_enabled:
            return JsonResponse({
                'success': False,
                'error': 'EFRIS auto-sync is disabled for this service',
                'details': {
                    'service_name': service.name,
                    'suggestion': 'Enable EFRIS auto-sync for this service first'
                }
            }, status=400)

        # Get tenant schema
        schema_name = request.tenant.schema_name

        # Try async task, fall back to sync
        try:
            from .tasks import sync_service_to_efris_task
            task = sync_service_to_efris_task.delay(
                schema_name=schema_name,
                service_id=service.id,
                user_id=request.user.id
            )

            logger.info(
                f"Service '{service.name}' (ID: {service.id}) queued for EFRIS sync "
                f"(Task: {task.id}, Company: {company.name})"
            )

            return JsonResponse({
                'success': True,
                'message': f'Service "{service.name}" queued for EFRIS sync',
                'task_id': task.id,
                'status': 'pending',
                'details': {
                    'service_id': service.id,
                    'service_name': service.name,
                    'service_code': service.code,
                    'company_name': company.name,
                }
            })

        except ImportError:
            # Celery not available, run synchronously
            logger.warning("Celery not available, running EFRIS sync synchronously")

            from efris.services import EFRISServiceManager

            with schema_context(schema_name):
                manager = EFRISServiceManager(company)
                result = manager.register_service(service, user=request.user)

            if result.get('success'):
                logger.info(
                    f"Service '{service.name}' synced to EFRIS successfully "
                    f"(EFRIS ID: {result.get('efris_service_id')})"
                )

                return JsonResponse({
                    'success': True,
                    'message': result.get('message', 'Service synced successfully'),
                    'efris_service_id': result.get('efris_service_id'),
                    'details': {
                        'service_id': service.id,
                        'service_name': service.name,
                        'service_code': service.code,
                    }
                })
            else:
                logger.error(
                    f"Failed to sync service '{service.name}' to EFRIS: {result.get('error')}"
                )

                return JsonResponse({
                    'success': False,
                    'error': result.get('error', 'Sync failed'),
                    'details': result.get('details', {})
                }, status=400)

    except Service.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Service not found'
        }, status=404)

    except Exception as e:
        logger.error(f"Error syncing service to EFRIS: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An unexpected error occurred',
            'details': {'error_message': str(e)}
        }, status=500)


@login_required
@permission_required('inventory.change_service')
@require_POST
def service_bulk_efris_sync(request):
    """
    Bulk sync services to EFRIS using company-level EFRIS configuration.
    """
    try:
        service_ids = request.POST.getlist('service_ids[]')

        if not service_ids:
            return JsonResponse({
                'success': False,
                'error': 'No services selected',
                'details': {'hint': 'Please select at least one service to sync'}
            }, status=400)

        # Get current company
        Company = get_tenant_model()
        company = Company.objects.get(schema_name=connection.schema_name)

        # Check company-level EFRIS status
        efris_status = get_company_efris_status(company)

        if not efris_status['can_sync']:
            return JsonResponse({
                'success': False,
                'error': 'EFRIS is not enabled for this company',
                'errors': efris_status['errors'],
                'details': {
                    'selected_count': len(service_ids),
                }
            }, status=400)

        # Validate services exist and are ready for sync
        from inventory.models import Service

        services = Service.objects.filter(id__in=service_ids)

        if not services.exists():
            return JsonResponse({
                'success': False,
                'error': 'No valid services found',
                'details': {'selected_count': len(service_ids)}
            }, status=404)

        # Check which services are ready for sync
        ready_services = []
        not_ready_services = []

        for service in services:
            if service.efris_configuration_complete and service.efris_auto_sync_enabled:
                ready_services.append(service)
            else:
                not_ready_services.append({
                    'id': service.id,
                    'name': service.name,
                    'reason': 'Configuration incomplete or auto-sync disabled'
                })

        if not ready_services:
            return JsonResponse({
                'success': False,
                'error': 'None of the selected services are ready for EFRIS sync',
                'details': {
                    'selected_count': len(service_ids),
                    'ready_count': 0,
                    'not_ready_services': not_ready_services
                }
            }, status=400)

        # Get tenant schema
        schema_name = request.tenant.schema_name
        ready_service_ids = [s.id for s in ready_services]

        # Try async task
        try:
            from .tasks import bulk_sync_services_to_efris_task
            task = bulk_sync_services_to_efris_task.delay(
                schema_name=schema_name,
                service_ids=ready_service_ids,
                user_id=request.user.id
            )

            logger.info(
                f"Bulk sync queued for {len(ready_services)} services "
                f"(Task: {task.id}, Company: {company.name})"
            )

            response_data = {
                'success': True,
                'message': f'{len(ready_services)} service(s) queued for EFRIS sync',
                'task_id': task.id,
                'details': {
                    'total_selected': len(service_ids),
                    'ready_count': len(ready_services),
                    'queued_count': len(ready_services),
                    'company_name': company.name,
                }
            }

            if not_ready_services:
                response_data['warnings'] = {
                    'not_ready_count': len(not_ready_services),
                    'not_ready_services': not_ready_services
                }

            return JsonResponse(response_data)

        except ImportError:
            # Celery not available, run synchronously
            logger.warning("Celery not available, running bulk sync synchronously")

            from efris.services import bulk_register_services_with_efris

            with schema_context(schema_name):
                results = bulk_register_services_with_efris(
                    company,
                    service_ids=ready_service_ids
                )

            logger.info(
                f"Bulk sync completed: {results['successful']}/{results['total']} services synced "
                f"(Company: {company.name})"
            )

            response_data = {
                'success': True,
                'message': f"Synced {results['successful']}/{results['total']} services to EFRIS",
                'results': results,
                'details': {
                    'total_selected': len(service_ids),
                    'ready_count': len(ready_services),
                    'successful': results['successful'],
                    'failed': results['failed'],
                    'company_name': company.name,
                }
            }

            if not_ready_services:
                response_data['warnings'] = {
                    'not_ready_count': len(not_ready_services),
                    'not_ready_services': not_ready_services
                }

            return JsonResponse(response_data)

    except Exception as e:
        logger.error(f"Bulk EFRIS sync error: {str(e)}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': 'An unexpected error occurred during bulk sync',
            'details': {'error_message': str(e)}
        }, status=500)


@login_required
@permission_required('inventory.view_service')
def check_service_efris_status(request, pk):
    """
    Check EFRIS sync readiness for a specific service.
    Useful for frontend to show status before attempting sync.
    """
    try:
        service = get_object_or_404(Service, pk=pk)

        # Get current company
        Company = get_tenant_model()
        company = Company.objects.get(schema_name=connection.schema_name)

        # Check company-level EFRIS status
        efris_status = get_company_efris_status(company)

        # Get service-specific errors
        service_errors = service.get_efris_errors() if not service.efris_configuration_complete else []

        response = {
            'service': {
                'id': service.id,
                'name': service.name,
                'code': service.code,
                'efris_auto_sync_enabled': service.efris_auto_sync_enabled,
                'efris_is_uploaded': service.efris_is_uploaded,
                'efris_configuration_complete': service.efris_configuration_complete,
                'efris_service_id': service.efris_service_id,
            },
            'company_efris': {
                'enabled': efris_status['enabled'],
                'can_sync': efris_status['can_sync'],
                'errors': efris_status['errors'],
            },
            'can_sync': (
                    efris_status['can_sync'] and
                    service.efris_configuration_complete and
                    service.efris_auto_sync_enabled
            ),
            'service_errors': service_errors,
            'overall_status': 'ready' if (
                    efris_status['can_sync'] and
                    service.efris_configuration_complete and
                    service.efris_auto_sync_enabled
            ) else 'not_ready'
        }

        return JsonResponse(response)

    except Service.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': 'Service not found'
        }, status=404)

    except Exception as e:
        logger.error(f"Error checking service EFRIS status: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

# ===========================================
# STATISTICS API
# ===========================================

@login_required
@require_http_methods(["GET"])
def service_statistics_api(request):
    """Get service statistics"""
    try:
        stats = {
            'total': Service.objects.count(),
            'active': Service.objects.filter(is_active=True).count(),
            'inactive': Service.objects.filter(is_active=False).count(),
            'efris_uploaded': Service.objects.filter(efris_is_uploaded=True).count(),
            'efris_pending': Service.objects.filter(
                efris_is_uploaded=False,
                efris_auto_sync_enabled=True
            ).count(),
            'efris_disabled': Service.objects.filter(efris_auto_sync_enabled=False).count(),
        }

        return JsonResponse({
            'success': True,
            'stats': stats
        })

    except Exception as e:
        logger.error(f"Error fetching service statistics: {str(e)}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)