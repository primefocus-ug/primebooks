from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required,permission_required
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib import messages
from django.http import JsonResponse, HttpResponse, FileResponse, Http404
from django.db.models import Sum, Count, Q, F, Avg,  Case, When, Value, CharField
from django.utils import timezone
from django.core.paginator import Paginator
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from django.core.exceptions import PermissionDenied
from django.views.decorators.cache import cache_page
from django.core.cache import cache
from datetime import timedelta
import json
import csv
import os
import mimetypes
import logging
from .models import SavedReport, ReportSchedule, GeneratedReport, ReportAccessLog, ReportComparison
from .forms import (SavedReportForm, ReportScheduleForm, ReportFilterForm,
                    SalesReportForm, InventoryReportForm, ReportExportForm)
from .services.report_generator import ReportGeneratorService
from .tasks import generate_report_async, log_report_access
from sales.models import Sale, SaleItem
from inventory.models import Product, Stock, StockMovement, Category
from stores.models import Store
from stores.utils import get_user_accessible_stores, validate_store_access
from django.core.exceptions import PermissionDenied
from accounts.models import CustomUser
from invoices.models import Invoice

from .models import SavedReport, GeneratedReport
from .forms import ReportFilterForm, SalesReportForm, InventoryReportForm
from django.db import connection

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def user_can_access_all_stores(user):
    """Check if user can access all stores using new utility"""
    # Use the imported get_user_accessible_stores function to check
    from stores.utils import get_user_accessible_stores
    all_stores_count = Store.objects.filter(is_active=True).count()
    accessible_stores_count = get_user_accessible_stores(user).count()

    # If user can access all active stores, they have full access
    return accessible_stores_count == all_stores_count


@login_required
@permission_required('reports.view_savedreport')
def report_dashboard(request):
    """Enhanced dashboard with real-time capabilities"""
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    # Check cache first - include schema in cache key
    schema_name = connection.schema_name
    cache_key = f'dashboard_stats_{schema_name}_{request.user.id}'
    stats = cache.get(cache_key)

    if not stats:
        # Quick stats with optimized queries
        stats = {
            'total_sales_today': Sale.objects.filter(
                store__in=stores,
                created_at__date=today,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(total=Sum('total_amount'))['total'] or 0,

            'total_sales_week': Sale.objects.filter(
                store__in=stores,
                created_at__date__gte=week_ago,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(total=Sum('total_amount'))['total'] or 0,

            'total_sales_month': Sale.objects.filter(
                store__in=stores,
                created_at__date__gte=month_ago,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(total=Sum('total_amount'))['total'] or 0,

            'transactions_today': Sale.objects.filter(
                store__in=stores,
                created_at__date=today,
                status__in=['COMPLETED', 'PAID']
            ).count(),

            'low_stock_products': Stock.objects.filter(
                store__in=stores,
                quantity__lte=F('low_stock_threshold'),
                quantity__gt=0
            ).count(),

            'out_of_stock_products': Stock.objects.filter(
                store__in=stores,
                quantity=0
            ).count(),

            'total_products': Product.objects.filter(is_active=True).count(),
            'active_stores': stores.count(),

            'pending_fiscalization': Sale.objects.filter(
                store__in=stores,
                status__in=['COMPLETED', 'PAID'],
                is_fiscalized=False,
                created_at__date__gte=week_ago
            ).count(),
        }

        # Cache for 2 minutes
        cache.set(cache_key, stats, 120)

    # Sales trend - include schema in cache key
    trend_cache_key = f'sales_trend_{schema_name}_{request.user.id}'
    sales_trend = cache.get(trend_cache_key)

    if not sales_trend:
        sales_trend = []
        for i in range(30):
            date = today - timedelta(days=i)
            daily_sales = Sale.objects.filter(
                store__in=stores,
                created_at__date=date,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                total=Sum('total_amount'),
                count=Count('id')
            )
            sales_trend.insert(0, {
                'date': date.strftime('%Y-%m-%d'),
                'amount': float(daily_sales['total'] or 0),
                'count': daily_sales['count'] or 0
            })

        cache.set(trend_cache_key, sales_trend, 300)

    # Top selling products - include schema in cache key
    top_products_key = f'top_products_{schema_name}_{request.user.id}'
    top_products = cache.get(top_products_key)

    if not top_products:
        top_products = SaleItem.objects.filter(
            sale__store__in=stores,
            sale__created_at__date__gte=month_ago,
            sale__status__in=['COMPLETED', 'PAID']
        ).values('product__name', 'product__sku').annotate(
            total_quantity=Sum('quantity'),
            total_revenue=Sum('total_price')
        ).order_by('-total_revenue')[:10]

        cache.set(top_products_key, list(top_products), 300)

    # Recent generated reports - filter by schema
    recent_reports = GeneratedReport.objects.filter(
        generated_by=request.user,
        status='COMPLETED'
    ).select_related('report').order_by('-generated_at')[:5]

    # Favorite saved reports - filter by schema
    favorite_reports = SavedReport.objects.filter(
        Q(created_by=request.user) | Q(is_shared=True),
        is_favorite=True
    ).order_by('-last_executed')[:5]

    # Stock alerts
    stock_alerts = Stock.objects.filter(
        store__in=stores,
        quantity__lte=F('low_stock_threshold')
    ).select_related('product', 'store').order_by('quantity')[:10]

    context = {
        'stats': stats,
        'sales_trend': json.dumps(sales_trend),
        'top_products': top_products,
        'recent_reports': recent_reports,
        'favorite_reports': favorite_reports,
        'stock_alerts': stock_alerts,
        'stores': stores,
        'websocket_url': f'ws/reports/dashboard/',
    }

    return render(request, 'reports/dashboard.html', context)


def get_current_schema():
    """Get current tenant schema name"""
    from django.db import connection
    return connection.schema_name


@login_required
@permission_required('sales.view_sale')
def sales_summary_report(request):
    """Enhanced sales summary report"""
    form = SalesReportForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    sales_data = []
    summary_stats = {}
    chart_data = []
    saved_report = None  # Initialize saved_report variable here

    if form.is_valid():
        # Extract filter parameters
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')
        group_by = form.cleaned_data.get('group_by', 'date')

        # Check if user has access to selected store
        if store_filter and store_filter not in stores:
            messages.error(request, "You don't have access to the selected store.")
            return redirect('reports:sales_summary')

        # Check cache with schema
        schema_name = connection.schema_name
        cache_key = f'sales_report_{schema_name}_{request.user.id}_{start_date}_{end_date}_{store_filter}_{group_by}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            sales_data = cached_result['sales_data']
            summary_stats = cached_result['summary_stats']
            chart_data = cached_result['chart_data']
        else:
            # Use report generator service
            saved_report = SavedReport.objects.filter(
                report_type='SALES_SUMMARY',
                created_by=request.user
            ).first()

            if not saved_report:
                # Create temporary report configuration
                saved_report = SavedReport(
                    name='Sales Summary',
                    report_type='SALES_SUMMARY',
                    created_by=request.user
                )
                saved_report.save()  # Save it to get an ID

            from .services.report_generator import ReportGeneratorService
            generator = ReportGeneratorService(request.user, saved_report)

            report_data = generator.generate(
                start_date=start_date,
                end_date=end_date,
                store_id=store_filter.id if store_filter else None,
                group_by=group_by
            )

            sales_data = report_data.get('grouped_data', [])
            summary_stats = report_data.get('summary', {})
            chart_data = sales_data[:50]

            # Cache results
            cache.set(cache_key, {
                'sales_data': sales_data,
                'summary_stats': summary_stats,
                'chart_data': chart_data
            }, 300)

        # Log access with schema_name - safe reference
        from .tasks import log_report_access
        report_id = saved_report.id if saved_report else 0

        log_report_access.delay(
            report_id,
            request.user.id,
            schema_name,
            'VIEW',
            form.cleaned_data,
            get_client_ip(request),
            request.META.get('HTTP_USER_AGENT', '')
        )

    context = {
        'form': form,
        'sales_data': sales_data,
        'summary_stats': summary_stats,
        'chart_data': json.dumps(chart_data, default=str),
        'stores': stores,
    }

    return render(request, 'reports/sales_summary.html', context)


@login_required
@permission_required('inventory.view_product')
def product_performance_report(request):
    """Enhanced product performance report"""
    form = ReportFilterForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    products_data = []
    summary_stats = {}

    if form.is_valid():
        # Extract serialized form data
        form_data = form.get_serialized_data()

        # Check if user has access to selected store
        store_filter = form.cleaned_data.get('store')
        if store_filter and store_filter not in stores:
            messages.error(request, "You don't have access to the selected store.")
            return redirect('reports:product_performance')

        # Include schema in cache key
        schema_name = connection.schema_name
        cache_key = f'product_performance_{schema_name}_{request.user.id}_{hash(str(form_data))}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            products_data = cached_result['products_data']
            summary_stats = cached_result['summary_stats']
        else:
            saved_report = SavedReport(
                name='Product Performance',
                report_type='PRODUCT_PERFORMANCE',
                created_by=request.user
            )
            saved_report.save()

            generator = ReportGeneratorService(request.user, saved_report)
            report_data = generator.generate(**form_data)

            products_data = report_data.get('products', [])
            summary_stats = report_data.get('summary', {})

            cache.set(cache_key, {
                'products_data': products_data,
                'summary_stats': summary_stats
            }, 300)

    # Pagination
    paginator = Paginator(products_data, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'form': form,
        'page_obj': page_obj,
        'summary_stats': summary_stats,
        'stores': stores,
    }

    return render(request, 'reports/product_performance.html', context)


@login_required
@permission_required('inventory.view_product')
def inventory_status_report(request):
    """Enhanced inventory status report with real-time alerts"""
    form = InventoryReportForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    inventory_data = []
    summary_stats = {}
    alerts = []

    if form.is_valid():
        # Extract serialized form data
        form_data = form.get_serialized_data()

        # Check if user has access to selected store
        store_filter = form.cleaned_data.get('store')
        if store_filter and store_filter not in stores:
            messages.error(request, "You don't have access to the selected store.")
            return redirect('reports:inventory_status')

        # Include schema in cache key
        schema_name = connection.schema_name
        cache_key = f'inventory_status_{schema_name}_{request.user.id}_{hash(str(form_data))}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            inventory_data = cached_result['inventory_data']
            summary_stats = cached_result['summary_stats']
            alerts = cached_result['alerts']
        else:
            saved_report = SavedReport(
                name='Inventory Status',
                report_type='INVENTORY_STATUS',
                created_by=request.user
            )
            saved_report.save()

            generator = ReportGeneratorService(request.user, saved_report)
            report_data = generator.generate(**form_data)

            inventory_data = report_data.get('inventory', [])
            summary_stats = report_data.get('summary', {})
            alerts = report_data.get('alerts', [])

            cache.set(cache_key, {
                'inventory_data': inventory_data,
                'summary_stats': summary_stats,
                'alerts': alerts
            }, 180)

    # Pagination
    paginator = Paginator(inventory_data, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'form': form,
        'page_obj': page_obj,
        'summary_stats': summary_stats,
        'alerts': alerts,
        'stores': stores,
    }

    return render(request, 'reports/inventory_status.html', context)




@login_required
@permission_required('reports.add_savedreport')
def generate_report(request, report_id):
    """Generate report asynchronously with progress tracking"""
    report = get_object_or_404(SavedReport, id=report_id)

    # Check permissions
    if not (user_can_access_all_stores(request.user) or
            report.created_by == request.user or report.is_shared):
        raise PermissionDenied

    if request.method == 'POST':
        try:
            # Get current tenant schema name
            schema_name = connection.schema_name

            # Get form data
            format_type = request.POST.get('format', 'PDF')
            include_charts = request.POST.get('include_charts') == 'on'
            include_summary = request.POST.get('include_summary') == 'on'
            confidential = request.POST.get('confidential') == 'on'
            watermark = request.POST.get('watermark', '')
            email_recipients = request.POST.get('email_recipients', '')

            # Create GeneratedReport entry
            generated_report = GeneratedReport.objects.create(
                report=report,
                generated_by=request.user,
                parameters=report.filters or {},
                file_format=format_type,
                status='PENDING'
            )

            # Prepare kwargs for generation
            kwargs = report.filters.copy() if report.filters else {}
            kwargs['format'] = format_type
            kwargs['include_charts'] = include_charts
            kwargs['include_summary'] = include_summary
            kwargs['email_report'] = bool(email_recipients)
            kwargs['email_recipients'] = email_recipients
            kwargs['confidential'] = confidential
            kwargs['watermark'] = watermark

            # Start async generation with schema_name
            from .tasks import generate_report_async
            task = generate_report_async.delay(
                report.id,
                request.user.id,
                schema_name,  # Pass the current tenant's schema name
                **kwargs
            )

            generated_report.task_id = task.id
            generated_report.save()

            messages.success(
                request,
                f'Report generation started. You will be notified when complete.'
            )

            # Return JSON response
            return JsonResponse({
                'success': True,
                'generated_report_id': generated_report.id,
                'websocket_url': f'/ws/reports/generation/{generated_report.id}/',
                'redirect_url': reverse('reports:history')
            })

        except Exception as e:
            logger.error(f"Error starting report generation: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': str(e)
            }, status=400)

    else:
        # GET request - show form
        from .forms import ReportExportForm
        export_form = ReportExportForm()

        context = {
            'report': report,
            'export_form': export_form,
        }

        return render(request, 'reports/generate_report.html', context)


@login_required
@permission_required('reports.view_savedreport')
def tax_report(request):
    """Tax report for EFRIS compliance."""
    from .forms import ReportFilterForm

    form = ReportFilterForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    tax_data = []
    summary_stats = {}
    efris_stats = {}

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')

        # Use report generator
        saved_report = SavedReport(
            name='Tax Report',
            report_type='TAX_REPORT',
            created_by=request.user
        )

        from .services.report_generator import ReportGeneratorService
        generator = ReportGeneratorService(request.user, saved_report)

        report_data = generator.generate(
            start_date=start_date,
            end_date=end_date,
            store_id=store_filter.id if store_filter else None
        )

        tax_data = report_data.get('tax_breakdown', [])
        summary_stats = report_data.get('summary', {})
        efris_stats = report_data.get('efris_stats', {})

    context = {
        'form': form,
        'tax_breakdown': tax_data,
        'summary_stats': summary_stats,
        'efris_stats': efris_stats,
        'stores': stores,
    }

    return render(request, 'reports/tax_report.html', context)


@login_required
@permission_required('view_savedreport')
def analytics_dashboard(request):
    """Advanced analytics dashboard with charts and KPIs."""
    # Get user's accessible stores
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    today = timezone.now().date()
    last_30_days = today - timedelta(days=30)
    last_year = today - timedelta(days=365)

    # Sales trend (last 30 days)
    sales_trend = []
    for i in range(30):
        date = today - timedelta(days=i)
        daily_sales = Sale.objects.filter(
            store__in=stores,
            created_at__date=date,
            status__in=['COMPLETED', 'PAID']
        ).aggregate(
            amount=Sum('total_amount'),
            count=Count('id')
        )
        sales_trend.insert(0, {
            'date': date.strftime('%Y-%m-%d'),
            'amount': float(daily_sales['amount'] or 0),
            'count': daily_sales['count'] or 0
        })

    # Monthly comparison (this year vs last year)
    monthly_comparison = []
    for month in range(1, 13):
        this_year_sales = Sale.objects.filter(
            store__in=stores,
            created_at__year=today.year,
            created_at__month=month,
            status__in=['COMPLETED', 'PAID']
        ).aggregate(total=Sum('total_amount'))['total'] or 0

        last_year_sales = Sale.objects.filter(
            store__in=stores,
            created_at__year=today.year - 1,
            created_at__month=month,
            status__in=['COMPLETED', 'PAID']
        ).aggregate(total=Sum('total_amount'))['total'] or 0

        monthly_comparison.append({
            'month': month,
            'this_year': float(this_year_sales),
            'last_year': float(last_year_sales)
        })

    # Top products by revenue (last 30 days)
    top_products = SaleItem.objects.filter(
        sale__store__in=stores,
        sale__created_at__date__gte=last_30_days,
        sale__status__in=['COMPLETED', 'PAID']
    ).values('product__name').annotate(
        revenue=Sum('total_price'),
        quantity=Sum('quantity')
    ).order_by('-revenue')[:10]

    # Store performance comparison
    store_performance = Sale.objects.filter(
        store__in=stores,
        created_at__date__gte=last_30_days,
        status__in=['COMPLETED', 'PAID']
    ).values('store__name', 'store__company__name').annotate(
        revenue=Sum('total_amount'),
        transactions=Count('id'),
        avg_transaction=Avg('total_amount')
    ).order_by('-revenue')

    # Customer insights (if customer data available)
    customer_stats = Sale.objects.filter(
        store__in=stores,
        created_at__date__gte=last_30_days,
        status__in=['COMPLETED', 'PAID'],
        customer__isnull=False
    ).aggregate(
        unique_customers=Count('customer', distinct=True),
        avg_customer_spend=Avg('total_amount')
    )

    # Payment method breakdown
    payment_methods = Sale.objects.filter(
        store__in=stores,
        created_at__date__gte=last_30_days,
        status__in=['COMPLETED', 'PAID']
    ).values('payment_method').annotate(
        count=Count('id'),
        amount=Sum('total_amount')
    ).order_by('-amount')

    context = {
        'sales_trend': json.dumps(sales_trend),
        'monthly_comparison': json.dumps(monthly_comparison),
        'top_products': list(top_products),
        'store_performance': store_performance,
        'customer_stats': customer_stats,
        'payment_methods': payment_methods,
        'stores': stores,
    }

    return render(request, 'reports/analytics_dashboard.html', context)


@login_required
@permission_required('reports.view_savedreport')
def export_report(request, report_type):
    """Export reports to CSV format."""
    if not request.user.has_perm('reports.can_export_reports'):
        messages.error(request, "You don't have permission to export reports.")
        return redirect('reports:dashboard')

    # Get current tenant schema
    schema_name = connection.schema_name

    # Get user's accessible stores
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{report_type}_{timezone.now().date()}.csv"'

    writer = csv.writer(response)

    if report_type == 'sales_summary':
        writer.writerow(['Date', 'Store', 'Company', 'Total Amount', 'Transactions', 'Average Transaction'])

        sales_data = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID']
        ).select_related('store', 'store__company').order_by('-created_at')

        for sale in sales_data:
            writer.writerow([
                sale.created_at.date(),
                sale.store.name,
                sale.store.company.name,
                sale.total_amount,
                1,  # Each row is one transaction
                sale.total_amount
            ])

    elif report_type == 'inventory_status':
        writer.writerow(['Product', 'SKU', 'Store', 'Quantity', 'Reorder Level', 'Status', 'Stock Value'])

        inventory_data = Stock.objects.filter(
            store__in=stores
        ).select_related('product', 'store')

        for stock in inventory_data:
            status = 'Out of Stock' if stock.quantity == 0 else \
                'Low Stock' if stock.quantity <= stock.low_stock_threshold else 'In Stock'

            writer.writerow([
                stock.product.name,
                stock.product.sku,
                stock.store.name,
                stock.quantity,
                stock.low_stock_threshold,
                status,
                stock.quantity * stock.product.cost_price
            ])

    return response


@login_required
@permission_required('view_savedreport')
def save_report(request):
    """Save current report configuration for future use."""
    if request.method == 'POST':
        report_name = request.POST.get('report_name')
        report_type = request.POST.get('report_type')
        filters = request.POST.get('filters', '{}')

        try:
            saved_report = SavedReport.objects.create(
                name=report_name,
                report_type=report_type,
                created_by=request.user,
                filters=json.loads(filters)
            )

            return JsonResponse({
                'success': True,
                'message': 'Report saved successfully',
                'report_id': saved_report.id
            })
        except Exception as e:
            return JsonResponse({
                'success': False,
                'message': f'Error saving report: {str(e)}'
            })

    return JsonResponse({'success': False, 'message': 'Invalid request method'})


@login_required
@permission_required('reports.view_savedreport')
def saved_reports_list(request):
    """List all saved reports with search and filters"""
    if user_can_access_all_stores(request.user):
        saved_reports = SavedReport.objects.all()
    else:
        saved_reports = SavedReport.objects.filter(
            Q(created_by=request.user) | Q(is_shared=True)
        )

    # Search
    search_query = request.GET.get('search', '')
    if search_query:
        saved_reports = saved_reports.filter(
            Q(name__icontains=search_query) |
            Q(description__icontains=search_query)
        )

    # Filter by report type
    report_type = request.GET.get('type')
    if report_type:
        saved_reports = saved_reports.filter(report_type=report_type)

    # Filter by favorites
    if request.GET.get('favorites'):
        saved_reports = saved_reports.filter(is_favorite=True)

    saved_reports = saved_reports.select_related('created_by').order_by('-last_modified')

    # Pagination
    paginator = Paginator(saved_reports, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'report_types': SavedReport.REPORT_TYPES,
        'selected_type': report_type,
        'search_query': search_query,
    }

    return render(request, 'reports/saved_reports_list.html', context)


@login_required
@permission_required('reports.add_savedreport')
def create_saved_report(request):
    """Create a new saved report configuration"""
    if request.method == 'POST':
        form = SavedReportForm(request.POST)
        if form.is_valid():
            saved_report = form.save(commit=False)
            saved_report.created_by = request.user

            # Set default JSON fields
            if not saved_report.columns:
                saved_report.columns = []
            if not saved_report.filters:
                saved_report.filters = {}
            if not saved_report.parameters:
                saved_report.parameters = {}

            saved_report.save()

            messages.success(request, 'Report configuration saved successfully!')
            return redirect('reports:saved_reports')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SavedReportForm()

    context = {
        'form': form,
        'title': 'Create Saved Report',
    }

    return render(request, 'reports/saved_report_form.html', context)


@login_required
@permission_required('reports.change_savedreport')
def edit_saved_report(request, report_id):
    """Edit an existing saved report"""
    saved_report = get_object_or_404(SavedReport, id=report_id)

    # Check permissions
    if not (user_can_access_all_stores(request.user) or
            saved_report.created_by == request.user):
        raise PermissionDenied

    if request.method == 'POST':
        form = SavedReportForm(request.POST, instance=saved_report)
        if form.is_valid():
            updated_report = form.save()

            # Invalidate cache
            updated_report.invalidate_cache()

            messages.success(request, 'Report updated successfully!')
            return redirect('reports:saved_reports')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = SavedReportForm(instance=saved_report)

    context = {
        'form': form,
        'saved_report': saved_report,
        'title': 'Edit Saved Report',
    }

    return render(request, 'reports/saved_report_form.html', context)


@login_required
@permission_required('reports.view_savedreport')
def view_saved_report(request, report_id):
    """View a saved report configuration."""
    saved_report = get_object_or_404(SavedReport, id=report_id)

    # Check permissions
    if not (user_can_access_all_stores(request.user) or
            saved_report.created_by == request.user or saved_report.is_shared):
        raise PermissionDenied

    context = {
        'saved_report': saved_report,
    }

    return render(request, 'reports/saved_report_detail.html', context)


@login_required
@permission_required('reports.delete_savedreport')
def delete_saved_report(request, report_id):
    """Delete a saved report"""
    saved_report = get_object_or_404(SavedReport, id=report_id)

    if not (user_can_access_all_stores(request.user) or
            saved_report.created_by == request.user):
        raise PermissionDenied

    if request.method == 'POST':
        saved_report.delete()
        messages.success(request, 'Report deleted successfully!')
        return redirect('reports:saved_reports')

    context = {
        'saved_report': saved_report,
    }

    return render(request, 'reports/confirm_delete.html', context)


@login_required
@permission_required('reports.view_savedreport')
def run_saved_report(request, report_id):
    """Execute a saved report configuration."""
    saved_report = get_object_or_404(SavedReport, id=report_id)

    # Check permissions
    if not (user_can_access_all_stores(request.user) or
            saved_report.created_by == request.user or saved_report.is_shared):
        raise PermissionDenied

    # Redirect to appropriate report view based on report type
    report_urls = {
        'SALES_SUMMARY': 'reports:sales_summary',
        'PRODUCT_PERFORMANCE': 'reports:product_performance',
        'INVENTORY_STATUS': 'reports:inventory_status',
        'TAX_REPORT': 'reports:tax_report',
        'Z_REPORT': 'reports:z_report',
        'EFRIS_COMPLIANCE': 'reports:efris_compliance',
        'PRICE_LOOKUP': 'reports:price_lookup',
    }

    url = report_urls.get(saved_report.report_type, 'reports:dashboard')

    # Add saved report filters as URL parameters
    query_params = saved_report.filters or {}
    query_string = '&'.join([f"{k}={v}" for k, v in query_params.items()])

    if query_string:
        return redirect(f"{reverse(url)}?{query_string}")
    else:
        return redirect(url)


@login_required
@permission_required('reports.view_reportschedule')
def report_schedules_list(request):
    """List all report schedules."""
    if user_can_access_all_stores(request.user):
        schedules = ReportSchedule.objects.all()
    else:
        schedules = ReportSchedule.objects.filter(
            report__created_by=request.user
        )

    schedules = schedules.select_related('report').order_by('-next_scheduled')

    # Pagination
    paginator = Paginator(schedules, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
    }

    return render(request, 'reports/schedules_list.html', context)


@login_required
@permission_required('reports.add_reportschedule')
def create_schedule(request):
    """Create a new report schedule."""
    if request.method == 'POST':
        form = ReportScheduleForm(request.POST, user=request.user)
        if form.is_valid():
            schedule = form.save()
            messages.success(request, 'Report schedule created successfully!')
            return redirect('reports:schedules')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ReportScheduleForm(user=request.user)

    context = {
        'form': form,
        'title': 'Create Report Schedule',
    }

    return render(request, 'reports/schedule_form.html', context)


@login_required
@permission_required('reports.change_reportschedule')
def edit_schedule(request, schedule_id):
    """Edit an existing report schedule."""
    schedule = get_object_or_404(ReportSchedule, id=schedule_id)

    # Check permissions
    if not (user_can_access_all_stores(request.user) or
            schedule.report.created_by == request.user):
        raise PermissionDenied

    if request.method == 'POST':
        form = ReportScheduleForm(request.POST, instance=schedule, user=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Report schedule updated successfully!')
            return redirect('reports:schedules')
        else:
            messages.error(request, 'Please correct the errors below.')
    else:
        form = ReportScheduleForm(instance=schedule, user=request.user)

    context = {
        'form': form,
        'schedule': schedule,
        'title': 'Edit Report Schedule',
    }

    return render(request, 'reports/schedule_form.html', context)


@login_required
@permission_required('reports.delete_reportschedule')
def delete_schedule(request, schedule_id):
    """Delete a report schedule."""
    schedule = get_object_or_404(ReportSchedule, id=schedule_id)

    # Check permissions
    if not (user_can_access_all_stores(request.user) or
            schedule.report.created_by == request.user):
        raise PermissionDenied

    if request.method == 'POST':
        schedule.delete()
        messages.success(request, 'Report schedule deleted successfully!')
        return redirect('reports:schedules')

    context = {
        'schedule': schedule,
    }

    return render(request, 'reports/confirm_delete_schedule.html', context)


@login_required
@permission_required('reports.view_reportschedule')
@require_http_methods(["POST"])
def toggle_schedule(request, schedule_id):
    """Toggle a report schedule active/inactive status."""
    schedule = get_object_or_404(ReportSchedule, id=schedule_id)

    # Check permissions
    if not (user_can_access_all_stores(request.user) or
            schedule.report.created_by == request.user):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    schedule.is_active = not schedule.is_active
    schedule.save()

    return JsonResponse({
        'success': True,
        'is_active': schedule.is_active,
        'message': f"Schedule {'activated' if schedule.is_active else 'deactivated'}"
    })


@login_required
@permission_required('reports.change_savedreport')
@require_http_methods(["POST"])
def toggle_favorite_report(request, report_id):
    """Toggle report favorite status"""
    saved_report = get_object_or_404(SavedReport, id=report_id)

    if not (user_can_access_all_stores(request.user) or
            saved_report.created_by == request.user or saved_report.is_shared):
        return JsonResponse({'success': False, 'error': 'Permission denied'}, status=403)

    saved_report.is_favorite = not saved_report.is_favorite
    saved_report.save()

    return JsonResponse({
        'success': True,
        'is_favorite': saved_report.is_favorite,
        'message': f"Report {'added to' if saved_report.is_favorite else 'removed from'} favorites"
    })


@login_required
@permission_required('reports.view_generatereport')
def generated_reports_history(request):
    """View history of generated reports with filtering"""
    if user_can_access_all_stores(request.user):
        reports = GeneratedReport.objects.all()
    else:
        reports = GeneratedReport.objects.filter(
            Q(generated_by=request.user) | Q(report__created_by=request.user)
        )

    reports = reports.select_related('report', 'generated_by').order_by('-generated_at')

    # Filters
    report_type = request.GET.get('type')
    status = request.GET.get('status')
    format_filter = request.GET.get('format')

    if report_type:
        reports = reports.filter(report__report_type=report_type)
    if status:
        reports = reports.filter(status=status)
    if format_filter:
        reports = reports.filter(file_format=format_filter)

    # Pagination
    paginator = Paginator(reports, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'report_types': SavedReport.REPORT_TYPES,
        'selected_type': report_type,
        'selected_status': status,
        'selected_format': format_filter,
    }

    return render(request, 'reports/generated_reports_history.html', context)


@login_required
@permission_required('reports.view_generatereport')
def download_generated_report(request, report_id):
    """Download generated report with access logging"""
    report = get_object_or_404(GeneratedReport, id=report_id)

    # Check permissions
    if not (user_can_access_all_stores(request.user) or
            report.generated_by == request.user or report.report.created_by == request.user):
        raise PermissionDenied

    if report.is_expired:
        messages.error(request, 'This report has expired and is no longer available.')
        return redirect('reports:history')

    if not os.path.exists(report.file_path):
        raise Http404("Report file not found")

    # Log download
    log_report_access.delay(
        report.report.id,
        request.user.id,
        'DOWNLOAD',
        {'generated_report_id': report.id},
        get_client_ip(request),
        request.META.get('HTTP_USER_AGENT', '')
    )

    # Increment download count
    report.increment_download_count()

    # Serve file
    response = FileResponse(
        open(report.file_path, 'rb'),
        content_type=mimetypes.guess_type(report.file_path)[0] or 'application/octet-stream'
    )
    response['Content-Disposition'] = f'attachment; filename="{os.path.basename(report.file_path)}"'
    response['Content-Length'] = report.file_size

    return response


@login_required
@permission_required('reports.delete_generatereport')
def delete_generated_report(request, report_id):
    report = get_object_or_404(GeneratedReport, id=report_id)

    if not (user_can_access_all_stores(request.user) or
            report.generated_by == request.user):
        raise PermissionDenied

    if request.method == 'POST':
        if os.path.exists(report.file_path):
            try:
                os.remove(report.file_path)
            except Exception as e:
                logger.error(f"Error deleting report file: {e}")

        report.delete()
        messages.success(request, 'Generated report deleted successfully!')
        return redirect('reports:history')

    context = {'report': report}
    return render(request, 'reports/confirm_delete_generated.html', context)


@login_required
def get_chart_data(request):
    """AJAX endpoint for chart data."""
    chart_type = request.GET.get('type', 'sales_trend')

    # Get user's accessible stores
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    if chart_type == 'sales_trend':
        days = int(request.GET.get('days', 7))
        today = timezone.now().date()

        data = []
        for i in range(days):
            date = today - timedelta(days=i)
            daily_sales = Sale.objects.filter(
                store__in=stores,
                created_at__date=date,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(total=Sum('total_amount'))['total'] or 0

            data.insert(0, {
                'date': date.strftime('%Y-%m-%d'),
                'amount': float(daily_sales)
            })

        return JsonResponse({'data': data})

    elif chart_type == 'top_products':
        limit = int(request.GET.get('limit', 10))
        days = int(request.GET.get('days', 30))
        start_date = timezone.now().date() - timedelta(days=days)

        products = SaleItem.objects.filter(
            sale__store__in=stores,
            sale__created_at__date__gte=start_date,
            sale__status__in=['COMPLETED', 'PAID']
        ).values('product__name').annotate(
            revenue=Sum('total_price')
        ).order_by('-revenue')[:limit]

        return JsonResponse({'data': list(products)})

    return JsonResponse({'error': 'Invalid chart type'})


@login_required
def get_quick_stats(request):
    """AJAX endpoint for dashboard quick stats."""
    # Get user's accessible stores
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    today = timezone.now().date()
    week_ago = today - timedelta(days=7)

    stats = {
        'today_sales': float(Sale.objects.filter(
            store__in=stores,
            created_at__date=today,
            status__in=['COMPLETED', 'PAID']
        ).aggregate(total=Sum('total_amount'))['total'] or 0),

        'week_sales': float(Sale.objects.filter(
            store__in=stores,
            created_at__date__gte=week_ago,
            status__in=['COMPLETED', 'PAID']
        ).aggregate(total=Sum('total_amount'))['total'] or 0),

        'low_stock_count': Stock.objects.filter(
            store__in=stores,
            quantity__lte=F('low_stock_threshold')
        ).count(),

        'pending_invoices': Invoice.objects.filter(
            store__in=stores,
            status__in=['SENT', 'PARTIALLY_PAID']
        ).count(),
    }

    return JsonResponse(stats)


@login_required
def get_filter_options(request):
    """AJAX endpoint for dynamic filter options."""
    filter_type = request.GET.get('type')

    # Get user's accessible stores
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    if filter_type == 'stores':
        options = [{'id': s.id, 'name': s.name} for s in stores]
    elif filter_type == 'categories':
        categories = Category.objects.all()
        options = [{'id': c.id, 'name': c.name} for c in categories]
    else:
        options = []

    return JsonResponse({'options': options})


@login_required
@permission_required('reports.add_savedreport')
def z_report(request):
    """Daily Z-Report for end-of-day summary."""
    form = ReportFilterForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    report_data = {}

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date') or timezone.now().date()
        end_date = form.cleaned_data.get('end_date') or start_date
        store_filter = form.cleaned_data.get('store')

        queryset = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID'],
            created_at__date__gte=start_date,
            created_at__date__lte=end_date
        )

        if store_filter:
            queryset = queryset.filter(store=store_filter)

        # Z-Report summary
        report_data = {
            'period_start': start_date,
            'period_end': end_date,
            'total_sales': queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
            'total_transactions': queryset.count(),
            'total_tax': queryset.aggregate(Sum('tax_amount'))['tax_amount__sum'] or 0,
            'total_discount': queryset.aggregate(Sum('discount_amount'))['discount_amount__sum'] or 0,
            'payment_breakdown': queryset.values('payment_method').annotate(
                count=Count('id'),
                amount=Sum('total_amount')
            ).order_by('payment_method'),
            'hourly_breakdown': queryset.extra(
                select={'hour': "EXTRACT(hour FROM created_at)"}
            ).values('hour').annotate(
                count=Count('id'),
                amount=Sum('total_amount')
            ).order_by('hour'),
        }

        # Refunds and voids
        report_data['refunds'] = queryset.filter(is_refunded=True).aggregate(
            count=Count('id'),
            amount=Sum('total_amount')
        )

        report_data['voids'] = queryset.filter(is_voided=True).aggregate(
            count=Count('id'),
            amount=Sum('total_amount')
        )

    context = {
        'form': form,
        'report_data': report_data,
        'stores': stores,
    }

    return render(request, 'reports/z_report.html', context)


@login_required
@permission_required('reports.view_savedreport')
def efris_compliance_report(request):
    """EFRIS compliance status report."""
    from .forms import ReportFilterForm

    form = ReportFilterForm(request.GET or None, user=request.user)

    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    compliance_data = {}

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')

        saved_report = SavedReport(
            name='EFRIS Compliance',
            report_type='EFRIS_COMPLIANCE',
            created_by=request.user
        )

        from .services.report_generator import ReportGeneratorService
        generator = ReportGeneratorService(request.user, saved_report)

        compliance_data = generator.generate(
            start_date=start_date,
            end_date=end_date,
            store_id=store_filter.id if store_filter else None
        )

    context = {
        'form': form,
        'compliance_data': compliance_data,
        'stores': stores,
    }

    return render(request, 'reports/efris_compliance.html', context)


@login_required
def price_lookup_report(request):
    """Price lookup report for products."""
    from .forms import ReportFilterForm
    from inventory.models import Category

    search_query = request.GET.get('search', '')
    category_filter = request.GET.get('category')

    # Get user's accessible stores
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    # Build product queryset
    products = Product.objects.filter(is_active=True)

    if search_query:
        products = products.filter(
            Q(name__icontains=search_query) |
            Q(sku__icontains=search_query) |
            Q(barcode__icontains=search_query)
        )

    if category_filter:
        products = products.filter(category_id=category_filter)

    # Get stock information for each product
    products_with_stock = []
    for product in products[:50]:  # Limit to 50
        stock_info = Stock.objects.filter(
            product=product,
            store__in=stores
        ).values('store__name').annotate(
            quantity=Sum('quantity')
        )

        products_with_stock.append({
            'product': product,
            'stock_info': stock_info,
            'total_stock': sum([s['quantity'] for s in stock_info])
        })

    # Pagination
    paginator = Paginator(products_with_stock, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_obj': page_obj,
        'search_query': search_query,
        'categories': Category.objects.all(),
        'selected_category': category_filter,
        'stores': stores,
    }

    return render(request, 'reports/price_lookup.html', context)


@login_required
@permission_required('reports.add_savedreport')
def cashier_performance_report(request):
    """Cashier performance report."""
    form = ReportFilterForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
        # Get all active users (could be filtered by role if needed)
        cashiers = CustomUser.objects.filter(
            is_active=True,
            is_hidden=False
        )
    else:
        stores = request.user.stores.filter(is_active=True)
        store_ids = stores.values_list('id', flat=True)
        cashiers = CustomUser.objects.filter(
            stores__id__in=store_ids,
            is_active=True,
            is_hidden=False
        ).distinct()

    performance_data = []

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')

        # Build queryset
        queryset = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID'],
            created_by__in=cashiers
        )

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if store_filter:
            queryset = queryset.filter(store=store_filter)

        performance_data = queryset.values(
            'created_by__first_name',
            'created_by__last_name',
            'created_by__username',
            'store__name'
        ).annotate(
            total_sales=Sum('total_amount'),
            transaction_count=Count('id'),
            avg_transaction=Avg('total_amount'),
            total_items=Sum('items__quantity'),
        ).order_by('-total_sales')

    context = {
        'form': form,
        'performance_data': performance_data,
        'stores': stores,
        'cashiers': cashiers,
    }

    return render(request, 'reports/cashier_performance.html', context)


@login_required
def print_sales_report(request, report_id):
    """Print-friendly sales report view."""
    # Implementation for print view
    pass  # Implement based on your specific printing requirements


@login_required
def print_inventory_report(request):
    """Print-friendly inventory report view."""
    # Implementation for print view
    pass  # Implement based on your specific printing requirements


@login_required
def print_tax_report(request):
    """Print-friendly tax report view."""
    # Implementation for print view
    pass  # Implement based on your specific printing requirements


@login_required
def get_dashboard_stats_ajax(request):
    """Get current dashboard statistics via AJAX"""
    cache_key = f'dashboard_stats_{request.user.id}'
    stats = cache.get(cache_key)

    if not stats:
        # Regenerate stats (same logic as dashboard view)
        if user_can_access_all_stores(request.user):
            stores = Store.objects.filter(is_active=True)
        else:
            stores = request.user.stores.filter(is_active=True)

        today = timezone.now().date()
        week_ago = today - timedelta(days=7)

        stats = {
            'sales_today': float(Sale.objects.filter(
                store__in=stores,
                created_at__date=today,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(total=Sum('total_amount'))['total'] or 0),

            'transactions_today': Sale.objects.filter(
                store__in=stores,
                created_at__date=today,
                status__in=['COMPLETED', 'PAID']
            ).count(),

            'low_stock_count': Stock.objects.filter(
                store__in=stores,
                quantity__lte=F('low_stock_threshold')
            ).count(),
        }

        cache.set(cache_key, stats, 120)

    return JsonResponse(stats)


@login_required
def get_report_progress_ajax(request, report_id):
    """Get report generation progress via AJAX"""
    report = get_object_or_404(GeneratedReport, id=report_id)

    if not (user_can_access_all_stores(request.user) or report.generated_by == request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    return JsonResponse({
        'status': report.status,
        'progress': report.progress,
        'error_message': report.error_message,
        'file_size': report.file_size if report.status == 'COMPLETED' else 0,
        'row_count': report.row_count if report.status == 'COMPLETED' else 0,
    })


@login_required
def cancel_report_generation_ajax(request, report_id):
    """Cancel ongoing report generation"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Method not allowed'}, status=405)

    report = get_object_or_404(GeneratedReport, id=report_id)

    if not (user_can_access_all_stores(request.user) or report.generated_by == request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    if report.status in ['PENDING', 'PROCESSING']:
        # Revoke celery task
        if report.task_id:
            from celery import current_app
            current_app.control.revoke(report.task_id, terminate=True)

        report.status = 'CANCELLED'
        report.error_message = 'Cancelled by user'
        report.save()

        return JsonResponse({'success': True, 'message': 'Report generation cancelled'})

    return JsonResponse({'success': False, 'message': 'Report cannot be cancelled'})


@login_required
def get_stock_alerts_ajax(request):
    """Get current stock alerts via AJAX"""
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    alerts = []

    # Low stock
    low_stock = Stock.objects.filter(
        store__in=stores,
        quantity__lte=F('low_stock_threshold'),
        quantity__gt=0
    ).select_related('product', 'store')[:10]

    for stock in low_stock:
        alerts.append({
            'type': 'low_stock',
            'severity': 'warning',
            'product_name': stock.product.name,
            'store_name': stock.store.name,
            'quantity': stock.quantity,
            'threshold': stock.low_stock_threshold
        })

    # Out of stock
    out_of_stock = Stock.objects.filter(
        store__in=stores,
        quantity=0
    ).select_related('product', 'store')[:10]

    for stock in out_of_stock:
        alerts.append({
            'type': 'out_of_stock',
            'severity': 'critical',
            'product_name': stock.product.name,
            'store_name': stock.store.name
        })

    return JsonResponse({'alerts': alerts})