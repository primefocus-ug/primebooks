import json
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Q, Count, Sum
from django.http import JsonResponse, HttpResponse
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext as _
from django.utils import timezone
from django.db import  models
from decimal import Decimal
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
from .models import Customer, CustomerGroup, CustomerNote, EFRISCustomerSync,CustomerCreditStatement
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


@login_required
@permission_required('customers.view_customer',raise_exception=True)
def customer_search_with_store(request):
    """
    Enhanced customer search API that returns customers based on store
    or returns common/recent customers
    """
    query = request.GET.get('q', '')
    store_id = request.GET.get('store_id', '')
    limit = int(request.GET.get('limit', 10))

    # Base queryset - active customers only
    queryset = Customer.objects.filter(is_active=True)

    if query:
        # Search by name, phone, email, or customer ID
        queryset = queryset.filter(
            Q(name__icontains=query) |
            Q(phone__icontains=query) |
            Q(email__icontains=query) |
            Q(customer_id__icontains=query)
        )
    else:
        # If no search query, return recent/common customers
        # You can customize this logic based on your needs

        # Option 1: Get customers who have made purchases at this store
        if store_id:
            from sales.models import Sale  # Import your Sale model
            recent_customer_ids = Sale.objects.filter(
                store_id=store_id
            ).values_list('customer_id', flat=True).distinct()[:limit]

            queryset = queryset.filter(id__in=recent_customer_ids)

        # Option 2: Get most recent customers overall
        if not queryset.exists():
            queryset = Customer.objects.filter(
                is_active=True
            ).order_by('-created_at')

    # Apply limit
    customers = queryset[:limit]

    # Serialize customer data
    data = {
        'customers': [
            {
                'id': customer.id,
                'name': customer.name,
                'phone': customer.phone or '',
                'email': customer.email or '',
                'customer_id': customer.customer_id,
                'customer_type': customer.get_customer_type_display(),
                'tin': customer.tin or '',
                'is_vat_registered': customer.is_vat_registered,
                'efris_status': customer.efris_status,
                'avatar': customer.name[0].upper() if customer.name else 'C',
            }
            for customer in customers
        ],
        'total': queryset.count()
    }

    return JsonResponse(data)


@login_required
@permission_required('customers.view_customer',raise_exception=True)
def get_store_customers(request):
    """
    Get customers associated with a specific store
    Based on purchase history
    """
    store_id = request.GET.get('store_id')
    limit = int(request.GET.get('limit', 20))

    if not store_id:
        return JsonResponse({'customers': [], 'total': 0})

    try:
        from sales.models import Sale

        # Get customers who have purchased from this store
        customer_ids = Sale.objects.filter(
            store_id=store_id
        ).values_list('customer_id', flat=True).distinct()

        customers = Customer.objects.filter(
            id__in=customer_ids,
            is_active=True
        ).annotate(
            last_purchase=models.Max('sale__created_at')
        ).order_by('-last_purchase')[:limit]

        data = {
            'customers': [
                {
                    'id': customer.id,
                    'name': customer.name,
                    'phone': customer.phone or '',
                    'email': customer.email or '',
                    'customer_id': customer.customer_id,
                    'customer_type': customer.get_customer_type_display(),
                    'avatar': customer.name[0].upper() if customer.name else 'C',
                    'last_purchase': customer.last_purchase.strftime('%Y-%m-%d') if hasattr(customer,
                                                                                            'last_purchase') and customer.last_purchase else None,
                }
                for customer in customers
            ],
            'total': customers.count()
        }

        return JsonResponse(data)

    except Exception as e:
        return JsonResponse({'error': str(e), 'customers': [], 'total': 0})



class CustomerViewSet(viewsets.ModelViewSet):
    queryset = Customer.objects.all()
    serializer_class = CustomerSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        # Add store filtering
        store_id = self.request.query_params.get('store_id')
        # Add credit status filtering
        credit_status = self.request.query_params.get('credit_status')

        if store_id:
            queryset = queryset.filter(store_id=store_id)
        if credit_status:
            queryset = queryset.filter(credit_status=credit_status)

        # Keep existing filters
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

    @action(detail=True, methods=['post'])
    def update_credit_status(self, request, pk=None):
        """Manually update credit status and balance"""
        customer = self.get_object()
        customer.update_credit_balance()

        return Response({
            'success': True,
            'message': 'Credit status updated',
            'credit_balance': customer.credit_balance,
            'credit_available': customer.credit_available,
            'credit_status': customer.credit_status
        })

    @action(detail=True, methods=['post'])
    def check_credit(self, request, pk=None):
        """Check if customer can make a credit purchase"""
        customer = self.get_object()
        amount = Decimal(request.data.get('amount', 0))

        can_purchase, reason = customer.check_credit_limit(amount)

        return Response({
            'can_purchase': can_purchase,
            'reason': reason,
            'available_credit': customer.credit_available,
            'requested_amount': amount,
            'new_balance': customer.credit_balance + amount if can_purchase else None
        })

    @action(detail=True, methods=['post'])
    def adjust_credit_limit(self, request, pk=None):
        """Adjust customer credit limit"""
        customer = self.get_object()
        new_limit = Decimal(request.data.get('credit_limit', 0))
        reason = request.data.get('reason', '')

        old_limit = customer.credit_limit
        customer.credit_limit = new_limit
        customer.save()

        # Log this change in credit statement
        if hasattr(customer, 'credit_statements'):
            CustomerCreditStatement.objects.create(
                customer=customer,
                transaction_type='ADJUSTMENT',
                amount=new_limit - old_limit,
                balance_before=old_limit,
                balance_after=new_limit,
                description=f"Credit limit adjusted: {old_limit} → {new_limit}. Reason: {reason}",
                created_by=request.user
            )

        return Response({
            'success': True,
            'old_limit': old_limit,
            'new_limit': new_limit,
            'credit_available': customer.credit_available
        })

    @action(detail=False, methods=['get'])
    def credit_report(self, request):
        """Generate credit report for customers"""
        queryset = self.filter_queryset(self.get_queryset())

        report_data = queryset.values(
            'id', 'name', 'phone', 'credit_limit',
            'credit_balance', 'credit_available', 'credit_status',
            'allow_credit', 'has_overdue_invoices'
        ).order_by('-credit_balance')

        summary = {
            'total_customers': queryset.count(),
            'total_credit_limit': sum(c['credit_limit'] for c in report_data),
            'total_credit_balance': sum(c['credit_balance'] for c in report_data),
            'customers_over_limit': sum(1 for c in report_data if c['credit_balance'] > c['credit_limit']),
            'customers_with_overdue': sum(1 for c in report_data if c['has_overdue_invoices']),
        }

        return Response({
            'summary': summary,
            'customers': list(report_data)
        })


class CustomerCreditReportView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """Credit report view for customers"""
    template_name = 'customers/credit_report.html'
    permission_required = 'customers.view_customer'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Filter parameters
        store_id = self.request.GET.get('store_id')
        credit_status = self.request.GET.get('credit_status')

        queryset = Customer.objects.filter(
            is_active=True,
            allow_credit=True
        )

        if store_id:
            queryset = queryset.filter(store_id=store_id)
        if credit_status:
            queryset = queryset.filter(credit_status=credit_status)

        # Calculate statistics
        stats = {
            'total_customers': queryset.count(),
            'total_credit_limit': queryset.aggregate(Sum('credit_limit'))['credit_limit__sum'] or 0,
            'total_credit_balance': queryset.aggregate(Sum('credit_balance'))['credit_balance__sum'] or 0,
            'customers_over_limit': queryset.filter(credit_balance__gt=models.F('credit_limit')).count(),
            'customers_with_overdue': sum(1 for c in queryset if c.has_overdue_invoices),
        }

        context.update({
            'customers': queryset,
            'stats': stats,
            'filter_store': store_id,
            'filter_status': credit_status,
        })

        return context


@login_required
def export_credit_report(request):
    """Export credit report to CSV"""
    customers = Customer.objects.filter(
        is_active=True,
        allow_credit=True
    ).select_related('store')

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="credit_report_{datetime.now().strftime("%Y%m%d")}.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Customer ID', 'Name', 'Phone', 'Email', 'Store',
        'Credit Limit', 'Credit Balance', 'Credit Available',
        'Credit Status', 'Has Overdue Invoices', 'Overdue Amount',
        'Credit Days', 'Last Credit Review'
    ])

    for customer in customers:
        writer.writerow([
            customer.customer_id,
            customer.name,
            customer.phone,
            customer.email,
            customer.store.name if customer.store else '',
            customer.credit_limit,
            customer.credit_balance,
            customer.credit_available,
            customer.get_credit_status_display(),
            'Yes' if customer.has_overdue_invoices else 'No',
            customer.overdue_amount,
            customer.credit_days,
            customer.last_credit_review.strftime('%Y-%m-%d') if customer.last_credit_review else '',
        ])

    return response

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
            Customer.objects.select_related('store').prefetch_related(
                'groups', 'notes__author', 'efris_syncs', 'credit_statements'
            ),
            pk=self.kwargs['pk']
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        customer = self.get_object()

        context['note_form'] = CustomerNoteForm()
        context['notes'] = customer.notes.select_related('author').order_by('-created_at')[:10]
        context['efris_form'] = EFRISSyncForm()
        context['efris_syncs'] = customer.efris_syncs.all()[:10]

        # Credit information
        from sales.models import Sale
        context['credit_statements'] = customer.credit_statements.all()[:20]
        context['overdue_invoices'] = Sale.objects.filter(
            customer=customer,
            payment_status='OVERDUE'
        )[:10]
        context['can_purchase_on_credit'], context['credit_message'] = customer.can_purchase_on_credit

        # eFRIS status information
        context['efris_status'] = {
            'can_sync': customer.can_sync_to_efris,
            'is_registered': customer.is_efris_registered,
            'status_display': customer.get_efris_status_display(),
            'last_sync': customer.efris_last_sync,
            'sync_error': customer.efris_sync_error,
        }

        return context


@login_required
@permission_required('customers.view_customer', raise_exception=True)
def store_customer_credit_info(request, store_id):
    """Get credit information for all customers of a store"""
    customers = Customer.objects.filter(
        store_id=store_id,
        is_active=True,
        allow_credit=True
    ).select_related('store')

    data = {
        'customers': [
            {
                'id': c.id,
                'name': c.name,
                'phone': c.phone,
                'credit_limit': c.credit_limit,
                'credit_balance': c.credit_balance,
                'credit_available': c.credit_available,
                'credit_status': c.credit_status,
                'has_overdue': c.has_overdue_invoices,
                'overdue_amount': c.overdue_amount,
            }
            for c in customers
        ]
    }

    return JsonResponse(data)


@login_required
@require_http_methods(["POST"])
def bulk_update_credit_limits(request):
    """Bulk update credit limits for multiple customers"""
    if not request.user.has_perm('customers.change_customer'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    try:
        data = json.loads(request.body)
        updates = data.get('updates', [])

        results = {'success': [], 'failed': []}

        for update in updates:
            try:
                customer = Customer.objects.get(id=update['customer_id'])
                old_limit = customer.credit_limit
                new_limit = Decimal(str(update['new_limit']))
                reason = update.get('reason', 'Bulk update')

                customer.credit_limit = new_limit
                customer.save()

                # Log the change
                CustomerCreditStatement.objects.create(
                    customer=customer,
                    transaction_type='ADJUSTMENT',
                    amount=new_limit - old_limit,
                    balance_before=old_limit,
                    balance_after=new_limit,
                    description=f"Bulk credit limit update: {old_limit} → {new_limit}. Reason: {reason}",
                    created_by=request.user,
                    reference_number=f"BULK_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                )

                results['success'].append({
                    'customer_id': customer.id,
                    'name': customer.name,
                    'old_limit': old_limit,
                    'new_limit': new_limit
                })

            except Exception as e:
                results['failed'].append({
                    'customer_id': update.get('customer_id'),
                    'error': str(e)
                })

        return JsonResponse(results)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


class CustomerCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """Create new customer with validation"""
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

        messages.success(self.request, _('Customer created successfully.'))
        return response

    def form_invalid(self, form):
        messages.error(self.request, _('Please correct the errors below.'))
        return super().form_invalid(form)


class CustomerUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Update existing customer"""
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
        messages.success(self.request, _('Customer updated successfully.'))
        return response


@login_required
@require_http_methods(["POST"])
def sync_customer_to_efris(request, pk):
    """Sync individual customer to eFRIS"""
    customer = get_object_or_404(Customer, pk=pk)

    # Use the updated validation from model
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


def validate_customer_data(customer_type, name, phone, tin=None):
    """
    Validate customer data according to new requirements
    Returns: (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Customer name is required"

    if not phone or not phone.strip():
        return False, "Phone number is required"

    if customer_type in ['BUSINESS', 'GOVERNMENT', 'NGO']:
        if not tin or not tin.strip():
            return False, f"TIN is required for {customer_type} customers"

    return True, "Valid"


@login_required
@permission_required('customers.add_customer', raise_exception=True)
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
            # Filter customers who can be synced using updated validation
            eligible_customers = [
                c for c in customers
                if c.can_sync_to_efris and c.efris_status in ['NOT_REGISTERED', 'FAILED']
            ]

            if not eligible_customers:
                messages.warning(request, _('No customers eligible for eFRIS sync.'))
                return redirect('customers:customer_list')

            try:
                service = EFRISCustomerService()
                success_count = 0
                error_count = 0

                for customer in eligible_customers:
                    try:
                        result = service.register_customer(customer)
                        if result['success']:
                            success_count += 1
                        else:
                            error_count += 1
                    except Exception as e:
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

        elif action == 'update_credit_limit':
            # New action to bulk update credit limits
            try:
                credit_limit = form.cleaned_data.get('credit_limit')
                if credit_limit is not None:
                    customers.update(credit_limit=credit_limit)

                    # Create credit statements for each customer
                    for customer in customers:
                        CustomerCreditStatement.objects.create(
                            customer=customer,
                            transaction_type='ADJUSTMENT',
                            amount=credit_limit - customer.credit_limit,
                            balance_before=customer.credit_limit,
                            balance_after=credit_limit,
                            description=f"Bulk credit limit update to {credit_limit}",
                            created_by=request.user,
                            reference_number=f"BULK_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                        )

                    messages.success(
                        request,
                        _('Credit limits updated for %(count)d customers.') % {'count': customers.count()}
                    )
            except Exception as e:
                messages.error(
                    request,
                    _('Error updating credit limits: %(error)s') % {'error': str(e)}
                )

        elif action == 'enable_credit':
            customers.update(allow_credit=True)
            messages.success(
                request,
                _('Credit enabled for %(count)d customers.') % {'count': customers.count()}
            )

        elif action == 'disable_credit':
            customers.update(allow_credit=False)
            messages.success(
                request,
                _('Credit disabled for %(count)d customers.') % {'count': customers.count()}
            )

    else:
        # Form validation failed
        messages.error(request, _('Invalid form data. Please check your selections.'))

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
@permission_required('customers.add_customer', raise_exception=True)
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
                        customer_type = row.get('customer_type', 'INDIVIDUAL')
                        name = row.get('name', '').strip()
                        phone = row.get('phone', '').strip()
                        tin = row.get('tin', '').strip()

                        # Validate required fields based on customer type
                        if not name:
                            raise ValueError("Customer name is required")
                        if not phone:
                            raise ValueError("Phone number is required")

                        # Business/Government/NGO validation
                        if customer_type in ['BUSINESS', 'GOVERNMENT', 'NGO']:
                            if not tin:
                                raise ValueError(f"TIN is required for {customer_type} customers")

                        data = {
                            'name': name,
                            'customer_type': customer_type,
                            'email': row.get('email', '').strip(),
                            'phone': phone,
                            'tin': tin,
                            'nin': row.get('nin', '').strip().upper(),
                            'brn': row.get('brn', '').strip().upper(),
                            'physical_address': row.get('physical_address', '').strip(),
                            'district': row.get('district', '').strip(),
                            'country': row.get('country', 'Uganda').strip(),
                            'store_id': form.cleaned_data.get('store'),
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
                                     _('Import completed with errors: %(errors)s') % {'errors': ', '.join(errors[:5])})

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