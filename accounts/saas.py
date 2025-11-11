from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q, Sum, Avg
from django.utils import timezone
from django.urls import reverse_lazy, reverse
from django.http import JsonResponse
from django.contrib import messages
from django.urls import reverse
from datetime import timedelta
from .utils import (
    get_visible_users,
    get_accessible_companies,
    require_saas_admin,
    get_company_user_count
)
from .models import CustomUser
from company.models import Company, SubscriptionPlan
import logging

logger = logging.getLogger(__name__)


def _is_admin_user(user):
    """
    Check if user has admin privileges (SAAS_ADMIN or SUPER_ADMIN)
    """
    return (
            getattr(user, 'is_saas_admin', False) or
            user.primary_role and user.primary_role.priority >= 90
    )


def _get_expired_companies():
    """
    Get companies with expired subscriptions
    Returns QuerySet of expired companies
    """
    today = timezone.now().date()
    expired_filter = Q()

    # Check by subscription_ends_at date
    if hasattr(Company, 'subscription_ends_at'):
        expired_filter |= Q(subscription_ends_at__lt=today)

    # Check by status field
    if hasattr(Company, 'status'):
        expired_filter |= Q(status__in=['EXPIRED', 'SUSPENDED', 'CANCELLED'])

    # Check by trial expiration
    if hasattr(Company, 'trial_ends_at'):
        expired_filter |= Q(
            is_trial=True,
            trial_ends_at__lt=today
        )

    return Company.objects.filter(expired_filter).distinct()


def _get_company_statistics():
    """
    Calculate comprehensive company statistics
    Returns dict with company metrics
    """
    stats = {
        'total': Company.objects.count(),
        'active': 0,
        'trial': 0,
        'expired': 0,
        'suspended': 0,
        'growth_rate': 0,
    }

    # Active companies
    if hasattr(Company, 'status'):
        stats['active'] = Company.objects.filter(status='ACTIVE').count()
        stats['suspended'] = Company.objects.filter(status__in=['SUSPENDED', 'CANCELLED']).count()
    else:
        stats['active'] = Company.objects.filter(is_active=True).count()

    # Trial companies
    if hasattr(Company, 'is_trial'):
        stats['trial'] = Company.objects.filter(
            is_trial=True,
            trial_ends_at__gte=timezone.now().date()
        ).count() if hasattr(Company, 'trial_ends_at') else Company.objects.filter(is_trial=True).count()

    # Expired companies
    stats['expired'] = _get_expired_companies().count()

    # Growth rate (last 30 days vs previous 30 days)
    thirty_days_ago = timezone.now() - timedelta(days=30)
    sixty_days_ago = timezone.now() - timedelta(days=60)

    recent_count = Company.objects.filter(created_at__gte=thirty_days_ago).count()
    previous_count = Company.objects.filter(
        created_at__gte=sixty_days_ago,
        created_at__lt=thirty_days_ago
    ).count()

    if previous_count > 0:
        stats['growth_rate'] = round(((recent_count - previous_count) / previous_count) * 100, 1)
    elif recent_count > 0:
        stats['growth_rate'] = 100

    return stats


def _get_user_statistics(include_hidden=False):
    """
    Calculate comprehensive user statistics

    Args:
        include_hidden: If True, includes hidden SaaS admin users in counts

    Returns dict with user metrics
    """
    if include_hidden:
        base_queryset = CustomUser.objects.all()
    else:
        base_queryset = get_visible_users()

    stats = {
        'total': base_queryset.count(),
        'active': base_queryset.filter(is_active=True).count(),
        'inactive': base_queryset.filter(is_active=False).count(),
        'locked': base_queryset.filter(locked_until__gt=timezone.now()).count(),
        'verified': base_queryset.filter(email_verified=True).count(),
        'two_factor_enabled': base_queryset.filter(two_factor_enabled=True).count(),
        'growth_rate': 0,
    }

    # User type distribution
    stats['by_type'] = list(
        base_queryset.values('groups__role__group__name')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    # Growth rate
    thirty_days_ago = timezone.now() - timedelta(days=30)
    sixty_days_ago = timezone.now() - timedelta(days=60)

    recent_count = base_queryset.filter(date_joined__gte=thirty_days_ago).count()
    previous_count = base_queryset.filter(
        date_joined__gte=sixty_days_ago,
        date_joined__lt=thirty_days_ago
    ).count()

    if previous_count > 0:
        stats['growth_rate'] = round(((recent_count - previous_count) / previous_count) * 100, 1)
    elif recent_count > 0:
        stats['growth_rate'] = 100

    return stats


def _get_revenue_statistics():
    """
    Calculate revenue statistics from subscriptions
    Returns dict with revenue metrics
    """
    stats = {
        'mrr': 0,  # Monthly Recurring Revenue
        'arr': 0,  # Annual Recurring Revenue
        'total_value': 0,
        'by_plan': [],
    }

    # Calculate MRR by plan
    if hasattr(Company, 'plan'):
        plan_revenue = Company.objects.filter(
            status='ACTIVE'
        ).values(
            'plan__name',
            'plan__display_name',
            'plan__price'
        ).annotate(
            company_count=Count('company_id')
        )

        for item in plan_revenue:
            price = item.get('plan__price', 0) or 0
            count = item['company_count']
            revenue = price * count

            stats['by_plan'].append({
                'name': item.get('plan__display_name') or item.get('plan__name', 'Unknown'),
                'companies': count,
                'revenue': revenue
            })

            stats['mrr'] += revenue

        stats['arr'] = stats['mrr'] * 12
        stats['total_value'] = stats['arr']

    return stats


def _get_system_health_metrics():
    """
    Get system health and performance metrics
    Returns dict with health indicators
    """
    metrics = {
        'database_size': 'N/A',
        'avg_users_per_company': 0,
        'avg_login_frequency': 0,
        'security_alerts': 0,
    }

    # Average users per company
    companies_with_users = Company.objects.annotate(
        user_count=Count('customuser')
    ).filter(user_count__gt=0)

    if companies_with_users.exists():
        metrics['avg_users_per_company'] = round(
            companies_with_users.aggregate(Avg('user_count'))['user_count__avg'] or 0,
            1
        )

    # Security alerts (locked accounts)
    metrics['security_alerts'] = CustomUser.objects.filter(
        locked_until__gt=timezone.now()
    ).count()

    return metrics


@login_required
def saas_admin_dashboard(request):
    """
    Unified admin dashboard with full system privileges
    Accessible by SAAS_ADMIN, SUPER_ADMIN, and SYSTEM_ADMIN users
    """
    # Check permissions
    if not _is_admin_user(request.user):
        raise PermissionDenied("You don't have permission to access the admin dashboard")

    # Determine if user should see hidden users
    include_hidden = getattr(request.user, 'is_saas_admin', False) or request.user.is_superuser

    # Get comprehensive statistics
    company_stats = _get_company_statistics()
    user_stats = _get_user_statistics(include_hidden=include_hidden)
    revenue_stats = _get_revenue_statistics()
    health_metrics = _get_system_health_metrics()

    # Recent activity
    recent_companies = Company.objects.select_related('plan').order_by('-created_at')[:10]

    if include_hidden:
        recent_users = CustomUser.objects.select_related('company').order_by('-date_joined')[:10]
    else:
        recent_users = get_visible_users().select_related('company').order_by('-date_joined')[:10]

    # Plan distribution with detailed metrics
    plan_stats = []
    if hasattr(Company, 'plan'):
        plan_data = Company.objects.values(
            'plan__name',
            'plan__display_name',
            'plan__price'
        ).annotate(
            count=Count('company_id'),
            active_count=Count('company_id', filter=Q(status='ACTIVE')) if hasattr(Company, 'status') else Count('company_id')
        ).order_by('-count')

        for item in plan_data:
            plan_stats.append({
                'name': item.get('plan__display_name') or item.get('plan__name', 'Unknown'),
                'total_companies': item['count'],
                'active_companies': item['active_count'],
                'price': item.get('plan__price', 0) or 0,
                'revenue': (item.get('plan__price', 0) or 0) * item['active_count']
            })

    # Companies requiring attention
    expiring_soon = []
    if hasattr(Company, 'subscription_ends_at'):
        thirty_days = timezone.now().date() + timedelta(days=30)
        expiring_soon = Company.objects.filter(
            subscription_ends_at__lte=thirty_days,
            subscription_ends_at__gte=timezone.now().date()
        ).select_related('plan').order_by('subscription_ends_at')[:10]

    # Trial companies ending soon
    trials_ending_soon = []
    if hasattr(Company, 'trial_ends_at'):
        seven_days = timezone.now().date() + timedelta(days=7)
        trials_ending_soon = Company.objects.filter(
            is_trial=True,
            trial_ends_at__lte=seven_days,
            trial_ends_at__gte=timezone.now().date()
        ).order_by('trial_ends_at')[:10]

    # Recently locked accounts (security monitoring)
    recently_locked = CustomUser.objects.filter(
        locked_until__gt=timezone.now()
    ).select_related('company').order_by('-locked_until')[:10]

    # Activity trends (last 30 days)
    activity_data = []
    for i in range(29, -1, -1):
        date = timezone.now().date() - timedelta(days=i)
        activity_data.append({
            'date': date.isoformat(),
            'new_companies': Company.objects.filter(created_at__date=date).count(),
            'new_users': CustomUser.objects.filter(date_joined__date=date).count(),
        })

    context = {
        # Statistics
        'company_stats': company_stats,
        'user_stats': user_stats,
        'revenue_stats': revenue_stats,
        'health_metrics': health_metrics,

        # Recent activity
        'recent_companies': recent_companies,
        'recent_users': recent_users,

        # Distribution
        'plan_stats': plan_stats,

        # Alerts and attention items
        'expiring_soon': expiring_soon,
        'trials_ending_soon': trials_ending_soon,
        'recently_locked': recently_locked,

        # Trends
        'activity_data': activity_data,

        # Access control
        'accessible_companies': get_accessible_companies(request.user),
        'is_saas_admin': getattr(request.user, 'is_saas_admin', False),
        'is_super_admin': request.user.is_superuser,
        'can_see_hidden_users': include_hidden,

        # Feature flags
        'can_manage_all_companies': True,
        'can_view_revenue': True,
        'can_manage_plans': True,
        'can_impersonate_users': getattr(request.user, 'is_saas_admin', False),
    }

    return render(request, 'accounts/saas_admin_dashboards.html', context)


@login_required
def system_admin_dashboard(request):
    """
    Legacy system admin dashboard - redirects to unified admin dashboard
    """
    if not _is_admin_user(request.user):
        raise PermissionDenied("You don't have permission to access the admin dashboard")

    messages.info(
        request,
        'System admin dashboard has been merged with SaaS admin dashboard for improved functionality.'
    )

    return redirect('saas_admin_dashboard')


@require_saas_admin
def switch_tenant_view(request):
    """
    Enhanced tenant switching with proper session management
    """
    tenant_id = request.GET.get('tenant_id') or request.POST.get('tenant_id')

    # If tenant_id provided, switch to that tenant
    if tenant_id:
        try:
            company = get_object_or_404(Company, id=tenant_id)

            # Store the target company in session
            request.session['saas_admin_viewing_company'] = company.company_id
            request.session['saas_admin_viewing_company_name'] = company.name

            # Also store schema name if using django-tenants
            if hasattr(company, 'schema_name'):
                request.session['saas_admin_viewing_schema'] = company.schema_name

            logger.info(f"SaaS admin {request.user.email} switched to company {company.name} (ID: {company.company_id})")

            # Return JSON for AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'message': f'Switched to {company.name}',
                    'company': {
                        'id': company.company_id,
                        'name': company.name,
                        'schema_name': getattr(company, 'schema_name', ''),
                    },
                    'redirect_url': reverse('companies:company_detail', kwargs={'company_id': company.company_id})
                })

            messages.success(request, f'Now viewing: {company.name}')

            # Redirect to company detail page
            from django.urls import reverse
            return redirect('companies:company_detail', company_id=company.company_id)

        except Company.DoesNotExist:
            logger.error(f"Company with ID {tenant_id} not found")

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': 'Company not found'
                }, status=404)

            messages.error(request, 'Company not found')
            return redirect('saas_admin_dashboard')

        except Exception as e:
            logger.error(f"Error switching tenant: {str(e)}", exc_info=True)

            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'error': str(e)
                }, status=500)

            messages.error(request, f'Error switching company: {str(e)}')
            return redirect('saas_admin_dashboard')

    # No tenant_id - return list of companies
    accessible_companies = get_accessible_companies(request.user)

    # Prepare companies data
    companies_data = []
    for company in accessible_companies:
        companies_data.append({
            'id': company.company_id,
            'name': company.name,
            'schema_name': getattr(company, 'schema_name', ''),
            'company_id': getattr(company, 'company_id', company.company_id),
            'user_count': get_company_user_count(company),
            'status': getattr(company, 'status', 'ACTIVE'),
            'is_trial': getattr(company, 'is_trial', False),
            'plan_name': company.plan.display_name if hasattr(company, 'plan') and company.plan else 'No Plan',
        })

    # Return JSON for AJAX
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'companies': companies_data,
            'current_company_id': request.session.get('saas_admin_viewing_company')
        })

    # Render template for regular request
    context = {
        'companies': companies_data,
        'current_company_id': request.session.get('saas_admin_viewing_company'),
        'current_company_name': request.session.get('saas_admin_viewing_company_name'),
    }

    return render(request, 'accounts/switch_tenant.html', context)


@require_saas_admin
def clear_tenant_view(request):
    """
    Clear the current tenant selection and return to global view
    """
    # Clear tenant session data
    request.session.pop('saas_admin_viewing_company', None)
    request.session.pop('saas_admin_viewing_company_name', None)
    request.session.pop('saas_admin_viewing_schema', None)

    logger.info(f"SaaS admin {request.user.email} cleared tenant view")

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'success': True,
            'message': 'Returned to global view'
        })

    messages.success(request, 'Returned to global view')
    return redirect('saas_admin_dashboard')


@login_required
def admin_quick_stats_api(request):
    """
    API endpoint for real-time admin statistics
    Returns JSON with current system stats
    """
    if not _is_admin_user(request.user):
        return JsonResponse({'error': 'Permission denied'}, status=403)

    include_hidden = getattr(request.user, 'is_saas_admin', False) or request.user.is_superuser

    stats = {
        'companies': _get_company_statistics(),
        'users': _get_user_statistics(include_hidden=include_hidden),
        'revenue': _get_revenue_statistics(),
        'health': _get_system_health_metrics(),
        'timestamp': timezone.now().isoformat(),
        'current_tenant': {
            'id': request.session.get('saas_admin_viewing_company'),
            'name': request.session.get('saas_admin_viewing_company_name'),
        }
    }

    return JsonResponse(stats)