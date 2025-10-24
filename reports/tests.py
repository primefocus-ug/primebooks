from django.test import TestCase

# Create your tests here.



#
#
#
#
# @login_required
# @permission_required('reports.view_savedreport')
# def tax_report(request):
#     """Tax report for EFRIS compliance."""
#     form = ReportFilterForm(request.GET or None, user=request.user)
#
#     # Get user's accessible stores
#     if request.user.is_superuser or request.user.user_type == 'SUPER_ADMIN':
#         stores = Store.objects.filter(is_active=True)
#     else:
#         stores = request.user.stores.filter(is_active=True)
#
#     tax_data = []
#     summary_stats = {}
#
#     if form.is_valid():
#         # Extract serialized form data
#         form_data = form.get_serialized_data()
#
#         # Build queryset
#         queryset = SaleItem.objects.filter(
#             sale__store__in=stores,
#             sale__is_completed=True
#         )
#
#         if form_data.get('start_date'):
#             queryset = queryset.filter(sale__created_at__date__gte=form_data['start_date'])
#         if form_data.get('end_date'):
#             queryset = queryset.filter(sale__created_at__date__lte=form_data['end_date'])
#         if form_data.get('store'):
#             queryset = queryset.filter(sale__store=form_data['store'])
#
#         # Tax breakdown by rate
#         tax_data = queryset.values('tax_rate').annotate(
#             tax_rate_display=Case(
#                 When(tax_rate='A', then=Value('Standard (18%)')),
#                 When(tax_rate='B', then=Value('Zero Rate (0%)')),
#                 When(tax_rate='C', then=Value('Exempt')),
#                 When(tax_rate='D', then=Value('Deemed (18%)')),
#                 When(tax_rate='E', then=Value('Excise Duty')),
#                 default=Value('Unknown'),
#                 output_field=CharField()
#             ),
#             total_sales=Sum('total_price'),
#             total_tax=Sum('tax_amount'),
#             transaction_count=Count('sale', distinct=True),
#             item_count=Count('id')
#         ).order_by('tax_rate')
#
#         # Summary statistics
#         summary_stats = queryset.aggregate(
#             total_sales_amount=Sum('total_price'),
#             total_tax_collected=Sum('tax_amount'),
#             total_items=Count('id'),
#             total_transactions=Count('sale', distinct=True)
#         )
#
#         # EFRIS compliance stats
#         efris_stats = Sale.objects.filter(
#             store__in=stores,
#             is_completed=True
#         )
#
#         if form_data.get('start_date'):
#             efris_stats = efris_stats.filter(created_at__date__gte=form_data['start_date'])
#         if form_data.get('end_date'):
#             efris_stats = efris_stats.filter(created_at__date__lte=form_data['end_date'])
#         if form_data.get('store'):
#             efris_stats = efris_stats.filter(store=form_data['store'])
#
#         summary_stats['efris_fiscalized'] = efris_stats.filter(is_fiscalized=True).count()
#         summary_stats['efris_pending'] = efris_stats.filter(is_fiscalized=False).count()
#         summary_stats['efris_compliance_rate'] = (
#                 summary_stats['efris_fiscalized'] /
#                 (summary_stats['efris_fiscalized'] + summary_stats['efris_pending']) * 100
#         ) if (summary_stats['efris_fiscalized'] + summary_stats['efris_pending']) > 0 else 0
#
#     context = {
#         'form': form,
#         'tax_data': tax_data,
#         'summary_stats': summary_stats,
#         'stores': stores,
#     }
#
#     return render(request, 'reports/tax_report.html', context)
#
#
# @login_required
# @permission_required('reports.add_savedreport')
# def z_report(request):
#     """Daily Z-Report for end-of-day summary."""
#     form = ReportFilterForm(request.GET or None, user=request.user)
#
#     # Get user's accessible stores
#     if request.user.is_superuser or request.user.user_type == 'SUPER_ADMIN':
#         stores = Store.objects.filter(is_active=True)
#     else:
#         stores = request.user.stores.filter(is_active=True)
#
#     report_data = {}
#
#     if form.is_valid():
#         # Extract serialized form data
#         form_data = form.get_serialized_data()
#         start_date = form_data.get('start_date') or timezone.now().date()
#         end_date = form_data.get('end_date') or start_date
#         store_filter = form_data.get('store')
#
#         queryset = Sale.objects.filter(
#             store__in=stores,
#             is_completed=True,
#             created_at__date__gte=start_date,
#             created_at__date__lte=end_date
#         )
#
#         if store_filter:
#             queryset = queryset.filter(store=store_filter)
#
#         # Z-Report summary
#         report_data = {
#             'period_start': start_date,
#             'period_end': end_date,
#             'total_sales': queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
#             'total_transactions': queryset.count(),
#             'total_tax': queryset.aggregate(Sum('tax_amount'))['tax_amount__sum'] or 0,
#             'total_discount': queryset.aggregate(Sum('discount_amount'))['discount_amount__sum'] or 0,
#             'payment_breakdown': queryset.values('payment_method').annotate(
#                 count=Count('id'),
#                 amount=Sum('total_amount')
#             ).order_by('payment_method'),
#             'hourly_breakdown': queryset.extra(
#                 select={'hour': "EXTRACT(hour FROM created_at)"}
#             ).values('hour').annotate(
#                 count=Count('id'),
#                 amount=Sum('total_amount')
#             ).order_by('hour'),
#         }
#
#         # Refunds and voids
#         report_data['refunds'] = queryset.filter(is_refunded=True).aggregate(
#             count=Count('id'),
#             amount=Sum('total_amount')
#         )
#
#         report_data['voids'] = queryset.filter(is_voided=True).aggregate(
#             count=Count('id'),
#             amount=Sum('total_amount')
#         )
#
#     context = {
#         'form': form,
#         'report_data': report_data,
#         'stores': stores,
#     }
#
#     return render(request, 'reports/z_report.html', context)
#
#
# @login_required
# @permission_required('reports.add_savedreport')
# def efris_compliance_report(request):
#     """EFRIS compliance status report."""
#     form = ReportFilterForm(request.GET or None, user=request.user)
#
#     # Get user's accessible stores
#     if request.user.is_superuser or request.user.user_type == 'SUPER_ADMIN':
#         stores = Store.objects.filter(is_active=True)
#     else:
#         stores = request.user.stores.filter(is_active=True)
#
#     compliance_data = {}
#
#     if form.is_valid():
#         # Extract serialized form data
#         form_data = form.get_serialized_data()
#         start_date = form_data.get('start_date')
#         end_date = form_data.get('end_date')
#         store_filter = form_data.get('store')
#
#         # Build queryset
#         queryset = Sale.objects.filter(
#             store__in=stores,
#             is_completed=True
#         )
#
#         if start_date:
#             queryset = queryset.filter(created_at__date__gte=start_date)
#         if end_date:
#             queryset = queryset.filter(created_at__date__lte=end_date)
#         if store_filter:
#             queryset = queryset.filter(store=store_filter)
#
#         total_sales = queryset.count()
#         fiscalized_sales = queryset.filter(is_fiscalized=True).count()
#         pending_sales = total_sales - fiscalized_sales
#
#         compliance_data = {
#             'total_sales': total_sales,
#             'fiscalized_sales': fiscalized_sales,
#             'pending_sales': pending_sales,
#             'compliance_rate': (fiscalized_sales / total_sales * 100) if total_sales > 0 else 0,
#
#             'store_breakdown': queryset.values('store__name').annotate(
#                 total=Count('id'),
#                 fiscalized=Count('id', filter=Q(is_fiscalized=True)),
#                 pending=Count('id', filter=Q(is_fiscalized=False))
#             ).order_by('-total'),
#
#             'daily_breakdown': queryset.extra(
#                 select={'date': "DATE(created_at)"}
#             ).values('date').annotate(
#                 total=Count('id'),
#                 fiscalized=Count('id', filter=Q(is_fiscalized=True)),
#                 pending=Count('id', filter=Q(is_fiscalized=False))
#             ).order_by('-date'),
#         }
#
#     context = {
#         'form': form,
#         'compliance_data': compliance_data,
#         'stores': stores,
#     }
#
#     return render(request, 'reports/efris_compliance.html', context)
#
#
# @login_required
# @permission_required('reports.add_savedreport')
# def cashier_performance_report(request):
#     """Cashier performance report."""
#     form = ReportFilterForm(request.GET or None, user=request.user)
#
#     # Get user's accessible stores
#     if request.user.is_superuser or request.user.user_type == 'SUPER_ADMIN':
#         stores = Store.objects.filter(is_active=True)
#         cashiers = CustomUser.objects.filter(
#             user_type__in=['CASHIER', 'MANAGER', 'EMPLOYEE'],
#             is_active=True
#         )
#     else:
#         stores = request.user.stores.filter(is_active=True)
#         store_ids = stores.values_list('id', flat=True)
#         cashiers = CustomUser.objects.filter(
#             stores__id__in=store_ids,
#             is_active=True
#         ).distinct()
#
#     performance_data = []
#
#     if form.is_valid():
#         # Extract serialized form data
#         form_data = form.get_serialized_data()
#         start_date = form_data.get('start_date')
#         end_date = form_data.get('end_date')
#         store_filter = form_data.get('store')
#
#         # Build queryset
#         queryset = Sale.objects.filter(
#             store__in=stores,
#             is_completed=True,
#             created_by__in=cashiers
#         )
#
#         if start_date:
#             queryset = queryset.filter(created_at__date__gte=start_date)
#         if end_date:
#             queryset = queryset.filter(created_at__date__lte=end_date)
#         if store_filter:
#             queryset = queryset.filter(store=store_filter)
#
#         performance_data = queryset.values(
#             'created_by__first_name',
#             'created_by__last_name',
#             'created_by__username',
#             'store__name'
#         ).annotate(
#             total_sales=Sum('total_amount'),
#             transaction_count=Count('id'),
#             avg_transaction=Avg('total_amount'),
#             total_items=Sum('items__quantity'),
#         ).order_by('-total_sales')
#
#     context = {
#         'form': form,
#         'performance_data': performance_data,
#         'stores': stores,
#         'cashiers': cashiers,
#     }
#
#     return render(request, 'reports/cashier_performance.html', context)
#
#
# @login_required
# @permission_required('reports.view_savedreport')
# def run_saved_report(request, report_id):
#     """Execute a saved report configuration."""
#     saved_report = get_object_or_404(SavedReport, id=report_id)
#
#     # Check permissions
#     if not (request.user.is_superuser or request.user.user_type == 'SUPER_ADMIN' or
#             saved_report.created_by == request.user or saved_report.is_shared):
#         raise PermissionDenied
#
#     # Serialize date fields in filters
#     def serialize_dates(obj):
#         from datetime import date, datetime
#         if isinstance(obj, (date, datetime)):
#             return obj.isoformat()
#         return obj
#
#     serialized_filters = {k: serialize_dates(v) for k, v in (saved_report.filters or {}).items()}
#
#     # Redirect to appropriate report view based on report type
#     report_urls = {
#         'SALES_SUMMARY': 'reports:sales_summary',
#         'PRODUCT_PERFORMANCE': 'reports:product_performance',
#         'INVENTORY_STATUS': 'reports:inventory_status',
#         'TAX_REPORT': 'reports:tax_report',
#         'Z_REPORT': 'reports:z_report',
#         'EFRIS_COMPLIANCE': 'reports:efris_compliance',
#         'PRICE_LOOKUP': 'reports:price_lookup',
#     }
#
#     url = report_urls.get(saved_report.report_type, 'reports:dashboard')
#
#     # Add saved report filters as URL parameters
#     query_string = '&'.join([f"{k}={v}" for k, v in serialized_filters.items()])
#
#     if query_string:
#         return redirect(f"{reverse(url)}?{query_string}")
#     else:
#         return redirect(url)