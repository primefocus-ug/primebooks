from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views.generic import TemplateView
from django.db.models import Count, Sum, F, Q
from django.http import JsonResponse
from datetime import datetime, timedelta
from django.utils import timezone


class EnhancedStockDashboardView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """Enhanced unified stock dashboard with EFRIS integration"""
    template_name = 'inventory/enhanced_stock_dashboard.html'
    permission_required = 'inventory.view_stock'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        from inventory.models import Stock, StockMovement, Product
        from stores.models import Store

        company = self.request.tenant

        # Basic Statistics
        context['total_products'] = Stock.objects.values('product').distinct().count()
        context['total_stores'] = Store.objects.filter(is_active=True).count()
        context['out_of_stock'] = Stock.objects.filter(quantity=0).count()
        context['low_stock'] = Stock.objects.filter(
            quantity__gt=0,
            quantity__lte=F('low_stock_threshold')
        ).count()

        # EFRIS Statistics
        context['efris_products'] = Product.objects.filter(
            efris_is_uploaded=True
        ).count()

        context['stocks_needing_sync'] = Stock.objects.filter(
            product__efris_is_uploaded=True,
            efris_sync_required=True
        ).count()

        # Recent Movements
        context['recent_movements'] = StockMovement.objects.select_related(
            'product', 'store', 'created_by'
        ).order_by('-created_at')[:10]

        # Products for dropdowns (EFRIS enabled products)
        context['products'] = Product.objects.filter(
            efris_is_uploaded=True,
            is_active=True
        ).order_by('name')

        # Company info
        context['company'] = company

        return context


@login_required
def stock_dashboard_data_api(request):
    """API endpoint for dashboard data (AJAX refresh)"""

    from inventory.models import Stock, StockMovement, Product
    from stores.models import Store

    try:
        # Date range for movements
        end_date = timezone.now()
        start_date = end_date - timedelta(days=7)

        # Stock Statistics
        stock_stats = {
            'total_products': Stock.objects.values('product').distinct().count(),
            'total_stores': Store.objects.filter(is_active=True).count(),
            'out_of_stock': Stock.objects.filter(quantity=0).count(),
            'low_stock': Stock.objects.filter(
                quantity__gt=0,
                quantity__lte=F('low_stock_threshold')
            ).count(),
            'efris_products': Product.objects.filter(efris_is_uploaded=True).count(),
        }

        # Movement Statistics
        movements_by_day = []
        for i in range(7):
            date = start_date + timedelta(days=i)
            count = StockMovement.objects.filter(
                created_at__date=date.date()
            ).count()
            movements_by_day.append({
                'date': date.strftime('%Y-%m-%d'),
                'count': count
            })

        # Stock by Status
        total_stocks = Stock.objects.count()
        stock_by_status = {
            'critical': Stock.objects.filter(quantity=0).count(),
            'low': Stock.objects.filter(
                quantity__gt=0,
                quantity__lte=F('low_stock_threshold')
            ).count(),
            'medium': Stock.objects.filter(
                quantity__gt=F('low_stock_threshold'),
                quantity__lte=F('low_stock_threshold') * 2
            ).count(),
            'good': Stock.objects.filter(
                quantity__gt=F('low_stock_threshold') * 2
            ).count(),
        }

        # Recent Movements
        recent_movements = list(
            StockMovement.objects.select_related(
                'product', 'store', 'created_by'
            ).order_by('-created_at')[:15].values(
                'product__name',
                'store__name',
                'movement_type',
                'quantity',
                'created_at',
                'created_by__username'
            )
        )

        # Stock Alerts (critical and low stock)
        stock_alerts = []

        # Critical stock alerts (out of stock)
        critical_stocks = Stock.objects.filter(
            quantity=0
        ).select_related('product', 'store')[:10]

        for stock in critical_stocks:
            stock_alerts.append({
                'product_name': stock.product.name,
                'store_name': stock.store.name,
                'current_stock': stock.quantity,
                'reorder_level': stock.low_stock_threshold,
                'status': 'critical'
            })

        # Low stock alerts
        low_stocks = Stock.objects.filter(
            quantity__gt=0,
            quantity__lte=F('low_stock_threshold')
        ).select_related('product', 'store')[:10]

        for stock in low_stocks:
            stock_alerts.append({
                'product_name': stock.product.name,
                'store_name': stock.store.name,
                'current_stock': stock.quantity,
                'reorder_level': stock.low_stock_threshold,
                'status': 'low'
            })

        # EFRIS sync status
        efris_stats = {
            'products_uploaded': Product.objects.filter(efris_is_uploaded=True).count(),
            'stocks_needing_sync': Stock.objects.filter(
                product__efris_is_uploaded=True,
                efris_sync_required=True
            ).count(),
        }

        return JsonResponse({
            'success': True,
            'stock_stats': stock_stats,
            'movement_stats': {
                'movements_by_day': movements_by_day,
            },
            'movements_by_day': movements_by_day,
            'stock_by_status': stock_by_status,
            'recent_movements': recent_movements,
            'stock_alerts': stock_alerts,
            'efris_stats': efris_stats,
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)
