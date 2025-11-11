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
    """
    Enhanced dashboard for SaaS admin or single company view
    """
    template_name = 'company/dashboard.html'
    permission_required = 'company.view_company'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        # Check if user is SaaS admin
        if self.request.user.is_saas_admin:
            # SaaS admin sees all companies
            companies = Company.objects.all()

            context.update({
                'total_companies': companies.count(),
                'verified_companies': companies.filter(is_verified=True).count(),
                'efris_enabled_companies': companies.filter(efris_enabled=True).count(),
                'active_companies': companies.filter(status='ACTIVE').count(),
                'trial_companies': companies.filter(status='TRIAL').count(),
                'expired_companies': companies.filter(status='EXPIRED').count(),
                'recent_companies': companies.order_by('-created_at')[:5],
                'is_saas_admin': True,
            })

            # Calculate totals across all companies
            total_branches = Store.objects.count()
            total_employees = CustomUser.objects.filter(is_hidden=False).count()

            # Charts data
            context['monthly_registrations'] = self.get_monthly_registrations()
            context['currency_distribution'] = self.get_currency_distribution()
            context['plan_distribution'] = self.get_plan_distribution()
            context['status_distribution'] = self.get_status_distribution()

        else:
            # Regular user sees only their company
            user_company = getattr(self.request.user, 'company', None)
            if not user_company:
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
                })
                return context

            company = user_company
            context['company'] = company
            context['company_id'] = company.company_id
            context['is_saas_admin'] = False

            # Stats for single company
            try:
                total_branches = Store.objects.filter(
                    company=company,
                    is_active=True
                ).count()
            except:
                total_branches = 0

            try:
                total_employees = CustomUser.objects.filter(
                    company=company,
                    is_active=True,
                    is_hidden=False
                ).count()
            except:
                total_employees = 0

            context.update({
                'total_companies': 1,
                'verified_companies': 1 if company.is_verified else 0,
                'efris_enabled_companies': 1 if company.efris_enabled else 0,
                'active_companies': 1 if company.status == 'ACTIVE' else 0,
                'trial_companies': 1 if company.status == 'TRIAL' else 0,
                'expired_companies': 1 if company.status == 'EXPIRED' else 0,
                'recent_companies': [company],
            })

            # Company-specific charts data
            context['monthly_registrations'] = self.get_monthly_registrations_single(company)
            context['currency_distribution'] = [{'currency': company.preferred_currency, 'count': 1}]
            context['plan_distribution'] = [
                {'plan': company.plan.display_name if company.plan else 'No Plan', 'count': 1}
            ]
            context['status_distribution'] = [{'status': company.status, 'count': 1}]

        context.update({
            'total_branches': total_branches,
            'total_employees': total_employees,
        })

        return context

    def get_monthly_registrations(self):
        """Get monthly company registrations for last 12 months"""
        data = []
        now = timezone.now()

        for i in range(12):
            month_start = (now - relativedelta(months=i)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            next_month_start = month_start + relativedelta(months=1)
            month_end = next_month_start - timedelta(seconds=1)

            count = Company.objects.filter(
                created_at__gte=month_start,
                created_at__lte=month_end
            ).count()

            data.append({
                'month': month_start.strftime('%b %Y'),
                'count': count
            })

        return list(reversed(data))

    def get_monthly_registrations_single(self, company):
        """Get registration data for single company"""
        data = []
        now = timezone.now()

        for i in range(12):
            month_start = (now - relativedelta(months=i)).replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            next_month_start = month_start + relativedelta(months=1)
            month_end = next_month_start - timedelta(seconds=1)

            count = 1 if (
                    company.created_at >= month_start and
                    company.created_at <= month_end
            ) else 0

            data.append({
                'month': month_start.strftime('%b %Y'),
                'count': count
            })

        return list(reversed(data))

    def get_currency_distribution(self):
        """Get currency distribution across companies"""
        return list(
            Company.objects.values('preferred_currency')
            .annotate(count=Count('company_id'))
            .order_by('-count')
        )

    def get_plan_distribution(self):
        """Get plan distribution across companies"""
        return list(
            Company.objects.filter(plan__isnull=False)
            .values(plan_name=F('plan__display_name'))
            .annotate(count=Count('company_id'))
            .order_by('-count')
        )

    def get_status_distribution(self):
        """Get status distribution across companies"""
        return list(
            Company.objects.values('status')
            .annotate(count=Count('company_id'))
            .order_by('-count')
        )


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
            is_completed=True
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