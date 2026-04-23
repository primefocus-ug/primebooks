from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse, FileResponse, Http404
from django.db.models import Sum, Count, Q, F, Avg,  Case, When, Value, CharField,Min,Max
from django.utils import timezone
from django.core.paginator import Paginator
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from collections import Counter, defaultdict
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.cache import cache
from django.db.models import Count
from django.db.models.functions import TruncMonth, ExtractWeekDay
from datetime import timedelta
import json
import csv
import os
import mimetypes
from django.db.models import OuterRef, Subquery
import logging
from .models import SavedReport, ReportSchedule, GeneratedReport, ReportAccessLog, ReportComparison
from .forms import (SavedReportForm, ReportScheduleForm, ReportFilterForm,
                    SalesReportForm, InventoryReportForm, ReportExportForm)
from .services.report_generator import ReportGeneratorService
from .tasks import generate_report_async, log_report_access
from sales.models import Sale, SaleItem
from inventory.models import Product, Stock, StockMovement, Category
from stores.models import Store
from expenses.models import Expense
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
@permission_required('reports.view_savedreport')
def combined_business_report(request):
    """Combined business report with multiple report types"""
    from .forms import CombinedReportForm

    # Check for export parameter
    export_format = request.GET.get('export')
    is_combined = request.GET.get('combined') == 'true'

    form = CombinedReportForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    combined_data = {}
    selected_reports = []

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')
        selected_reports = form.cleaned_data.get('report_types', [])

        # Check if user has access to selected store
        if store_filter and store_filter not in stores:
            messages.error(request, "You don't have access to the selected store.")
            return redirect('reports:combined_business')

        # Handle export
        if export_format and is_combined:
            return export_combined_report(request, selected_reports, {
                'start_date': start_date,
                'end_date': end_date,
                'store_id': store_filter.id if store_filter else None,
                'format': export_format,
                'report_name': 'Combined Business Report'
            })

        # Include schema in cache key
        schema_name = connection.schema_name
        cache_key = f'combined_report_{schema_name}_{request.user.id}_{start_date}_{end_date}_{store_filter}_{hash(str(sorted(selected_reports)))}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            combined_data = cached_result['combined_data']
        else:
            saved_report = SavedReport(
                name='Combined Business Report',
                report_type='CUSTOM',
                created_by=request.user
            )
            saved_report.save()

            from .services.report_generator import ReportGeneratorService
            generator = ReportGeneratorService(request.user, saved_report)

            filters = {
                'start_date': start_date,
                'end_date': end_date,
                'store_id': store_filter.id if store_filter else None,
            }

            # Generate combined report
            combined_data = generator.generate_combined_report(
                report_types=selected_reports,
                **filters
            )

            cache.set(cache_key, {
                'combined_data': combined_data
            }, 300)  # Cache for 5 minutes

    # Prepare data for templates
    context = {
        'form': form,
        'combined_data': combined_data,
        'selected_reports': selected_reports,
        'stores': stores,
        'report_types': [
            ('SALES_SUMMARY', 'Sales Summary'),
            ('PRODUCT_PERFORMANCE', 'Product Performance'),
            ('INVENTORY_STATUS', 'Inventory Status'),
            ('PROFIT_LOSS', 'Profit & Loss'),
            ('EXPENSE_REPORT', 'Expense Report'),
            ('Z_REPORT', 'Z-Report'),
            ('CASHIER_PERFORMANCE', 'Cashier Performance'),
            ('STOCK_MOVEMENT', 'Stock Movement'),
            ('CUSTOMER_ANALYTICS', 'Customer Analytics'),
        ]
    }

    # Handle print request
    if request.GET.get('print') == 'true':
        return render(request, 'reports/print/combined_business_report.html', context)

    return render(request, 'reports/combined_business_report.html', context)


def export_combined_report(request, report_types, filters):
    """Export combined report — now uses the narrative PDF engine."""
    from .services.comparison_engine import ComparisonEngine
    from .services.narrative_engine import build_narratives, resolve_reader_role
    from .services.currency_formatter import get_formatter
    from .services.pdf_export import PDFExportService
    from .services.excel_export import ExcelExportService
    from .services.csv_export import CSVExportService
    import json
    from django.http import HttpResponse

    try:
        saved_report = SavedReport(
            name=filters.get('report_name', 'Combined Report'),
            report_type='CUSTOM',
            created_by=request.user,
        )
        saved_report.save()

        # Comparison params from filters (with defaults)
        comparison_mode = filters.get('comparison_mode', 'auto')
        comparison_start = filters.get('comparison_start')
        comparison_end = filters.get('comparison_end')

        fmt = get_formatter(user=request.user)
        reader_role = resolve_reader_role(request.user)

        engine = ComparisonEngine(request.user, saved_report)
        result = engine.fetch(
            start_date=filters.get('start_date'),
            end_date=filters.get('end_date'),
            store_id=filters.get('store_id'),
            comparison_mode=comparison_mode,
            comparison_start=comparison_start,
            comparison_end=comparison_end,
        )

        # For combined reports the generator already built sub-report data;
        # we need to run generate_combined_report as well.
        from .services.report_generator import ReportGeneratorService
        generator = ReportGeneratorService(request.user, saved_report)
        combined_data = generator.generate_combined_report(
            report_types=report_types,
            start_date=filters.get('start_date'),
            end_date=filters.get('end_date'),
            store_id=filters.get('store_id'),
        )

        format_type = filters.get('format', 'PDF').upper()

        if format_type == 'PDF':
            # Build narratives for each sub-report type
            all_narratives = []
            for rt in report_types:
                sub_data = combined_data.get(rt, {})
                if sub_data:
                    all_narratives += build_narratives(
                        report_type=rt,
                        data=sub_data,
                        prior=result['prior'],
                        delta=result['delta'],
                        fmt=fmt,
                        period_label=result['current_label'],
                        prior_label=result['prior_label'],
                        reader_role=reader_role,
                    )

            company_info = {
                'name': request.user.company.name if request.user.company else 'Company',
            }

            buffer = PDFExportService(
                report_data=combined_data,
                report_name=filters.get('report_name', 'Combined Business Report'),
                report_type='COMBINED',
                company_info=company_info,
                narratives=all_narratives,
                fmt=fmt,
                prior_data=result['prior'],
                delta=result['delta'],
                period_label=result['current_label'],
                prior_label=result['prior_label'],
                reader_role=reader_role,
            ).generate_pdf()

            response = HttpResponse(buffer.read(), content_type='application/pdf')
            filename = f"combined_report_{timezone.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        elif format_type == 'XLSX':
            from .services.export_service import ReportExportService
            export_service = ReportExportService(combined_data, filters)
            response = export_service.export_to_excel()
            filename = f"combined_report_{timezone.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        elif format_type == 'CSV':
            from .services.export_service import ReportExportService
            export_service = ReportExportService(combined_data, filters)
            response = export_service.export_to_csv()
            filename = f"combined_report_{timezone.now().strftime('%Y%m%d_%H%M%S')}.csv"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

        elif format_type == 'JSON':
            response = HttpResponse(
                json.dumps(combined_data, indent=2, default=str),
                content_type='application/json',
            )
            filename = f"combined_report_{timezone.now().strftime('%Y%m%d_%H%M%S')}.json"
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response

    except Exception as e:
        logger.error(f'export_combined_report error: {e}', exc_info=True)
        return HttpResponse(f'Export failed: {e}', status=500)


@login_required
@permission_required('expenses.view_expense', raise_exception=False)
def expense_report(request):
    """Comprehensive expense tracking report - Updated for simplified models"""
    from .forms import ReportFilterForm

    form = ReportFilterForm(request.GET or None, user=request.user)

    expense_data = []
    summary = {}
    tag_breakdown = []
    payment_breakdown = []
    monthly_trend = []

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')

        # Additional expense-specific filters
        payment_method_filter = request.GET.get('payment_method')
        tag_filter = request.GET.get('tags')

        # Include schema in cache key
        try:
            schema_name = connection.schema_name
        except:
            schema_name = 'public'

        cache_key = f'expense_report_{schema_name}_{request.user.id}_{start_date}_{end_date}_{payment_method_filter}_{tag_filter}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            expense_data = cached_result['expense_data']
            summary = cached_result['summary']
            tag_breakdown = cached_result['tag_breakdown']
            payment_breakdown = cached_result['payment_breakdown']
            monthly_trend = cached_result['monthly_trend']
        else:
            try:
                from .models import SavedReport
                saved_report = SavedReport(
                    name='Expense Report',
                    report_type='EXPENSE_REPORT',
                    created_by=request.user
                )
                saved_report.save()
            except:
                saved_report = None

            from .services.report_generator import ReportGeneratorService
            generator = ReportGeneratorService(request.user, saved_report)

            filters = {
                'start_date': start_date,
                'end_date': end_date,
                'payment_method': payment_method_filter,
                'tags': tag_filter,
            }

            report_data = generator.generate(**filters)

            expense_data = report_data.get('expenses', [])
            summary = report_data.get('summary', {})
            tag_breakdown = report_data.get('tag_breakdown', [])
            payment_breakdown = report_data.get('payment_breakdown', [])
            monthly_trend = report_data.get('monthly_trend', [])

            cache.set(cache_key, {
                'expense_data': expense_data,
                'summary': summary,
                'tag_breakdown': tag_breakdown,
                'payment_breakdown': payment_breakdown,
                'monthly_trend': monthly_trend
            }, 300)

    # Prepare chart data
    tag_chart_data = {
        'labels': [item['tag_name'] for item in tag_breakdown[:10]],
        'amounts': [float(item['total_amount']) for item in tag_breakdown[:10]],
    }

    payment_chart_data = {
        'labels': [item['payment_method'] for item in payment_breakdown],
        'amounts': [float(item['total_amount']) for item in payment_breakdown],
    }

    monthly_chart_data = {
        'labels': [item['month'] for item in monthly_trend],
        'amounts': [float(item['total']) for item in monthly_trend],
        'counts': [item['count'] for item in monthly_trend],
    }

    context = {
        'form': form,
        'expense_data': expense_data,
        'summary': summary,
        'tag_breakdown': tag_breakdown,
        'payment_breakdown': payment_breakdown,
        'monthly_trend': monthly_trend,
        'tag_chart_data': json.dumps(tag_chart_data),
        'payment_chart_data': json.dumps(payment_chart_data),
        'monthly_chart_data': json.dumps(monthly_chart_data),
        'selected_payment_method': request.GET.get('payment_method', ''),
        'selected_tags': request.GET.get('tags', ''),
        'payment_method_choices': Expense.PAYMENT_METHODS,
    }

    return render(request, 'reports/expense_report.html', context)


@login_required
@permission_required('expenses.view_expense', raise_exception=False)
def expense_analytics(request):
    """Expense analytics and insights report - Updated for simplified models"""
    from .forms import ReportFilterForm

    form = ReportFilterForm(request.GET or None, user=request.user)

    analytics_data = {}

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        tag_filter = request.GET.get('tags')

        # Include schema in cache key
        try:
            schema_name = connection.schema_name
        except:
            schema_name = 'public'

        cache_key = f'expense_analytics_{schema_name}_{request.user.id}_{start_date}_{end_date}_{tag_filter}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            analytics_data = cached_result['analytics_data']
        else:
            try:
                from .models import SavedReport
                saved_report = SavedReport(
                    name='Expense Analytics',
                    report_type='EXPENSE_ANALYTICS',
                    created_by=request.user
                )
                saved_report.save()
            except:
                saved_report = None

            from .services.report_generator import ReportGeneratorService
            generator = ReportGeneratorService(request.user, saved_report)

            report_data = generator.generate(
                start_date=start_date,
                end_date=end_date,
                tags=tag_filter
            )

            analytics_data = report_data

            cache.set(cache_key, {
                'analytics_data': analytics_data
            }, 300)

    # Prepare chart data
    monthly_chart = {
        'labels': [item['month'] for item in analytics_data.get('monthly_data', [])],
        'amounts': [float(item['total']) for item in analytics_data.get('monthly_data', [])],
        'counts': [item['count'] for item in analytics_data.get('monthly_data', [])],
    }

    tag_chart = {
        'labels': [item['tag_name'] for item in analytics_data.get('top_tags', [])],
        'amounts': [float(item['total']) for item in analytics_data.get('top_tags', [])],
    }

    payment_chart = {
        'labels': [item['payment_method'] for item in analytics_data.get('payment_methods', [])],
        'amounts': [float(item['total']) for item in analytics_data.get('payment_methods', [])],
    }

    day_of_week_chart = {
        'labels': [item['day'] for item in analytics_data.get('day_of_week_analysis', [])],
        'amounts': [float(item['total']) for item in analytics_data.get('day_of_week_analysis', [])],
    }

    context = {
        'form': form,
        'analytics_data': analytics_data,
        'monthly_chart': json.dumps(monthly_chart),
        'tag_chart': json.dumps(tag_chart),
        'payment_chart': json.dumps(payment_chart),
        'day_of_week_chart': json.dumps(day_of_week_chart),
        'selected_tags': request.GET.get('tags', ''),
    }

    return render(request, 'reports/expense_analytics.html', context)


def get_top_tags(expenses):
    """Top tags by total amount"""
    totals = defaultdict(float)

    for expense in expenses.prefetch_related('tags'):
        for tag in expense.tags.all():
            totals[tag.name] += float(expense.amount)

    result = [{'tag_name': k, 'total': v} for k, v in totals.items()]
    return sorted(result, key=lambda x: x['total'], reverse=True)


def get_day_name(day):
    """Convert day number to day name"""
    return {
        1: 'Sunday',
        2: 'Monday',
        3: 'Tuesday',
        4: 'Wednesday',
        5: 'Thursday',
        6: 'Friday',
        7: 'Saturday',
    }.get(day, f'Day {day}')



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

            # ✅ Handle Desktop vs Web mode
            if getattr(settings, 'DESKTOP_MODE', False):
                # Desktop mode - run synchronously (no Celery)
                logger.info("Desktop mode - generating report synchronously")

                generated_report.task_id = None  # ✅ No Celery task
                generated_report.status = 'PROCESSING'
                generated_report.save()

                try:
                    # Generate report synchronously
                    from .utils import generate_report_sync
                    result = generate_report_sync(
                        report.id,
                        request.user.id,
                        schema_name,
                        **kwargs
                    )

                    generated_report.status = 'COMPLETED'
                    generated_report.file_path = result['file_path']
                    generated_report.file_size = result['file_size']
                    generated_report.save()

                    messages.success(request, 'Report generated successfully!')

                    return JsonResponse({
                        'success': True,
                        'generated_report_id': generated_report.id,
                        'download_url': generated_report.file_path,
                        'redirect_url': reverse('reports:history')
                    })

                except Exception as e:
                    logger.error(f"Report generation failed: {e}", exc_info=True)
                    generated_report.status = 'FAILED'
                    generated_report.error_message = str(e)
                    generated_report.save()

                    return JsonResponse({
                        'success': False,
                        'error': str(e)
                    }, status=400)
            else:
                # Web mode - use Celery async
                from .tasks import generate_report_async
                comparison_mode = request.POST.get('comparison_mode', 'auto')
                comparison_start = request.POST.get('comparison_start') or None
                comparison_end   = request.POST.get('comparison_end')   or None
                task = generate_report_async.delay(
                    report.id,
                    request.user.id,
                    schema_name,
                    comparison_mode=comparison_mode,
                    comparison_start = comparison_start,
                    comparison_end   = comparison_end,
                    **kwargs
                )

                generated_report.task_id = task.id
                generated_report.save()

                messages.success(
                    request,
                    f'Report generation started. You will be notified when complete.'
                )

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

    # For CUSTOM report type that is a Combined Report, handle specially
    if saved_report.report_type == 'CUSTOM':
        # Check if this is a combined report based on name or parameters
        if 'combined' in saved_report.name.lower() or 'business' in saved_report.name.lower():
            # Redirect to combined business report with saved filters
            url = 'reports:combined_business_report'

            # Get saved filters and parameters
            filters = saved_report.filters or {}
            parameters = saved_report.parameters or {}

            # Merge parameters into filters for the combined report
            for key, value in parameters.items():
                filters[key] = value

            # Build query string
            query_string = '&'.join([f"{k}={v}" for k, v in filters.items() if v])

            if query_string:
                return redirect(f"{reverse(url)}?{query_string}")
            else:
                return redirect(url)

    # For other report types, use the existing mapping
    report_urls = {
        'SALES_SUMMARY': 'reports:sales_summary',
        'PRODUCT_PERFORMANCE': 'reports:product_performance',
        'INVENTORY_STATUS': 'reports:inventory_status',
        'TAX_REPORT': 'reports:tax_report',
        'Z_REPORT': 'reports:z_report',
        'EFRIS_COMPLIANCE': 'reports:efris_compliance',
        'PRICE_LOOKUP': 'reports:price_lookup',
        'CASHIER_PERFORMANCE': 'reports:cashier_performance',
        'PROFIT_LOSS': 'reports:profit_loss',
        'STOCK_MOVEMENT': 'reports:stock_movement',
        'CUSTOMER_ANALYTICS': 'reports:customer_analytics',
        'EXPENSE_REPORT': 'reports:expense_report',
        'EXPENSE_ANALYTICS': 'reports:expense_analytics',
    }

    url = report_urls.get(saved_report.report_type, 'reports:dashboard')

    # Add saved report filters as URL parameters
    filters = saved_report.filters or {}
    query_string = '&'.join([f"{k}={v}" for k, v in filters.items() if v])

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
            # Save normally - the model handles next_scheduled calculation
            schedule = form.save()

            logger.info(
                f"Created schedule {schedule.id}: {schedule.report.name} "
                f"(frequency: {schedule.frequency}, next run: {schedule.next_scheduled})"
            )

            messages.success(
                request,
                f'Report schedule created successfully! '
                f'Next run: {schedule.next_scheduled.strftime("%Y-%m-%d %H:%M") if schedule.next_scheduled else "Not calculated"}'
            )
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
            # form.save() triggers ReportSchedule.save() which already recalculates
            # next_scheduled — do NOT call schedule.calculate_next_run() here as that
            # causes a redundant second DB write and can clobber concurrent updates.
            schedule = form.save()

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
    base_qs = GeneratedReport.objects.filter(
        report=OuterRef('report'),
        generated_by=OuterRef('generated_by')
    ).order_by('-generated_at')

    latest_ids = GeneratedReport.objects.values(
        'report', 'generated_by'
    ).annotate(
        latest_id=Subquery(base_qs.values('id')[:1])
    ).values('latest_id')

    reports = GeneratedReport.objects.filter(id__in=latest_ids)

    reports = reports.select_related('report', 'generated_by').order_by('-generated_at')

    paginator = Paginator(reports, 25)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(request, 'reports/generated_reports_history.html', {
        'page_obj': page_obj
    })



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
    """EFRIS compliance status report with detailed breakdown"""
    from .forms import ReportFilterForm

    form = ReportFilterForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    compliance_data = {}
    summary_stats = {}
    store_breakdown = []
    daily_breakdown = []
    failed_sales = []

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')

        # Check if user has access to selected store
        if store_filter and store_filter not in stores:
            messages.error(request, "You don't have access to the selected store.")
            return redirect('reports:efris_compliance')

        # Include schema in cache key
        schema_name = connection.schema_name
        cache_key = f'efris_compliance_{schema_name}_{request.user.id}_{start_date}_{end_date}_{store_filter}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            compliance_data = cached_result['compliance_data']
            summary_stats = cached_result['summary_stats']
            store_breakdown = cached_result['store_breakdown']
            daily_breakdown = cached_result['daily_breakdown']
            failed_sales = cached_result['failed_sales']
        else:
            saved_report = SavedReport(
                name='EFRIS Compliance',
                report_type='EFRIS_COMPLIANCE',
                created_by=request.user
            )
            saved_report.save()

            from .services.report_generator import ReportGeneratorService
            generator = ReportGeneratorService(request.user, saved_report)

            report_data = generator.generate(
                start_date=start_date,
                end_date=end_date,
                store_id=store_filter.id if store_filter else None
            )

            compliance_data = report_data.get('compliance', {})
            store_breakdown = report_data.get('store_breakdown', [])
            daily_breakdown = report_data.get('daily_breakdown', [])
            failed_sales = report_data.get('failed_sales', [])

            # Calculate summary stats
            summary_stats = {
                'compliance_rate': compliance_data.get('compliance_rate', 0),
                'total_sales': compliance_data.get('total_sales', 0),
                'fiscalized': compliance_data.get('fiscalized', 0),
                'pending': compliance_data.get('pending', 0),
                'failed': compliance_data.get('failed', 0),
            }

            cache.set(cache_key, {
                'compliance_data': compliance_data,
                'summary_stats': summary_stats,
                'store_breakdown': store_breakdown,
                'daily_breakdown': daily_breakdown,
                'failed_sales': failed_sales
            }, 300)  # Cache for 5 minutes

        # Log access
        from .tasks import log_report_access
        log_report_access.delay(
            0,  # No saved report ID
            request.user.id,
            schema_name,
            'VIEW',
            form.cleaned_data,
            get_client_ip(request),
            request.META.get('HTTP_USER_AGENT', '')
        )

    # Prepare data for charts
    chart_data = {
        'labels': [store['store__name'] for store in store_breakdown[:10]],
        'compliance_rates': [store.get('compliance_rate', 0) for store in store_breakdown[:10]],
        'fiscalized_counts': [store.get('fiscalized', 0) for store in store_breakdown[:10]],
        'pending_counts': [store.get('pending', 0) for store in store_breakdown[:10]],
    }

    context = {
        'form': form,
        'compliance_data': compliance_data,
        'summary_stats': summary_stats,
        'store_breakdown': store_breakdown,
        'daily_breakdown': daily_breakdown,
        'failed_sales': failed_sales,
        'chart_data': json.dumps(chart_data),
        'stores': stores,
    }

    return render(request, 'reports/efris_compliance.html', context)



@login_required
@permission_required('reports.view_savedreport')
def cashier_performance_report(request):
    """Cashier performance report with enhanced metrics"""
    form = ReportFilterForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    performance_data = []
    summary_stats = {}

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')

        # Check if user has access to selected store
        if store_filter and store_filter not in stores:
            messages.error(request, "You don't have access to the selected store.")
            return redirect('reports:cashier_performance')

        # Include schema in cache key
        schema_name = connection.schema_name
        cache_key = f'cashier_performance_{schema_name}_{request.user.id}_{start_date}_{end_date}_{store_filter}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            performance_data = cached_result['performance_data']
            summary_stats = cached_result['summary_stats']
        else:
            saved_report = SavedReport(
                name='Cashier Performance',
                report_type='CASHIER_PERFORMANCE',
                created_by=request.user
            )
            saved_report.save()

            from .services.report_generator import ReportGeneratorService
            generator = ReportGeneratorService(request.user, saved_report)

            report_data = generator.generate(
                start_date=start_date,
                end_date=end_date,
                store_id=store_filter.id if store_filter else None
            )

            performance_data = report_data.get('performance', [])
            summary_stats = report_data.get('summary', {})

            cache.set(cache_key, {
                'performance_data': performance_data,
                'summary_stats': summary_stats
            }, 300)

    # Calculate additional metrics
    for cashier in performance_data:
        cashier['name'] = f"{cashier.get('created_by__first_name', '')} {cashier.get('created_by__last_name', '')}".strip()
        cashier['username'] = cashier.get('created_by__username', 'N/A')
        cashier['store_name'] = cashier.get('store__name', 'N/A')

    # Sort by total sales
    performance_data = sorted(performance_data, key=lambda x: x.get('total_sales', 0), reverse=True)

    context = {
        'form': form,
        'performance_data': performance_data,
        'summary_stats': summary_stats,
        'stores': stores,
    }

    return render(request, 'reports/cashier_performance.html', context)

@login_required
@permission_required('reports.view_savedreport')
def profit_loss_report(request):
    """Profit and Loss statement report"""
    form = ReportFilterForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    profit_loss_data = {}
    category_profit = []
    summary = {}

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')

        # Check if user has access to selected store
        if store_filter and store_filter not in stores:
            messages.error(request, "You don't have access to the selected store.")
            return redirect('reports:profit_loss')

        # Include schema in cache key
        schema_name = connection.schema_name
        cache_key = f'profit_loss_{schema_name}_{request.user.id}_{start_date}_{end_date}_{store_filter}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            profit_loss_data = cached_result['profit_loss_data']
            category_profit = cached_result['category_profit']
            summary = cached_result['summary']
        else:
            saved_report = SavedReport(
                name='Profit & Loss',
                report_type='PROFIT_LOSS',
                created_by=request.user
            )
            saved_report.save()

            from .services.report_generator import ReportGeneratorService
            generator = ReportGeneratorService(request.user, saved_report)

            report_data = generator.generate(
                start_date=start_date,
                end_date=end_date,
                store_id=store_filter.id if store_filter else None
            )

            profit_loss_data = report_data.get('profit_loss', {})
            category_profit = report_data.get('category_profit', [])
            summary = {
                'total_revenue': profit_loss_data.get('revenue', {}).get('net_revenue', 0),
                'total_profit': profit_loss_data.get('profit', {}).get('net_profit', 0),
                'total_costs': profit_loss_data.get('costs', {}).get('total_costs', 0),
                'gross_margin': profit_loss_data.get('profit', {}).get('gross_margin', 0),
                'net_margin': profit_loss_data.get('profit', {}).get('net_margin', 0),
            }

            cache.set(cache_key, {
                'profit_loss_data': profit_loss_data,
                'category_profit': category_profit,
                'summary': summary
            }, 300)

    # Prepare chart data
    revenue_data = profit_loss_data.get('revenue', {})
    cost_data = profit_loss_data.get('costs', {})
    profit_data = profit_loss_data.get('profit', {})

    context = {
        'form': form,
        'profit_loss_data': profit_loss_data,
        'category_profit': category_profit,
        'summary': summary,
        'revenue_data': json.dumps(revenue_data),
        'cost_data': json.dumps(cost_data),
        'profit_data': json.dumps(profit_data),
        'stores': stores,
    }

    return render(request, 'reports/profit_loss.html', context)


@login_required
@permission_required('reports.view_savedreport')
def stock_movement_report(request):
    """Stock movement tracking report"""
    from .forms import ReportFilterForm

    form = ReportFilterForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    movements = []
    summary = []
    filters = {}

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')
        movement_type = request.GET.get('movement_type')

        # Check if user has access to selected store
        if store_filter and store_filter not in stores:
            messages.error(request, "You don't have access to the selected store.")
            return redirect('reports:stock_movement')

        # Include schema in cache key
        schema_name = connection.schema_name
        cache_key = f'stock_movement_{schema_name}_{request.user.id}_{start_date}_{end_date}_{store_filter}_{movement_type}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            movements = cached_result['movements']
            summary = cached_result['summary']
        else:
            saved_report = SavedReport(
                name='Stock Movement',
                report_type='STOCK_MOVEMENT',
                created_by=request.user
            )
            saved_report.save()

            from .services.report_generator import ReportGeneratorService
            generator = ReportGeneratorService(request.user, saved_report)

            filters = {
                'start_date': start_date,
                'end_date': end_date,
                'store_id': store_filter.id if store_filter else None,
                'movement_type': movement_type
            }

            report_data = generator.generate(**filters)

            movements = report_data.get('movements', [])
            summary = report_data.get('summary', [])

            cache.set(cache_key, {
                'movements': movements,
                'summary': summary
            }, 300)

    # Movement type choices (you might want to get these from your model)
    movement_types = [
        ('', 'All Types'),
        ('PURCHASE', 'Purchase'),
        ('SALE', 'Sale'),
        ('TRANSFER_IN', 'Transfer In'),
        ('TRANSFER_OUT', 'Transfer Out'),
        ('ADJUSTMENT', 'Adjustment'),
        ('RETURN', 'Return'),
        ('WASTAGE', 'Wastage'),
    ]

    # Calculate totals
    total_in = sum([m['quantity'] for m in movements if m['movement_type'] in ['PURCHASE', 'TRANSFER_IN', 'RETURN']])
    total_out = sum(
        [m['quantity'] for m in movements if m['movement_type'] in ['SALE', 'TRANSFER_OUT', 'ADJUSTMENT', 'WASTAGE']])
    net_movement = total_in - total_out

    context = {
        'form': form,
        'movements': movements,
        'summary': summary,
        'filters': filters,
        'movement_types': movement_types,
        'total_in': total_in,
        'total_out': total_out,
        'net_movement': net_movement,
        'selected_type': request.GET.get('movement_type', ''),
        'stores': stores,
    }

    return render(request, 'reports/stock_movement.html', context)


@login_required
@permission_required('reports.view_savedreport')
def price_lookup_report(request):
    """Price lookup report for products with enhanced filtering"""
    from .forms import ReportFilterForm
    from inventory.models import Category

    form = ReportFilterForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    products_data = []
    summary = {}

    if form.is_valid():
        search_query = request.GET.get('search', '')
        category_id = request.GET.get('category')
        store_filter = form.cleaned_data.get('store')

        # Check if user has access to selected store
        if store_filter and store_filter not in stores:
            messages.error(request, "You don't have access to the selected store.")
            return redirect('reports:price_lookup')

        # Include schema in cache key
        schema_name = connection.schema_name
        cache_key = f'price_lookup_{schema_name}_{request.user.id}_{search_query}_{category_id}_{store_filter}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            products_data = cached_result['products_data']
            summary = cached_result['summary']
        else:
            saved_report = SavedReport(
                name='Price Lookup',
                report_type='PRICE_LOOKUP',
                created_by=request.user
            )
            saved_report.save()

            from .services.report_generator import ReportGeneratorService
            generator = ReportGeneratorService(request.user, saved_report)

            filters = {
                'search': search_query,
                'category_id': category_id,
                'store_id': store_filter.id if store_filter else None
            }

            report_data = generator.generate(**filters)

            products_data = report_data.get('products', [])

            # Calculate summary
            if products_data:
                summary = {
                    'total_products': len(products_data),
                    'total_stock_value': sum([p.get('total_stock', 0) * p.get('cost_price', 0) for p in products_data]),
                    'total_retail_value': sum(
                        [p.get('total_stock', 0) * p.get('selling_price', 0) for p in products_data]),
                    'avg_margin': sum(
                        [((p.get('selling_price', 0) - p.get('cost_price', 0)) / p.get('selling_price', 0) * 100)
                         for p in products_data if p.get('selling_price', 0) > 0]) / len(
                        products_data) if products_data else 0,
                }

            cache.set(cache_key, {
                'products_data': products_data,
                'summary': summary
            }, 300)

    # Get all categories for filter
    categories = Category.objects.all()

    context = {
        'form': form,
        'products_data': products_data,
        'summary': summary,
        'categories': categories,
        'search_query': request.GET.get('search', ''),
        'selected_category': request.GET.get('category', ''),
        'stores': stores,
    }

    return render(request, 'reports/price_lookup.html', context)

@login_required
@permission_required('reports.view_savedreport')
def customer_analytics_report(request):
    """Customer analytics and segmentation report"""
    form = ReportFilterForm(request.GET or None, user=request.user)

    # Get user's accessible stores
    stores = get_user_accessible_stores(request.user)

    customers_data = []
    summary = {}
    top_products = []

    if form.is_valid():
        start_date = form.cleaned_data.get('start_date')
        end_date = form.cleaned_data.get('end_date')
        store_filter = form.cleaned_data.get('store')

        # Check if user has access to selected store
        if store_filter and store_filter not in stores:
            messages.error(request, "You don't have access to the selected store.")
            return redirect('reports:customer_analytics')

        # Include schema in cache key
        schema_name = connection.schema_name
        cache_key = f'customer_analytics_{schema_name}_{request.user.id}_{start_date}_{end_date}_{store_filter}'
        cached_result = cache.get(cache_key)

        if cached_result and not request.GET.get('refresh'):
            customers_data = cached_result['customers_data']
            summary = cached_result['summary']
            top_products = cached_result['top_products']
        else:
            saved_report = SavedReport(
                name='Customer Analytics',
                report_type='CUSTOMER_ANALYTICS',
                created_by=request.user
            )
            saved_report.save()

            from .services.report_generator import ReportGeneratorService
            generator = ReportGeneratorService(request.user, saved_report)

            report_data = generator.generate(
                start_date=start_date,
                end_date=end_date,
                store_id=store_filter.id if store_filter else None
            )

            customers_data = report_data.get('customers', [])
            summary = report_data.get('summary', {})
            top_products = report_data.get('top_products', [])

            cache.set(cache_key, {
                'customers_data': customers_data,
                'summary': summary,
                'top_products': top_products
            }, 300)

    # Segment customers
    segments = {
        'high_value': [c for c in customers_data if c.get('total_spent', 0) > 1000000],
        'medium_value': [c for c in customers_data if 500000 <= c.get('total_spent', 0) <= 1000000],
        'low_value': [c for c in customers_data if c.get('total_spent', 0) < 500000],
        'repeat_customers': [c for c in customers_data if c.get('total_purchases', 0) > 1],
        'new_customers': [c for c in customers_data if c.get('total_purchases', 0) == 1],
    }

    # Calculate segment statistics
    segment_stats = {
        name: {
            'count': len(customers),
            'total_spent': sum([c.get('total_spent', 0) for c in customers]),
            'avg_spent': sum([c.get('total_spent', 0) for c in customers]) / len(customers) if customers else 0
        }
        for name, customers in segments.items()
    }

    # Prepare chart data
    customer_names = [c.get('customer__name', f"Customer {c.get('customer__id', '')}") for c in customers_data[:10]]
    customer_spending = [float(c.get('total_spent', 0)) for c in customers_data[:10]]

    context = {
        'form': form,
        'customers_data': customers_data[:50],  # Limit display to 50
        'summary': summary,
        'top_products': top_products,
        'segments': segments,
        'segment_stats': segment_stats,
        'customer_names': json.dumps(customer_names),
        'customer_spending': json.dumps(customer_spending),
        'stores': stores,
    }

    return render(request, 'reports/customer_analytics.html', context)


@login_required
@permission_required('reports.view_savedreport')
def custom_report(request, report_id=None):
    """Custom report configuration and generation"""
    if report_id:
        # Load existing custom report
        saved_report = get_object_or_404(SavedReport, id=report_id)

        # Check permissions
        if not (user_can_access_all_stores(request.user) or
                saved_report.created_by == request.user or saved_report.is_shared):
            raise PermissionDenied
    else:
        saved_report = None

    if request.method == 'POST':
        form = SavedReportForm(request.POST, instance=saved_report)
        if form.is_valid():
            custom_report = form.save(commit=False)
            custom_report.report_type = 'CUSTOM'
            custom_report.created_by = request.user

            # Parse custom parameters from form
            custom_params = {}
            for key, value in request.POST.items():
                if key.startswith('custom_'):
                    param_key = key.replace('custom_', '')
                    custom_params[param_key] = value

            custom_report.parameters = custom_params
            custom_report.save()

            messages.success(request, 'Custom report saved successfully!')
            return redirect('reports:run_saved_report', report_id=custom_report.id)
    else:
        form = SavedReportForm(instance=saved_report)

    # Get available report templates
    report_templates = SavedReport.objects.filter(
        report_type__in=['SALES_SUMMARY', 'PRODUCT_PERFORMANCE', 'INVENTORY_STATUS'],
        is_shared=True
    ).values('id', 'name', 'report_type')

    context = {
        'form': form,
        'saved_report': saved_report,
        'report_templates': report_templates,
        'title': 'Create Custom Report' if not saved_report else 'Edit Custom Report',
    }

    return render(request, 'reports/custom_report_form.html', context)


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