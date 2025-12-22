from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib.auth.decorators import permission_required
from django.urls import reverse_lazy, reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import (ListView, DetailView, CreateView, UpdateView, DeleteView)
from django.views import View
import csv
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.db.models import Sum, Count, Avg, F, Q
from decimal import Decimal
from datetime import timedelta
from sales.models import Sale, SaleItem
from accounts.models import CustomUser
from inventory.models import Stock
from stores.models import Store, DeviceOperatorLog
from company.models import Company
from company.forms import SearchForm
from company.mixins import CompanyFieldLockMixin


@login_required
@permission_required('stores.view_store', raise_exception=True)
@require_http_methods(["GET"])
def branch_analytics(request, **kwargs):
    """
    Store analytics view with backward compatibility for branch_id parameter.
    """
    # Handle both store_id and branch_id parameters
    store_identifier = kwargs.get('store_id') or kwargs.get('branch_id')

    if not store_identifier:
        return JsonResponse({'error': 'Store ID is required'}, status=400)

    store = get_object_or_404(Store, id=store_identifier)

    # Permission check
    if not request.user.has_perm('stores.view_store'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    today = timezone.now().date()
    thirty_days_ago = today - timedelta(days=30)
    sixty_days_ago = today - timedelta(days=60)

    # For company-wide analytics, get all stores for the company
    company = store.company
    stores = Store.objects.filter(company=company, is_active=True)
    store_ids = stores.values_list('id', flat=True)

    try:
        # Current period (last 30 days) revenue
        total_revenue = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date__gte=thirty_days_ago,
            is_voided=False,
            status__in=['COMPLETED', 'PAID']
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

        # Previous period (30-60 days ago) revenue
        prev_revenue = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date__range=[sixty_days_ago, thirty_days_ago],
            is_voided=False,
            status__in=['COMPLETED', 'PAID']
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

        # Calculate revenue growth
        revenue_growth = 0
        if prev_revenue > 0:
            revenue_growth = round(((total_revenue - prev_revenue) / prev_revenue) * 100, 1)

        # Current period sales count
        total_sales = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date__gte=thirty_days_ago,
            is_voided=False,
            status__in=['COMPLETED', 'PAID']
        ).count()

        # Previous period sales count
        prev_sales = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date__range=[sixty_days_ago, thirty_days_ago],
            is_voided=False,
            status__in=['COMPLETED', 'PAID']
        ).count()

        # Calculate sales growth
        sales_growth = 0
        if prev_sales > 0:
            sales_growth = round(((total_sales - prev_sales) / prev_sales) * 100, 1)

        # Current period unique customers
        total_customers = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date__gte=thirty_days_ago,
            customer__isnull=False,
            is_voided=False,
            status__in=['COMPLETED', 'PAID']
        ).values('customer').distinct().count()

        # Previous period unique customers
        prev_customers = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date__range=[sixty_days_ago, thirty_days_ago],
            customer__isnull=False,
            is_voided=False,
            status__in=['COMPLETED', 'PAID']
        ).values('customer').distinct().count()

        # Calculate customer growth
        customer_growth = 0
        if prev_customers > 0:
            customer_growth = round(((total_customers - prev_customers) / prev_customers) * 100, 1)

        # Total products across all stores
        total_products = Stock.objects.filter(
            store__in=stores
        ).values('product').distinct().count()

        # Low stock items
        low_stock_items = Stock.objects.filter(
            store__in=stores,
            quantity__lte=F('low_stock_threshold')
        ).count()

    except Exception as e:
        # Fallback to zero values if queries fail
        total_revenue = Decimal('0')
        revenue_growth = 0
        total_sales = 0
        sales_growth = 0
        total_customers = 0
        customer_growth = 0
        total_products = 0
        low_stock_items = 0

    # Generate revenue data for chart (last 7 days)
    revenue_data = generate_revenue_data(store_ids, 7)

    # Store performance data
    store_performance_data = generate_store_performance_data(stores)

    # Store details for performance table
    store_details = generate_store_details(stores)

    return JsonResponse({
        'metrics': {
            'total_revenue': float(total_revenue),
            'revenue_growth': revenue_growth,
            'total_sales': total_sales,
            'sales_growth': sales_growth,
            'total_customers': total_customers,
            'customer_growth': customer_growth,
            'total_products': total_products,
            'low_stock_items': low_stock_items,
        },
        'revenue_data': revenue_data,
        'store_performance': store_performance_data,
        'store_details': store_details,
    })


@login_required
@permission_required('stores.view_store', raise_exception=True)
@require_http_methods(["GET"])
def branch_store_stats(request, **kwargs):
    """
    Return basic statistics for stores.
    Parameter renamed to store_id but maintains backward compatibility.
    """
    store_identifier = kwargs.get('store_id') or kwargs.get('branch_id')

    if not store_identifier:
        return JsonResponse({'error': 'Store ID is required'}, status=400)

    store = get_object_or_404(Store, id=store_identifier)

    if not request.user.has_perm('stores.view_store'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    # Get all stores for the company
    company = store.company
    stores = Store.objects.filter(company=company, is_active=True)

    stores_data = []
    thirty_days_ago = timezone.now().date() - timedelta(days=30)

    for current_store in stores:
        try:
            # Get sales count for each store (last 30 days)
            sales_count = Sale.objects.filter(
                store=current_store,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).count()

        except Exception:
            sales_count = 0

        stores_data.append({
            'id': current_store.id,
            'name': current_store.name,
            'sales_count': sales_count,
        })

    return JsonResponse({
        'stores': stores_data
    })


@login_required
@permission_required('stores.view_store', raise_exception=True)
@require_http_methods(["GET"])
def branch_performance(request, **kwargs):
    """Return performance data including top performers and stores needing attention."""
    store_identifier = kwargs.get('store_id') or kwargs.get('branch_id')

    if not store_identifier:
        return JsonResponse({'error': 'Store ID is required'}, status=400)

    store = get_object_or_404(Store, id=store_identifier)

    if not request.user.has_perm('stores.view_store'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    # Get all stores for the company
    company = store.company
    stores = Store.objects.filter(company=company, is_active=True)
    thirty_days_ago = timezone.now().date() - timedelta(days=30)

    # Generate top performing stores
    top_stores = []
    attention_stores = []

    for current_store in stores:
        try:
            # Calculate actual performance metrics
            revenue_data = Sale.objects.filter(
                store=current_store,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                total_revenue=Sum('total_amount'),
                total_sales=Count('id'),
                avg_sale=Avg('total_amount')
            )

            revenue = float(revenue_data['total_revenue'] or 0)
            sales_count = revenue_data['total_sales'] or 0
            avg_sale_amount = float(revenue_data['avg_sale'] or 0)

            # Calculate performance score based on multiple factors
            performance_score = 0
            if sales_count > 0:
                # Base score on sales volume (0-40 points)
                sales_score = min(40, (sales_count / 10) * 5)

                # Add revenue component (0-40 points)
                revenue_score = min(40, (revenue / 100000) * 10)

                # Add average sale amount component (0-20 points)
                avg_score = min(20, (avg_sale_amount / 10000) * 5)

                performance_score = sales_score + revenue_score + avg_score

            performance_score = min(100, performance_score)

            store_data = {
                'id': current_store.id,
                'name': current_store.name,
                'revenue': revenue,
                'sales_count': sales_count,
                'avg_sale_amount': avg_sale_amount,
                'performance_score': round(performance_score, 1),
            }

            # Determine if store needs attention
            if performance_score < 30:
                attention_stores.append({
                    **store_data,
                    'issue': 'low_performance',
                    'issue_description': 'Below average performance metrics'
                })
            elif sales_count == 0:
                attention_stores.append({
                    **store_data,
                    'issue': 'no_sales',
                    'issue_description': 'No sales recorded in the last 30 days'
                })
            elif not current_store.is_active:
                attention_stores.append({
                    **store_data,
                    'issue': 'inactive',
                    'issue_description': 'Store is currently inactive'
                })
            else:
                top_stores.append(store_data)

        except Exception as e:
            attention_stores.append({
                'id': current_store.id,
                'name': current_store.name,
                'revenue': 0,
                'sales_count': 0,
                'avg_sale_amount': 0,
                'performance_score': 0,
                'issue': 'data_error',
                'issue_description': f'Error retrieving data: {str(e)}'
            })

    # Sort top stores by performance score
    top_stores.sort(key=lambda x: x['performance_score'], reverse=True)
    top_stores = top_stores[:5]

    # Generate trend data
    trend_data = generate_performance_trend_data(stores)

    return JsonResponse({
        'top_stores': top_stores,
        'attention_stores': attention_stores,
        'trend_data': trend_data,
    })


@login_required
@permission_required('accounts.add_customuser', raise_exception=True)
@require_http_methods(["GET"])
def branch_staff_overview(request, **kwargs):
    """Return staff overview data."""
    # Handle both store_id and branch_id parameters
    store_identifier = kwargs.get('store_id') or kwargs.get('branch_id')

    if not store_identifier:
        return JsonResponse({'error': 'Store ID is required'}, status=400)

    store = get_object_or_404(Store, id=store_identifier)

    if not request.user.has_perm('stores.view_store'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    # Get all stores in the company
    company = store.company
    stores = Store.objects.filter(company=company, is_active=True)

    # Get all staff members across all stores
    staff_ids = set()
    for current_store in stores:
        staff_ids.update(current_store.staff.values_list('id', flat=True))

    # Get staff statistics
    total_staff = len(staff_ids)

    if staff_ids:
        staff_queryset = CustomUser.objects.filter(
            id__in=staff_ids,
            is_hidden=False
        )

        active_staff = staff_queryset.filter(is_active=True).count()

        # FIXED: Access role name through group relationship
        # The Role model has a one-to-one relationship with Group
        # So we need to access: primary_role -> group -> name
        managers = staff_queryset.filter(
            primary_role__group__name__in=['Manager', 'Company Admin', 'Administrator', 'Store Manager'],
            is_active=True
        ).count()

        # For cashiers
        cashiers = staff_queryset.filter(
            primary_role__group__name='Cashier',
            is_active=True
        ).count()

        # Get recent activities from device logs
        recent_activities = []
        try:
            logs = DeviceOperatorLog.objects.filter(
                user_id__in=staff_ids,
                store__in=stores
            ).select_related(
                'user', 'store', 'device'
            ).order_by('-timestamp')[:10]

            for log in logs:
                time_diff = timezone.now() - log.timestamp
                if time_diff.days > 0:
                    time_ago = f"{time_diff.days} day{'s' if time_diff.days != 1 else ''} ago"
                elif time_diff.seconds > 3600:
                    hours = time_diff.seconds // 3600
                    time_ago = f"{hours} hour{'s' if hours != 1 else ''} ago"
                else:
                    minutes = max(1, time_diff.seconds // 60)
                    time_ago = f"{minutes} minute{'s' if minutes != 1 else ''} ago"

                recent_activities.append({
                    'user_name': log.user.get_full_name() or log.user.username,
                    'action': log.action.replace('_', ' ').title(),
                    'store_name': log.store.name,
                    'time_ago': time_ago,
                    'avatar': log.user.avatar.url if log.user.avatar else None,
                })

        except Exception as e:
            print(f"Error getting recent activities: {e}")
            recent_activities = []
    else:
        active_staff = 0
        managers = 0
        cashiers = 0
        recent_activities = []

    return JsonResponse({
        'total_staff': total_staff,
        'active_staff': active_staff,
        'managers': managers,
        'cashiers': cashiers,
        'recent_activities': recent_activities,
    })

@login_required
@permission_required('stores.view_store',raise_exception=True)
@require_http_methods(["GET"])
def branch_revenue_data(request, store_id):
    """Return revenue data for different time ranges."""
    store = get_object_or_404(Store, id=store_id)

    if not request.user.has_perm('stores.view_store'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    range_param = request.GET.get('range', '7d')
    try:
        days = int(range_param.replace('d', ''))
    except ValueError:
        days = 7

    # Get all stores for the company
    company = store.company
    stores = Store.objects.filter(company=company, is_active=True)
    store_ids = stores.values_list('id', flat=True)

    revenue_data = generate_revenue_data(store_ids, days)

    return JsonResponse(revenue_data)


# Helper functions

def generate_revenue_data(store_ids, days=7):
    """Generate revenue data for the specified number of days."""
    labels = []
    values = []

    for i in range(days):
        date = timezone.now().date() - timedelta(days=days - 1 - i)
        labels.append(date.strftime('%m/%d'))

        try:
            daily_revenue = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date=date,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(total=Sum('total_amount'))['total'] or 0

            values.append(float(daily_revenue))
        except Exception:
            values.append(0)

    return {
        'labels': labels,
        'values': values
    }


def generate_store_performance_data(stores):
    """Generate pie chart data for store performance comparison."""
    labels = []
    values = []
    thirty_days_ago = timezone.now().date() - timedelta(days=30)

    for store in stores[:5]:
        labels.append(store.name)

        try:
            performance_value = Sale.objects.filter(
                store=store,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(total=Sum('total_amount'))['total'] or 0

            values.append(float(performance_value))
        except Exception:
            values.append(0)

    return {
        'labels': labels,
        'values': values
    }


def generate_store_details(stores):
    """Generate detailed performance data for each store."""
    store_details = []
    thirty_days_ago = timezone.now().date() - timedelta(days=30)
    sixty_days_ago = timezone.now().date() - timedelta(days=60)

    for store in stores:
        try:
            # Current period metrics
            current_metrics = Sale.objects.filter(
                store=store,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                revenue=Sum('total_amount'),
                sales_count=Count('id'),
                avg_sale=Avg('total_amount')
            )

            # Previous period metrics
            prev_metrics = Sale.objects.filter(
                store=store,
                created_at__date__range=[sixty_days_ago, thirty_days_ago],
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                revenue=Sum('total_amount'),
                sales_count=Count('id')
            )

            revenue_30d = float(current_metrics['revenue'] or 0)
            prev_revenue = float(prev_metrics['revenue'] or 0)
            sales_count = current_metrics['sales_count'] or 0
            prev_sales = prev_metrics['sales_count'] or 0
            avg_sale = float(current_metrics['avg_sale'] or 0)

            # Calculate growth rates
            revenue_growth = 0
            if prev_revenue > 0:
                revenue_growth = round(((revenue_30d - prev_revenue) / prev_revenue) * 100, 1)

            sales_growth = 0
            if prev_sales > 0:
                sales_growth = round(((sales_count - prev_sales) / prev_sales) * 100, 1)

            # Calculate performance score
            performance_score = 0
            if sales_count > 0:
                sales_score = min(40, (sales_count / 10) * 5)
                revenue_score = min(40, (revenue_30d / 100000) * 10)
                avg_score = min(20, (avg_sale / 10000) * 5)
                performance_score = min(100, sales_score + revenue_score + avg_score)

        except Exception:
            revenue_30d = 0
            revenue_growth = 0
            sales_count = 0
            sales_growth = 0
            avg_sale = 0
            performance_score = 0

        store_details.append({
            'id': store.id,
            'name': store.name,
            'code': store.code,
            'logo': store.logo.url if store.logo else None,
            'revenue_30d': revenue_30d,
            'revenue_growth': revenue_growth,
            'sales_count': sales_count,
            'sales_growth': sales_growth,
            'avg_sale': avg_sale,
            'performance_score': round(performance_score, 1),
            'is_active': store.is_active,
            'efris_enabled': store.efris_enabled,
        })

    return store_details


def generate_performance_trend_data(stores):
    """Generate performance trend data for the last 7 days."""
    labels = []
    values = []

    for i in range(7):
        date = timezone.now().date() - timedelta(days=6 - i)
        labels.append(date.strftime('%m/%d'))

        try:
            daily_sales = Sale.objects.filter(
                store__in=stores,
                created_at__date=date,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).count()

            daily_performance = min(100, daily_sales * 2)
            values.append(daily_performance)
        except Exception:
            values.append(0)

    return {
        'labels': labels,
        'values': values
    }


@login_required
@permission_required('stores.view_store',raise_exception=True)
@require_http_methods(["GET"])
def export_branch_data(request, store_id):
    """Export store data as CSV."""
    store = get_object_or_404(Store, id=store_id)

    if not request.user.has_perm('stores.view_store'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="store_{store_id}_data.csv"'

    writer = csv.writer(response)
    writer.writerow(['Company', 'Store', 'Code', 'Revenue (30d)', 'Sales Count (30d)', 'Avg Sale', 'Active'])

    thirty_days_ago = timezone.now().date() - timedelta(days=30)

    # Get all stores for the company
    company = store.company
    stores = Store.objects.filter(company=company)

    for current_store in stores:
        try:
            metrics = Sale.objects.filter(
                store=current_store,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                revenue=Sum('total_amount'),
                sales_count=Count('id'),
                avg_sale=Avg('total_amount')
            )

            revenue = float(metrics['revenue'] or 0)
            sales = metrics['sales_count'] or 0
            avg_sale = float(metrics['avg_sale'] or 0)

        except Exception:
            revenue = 0
            sales = 0
            avg_sale = 0

        writer.writerow([
            company.name,
            current_store.name,
            current_store.code,
            revenue,
            sales,
            avg_sale,
            'Yes' if current_store.is_active else 'No'
        ])

    return response


@login_required
@permission_required('stores.add_store',raise_exception=True)
@require_http_methods(["POST"])
def generate_branch_report(request, store_id):
    """Generate comprehensive store report."""
    store = get_object_or_404(Store, id=store_id)

    if not request.user.has_perm('stores.view_store'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    thirty_days_ago = timezone.now().date() - timedelta(days=30)

    # Get all stores for the company
    company = store.company
    stores = Store.objects.filter(company=company)

    # Collect data for the report
    report_data = {
        'store': store,
        'company': company,
        'generated_date': timezone.now(),
        'period': f"{thirty_days_ago} to {timezone.now().date()}",
        'stores': []
    }

    for current_store in stores:
        try:
            metrics = Sale.objects.filter(
                store=current_store,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                revenue=Sum('total_amount'),
                sales_count=Count('id'),
                avg_sale=Avg('total_amount')
            )

            store_data = {
                'name': current_store.name,
                'code': current_store.code,
                'revenue': float(metrics['revenue'] or 0),
                'sales_count': metrics['sales_count'] or 0,
                'avg_sale': float(metrics['avg_sale'] or 0),
                'is_active': current_store.is_active
            }
            report_data['stores'].append(store_data)

        except Exception:
            continue

    return JsonResponse({
        'status': 'success',
        'message': 'Report data prepared successfully',
        'data': {
            'company_name': company.name,
            'store_name': store.name,
            'total_stores': len(report_data['stores']),
            'total_revenue': sum(s['revenue'] for s in report_data['stores']),
            'total_sales': sum(s['sales_count'] for s in report_data['stores']),
            'period': report_data['period']
        }
    })



class BranchListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """List all stores (backward compatible as branches)."""
    model = Store
    template_name = 'company/branch_list.html'
    context_object_name = 'branches'
    permission_required = 'stores.view_store'
    paginate_by = 25

    def get_queryset(self):
        queryset = Store.objects.select_related('company')

        # Company filter
        company_id = self.request.GET.get('company')
        if company_id:
            queryset = queryset.filter(company_id=company_id)

        # Search functionality
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(code__icontains=search_query) |
                Q(location__icontains=search_query) |
                Q(company__name__icontains=search_query)
            )

        # Active filter
        is_active = self.request.GET.get('is_active')
        if is_active:
            queryset = queryset.filter(is_active=is_active == 'true')

        return queryset.order_by('company__name', 'name')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = SearchForm(self.request.GET)
        context['companies'] = Company.objects.filter(is_active=True)
        context['stores'] = context['branches']
        return context


class BranchDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """Store detail view (backward compatible as branch). Shows company-wide analytics."""
    model = Store
    template_name = 'company/branch_detail.html'
    context_object_name = 'branch'
    permission_required = 'stores.view_store'

    def get_queryset(self):
        return Store.objects.select_related('company').prefetch_related('staff', 'devices')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.get_object()

        # Provide both 'store' and 'branch' for backward compatibility
        context['store'] = store
        context['company'] = store.company

        # Get all stores/branches in the same company
        # These are sibling stores, not child stores
        all_stores = Store.objects.filter(
            company=store.company
        ).select_related('company').prefetch_related('staff', 'devices').order_by('-is_main_branch', 'name')

        # Attach stores to the branch object so template can use branch.stores.all
        store.stores = all_stores

        # Store counts
        context["active_store_count"] = all_stores.filter(is_active=True).count()
        context['total_stores'] = all_stores.count()

        # Get basic metrics for quick stats
        thirty_days_ago = timezone.now().date() - timedelta(days=30)

        # Company-wide revenue (all stores)
        context['company_revenue'] = Sale.objects.filter(
            store__company=store.company,
            created_at__date__gte=thirty_days_ago,
            is_voided=False,
            status__in=['COMPLETED', 'PAID']
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

        # Company-wide sales count
        context['company_sales_count'] = Sale.objects.filter(
            store__company=store.company,
            created_at__date__gte=thirty_days_ago,
            is_voided=False,
            status__in=['COMPLETED', 'PAID']
        ).count()

        return context


class BranchCreateView(CompanyFieldLockMixin, LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Store
    template_name = 'company/branch_form.html'
    permission_required = 'stores.add_store'
    fields = ['company', 'name', 'code', 'location', ...]
    success_url = reverse_lazy('companies:branch_list')

    def form_valid(self, form):
        messages.success(self.request, _('Store created successfully.'))
        return super().form_valid(form)


class BranchUpdateView(CompanyFieldLockMixin, LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Store
    template_name = 'company/branch_form.html'
    permission_required = 'stores.change_store'
    fields = [
        'company', 'name', 'code', 'location', 'physical_address',
        'phone', 'email', 'tin', 'nin', 'is_main_branch',
        'is_active', 'store_type', 'manager_name', 'manager_phone',
        'allows_sales', 'allows_inventory'
    ]
    success_url = reverse_lazy('companies:branch_list')

    def form_valid(self, form):
        messages.success(self.request, _('Store updated successfully.'))
        return super().form_valid(form)

class BranchDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    """Delete store (backward compatible as branch)."""
    model = Store
    template_name = 'company/branch_confirm_delete.html'
    permission_required = 'stores.delete_store'
    success_url = reverse_lazy('companies:branch_list')

    def delete(self, request, *args, **kwargs):
        store_name = self.get_object().name
        result = super().delete(request, *args, **kwargs)
        messages.success(request, _('Store "%s" deleted successfully.') % store_name)
        return result


# AJAX Views

class GetBranchesAjaxView(LoginRequiredMixin, View):
    """Get stores for a specific company via AJAX (backward compatible)."""

    def get(self, request, *args, **kwargs):
        company_id = request.GET.get('company_id')
        if company_id:
            branches = Store.objects.filter(company_id=company_id).values('id', 'name')
            return JsonResponse({'branches': list(branches)})
        return JsonResponse({'branches': []})


class GetCompanyBranchesView(LoginRequiredMixin, View):
    """Get stores for a company in JSON format (backward compatible)."""

    def get(self, request, *args, **kwargs):
        company_id = request.GET.get('company_id')
        branches = Store.objects.filter(company_id=company_id).values('id', 'name', 'code')
        return JsonResponse({'branches': list(branches)})


class ExportBranchesView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Export stores to CSV (backward compatible as branches)."""
    permission_required = 'stores.view_store'

    def get(self, request, *args, **kwargs):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="branches.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Company', 'Branch Name', 'Code', 'Location', 'Phone', 'Email',
            'TIN', 'Is Active', 'Is Main Branch', 'Created At'
        ])

        branches = Store.objects.select_related('company')

        # Apply filters
        company_id = request.GET.get('company')
        if company_id:
            branches = branches.filter(company_id=company_id)

        search_query = request.GET.get('q')
        if search_query:
            branches = branches.filter(
                Q(name__icontains=search_query) |
                Q(code__icontains=search_query) |
                Q(location__icontains=search_query)
            )

        for branch in branches:
            writer.writerow([
                branch.company.name if branch.company else '',
                branch.name,
                branch.code or '',
                branch.location or '',
                branch.phone or '',
                branch.email or '',
                branch.tin or '',
                'Yes' if branch.is_active else 'No',
                'Yes' if branch.is_main_branch else 'No',
                branch.created_at.strftime('%Y-%m-%d %H:%M:%S') if hasattr(branch, 'created_at') else '',
            ])

        return response