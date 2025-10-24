from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
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


@login_required
@require_http_methods(["GET"])
def branch_analytics(request, branch_id):
    """
    Branch analytics view - now using Store model.
    branch_id parameter kept for backward compatibility with URLs.
    """
    # Get store (previously branch)
    store = get_object_or_404(Store, id=branch_id)

    # Updated permission check
    if not request.user.has_perm('stores.view_store'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    today = timezone.now().date()
    thirty_days_ago = today - timedelta(days=30)
    sixty_days_ago = today - timedelta(days=60)
    seven_days_ago = today - timedelta(days=7)

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
            is_completed=True
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

        # Previous period (30-60 days ago) revenue
        prev_revenue = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date__range=[sixty_days_ago, thirty_days_ago],
            is_voided=False,
            is_completed=True
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
            is_completed=True
        ).count()

        # Previous period sales count
        prev_sales = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date__range=[sixty_days_ago, thirty_days_ago],
            is_voided=False,
            is_completed=True
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
            is_completed=True
        ).values('customer').distinct().count()

        # Previous period unique customers
        prev_customers = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date__range=[sixty_days_ago, thirty_days_ago],
            customer__isnull=False,
            is_voided=False,
            is_completed=True
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
@require_http_methods(["GET"])
def branch_store_stats(request, branch_id):
    """
    Return basic statistics for stores.
    For company-wide view: pass main store's ID
    For single store view: pass that store's ID
    """
    store = get_object_or_404(Store, id=branch_id)

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
                is_completed=True
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
@require_http_methods(["GET"])
def branch_performance(request, branch_id):
    """Return performance data including top performers and stores needing attention."""
    store = get_object_or_404(Store, id=branch_id)

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
                is_completed=True
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
                sales_score = min(40, (sales_count / 10) * 5)  # 10 sales = 5 points, max 40

                # Add revenue component (0-40 points)
                revenue_score = min(40, (revenue / 100000) * 10)  # 100k = 10 points, max 40

                # Add average sale amount component (0-20 points)
                avg_score = min(20, (avg_sale_amount / 10000) * 5)  # 10k avg = 5 points, max 20

                performance_score = sales_score + revenue_score + avg_score

            performance_score = min(100, performance_score)  # Cap at 100

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
            # Handle case where there's an error with queries
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
    top_stores = top_stores[:5]  # Top 5 performers

    # Generate trend data
    trend_data = generate_performance_trend_data(stores)

    return JsonResponse({
        'top_stores': top_stores,
        'attention_stores': attention_stores,
        'trend_data': trend_data,
    })


@login_required
@require_http_methods(["GET"])
def branch_staff_overview(request, branch_id):
    """Return staff overview data."""
    store = get_object_or_404(Store, id=branch_id)

    if not request.user.has_perm('stores.view_store'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    # Get all stores in the company
    company = store.company
    stores = Store.objects.filter(company=company, is_active=True)

    # Get all staff members across all stores
    staff_ids = []
    for current_store in stores:
        staff_ids.extend(current_store.staff.values_list('id', flat=True))

    # Remove duplicates (staff might work in multiple stores)
    unique_staff_ids = list(set(staff_ids))

    # Get staff statistics
    total_staff = len(unique_staff_ids)

    if unique_staff_ids:
        staff_queryset = CustomUser.objects.filter(
            id__in=unique_staff_ids,
            is_hidden=False  # Exclude hidden users
        )

        active_staff = staff_queryset.filter(is_active=True).count()
        managers = staff_queryset.filter(
            user_type__in=['MANAGER', 'COMPANY_ADMIN'],
            is_active=True
        ).count()
        cashiers = staff_queryset.filter(
            user_type='CASHIER',
            is_active=True
        ).count()

        # Get recent activities from device logs
        recent_activities = []
        try:
            # Get recent device operator logs for stores
            logs = DeviceOperatorLog.objects.filter(
                user_id__in=unique_staff_ids,
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
@require_http_methods(["GET"])
def branch_revenue_data(request, branch_id):
    """Return revenue data for different time ranges."""
    store = get_object_or_404(Store, id=branch_id)

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

        # Get actual daily revenue from Sales
        try:
            daily_revenue = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date=date,
                is_voided=False,
                is_completed=True
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

    for store in stores[:5]:  # Top 5 stores for pie chart
        labels.append(store.name)

        try:
            # Get actual performance value based on revenue
            performance_value = Sale.objects.filter(
                store=store,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                is_completed=True
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
                is_completed=True
            ).aggregate(
                revenue=Sum('total_amount'),
                sales_count=Count('id'),
                avg_sale=Avg('total_amount')
            )

            # Previous period metrics for comparison
            prev_metrics = Sale.objects.filter(
                store=store,
                created_at__date__range=[sixty_days_ago, thirty_days_ago],
                is_voided=False,
                is_completed=True
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
            # Calculate daily performance based on total sales across all stores
            daily_sales = Sale.objects.filter(
                store__in=stores,
                created_at__date=date,
                is_voided=False,
                is_completed=True
            ).count()

            # Convert to a performance score (adjust logic as needed)
            daily_performance = min(100, daily_sales * 2)  # 50 sales = 100 performance
            values.append(daily_performance)
        except Exception:
            values.append(0)

    return {
        'labels': labels,
        'values': values
    }

@login_required
@require_http_methods(["GET"])
def export_branch_data(request, branch_id):
    """Export store/branch data as CSV."""
    store = get_object_or_404(Store, id=branch_id)

    if not request.user.has_perm('stores.view_store'):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="store_{branch_id}_data.csv"'

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
                is_completed=True
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
@require_http_methods(["POST"])
def generate_branch_report(request, branch_id):
    """Generate comprehensive store/branch report as PDF."""
    store = get_object_or_404(Store, id=branch_id)

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
                is_completed=True
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


# Class-based views

class BranchListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """
    List all stores (previously branches).
    Template and context names kept for backward compatibility.
    """
    model = Store
    template_name = 'company/branch_list.html'  # Keep same template
    context_object_name = 'branches'  # Keep same context name for template compatibility
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
        context['stores'] = context['branches']  # Add stores alias
        return context


class BranchDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    """Store detail view (previously branch)."""
    model = Store
    template_name = 'company/branch_detail.html'  # Keep same template
    context_object_name = 'branch'  # Keep same context name for template compatibility
    permission_required = 'stores.view_store'

    def get_queryset(self):
        return Store.objects.select_related('company')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        store = self.get_object()

        # Backward compatibility: add store as 'branch'
        context['store'] = store

        # For displaying "other stores" in the same company (like branches under a branch)
        context["active_store_count"] = Store.objects.filter(
            company=store.company,
            is_active=True
        ).count()

        return context


class BranchCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    """Create new store (previously branch)."""
    model = Store
    template_name = 'company/branch_form.html'  # Keep same template
    permission_required = 'stores.add_store'
    # Updated fields for Store model
    fields = [
        'company', 'name', 'code', 'location', 'physical_address',
        'phone', 'email', 'tin', 'nin', 'is_main_branch',
        'is_active', 'store_type', 'manager_name', 'manager_phone'
    ]
    success_url = reverse_lazy('companies:branch_list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        # Restrict company field to only current user's company
        current_user = self.request.user
        if hasattr(current_user, 'company') and current_user.company:
            company = current_user.company
            form.fields['company'].queryset = Company.objects.filter(company_id=company.company_id)
            form.fields['company'].initial = company
            form.fields['company'].disabled = True
        else:
            form.fields['company'].queryset = Company.objects.none()

        return form

    def form_valid(self, form):
        messages.success(self.request, _('Store created successfully.'))
        return super().form_valid(form)


class BranchUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Update store (previously branch)."""
    model = Store
    template_name = 'company/branch_form.html'  # Keep same template
    permission_required = 'stores.change_store'
    # Updated fields for Store model
    fields = [
        'company', 'name', 'code', 'location', 'physical_address',
        'phone', 'email', 'tin', 'nin', 'is_main_branch',
        'is_active', 'store_type', 'manager_name', 'manager_phone',
        'allows_sales', 'allows_inventory'
    ]
    success_url = reverse_lazy('companies:branch_list')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)

        # Restrict company field to only current user's company
        current_user = self.request.user
        if hasattr(current_user, 'company') and current_user.company:
            company = current_user.company
            form.fields['company'].queryset = Company.objects.filter(company_id=company.company_id)
            form.fields['company'].initial = company
            form.fields['company'].disabled = True
        else:
            form.fields['company'].queryset = Company.objects.none()

        return form


class BranchDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    """Delete branch."""
    model = Store
    template_name = 'company/branch_confirm_delete.html'
    permission_required = 'branches.delete_companybranch'
    success_url = reverse_lazy('companies:branch_list')

    def delete(self, request, *args, **kwargs):
        branch_name = self.get_object().name
        result = super().delete(request, *args, **kwargs)
        messages.success(request, _('Branch "%s" deleted successfully.') % branch_name)
        return result


# AJAX Views for dynamic forms
class GetBranchesAjaxView(LoginRequiredMixin, View):
    """Get branches for a specific company via AJAX."""
    
    def get(self, request, *args, **kwargs):
        company_id = request.GET.get('company_id')
        if company_id:
            branches = Store.objects.filter(company_id=company_id).values('id', 'name')
            return JsonResponse({'branches': list(branches)})
        return JsonResponse({'branches': []})


class GetCompanyBranchesView(LoginRequiredMixin, View):
    """Get branches for a company in JSON format."""
    
    def get(self, request, *args, **kwargs):
        company_id = request.GET.get('company_id')
        branches = Store.objects.filter(company_id=company_id).values('id', 'name', 'code')
        return JsonResponse({'branches': list(branches)})
    

class ExportBranchesView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Export branches to CSV."""
    permission_required = 'branches.view_companybranch'
    
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
                branch.company.name,
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



