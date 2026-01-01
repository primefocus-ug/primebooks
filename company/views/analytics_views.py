import logging
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.db.models import Sum, Count, Avg, Q,F
from django.utils import timezone
from django.views.generic import TemplateView
from datetime import timedelta
from dateutil.relativedelta import relativedelta

from accounts.models import CustomUser
from stores.models import Store
from sales.models import Sale
from inventory.models import Stock
from ..models import Company, SubscriptionPlan

logger = logging.getLogger(__name__)


class DashboardView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """Dashboard view showing only the current logged-in user's company."""
    template_name = 'company/dashboard.html'
    permission_required = 'company.view_company'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user_company = getattr(self.request.user, 'company', None)

        if not user_company:
            # User has no company assigned
            context.update({
                'total_companies': 0,
                'verified_companies': 0,
                'efris_enabled_companies': 0,
                'active_companies': 0,
                'trial_companies': 0,
                'expired_companies': 0,
                'total_branches': 0,
                'total_employees': 0,
                'recent_companies': [],
                'company': None,
                'company_id': None,
                'is_saas_admin': False,
                'monthly_registrations': [],
                'currency_distribution': [],
                'plan_distribution': [],
                'status_distribution': [],
            })
            return context

        # Always show only the current user's company
        company = user_company
        context['company'] = company
        context['company_id'] = company.company_id
        context['is_saas_admin'] = self.request.user.is_saas_admin if hasattr(self.request.user, 'is_saas_admin') else False

        # Company stats - always for current company only
        total_branches = Store.objects.filter(company=company, is_active=True).count()
        total_employees = CustomUser.objects.filter(company=company, is_active=True, is_hidden=False).count()

        context.update({
            'total_companies': 1,  # Always 1 - showing only current company
            'verified_companies': 1 if company.is_verified else 0,
            'efris_enabled_companies': 1 if company.efris_enabled else 0,
            'active_companies': 1 if company.status == 'ACTIVE' else 0,
            'trial_companies': 1 if company.status == 'TRIAL' else 0,
            'expired_companies': 1 if company.status == 'EXPIRED' else 0,
            'recent_companies': [company],  # Only current company
            'total_branches': total_branches,
            'total_employees': total_employees,
            # Charts data - all for current company only
            'monthly_registrations': self.get_monthly_registrations_single(company),
            'currency_distribution': [{'currency': company.preferred_currency, 'count': 1}],
            'plan_distribution': [{'plan': company.plan.display_name if company.plan else 'No Plan', 'count': 1}],
            'status_distribution': [{'status': company.status, 'count': 1}],
        })

        return context

    def get_monthly_registrations_single(self, company):
        """Get registration data for single company over the past 12 months."""
        data = []
        now = timezone.now()

        for i in range(12):
            month_start = (now - relativedelta(months=i)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month_start = month_start + relativedelta(months=1)
            month_end = next_month_start - timedelta(seconds=1)

            # Check if company was created in this month
            count = 1 if (company.created_at >= month_start and company.created_at <= month_end) else 0

            data.append({
                'month': month_start.strftime('%b %Y'),
                'count': count
            })

        return list(reversed(data))

class CompanyAnalyticsAPIView(LoginRequiredMixin, TemplateView):
    """
    Analytics API for company metrics
    """

    def get(self, request, *args, **kwargs):
        from django.http import JsonResponse

        company_id = kwargs.get('company_id')

        try:
            if request.user.is_saas_admin:
                company = Company.objects.get(company_id=company_id)
            else:
                company = getattr(request.user, 'company', None)
                if not company or company.company_id != company_id:
                    return JsonResponse({
                        'success': False,
                        'message': 'Permission denied'
                    }, status=403)

            # Get analytics data
            analytics = self.get_company_analytics(company)

            return JsonResponse({
                'success': True,
                'analytics': analytics,
                'timestamp': timezone.now().isoformat()
            })

        except Company.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Company not found'
            }, status=404)
        except Exception as e:
            logger.error(f"Error fetching analytics: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'Error fetching analytics'
            }, status=500)

    def get_company_analytics(self, company):
        """Calculate comprehensive company analytics"""
        thirty_days_ago = timezone.now().date() - timedelta(days=30)

        # Revenue analytics
        stores = Store.objects.filter(company=company)
        store_ids = stores.values_list('id', flat=True)

        revenue_data = Sale.objects.filter(
            store_id__in=store_ids,
            created_at__date__gte=thirty_days_ago,
            is_voided=False,
            status__in=['COMPLETED', 'PAID']
        ).aggregate(
            total_revenue=Sum('total_amount'),
            total_sales=Count('id'),
            avg_sale=Avg('total_amount')
        )

        # Employee analytics
        employees = CustomUser.objects.filter(company=company, is_hidden=False)

        # Inventory analytics
        inventory_data = Stock.objects.filter(
            store__in=stores
        ).aggregate(
            total_items=Count('id'),
            low_stock=Count('id', filter=Q(quantity__lte=F('low_stock_threshold'))),
            out_of_stock=Count('id', filter=Q(quantity=0))
        )

        return {
            'revenue': {
                'total_30d': float(revenue_data['total_revenue'] or 0),
                'sales_count_30d': revenue_data['total_sales'] or 0,
                'avg_sale_amount': float(revenue_data['avg_sale'] or 0),
            },
            'employees': {
                'total': employees.count(),
                'active': employees.filter(is_active=True).count(),
            },
            'branches': {
                'total': stores.count(),
                'active': stores.filter(is_active=True).count(),
            },
            'inventory': inventory_data,
        }


class UsageMetricsAPIView(LoginRequiredMixin, TemplateView):
    """
    Detailed usage metrics for monitoring plan limits
    """

    def get(self, request, *args, **kwargs):
        from django.http import JsonResponse

        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        plan = company.plan
        if not plan:
            return JsonResponse({
                'success': False,
                'message': 'No plan assigned'
            }, status=400)

        # Calculate usage metrics
        metrics = {
            'users': self._get_user_metrics(company, plan),
            'branches': self._get_branch_metrics(company, plan),
            'storage': self._get_storage_metrics(company, plan),
            'api_calls': self._get_api_metrics(company, plan),
        }

        # Generate warnings
        warnings = self._generate_warnings(metrics)

        return JsonResponse({
            'success': True,
            'metrics': metrics,
            'warnings': warnings,
            'timestamp': timezone.now().isoformat()
        })

    def _get_user_metrics(self, company, plan):
        """Calculate user usage metrics"""
        current = CustomUser.objects.filter(
            company=company, is_hidden=False
        ).count()

        return {
            'current': current,
            'limit': plan.max_users,
            'percentage': round((current / plan.max_users * 100), 1) if plan.max_users > 0 else 0,
            'available': max(0, plan.max_users - current),
            'over_limit': current > plan.max_users,
        }

    def _get_branch_metrics(self, company, plan):
        """Calculate branch usage metrics"""
        current = company.branches_count

        return {
            'current': current,
            'limit': plan.max_branches,
            'percentage': round((current / plan.max_branches * 100), 1) if plan.max_branches > 0 else 0,
            'available': max(0, plan.max_branches - current),
            'over_limit': current > plan.max_branches,
        }

    def _get_storage_metrics(self, company, plan):
        """Calculate storage usage metrics"""
        storage_gb = company.storage_used_mb / 1024

        return {
            'current_gb': round(storage_gb, 2),
            'limit_gb': plan.max_storage_gb,
            'percentage': round(company.storage_usage_percentage, 1),
            'available_gb': round(max(0, plan.max_storage_gb - storage_gb), 2),
            'over_limit': storage_gb > plan.max_storage_gb,
        }

    def _get_api_metrics(self, company, plan):
        """Calculate API usage metrics"""
        current = company.api_calls_this_month

        return {
            'current': current,
            'limit': plan.max_api_calls_per_month,
            'percentage': round(
                (current / plan.max_api_calls_per_month * 100), 1
            ) if plan.max_api_calls_per_month > 0 else 0,
            'available': max(0, plan.max_api_calls_per_month - current),
            'over_limit': current > plan.max_api_calls_per_month,
        }

    def _generate_warnings(self, metrics):
        """Generate usage warnings"""
        warnings = []

        for key, data in metrics.items():
            if data['percentage'] >= 90:
                warnings.append({
                    'category': key,
                    'severity': 'critical' if data['percentage'] >= 100 else 'warning',
                    'message': f"{key.replace('_', ' ').title()} at {data['percentage']}% capacity",
                    'suggestion': f"Consider upgrading your plan to increase {key.replace('_', ' ')} limit"
                })

        return warnings