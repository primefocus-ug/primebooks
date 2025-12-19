from django.core.cache import cache
from django.db.models import Sum, Count, Avg, F, Q, Value, Case, When,Max
from django.utils import timezone
import time
import logging
from typing import Dict, Any, Optional
from datetime import date, datetime
from decimal import Decimal
from sales.models import Sale, SaleItem
from inventory.models import Stock, Product, StockMovement
from stores.models import Store
from expenses.models import Expense, ExpenseCategory
from ..models import SavedReport, GeneratedReport, ReportAccessLog
from django.db.models.functions import TruncDate
logger = logging.getLogger(__name__)


class ReportGeneratorService:
    """Main service for generating reports with caching and optimization"""

    def __init__(self, user, report):
        self.user = user
        self.report = report
        self.start_time = time.time()

    def get_accessible_stores(self):
        """Get stores accessible to the user"""
        from stores.models import Store
        if self.user.is_superuser or self.user.primary_role and user.primary_role.priority >= 90:
            return Store.objects.filter(is_active=True)
        return self.user.stores.filter(is_active=True)

    def get_cache_key(self, **kwargs) -> str:
        """Generate unique cache key for report"""
        # Convert non-serializable objects
        serializable_kwargs = {}
        for key, value in kwargs.items():
            if isinstance(value, (date, datetime)):
                serializable_kwargs[key] = value.isoformat()
            elif isinstance(value, Decimal):
                serializable_kwargs[key] = float(value)
            elif hasattr(value, 'id'):  # Django model instance
                serializable_kwargs[key] = value.id
            else:
                serializable_kwargs[key] = value

        return self.report.get_cache_key(self.user.id, **serializable_kwargs)

    def get_cached_results(self, **kwargs) -> Optional[Dict]:
        """Retrieve cached report results"""
        if not self.report.enable_caching:
            return None

        cache_key = self.get_cache_key(**kwargs)
        cached_data = cache.get(cache_key)

        if cached_data:
            logger.info(f"Cache hit for report {self.report.id}")
            return cached_data

        logger.info(f"Cache miss for report {self.report.id}")
        return None

    def cache_results(self, data: Dict, **kwargs):
        """Cache report results"""
        if not self.report.enable_caching:
            return

        cache_key = self.get_cache_key(**kwargs)
        cache.set(cache_key, data, self.report.cache_duration)
        logger.info(f"Cached report {self.report.id} for {self.report.cache_duration}s")

    def generate(self, **kwargs) -> Dict[str, Any]:
        """Generate report with intelligent caching"""
        # Check cache first
        cached_results = self.get_cached_results(**kwargs)
        if cached_results:
            cached_results['from_cache'] = True
            return cached_results

        # Generate fresh data
        logger.info(f"Generating fresh report: {self.report.name}")

        # Route to appropriate generator
        generator_map = {
            'SALES_SUMMARY': self._generate_sales_summary,
            'PRODUCT_PERFORMANCE': self._generate_product_performance,
            'INVENTORY_STATUS': self._generate_inventory_status,
            'TAX_REPORT': self._generate_tax_report,
            'Z_REPORT': self._generate_z_report,
            'EFRIS_COMPLIANCE': self._generate_efris_compliance,
            'CASHIER_PERFORMANCE': self._generate_cashier_performance,
            'PROFIT_LOSS': self._generate_profit_loss,
            'STOCK_MOVEMENT': self._generate_stock_movement,
            'PRICE_LOOKUP': self._generate_price_lookup,
            'CUSTOMER_ANALYTICS': self._generate_customer_analytics,
            'EXPENSE_REPORT': self._generate_expense_report,
            'EXPENSE_ANALYTICS': self._generate_expense_analytics,
            'CUSTOM': self._generate_custom,
        }

        generator = generator_map.get(self.report.report_type)
        if not generator:
            raise ValueError(f"Unknown report type: {self.report.report_type}")

        # Generate data
        results = generator(**kwargs)

        # Add metadata
        results['metadata'] = {
            'generated_at': timezone.now().isoformat(),
            'generated_by': self.user.get_full_name(),
            'generation_time': time.time() - self.start_time,
            'from_cache': False,
            'report_name': self.report.name,
            'report_type': self.report.get_report_type_display(),
        }

        # Cache results
        self.cache_results(results, **kwargs)

        # Update execution count
        self.report.increment_execution_count()

        return results

    def _generate_sales_summary(self, **kwargs) -> Dict:
        """Generate sales summary report with optimized queries - FIXED"""
        from sales.models import Sale, SaleItem

        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')
        group_by = kwargs.get('group_by', 'date')

        stores = self.get_accessible_stores()

        # Build optimized queryset
        queryset = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID']
        ).select_related('store', 'store__company', 'created_by')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Summary statistics with single query
        summary = queryset.aggregate(
            total_sales=Sum('total_amount'),
            total_transactions=Count('id'),
            avg_transaction=Avg('total_amount'),
            total_tax=Sum('tax_amount'),
            total_discount=Sum('discount_amount'),
        )

        if group_by == 'date':
            grouped_data = list(queryset.extra(
                select={'date': "DATE(created_at)"}
            ).values('date').annotate(
                total_amount=Sum('total_amount'),
                transaction_count=Count('id'),
                total_tax=Sum('tax_amount'),
            ).order_by('date'))

            # Calculate avg_amount in Python to avoid double aggregation
            for day in grouped_data:
                day['avg_amount'] = (day['total_amount'] / day['transaction_count']) if day['transaction_count'] else 0

        elif group_by == 'store':
            grouped_data = list(queryset.values(
                'store__name', 'store__code', 'store__company__name'
            ).annotate(
                total_amount=Sum('total_amount'),
                transaction_count=Count('id'),
                total_tax=Sum('tax_amount'),
            ).order_by('-total_amount'))

            # Calculate avg_amount in Python
            for store in grouped_data:
                store['avg_amount'] = (store['total_amount'] / store['transaction_count']) if store[
                    'transaction_count'] else 0

        elif group_by == 'payment_method':
            grouped_data = list(queryset.values('payment_method').annotate(
                total_amount=Sum('total_amount'),
                transaction_count=Count('id'),
            ).order_by('-total_amount'))

            # Calculate avg_amount in Python
            for pm in grouped_data:
                pm['avg_amount'] = (pm['total_amount'] / pm['transaction_count']) if pm['transaction_count'] else 0

        elif group_by == 'hour':
            grouped_data = list(queryset.extra(
                select={'hour': "EXTRACT(hour FROM created_at)"}
            ).values('hour').annotate(
                total_amount=Sum('total_amount'),
                transaction_count=Count('id'),
            ).order_by('hour'))

            # Calculate avg_amount in Python
            for hour in grouped_data:
                hour['avg_amount'] = (hour['total_amount'] / hour['transaction_count']) if hour[
                    'transaction_count'] else 0
        else:
            grouped_data = []

        # Top products in period
        top_products = list(SaleItem.objects.filter(
            sale__in=queryset,
            sale__status__in=['COMPLETED', 'PAID']
        ).values(
            'product__name', 'product__sku'
        ).annotate(
            quantity=Sum('quantity'),
            revenue=Sum('total_price')
        ).order_by('-revenue')[:10])

        # Payment method breakdown
        payment_methods = list(queryset.values('payment_method').annotate(
            count=Count('id'),
            amount=Sum('total_amount')
        ).order_by('-amount'))

        # Calculate percentages
        total_amount = summary['total_sales'] or 0
        for pm in payment_methods:
            pm['percentage'] = (pm['amount'] / total_amount * 100) if total_amount > 0 else 0

        return {
            'summary': summary,
            'grouped_data': grouped_data,
            'top_products': top_products,
            'payment_methods': payment_methods,
            'filters': kwargs,
        }

    def _generate_custom(self, **kwargs) -> Dict:
        """Fallback for custom reports"""
        return {
            'message': 'Custom report type. Please configure specific parameters.',
            'filters': kwargs,
        }

    def _generate_expense_report(self, **kwargs) -> Dict:
        """Generate expense tracking report"""
        from django.db.models import F, Sum, Count, Avg
        from django.db import connection

        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')
        category_id = kwargs.get('category_id')
        status_filter = kwargs.get('status')
        payment_method_filter = kwargs.get('payment_method')

        stores = self.get_accessible_stores()

        queryset = Expense.objects.select_related(
            'category', 'store', 'created_by', 'approved_by', 'paid_by'
        ).prefetch_related('attachments')

        # Apply filters
        if start_date:
            queryset = queryset.filter(expense_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(expense_date__lte=end_date)
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        if category_id:
            queryset = queryset.filter(category_id=category_id)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if payment_method_filter:
            queryset = queryset.filter(payment_method=payment_method_filter)

        # Status counts - calculate total_amount in Python since it's a property
        status_counts_data = {}
        for expense in queryset:
            status = expense.status
            if status not in status_counts_data:
                status_counts_data[status] = {'count': 0, 'total_amount': 0}
            status_counts_data[status]['count'] += 1
            status_counts_data[status]['total_amount'] += float(expense.total_amount)

        status_counts = [{'status': status, 'count': data['count'], 'total_amount': data['total_amount']}
                         for status, data in status_counts_data.items()]

        # Category breakdown - also needs Python calculation
        category_breakdown_data = {}
        for expense in queryset:
            category_name = expense.category.name if expense.category else 'Uncategorized'
            color_code = expense.category.color_code if expense.category else '#6c757d'
            icon = expense.category.icon if expense.category else ''

            if category_name not in category_breakdown_data:
                category_breakdown_data[category_name] = {
                    'category__name': category_name,
                    'category__color_code': color_code,
                    'category__icon': icon,
                    'expense_count': 0,
                    'total_amount': 0,
                    'avg_amount': 0
                }

            category_breakdown_data[category_name]['expense_count'] += 1
            category_breakdown_data[category_name]['total_amount'] += float(expense.total_amount)

        # Calculate average for each category
        for data in category_breakdown_data.values():
            if data['expense_count'] > 0:
                data['avg_amount'] = data['total_amount'] / data['expense_count']

        category_breakdown = list(category_breakdown_data.values())

        # Store breakdown
        store_breakdown_data = {}
        for expense in queryset:
            store_name = expense.store.name if expense.store else 'No Store'
            if store_name not in store_breakdown_data:
                store_breakdown_data[store_name] = {
                    'store__name': store_name,
                    'expense_count': 0,
                    'total_amount': 0
                }
            store_breakdown_data[store_name]['expense_count'] += 1
            store_breakdown_data[store_name]['total_amount'] += float(expense.total_amount)

        store_breakdown = list(store_breakdown_data.values())

        # Payment method breakdown
        payment_breakdown_data = {}
        for expense in queryset:
            method = expense.payment_method or 'Unknown'
            if method not in payment_breakdown_data:
                payment_breakdown_data[method] = {
                    'payment_method': method,
                    'count': 0,
                    'total_amount': 0
                }
            payment_breakdown_data[method]['count'] += 1
            payment_breakdown_data[method]['total_amount'] += float(expense.total_amount)

        payment_breakdown = list(payment_breakdown_data.values())

        # Expense list with detailed data - calculate total_amount in Python
        expenses = []
        for expense in queryset.order_by('-expense_date')[:500]:  # Limit to 500
            expenses.append({
                'id': expense.id,
                'expense_number': expense.expense_number,
                'title': expense.title,
                'description': expense.description,
                'category__name': expense.category.name if expense.category else 'Uncategorized',
                'category__color_code': expense.category.color_code if expense.category else '#6c757d',
                'store__name': expense.store.name if expense.store else 'No Store',
                'created_by__first_name': expense.created_by.first_name if expense.created_by else '',
                'created_by__last_name': expense.created_by.last_name if expense.created_by else '',
                'amount': float(expense.amount),
                'currency': expense.currency,
                'tax_amount': float(expense.tax_amount),
                'total_amount': float(expense.total_amount),  # This is the property
                'expense_date': expense.expense_date,
                'status': expense.status,
                'payment_method': expense.payment_method,
                'vendor_name': expense.vendor_name,
                'reference_number': expense.reference_number,
                'approved_by__first_name': expense.approved_by.first_name if expense.approved_by else '',
                'approved_by__last_name': expense.approved_by.last_name if expense.approved_by else '',
                'paid_by__first_name': expense.paid_by.first_name if expense.paid_by else '',
                'paid_by__last_name': expense.paid_by.last_name if expense.paid_by else '',
                'is_reimbursable': expense.is_reimbursable,
                'is_recurring': expense.is_recurring,
                'due_date': expense.due_date,
                'rejection_reason': expense.rejection_reason,
                'notes': expense.notes,
            })

        # Calculate summaries
        total_amount = sum(float(expense.total_amount) for expense in queryset)
        total_expenses = queryset.count()
        total_tax = sum(float(expense.tax_amount) for expense in queryset)

        summary = {
            'total_expenses': total_expenses,
            'total_amount': total_amount,
            'total_tax': total_tax,
            'avg_expense': total_amount / total_expenses if total_expenses > 0 else 0,
            'pending_expenses': queryset.filter(status='SUBMITTED').count(),
            'overdue_expenses': queryset.filter(
                status='APPROVED',
                due_date__lt=timezone.now().date()
            ).count(),
        }

        # Monthly trend - use PostgreSQL-compatible date extraction
        # Check database backend
        vendor = connection.vendor

        if vendor == 'postgresql':
            # PostgreSQL: Use TO_CHAR or EXTRACT
            monthly_trend = list(queryset.extra(
                select={'month': "TO_CHAR(expense_date, 'YYYY-MM')"}
            ).values('month').annotate(
                count=Count('id'),
                total=Sum(F('amount') + F('tax_amount'))
            ).order_by('month')[:12])
        elif vendor == 'mysql':
            # MySQL: Use DATE_FORMAT
            monthly_trend = list(queryset.extra(
                select={'month': "DATE_FORMAT(expense_date, '%%Y-%%m')"}
            ).values('month').annotate(
                count=Count('id'),
                total=Sum(F('amount') + F('tax_amount'))
            ).order_by('month')[:12])
        else:
            # Fallback: Use Django's TruncMonth
            from django.db.models.functions import TruncMonth
            monthly_trend = list(queryset.annotate(
                month=TruncMonth('expense_date')
            ).values('month').annotate(
                count=Count('id'),
                total=Sum(F('amount') + F('tax_amount'))
            ).order_by('month')[:12])
            # Format the month string
            for item in monthly_trend:
                if isinstance(item['month'], (datetime, date)):
                    item['month'] = item['month'].strftime('%Y-%m')

        return {
            'expenses': expenses,
            'summary': summary,
            'status_counts': status_counts,
            'category_breakdown': category_breakdown,
            'store_breakdown': store_breakdown,
            'payment_breakdown': payment_breakdown,
            'monthly_trend': monthly_trend,
            'filters': kwargs,
        }

    def _generate_expense_analytics(self, **kwargs) -> Dict:
        """Generate expense analytics and insights report"""
        from django.db.models.functions import TruncMonth, TruncWeek
        from django.db.models import F, Sum, Count, Avg
        from django.db import connection

        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')

        stores = self.get_accessible_stores()

        queryset = Expense.objects.filter(status='PAID').select_related('category', 'store')

        if start_date:
            queryset = queryset.filter(expense_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(expense_date__lte=end_date)
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Monthly trend with comparison - calculate total as amount + tax_amount
        monthly_data = list(queryset.annotate(
            month=TruncMonth('expense_date')
        ).values('month').annotate(
            total=Sum(F('amount') + F('tax_amount')),  # Calculate total here
            count=Count('id'),
            avg=Avg('amount')
        ).order_by('month')[:12])

        # Format month strings
        for item in monthly_data:
            if isinstance(item['month'], (datetime, date)):
                item['month'] = item['month'].strftime('%Y-%m')

        # Weekly pattern
        weekly_data = list(queryset.annotate(
            week=TruncWeek('expense_date')
        ).values('week').annotate(
            total=Sum(F('amount') + F('tax_amount'))
        ).order_by('week')[:8])

        # Format week strings
        for item in weekly_data:
            if isinstance(item['week'], (datetime, date)):
                item['week'] = item['week'].strftime('%Y-%m-%d')

        # Top categories - calculate in Python
        category_data = {}
        for expense in queryset:
            category_name = expense.category.name if expense.category else 'Uncategorized'
            color_code = expense.category.color_code if expense.category else '#6c757d'
            total_amount = float(expense.amount) + float(expense.tax_amount)

            if category_name not in category_data:
                category_data[category_name] = {
                    'category__name': category_name,
                    'category__color_code': color_code,
                    'total': 0,
                    'count': 0,
                    'avg': 0
                }

            category_data[category_name]['total'] += total_amount
            category_data[category_name]['count'] += 1

        # Calculate averages
        for data in category_data.values():
            if data['count'] > 0:
                data['avg'] = data['total'] / data['count']

        top_categories = sorted(category_data.values(), key=lambda x: x['total'], reverse=True)[:10]

        # Vendor analysis
        vendor_data = {}
        for expense in queryset:
            if expense.vendor_name:
                vendor = expense.vendor_name
                total_amount = float(expense.amount) + float(expense.tax_amount)

                if vendor not in vendor_data:
                    vendor_data[vendor] = {
                        'vendor_name': vendor,
                        'total': 0,
                        'count': 0
                    }

                vendor_data[vendor]['total'] += total_amount
                vendor_data[vendor]['count'] += 1

        top_vendors = sorted(vendor_data.values(), key=lambda x: x['total'], reverse=True)[:10]

        # Payment method analysis
        payment_data = {}
        for expense in queryset:
            if expense.payment_method:
                method = expense.payment_method
                total_amount = float(expense.amount) + float(expense.tax_amount)

                if method not in payment_data:
                    payment_data[method] = {
                        'payment_method': method,
                        'total': 0,
                        'count': 0
                    }

                payment_data[method]['total'] += total_amount
                payment_data[method]['count'] += 1

        payment_methods = sorted(payment_data.values(), key=lambda x: x['total'], reverse=True)

        # Recurring expenses analysis
        recurring_total = 0
        recurring_count = 0
        for expense in queryset.filter(is_recurring=True):
            recurring_total += float(expense.amount) + float(expense.tax_amount)
            recurring_count += 1

        recurring_expenses = {
            'total': recurring_total,
            'count': recurring_count
        }

        # Budget vs actual by category
        budget_analysis = []
        categories = ExpenseCategory.objects.filter(is_active=True)

        for category in categories:
            category_expenses = queryset.filter(category=category)
            total_spent = sum(float(expense.amount) + float(expense.tax_amount)
                              for expense in category_expenses)
            budget_analysis.append({
                'category': category.name,
                'monthly_budget': float(category.monthly_budget) if category.monthly_budget else None,
                'total_spent': total_spent,
                'budget_utilization': (total_spent / float(category.monthly_budget) * 100)
                if category.monthly_budget and float(category.monthly_budget) > 0 else None,
            })

        # Summary insights
        total_spent = sum(float(expense.amount) + float(expense.tax_amount) for expense in queryset)
        expense_count = queryset.count()

        summary_insights = {
            'total_spent': total_spent,
            'avg_monthly_spending': total_spent / len(monthly_data) if monthly_data else 0,
            'most_expensive_category': top_categories[0]['category__name'] if top_categories else None,
            'top_vendor': top_vendors[0]['vendor_name'] if top_vendors else None,
            'recurring_expenses_percentage': (recurring_count / expense_count * 100)
            if expense_count > 0 else 0,
        }

        return {
            'monthly_data': monthly_data,
            'weekly_data': weekly_data,
            'top_categories': top_categories,
            'top_vendors': top_vendors,
            'payment_methods': payment_methods,
            'recurring_expenses': recurring_expenses,
            'budget_analysis': budget_analysis,
            'summary_insights': summary_insights,
            'filters': kwargs,
        }

    def _generate_customer_analytics(self, **kwargs) -> Dict:
        """Generate customer analytics report - NEW"""
        from sales.models import Sale, SaleItem
        from customers.models import Customer  # Adjust import based on your model

        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')

        stores = self.get_accessible_stores()

        # Build queryset
        queryset = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID'],
            customer__isnull=False  # Only sales with customer data
        ).select_related('customer', 'store')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Customer metrics
        customer_data = list(queryset.values(
            'customer__id',
            'customer__name',
            'customer__email',
            'customer__phone'
        ).annotate(
            total_purchases=Count('id'),
            total_spent=Sum('total_amount'),
            avg_purchase=Sum('total_amount') / Count('id'),
            last_purchase=Max('created_at')
        ).order_by('-total_spent'))

        # Calculate in Python
        for customer in customer_data:
            customer['avg_purchase'] = (
                    customer['total_spent'] / customer['total_purchases']
            ) if customer['total_purchases'] else 0

        # Summary
        summary = {
            'total_customers': queryset.values('customer').distinct().count(),
            'total_revenue': queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
            'avg_customer_value': 0,
            'repeat_customers': queryset.values('customer').annotate(
                purchase_count=Count('id')
            ).filter(purchase_count__gt=1).count()
        }

        if summary['total_customers'] > 0:
            summary['avg_customer_value'] = summary['total_revenue'] / summary['total_customers']

        # Top products per customer segment
        top_products = list(SaleItem.objects.filter(
            sale__in=queryset
        ).values(
            'product__name'
        ).annotate(
            quantity=Sum('quantity'),
            revenue=Sum('total_price')
        ).order_by('-revenue')[:10])

        return {
            'customers': customer_data,
            'summary': summary,
            'top_products': top_products,
            'filters': kwargs,
        }

    def _generate_stock_movement(self, **kwargs) -> Dict:
        """Generate stock movement report - ALREADY PROVIDED"""
        from inventory.models import StockMovement

        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')
        movement_type = kwargs.get('movement_type')

        stores = self.get_accessible_stores()

        queryset = StockMovement.objects.filter(
            store__in=stores
        ).select_related('product', 'store', 'created_by')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(store_id=store_id)
        if movement_type:
            queryset = queryset.filter(movement_type=movement_type)

        # Movement details
        movements = []
        for movement in queryset[:500]:  # Limit to 500
            movements.append({
                'id': movement.id,
                'product_name': movement.product.name,
                'product_sku': movement.product.sku,
                'store_name': movement.store.name,
                'movement_type': movement.movement_type,
                'quantity': movement.quantity,
                'reference_number': movement.reference_number,
                'created_at': movement.created_at.isoformat(),
                'created_by': movement.created_by.get_full_name() if movement.created_by else None,
                'notes': movement.notes
            })

        # Summary by type
        summary = list(queryset.values('movement_type').annotate(
            total_quantity=Sum('quantity'),
            movement_count=Count('id')
        ).order_by('movement_type'))

        return {
            'movements': movements,
            'summary': summary,
            'filters': kwargs,
        }

    def _generate_cashier_performance(self, **kwargs) -> Dict:
        """Generate cashier performance report - ALREADY PROVIDED"""
        from sales.models import Sale

        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')

        stores = self.get_accessible_stores()

        queryset = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID']
        ).select_related('created_by', 'store')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Cashier performance
        performance = list(queryset.values(
            'created_by__id',
            'created_by__first_name',
            'created_by__last_name',
            'created_by__username',
            'store__name'
        ).annotate(
            total_sales=Sum('total_amount'),
            transaction_count=Count('id'),
            total_items=Count('items'),
            total_discount=Sum('discount_amount'),
            refund_count=Count('id', filter=Q(is_refunded=True)),
        ).order_by('-total_sales'))

        # Calculate metrics in Python
        for cashier in performance:
            if cashier['transaction_count'] > 0:
                cashier['avg_transaction'] = cashier['total_sales'] / cashier['transaction_count']
                cashier['items_per_transaction'] = cashier['total_items'] / cashier['transaction_count']
                cashier['refund_rate'] = (cashier['refund_count'] / cashier['transaction_count']) * 100
            else:
                cashier['avg_transaction'] = 0
                cashier['items_per_transaction'] = 0
                cashier['refund_rate'] = 0

        # Summary
        summary = {
            'total_cashiers': queryset.values('created_by').distinct().count(),
            'total_sales': queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or 0,
            'total_transactions': queryset.count(),
        }

        if summary['total_cashiers'] > 0:
            summary['avg_per_cashier'] = summary['total_sales'] / summary['total_cashiers']
        else:
            summary['avg_per_cashier'] = 0

        return {
            'performance': performance,
            'summary': summary,
            'filters': kwargs,
        }

    def _generate_profit_loss(self, **kwargs) -> Dict:
        """Generate profit and loss statement - ALREADY PROVIDED"""
        from sales.models import SaleItem

        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')

        stores = self.get_accessible_stores()

        # Revenue from sales
        sales_queryset = SaleItem.objects.filter(
            sale__store__in=stores,
            sale__status__in=['COMPLETED', 'PAID']
        ).select_related('sale', 'product')

        if start_date:
            sales_queryset = sales_queryset.filter(sale__created_at__date__gte=start_date)
        if end_date:
            sales_queryset = sales_queryset.filter(sale__created_at__date__lte=end_date)
        if store_id:
            sales_queryset = sales_queryset.filter(sale__store_id=store_id)

        # Calculate revenue and costs
        financial_summary = sales_queryset.aggregate(
            gross_revenue=Sum('total_price'),
            cost_of_goods_sold=Sum(F('product__cost_price') * F('quantity')),
            total_tax=Sum('tax_amount'),
        )

        # Get discount from sales
        from sales.models import Sale
        discount_sum = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID']
        )
        if start_date:
            discount_sum = discount_sum.filter(created_at__date__gte=start_date)
        if end_date:
            discount_sum = discount_sum.filter(created_at__date__lte=end_date)
        if store_id:
            discount_sum = discount_sum.filter(store_id=store_id)

        total_discount = discount_sum.aggregate(Sum('discount_amount'))['discount_amount__sum'] or 0

        # Calculate profit metrics
        gross_revenue = financial_summary['gross_revenue'] or 0
        cogs = financial_summary['cost_of_goods_sold'] or 0
        tax = financial_summary['total_tax'] or 0
        discount = total_discount

        gross_profit = gross_revenue - cogs
        net_revenue = gross_revenue - discount
        net_profit = gross_profit - tax

        profit_loss = {
            'revenue': {
                'gross_revenue': float(gross_revenue),
                'discounts': float(discount),
                'net_revenue': float(net_revenue),
            },
            'costs': {
                'cost_of_goods_sold': float(cogs),
                'tax': float(tax),
                'total_costs': float(cogs + tax),
            },
            'profit': {
                'gross_profit': float(gross_profit),
                'gross_margin': (gross_profit / gross_revenue * 100) if gross_revenue > 0 else 0,
                'net_profit': float(net_profit),
                'net_margin': (net_profit / gross_revenue * 100) if gross_revenue > 0 else 0,
            }
        }

        # Category-wise profit
        category_profit = list(sales_queryset.values(
            'product__category__name'
        ).annotate(
            revenue=Sum('total_price'),
            cost=Sum(F('product__cost_price') * F('quantity')),
            quantity=Sum('quantity')
        ).order_by('-revenue'))

        for cat in category_profit:
            revenue = cat['revenue'] or 0
            cost = cat['cost'] or 0
            cat['profit'] = float(revenue - cost)
            cat['margin'] = ((revenue - cost) / revenue * 100) if revenue > 0 else 0

        return {
            'profit_loss': profit_loss,
            'category_profit': category_profit,
            'filters': kwargs,
        }


    def _generate_price_lookup(self, **kwargs) -> Dict:
        """Generate price lookup report - NEW"""
        from inventory.models import Product, Stock
        from django.db.models import Sum

        search_query = kwargs.get('search', '')
        category_id = kwargs.get('category_id')

        stores = self.get_accessible_stores()

        # Build product queryset
        products = Product.objects.filter(is_active=True)

        if search_query:
            products = products.filter(
                Q(name__icontains=search_query) |
                Q(sku__icontains=search_query) |
                Q(barcode__icontains=search_query)
            )

        if category_id:
            products = products.filter(category_id=category_id)

        # Get stock information for each product
        products_with_stock = []
        for product in products[:100]:  # Limit to 100
            stock_info = Stock.objects.filter(
                product=product,
                store__in=stores
            ).values('store__name', 'store__id').annotate(
                quantity=Sum('quantity')
            )

            products_with_stock.append({
                'product_id': product.id,
                'product_name': product.name,
                'sku': product.sku,
                'barcode': product.barcode,
                'category': product.category.name if product.category else None,
                'selling_price': float(product.selling_price),
                'cost_price': float(product.cost_price),
                'stock_info': list(stock_info),
                'total_stock': sum([s['quantity'] for s in stock_info])
            })

        return {
            'products': products_with_stock,
            'filters': kwargs,
        }

    def _generate_product_performance(self, **kwargs) -> Dict:
        """Generate product performance report"""
        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')
        category_id = kwargs.get('category_id')
        limit = kwargs.get('limit', 100)

        stores = self.get_accessible_stores()

        queryset = SaleItem.objects.filter(
            sale__store__in=stores,
            sale__status__in=['COMPLETED', 'PAID']
        ).select_related('product', 'product__category', 'sale__store')

        if start_date:
            queryset = queryset.filter(sale__created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(sale__created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(sale__store_id=store_id)
        if category_id:
            queryset = queryset.filter(product__category_id=category_id)

        # Product performance with profit calculation
        products = list(queryset.values(
            'product__id',
            'product__name',
            'product__sku',
            'product__category__name',
            'product__selling_price',
            'product__cost_price'
        ).annotate(
            total_quantity=Sum('quantity'),
            total_revenue=Sum('total_price'),
            total_cost=Sum(F('product__cost_price') * F('quantity')),
            avg_price=Avg('unit_price'),
            transaction_count=Count('sale', distinct=True),
            total_tax=Sum('tax_amount')
        ).order_by('-total_revenue')[:limit])

        # Calculate profit and margin
        for product in products:
            cost = product['total_cost'] or 0
            revenue = product['total_revenue'] or 0
            product['total_profit'] = revenue - cost
            product['profit_margin'] = ((revenue - cost) / revenue * 100) if revenue > 0 else 0

        # Summary statistics
        summary = {
            'total_products': queryset.values('product').distinct().count(),
            'total_quantity_sold': queryset.aggregate(Sum('quantity'))['quantity__sum'] or 0,
            'total_revenue': queryset.aggregate(Sum('total_price'))['total_price__sum'] or 0,
            'total_cost': queryset.aggregate(
                total_cost=Sum(F('product__cost_price') * F('quantity'))
            )['total_cost'] or 0,
        }
        summary['total_profit'] = summary['total_revenue'] - summary['total_cost']
        summary['avg_profit_margin'] = (
            (summary['total_profit'] / summary['total_revenue'] * 100)
            if summary['total_revenue'] > 0 else 0
        )

        # Category breakdown
        category_performance = list(queryset.values(
            'product__category__name'
        ).annotate(
            quantity=Sum('quantity'),
            revenue=Sum('total_price'),
            product_count=Count('product', distinct=True)
        ).order_by('-revenue'))

        return {
            'products': products,
            'summary': summary,
            'category_performance': category_performance,
            'filters': kwargs,
        }

    def _generate_inventory_status(self, **kwargs) -> Dict:
        """Generate inventory status report"""
        store_id = kwargs.get('store_id')
        category_id = kwargs.get('category_id')
        status_filter = kwargs.get('status')

        stores = self.get_accessible_stores()

        queryset = Stock.objects.filter(
            store__in=stores
        ).select_related('product', 'store', 'product__category')

        if store_id:
            queryset = queryset.filter(store_id=store_id)
        if category_id:
            queryset = queryset.filter(product__category_id=category_id)

        # Apply status filter
        if status_filter == 'low_stock':
            queryset = queryset.filter(quantity__lte=F('low_stock_threshold'), quantity__gt=0)
        elif status_filter == 'out_of_stock':
            queryset = queryset.filter(quantity=0)
        elif status_filter == 'in_stock':
            queryset = queryset.filter(quantity__gt=F('low_stock_threshold'))

        # Annotate with status and value
        inventory = list(queryset.annotate(
            stock_value=F('quantity') * F('product__cost_price'),
            retail_value=F('quantity') * F('product__selling_price'),
            status=Case(
                When(quantity=0, then=Value('out_of_stock')),
                When(quantity__lte=F('low_stock_threshold'), then=Value('low_stock')),
                default=Value('in_stock'),
            )
        ).values(
            'id', 'product__name', 'product__sku', 'product__category__name',
            'store__name', 'quantity', 'low_stock_threshold',
            'product__cost_price', 'product__selling_price', 'stock_value',
            'retail_value', 'status', 'last_import_update'
        ).order_by('product__name'))

        # Summary statistics
        summary = queryset.aggregate(
            total_products=Count('id'),
            total_quantity=Sum('quantity'),
            total_stock_value=Sum(F('quantity') * F('product__cost_price')),
            total_retail_value=Sum(F('quantity') * F('product__selling_price')),
            low_stock_count=Count('id', filter=Q(
                quantity__lte=F('low_stock_threshold'),
                quantity__gt=0
            )),
            out_of_stock_count=Count('id', filter=Q(quantity=0)),
        )

        # Alerts for low stock items
        alerts = list(queryset.filter(
            quantity__lte=F('low_stock_threshold'),
            quantity__gt=0
        ).values(
            'product__name', 'product__sku', 'store__name',
            'quantity', 'low_stock_threshold',
        ).order_by('quantity')[:20])

        # Category breakdown
        category_summary = list(queryset.values(
            'product__category__name'
        ).annotate(
            product_count=Count('id'),
            total_quantity=Sum('quantity'),
            stock_value=Sum(F('quantity') * F('product__cost_price'))
        ).order_by('-stock_value'))

        return {
            'inventory': inventory,
            'summary': summary,
            'alerts': alerts,
            'category_summary': category_summary,
            'filters': kwargs,
        }

    def _generate_tax_report(self, **kwargs) -> Dict:
        """Generate tax report for EFRIS compliance"""
        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')

        stores = self.get_accessible_stores()

        queryset = SaleItem.objects.filter(
            sale__store__in=stores,
            sale__status__in=['COMPLETED', 'PAID']
        ).select_related('sale', 'sale__store', 'product')

        if start_date:
            queryset = queryset.filter(sale__created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(sale__created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(sale__store_id=store_id)

        # Tax breakdown by rate
        tax_breakdown = list(queryset.values('tax_rate').annotate(
            tax_rate_display=Case(
                When(tax_rate='A', then=Value('Standard (18%)')),
                When(tax_rate='B', then=Value('Zero Rate (0%)')),
                When(tax_rate='C', then=Value('Exempt')),
                When(tax_rate='D', then=Value('Deemed (18%)')),
                When(tax_rate='E', then=Value('Excise Duty')),
                default=Value('Unknown'),
            ),
            total_sales=Sum('total_price'),
            total_tax=Sum('tax_amount'),
            transaction_count=Count('sale', distinct=True),
            item_count=Count('id')
        ).order_by('tax_rate'))

        # Summary
        summary = queryset.aggregate(
            total_sales_amount=Sum('total_price'),
            total_tax_collected=Sum('tax_amount'),
            total_items=Count('id'),
            total_transactions=Count('sale', distinct=True)
        )

        # EFRIS compliance check
        sales_queryset = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID']
        )
        if start_date:
            sales_queryset = sales_queryset.filter(created_at__date__gte=start_date)
        if end_date:
            sales_queryset = sales_queryset.filter(created_at__date__lte=end_date)
        if store_id:
            sales_queryset = sales_queryset.filter(store_id=store_id)

        efris_stats = sales_queryset.aggregate(
            total_sales=Count('id'),
            fiscalized=Count('id', filter=Q(is_fiscalized=True)),
            pending=Count('id', filter=Q(is_fiscalized=False)),
        )
        efris_stats['compliance_rate'] = (
            (efris_stats['fiscalized'] / efris_stats['total_sales'] * 100)
            if efris_stats['total_sales'] > 0 else 0
        )

        # Daily tax summary
        daily_tax = list(
            queryset
            .annotate(date=TruncDate('sale__created_at'))
            .values('date')
            .annotate(
                total_sales=Sum('total_price'),
                total_tax=Sum('tax_amount'),
                transaction_count=Count('sale', distinct=True)
            )
            .order_by('date')
        )

        return {
            'tax_breakdown': tax_breakdown,
            'summary': summary,
            'efris_stats': efris_stats,
            'daily_tax': daily_tax,
            'filters': kwargs,
        }

    def _generate_z_report(self, **kwargs) -> Dict:
        """Generate Z-Report (end of day summary)"""
        report_date = kwargs.get('report_date', timezone.now().date())
        store_id = kwargs.get('store_id')

        stores = self.get_accessible_stores()

        # Base queryset for daily sales
        queryset = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID'],
            created_at__date=report_date
        ).select_related('store', 'created_by')

        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Main summary - FIXED: Aggregate directly on queryset
        summary = queryset.aggregate(
            total_sales=Sum('total_amount'),
            total_transactions=Count('id'),
            total_tax=Sum('tax_amount'),
            total_discount=Sum('discount_amount'),
        )

        # Calculate average transaction manually
        if summary['total_transactions'] > 0:
            summary['avg_transaction'] = summary['total_sales'] / summary['total_transactions']
        else:
            summary['avg_transaction'] = 0

        # Payment method breakdown - FIXED: Use proper aggregation
        payment_breakdown = list(
            queryset.values('payment_method')
            .annotate(
                count=Count('id'),
                amount=Sum('total_amount')
            )
            .order_by('payment_method')
        )

        # Hourly breakdown
        hourly_breakdown = list(
            queryset.extra(
                select={'hour': "EXTRACT(hour FROM created_at)"}
            )
            .values('hour')
            .annotate(
                count=Count('id'),
                amount=Sum('total_amount')
            )
            .order_by('hour')
        )

        # Cashier performance - FIXED: Calculate average in Python
        cashier_performance_raw = list(
            queryset.values(
                'created_by__id',
                'created_by__first_name',
                'created_by__last_name',
                'created_by__username'
            )
            .annotate(
                transaction_count=Count('id'),
                total_amount=Sum('total_amount')
            )
            .order_by('-total_amount')
        )

        # Calculate average transaction per cashier in Python
        cashier_performance = []
        for cashier in cashier_performance_raw:
            cashier_data = dict(cashier)
            if cashier['transaction_count'] > 0:
                cashier_data['avg_transaction'] = cashier['total_amount'] / cashier['transaction_count']
            else:
                cashier_data['avg_transaction'] = 0
            cashier_performance.append(cashier_data)

        # Refunds and voids
        refunds = queryset.filter(is_refunded=True).aggregate(
            count=Count('id'),
            amount=Sum('total_amount')
        )

        voids = queryset.filter(is_voided=True).aggregate(
            count=Count('id'),
            amount=Sum('total_amount')
        )

        # Top products sold today
        top_products = list(
            SaleItem.objects.filter(
                sale__in=queryset
            )
            .values(
                'product__name',
                'product__sku'
            )
            .annotate(
                quantity=Sum('quantity'),
                revenue=Sum('total_price')
            )
            .order_by('-revenue')[:10]
        )

        # Additional metrics for the template
        first_sale = queryset.order_by('created_at').first()
        last_sale = queryset.order_by('-created_at').first()

        if first_sale and last_sale:
            operating_hours = (last_sale.created_at - first_sale.created_at).seconds // 3600
            if operating_hours == 0:
                operating_hours = 1
        else:
            operating_hours = 0

        # Calculate net sales
        net_sales = (summary['total_sales'] or 0) - (summary['total_discount'] or 0) - (summary['total_tax'] or 0)

        return {
            'report_date': report_date.isoformat(),
            'summary': summary,
            'payment_breakdown': payment_breakdown,
            'hourly_breakdown': hourly_breakdown,
            'cashier_performance': cashier_performance,
            'refunds': refunds,
            'voids': voids,
            'top_products': top_products,
            'filters': kwargs,
            'first_sale_time': first_sale.created_at.time().strftime('%H:%M') if first_sale else '08:00',
            'last_sale_time': last_sale.created_at.time().strftime('%H:%M') if last_sale else '20:00',
            'operating_hours': operating_hours,
            'net_sales': net_sales,
            'max_hourly_amount': max([hour.get('amount', 0) for hour in hourly_breakdown], default=0),
        }

    def _generate_efris_compliance(self, **kwargs) -> Dict:
        """Generate EFRIS compliance report"""
        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')

        stores = self.get_accessible_stores()

        # ✅ FIXED: Use status field instead of is_completed
        # Completed sales are those with status 'COMPLETED' or 'PAID'
        completed_statuses = ['COMPLETED', 'PAID']

        queryset = Sale.objects.filter(
            store__in=stores,
            status__in=completed_statuses  # ✅ Filter by status
        ).select_related('store')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Overall compliance
        # ✅ FIXED: Replace is_completed=False check with status not in completed_statuses
        compliance = queryset.aggregate(
            total_sales=Count('id'),
            fiscalized=Count('id', filter=Q(is_fiscalized=True)),
            pending=Count('id', filter=Q(is_fiscalized=False)),
            # ✅ Count sales that are not in completed statuses
            failed=Count('id', filter=~Q(status__in=completed_statuses)),
        )
        compliance['compliance_rate'] = (
            (compliance['fiscalized'] / compliance['total_sales'] * 100)
            if compliance['total_sales'] > 0 else 0
        )

        # Store-wise breakdown
        store_breakdown = list(queryset.values(
            'store__name', 'store__code', 'store__efris_device_number'
        ).annotate(
            total=Count('id'),
            fiscalized=Count('id', filter=Q(is_fiscalized=True)),
            pending=Count('id', filter=Q(is_fiscalized=False)),
            # ✅ Count sales that are not in completed statuses
            failed=Count('id', filter=~Q(status__in=completed_statuses)),
        ).order_by('-total'))

        for store in store_breakdown:
            total = store['total']
            store['compliance_rate'] = (
                (store['fiscalized'] / total * 100) if total > 0 else 0
            )

        # Daily compliance trend
        daily_breakdown = list(queryset.extra(
            select={'date': "DATE(created_at)"}
        ).values('date').annotate(
            total=Count('id'),
            fiscalized=Count('id', filter=Q(is_fiscalized=True)),
            pending=Count('id', filter=Q(is_fiscalized=False)),
        ).order_by('-date'))

        for day in daily_breakdown:
            total = day['total']
            day['compliance_rate'] = (
                (day['fiscalized'] / total * 100) if total > 0 else 0
            )

        # Failed fiscalization details
        # ✅ FIXED: Filter by status not in completed statuses
        failed_sales = list(queryset.filter(
            ~Q(status__in=completed_statuses)  # Sales not completed
        ).values(
            'id', 'document_number', 'store__name', 'total_amount',  # ✅ Changed invoice_number to document_number
            'created_at', 'status'  # ✅ Added status to see why it failed
        ).order_by('-created_at')[:50])

        return {
            'compliance': compliance,
            'store_breakdown': store_breakdown,
            'daily_breakdown': daily_breakdown,
            'failed_sales': failed_sales,
            'filters': kwargs,
            'completed_statuses': completed_statuses,  # ✅ Added for reference
        }
