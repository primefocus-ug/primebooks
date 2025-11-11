import logging
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum, Count, Avg, F, Q
from django.http import JsonResponse, Http404
from django.utils import timezone
from django.views import View
from datetime import timedelta

from accounts.models import CustomUser
from stores.models import Store
from sales.models import Sale
from inventory.models import Stock
from ..models import Company

logger = logging.getLogger(__name__)


class CompanyStatusAPIView(LoginRequiredMixin, View):
    """Real-time company status check"""

    def get(self, request, *args, **kwargs):
        try:
            company = getattr(request.user, 'company', None)
            if not company:
                return JsonResponse({
                    'success': False,
                    'message': 'No company found'
                }, status=404)

            # Update and get fresh status
            status_changed = company.check_and_update_access_status()
            company.refresh_from_db()

            restrictions = company.get_access_restrictions()

            data = {
                'success': True,
                'company_id': company.company_id,
                'status': company.status,
                'status_display': company.get_status_display(),
                'is_active': company.is_active,
                'has_active_access': company.has_active_access,
                'access_status_display': company.access_status_display,
                'days_until_expiry': company.days_until_expiry,
                'is_trial': company.is_trial,
                'restrictions': restrictions,
                'has_restrictions': len(restrictions) > 0,
                'status_changed': status_changed,
                'timestamp': timezone.now().isoformat(),
            }

            # Plan info
            if company.plan:
                data['plan'] = {
                    'name': company.plan.name,
                    'display_name': company.plan.display_name,
                    'price': float(company.plan.price),
                    'billing_cycle': company.plan.get_billing_cycle_display(),
                }

            return JsonResponse(data)

        except Exception as e:
            logger.error(f"Error fetching company status: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'Error fetching status'
            }, status=500)


class QuickStatsAPIView(LoginRequiredMixin, View):
    """Quick stats for dashboard widgets"""

    def get(self, request, *args, **kwargs):
        try:
            company = getattr(request.user, 'company', None)
            if not company:
                return JsonResponse({
                    'success': False,
                    'message': 'No company found'
                }, status=404)

            # Time range
            days = int(request.GET.get('days', 30))
            start_date = timezone.now().date() - timedelta(days=days)

            # Get stores
            stores = Store.objects.filter(company=company)
            store_ids = stores.values_list('id', flat=True)

            # Revenue stats
            revenue_data = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date__gte=start_date,
                is_voided=False,
                is_completed=True
            ).aggregate(
                total_revenue=Sum('total_amount'),
                total_sales=Count('id'),
                avg_sale=Avg('total_amount')
            )

            # Today's stats
            today = timezone.now().date()
            today_data = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date=today,
                is_voided=False,
                is_completed=True
            ).aggregate(
                revenue=Sum('total_amount'),
                sales=Count('id')
            )

            # Employee stats
            employees = CustomUser.objects.filter(company=company, is_hidden=False)
            active_employees = employees.filter(is_active=True).count()

            # Inventory alerts
            inventory_alerts = Stock.objects.filter(
                store__in=stores
            ).aggregate(
                low_stock=Count('id', filter=Q(quantity__lte=F('low_stock_threshold'))),
                out_of_stock=Count('id', filter=Q(quantity=0))
            )

            # Branch stats
            active_branches = stores.filter(is_active=True).count()

            return JsonResponse({
                'success': True,
                'stats': {
                    'revenue_period': {
                        'total': float(revenue_data['total_revenue'] or 0),
                        'sales_count': revenue_data['total_sales'] or 0,
                        'avg_sale': float(revenue_data['avg_sale'] or 0),
                        'days': days,
                    },
                    'today': {
                        'revenue': float(today_data['revenue'] or 0),
                        'sales': today_data['sales'] or 0,
                    },
                    'employees': {
                        'total': employees.count(),
                        'active': active_employees,
                    },
                    'branches': {
                        'total': stores.count(),
                        'active': active_branches,
                    },
                    'inventory': {
                        'low_stock': inventory_alerts['low_stock'],
                        'out_of_stock': inventory_alerts['out_of_stock'],
                        'needs_attention': inventory_alerts['low_stock'] + inventory_alerts['out_of_stock'],
                    },
                    'storage': {
                        'used_mb': company.storage_used_mb,
                        'used_gb': round(company.storage_used_mb / 1024, 2),
                        'percentage': round(company.storage_usage_percentage, 1),
                    },
                },
                'timestamp': timezone.now().isoformat(),
            })

        except Exception as e:
            logger.error(f"Error fetching quick stats: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'Error fetching stats'
            }, status=500)


class UsageMetricsAPIView(LoginRequiredMixin, View):
    """Detailed usage metrics for subscription monitoring"""

    def get(self, request, *args, **kwargs):
        try:
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

            # Users
            total_users = CustomUser.objects.filter(
                company=company, is_hidden=False
            ).count()

            # Branches
            total_branches = company.branches_count

            # Storage
            storage_gb = company.storage_used_mb / 1024

            # API calls (this month)
            api_calls = company.api_calls_this_month

            # Build metrics
            metrics = {
                'users': {
                    'current': total_users,
                    'limit': plan.max_users,
                    'percentage': round((total_users / plan.max_users * 100), 1) if plan.max_users > 0 else 0,
                    'available': max(0, plan.max_users - total_users),
                    'over_limit': total_users > plan.max_users,
                },
                'branches': {
                    'current': total_branches,
                    'limit': plan.max_branches,
                    'percentage': round((total_branches / plan.max_branches * 100), 1) if plan.max_branches > 0 else 0,
                    'available': max(0, plan.max_branches - total_branches),
                    'over_limit': total_branches > plan.max_branches,
                },
                'storage': {
                    'current_gb': round(storage_gb, 2),
                    'limit_gb': plan.max_storage_gb,
                    'percentage': round(company.storage_usage_percentage, 1),
                    'available_gb': round(max(0, plan.max_storage_gb - storage_gb), 2),
                    'over_limit': storage_gb > plan.max_storage_gb,
                },
                'api_calls': {
                    'current': api_calls,
                    'limit': plan.max_api_calls_per_month,
                    'percentage': round((api_calls / plan.max_api_calls_per_month * 100),
                                        1) if plan.max_api_calls_per_month > 0 else 0,
                    'available': max(0, plan.max_api_calls_per_month - api_calls),
                    'over_limit': api_calls > plan.max_api_calls_per_month,
                },
            }

            # Check for warnings
            warnings = []
            for key, data in metrics.items():
                if data['percentage'] >= 90:
                    warnings.append({
                        'category': key,
                        'severity': 'critical' if data['percentage'] >= 100 else 'warning',
                        'message': f"{key.replace('_', ' ').title()} at {data['percentage']}% capacity",
                        'suggestion': f"Consider upgrading your plan to increase {key.replace('_', ' ')} limit"
                    })

            return JsonResponse({
                'success': True,
                'plan': {
                    'name': plan.name,
                    'display_name': plan.display_name,
                },
                'metrics': metrics,
                'warnings': warnings,
                'timestamp': timezone.now().isoformat(),
            })

        except Exception as e:
            logger.error(f"Error fetching usage metrics: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'Error fetching metrics'
            }, status=500)


class NotificationsAPIView(LoginRequiredMixin, View):
    """Get company-related notifications"""

    def get(self, request, *args, **kwargs):
        try:
            company = getattr(request.user, 'company', None)
            if not company:
                return JsonResponse({
                    'success': False,
                    'message': 'No company found'
                }, status=404)

            notifications = []

            # Subscription expiry warnings
            days_left = company.days_until_expiry
            if days_left <= 7 and days_left > 0:
                notifications.append({
                    'type': 'warning',
                    'category': 'subscription',
                    'title': 'Subscription Expiring Soon',
                    'message': f'Your subscription expires in {days_left} days',
                    'action': {
                        'text': 'Renew Now',
                        'url': '/companies/subscription/renew/',
                    },
                    'icon': 'bi-exclamation-triangle',
                    'priority': 'high',
                })
            elif days_left <= 0:
                if company.is_in_grace_period:
                    grace_days = (company.grace_period_ends_at - timezone.now().date()).days
                    notifications.append({
                        'type': 'danger',
                        'category': 'subscription',
                        'title': 'Subscription Expired - Grace Period',
                        'message': f'Grace period ends in {grace_days} days',
                        'action': {
                            'text': 'Renew Immediately',
                            'url': '/companies/subscription/renew/',
                        },
                        'icon': 'bi-exclamation-octagon',
                        'priority': 'critical',
                    })
                else:
                    notifications.append({
                        'type': 'danger',
                        'category': 'subscription',
                        'title': 'Subscription Expired',
                        'message': 'Your subscription has expired',
                        'action': {
                            'text': 'Renew Subscription',
                            'url': '/companies/subscription/renew/',
                        },
                        'icon': 'bi-x-octagon',
                        'priority': 'critical',
                    })

            # Usage warnings
            if company.plan:
                # Storage warning
                if company.storage_usage_percentage >= 90:
                    notifications.append({
                        'type': 'warning' if company.storage_usage_percentage < 100 else 'danger',
                        'category': 'storage',
                        'title': 'Storage Limit Reached',
                        'message': f'Using {round(company.storage_usage_percentage, 1)}% of storage',
                        'action': {
                            'text': 'Upgrade Plan',
                            'url': '/companies/subscription/plans/',
                        },
                        'icon': 'bi-hdd',
                        'priority': 'medium',
                    })

                # User limit warning
                user_count = CustomUser.objects.filter(company=company, is_hidden=False).count()
                user_percentage = (user_count / company.plan.max_users * 100) if company.plan.max_users > 0 else 0
                if user_percentage >= 90:
                    notifications.append({
                        'type': 'warning',
                        'category': 'users',
                        'title': 'User Limit Approaching',
                        'message': f'{user_count}/{company.plan.max_users} users',
                        'action': {
                            'text': 'Upgrade Plan',
                            'url': '/companies/subscription/plans/',
                        },
                        'icon': 'bi-people',
                        'priority': 'medium',
                    })

            # Inventory alerts
            stores = Store.objects.filter(company=company)
            low_stock_count = Stock.objects.filter(
                store__in=stores,
                quantity__lte=F('low_stock_threshold')
            ).count()

            if low_stock_count > 0:
                notifications.append({
                    'type': 'info',
                    'category': 'inventory',
                    'title': 'Low Stock Alert',
                    'message': f'{low_stock_count} items need restocking',
                    'action': {
                        'text': 'View Inventory',
                        'url': '/inventory/',
                    },
                    'icon': 'bi-box-seam',
                    'priority': 'low',
                })

            # EFRIS warnings
            if company.efris_enabled and not company.efris_is_active:
                notifications.append({
                    'type': 'warning',
                    'category': 'efris',
                    'title': 'EFRIS Not Active',
                    'message': 'EFRIS integration is enabled but not active',
                    'action': {
                        'text': 'Configure EFRIS',
                        'url': f'/companies/profile/?tab=efris',
                    },
                    'icon': 'bi-shield-exclamation',
                    'priority': 'medium',
                })

            # Sort by priority
            priority_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
            notifications.sort(key=lambda x: priority_order.get(x['priority'], 99))

            return JsonResponse({
                'success': True,
                'notifications': notifications,
                'count': len(notifications),
                'unread_count': len([n for n in notifications if n['priority'] in ['critical', 'high']]),
                'timestamp': timezone.now().isoformat(),
            })

        except Exception as e:
            logger.error(f"Error fetching notifications: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'Error fetching notifications'
            }, status=500)


class RevenueChartAPIView(LoginRequiredMixin, View):
    """Revenue chart data for dashboard"""

    def get(self, request, *args, **kwargs):
        try:
            company = getattr(request.user, 'company', None)
            if not company:
                return JsonResponse({
                    'success': False,
                    'message': 'No company found'
                }, status=404)

            # Get parameters
            period = request.GET.get('period', 'week')  # week, month, year

            stores = Store.objects.filter(company=company)
            store_ids = stores.values_list('id', flat=True)

            labels = []
            data = []

            if period == 'week':
                # Last 7 days
                for i in range(7):
                    date = timezone.now().date() - timedelta(days=6 - i)
                    daily_revenue = Sale.objects.filter(
                        store_id__in=store_ids,
                        created_at__date=date,
                        is_voided=False,
                        is_completed=True
                    ).aggregate(total=Sum('total_amount'))['total'] or 0

                    labels.append(date.strftime('%a, %b %d'))
                    data.append(float(daily_revenue))

            elif period == 'month':
                # Last 30 days by week
                for i in range(4):
                    week_start = timezone.now().date() - timedelta(days=(3 - i) * 7 + 6)
                    week_end = week_start + timedelta(days=6)

                    week_revenue = Sale.objects.filter(
                        store_id__in=store_ids,
                        created_at__date__range=[week_start, week_end],
                        is_voided=False,
                        is_completed=True
                    ).aggregate(total=Sum('total_amount'))['total'] or 0

                    labels.append(f'{week_start.strftime("%b %d")} - {week_end.strftime("%d")}')
                    data.append(float(week_revenue))

            elif period == 'year':
                # Last 12 months
                for i in range(12):
                    month_date = timezone.now().date() - timedelta(days=(11 - i) * 30)
                    month_start = month_date.replace(day=1)

                    # Get last day of month
                    if month_start.month == 12:
                        month_end = month_start.replace(year=month_start.year + 1, month=1, day=1) - timedelta(days=1)
                    else:
                        month_end = month_start.replace(month=month_start.month + 1, day=1) - timedelta(days=1)

                    month_revenue = Sale.objects.filter(
                        store_id__in=store_ids,
                        created_at__date__range=[month_start, month_end],
                        is_voided=False,
                        is_completed=True
                    ).aggregate(total=Sum('total_amount'))['total'] or 0

                    labels.append(month_start.strftime('%b %Y'))
                    data.append(float(month_revenue))

            return JsonResponse({
                'success': True,
                'chart_data': {
                    'labels': labels,
                    'datasets': [{
                        'label': 'Revenue',
                        'data': data,
                        'borderColor': 'rgb(75, 192, 192)',
                        'backgroundColor': 'rgba(75, 192, 192, 0.2)',
                        'tension': 0.1,
                    }]
                },
                'period': period,
                'total': sum(data),
                'timestamp': timezone.now().isoformat(),
            })

        except Exception as e:
            logger.error(f"Error fetching revenue chart data: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'Error fetching chart data'
            }, status=500)