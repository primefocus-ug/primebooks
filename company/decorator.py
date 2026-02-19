from functools import wraps
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import reverse
from django.http import JsonResponse
from accounts.models import CustomUser
from functools import wraps
from django.db import connection
from django_tenants.utils import get_public_schema_name
import logging

logger = logging.getLogger(__name__)


def check_user_limit(view_func):
    '''
    Decorator to check if company can add more users
    Use on user creation views
    '''

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        company = getattr(request.user, 'company', None)

        if not company:
            messages.error(request, 'No company found')
            return redirect('companies:dashboard')

        # Skip check for SaaS admins
        if request.user.is_saas_admin:
            return view_func(request, *args, **kwargs)

        # Check user limit
        if not company.plan:
            messages.error(request, 'No active plan. Please subscribe.')
            return redirect('companies:subscription_plans')

        current_users = CustomUser.objects.filter(
            company=company,
            is_hidden=False
        ).count()

        if current_users >= company.plan.max_users:
            messages.warning(
                request,
                f'User limit reached ({current_users}/{company.plan.max_users}). '
                f'Please upgrade your plan to add more users.'
            )

            # Handle AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': 'User limit reached',
                    'limit': company.plan.max_users,
                    'current': current_users,
                    'upgrade_url': reverse('companies:subscription_plans')
                }, status=403)

            return redirect('companies:subscription_plans')

        return view_func(request, *args, **kwargs)

    return wrapper


def check_branch_limit(view_func):
    """
    Decorator to check if company can add more branches.
    Allows exactly max_branches.
    Blocks only when creating beyond the limit.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):

        # 🚫 Skip check in public schema
        if connection.schema_name == get_public_schema_name():
            return view_func(request, *args, **kwargs)

        # 🚫 Must be authenticated
        if not request.user.is_authenticated:
            return redirect('accounts:login')

        company = getattr(request.user, 'company', None)

        if not company:
            messages.error(request, 'No company found.')
            return redirect('companies:dashboard')

        # 🚫 SaaS admin bypass
        if getattr(request.user, 'is_saas_admin', False):
            return view_func(request, *args, **kwargs)

        # 🚫 Must have active plan
        if not company.plan:
            messages.error(request, 'No active plan. Please subscribe.')
            return redirect('companies:subscription_plans')

        # ✅ REAL DATABASE COUNT (do not use cached property)
        current_branches = company.branches.filter(is_deleted=False).count() \
            if hasattr(company.branches.model, 'is_deleted') \
            else company.branches.count()

        max_allowed = company.plan.max_branches

        logger.info(
            f"Branch check → Company: {company.company_id}, "
            f"Current: {current_branches}, Limit: {max_allowed}"
        )

        # ✅ Correct logic: allow exactly max_branches
        # Block only if the NEXT branch exceeds limit
        if current_branches + 1 > max_allowed:

            message = (
                f'Branch limit reached ({current_branches}/{max_allowed}). '
                f'Please upgrade your plan to add more branches.'
            )

            # Handle AJAX
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': message,
                    'limit': max_allowed,
                    'current': current_branches,
                    'upgrade_url': reverse('companies:subscription_plans')
                }, status=403)

            messages.warning(request, message)
            return redirect('companies:subscription_plans')

        # ✅ Safe to create branch
        return view_func(request, *args, **kwargs)

    return wrapper


def check_storage_limit(view_func):
    '''
    Decorator to check if company has storage space
    Use on file upload views
    '''

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        company = getattr(request.user, 'company', None)

        if not company:
            messages.error(request, 'No company found')
            return redirect('companies:dashboard')

        # Skip check for SaaS admins
        if request.user.is_saas_admin:
            return view_func(request, *args, **kwargs)

        # Check storage limit
        if not company.plan:
            messages.error(request, 'No active plan. Please subscribe.')
            return redirect('companies:subscription_plans')

        if company.storage_usage_percentage >= 100:
            messages.warning(
                request,
                f'Storage limit reached. Please upgrade your plan for more storage.'
            )

            # Handle AJAX requests
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': False,
                    'message': 'Storage limit reached',
                    'usage_percentage': company.storage_usage_percentage,
                    'upgrade_url': reverse('companies:subscription_plans')
                }, status=403)

            return redirect('companies:subscription_plans')

        return view_func(request, *args, **kwargs)

    return wrapper


def check_api_limit(view_func):
    '''
    Decorator to check API call limits
    Use on API views
    '''

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        company = getattr(request.user, 'company', None)

        if not company or not company.plan:
            return JsonResponse({
                'success': False,
                'message': 'No active plan'
            }, status=403)

        # Skip check for SaaS admins
        if request.user.is_saas_admin:
            return view_func(request, *args, **kwargs)

        # Check if plan allows API access
        if not company.plan.can_use_api:
            return JsonResponse({
                'success': False,
                'message': 'API access not available in your plan',
                'upgrade_url': reverse('companies:subscription_plans')
            }, status=403)

        # Check API call limit
        if company.api_calls_this_month >= company.plan.max_api_calls_per_month:
            return JsonResponse({
                'success': False,
                'message': 'API call limit reached',
                'limit': company.plan.max_api_calls_per_month,
                'current': company.api_calls_this_month,
                'upgrade_url': reverse('companies:subscription_plans')
            }, status=429)

        # Increment API call counter
        company.api_calls_this_month += 1
        company.save(update_fields=['api_calls_this_month'])

        return view_func(request, *args, **kwargs)

    return wrapper


def check_feature_access(feature_name):
    '''
    Decorator to check if company has access to a specific feature
    Use: @check_feature_access('can_use_advanced_reports')
    '''

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            company = getattr(request.user, 'company', None)

            if not company or not company.plan:
                messages.error(request, 'No active plan')
                return redirect('companies:subscription_plans')

            # Skip check for SaaS admins
            if request.user.is_saas_admin:
                return view_func(request, *args, **kwargs)

            # Check feature access
            if not getattr(company.plan, feature_name, False):
                messages.warning(
                    request,
                    f'This feature is not available in your current plan. Please upgrade.'
                )
                return redirect('companies:subscription_plans')

            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator

def require_active_company(view_func):
    """Decorator to ensure company has active access"""

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')

        company = request.user.company
        if not company or not company.has_active_access:
            messages.error(request, "Your company account does not have active access.")
            return redirect('company_expired')

        return view_func(request, *args, **kwargs)

    return wrapper



def require_public_schema(view_func):
    """
    Decorator to ensure a view runs in the public schema.
    Critical for tenant creation and other public schema operations.
    """

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        public_schema = get_public_schema_name()
        current_schema = connection.schema_name

        if current_schema != public_schema:
            logger.warning(
                f"View {view_func.__name__} called from tenant schema '{current_schema}'. "
                f"Switching to public schema '{public_schema}'"
            )
            connection.set_schema_to_public()

        return view_func(request, *args, **kwargs)

    return wrapper

# Usage in views.py:
# from .decorators import require_public_schema
#
# @login_required
# @require_public_schema
# def create_tenant_view(request):
#     ...