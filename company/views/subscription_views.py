import logging
from decimal import Decimal
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import JsonResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import TemplateView, ListView
from datetime import timedelta

from ..models import Company, SubscriptionPlan
from ..services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)


class SubscriptionDashboardView(LoginRequiredMixin, TemplateView):
    """
    Main subscription dashboard showing current plan, usage, and options
    """
    template_name = 'company/subscription/dashboard.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user

        # Get company
        company = getattr(user, 'company', None)
        if not company:
            raise Http404("No company associated with user")

        # Current plan details
        # NOTE: We do not call check_and_update_access_status() here — it writes
        # to the DB and is already run by CompanyAccessMiddleware and the periodic
        # Celery task. Reading company.status directly is sufficient and safe.
        plan = company.plan

        # Calculate usage with safe defaults
        from accounts.models import CustomUser

        usage_data = {
            'users': {
                'current': CustomUser.objects.filter(
                    company=company, is_hidden=False
                ).count(),
                'limit': plan.max_users if plan else 0,
            },
            'branches': {
                'current': company.branches_count,
                'limit': plan.max_branches if plan else 0,
            },
            'storage': {
                'current_mb': company.storage_used_mb,
                'current_gb': round(company.storage_used_mb / 1024, 2),
                'limit_gb': plan.max_storage_gb if plan else 0,
                'percentage': company.storage_usage_percentage,
            },
            'api_calls': {
                'current': company.api_calls_this_month,
                'limit': plan.max_api_calls_per_month if plan else 0,
            },
        }

        # Calculate percentages SAFELY
        for key, data in usage_data.items():
            try:
                # Ensure all required keys exist with safe defaults
                current = data.get('current', 0)
                limit = data.get('limit', 0)

                if limit and limit > 0:
                    data['percentage'] = round((current / limit) * 100, 1)
                else:
                    data['percentage'] = 0

                # Ensure 'current' key exists for recommendations
                if 'current' not in data:
                    data['current'] = 0

            except (KeyError, TypeError, ZeroDivisionError) as e:
                # Log error and set safe default
                logger.warning(f"Error calculating usage percentage for {key}: {e}")
                data['percentage'] = 0

        # Subscription status
        status_info = {
            'is_trial': company.is_trial,
            'is_active': company.status == 'ACTIVE',
            'is_expired': company.status == 'EXPIRED',
            'is_suspended': company.status == 'SUSPENDED',
            'in_grace_period': company.is_in_grace_period,
            'days_until_expiry': company.days_until_expiry,
            'trial_ends_at': company.trial_ends_at,
            'subscription_ends_at': company.subscription_ends_at,
            'grace_period_ends_at': company.grace_period_ends_at,
            'next_billing_date': company.next_billing_date,
        }

        # Available upgrade options
        available_plans = SubscriptionPlan.objects.filter(
            is_active=True
        ).order_by('sort_order', 'price')

        # Recommendations
        recommendations = []

        # Check if nearing limits (safely)
        for key, data in usage_data.items():
            percentage = data.get('percentage', 0)
            if percentage > 80:
                recommendations.append({
                    'type': 'warning',
                    'category': key,
                    'message': f"You're using {percentage}% of your {key.replace('_', ' ')} limit",
                    'action': 'Consider upgrading your plan',
                })

        # Check subscription status
        if company.is_trial and status_info['days_until_expiry'] <= 7:
            recommendations.append({
                'type': 'urgent',
                'category': 'trial',
                'message': f"Your trial expires in {status_info['days_until_expiry']} days",
                'action': 'Upgrade to a paid plan to continue using all features',
            })
        elif not company.is_trial and status_info['days_until_expiry'] <= 7:
            recommendations.append({
                'type': 'urgent',
                'category': 'renewal',
                'message': f"Your subscription expires in {status_info['days_until_expiry']} days",
                'action': 'Renew your subscription to avoid service interruption',
            })

        context.update({
            'company': company,
            'current_plan': plan,
            'usage_data': usage_data,
            'status_info': status_info,
            'available_plans': available_plans,
            'recommendations': recommendations,
            'features_list': plan.get_feature_list() if plan else [],
        })

        return context


class SubscriptionPlansView(LoginRequiredMixin, ListView):
    """
    View to browse and compare subscription plans
    """
    model = SubscriptionPlan
    template_name = 'company/subscription/plans.html'
    context_object_name = 'plans'

    def get_queryset(self):
        return SubscriptionPlan.objects.filter(
            is_active=True
        ).order_by('sort_order', 'price')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        company = getattr(self.request.user, 'company', None)
        if not company:
            raise Http404("No company associated with user")

        context['company'] = company
        context['current_plan'] = company.plan

        # Add comparison data
        plans = context['plans']

        # Features comparison matrix
        all_features = set()
        for plan in plans:
            all_features.update(plan.get_feature_list())

        context['all_features'] = sorted(all_features)

        # Billing cycle selection
        context['billing_cycle'] = self.request.GET.get('billing_cycle', 'MONTHLY')

        return context

@login_required
def get_subscription_limits(request):
    """API endpoint to get current subscription limits"""
    company = getattr(request.user, 'company', None)
    if not company:
        return JsonResponse({'error': 'No company found'}, status=404)

    # Refresh from DB to get current field values without triggering a full
    # status update write (that is handled by middleware and periodic tasks)
    company.refresh_from_db(fields=[
        'status', 'is_active', 'storage_used_mb', 'api_calls_this_month',
        'subscription_ends_at', 'trial_ends_at'
    ])

    limits = {
        'users': {
            'current': company.active_users_count,
            'limit': company.plan.max_users if company.plan else 0,
            'available': max(0, (company.plan.max_users if company.plan else 0) - company.active_users_count),
            'exceeded': company.active_users_count >= (company.plan.max_users if company.plan else 0),
            'percentage': round((company.active_users_count / company.plan.max_users * 100) if company.plan and company.plan.max_users > 0 else 0, 1)
        },
        'branches': {
            'current': company.branches_count,
            'limit': company.plan.max_branches if company.plan else 0,
            'available': max(0, (company.plan.max_branches if company.plan else 0) - company.branches_count),
            'exceeded': company.branches_count >= (company.plan.max_branches if company.plan else 0),
            'percentage': round((company.branches_count / company.plan.max_branches * 100) if company.plan and company.plan.max_branches > 0 else 0, 1)
        },
        'storage': {
            'current_mb': company.storage_used_mb,
            'limit_gb': company.plan.max_storage_gb if company.plan else 0,
            'percentage': round(company.storage_usage_percentage, 1),
            'exceeded': company.storage_usage_percentage >= 100,
        }
    }

    return JsonResponse({
        'success': True,
        'limits': limits,
        'plan': {
            'name': company.plan.display_name if company.plan else 'No Plan',
            'status': company.status,
            'is_active': company.is_active
        }
    })

class SubscriptionUpgradeView(LoginRequiredMixin, View):
    """
    Handle subscription upgrade requests
    """

    def get(self, request, *args, **kwargs):
        """Show upgrade confirmation page"""
        company = getattr(request.user, 'company', None)
        if not company:
            raise Http404("No company associated with user")

        plan_id = kwargs.get('plan_id')
        new_plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)

        # Calculate costs
        billing_cycle = request.GET.get('billing_cycle', 'MONTHLY')

        # Prorated calculation if mid-cycle upgrade
        proration_credit = Decimal('0.00')
        if company.subscription_ends_at and not company.is_trial:
            days_remaining = (company.subscription_ends_at - timezone.now().date()).days
            if days_remaining > 0 and company.plan:
                # Calculate credit from current plan
                current_daily_rate = company.plan.price / 30  # Simplified
                proration_credit = current_daily_rate * days_remaining

        # Calculate new cost
        upgrade_cost = new_plan.price + new_plan.setup_fee - proration_credit

        context = {
            'company': company,
            'current_plan': company.plan,
            'new_plan': new_plan,
            'billing_cycle': billing_cycle,
            'upgrade_cost': max(upgrade_cost, Decimal('0.00')),
            'proration_credit': proration_credit,
            'setup_fee': new_plan.setup_fee,
        }

        return render(request, 'company/subscription/upgrade_confirm.html', context)

    def post(self, request, *args, **kwargs):
        """Process upgrade"""
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        plan_id = kwargs.get('plan_id')
        billing_cycle = request.POST.get('billing_cycle', 'MONTHLY').strip().upper()
        payment_method = request.POST.get('payment_method', '').strip()

        if billing_cycle not in ('MONTHLY', 'QUARTERLY', 'YEARLY'):
            return JsonResponse({
                'success': False,
                'message': f'Invalid billing cycle: {billing_cycle!r}.'
            }, status=400)

        try:
            new_plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)

            # Validate upgrade
            if company.plan and new_plan.price <= company.plan.price:
                return JsonResponse({
                    'success': False,
                    'message': 'Selected plan is not an upgrade. Use downgrade instead.'
                }, status=400)

            # Delegate to Pesapal payment flow — subscription is activated
            # automatically by the IPN callback once payment is confirmed.
            from .billing_views import InitiateSubscriptionPaymentView
            view = InitiateSubscriptionPaymentView()
            view.request = request
            return view.post(request, plan_id=plan_id)

        except SubscriptionPlan.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Plan not found'
            }, status=404)

        except Exception as e:
            logger.error(f"Error upgrading subscription: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'An error occurred during upgrade'
            }, status=500)


class SubscriptionDowngradeView(LoginRequiredMixin, View):
    """
    Handle subscription downgrade requests
    """

    def get(self, request, *args, **kwargs):
        """Show downgrade confirmation page"""
        company = getattr(request.user, 'company', None)
        if not company:
            raise Http404("No company associated with user")

        plan_id = kwargs.get('plan_id')
        new_plan = get_object_or_404(SubscriptionPlan, id=plan_id, is_active=True)

        # Check for potential issues
        from accounts.models import CustomUser

        issues = []

        # Check user limit
        current_users = CustomUser.objects.filter(
            company=company, is_hidden=False
        ).count()
        if current_users > new_plan.max_users:
            issues.append({
                'type': 'users',
                'message': f'You have {current_users} users but the new plan allows only {new_plan.max_users}',
                'action': f'Please deactivate {current_users - new_plan.max_users} users before downgrading'
            })

        # Check branch limit
        if company.branches_count > new_plan.max_branches:
            issues.append({
                'type': 'branches',
                'message': f'You have {company.branches_count} branches but the new plan allows only {new_plan.max_branches}',
                'action': f'Please deactivate {company.branches_count - new_plan.max_branches} branches before downgrading'
            })

        # Check storage
        storage_gb = company.storage_used_mb / 1024
        if storage_gb > new_plan.max_storage_gb:
            issues.append({
                'type': 'storage',
                'message': f'You are using {storage_gb:.2f}GB but the new plan allows only {new_plan.max_storage_gb}GB',
                'action': 'Please reduce your storage usage before downgrading'
            })

        # Features that will be lost
        lost_features = []
        if company.plan:
            current_features = set(company.plan.get_feature_list())
            new_features = set(new_plan.get_feature_list())
            lost_features = list(current_features - new_features)

        context = {
            'company': company,
            'current_plan': company.plan,
            'new_plan': new_plan,
            'issues': issues,
            'can_downgrade': len(issues) == 0,
            'lost_features': lost_features,
            'effective_date': company.subscription_ends_at,
        }

        return render(request, 'company/subscription/downgrade_confirm.html', context)

    def post(self, request, *args, **kwargs):
        """Process downgrade"""
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        plan_id = kwargs.get('plan_id')

        try:
            new_plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)

            # Validate downgrade
            if company.plan and new_plan.price >= company.plan.price:
                return JsonResponse({
                    'success': False,
                    'message': 'Selected plan is not a downgrade. Use upgrade instead.'
                }, status=400)

            # Process through service
            service = SubscriptionService()
            result = service.downgrade_subscription(
                company=company,
                new_plan=new_plan,
                downgraded_by=request.user
            )

            if result['success']:
                messages.success(
                    request,
                    f"Downgrade scheduled to {new_plan.display_name}. "
                    f"Changes will take effect on {company.subscription_ends_at}"
                )

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse(result)

                return redirect('companies:subscription_dashboard')
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse(result, status=400)

                messages.error(request, result.get('message', 'Downgrade failed'))
                return redirect('companies:subscription_plans')

        except SubscriptionPlan.DoesNotExist:
            return JsonResponse({
                'success': False,
                'message': 'Plan not found'
            }, status=404)

        except Exception as e:
            logger.error(f"Error downgrading subscription: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'An error occurred during downgrade'
            }, status=500)


class SubscriptionRenewView(LoginRequiredMixin, View):
    """
    Handle subscription renewal
    """

    def get(self, request, *args, **kwargs):
        """Show renewal confirmation page"""
        company = getattr(request.user, 'company', None)
        if not company:
            raise Http404("No company associated with user")

        if not company.plan:
            messages.error(request, 'No active plan to renew')
            return redirect('companies:subscription_plans')

        # Calculate renewal cost
        billing_cycle = request.GET.get('billing_cycle', company.plan.billing_cycle)

        context = {
            'company': company,
            'plan': company.plan,
            'billing_cycle': billing_cycle,
            'renewal_cost': company.plan.price,
            'current_expiry': company.subscription_ends_at,
        }

        return render(request, 'company/subscription/renew_confirm.html', context)

    def post(self, request, *args, **kwargs):
        """Process renewal"""
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        if not company.plan:
            return JsonResponse({
                'success': False,
                'message': 'No active plan to renew'
            }, status=400)

        billing_cycle = request.POST.get('billing_cycle', '').strip().upper()
        payment_method = request.POST.get('payment_method', '').strip()

        if billing_cycle not in ('MONTHLY', 'QUARTERLY', 'YEARLY'):
            return JsonResponse({
                'success': False,
                'message': f'Invalid billing cycle: {billing_cycle!r}. Must be MONTHLY, QUARTERLY, or YEARLY.'
            }, status=400)

        try:
            # Delegate to Pesapal payment flow — subscription is activated
            # automatically by the IPN callback once payment is confirmed.
            from .billing_views import InitiateSubscriptionPaymentView
            view = InitiateSubscriptionPaymentView()
            view.request = request
            return view.post(request, plan_id=company.plan_id)

        except Exception as e:
            logger.error(f"Error renewing subscription: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'An error occurred during renewal'
            }, status=500)


class SubscriptionCancelView(LoginRequiredMixin, View):
    """
    Handle subscription cancellation
    """

    def get(self, request, *args, **kwargs):
        """Show cancellation confirmation page"""
        company = getattr(request.user, 'company', None)
        if not company:
            raise Http404("No company associated with user")

        context = {
            'company': company,
            'plan': company.plan,
            'cancellation_date': company.subscription_ends_at,
        }

        return render(request, 'company/subscription/cancel_confirm.html', context)

    def post(self, request, *args, **kwargs):
        """Process cancellation"""
        company = getattr(request.user, 'company', None)
        if not company:
            return JsonResponse({
                'success': False,
                'message': 'No company found'
            }, status=404)

        reason = request.POST.get('reason', '')
        immediate = request.POST.get('immediate', 'false') == 'true'

        try:
            # Process through service
            service = SubscriptionService()
            result = service.cancel_subscription(
                company=company,
                reason=reason,
                immediate=immediate,
                cancelled_by=request.user
            )

            if result['success']:
                if immediate:
                    messages.warning(request, 'Subscription cancelled immediately')
                else:
                    messages.info(
                        request,
                        f"Subscription will be cancelled on {company.subscription_ends_at}"
                    )

                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse(result)

                return redirect('companies:subscription_dashboard')
            else:
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return JsonResponse(result, status=400)

                messages.error(request, result.get('message', 'Cancellation failed'))
                return redirect('companies:subscription_dashboard')

        except Exception as e:
            logger.error(f"Error cancelling subscription: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'An error occurred during cancellation'
            }, status=500)