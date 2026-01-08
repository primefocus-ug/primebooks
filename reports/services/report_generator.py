from django.core.cache import cache
from django.db.models import Sum, Count, Avg, F, Q, Value, Case, When,Max,Min
from django.utils import timezone
import time
import logging
from typing import Dict, Any, Optional
from datetime import date, datetime
from decimal import Decimal
from sales.models import Sale, SaleItem
from inventory.models import Stock, Product, StockMovement
from stores.models import Store
from django.db import models,connection
from expenses.models import Expense,Budget
from django.db.models.functions import TruncMonth, TruncDate, ExtractWeekDay, TruncWeek, TruncDay
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
        if self.user.is_superuser or (hasattr(self.user, 'primary_role') and
                                      self.user.primary_role and
                                      self.user.primary_role.priority >= 90):
            return Store.objects.filter(is_active=True)
        return self.user.stores.filter(is_active=True)

    def get_cache_key(self, **kwargs) -> str:
        """Generate unique cache key for report with tenant isolation"""
        import hashlib
        import json

        schema_name = connection.schema_name
        serializable_kwargs = {}

        for key, value in kwargs.items():
            if isinstance(value, (date, datetime)):
                serializable_kwargs[key] = value.isoformat()
            elif isinstance(value, Decimal):
                serializable_kwargs[key] = float(value)
            elif hasattr(value, 'id'):
                serializable_kwargs[key] = value.id
            else:
                serializable_kwargs[key] = value

        param_string = json.dumps(serializable_kwargs, sort_keys=True, default=str)
        hash_input = f"{schema_name}:{self.report.id}:{self.user.id}:{param_string}"

        return f"report:{hashlib.md5(hash_input.encode()).hexdigest()}"

    def get_cached_results(self, **kwargs) -> Optional[Dict]:
        """Retrieve cached report results"""
        if not self.report.enable_caching:
            return None

        cache_key = self.get_cache_key(**kwargs)
        cached_data = cache.get(cache_key)

        if cached_data:
            logger.info(f"Cache hit for report {self.report.id}")
            return cached_data

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
        cached_results = self.get_cached_results(**kwargs)
        if cached_results:
            cached_results['from_cache'] = True
            return cached_results

        logger.info(f"Generating fresh report: {self.report.name}")

        generator_map = {
            'SALES_SUMMARY': self._generate_sales_summary,
            'PRICE_LOOKUP': self._generate_price_lookup,
            'EFRIS_COMPLIANCE': self._generate_efris_compliance,
            'PRODUCT_PERFORMANCE': self._generate_product_performance,
            'INVENTORY_STATUS': self._generate_inventory_status,
            'PROFIT_LOSS': self._generate_profit_loss,
            'EXPENSE_REPORT': self._generate_expense_report,
            'EXPENSE_ANALYTICS': self._generate_expense_analytics,
            'Z_REPORT': self._generate_z_report,
            'CASHIER_PERFORMANCE': self._generate_cashier_performance,
            'STOCK_MOVEMENT': self._generate_stock_movement,
            'CUSTOMER_ANALYTICS': self._generate_customer_analytics,
            'CUSTOM': self._generate_custom,
        }

        generator = generator_map.get(self.report.report_type)
        if not generator:
            raise ValueError(f"Unknown report type: {self.report.report_type}")

        results = generator(**kwargs)

        results['metadata'] = {
            'generated_at': timezone.now().isoformat(),
            'generated_by': self.user.get_full_name(),
            'generation_time': time.time() - self.start_time,
            'from_cache': False,
            'report_name': self.report.name,
            'report_type': self.report.get_report_type_display(),
        }

        self.cache_results(results, **kwargs)
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

    def generate_combined_report(self, report_types, **kwargs) -> Dict:
        """Generate a combined report with multiple report types"""
        combined_data = {}

        # Define which reports to generate
        generator_map = {
            'SALES_SUMMARY': self._generate_sales_summary,
            'PRODUCT_PERFORMANCE': self._generate_product_performance,
            'INVENTORY_STATUS': self._generate_inventory_status,
            'PROFIT_LOSS': self._generate_profit_loss,
            'EXPENSE_REPORT': self._generate_expense_report,
            'EXPENSE_ANALYTICS': self._generate_expense_analytics,
            'Z_REPORT': self._generate_z_report,
            'EFRIS_COMPLIANCE': self._generate_efris_compliance,
            'CASHIER_PERFORMANCE': self._generate_cashier_performance,
            'STOCK_MOVEMENT': self._generate_stock_movement,
            'CUSTOMER_ANALYTICS': self._generate_customer_analytics,
        }

        # Generate each requested report
        for report_type in report_types:
            if report_type in generator_map:
                try:
                    report_data = generator_map[report_type](**kwargs)
                    combined_data[report_type] = report_data
                except Exception as e:
                    logger.error(f"Error generating {report_type}: {e}")
                    combined_data[report_type] = {'error': str(e)}

        # Add custom combined analytics
        combined_data['custom_analytics'] = self._generate_custom_analytics(combined_data, **kwargs)

        # Calculate overall business health score
        combined_data['business_health'] = self._calculate_business_health(combined_data)

        return combined_data

    def _generate_custom_analytics(self, combined_data, **kwargs) -> Dict:
        """Generate custom analytics across multiple reports"""
        analytics = {
            'cross_report_insights': [],
            'key_metrics': {},
            'recommendations': []
        }

        # Extract data from different reports
        sales_data = combined_data.get('SALES_SUMMARY', {})
        profit_loss_data = combined_data.get('PROFIT_LOSS', {})
        expense_data = combined_data.get('EXPENSE_REPORT', {})
        inventory_data = combined_data.get('INVENTORY_STATUS', {})

        # Calculate cash flow (Sales - Expenses)
        if sales_data and expense_data:
            total_sales = sales_data.get('summary', {}).get('total_sales', 0) or 0
            total_expenses = expense_data.get('summary', {}).get('total_amount', 0) or 0
            cash_flow = float(total_sales) - float(total_expenses)

            analytics['key_metrics']['cash_flow'] = cash_flow
            analytics['key_metrics']['cash_flow_margin'] = (
                        cash_flow / float(total_sales) * 100) if total_sales > 0 else 0

            if cash_flow < 0:
                analytics['recommendations'].append("⚠️ Negative cash flow: Expenses exceed sales")
            else:
                analytics['recommendations'].append("✅ Positive cash flow maintained")

        # Calculate inventory turnover
        if sales_data and inventory_data:
            # This is a simplified calculation
            analytics['key_metrics']['inventory_turnover_ratio'] = "N/A"  # Would need more data

        # Profitability analysis
        if profit_loss_data:
            profit_data = profit_loss_data.get('profit_loss', {}).get('profit', {})
            net_profit = profit_data.get('net_profit', 0)
            net_margin = profit_data.get('net_margin', 0)

            analytics['key_metrics']['profitability'] = {
                'net_profit': net_profit,
                'net_margin': net_margin,
                'status': 'Profitable' if net_profit > 0 else 'Loss'
            }

        # Expense efficiency ratio
        if sales_data and expense_data:
            total_sales = sales_data.get('summary', {}).get('total_sales', 0) or 0
            total_expenses = expense_data.get('summary', {}).get('total_amount', 0) or 0

            if total_sales > 0:
                expense_ratio = (float(total_expenses) / float(total_sales)) * 100
                analytics['key_metrics']['expense_to_sales_ratio'] = expense_ratio

                if expense_ratio > 50:
                    analytics['recommendations'].append("🔴 High expense ratio: Consider cost reduction")
                elif expense_ratio > 30:
                    analytics['recommendations'].append("🟡 Moderate expense ratio: Monitor closely")
                else:
                    analytics['recommendations'].append("🟢 Healthy expense ratio")

        # Sales on credit analysis - FIXED CALL
        analytics['key_metrics']['credit_sales'] = self._calculate_credit_sales(**kwargs)

        return analytics

    def _calculate_business_health(self, combined_data) -> Dict:
        """Calculate overall business health score"""
        health_score = 0
        factors = []
        max_score = 100

        # Profitability factor (0-30 points)
        if 'PROFIT_LOSS' in combined_data:
            profit_data = combined_data['PROFIT_LOSS'].get('profit_loss', {}).get('profit', {})
            net_margin = profit_data.get('net_margin', 0)

            if net_margin > 20:
                health_score += 30
                factors.append(('✅ High profitability', 30))
            elif net_margin > 10:
                health_score += 20
                factors.append(('🟡 Moderate profitability', 20))
            elif net_margin > 0:
                health_score += 10
                factors.append(('⚪ Low profitability', 10))
            else:
                factors.append(('🔴 Loss making', 0))

        # Cash flow factor (0-25 points)
        # Would need actual cash flow calculation

        # Inventory health factor (0-20 points)
        if 'INVENTORY_STATUS' in combined_data:
            inventory_data = combined_data['INVENTORY_STATUS']
            out_of_stock = inventory_data.get('summary', {}).get('out_of_stock_count', 0)

            if out_of_stock == 0:
                health_score += 20
                factors.append(('✅ No out-of-stock items', 20))
            elif out_of_stock <= 5:
                health_score += 15
                factors.append(('🟡 Few out-of-stock items', 15))
            else:
                health_score += 5
                factors.append(('🔴 Many out-of-stock items', 5))

        # Expense control factor (0-15 points)
        if 'EXPENSE_REPORT' in combined_data:
            expense_data = combined_data['EXPENSE_REPORT']
            pending_expenses = expense_data.get('summary', {}).get('pending_expenses', 0)

            if pending_expenses == 0:
                health_score += 15
                factors.append(('✅ All expenses processed', 15))
            elif pending_expenses <= 10:
                health_score += 10
                factors.append(('🟡 Some pending expenses', 10))
            else:
                health_score += 5
                factors.append(('🔴 Many pending expenses', 5))

        # Sales trend factor (0-10 points)
        if 'SALES_SUMMARY' in combined_data:
            health_score += 10  # Simplified
            factors.append(('✅ Sales data available', 10))

        return {
            'score': health_score,
            'percentage': (health_score / max_score) * 100,
            'grade': self._get_health_grade(health_score),
            'factors': factors,
            'max_score': max_score
        }

    def _get_health_grade(self, score):
        """Convert health score to letter grade"""
        if score >= 90:
            return 'A+'
        elif score >= 80:
            return 'A'
        elif score >= 70:
            return 'B'
        elif score >= 60:
            return 'C'
        elif score >= 50:
            return 'D'
        else:
            return 'F'

    def _calculate_credit_sales(self, **kwargs):
        """Calculate sales on credit and money not paid"""
        from sales.models import Sale
        from django.db.models import Sum
        from decimal import Decimal

        stores = self.get_accessible_stores()

        # Get sales - focus on INVOICES (credit sales) and RECEIPTS
        queryset = Sale.objects.filter(
            store__in=stores,
            document_type__in=['INVOICE', 'RECEIPT']  # Only invoices and receipts for sales
        ).exclude(
            status__in=['VOIDED', 'REFUNDED', 'CANCELLED']  # Exclude voided/refunded/cancelled sales
        )

        # Apply filters
        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Calculate totals - convert to float immediately
        total_sales = float(queryset.aggregate(total=Sum('total_amount'))['total'] or Decimal('0'))

        # Paid sales: invoices with PAID payment_status OR receipts (which are always paid)
        paid_sales = float(queryset.filter(
            models.Q(payment_status='PAID') |
            models.Q(document_type='RECEIPT', status='COMPLETED')
        ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0'))

        # Credit sales: INVOICES that are COMPLETED but may not be fully paid
        credit_sales = float(
            queryset.filter(
                document_type='INVOICE',
                status='COMPLETED'
            ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        )

        # Pending sales: invoices with PENDING_PAYMENT status
        pending_sales = float(
            queryset.filter(
                document_type='INVOICE',
                status='PENDING_PAYMENT'
            ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        )

        # Partially paid sales: invoices with PARTIALLY_PAID payment status
        partial_sales = float(
            queryset.filter(
                document_type='INVOICE',
                payment_status='PARTIALLY_PAID'
            ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        )

        # Calculate overdue sales
        overdue_sales = float(
            queryset.filter(
                document_type='INVOICE',
                payment_status='OVERDUE'
            ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')
        )

        # Calculate outstanding amount based on payment_status
        # Pending + Overdue + (Partially paid * outstanding portion)
        # For partially paid, we need to calculate the actual outstanding amount
        outstanding = Decimal('0')

        # Add full amounts for pending and overdue invoices
        pending_invoices = queryset.filter(
            document_type='INVOICE',
            payment_status__in=['PENDING', 'OVERDUE']
        )
        for invoice in pending_invoices:
            outstanding += invoice.total_amount

        # For partially paid, calculate remaining amount
        partial_invoices = queryset.filter(
            document_type='INVOICE',
            payment_status='PARTIALLY_PAID'
        )
        for invoice in partial_invoices:
            amount_paid = invoice.amount_paid or Decimal('0')
            outstanding += (invoice.total_amount - amount_paid)

        # Convert to float for the return value
        outstanding_float = float(outstanding)

        # Calculate collection rate
        collection_rate = (float(paid_sales) / float(total_sales) * 100) if total_sales > 0 else 0

        return {
            'total_sales': total_sales,
            'paid_sales': paid_sales,
            'credit_sales': credit_sales,  # All invoices (COMPLETED status)
            'pending_sales': pending_sales,  # PENDING_PAYMENT status
            'partial_sales': partial_sales,  # PARTIALLY_PAID payment_status
            'overdue_sales': overdue_sales,  # OVERDUE payment_status
            'outstanding_amount': outstanding_float,
            'collection_rate': collection_rate,
            'details': {
                'total_invoices': queryset.filter(document_type='INVOICE').count(),
                'total_receipts': queryset.filter(document_type='RECEIPT').count(),
                'total_pending': queryset.filter(document_type='INVOICE', payment_status='PENDING').count(),
                'total_partial': queryset.filter(document_type='INVOICE', payment_status='PARTIALLY_PAID').count(),
                'total_overdue': queryset.filter(document_type='INVOICE', payment_status='OVERDUE').count(),
            }
        }

    def _generate_expense_report(self, **kwargs) -> Dict:
        """Generate expense report - Works with your simplified Expense model"""
        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        tag_filter = kwargs.get('tags')
        min_amount = kwargs.get('min_amount')
        max_amount = kwargs.get('max_amount')

        queryset = Expense.objects.filter(user=self.user)

        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        if min_amount:
            queryset = queryset.filter(amount__gte=min_amount)
        if max_amount:
            queryset = queryset.filter(amount__lte=max_amount)
        if tag_filter:
            tags = [t.strip() for t in tag_filter.split(',')]
            queryset = queryset.filter(tags__name__in=tags).distinct()

        expenses = []
        for expense in queryset.select_related('user').prefetch_related('tags')[:500]:
            expenses.append({
                'id': expense.id,
                'description': expense.description,
                'amount': float(expense.amount),
                'date': expense.date,
                'tags': [tag.name for tag in expense.tags.all()],
                'receipt': expense.receipt.url if expense.receipt else None,
                'receipt_filename': expense.receipt_filename if hasattr(expense, 'receipt_filename') else None,
                'notes': expense.notes,
            })

        summary = {
            'total_expenses': queryset.count(),
            'total_amount': float(queryset.aggregate(total=Sum('amount'))['total'] or 0),
            'avg_expense': float(queryset.aggregate(avg=Avg('amount'))['avg'] or 0),
            'min_amount': float(queryset.aggregate(min=Min('amount'))['min'] or 0),
            'max_amount': float(queryset.aggregate(max=Max('amount'))['max'] or 0),
        }

        # Tag breakdown
        tag_data = {}
        for expense in queryset.prefetch_related('tags'):
            for tag in expense.tags.all():
                if tag.name not in tag_data:
                    tag_data[tag.name] = {'tag_name': tag.name, 'count': 0, 'total_amount': 0}
                tag_data[tag.name]['count'] += 1
                tag_data[tag.name]['total_amount'] += float(expense.amount)

        tag_breakdown = sorted(tag_data.values(), key=lambda x: x['total_amount'], reverse=True)[:20]

        # Monthly trend
        monthly_trend = list(queryset.annotate(
            month=TruncMonth('date')
        ).values('month').annotate(
            count=Count('id'),
            total=Sum('amount')
        ).order_by('month')[:12])

        for item in monthly_trend:
            item['month'] = item['month'].strftime('%Y-%m') if item['month'] else None
            item['total'] = float(item['total'] or 0)

        return {
            'expenses': expenses,
            'summary': summary,
            'tag_breakdown': tag_breakdown,
            'monthly_trend': monthly_trend,
            'filters': kwargs,
        }

    def _generate_expense_analytics(self, **kwargs) -> Dict:
        """Generate expense analytics"""
        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        tag_filter = kwargs.get('tags')

        queryset = Expense.objects.filter(user=self.user)

        if start_date:
            queryset = queryset.filter(date__gte=start_date)
        if end_date:
            queryset = queryset.filter(date__lte=end_date)
        if tag_filter:
            tags = [t.strip() for t in tag_filter.split(',')]
            queryset = queryset.filter(tags__name__in=tags).distinct()

        # Monthly trend
        monthly_data = list(queryset.annotate(
            month=TruncMonth('date')
        ).values('month').annotate(
            count=Count('id'),
            total=Sum('amount'),
            avg=Avg('amount')
        ).order_by('month')[:12])

        for item in monthly_data:
            item['month'] = item['month'].strftime('%Y-%m') if item['month'] else None
            item['total'] = float(item['total'] or 0)
            item['avg'] = float(item['avg'] or 0)

        # Day of week analysis
        day_of_week_data = list(queryset.annotate(
            day=ExtractWeekDay('date')
        ).values('day').annotate(
            count=Count('id'),
            total=Sum('amount')
        ).order_by('day'))

        day_names = {1: 'Sunday', 2: 'Monday', 3: 'Tuesday', 4: 'Wednesday',
                     5: 'Thursday', 6: 'Friday', 7: 'Saturday'}

        day_of_week_analysis = []
        for item in day_of_week_data:
            day_of_week_analysis.append({
                'day': day_names.get(item['day'], f"Day {item['day']}"),
                'total': float(item['total'] or 0),
                'count': item['count'],
                'avg': float(item['total'] or 0) / item['count'] if item['count'] > 0 else 0
            })

        # Top tags
        tag_data = {}
        for expense in queryset.prefetch_related('tags'):
            for tag in expense.tags.all():
                if tag.name not in tag_data:
                    tag_data[tag.name] = {'tag_name': tag.name, 'total': 0, 'count': 0}
                tag_data[tag.name]['total'] += float(expense.amount)
                tag_data[tag.name]['count'] += 1

        for data in tag_data.values():
            if data['count'] > 0:
                data['avg'] = data['total'] / data['count']

        top_tags = sorted(tag_data.values(), key=lambda x: x['total'], reverse=True)[:10]

        # Recent expenses
        recent_expenses = []
        for expense in queryset.order_by('-date')[:10]:
            recent_expenses.append({
                'id': expense.id,
                'description': expense.description,
                'amount': float(expense.amount),
                'date': expense.date,
                'tags': [tag.name for tag in expense.tags.all()],
                'receipt': bool(expense.receipt),
            })

        # Budget analysis
        budget_analysis = []
        user_budgets = Budget.objects.filter(user=self.user, is_active=True)

        for budget in user_budgets:
            current_spending = float(budget.get_current_spending())
            percentage_used = float(budget.get_percentage_used())

            budget_analysis.append({
                'name': budget.name,
                'amount': float(budget.amount),
                'period': budget.get_period_display(),
                'current_spending': current_spending,
                'percentage_used': percentage_used,
                'remaining': float(budget.amount) - current_spending,
                'is_over_threshold': budget.is_over_threshold(),
                'alert_threshold': budget.alert_threshold,
                'tags': list(budget.tags.names()) if budget.tags.exists() else [],
            })

        summary = {
            'total_expenses': float(queryset.aggregate(total=Sum('amount'))['total'] or 0),
            'avg_expense': float(queryset.aggregate(avg=Avg('amount'))['avg'] or 0),
            'total_count': queryset.count(),
            'max_expense': float(queryset.aggregate(max=Max('amount'))['max'] or 0),
            'min_expense': float(queryset.aggregate(min=Min('amount'))['min'] or 0),
        }

        return {
            'monthly_data': monthly_data,
            'day_of_week_analysis': day_of_week_analysis,
            'top_tags': top_tags,
            'recent_expenses': recent_expenses,
            'budget_analysis': budget_analysis,
            'summary': summary,
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
        """Generate cashier performance report"""
        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')

        stores = self.get_accessible_stores()

        queryset = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID']
        ).select_related('created_by')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        performance = list(queryset.values(
            'created_by__id',
            'created_by__first_name',
            'created_by__last_name',
        ).annotate(
            total_sales=Sum('total_amount'),
            transaction_count=Count('id'),
        ).order_by('-total_sales'))

        for cashier in performance:
            cashier['total_sales'] = float(cashier['total_sales'] or 0)
            if cashier['transaction_count'] > 0:
                cashier['avg_transaction'] = cashier['total_sales'] / cashier['transaction_count']
            else:
                cashier['avg_transaction'] = 0

        summary = {
            'total_cashiers': len(performance),
            'total_sales': sum(c['total_sales'] for c in performance),
            'total_transactions': sum(c['transaction_count'] for c in performance),
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
        """Generate profit and loss statement"""
        from decimal import Decimal
        from django.db.models import F, Sum, Count

        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')

        stores = self.get_accessible_stores()

        # Get completed sales
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

        # Get sale items for detailed calculation
        sale_items = SaleItem.objects.filter(
            sale__in=sales_queryset,
            product__isnull=False
        ).select_related('product', 'sale')

        # Calculate revenue and COGS from sale items
        financial_data = sale_items.aggregate(
            total_revenue=Sum('total_price'),
            total_cost=Sum(F('product__cost_price') * F('quantity'),
                           output_field=models.DecimalField(max_digits=20, decimal_places=2)),
            total_tax=Sum('tax_amount'),
            total_discount=Sum('discount_amount'),
            total_items=Count('id')
        )

        # Get discounts from sales
        discount_data = sales_queryset.aggregate(
            total_discount=Sum('discount_amount')
        )

        # Calculate values
        gross_revenue = financial_data['total_revenue'] or Decimal('0')
        cogs = financial_data['total_cost'] or Decimal('0')
        tax = financial_data['total_tax'] or Decimal('0')
        discount = discount_data['total_discount'] or Decimal('0')

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
                'gross_margin': float((gross_profit / gross_revenue * 100) if gross_revenue > 0 else 0),
                'net_profit': float(net_profit),
                'net_margin': float((net_profit / gross_revenue * 100) if gross_revenue > 0 else 0),
            }
        }

        # Category-wise profit
        category_profit_raw = sale_items.values(
            'product__category__name'
        ).annotate(
            revenue=Sum('total_price'),
            cost=Sum(F('product__cost_price') * F('quantity'),
                     output_field=models.DecimalField(max_digits=20, decimal_places=2)),
            quantity=Sum('quantity')
        ).order_by('-revenue')

        category_profit = []
        for cat in category_profit_raw:
            revenue = cat['revenue'] or Decimal('0')
            cost = cat['cost'] or Decimal('0')
            category_profit.append({
                'category': cat['product__category__name'],
                'revenue': float(revenue),
                'cost': float(cost),
                'profit': float(revenue - cost),
                'margin': float(((revenue - cost) / revenue * 100) if revenue > Decimal('0') else Decimal('0')),
                'quantity': float(cat['quantity'] or Decimal('0'))
            })

        # Store-wise breakdown
        store_profit = list(sales_queryset.values(
            'store__name'
        ).annotate(
            revenue=Sum('total_amount'),
            discount=Sum('discount_amount'),
            tax=Sum('tax_amount')
        ).order_by('-revenue'))

        for store in store_profit:
            revenue = store['revenue'] or Decimal('0')
            discount = store['discount'] or Decimal('0')
            tax = store['tax'] or Decimal('0')
            # Simplified: net profit = revenue - discount - tax
            store['net_profit'] = float(revenue - discount - tax)
            store['net_margin'] = float(
                ((revenue - discount - tax) / revenue * 100) if revenue > Decimal('0') else Decimal('0'))

        return {
            'profit_loss': profit_loss,
            'category_profit': category_profit,
            'store_profit': store_profit,
            'filters': kwargs,
            'date_range': {
                'start_date': start_date,
                'end_date': end_date
            }
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

        stores = self.get_accessible_stores()

        queryset = SaleItem.objects.filter(
            sale__store__in=stores,
            sale__status__in=['COMPLETED', 'PAID'],
            product__isnull=False
        ).select_related('product', 'sale__store')

        if start_date:
            queryset = queryset.filter(sale__created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(sale__created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(sale__store_id=store_id)

        products = list(queryset.values(
            'product__id',
            'product__name',
            'product__sku',
            'product__selling_price',
        ).annotate(
            total_quantity=Sum('quantity'),
            total_revenue=Sum('total_price'),
            transaction_count=Count('sale', distinct=True),
            avg_price=Avg('unit_price'),
        ).order_by('-total_revenue')[:100])

        # Convert Decimals
        for product in products:
            product['total_revenue'] = float(product['total_revenue'] or 0)
            product['avg_price'] = float(product['avg_price'] or 0)
            product['product__selling_price'] = float(product['product__selling_price'] or 0)

        summary = {
            'total_products': len(products),
            'total_quantity_sold': sum(p['total_quantity'] for p in products),
            'total_revenue': sum(p['total_revenue'] for p in products),
        }

        return {
            'products': products,
            'summary': summary,
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

        # FIXED: Use ExpressionWrapper for calculations
        from django.db.models import ExpressionWrapper

        inventory = list(queryset.annotate(
            stock_value=ExpressionWrapper(
                F('quantity') * F('product__cost_price'),
                output_field=models.DecimalField(max_digits=20, decimal_places=2)
            ),
            retail_value=ExpressionWrapper(
                F('quantity') * F('product__selling_price'),
                output_field=models.DecimalField(max_digits=20, decimal_places=2)
            ),
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

        # FIXED: Summary calculations with proper aggregates
        summary = queryset.aggregate(
            total_products=Count('id'),
            total_quantity=Sum('quantity'),
            total_stock_value=Sum(
                ExpressionWrapper(
                    F('quantity') * F('product__cost_price'),
                    output_field=models.DecimalField(max_digits=20, decimal_places=2)
                )
            ),
            total_retail_value=Sum(
                ExpressionWrapper(
                    F('quantity') * F('product__selling_price'),
                    output_field=models.DecimalField(max_digits=20, decimal_places=2)
                )
            ),
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
            stock_value=Sum(
                ExpressionWrapper(
                    F('quantity') * F('product__cost_price'),
                    output_field=models.DecimalField(max_digits=20, decimal_places=2)
                )
            )
        ).order_by('-stock_value'))

        # Convert Decimal to float for JSON serialization
        for item in inventory:
            item['stock_value'] = float(item['stock_value'] or Decimal('0'))
            item['retail_value'] = float(item['retail_value'] or Decimal('0'))
            item['quantity'] = float(item['quantity'] or Decimal('0'))

        for key in ['total_stock_value', 'total_retail_value']:
            summary[key] = float(summary[key] or Decimal('0'))
        summary['total_quantity'] = float(summary['total_quantity'] or Decimal('0'))

        for cat in category_summary:
            cat['stock_value'] = float(cat['stock_value'] or Decimal('0'))
            cat['total_quantity'] = float(cat['total_quantity'] or Decimal('0'))

        return {
            'inventory': inventory,
            'summary': summary,
            'alerts': alerts,
            'category_summary': category_summary,
            'filters': kwargs,
        }

    def _generate_tax_report(self, **kwargs) -> Dict:
        """Generate tax report for EFRIS compliance"""
        from decimal import Decimal

        start_date = kwargs.get('start_date')
        end_date = kwargs.get('end_date')
        store_id = kwargs.get('store_id')

        stores = self.get_accessible_stores()

        # FIXED: Use Sale instead of SaleItem for better aggregation
        queryset = Sale.objects.filter(
            store__in=stores,
            status__in=['COMPLETED', 'PAID']
        ).select_related('store')

        if start_date:
            queryset = queryset.filter(created_at__date__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__date__lte=end_date)
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Summary from sales
        summary = queryset.aggregate(
            total_sales_amount=Sum('total_amount'),
            total_tax_collected=Sum('tax_amount'),
            total_transactions=Count('id'),
            total_discount=Sum('discount_amount')
        )

        # Tax breakdown by analyzing sale items
        sale_items = SaleItem.objects.filter(
            sale__in=queryset
        )

        tax_breakdown_raw = sale_items.values('tax_rate').annotate(
            total_sales=Sum('total_price'),
            total_tax=Sum('tax_amount'),
            transaction_count=Count('sale', distinct=True),
            item_count=Count('id')
        ).order_by('tax_rate')

        tax_breakdown = []
        for tax in tax_breakdown_raw:
            tax_rate_display = dict(Product.TAX_RATE_CHOICES).get(tax['tax_rate'], 'Unknown')
            tax_breakdown.append({
                'tax_rate': tax['tax_rate'],
                'tax_rate_display': tax_rate_display,
                'total_sales': float(tax['total_sales'] or Decimal('0')),
                'total_tax': float(tax['total_tax'] or Decimal('0')),
                'transaction_count': tax['transaction_count'],
                'item_count': tax['item_count'],
                'effective_rate': float(
                    (tax['total_tax'] / tax['total_sales'] * 100) if tax['total_sales'] > Decimal('0') else Decimal(
                        '0'))
            })

        # EFRIS compliance check
        efris_stats = queryset.aggregate(
            total_sales=Count('id'),
            fiscalized=Count('id', filter=Q(is_fiscalized=True)),
            pending=Count('id', filter=Q(is_fiscalized=False)),
        )
        efris_stats['compliance_rate'] = float(
            (efris_stats['fiscalized'] / efris_stats['total_sales'] * 100)
            if efris_stats['total_sales'] > 0 else 0
        )

        # Daily tax summary
        daily_tax = list(
            queryset
            .annotate(date=TruncDate('created_at'))
            .values('date')
            .annotate(
                total_sales=Sum('total_amount'),
                total_tax=Sum('tax_amount'),
                transaction_count=Count('id')
            )
            .order_by('date')
        )

        # Convert Decimal to float
        for key in ['total_sales_amount', 'total_tax_collected', 'total_discount']:
            summary[key] = float(summary[key] or Decimal('0'))

        for day in daily_tax:
            day['total_sales'] = float(day['total_sales'] or Decimal('0'))
            day['total_tax'] = float(day['total_tax'] or Decimal('0'))

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
