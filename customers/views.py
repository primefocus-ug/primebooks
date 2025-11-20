from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q, Count
from django.http import JsonResponse, HttpResponse
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext as _
from django.utils import timezone
from django.db import  models
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
)
from django.views.decorators.http import require_http_methods
import csv
from datetime import datetime, timedelta

from .forms import (
    CustomerForm, CustomerSearchForm, CustomerGroupForm,
    CustomerNoteForm, BulkCustomerActionForm, CustomerImportForm,
     EFRISSyncForm
)
from .models import Customer, CustomerGroup, CustomerNote, EFRISCustomerSync
from .serializers import (
    CustomerSerializer,
    CustomerGroupSerializer,
    CustomerNoteSerializer,
    CustomerTaxInfoSerializer,
    CustomerImportSerializer,
    CustomerExportSerializer,
    EFRISCustomerSerializer,
    EFRISSyncSerializer
)
from .exporters import CustomerExporter
from .efris_service import EFRISCustomerService
import pandas as pd


class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        company_id = self.request.query_params.get('company_id')
        customer_type = self.request.query_params.get('customer_type')
        efris_status = self.request.query_params.get('efris_status')

        if company_id:
            queryset = queryset.filter(company_id=company_id)
        if customer_type:
            queryset = queryset.filter(customer_type=customer_type)
        if efris_status:
            queryset = queryset.filter(efris_status=efris_status)

        return queryset

    @action(detail=True, methods=['get'])
    def tax_info(self, request, pk=None):
        customer = self.get_object()
        serializer = CustomerTaxInfoSerializer(customer)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def sync_to_efris(self, request, pk=None):
        """Sync single customer to eFRIS"""
        customer = self.get_object()

        if not customer.can_sync_to_efris:
            return Response(
                {'error': 'Customer does not have required information for eFRIS sync'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            service = EFRISCustomerService()
            result = service.register_customer(customer)

            if result['success']:
                return Response({
                    'success': True,
                    'message': 'Customer synced to eFRIS successfully',
                    'efris_id': result.get('efris_id'),
                    'reference': result.get('reference')
                })
            else:
                return Response({
                    'success': False,
                    'error': result.get('error', 'Unknown error occurred')
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            return Response(
                {'error': f'eFRIS sync failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def bulk_sync_to_efris(self, request):
        """Bulk sync customers to eFRIS"""
        customer_ids = request.data.get('customer_ids', [])

        if not customer_ids:
            return Response(
                {'error': 'No customers selected'},
                status=status.HTTP_400_BAD_REQUEST
            )

        customers = Customer.objects.filter(
            id__in=customer_ids,
            efris_status__in=['NOT_REGISTERED', 'FAILED']
        )

        results = {'success': 0, 'failed': 0, 'skipped': 0, 'errors': []}
        service = EFRISCustomerService()

        for customer in customers:
            if not customer.can_sync_to_efris:
                results['skipped'] += 1
                results['errors'].append(f'{customer.name}: Missing required information')
                continue

            try:
                result = service.register_customer(customer)
                if result['success']:
                    results['success'] += 1
                else:
                    results['failed'] += 1
                    results['errors'].append(f'{customer.name}: {result.get("error", "Unknown error")}')
            except Exception as e:
                results['failed'] += 1
                results['errors'].append(f'{customer.name}: {str(e)}')

        return Response(results)

    @action(detail=True, methods=['get'])
    def efris_status(self, request, pk=None):
        """Get customer eFRIS status and sync history"""
        customer = self.get_object()
        syncs = customer.efris_syncs.all()[:10]

        return Response({
            'customer_id': customer.id,
            'efris_status': customer.efris_status,
            'efris_customer_id': customer.efris_customer_id,
            'efris_registered_at': customer.efris_registered_at,
            'efris_last_sync': customer.efris_last_sync,
            'can_sync': customer.can_sync_to_efris,
            'sync_history': EFRISSyncSerializer(syncs, many=True).data
        })

    @action(detail=False, methods=['post'])
    def import_data(self, request):
        serializer = CustomerImportSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        file = serializer.validated_data['file']
        overwrite = serializer.validated_data['overwrite']
        auto_sync_efris = serializer.validated_data.get('auto_sync_efris', False)

        try:
            ext = file.name.lower().split('.')[-1]
            if ext == 'xlsx':
                df = pd.read_excel(file)
            else:
                df = pd.read_csv(file)
        except Exception as e:
            return Response({'error': f'Failed to read file: {e}'}, status=status.HTTP_400_BAD_REQUEST)

        results = {'created': 0, 'updated': 0, 'efris_synced': 0, 'errors': []}
        service = EFRISCustomerService() if auto_sync_efris else None

        def process_row(row):
            customer_data = {
                'name': row['name'],
                'customer_type': row.get('customer_type', 'INDIVIDUAL'),
                'email': row.get('email'),
                'phone': row['phone'],
                'tin': row.get('tin'),
                'nin': row.get('nin'),
                'brn': row.get('brn'),
                'physical_address': row.get('physical_address'),
                'postal_address': row.get('postal_address'),
                'district': row.get('district'),
                'is_vat_registered': bool(row.get('is_vat_registered', False)),
            }

            if overwrite and 'customer_id' in row and pd.notna(row['customer_id']):
                try:
                    customer = Customer.objects.get(customer_id=row['customer_id'])
                except Customer.DoesNotExist:
                    return 'Customer not found for update'
                serializer = CustomerSerializer(customer, data=customer_data)
                if serializer.is_valid():
                    customer = serializer.save()

                    # Auto sync to eFRIS if enabled
                    if auto_sync_efris and service and customer.can_sync_to_efris:
                        try:
                            result = service.register_customer(customer)
                            if result['success']:
                                results['efris_synced'] += 1
                        except:
                            pass  # Continue with import even if eFRIS sync fails

                    return 'updated'
                return serializer.errors
            else:
                serializer = CustomerSerializer(data=customer_data)
                if serializer.is_valid():
                    customer = serializer.save()

                    # Auto sync to eFRIS if enabled
                    if auto_sync_efris and service and customer.can_sync_to_efris:
                        try:
                            result = service.register_customer(customer)
                            if result['success']:
                                results['efris_synced'] += 1
                        except:
                            pass  # Continue with import even if eFRIS sync fails

                    return 'created'
                return serializer.errors

        for _, row in df.iterrows():
            result = process_row(row)
            if result == 'created':
                results['created'] += 1
            elif result == 'updated':
                results['updated'] += 1
            else:
                results['errors'].append(result)

        return Response(results)

    @action(detail=False, methods=['get'])
    def export(self, request):
        serializer = CustomerExportSerializer(data=request.query_params)
        if serializer.is_valid():
            queryset = self.filter_queryset(self.get_queryset())
            exporter = CustomerExporter(
                queryset,
                serializer.validated_data['format'],
                serializer.validated_data['include_tax_info'],
                serializer.validated_data.get('include_efris_info', False)
            )
            return exporter.export()
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CustomerListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Advanced customer list view with search, filtering, and eFRIS integration"""
    model = Customer
    template_name = 'customers/customer_list.html'
    context_object_name = 'customers'
    permission_required = 'customers.view_customer'
    paginate_by = 25
    ordering = ['-created_at']

    def get_queryset(self):
        queryset = Customer.objects.select_related('store').prefetch_related('groups', 'notes')

        # Apply search filters
        search_form = CustomerSearchForm(self.request.GET)
        if search_form.is_valid():
            search = search_form.cleaned_data.get('search')
            if search:
                queryset = queryset.filter(
                    Q(name__icontains=search) |
                    Q(phone__icontains=search) |
                    Q(email__icontains=search) |
                    Q(tin__icontains=search) |
                    Q(nin__icontains=search) |
                    Q(brn__icontains=search) |
                    Q(customer_id__icontains=search) |
                    Q(efris_customer_id__icontains=search)
                )

            customer_type = search_form.cleaned_data.get('customer_type')
            if customer_type:
                queryset = queryset.filter(customer_type=customer_type)

            store = search_form.cleaned_data.get('store')
            if store:
                queryset = queryset.filter(store=store)

            is_vat_registered = search_form.cleaned_data.get('is_vat_registered')
            if is_vat_registered != '':
                queryset = queryset.filter(is_vat_registered=is_vat_registered == '1')

            is_active = search_form.cleaned_data.get('is_active')
            if is_active != '':
                queryset = queryset.filter(is_active=is_active == '1')

            district = search_form.cleaned_data.get('district')
            if district:
                queryset = queryset.filter(district__icontains=district)

            # eFRIS filtering
            efris_status = search_form.cleaned_data.get('efris_status')
            if efris_status:
                queryset = queryset.filter(efris_status=efris_status)

        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = CustomerSearchForm(self.request.GET)
        context['bulk_form'] = BulkCustomerActionForm()

        # Add statistics
        queryset = self.get_queryset()
        context['stats'] = {
            'total': queryset.count(),
            'active': queryset.filter(is_active=True).count(),
            'vat_registered': queryset.filter(is_vat_registered=True).count(),
            'business': queryset.filter(customer_type='BUSINESS').count(),
            'efris_registered': queryset.filter(efris_status='REGISTERED').count(),
            'efris_pending': queryset.filter(efris_status__in=['NOT_REGISTERED', 'PENDING']).count(),
            'efris_failed': queryset.filter(efris_status='FAILED').count(),
        }

        return context


class CustomerDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """Detailed customer view with related information and eFRIS status"""
    model = Customer
    permission_required = 'customers.view_customer'
    template_name = 'customers/customer_detail.html'
    context_object_name = 'customer'

    def get_object(self):
        return get_object_or_404(
            Customer.objects.select_related('store').prefetch_related('groups', 'notes__author', 'efris_syncs'),
            pk=self.kwargs['pk']
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = self.get_object()

        context['note_form'] = CustomerNoteForm()
        context['notes'] = customer.notes.select_related('author').order_by('-created_at')[:10]
        context['efris_form'] = EFRISSyncForm()
        context['efris_syncs'] = customer.efris_syncs.all()[:10]

        # eFRIS status information
        context['efris_status'] = {
            'can_sync': customer.can_sync_to_efris,
            'is_registered': customer.is_efris_registered,
            'status_display': customer.get_efris_status_display(),
            'last_sync': customer.efris_last_sync,
            'sync_error': customer.efris_sync_error,
        }

        return context


class CustomerCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """Create new customer with validation and optional eFRIS sync"""
    model = Customer
    form_class = CustomerForm
    permission_required = 'customers.add_customer'
    template_name = 'customers/customer_form.html'
    success_url = reverse_lazy('customers:customer_list')

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        customer = self.object

        # Auto sync to eFRIS if requested
        auto_sync_efris = form.cleaned_data.get('auto_sync_efris', False)
        if auto_sync_efris and customer.can_sync_to_efris:
            try:
                service = EFRISCustomerService()
                result = service.register_customer(customer)
                if result['success']:
                    messages.success(
                        self.request,
                        _('Customer created and synced to eFRIS successfully.')
                    )
                else:
                    messages.warning(
                        self.request,
                        _('Customer created but eFRIS sync failed: %(error)s') % {
                            'error': result.get('error', 'Unknown error')}
                    )
            except Exception as e:
                messages.warning(
                    self.request,
                    _('Customer created but eFRIS sync failed: %(error)s') % {'error': str(e)}
                )
        else:
            messages.success(self.request, _('Customer created successfully.'))

        return response

    def form_invalid(self, form):
        messages.error(self.request, _('Please correct the errors below.'))
        return super().form_invalid(form)


class CustomerUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Update existing customer with eFRIS sync option"""
    model = Customer
    form_class = CustomerForm
    permission_required = 'customers.change_customer'
    template_name = 'customers/customer_form.html'

    def get_success_url(self):
        return reverse('customers:detail', kwargs={'pk': self.object.pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        response = super().form_valid(form)
        customer = self.object

        # Check if eFRIS update is requested
        update_efris = form.cleaned_data.get('update_efris', False)
        if update_efris and customer.is_efris_registered:
            try:
                service = EFRISCustomerService()
                result = service.update_customer(customer)
                if result['success']:
                    messages.success(
                        self.request,
                        _('Customer updated and synced to eFRIS successfully.')
                    )
                else:
                    messages.warning(
                        self.request,
                        _('Customer updated but eFRIS sync failed: %(error)s') % {
                            'error': result.get('error', 'Unknown error')}
                    )
            except Exception as e:
                messages.warning(
                    self.request,
                    _('Customer updated but eFRIS sync failed: %(error)s') % {'error': str(e)}
                )
        else:
            messages.success(self.request, _('Customer updated successfully.'))

        return response


@login_required
@require_http_methods(["POST"])
def sync_customer_to_efris(request, pk):
    """Sync individual customer to eFRIS"""
    customer = get_object_or_404(Customer, pk=pk)

    if not customer.can_sync_to_efris:
        messages.error(
            request,
            _('Customer does not have required information for eFRIS sync.')
        )
        return redirect('customers:detail', pk=pk)

    try:
        service = EFRISCustomerService()

        if customer.is_efris_registered:
            result = service.update_customer(customer)
            action = 'updated'
        else:
            result = service.register_customer(customer)
            action = 'registered'

        if result['success']:
            messages.success(
                request,
                _('Customer %(action)s in eFRIS successfully.') % {'action': action}
            )
        else:
            messages.error(
                request,
                _('eFRIS sync failed: %(error)s') % {'error': result.get('error', 'Unknown error')}
            )

    except Exception as e:
        messages.error(
            request,
            _('eFRIS sync failed: %(error)s') % {'error': str(e)}
        )

    return redirect('customers:detail', pk=pk)


@login_required
@require_http_methods(["POST"])
def bulk_customer_action(request):
    """Handle bulk actions on customers including eFRIS sync"""
    form = BulkCustomerActionForm(request.POST)

    if form.is_valid():
        action = form.cleaned_data['action']
        selected_ids = request.POST.getlist('selected_customers')

        if not selected_ids:
            messages.error(request, _('No customers selected.'))
            return redirect('customers:customer_list')

        customers = Customer.objects.filter(id__in=selected_ids)

        if action == 'activate':
            customers.update(is_active=True)
            messages.success(request, _('Selected customers activated.'))

        elif action == 'deactivate':
            customers.update(is_active=False)
            messages.success(request, _('Selected customers deactivated.'))

        elif action == 'sync_to_efris':
            # Bulk sync to eFRIS
            eligible_customers = customers.filter(
                efris_status__in=['NOT_REGISTERED', 'FAILED']
            )

            if not eligible_customers.exists():
                messages.warning(request, _('No customers eligible for eFRIS sync.'))
                return redirect('customers:customer_list')

            try:
                service = EFRISCustomerService()
                success_count = 0
                error_count = 0

                for customer in eligible_customers:
                    if customer.can_sync_to_efris:
                        try:
                            result = service.register_customer(customer)
                            if result['success']:
                                success_count += 1
                            else:
                                error_count += 1
                        except:
                            error_count += 1
                    else:
                        error_count += 1

                if success_count > 0:
                    messages.success(
                        request,
                        _('%(count)d customers synced to eFRIS successfully.') % {'count': success_count}
                    )

                if error_count > 0:
                    messages.warning(
                        request,
                        _('%(count)d customers failed to sync to eFRIS.') % {'count': error_count}
                    )

            except Exception as e:
                messages.error(
                    request,
                    _('Bulk eFRIS sync failed: %(error)s') % {'error': str(e)}
                )

        elif action == 'add_to_group':
            group = form.cleaned_data.get('group')
            if group:
                group.customers.add(*customers)
                messages.success(request, _('Customers added to group.'))

                # Auto sync if group has auto_sync_to_efris enabled
                if group.auto_sync_to_efris:
                    non_registered = customers.filter(efris_status='NOT_REGISTERED')
                    if non_registered.exists():
                        try:
                            service = EFRISCustomerService()
                            for customer in non_registered:
                                if customer.can_sync_to_efris:
                                    service.register_customer(customer)
                        except:
                            pass  # Continue silently

        elif action == 'remove_from_group':
            group = form.cleaned_data.get('group')
            if group:
                group.customers.remove(*customers)
                messages.success(request, _('Customers removed from group.'))

        elif action == 'export':
            return export_customers(request, customers)

        elif action == 'delete':
            count = customers.count()
            customers.delete()
            messages.success(request, _('%(count)d customers deleted.') % {'count': count})

    return redirect('customers:customer_list')


def export_customers(request, customers=None):
    """Export customers to CSV with eFRIS information"""
    if customers is None:
        customers = Customer.objects.all()

    response = HttpResponse(content_type='text/csv')
    response[
        'Content-Disposition'] = f'attachment; filename="customers_efris_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Customer ID', 'Name', 'Type', 'Email', 'Phone', 'TIN', 'NIN', 'BRN',
        'Physical Address', 'District', 'Country', 'VAT Registered', 'Credit Limit',
        'Active', 'eFRIS Status', 'eFRIS Customer ID', 'eFRIS Registered At',
        'eFRIS Last Sync', 'Created At'
    ])

    for customer in customers:
        writer.writerow([
            customer.customer_id,
            customer.name,
            customer.get_customer_type_display(),
            customer.email,
            customer.phone,
            customer.tin,
            customer.nin,
            customer.brn,
            customer.physical_address,
            customer.district,
            customer.country,
            'Yes' if customer.is_vat_registered else 'No',
            customer.credit_limit,
            'Yes' if customer.is_active else 'No',
            customer.get_efris_status_display(),
            customer.efris_customer_id,
            customer.efris_registered_at.strftime('%Y-%m-%d %H:%M:%S') if customer.efris_registered_at else '',
            customer.efris_last_sync.strftime('%Y-%m-%d %H:%M:%S') if customer.efris_last_sync else '',
            customer.created_at.strftime('%Y-%m-%d %H:%M:%S'),
        ])

    return response


class EFRISCustomerDashboardView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """eFRIS Customer dashboard with analytics"""
    template_name = 'customers/efris_dashboard.html'
    permission_required = 'customers.view_customer'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # eFRIS Statistics
        total_customers = Customer.objects.count()
        efris_stats = Customer.objects.aggregate(
            registered=Count('id', filter=Q(efris_status='REGISTERED')),
            pending=Count('id', filter=Q(efris_status__in=['NOT_REGISTERED', 'PENDING'])),
            failed=Count('id', filter=Q(efris_status='FAILED')),
            updated=Count('id', filter=Q(efris_status='UPDATED')),
        )

        # Sync history (last 30 days)
        thirty_days_ago = timezone.now() - timedelta(days=30)
        sync_history = EFRISCustomerSync.objects.filter(
            created_at__gte=thirty_days_ago
        ).values('status').annotate(
            count=Count('id')
        ).order_by('status')

        # Recent sync activities
        recent_syncs = EFRISCustomerSync.objects.select_related(
            'customer'
        ).order_by('-created_at')[:20]

        # Customers ready for sync
        ready_for_sync = Customer.objects.filter(
            efris_status='NOT_REGISTERED'
        ).exclude(
            Q(name__isnull=True) | Q(name__exact='') |
            Q(phone__isnull=True) | Q(phone__exact='')
        )

        # Failed syncs that can be retried
        failed_syncs = EFRISCustomerSync.objects.filter(
            status='FAILED',
            retry_count__lt=models.F('max_retries')
        ).select_related('customer')

        context.update({
            'total_customers': total_customers,
            'efris_stats': efris_stats,
            'sync_history': list(sync_history),
            'recent_syncs': recent_syncs,
            'ready_for_sync': ready_for_sync[:10],
            'ready_count': ready_for_sync.count(),
            'failed_syncs': failed_syncs[:10],
            'failed_count': failed_syncs.count(),
            'sync_percentage': round(
                (efris_stats['registered'] / total_customers * 100) if total_customers > 0 else 0, 1
            ),
        })

        return context


@login_required
def efris_sync_status_api(request):
    """API endpoint for eFRIS sync status"""
    stats = {
        'total_customers': Customer.objects.count(),
        'efris_registered': Customer.objects.filter(efris_status='REGISTERED').count(),
        'efris_pending': Customer.objects.filter(efris_status__in=['NOT_REGISTERED', 'PENDING']).count(),
        'efris_failed': Customer.objects.filter(efris_status='FAILED').count(),
        'ready_for_sync': Customer.objects.filter(
            efris_status='NOT_REGISTERED'
        ).exclude(
            Q(name__isnull=True) | Q(name__exact='') |
            Q(phone__isnull=True) | Q(phone__exact='')
        ).count(),
        'recent_syncs': EFRISCustomerSync.objects.filter(
            created_at__gte=timezone.now() - timedelta(hours=24)
        ).count(),
    }

    return JsonResponse(stats)


@login_required
@require_http_methods(["POST"])
def retry_failed_efris_sync(request, sync_id):
    """Retry a failed eFRIS sync"""
    sync_record = get_object_or_404(EFRISCustomerSync, id=sync_id)

    if not sync_record.can_retry:
        messages.error(request, _('This sync cannot be retried.'))
        return redirect('customers:efris_dashboard')

    try:
        service = EFRISCustomerService()

        if sync_record.sync_type == 'REGISTER':
            result = service.register_customer(sync_record.customer)
        elif sync_record.sync_type == 'UPDATE':
            result = service.update_customer(sync_record.customer)
        else:
            result = {'success': False, 'error': 'Invalid sync type'}

        if result['success']:
            sync_record.mark_success(
                response_data=result.get('response_data'),
                efris_reference=result.get('reference')
            )
            messages.success(request, _('eFRIS sync retry successful.'))
        else:
            sync_record.mark_failed(result.get('error', 'Retry failed'))
            messages.error(
                request,
                _('eFRIS sync retry failed: %(error)s') % {'error': result.get('error', 'Unknown error')}
            )

    except Exception as e:
        sync_record.mark_failed(str(e))
        messages.error(
            request,
            _('eFRIS sync retry failed: %(error)s') % {'error': str(e)}
        )

    return redirect('customers:efris_dashboard')

class CustomerGroupViewSet(viewsets.ModelViewSet):
    queryset = CustomerGroup.objects.all()
    serializer_class = CustomerGroupSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        company_id = self.request.query_params.get('company_id')
        if company_id:
            queryset = queryset.filter(company_id=company_id)
        return queryset

    @action(detail=True, methods=['post'])
    def add_customers(self, request, pk=None):
        group = self.get_object()
        customer_ids = request.data.get('customer_ids', [])

        # Optional: Validate these customers belong to user's company
        group.customers.add(*customer_ids)
        return Response({'status': 'success', 'count': group.customers.count()})

class CustomerNoteViewSet(viewsets.ModelViewSet):
    queryset = CustomerNote.objects.all()
    serializer_class = CustomerNoteSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        customer_id = self.request.query_params.get('customer_id')
        if customer_id:
            queryset = queryset.filter(customer_id=customer_id)
        return queryset

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)

@login_required
def customer_import(request):
    """Import customers from CSV/Excel file"""
    if request.method == 'POST':
        form = CustomerImportForm(request.POST, request.FILES)
        if form.is_valid():
            file = form.cleaned_data['file']
            update_existing = form.cleaned_data['update_existing']

            try:
                # Read file based on extension
                if file.name.endswith('.csv'):
                    df = pd.read_csv(file)
                else:
                    df = pd.read_excel(file)

                created_count = 0
                updated_count = 0
                errors = []

                for index, row in df.iterrows():
                    try:
                        # Map CSV columns to model fields
                        data = {
                            'name': row.get('name', ''),
                            'customer_type': row.get('customer_type', 'INDIVIDUAL'),
                            'email': row.get('email', ''),
                            'phone': row.get('phone', ''),
                            'tin': row.get('tin', ''),
                            'nin': row.get('nin', ''),
                            'brn': row.get('brn', ''),
                            'physical_address': row.get('physical_address', ''),
                            'district': row.get('district', ''),
                            'country': row.get('country', 'Uganda'),
                        }

                        # Try to find existing customer
                        existing = None
                        if update_existing:
                            if data['phone']:
                                existing = Customer.objects.filter(phone=data['phone']).first()
                            elif data['email']:
                                existing = Customer.objects.filter(email=data['email']).first()

                        if existing:
                            # Update existing customer
                            for key, value in data.items():
                                if value:
                                    setattr(existing, key, value)
                            existing.save()
                            updated_count += 1
                        else:
                            # Create new customer
                            customer = Customer(**data)
                            customer.save()
                            created_count += 1

                    except Exception as e:
                        errors.append(f'Row {index + 1}: {str(e)}')

                if errors:
                    messages.warning(request,
                                     _('Import completed with errors: %(errors)s') % {'errors': ', '.join(errors)})

                messages.success(request, _('Import completed. Created: %(created)d, Updated: %(updated)d') % {
                    'created': created_count, 'updated': updated_count
                })

            except Exception as e:
                messages.error(request, _('Error processing file: %(error)s') % {'error': str(e)})
    else:
        form = CustomerImportForm()

    return render(request, 'customers/customer_import.html', {'form': form})

class CustomerGroupCreateView(LoginRequiredMixin,PermissionRequiredMixin, CreateView):
    """Create new customer group"""
    model = CustomerGroup
    form_class = CustomerGroupForm
    permission_required = 'customers.add_customergroup'
    template_name = 'customers/group_form.html'
    success_url = reverse_lazy('customers:group_list')


class CustomerGroupUpdateView(LoginRequiredMixin,PermissionRequiredMixin, UpdateView):
    """Update customer group"""
    model = CustomerGroup
    form_class = CustomerGroupForm
    permission_required = 'customers.change_customergroup'
    template_name = 'customers/group_form.html'
    success_url = reverse_lazy('customers:group_list')


class CustomerGroupDeleteView(LoginRequiredMixin,PermissionRequiredMixin, DeleteView):
    """Delete customer group"""
    model = CustomerGroup
    permission_required = 'customers.delete_customergroup'
    template_name = 'customers/group_confirm_delete.html'
    success_url = reverse_lazy('customers:group_list')

@login_required
def customer_stats_api(request):
    """API endpoint for customer statistics"""
    stats = {
        'total_customers': Customer.objects.count(),
        'active_customers': Customer.objects.filter(is_active=True).count(),
        'business_customers': Customer.objects.filter(customer_type='BUSINESS').count(),
        'vat_registered': Customer.objects.filter(is_vat_registered=True).count(),
        'by_type': {
            'INDIVIDUAL': Customer.objects.filter(customer_type='INDIVIDUAL').count(),
            'BUSINESS': Customer.objects.filter(customer_type='BUSINESS').count(),
            'GOVERNMENT': Customer.objects.filter(customer_type='GOVERNMENT').count(),
            'NGO': Customer.objects.filter(customer_type='NGO').count(),
        },
        'recent_registrations': Customer.objects.filter(
            created_at__gte=datetime.now() - timedelta(days=30)
        ).count(),
    }

    return JsonResponse(stats)


@login_required
def validate_customer_field(request):
    """AJAX endpoint for field validation"""
    field_name = request.GET.get('field')
    field_value = request.GET.get('value')
    customer_id = request.GET.get('customer_id')

    if not field_name or not field_value:
        return JsonResponse({'valid': True})

    # Build query
    query = Q(**{field_name: field_value})

    # Exclude current customer if editing
    queryset = Customer.objects.filter(query)
    if customer_id:
        queryset = queryset.exclude(id=customer_id)

    exists = queryset.exists()

    return JsonResponse({
        'valid': not exists,
        'message': _('This %(field)s is already in use.') % {'field': field_name} if exists else ''
    })

class CustomerDeleteView(LoginRequiredMixin,PermissionRequiredMixin, DeleteView):
    """Delete customer with confirmation"""
    model = Customer
    permission_required = 'customers.delete_customer'
    template_name = 'customers/customer_confirm_delete.html'
    success_url = reverse_lazy('customers:customer_list')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, _('Customer deleted successfully.'))
        return super().delete(request, *args, **kwargs)


@login_required
@require_http_methods(["POST"])
def add_customer_note(request, pk):
    """Add a note to a customer"""
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerNoteForm(request.POST)

    if form.is_valid():
        note = form.save(commit=False)
        note.customer = customer
        note.author = request.user
        note.save()
        messages.success(request, _('Note added successfully.'))
    else:
        messages.error(request, _('Error adding note.'))

    return redirect('customers:detail', pk=pk)


class CustomerGroupListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """List all customer groups with eFRIS sync info"""
    model = CustomerGroup
    permission_required = 'customers.view_customergroup'
    template_name = 'customers/group_list.html'
    context_object_name = 'groups'
    paginate_by = 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Add eFRIS stats for each group
        for group in context['groups']:
            group.efris_stats = {
                'registered': group.efris_registered_count,
                'pending': group.efris_pending_count,
                'total': group.customers.count()
            }

        return context


class CustomerDashboardView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """Enhanced customer dashboard with eFRIS analytics"""
    template_name = 'customers/dashboard.html'
    permission_required = 'customers.view_customer'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Basic stats
        total_customers = Customer.objects.count()
        active_customers = Customer.objects.filter(is_active=True).count()

        # eFRIS stats
        efris_stats = Customer.objects.aggregate(
            registered=Count('id', filter=Q(efris_status='REGISTERED')),
            pending=Count('id', filter=Q(efris_status__in=['NOT_REGISTERED', 'PENDING'])),
            failed=Count('id', filter=Q(efris_status='FAILED')),
        )

        # Customer type breakdown with eFRIS status
        customer_types = Customer.objects.values('customer_type').annotate(
            total_count=Count('id'),
            efris_registered=Count('id', filter=Q(efris_status='REGISTERED')),
        ).order_by('customer_type')

        # Recent activities
        recent_customers = Customer.objects.order_by('-created_at')[:10]
        recent_syncs = EFRISCustomerSync.objects.select_related(
            'customer'
        ).order_by('-created_at')[:10]

        context.update({
            'total_customers': total_customers,
            'active_customers': active_customers,
            'inactive_customers': total_customers - active_customers,
            'efris_stats': efris_stats,
            'customer_types': customer_types,
            'recent_customers': recent_customers,
            'recent_syncs': recent_syncs,
            'efris_sync_percentage': round(
                (efris_stats['registered'] / total_customers * 100) if total_customers > 0 else 0, 1
            ),
        })

        return context


# API Views
@login_required
def customer_autocomplete(request):
    """AJAX endpoint for customer autocomplete with eFRIS info"""
    term = request.GET.get('term', '')
    customers = Customer.objects.filter(
        Q(name__icontains=term) | Q(phone__icontains=term) | Q(email__icontains=term)
    ).filter(is_active=True)[:10]

    data = [
        {
            'id': customer.id,
            'label': f"{customer.name} - {customer.phone}",
            'value': customer.name,
            'phone': customer.phone,
            'email': customer.email,
            'customer_type': customer.get_customer_type_display(),
            'efris_status': customer.efris_status,
            'efris_customer_id': customer.efris_customer_id,
        }
        for customer in customers
    ]

    return JsonResponse(data, safe=False)