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
from accounts.models import CustomUser
from invoices.models import Invoice

from .models import SavedReport, GeneratedReport
from .forms import ReportFilterForm, SalesReportForm, InventoryReportForm

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
    """Check if user can access all stores (SaaS admin or high-priority role)"""
    return (
        getattr(user, 'is_saas_admin', False) or
        user.is_superuser or
        (user.primary_role and user.primary_role.priority >= 90)
    )


@login_required
@permission_required('reports.view_savedreport')
def report_dashboard(request):
    """Enhanced dashboard with real-time capabilities"""
    today = timezone.now().date()
    week_ago = today - timedelta(days=7)
    month_ago = today - timedelta(days=30)

    # Get user's accessible stores
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    # Check cache first
    cache_key = f'dashboard_stats_{request.user.id}'
    stats = cache.get(cache_key)

    if not stats:
        # Quick stats with optimized queries
        stats = {
            'total_sales_today': Sale.objects.filter(
                store__in=stores,
                created_at__date=today,
                is_completed=True
            ).aggregate(total=Sum('total_amount'))['total'] or 0,

            'total_sales_week': Sale.objects.filter(
                store__in=stores,
                created_at__date__gte=week_ago,
                is_completed=True
            ).aggregate(total=Sum('total_amount'))['total'] or 0,

            'total_sales_month': Sale.objects.filter(
                store__in=stores,
                created_at__date__gte=month_ago,
                is_completed=True
            ).aggregate(total=Sum('total_amount'))['total'] or 0,

            'transactions_today': Sale.objects.filter(
                store__in=stores,
                created_at__date=today,
                is_completed=True
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
                is_completed=True,
                is_fiscalized=False,
                created_at__date__gte=week_ago
            ).count(),
        }

        # Cache for 2 minutes
        cache.set(cache_key, stats, 120)

    # Sales trend (last 30 days) - cached separately
    trend_cache_key = f'sales_trend_{request.user.id}'
    sales_trend = cache.get(trend_cache_key)

    if not sales_trend:
        sales_trend = []
        for i in range(30):
            date = today - timedelta(days=i)
            daily_sales = Sale.objects.filter(
                store__in=stores,
                created_at__date=date,
                is_completed=True
            ).aggregate(
                total=Sum('total_amount'),
                count=Count('id')
            )
            sales_trend.insert(0, {
                'date': date.strftime('%Y-%m-%d'),
                'amount': float(daily_sales['total'] or 0),
                'count': daily_sales['count'] or 0
            })

        cache.set(trend_cache_key, sales_trend, 300)  # 5 minutes

    # Top selling products (this month) - cached
    top_products_key = f'top_products_{request.user.id}'
    top_products = cache.get(top_products_key)

    if not top_products:
        top_products = SaleItem.objects.filter(
            sale__store__in=stores,
            sale__created_at__date__gte=month_ago,
            sale__is_completed=True
        ).values('product__name', 'product__sku').annotate(
            total_quantity=Sum('quantity'),
            total_revenue=Sum('total_price')
        ).order_by('-total_revenue')[:10]

        cache.set(top_products_key, list(top_products), 300)

    # Recent generated reports
    recent_reports = GeneratedReport.objects.filter(
        generated_by=request.user,
        status='COMPLETED'
    ).select_related('report').order_by('-generated_at')[:5]

    # Favorite saved reports
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
    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    sales_data = []
    summary_stats = {}
    chart_data = []

    if form.is_valid():
        # Extract filter parameters
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')
        group_by = form.cleaned_data.get('group_by', 'date')

        # Check cache
        cache_key = f'sales_report_{request.user.id}_{start_date}_{end_date}_{store_filter}_{group_by}'
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
            chart_data = sales_data[:50]  # Limit chart data

            # Cache results
            cache.set(cache_key, {
                'sales_data': sales_data,
                'summary_stats': summary_stats,
                'chart_data': chart_data
            }, 300)  # 5 minutes

        # Log access with schema_name
        from .tasks import log_report_access
        schema_name = get_current_schema()
        log_report_access.delay(
            saved_report.id if saved_report.id else 0,
            request.user.id,
            schema_name,  # Pass schema name
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

    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    products_data = []
    summary_stats = {}

    if form.is_valid():
        # Extract serialized form data
        form_data = form.get_serialized_data()

        cache_key = f'product_performance_{request.user.id}_{hash(str(form_data))}'
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
            # Save the temporary report to the database to ensure it has a primary key
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

    if user_can_access_all_stores(request.user):
        stores = Store.objects.filter(is_active=True)
    else:
        stores = request.user.stores.filter(is_active=True)

    inventory_data = []
    summary_stats = {}
    alerts = []

    if form.is_valid():
        # Extract serialized form data
        form_data = form.get_serialized_data()

        cache_key = f'inventory_status_{request.user.id}_{hash(str(form_data))}'
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
            saved_report.save()  # Save the temporary report to ensure it has a primary key

            generator = ReportGeneratorService(request.user, saved_report)
            report_data = generator.generate(**form_data)

            inventory_data = report_data.get('inventory', [])
            summary_stats = report_data.get('summary', {})
            alerts = report_data.get('alerts', [])

            cache.set(cache_key, {
                'inventory_data': inventory_data,
                'summary_stats': summary_stats,
                'alerts': alerts
            }, 180)  # 3 minutes - shorter cache for inventory

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


logger = logging.getLogger(__name__)
from django.db import connection


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
            is_completed=True
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
            is_completed=True
        ).aggregate(total=Sum('total_amount'))['total'] or 0

        last_year_sales = Sale.objects.filter(
            store__in=stores,
            created_at__year=today.year - 1,
            created_at__month=month,
            is_completed=True
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
        sale__is_completed=True
    ).values('product__name').annotate(
        revenue=Sum('total_price'),
        quantity=Sum('quantity')
    ).order_by('-revenue')[:10]

    # Store performance comparison
    store_performance = Sale.objects.filter(
        store__in=stores,
        created_at__date__gte=last_30_days,
        is_completed=True
    ).values('store__name', 'store__company__name').annotate(
        revenue=Sum('total_amount'),
        transactions=Count('id'),
        avg_transaction=Avg('total_amount')
    ).order_by('-revenue')

    # Customer insights (if customer data available)
    customer_stats = Sale.objects.filter(
        store__in=stores,
        created_at__date__gte=last_30_days,
        is_completed=True,
        customer__isnull=False
    ).aggregate(
        unique_customers=Count('customer', distinct=True),
        avg_customer_spend=Avg('total_amount')
    )

    # Payment method breakdown
    payment_methods = Sale.objects.filter(
        store__in=stores,
        created_at__date__gte=last_30_days,
        is_completed=True
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
            is_completed=True
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

