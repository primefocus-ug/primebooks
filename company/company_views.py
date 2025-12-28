import secrets
import string
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.shortcuts import redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.db import transaction
from django.http import JsonResponse, HttpResponse
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.http import HttpResponseForbidden
from django.views.generic import (ListView, CreateView, DetailView, UpdateView, DeleteView, TemplateView)
from django.views import View
from django.contrib.auth import get_user_model
import json
from dateutil.relativedelta import relativedelta
import csv
from decimal import Decimal
from accounts.utils import require_saas_admin, require_company_access
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, get_object_or_404
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.views.generic import DetailView
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Sum, Count, Avg, F, Q
from django.utils import timezone
from django.http import Http404
import logging
from django.views.decorators.http import require_POST
from accounts.utils import require_saas_admin, require_company_access


from sales.models import Sale, SaleItem
from stores.models import Store, DeviceOperatorLog #StoreInventory,
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from datetime import  timedelta
from accounts.forms import CompanyUserForm
from .models import Company, Domain, SubscriptionPlan
from accounts.models import CustomUser
from inventory.models import Stock
from accounts.utils import get_visible_users, can_access_company
from .forms import (
    CompanyForm, DomainForm, BulkActionForm, SearchForm,
    CompanyBranchFormSet,CompanyEmployeeFormSet
)

User = get_user_model()
logger = logging.getLogger(__name__)


@require_saas_admin
@require_http_methods(["GET", "POST"])
def company_action(request, company_id):
    """Display a confirmation page and perform SaaS admin actions on a company"""
    company = get_object_or_404(Company, pk=company_id)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "activate":
            company.reactivate_company(reason="Activated by SaaS admin")
            messages.success(request, f"✅ Company {company.name} activated")

        elif action == "deactivate":
            company.deactivate_company(reason="Deactivated by SaaS admin")
            messages.warning(request, f"⚠️ Company {company.name} deactivated")

        elif action == "suspend":
            company.suspend_for_misbehavior(reason="Suspended by SaaS admin", suspended_by=request.user)
            messages.warning(request, f"⚠️ Company {company.name} suspended")

        elif action == "archive":
            company.status = "ARCHIVED"
            company.is_active = False
            company.save()
            messages.error(request, f"🗄️ Company {company.name} archived")

        else:
            return HttpResponseForbidden("Unknown action")

        return redirect("companies:company_detail", company_id=company.company_id)

    # For GET requests, render the confirmation page
    return render(request, "company/company_action.html", {"company": company})


def generate_random_password(length=12):
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


class CompanyMetricsAPIView(LoginRequiredMixin, View):
    """API endpoint for real-time company metrics"""

    def get(self, request, company_id):
        try:
            company = Company.objects.get(company_id=company_id)

            # Check permissions
            if not request.user.can_access_company(company):
                return JsonResponse({'error': 'Permission denied'}, status=403)

            today = timezone.now().date()
            thirty_days_ago = today - timedelta(days=30)

            # Get basic metrics
            branches = Store.objects.filter(company=company)
            employees = CustomUser.objects.filter(company=company, is_hidden=False)

            # Revenue metrics
            all_stores = Store.objects.filter(company=company)
            store_ids = all_stores.values_list('id', flat=True)

            today_revenue = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date=today,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(total=Sum('total_amount'))['total'] or Decimal('0')

            today_sales = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date=today,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).count()

            # Active users (last 15 minutes)
            active_users = CustomUser.objects.filter(
                company=company,
                is_active=True,
                last_activity_at__gte=timezone.now() - timedelta(minutes=15)
            ).count()

            #Inventory alerts
            low_stock = Stock.objects.filter(
                store__in=all_stores,
                quantity__lte=F('low_stock_threshold')
            ).count()

            out_of_stock = Stock.objects.filter(
                store__in=all_stores,
                quantity=0
            ).count()

            return JsonResponse({
                'success': True,
                'metrics': {
                    'total_branches': branches.count(),
                    'active_branches': branches.filter(is_active=True).count(),
                    'total_employees': employees.count(),
                    'active_employees': employees.filter(is_active=True).count(),
                    'today_revenue': float(today_revenue),
                    'today_sales': today_sales,
                    'active_users': active_users,
                    'inventory_alerts': {
                        'low_stock_items': low_stock,
                        'out_of_stock_items': out_of_stock
                    }
                },
                'timestamp': timezone.now().isoformat()
            })

        except Company.DoesNotExist:
            return JsonResponse({'error': 'Company not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class CompanyStatusAPIView(LoginRequiredMixin, View):
    """API endpoint for company status checks"""

    def get(self, request, company_id):
        try:
            company = Company.objects.get(company_id=company_id)

            if not request.user.can_access_company(company):
                return JsonResponse({'error': 'Permission denied'}, status=403)

            return JsonResponse({
                'success': True,
                'status': company.status,
                'status_changed': False,  # You could implement status change detection
                'last_updated': company.updated_at.isoformat() if hasattr(company, 'updated_at') else None
            })

        except Company.DoesNotExist:
            return JsonResponse({'error': 'Company not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)


class BranchAnalyticsAPIView(LoginRequiredMixin, View):
    """API endpoint for branch analytics (WebSocket fallback)"""

    def get(self, request, store_id):
        try:
            branch = Store.objects.select_related('company').get(id=store_id)

            if not request.user.can_access_company(branch.company):
                return JsonResponse({'error': 'Permission denied'}, status=403)

            # Use the same logic from the WebSocket consumer
            thirty_days_ago = timezone.now().date() - timedelta(days=30)
            sixty_days_ago = timezone.now().date() - timedelta(days=60)

            stores = branch.stores.all()
            store_ids = stores.values_list('id', flat=True)

            # Current metrics
            current_metrics = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                total_revenue=Sum('total_amount'),
                total_sales=Count('id'),
                avg_sale=Avg('total_amount'),
                unique_customers=Count('customer', distinct=True)
            )

            # Previous period for growth calculation
            prev_metrics = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date__range=[sixty_days_ago, thirty_days_ago],
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                total_revenue=Sum('total_amount'),
                total_sales=Count('id')
            )

            # Calculate growth rates
            revenue_growth = 0
            sales_growth = 0
            customer_growth = 0

            if prev_metrics['total_revenue'] and current_metrics['total_revenue']:
                revenue_growth = round(
                    ((float(current_metrics['total_revenue']) - float(prev_metrics['total_revenue'])) /
                     float(prev_metrics['total_revenue'])) * 100, 1
                )

            if prev_metrics['total_sales']:
                sales_growth = round(
                    ((current_metrics['total_sales'] - prev_metrics['total_sales']) /
                     prev_metrics['total_sales']) * 100, 1
                )

            # Revenue data for chart (last 7 days)
            revenue_data = {'labels': [], 'values': []}
            for i in range(7):
                date = timezone.now().date() - timedelta(days=6 - i)
                daily_revenue = Sale.objects.filter(
                    store_id__in=store_ids,
                    created_at__date=date,
                    is_voided=False,
                    status__in=['COMPLETED', 'PAID']
                ).aggregate(total=Sum('total_amount'))['total'] or 0

                revenue_data['labels'].append(date.strftime('%m/%d'))
                revenue_data['values'].append(float(daily_revenue))

            # Store performance
            store_details = []
            store_performance = {'labels': [], 'values': []}

            for store in stores:
                store_metrics = Sale.objects.filter(
                    store=store,
                    created_at__date__gte=thirty_days_ago,
                    is_voided=False,
                    status__in=['COMPLETED', 'PAID']
                ).aggregate(
                    revenue=Sum('total_amount'),
                    sales_count=Count('id')
                )

                store_revenue = float(store_metrics['revenue'] or 0)

                store_details.append({
                    'name': store.name,
                    'revenue_30d': store_revenue,
                    'sales_count': store_metrics['sales_count'] or 0
                })

                store_performance['labels'].append(store.name)
                store_performance['values'].append(store_revenue)

            # Inventory alerts
            low_stock_items = Stock.objects.filter(
                store__in=stores,
                quantity__lte=F('low_stock_threshold')
            ).count()

            return JsonResponse({
                'success': True,
                'metrics': {
                    'total_revenue': float(current_metrics['total_revenue'] or 0),
                    'revenue_growth': revenue_growth,
                    'total_sales': current_metrics['total_sales'] or 0,
                    'sales_growth': sales_growth,
                    'total_customers': current_metrics['unique_customers'] or 0,
                    'customer_growth': customer_growth,
                    'low_stock_items': low_stock_items,
                },
                'revenue_data': revenue_data,
                'store_performance': store_performance,
                'store_details': store_details,
                'timestamp': timezone.now().isoformat()
            })

        except Store.DoesNotExist:
            return JsonResponse({'error': 'Branch not found'}, status=404)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)




class DashboardView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    """Dashboard view showing only the current user's company."""
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

        company = user_company
        context['company'] = company
        context['company_id'] = company.company_id
        context['is_saas_admin'] = False  # Even if user is SaaS admin, only current company is shown

        # Company stats
        total_branches = Store.objects.filter(company=company, is_active=True).count()
        total_employees = CustomUser.objects.filter(company=company, is_active=True, is_hidden=False).count()

        context.update({
            'total_companies': 1,
            'verified_companies': 1 if company.is_verified else 0,
            'efris_enabled_companies': 1 if company.efris_enabled else 0,
            'active_companies': 1 if company.status == 'ACTIVE' else 0,
            'trial_companies': 1 if company.status == 'TRIAL' else 0,
            'expired_companies': 1 if company.status == 'EXPIRED' else 0,
            'recent_companies': [company],
            'total_branches': total_branches,
            'total_employees': total_employees,
            # Charts data
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

            count = 1 if (company.created_at >= month_start and company.created_at <= month_end) else 0

            data.append({
                'month': month_start.strftime('%b %Y'),
                'count': count
            })

        return list(reversed(data))



class CompanyListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """Enhanced company list with proper tenant filtering."""
    model = Company
    template_name = 'company/company_list.html'
    context_object_name = 'companies'
    paginate_by = 25
    permission_required = 'company.view_company'

    def get_queryset(self):
        # Base queryset with related data
        queryset = Company.objects.select_related('plan').prefetch_related('domains')

        # Apply tenant filtering based on user permissions
        if not self.request.user.is_saas_admin:
            # Non-SaaS admin users can only see their own company
            user_company = getattr(self.request.user, 'company', None)
            if user_company:
                queryset = queryset.filter(company_id=user_company.company_id)
            else:
                queryset = queryset.none()

        # Search functionality
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(trading_name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(tin__icontains=search_query) |
                Q(brn__icontains=search_query) |
                Q(physical_address__icontains=search_query)
            )

        # Status filter
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        # Verification filter
        is_verified = self.request.GET.get('is_verified')
        if is_verified:
            queryset = queryset.filter(is_verified=(is_verified.lower() == 'true'))

        # EFRIS filter
        efris_enabled = self.request.GET.get('efris_enabled')
        if efris_enabled:
            queryset = queryset.filter(efris_enabled=(efris_enabled.lower() == 'true'))

        # Currency filter
        currency = self.request.GET.get('currency')
        if currency:
            queryset = queryset.filter(preferred_currency=currency)

        # Plan filter
        plan = self.request.GET.get('plan')
        if plan:
            queryset = queryset.filter(plan_id=plan)

        # Date range filters
        created_after = self.request.GET.get('created_after')
        if created_after:
            queryset = queryset.filter(created_at__gte=created_after)

        created_before = self.request.GET.get('created_before')
        if created_before:
            queryset = queryset.filter(created_at__lte=created_before)

        # Sorting
        sort = self.request.GET.get('sort', '-created_at')
        allowed_sorts = ['name', '-name', 'created_at', '-created_at', 'is_verified', '-is_verified', 'status',
                         '-status']
        if sort not in allowed_sorts:
            sort = '-created_at'
        queryset = queryset.order_by(sort)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = SearchForm(self.request.GET)
        context['bulk_form'] = BulkActionForm()
        context['is_saas_admin'] = self.request.user.is_saas_admin

        # Add filter options
        context['status_choices'] = Company.STATUS_CHOICES
        context['currency_choices'] = Company.CURRENCY_CHOICES
        context['plans'] = SubscriptionPlan.objects.filter(is_active=True)

        # Current filters for template
        context['current_filters'] = {
            'q': self.request.GET.get('q', ''),
            'status': self.request.GET.get('status', ''),
            'is_verified': self.request.GET.get('is_verified', ''),
            'efris_enabled': self.request.GET.get('efris_enabled', ''),
            'currency': self.request.GET.get('currency', ''),
            'plan': self.request.GET.get('plan', ''),
            'sort': self.request.GET.get('sort', '-created_at'),
        }

        return context

    def post(self, request, *args, **kwargs):
        """Handle bulk actions (SaaS admin only)."""
        if not request.user.is_saas_admin:
            messages.error(request, _('Permission denied.'))
            return redirect('companies:company_list')

        bulk_form = BulkActionForm(request.POST)
        if bulk_form.is_valid():
            action = bulk_form.cleaned_data['action']
            selected_items = json.loads(bulk_form.cleaned_data['selected_items'])

            if not selected_items:
                messages.warning(request, _('No items selected.'))
                return redirect('companies:company_list')

            companies = Company.objects.filter(company_id__in=selected_items)

            # Perform bulk actions
            if action == 'verify':
                updated = companies.update(is_verified=True)
                messages.success(request, _('Successfully verified %d companies.') % updated)

            elif action == 'unverify':
                updated = companies.update(is_verified=False)
                messages.success(request, _('Successfully unverified %d companies.') % updated)

            elif action == 'enable_efris':
                updated = companies.update(efris_enabled=True)
                messages.success(request, _('Enabled EFRIS for %d companies.') % updated)

            elif action == 'disable_efris':
                updated = companies.update(efris_enabled=False)
                messages.success(request, _('Disabled EFRIS for %d companies.') % updated)

            elif action == 'suspend':
                for company in companies:
                    company.suspend_for_misbehavior("Bulk suspended by admin", suspended_by=request.user)
                messages.success(request, _('Successfully suspended %d companies.') % companies.count())

            elif action == 'activate':
                for company in companies:
                    company.reactivate_company("Bulk activated by admin")
                messages.success(request, _('Successfully activated %d companies.') % companies.count())

            elif action == 'delete':
                count = companies.count()
                companies.delete()
                messages.success(request, _('Successfully deleted %d companies.') % count)

        return redirect('companies:company_list')



class CompanyDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = Company
    template_name = 'company/company_detail.html'
    context_object_name = 'company'
    slug_field = 'company_id'
    slug_url_kwarg = 'company_id'
    paginate_branches_by = 10
    paginate_employees_by = 10
    permission_required = 'company.view_company'

    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()

        company_id = self.kwargs.get(self.slug_url_kwarg)
        try:
            obj = queryset.select_related('plan').prefetch_related('domains').get(**{self.slug_field: company_id})

            # Check access permissions
            if not self.request.user.is_saas_admin:
                # Get user's company
                user_company = getattr(self.request.user, 'company', None)

                # 🔥 FIX: Compare company IDs as strings
                if user_company:
                    belongs_to_company = str(user_company.company_id) == str(obj.company_id)
                else:
                    belongs_to_company = False

                # Check if user has permission OR belongs to company
                has_permission = self.request.user.has_perm('company.view_company')

                if not (has_permission and belongs_to_company):
                    # User needs BOTH permission AND company membership
                    raise Http404("Company not found")

        except Company.DoesNotExist:
            raise Http404("Company not found")
        return obj

    def get_queryset(self):
        return Company.objects.select_related('plan').prefetch_related('domains')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.object

        # Check company access and update status
        company.check_and_update_access_status()

        # Branches with analytics
        branches_data = self._get_paginated_branches_with_analytics(company)
        context.update(branches_data)

        # Employees
        employees_data = self._get_paginated_employees(company)
        context.update(employees_data)

        # Company statistics with analytics
        statistics = self._get_company_statistics_with_analytics(company)
        context.update(statistics)

        # Branch performance overview
        branch_performance = self._get_branch_performance_overview(company)
        context.update(branch_performance)

        # Management and staff analytics
        management_data = self._get_management_analytics(company)
        context.update(management_data)

        # Revenue analytics
        revenue_data = self._get_company_revenue_analytics(company)
        context.update(revenue_data)

        # Recent activities with more context
        context['recent_activities'] = self._get_recent_activities_enhanced(company)

        # Operational metrics
        operational_metrics = self._get_operational_metrics(company)
        context.update(operational_metrics)

        # Access status and restrictions
        context['access_restrictions'] = company.get_access_restrictions()
        context['can_perform_actions'] = {
            'create_invoice': company.can_perform_action('create_invoice')[0],
            'add_user': company.can_perform_action('add_user')[0],
            'use_efris': company.can_perform_action('use_efris')[0],
            'export_data': company.can_perform_action('export_data')[0],
        }

        # EFRIS status
        context['efris_status'] = {
            'enabled': company.efris_enabled,
            'active': company.efris_is_active,
            'configured': company.efris_configuration_complete,
            'errors': company.get_efris_configuration_errors(),
            'status_display': company.efris_status_display,
        }

        return context

    def _get_paginated_branches_with_analytics(self, company):
        """
        Get paginated stores (branches) with performance analytics.
        Each store now represents what was previously a branch.
        """
        try:
            # Get all stores for this company
            # No need to prefetch 'stores' - Store IS the branch now!
            queryset = Store.objects.filter(
                company=company
            ).order_by('-is_main_branch', 'name')

            # Add analytics to each store (branch)
            branches_with_analytics = []
            thirty_days_ago = timezone.now().date() - timedelta(days=30)

            for store in queryset:  # Each store is a branch
                try:
                    # Get sales for THIS store only
                    # No need to get multiple stores - this store IS the branch
                    sales_data = Sale.objects.filter(
                        store=store,  # Just this store
                        created_at__date__gte=thirty_days_ago,
                        is_voided=False,
                        status__in=['COMPLETED', 'PAID']
                    ).aggregate(
                        total_revenue=Sum('total_amount'),
                        total_sales=Count('id'),
                        avg_sale=Avg('total_amount')
                    )

                    # Store/Branch analytics
                    store.analytics = {
                        # Store-level metrics (branch is the store itself)
                        'total_stores': 1,  # This store itself
                        'active_stores': 1 if store.is_active else 0,
                        'total_revenue_30d': float(sales_data['total_revenue'] or 0),
                        'total_sales_30d': sales_data['total_sales'] or 0,
                        'avg_sale_amount': float(sales_data['avg_sale'] or 0),

                        # Inventory metrics
                        'stores_with_inventory': 1 if Stock.objects.filter(
                            store=store
                        ).exists() else 0,
                        'low_stock_items': Stock.objects.filter(
                            store=store,
                            quantity__lte=F('low_stock_threshold')
                        ).count(),
                    }

                    # Performance score calculation
                    performance_score = self._calculate_branch_performance_score(store.analytics)
                    store.analytics['performance_score'] = performance_score

                except Exception as e:
                    logger.error(f"Error calculating analytics for store {store.id}: {e}")
                    store.analytics = {
                        'total_stores': 0,
                        'active_stores': 0,
                        'total_revenue_30d': 0,
                        'total_sales_30d': 0,
                        'avg_sale_amount': 0,
                        'stores_with_inventory': 0,
                        'low_stock_items': 0,
                        'performance_score': 0,
                    }

                branches_with_analytics.append(store)

            # Paginate the enhanced stores (branches)
            paginator = Paginator(branches_with_analytics, self.paginate_branches_by)
            page_number = self.request.GET.get('branches_page', 1)
            try:
                page = paginator.page(page_number)
            except (PageNotAnInteger, EmptyPage):
                page = paginator.page(1)

            return {
                'branches': page,  # These are Store objects, but context name kept for template compatibility
                'total_branches': paginator.count,
                'branches_paginator': paginator,
                'branches_with_analytics': branches_with_analytics,
            }
        except Exception as e:
            logger.error(f"Error fetching branches with analytics for company {company}: {e}", exc_info=True)
            return {'branches': None, 'total_branches': 0, 'branches_paginator': None}

    def _get_paginated_employees(self, company):
        """Get paginated employees with role analytics."""
        try:
            queryset = CustomUser.objects.filter(
                company=company,
                is_active=True,
                is_hidden=False
            ).select_related('company').order_by('first_name', 'last_name')

            paginator = Paginator(queryset, self.paginate_employees_by)
            page_number = self.request.GET.get('employees_page', 1)
            try:
                page = paginator.page(page_number)
            except (PageNotAnInteger, EmptyPage):
                page = paginator.page(1)

            return {
                'employees': page,
                'total_employees': paginator.count,
                'employees_paginator': paginator,
            }
        except Exception as e:
            logger.error(f"Error fetching employees for company {company}: {e}", exc_info=True)
            return {'employees': None, 'total_employees': 0, 'employees_paginator': None}

    def _get_company_statistics_with_analytics(self, company):
        """Get enhanced company statistics with analytics."""
        stats = {}
        thirty_days_ago = timezone.now().date() - timedelta(days=30)

        try:
            # Branch statistics
            branches = Store.objects.filter(company=company)
            stats['total_branches'] = branches.count()
            stats['active_branches'] = branches.filter(is_active=True).count()
            stats['main_branches'] = branches.filter(is_main_branch=True).count()

            # Store statistics across all branches
            all_stores = Store.objects.filter(company=company)
            stats['total_stores'] = all_stores.count()
            stats['active_stores'] = all_stores.filter(is_active=True).count()

        except Exception as e:
            logger.error(f"Error calculating branch/store stats: {e}")
            stats.update({
                'total_branches': 0,
                'active_branches': 0,
                'main_branches': 0,
                'total_stores': 0,
                'active_stores': 0,
            })

        try:
            # Employee statistics with role breakdown
            all_employees = CustomUser.objects.filter(company=company, is_hidden=False)
            stats['total_employees'] = all_employees.count()
            stats['active_employees'] = all_employees.filter(is_active=True).count()

            # Role breakdown
            stats['company_admins'] = all_employees.filter(
                company_admin=True, is_active=True
            ).count()
            stats['managers'] = all_employees.filter(
                primary_role__name__iexact='Manager', is_active=True
            ).count()
            stats['cashiers'] = all_employees.filter(
                primary_role__name__iexact='Cashier', is_active=True
            ).count()
            stats['authorized_signatories_count'] = stats['company_admins']

        except Exception as e:
            logger.error(f"Error calculating employee stats: {e}")
            stats.update({
                'total_employees': 0,
                'active_employees': 0,
                'company_admins': 0,
                'managers': 0,
                'cashiers': 0,
                'authorized_signatories_count': 0,
            })

        # Storage usage calculation
        if company.plan and company.plan.max_storage_gb > 0:
            stats['storage_usage'] = min(
                round(company.storage_usage_percentage, 1), 100
            )
        else:
            stats['storage_usage'] = 0

        # Days until expiry
        stats['days_until_expiry'] = max(company.days_until_expiry, 0)

        return stats

    def _get_branch_performance_overview(self, company):
        """Get overall branch performance metrics."""
        try:
            branches = Store.objects.filter(company=company, is_active=True)
            thirty_days_ago = timezone.now().date() - timedelta(days=30)

            performance_data = {
                'top_performing_branches': [],
                'branches_needing_attention': [],
                'overall_performance_score': 0,
            }

            branch_performances = []

            for branch in branches:
                stores = Store.objects.filter(company=company)
                store_ids = stores.values_list('id', flat=True)

                # Calculate branch performance metrics
                metrics = Sale.objects.filter(
                    store_id__in=store_ids,
                    created_at__date__gte=thirty_days_ago,
                    is_voided=False,
                    status__in=['COMPLETED', 'PAID']
                ).aggregate(
                    revenue=Sum('total_amount'),
                    sales_count=Count('id'),
                    avg_sale=Avg('total_amount')
                )

                revenue = float(metrics['revenue'] or 0)
                sales_count = metrics['sales_count'] or 0
                avg_sale = float(metrics['avg_sale'] or 0)

                performance_score = self._calculate_branch_performance_score({
                    'total_revenue_30d': revenue,
                    'total_sales_30d': sales_count,
                    'avg_sale_amount': avg_sale,
                })

                branch_data = {
                    'branch': branch,
                    'revenue': revenue,
                    'sales_count': sales_count,
                    'avg_sale': avg_sale,
                    'performance_score': performance_score,
                }

                branch_performances.append(branch_data)

            # Sort by performance
            branch_performances.sort(key=lambda x: x['performance_score'], reverse=True)

            # Top 3 performing branches
            performance_data['top_performing_branches'] = branch_performances[:3]

            # Branches needing attention (bottom 20% or score < 30)
            threshold = max(1, len(branch_performances) // 5)  # Bottom 20%
            low_performers = [
                b for b in branch_performances
                if b['performance_score'] < 30
            ][-threshold:]
            performance_data['branches_needing_attention'] = low_performers

            # Overall company performance score
            if branch_performances:
                performance_data['overall_performance_score'] = round(
                    sum(b['performance_score'] for b in branch_performances) / len(branch_performances), 1
                )

            return performance_data

        except Exception as e:
            logger.error(f"Error calculating branch performance: {e}")
            return {
                'top_performing_branches': [],
                'branches_needing_attention': [],
                'overall_performance_score': 0,
            }

    def _get_management_analytics(self, company):
        """Get management and staff analytics."""
        try:
            thirty_days_ago = timezone.now().date() - timedelta(days=30)

            # Staff activity analytics
            all_staff = CustomUser.objects.filter(company=company, is_hidden=False, is_active=True)

            # Recent staff activities from device logs
            recent_staff_activities = []
            try:
                company_stores = Store.objects.filter(company=company)
                logs = DeviceOperatorLog.objects.filter(
                    device__store__in=company_stores,
                    timestamp__gte=timezone.now() - timedelta(days=7)
                ).select_related('user', 'device__store__company').order_by('-timestamp')[:15]

                for log in logs:
                    time_diff = timezone.now() - log.timestamp
                    if time_diff.days > 0:
                        time_ago = f"{time_diff.days} day{'s' if time_diff.days != 1 else ''} ago"
                    elif time_diff.seconds > 3600:
                        hours = time_diff.seconds // 3600
                        time_ago = f"{hours} hour{'s' if hours != 1 else ''} ago"
                    else:
                        minutes = max(1, time_diff.seconds // 60)
                        time_ago = f"{minutes} minute{'s' if minutes != 1 else ''} ago"

                    recent_staff_activities.append({
                        'user_name': log.user.get_full_name() or log.user.username,
                        'action': log.action.replace('_', ' ').title(),
                        'store_name': log.device.store.name if log.device else 'Unknown',
                        'branch_name': log.device.store.branch.name if log.device and log.device.store else 'Unknown',
                        'time_ago': time_ago,
                        'timestamp': log.timestamp,
                    })
            except Exception as e:
                logger.error(f"Error fetching staff activities: {e}")

            # Staff performance metrics
            staff_metrics = {
                'total_active_staff': all_staff.count(),
                'staff_by_role': {
                    'admins': all_staff.filter(company_admin=True).count(),
                    'managers': all_staff.filter(groups__role__group__name='Manager').distinct().count(),
                    'cashiers': all_staff.filter(groups__role__group__name='Cashier').distinct().count(),
                    'employees': all_staff.filter(groups__role__group__name='Viewer').distinct().count(),
                },
                'recent_activities': recent_staff_activities[:10],
                'staff_login_activity': all_staff.filter(
                    last_activity_at__gte=thirty_days_ago
                ).count(),
            }

            return staff_metrics

        except Exception as e:
            logger.error(f"Error calculating management analytics: {e}")
            return {
                'total_active_staff': 0,
                'staff_by_role': {'admins': 0, 'managers': 0, 'cashiers': 0, 'employees': 0},
                'recent_activities': [],
                'staff_login_activity': 0,
            }

    def _get_company_revenue_analytics(self, company):
        """Get company-wide revenue analytics."""
        try:
            thirty_days_ago = timezone.now().date() - timedelta(days=30)
            sixty_days_ago = timezone.now().date() - timedelta(days=60)
            seven_days_ago = timezone.now().date() - timedelta(days=7)

            # Get all stores across all branches
            company_stores = Store.objects.filter(company=company)
            store_ids = company_stores.values_list('id', flat=True)

            # Current period revenue (30 days)
            current_revenue = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date__gte=thirty_days_ago,
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                total_revenue=Sum('total_amount'),
                total_sales=Count('id'),
                avg_sale=Avg('total_amount')
            )

            # Previous period revenue (30-60 days ago)
            previous_revenue = Sale.objects.filter(
                store_id__in=store_ids,
                created_at__date__range=[sixty_days_ago, thirty_days_ago],
                is_voided=False,
                status__in=['COMPLETED', 'PAID']
            ).aggregate(
                total_revenue=Sum('total_amount'),
                total_sales=Count('id'),
                avg_sale=Avg('total_amount')
            )

            # Calculate growth rates
            current_total = float(current_revenue['total_revenue'] or 0)
            previous_total = float(previous_revenue['total_revenue'] or 0)

            revenue_growth = 0
            if previous_total > 0:
                revenue_growth = round(((current_total - previous_total) / previous_total) * 100, 1)

            # Sales growth
            current_sales = current_revenue['total_sales'] or 0
            previous_sales = previous_revenue['total_sales'] or 0

            sales_growth = 0
            if previous_sales > 0:
                sales_growth = round(((current_sales - previous_sales) / previous_sales) * 100, 1)

            # Weekly revenue trend (last 7 days)
            weekly_trend = []
            for i in range(7):
                date = timezone.now().date() - timedelta(days=6 - i)
                daily_revenue = Sale.objects.filter(
                    store_id__in=store_ids,
                    created_at__date=date,
                    is_voided=False,
                    status__in=['COMPLETED', 'PAID']
                ).aggregate(total=Sum('total_amount'))['total'] or 0

                weekly_trend.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'revenue': float(daily_revenue)
                })

            return {
                'revenue_analytics': {
                    'current_period': {
                        'total_revenue': current_total,
                        'total_sales': current_sales,
                        'avg_sale': float(current_revenue['avg_sale'] or 0),
                    },
                    'previous_period': {
                        'total_revenue': previous_total,
                        'total_sales': previous_sales,
                        'avg_sale': float(previous_revenue['avg_sale'] or 0),
                    },
                    'growth_rates': {
                        'revenue_growth': revenue_growth,
                        'sales_growth': sales_growth,
                    },
                    'weekly_trend': weekly_trend,
                }
            }

        except Exception as e:
            logger.error(f"Error calculating revenue analytics: {e}")
            return {
                'revenue_analytics': {
                    'current_period': {'total_revenue': 0, 'total_sales': 0, 'avg_sale': 0},
                    'previous_period': {'total_revenue': 0, 'total_sales': 0, 'avg_sale': 0},
                    'growth_rates': {'revenue_growth': 0, 'sales_growth': 0},
                    'weekly_trend': [],
                }
            }

    def _get_operational_metrics(self, company):
        """Get operational metrics across the company."""
        try:
            company_stores = Store.objects.filter(company=company)

            # Inventory metrics
            total_products = Stock.objects.filter(
                store__in=company_stores
            ).values('product').distinct().count()

            low_stock_items = Stock.objects.filter(
                store__in=company_stores,
                quantity__lte=F('low_stock_threshold')
            ).count()

            out_of_stock_items = Stock.objects.filter(
                store__in=company_stores,
                quantity=0
            ).count()

            # Device/System metrics
            total_devices = company_stores.aggregate(
                device_count=Count('devices')
            )['device_count'] or 0

            return {
                'operational_metrics': {
                    'inventory': {
                        'total_products': total_products,
                        'low_stock_items': low_stock_items,
                        'out_of_stock_items': out_of_stock_items,
                        'stock_health_percentage': round(
                            ((total_products - low_stock_items - out_of_stock_items) / max(total_products, 1)) * 100, 1
                        ),
                    },
                    'systems': {
                        'total_devices': total_devices,
                        'efris_enabled_stores': company_stores.filter(efris_enabled=True).count(),
                    }
                }
            }

        except Exception as e:
            logger.error(f"Error calculating operational metrics: {e}")
            return {
                'operational_metrics': {
                    'inventory': {
                        'total_products': 0,
                        'low_stock_items': 0,
                        'out_of_stock_items': 0,
                        'stock_health_percentage': 100,
                    },
                    'systems': {
                        'total_devices': 0,
                        'efris_enabled_stores': 0,
                    }
                }
            }

    def _calculate_branch_performance_score(self, analytics):
        """Calculate a performance score for a branch based on its analytics."""
        try:
            revenue = analytics.get('total_revenue_30d', 0)
            sales_count = analytics.get('total_sales_30d', 0)
            avg_sale = analytics.get('avg_sale_amount', 0)

            # Base score calculation (max 100)
            performance_score = 0

            if sales_count > 0:
                # Sales volume component (40% weight)
                sales_score = min(40, (sales_count / 50) * 40)  # 50 sales = full 40 points

                # Revenue component (40% weight)
                revenue_score = min(40, (revenue / 500000) * 40)  # 500k = full 40 points

                # Average sale component (20% weight)
                avg_score = min(20, (avg_sale / 25000) * 20)  # 25k avg = full 20 points

                performance_score = sales_score + revenue_score + avg_score

            return round(min(100, performance_score), 1)

        except Exception:
            return 0

    def _get_recent_activities_enhanced(self, company):
        """Get enhanced recent activities with more context."""
        activities = []

        try:
            # Company-level activities
            activities.extend([
                {
                    'description': f"Company {company.name} profile updated",
                    'created_at': company.updated_at,
                    'type': 'company_update',
                    'icon': 'bi-building',
                },
                {
                    'description': f"Company {company.name} created",
                    'created_at': company.created_at,
                    'type': 'company_created',
                    'icon': 'bi-plus-circle',
                }
            ])

            # Recent branch activities
            recent_branches = Store.objects.filter(
                company=company,
                created_at__gte=timezone.now() - timedelta(days=30)
            ).order_by('-created_at')[:3]

            for branch in recent_branches:
                activities.append({
                    'description': f"New branch '{branch.name}' added",
                    'created_at': branch.created_at,
                    'type': 'branch_created',
                    'icon': 'bi-diagram-3',
                })

            # Recent employee activities
            recent_employees = CustomUser.objects.filter(
                company=company,
                is_hidden=False,
                date_joined__gte=timezone.now() - timedelta(days=30)
            ).order_by('-date_joined')[:3]

            for employee in recent_employees:
                activities.append({
                    'description': f"New employee {employee.get_full_name() or employee.username} joined",
                    'created_at': employee.date_joined,
                    'type': 'employee_joined',
                    'icon': 'bi-person-plus',
                })

        except Exception as e:
            logger.error(f"Error fetching enhanced activities for company {company}: {e}")

        # Sort by most recent and limit to 10
        activities.sort(key=lambda x: x['created_at'], reverse=True)
        return activities[:10]


class CompanyDetailMixin:
    """
    Enhanced mixin to provide company detail context for other views.
    """

    def get_company_context(self, company):
        """
        Get enhanced company context data with analytics.
        """
        context = {}

        # Basic counts with analytics
        try:
            branches = Store.objects.filter(company=company)
            context['branches_count'] = branches.count()
            context['active_branches_count'] = branches.filter(is_active=True).count()

            # Store counts across branches
            all_stores = Store.objects.filter(company=company)
            context['stores_count'] = all_stores.count()
            context['active_stores_count'] = all_stores.filter(is_active=True).count()

        except Exception:
            context.update({
                'branches_count': 0,
                'active_branches_count': 0,
                'stores_count': 0,
                'active_stores_count': 0,
            })

        try:
            # Employee counts with role breakdown
            employees = CustomUser.objects.filter(company=company, is_hidden=False)
            context['employees_count'] = employees.count()
            context['active_employees_count'] = employees.filter(is_active=True).count()
            context['admin_employees_count'] = employees.filter(
                company_admin=True, is_active=True
            ).count()
        except Exception:
            context.update({
                'employees_count': 0,
                'active_employees_count': 0,
                'admin_employees_count': 0,
            })

        # Storage usage
        if company.plan and company.plan.max_storage_gb > 0:
            storage_percentage = (company.storage_used_mb / (company.plan.max_storage_gb * 1024)) * 100
            context['storage_usage'] = min(round(storage_percentage, 1), 100)
        else:
            context['storage_usage'] = 0

        # Days until expiry
        today = timezone.now().date()
        if company.is_trial and company.trial_ends_at:
            days_until_expiry = (company.trial_ends_at - today).days
        elif company.subscription_ends_at:
            days_until_expiry = (company.subscription_ends_at - today).days
        else:
            days_until_expiry = 0

        context['days_until_expiry'] = max(days_until_expiry, 0)

        return context

class CompanyFormMixin:
    """Mixin for company form views with formset support."""

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        self.object = getattr(self, 'object', None)  # For CreateView (object=None)

        # Branch formset (only if CompanyBranchFormSet exists)
        if CompanyBranchFormSet:
            context['branch_formset'] = CompanyBranchFormSet(
                self.request.POST or None,
                self.request.FILES or None,
                instance=self.object,
                prefix='branch'
            )
        else:
            context['branch_formset'] = None

        # Remove the incorrect employee form - handle employees separately
        # Employee management should be done through a separate view/form

        return context

    def form_valid(self, form):
        context = self.get_context_data()
        branch_formset = context.get('branch_formset')

        # Validate branch formset if it exists
        formsets_valid = True
        if branch_formset:
            formsets_valid = branch_formset.is_valid()

        if formsets_valid and form.is_valid():
            with transaction.atomic():
                # Save the main company form
                self.object = form.save(commit=False)

                # Generate schema name if missing (for new companies)
                if not self.object.schema_name:
                    self.object.schema_name = self.generate_unique_schema_name()

                self.object.save()
                form.save_m2m()

                # Save branch formset if it exists
                if branch_formset:
                    branch_formset.instance = self.object
                    branch_formset.save()

                messages.success(self.request, _('Company saved successfully.'))
                return super().form_valid(form)

        # Handle formset errors
        if branch_formset and not branch_formset.is_valid():
            for f in branch_formset.forms:
                for field, errors in f.errors.items():
                    for error in errors:
                        messages.error(self.request, f"Branch {field}: {error}")
            for error in branch_formset.non_form_errors():
                messages.error(self.request, f"Branch formset: {error}")

        return self.form_invalid(form)

    def generate_unique_schema_name(self):
        """Generate a unique schema name for the company."""
        if hasattr(self.object, 'generate_unique_schema_name'):
            return self.object.generate_unique_schema_name()

        # Fallback method if model doesn't have the method
        import uuid
        base_name = f"company_{str(uuid.uuid4())[:8]}"
        return base_name

class CompanyCreateView(LoginRequiredMixin, PermissionRequiredMixin, CompanyFormMixin, CreateView):
    model = Company
    form_class = CompanyForm
    template_name = 'company/company_form.html'
    permission_required = 'company.add_company'
    raise_exception = True

    extra_context = {
        'form_title': _('Create Company'),
        'submit_text': _('Create Company')
    }

    def get_success_url(self):
        return self.object.get_absolute_url()


class CompanyUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    """Enhanced company update view with proper access control."""
    model = Company
    form_class = CompanyForm
    template_name = 'company/company_forrm.html'
    permission_required = 'company.change_company'
    slug_field = 'company_id'
    slug_url_kwarg = 'company_id'
    context_object_name = 'company'

    def get_object(self, queryset=None):
        """Get object with access control."""
        if queryset is None:
            queryset = self.get_queryset()

        company_id = self.kwargs.get(self.slug_url_kwarg)
        try:
            obj = queryset.get(**{self.slug_field: company_id})

            # Check access permissions
            if not self.request.user.is_saas_admin:
                user_company = getattr(self.request.user, 'company', None)
                if not user_company or obj.company_id != user_company.company_id:
                    raise Http404("Company not found")

        except Company.DoesNotExist:
            raise Http404("Company not found")
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        company = self.object

        context.update({
            'form_title': _('Update Company'),
            'submit_text': _('Save Changes'),
            'is_update': True,
            'company': company,
            'company_id': company.company_id,
        })

        # Add company statistics
        if company:
            try:
                total_branches = Store.objects.filter(company=company).count()
                active_branches = Store.objects.filter(company=company, is_active=True).count()
                total_employees = CustomUser.objects.filter(company=company, is_hidden=False).count()
                active_employees = CustomUser.objects.filter(
                    company=company, is_active=True, is_hidden=False
                ).count()

                # Get storage usage percentage
                storage_percentage = 0
                if company.plan and company.plan.max_storage_gb > 0:
                    storage_percentage = min(
                        round((company.storage_used_mb / (company.plan.max_storage_gb * 1024)) * 100, 1),
                        100
                    )

                context.update({
                    'total_branches': total_branches,
                    'active_branches': active_branches,
                    'total_employees': total_employees,
                    'active_employees': active_employees,
                    'storage_usage_percentage': storage_percentage,
                    'days_until_expiry': max(company.days_until_expiry, 0),
                })

                logger.debug(
                    f"Company stats for {company.company_id}: "
                    f"branches={total_branches}/{active_branches}, "
                    f"employees={total_employees}/{active_employees}"
                )
            except Exception as e:
                logger.error(f"Error building context for company {company}: {e}", exc_info=True)
                context.update({
                    'total_branches': 0,
                    'active_branches': 0,
                    'total_employees': 0,
                    'active_employees': 0,
                    'storage_usage_percentage': 0,
                    'days_until_expiry': 0,
                })

        # Available plans for dropdown
        context['available_plans'] = SubscriptionPlan.objects.filter(is_active=True).order_by('sort_order')

        # Currency choices
        context['currency_choices'] = Company.CURRENCY_CHOICES

        # Status choices
        context['status_choices'] = Company.STATUS_CHOICES

        # EFRIS mode choices
        context['efris_mode_choices'] = Company.EFRIS_MODE_CHOICES

        return context

    def form_valid(self, form):
        """Override to add success message and proper save."""
        try:
            # Save the form
            self.object = form.save(commit=False)

            # Ensure schema_name exists (should already exist for updates)
            if not self.object.schema_name:
                logger.warning(f"Company {self.object.company_id} missing schema_name during update")
                # Schema name should already exist, but just in case
                from django.utils.text import slugify
                import uuid
                self.object.schema_name = f"tenant_{slugify(self.object.name)[:20]}_{str(uuid.uuid4())[:8]}"

            # Update status if needed
            self.object.check_and_update_access_status()

            # Save the object
            self.object.save()

            # Save many-to-many relationships
            form.save_m2m()

            messages.success(
                self.request,
                _('Company "%(name)s" updated successfully.') % {'name': self.object.display_name}
            )

            logger.info(
                f"Company {self.object.company_id} updated successfully "
                f"by user {self.request.user}"
            )

            return redirect(self.get_success_url())

        except Exception as e:
            logger.error(f"Error saving company update: {e}", exc_info=True)
            messages.error(
                self.request,
                _('Error updating company: %(error)s') % {'error': str(e)}
            )
            return self.form_invalid(form)

    def form_invalid(self, form):
        """Handle invalid form submission."""
        logger.warning(
            f"Invalid company update form submitted by user={self.request.user} "
            f"for company_id={self.kwargs.get('company_id')}. "
            f"Errors={form.errors.as_json()}"
        )

        # Add error messages for each field
        for field, errors in form.errors.items():
            for error in errors:
                if field == '__all__':
                    messages.error(self.request, error)
                else:
                    field_label = form.fields[field].label if field in form.fields else field
                    messages.error(self.request, f"{field_label}: {error}")

        return super().form_invalid(form)

    def get_success_url(self):
        """Redirect to company detail page after successful update."""
        return reverse('companies:company_detail', kwargs={'company_id': self.object.company_id})


@method_decorator(csrf_exempt, name='dispatch')
class CompanyAutoSaveView(LoginRequiredMixin, View):
    """Auto-save company form data."""

    def post(self, request, *args, **kwargs):
        try:
            company_id = request.POST.get('company_id', '').strip()

            # Determine if we're updating or creating
            instance = None
            if company_id and company_id != 'None' and company_id != '':
                try:
                    instance = Company.objects.get(company_id=company_id)

                    # Check access permissions for updates
                    if not request.user.is_saas_admin:
                        user_company = getattr(request.user, 'company', None)
                        if not user_company or instance.company_id != user_company.company_id:
                            return JsonResponse({
                                'success': False,
                                'message': 'Permission denied'
                            }, status=403)

                except Company.DoesNotExist:
                    instance = None

            # Create form with or without instance
            form = CompanyForm(request.POST, request.FILES, instance=instance)

            # For auto-save, we're more lenient with validation
            try:
                cleaned_data = {}

                # Only validate and save non-empty fields
                for field_name, field in form.fields.items():
                    value = request.POST.get(field_name, '').strip()
                    if value:
                        try:
                            clean_method = getattr(form, f'clean_{field_name}', None)
                            if clean_method:
                                cleaned_data[field_name] = clean_method()
                            else:
                                cleaned_data[field_name] = field.clean(value)
                        except Exception as e:
                            continue

                if cleaned_data:
                    with transaction.atomic():
                        if instance:
                            # Update existing company with cleaned data
                            for field, value in cleaned_data.items():
                                if hasattr(instance, field):
                                    setattr(instance, field, value)
                            instance.save()
                            company_id = instance.company_id
                        else:
                            # For new companies, we need at least a name to proceed
                            if 'name' in cleaned_data:
                                company = Company()
                                for field, value in cleaned_data.items():
                                    if hasattr(company, field):
                                        setattr(company, field, value)

                                # Generate schema_name if not provided
                                if not hasattr(company, 'schema_name') or not company.schema_name:
                                    import uuid
                                    company.schema_name = f"temp_{str(uuid.uuid4())[:8]}"

                                company.save()
                                company_id = company.company_id
                            else:
                                return JsonResponse({
                                    'success': False,
                                    'message': 'Company name is required for auto-save'
                                }, status=400)

                        return JsonResponse({
                            'success': True,
                            'company_id': company_id,
                            'message': 'Draft saved successfully',
                            'saved_fields': list(cleaned_data.keys())
                        })
                else:
                    return JsonResponse({
                        'success': False,
                        'message': 'No valid data to save'
                    }, status=400)

            except Exception as e:
                logger.error(f"Auto-save processing error: {str(e)}", exc_info=True)
                return JsonResponse({
                    'success': False,
                    'message': 'Failed to process form data',
                    'error': str(e)
                }, status=500)

        except Exception as e:
            logger.error(f"Auto-save exception: {str(e)}", exc_info=True)
            return JsonResponse({
                'success': False,
                'message': 'Server error during auto-save',
                'error': str(e)
            }, status=500)


class CompanyDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    """Delete company with confirmation and access control."""
    model = Company
    template_name = 'company/company_confirm_delete.html'
    permission_required = 'company.delete_company'
    success_url = reverse_lazy('companies:company_list')
    slug_field = 'company_id'
    slug_url_kwarg = 'company_id'

    def get_object(self, queryset=None):
        """Get object with access control."""
        if queryset is None:
            queryset = self.get_queryset()

        company_id = self.kwargs.get(self.slug_url_kwarg)
        try:
            obj = queryset.get(**{self.slug_field: company_id})

            # Only SaaS admin can delete companies
            if not self.request.user.is_saas_admin:
                raise Http404("Company not found")

        except Company.DoesNotExist:
            raise Http404("Company not found")
        return obj

    def delete(self, request, *args, **kwargs):
        company_name = self.get_object().name
        result = super().delete(request, *args, **kwargs)
        messages.success(request, _('Company "%s" deleted successfully.') % company_name)
        return result




class EmployeeListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    model = CustomUser
    template_name = 'company/employee_list.html'
    context_object_name = 'employees'
    paginate_by = 25
    permission_required = 'accounts.view_customuser'

    def get_queryset(self):
        company_id = self.kwargs.get('company_id')
        self.company = get_object_or_404(Company, company_id=company_id)

        # Check access permissions
        if not self.request.user.is_saas_admin:
            user_company = getattr(self.request.user, 'company', None)
            if not user_company or self.company.company_id != user_company.company_id:
                raise Http404("Company not found")

        # Filter by company and exclude hidden/saas admin users
        queryset = CustomUser.objects.filter(
            company=self.company,
            is_hidden=False
        ).select_related('company').order_by('first_name', 'last_name')

        # Add search functionality
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(first_name__icontains=search_query) |
                Q(last_name__icontains=search_query) |
                Q(email__icontains=search_query) |
                Q(username__icontains=search_query)
            )

        # Status filter
        status = self.request.GET.get('status')
        if status == 'active':
            queryset = queryset.filter(is_active=True)
        elif status == 'inactive':
            queryset = queryset.filter(is_active=False)

        # Role filter
        role = self.request.GET.get('role')
        if role == 'admin':
            queryset = queryset.filter(company_admin=True)
        elif role == 'employee':
            queryset = queryset.filter(company_admin=False)

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['company'] = self.company
        context['total_employees'] = self.get_queryset().count()
        return context


class EmployeeDetailView(LoginRequiredMixin, PermissionRequiredMixin, DetailView):
    model = CustomUser
    template_name = 'company/employee_detail.html'
    context_object_name = 'employee'
    permission_required = 'accounts.view_customuser'

    def get_queryset(self):
        company_id = self.kwargs.get('company_id')
        self.company = get_object_or_404(Company, company_id=company_id)

        # Check access permissions
        if not self.request.user.is_saas_admin:
            user_company = getattr(self.request.user, 'company', None)
            if not user_company or self.company.company_id != user_company.company_id:
                raise Http404("Company not found")

        return CustomUser.objects.filter(
            company=self.company,
            is_hidden=False
        ).select_related('company')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['company'] = self.company
        context['is_company_admin'] = self.object.company_admin
        return context

class EmployeeCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = CustomUser
    template_name = 'company/employee_form.html'
    permission_required = 'accounts.add_customuser'
    fields = ['username', 'email', 'first_name', 'last_name', 'phone_number',
              'primary_role', 'company_admin', 'is_active']

    def dispatch(self, request, *args, **kwargs):
        company_id = self.kwargs.get('company_id')
        self.company = get_object_or_404(Company, company_id=company_id)

        # Check access permissions
        if not request.user.is_saas_admin:
            user_company = getattr(request.user, 'company', None)
            if not user_company or self.company.company_id != user_company.company_id:
                raise Http404("Company not found")

        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        return CompanyUserForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.company
        return kwargs

    def form_valid(self, form):
        # Create the user but don't save yet
        user = form.save(commit=False)
        user.company = self.company

        # Generate a temporary password
        temp_password = generate_random_password()
        user.set_password(temp_password)

        user.save()

        messages.success(
            self.request,
            f'Employee {user.get_full_name() or user.username} created successfully. '
            f'Temporary password has been generated.'
        )
        return super().form_valid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['company'] = self.company
        context['company_id'] = self.company.company_id
        context['form_title'] = 'Add Employee'
        return context

    def get_success_url(self):
        return reverse_lazy(
            'companies:employee_list',
            kwargs={'company_id': self.kwargs.get('company_id')}
        )


class EmployeeUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = CustomUser
    template_name = 'company/employee_form.html'
    permission_required = 'accounts.change_customuser'
    fields = ['username', 'email', 'first_name', 'last_name', 'phone_number',
              'primary_role', 'company_admin', 'is_active']

    def dispatch(self, request, *args, **kwargs):
        company_id = self.kwargs.get('company_id')
        self.company = get_object_or_404(Company, company_id=company_id)

        # Check access permissions
        if not request.user.is_saas_admin:
            user_company = getattr(request.user, 'company', None)
            if not user_company or self.company.company_id != user_company.company_id:
                raise Http404("Company not found")

        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        return CompanyUserForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['company'] = self.company
        return kwargs

    def get_queryset(self):
        return CustomUser.objects.filter(
            company=self.company,
            is_hidden=False,
            is_saas_admin=False
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['company'] = self.company
        context['company_id'] = self.company.company_id
        context['form_title'] = 'Update Employee'
        return context

    def get_success_url(self):
        return reverse_lazy('companies:employee_detail', kwargs={
            'company_id': self.company.company_id,
            'pk': self.object.pk
        })




class EmployeeDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    model = CustomUser
    template_name = 'company/employee_confirm_delete.html'
    permission_required = 'accounts.delete_customuser'

    def dispatch(self, request, *args, **kwargs):
        company_id = self.kwargs.get('company_id')
        self.company = get_object_or_404(Company, company_id=company_id)

        # Check access permissions
        if not request.user.is_saas_admin:
            user_company = getattr(request.user, 'company', None)
            if not user_company or self.company.company_id != user_company.company_id:
                raise Http404("Company not found")

        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        return CustomUser.objects.filter(
            company=self.company,
            is_hidden=False,
            is_saas_admin=False
        )

    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()

        # Instead of deleting, deactivate the user
        self.object.is_active = False
        self.object.save()

        messages.success(
            request,
            f'Employee {self.object.get_full_name() or self.object.username} has been deactivated.'
        )
        return redirect(self.get_success_url())

    def get_success_url(self):
        return reverse_lazy('companies:employee_list', kwargs={
            'company_id': self.company.company_id
        })


class DomainListView(LoginRequiredMixin, PermissionRequiredMixin, ListView):
    """List domains with proper tenant filtering."""
    model = Domain
    template_name = 'company/domain_list.html'
    context_object_name = 'domains'
    paginate_by = 25
    permission_required = 'company.view_domain'

    def get_queryset(self):
        queryset = Domain.objects.select_related('tenant')

        if not self.request.user.is_saas_admin:
            # Non-SaaS admin users can only see their company's domains
            user_company = getattr(self.request.user, 'company', None)
            if user_company:
                queryset = queryset.filter(tenant=user_company)
            else:
                queryset = queryset.none()

        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(domain__icontains=search_query) |
                Q(tenant__name__icontains=search_query)
            )

        is_primary = self.request.GET.get('is_primary')
        if is_primary:
            queryset = queryset.filter(is_primary=is_primary.lower() == 'true')

        return queryset.order_by('domain')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = SearchForm(self.request.GET)
        context['bulk_form'] = BulkActionForm()
        context['is_saas_admin'] = self.request.user.is_saas_admin

        # Current filters
        context['current_filters'] = {
            'q': self.request.GET.get('q', ''),
            'tenant': self.request.GET.get('tenant', ''),
            'is_primary': self.request.GET.get('is_primary', ''),
        }

        return context

    def post(self, request, *args, **kwargs):
        """Handle bulk actions."""
        bulk_form = BulkActionForm(request.POST)
        if bulk_form.is_valid():
            action = bulk_form.cleaned_data['action']
            selected_items = json.loads(bulk_form.cleaned_data['selected_items'])

            if not selected_items:
                messages.warning(request, _('No items selected.'))
                return redirect('companies:domain_list')

            # Filter domains based on user permissions
            domains = Domain.objects.filter(id__in=selected_items)
            if not request.user.is_saas_admin:
                user_company = getattr(request.user, 'company', None)
                if user_company:
                    domains = domains.filter(tenant=user_company)
                else:
                    domains = domains.none()

            if action == 'set_primary':
                tenants = domains.values_list('tenant_id', flat=True).distinct()
                for tenant_id in tenants:
                    Domain.objects.filter(tenant_id=tenant_id).update(is_primary=False)

                updated = domains.update(is_primary=True)
                messages.success(request, _('Set %d domains as primary.') % updated)

            elif action == 'delete':
                count = domains.count()
                domains.delete()
                messages.success(request, _('Successfully deleted %d domains.') % count)

        return redirect('companies:domain_list')


class DomainCreateView(LoginRequiredMixin, PermissionRequiredMixin, CreateView):
    model = Domain
    form_class = DomainForm
    template_name = 'company/domain_form.html'
    permission_required = 'company.add_domain'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def form_valid(self, form):
        messages.success(self.request, _('Domain created successfully.'))
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('companies:domain_list')


class DomainUpdateView(LoginRequiredMixin, PermissionRequiredMixin, UpdateView):
    model = Domain
    form_class = DomainForm
    template_name = 'company/domain_form.html'
    permission_required = 'company.change_domain'

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.request.user.is_saas_admin:
            user_company = getattr(self.request.user, 'company', None)
            if user_company:
                qs = qs.filter(tenant=user_company)
            else:
                qs = qs.none()
        return qs

    def form_valid(self, form):
        messages.success(self.request, _('Domain updated successfully.'))
        return super().form_valid(form)

    def get_success_url(self):
        return reverse_lazy('companies:domain_list')


class DomainDeleteView(LoginRequiredMixin, PermissionRequiredMixin, DeleteView):
    """Delete domain with proper access control."""
    model = Domain
    template_name = 'company/domain_confirm_delete.html'
    permission_required = 'company.delete_domain'

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.request.user.is_saas_admin:
            user_company = getattr(self.request.user, 'company', None)
            if user_company:
                qs = qs.filter(tenant=user_company)
            else:
                qs = qs.none()
        return qs

    def delete(self, request, *args, **kwargs):
        domain_name = self.get_object().domain
        result = super().delete(request, *args, **kwargs)
        messages.success(request, _('Domain "%s" deleted successfully.') % domain_name)
        return result

    def get_success_url(self):
        return reverse_lazy('companies:domain_list')


class CheckSchemaNameView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Check if schema name is available."""
    permission_required = 'company.view_company'

    def get(self, request, *args, **kwargs):
        schema_name = request.GET.get('schema_name')
        exclude_id = request.GET.get('exclude_id')

        if not schema_name:
            return JsonResponse({'valid': False, 'message': _('Schema name is required.')})

        queryset = Company.objects.filter(schema_name__iexact=schema_name)
        if exclude_id:
            queryset = queryset.exclude(company_id=exclude_id)

        if queryset.exists():
            return JsonResponse({
                'valid': False,
                'message': _('This schema name is already in use.')
            })

        return JsonResponse({'valid': True})


class ExportCompaniesView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Export companies with proper access control."""
    permission_required = 'company.view_company'

    def get(self, request, *args, **kwargs):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="companies.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Company ID', 'Name', 'Trading Name', 'TIN', 'BRN', 'Email', 'Phone',
            'Status', 'Is Verified', 'EFRIS Enabled', 'Plan', 'Created At'
        ])

        # Apply access control
        if request.user.is_saas_admin:
            companies = Company.objects.all()
        else:
            user_company = getattr(request.user, 'company', None)
            companies = Company.objects.filter(
                company_id=user_company.company_id) if user_company else Company.objects.none()

        for c in companies:
            writer.writerow([
                c.company_id,
                c.name,
                c.trading_name or '',
                c.tin or '',
                c.brn or '',
                c.email or '',
                c.phone or '',
                c.get_status_display(),
                'Yes' if c.is_verified else 'No',
                'Yes' if c.efris_enabled else 'No',
                c.plan.display_name if c.plan else 'No Plan',
                c.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        return response




class ExportEmployeesView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Export employees with proper access control."""
    permission_required = 'accounts.view_customuser'

    def get(self, request, *args, **kwargs):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="employees.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Username', 'Email', 'First Name', 'Last Name', 'Phone', 'User Type',
            'Is Active', 'Is Admin', 'Date Joined', 'Last Login', 'Company'
        ])

        # Apply access control
        if request.user.is_saas_admin:
            employees = CustomUser.objects.filter(is_hidden=False).select_related('company')
        else:
            user_company = getattr(request.user, 'company', None)
            if user_company:
                employees = CustomUser.objects.filter(
                    company=user_company,
                    is_hidden=False
                ).select_related('company')
            else:
                employees = CustomUser.objects.none()

        for emp in employees:
            writer.writerow([
                emp.username,
                emp.email,
                emp.first_name,
                emp.last_name,
                emp.phone_number or '',
                emp.display_role,
                'Yes' if emp.is_active else 'No',
                'Yes' if emp.company_admin else 'No',
                emp.date_joined.strftime('%Y-%m-%d %H:%M:%S'),
                emp.last_login.strftime('%Y-%m-%d %H:%M:%S') if emp.last_login else 'Never',
                emp.company.name if emp.company else '',
            ])

        return response


class ExportDomainsView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """Export domains with proper access control."""
    permission_required = 'company.view_domain'

    def get(self, request, *args, **kwargs):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="domains.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Domain', 'Company', 'Is Primary', 'SSL Enabled', 'Created At'
        ])

        # Apply access control
        if request.user.is_saas_admin:
            domains = Domain.objects.all().select_related('tenant')
        else:
            user_company = getattr(request.user, 'company', None)
            domains = Domain.objects.filter(tenant=user_company).select_related(
                'tenant') if user_company else Domain.objects.none()

        for d in domains:
            writer.writerow([
                d.domain,
                d.tenant.name if d.tenant else '',
                'Yes' if d.is_primary else 'No',
                'Yes' if d.ssl_enabled else 'No',
                d.created_at.strftime('%Y-%m-%d %H:%M:%S'),
            ])
        return response


class CompanyStatsAPIView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = 'company.view_company'

    def get(self, request, *args, **kwargs):
        days = int(request.GET.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)

        # Apply access control
        if request.user.is_saas_admin:
            companies = Company.objects.all()
            total = companies.count()
            verified = companies.filter(is_verified=True).count()
            efris_enabled = companies.filter(efris_enabled=True).count()
            recent = companies.filter(created_at__gte=start_date).count()
            active = companies.filter(status='ACTIVE').count()
            trial = companies.filter(status='TRIAL').count()
            expired = companies.filter(status='EXPIRED').count()

            # Calculate growth rate
            previous_period_start = start_date - timedelta(days=days)
            previous_count = companies.filter(
                created_at__range=[previous_period_start, start_date]
            ).count()
            growth_rate = ((recent - previous_count) / max(previous_count, 1)) * 100 if previous_count else 0
        else:
            # Single company view
            company = getattr(request.user, 'company', None)
            if not company:
                return JsonResponse({'error': 'No company assigned.'}, status=400)

            total = 1
            verified = 1 if company.is_verified else 0
            efris_enabled = 1 if company.efris_enabled else 0
            recent = 1 if company.created_at >= start_date else 0
            active = 1 if company.status == 'ACTIVE' else 0
            trial = 1 if company.status == 'TRIAL' else 0
            expired = 1 if company.status == 'EXPIRED' else 0
            growth_rate = 0

        return JsonResponse({
            'total_companies': total,
            'verified_companies': verified,
            'efris_enabled_companies': efris_enabled,
            'active_companies': active,
            'trial_companies': trial,
            'expired_companies': expired,
            'recent_companies': recent,
            'growth_rate': round(growth_rate, 2),
            'verification_rate': round((verified / max(total, 1) * 100), 2),
            'efris_adoption_rate': round((efris_enabled / max(total, 1) * 100), 2),
        })


class AdvancedSearchView(LoginRequiredMixin, PermissionRequiredMixin, TemplateView):
    template_name = 'company/advanced_search.html'
    permission_required = 'company.view_company'

    def perform_search(self):
        company = getattr(self.request.user, 'company', None)
        if not company:
            return Company.objects.none()

        queryset = Company.objects.filter(pk=company.pk).select_related('plan').prefetch_related('domains')

        # Apply optional filters (q, plan, status, domain, etc.) only if company matches
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(name__icontains=search_query) |
                Q(trading_name__icontains=search_query) |
                Q(tin__icontains=search_query) |
                Q(brn__icontains=search_query) |
                Q(email__icontains=search_query)
            )

        # Additional filters...
        plan = self.request.GET.get('plan')
        if plan:
            queryset = queryset.filter(plan__name__icontains=plan)

        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        domain = self.request.GET.get('domain')
        if domain:
            queryset = queryset.filter(domains__domain__icontains=domain)

        # Date range
        start_date = self.request.GET.get('start_date')
        end_date = self.request.GET.get('end_date')
        if start_date and end_date:
            queryset = queryset.filter(created_at__range=[start_date, end_date])

        # Admin presence
        has_admin = self.request.GET.get('has_admin')
        if has_admin == 'yes':
            queryset = queryset.filter(admin_users__isnull=False)
        elif has_admin == 'no':
            queryset = queryset.filter(admin_users__isnull=True)

        return queryset.distinct()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['companies'] = self.perform_search()
        return context



@login_required
def company_expired_view(request):
    """View for expired companies"""
    company = request.user.company

    # Force refresh company status
    company.force_status_refresh()

    # Calculate days expired and determine expiration type
    expiration_date = None
    expiration_type = None

    if company.is_trial and company.trial_ends_at:
        expiration_date = company.trial_ends_at
        expiration_type = 'trial'
    elif company.subscription_ends_at:
        expiration_date = company.subscription_ends_at
        expiration_type = 'subscription'

    # Calculate days expired
    if expiration_date:
        days_expired = (timezone.now().date() - expiration_date).days
    else:
        days_expired = 0

    # Determine if we should show warning about data retention
    show_data_warning = days_expired >= 30  # Show warning after 30 days

    context = {
        'company': company,
        'plan': company.plan,
        'days_expired': max(0, days_expired),
        'expiration_type': expiration_type,
        'expiration_date': expiration_date,
        'show_data_warning': show_data_warning,
    }
    return render(request, 'company/expired.html', context)


@login_required
def company_suspended_view(request):
    """View for suspended companies"""
    company = request.user.company

    # Force refresh company status
    company.force_status_refresh()

    grace_days_left = 0
    if company.grace_period_ends_at:
        grace_days_left = max(0, (company.grace_period_ends_at - timezone.now().date()).days)

    context = {
        'company': company,
        'is_grace_period': company.is_in_grace_period,
        'grace_days_left': grace_days_left,
    }
    return render(request, 'company/suspended.html', context)


def company_deactivated_view(request):
    """View for manually deactivated companies"""
    return render(request, 'company/deactivated.html')


@login_required
def billing_view(request):
    """Billing and subscription management view"""
    company = request.user.company

    # Force refresh company status
    company.force_status_refresh()

    plans = SubscriptionPlan.objects.filter(is_active=True).order_by('sort_order', 'price')

    # FIXED: Use cached property and filter for active users
    context = {
        'company': company,
        'current_plan': company.plan,
        'available_plans': plans,
        'usage_stats': {
            'storage_used': company.storage_used_mb,
            'storage_percentage': company.storage_usage_percentage,
            'users_count': company.active_users_count,  # FIXED: Use cached property
            'branches_count': company.branches_count,
        }
    }
    return render(request, 'company/billing.html', context)


@login_required
@transaction.atomic
def upgrade_plan_view(request):
    """Plan upgrade view with transaction protection"""
    if request.method == 'POST':
        plan_id = request.POST.get('plan_id')
        billing_cycle = request.POST.get('billing_cycle', 'MONTHLY')

        try:
            plan = SubscriptionPlan.objects.get(id=plan_id, is_active=True)

            # Get company with lock to prevent concurrent modifications
            company = Company.objects.select_for_update().get(
                company_id=request.user.company.company_id
            )

            # Validate upgrade
            if company.plan and plan.price <= company.plan.price:
                messages.warning(
                    request,
                    'Please use the subscription management page for plan changes.'
                )
                return redirect('companies:subscription_dashboard')

            # Store old plan for logging
            old_plan = company.plan

            # Update company plan
            company.plan = plan

            if plan.name != 'FREE':
                # Calculate subscription period based on billing cycle
                duration_days = {
                    'MONTHLY': 30,
                    'QUARTERLY': 90,
                    'YEARLY': 365,
                }.get(billing_cycle, 30)

                company.is_trial = False
                company.subscription_starts_at = timezone.now().date()
                company.subscription_ends_at = company.subscription_starts_at + timedelta(days=duration_days)
                company.grace_period_ends_at = company.subscription_ends_at + timedelta(days=7)
                company.status = 'ACTIVE'
                company.is_active = True
                company.next_billing_date = company.subscription_ends_at

            # Save with status update
            company.save()

            # Clear all caches after upgrade
            company._clear_all_caches()

            # Reactivate users if they were deactivated
            if company.is_active:
                company.reactivate_all_users()

            messages.success(
                request,
                f'Successfully upgraded to {plan.display_name or plan.get_name_display()}!'
            )

            logger.info(
                f"Company {company.company_id} upgraded from "
                f"{old_plan.name if old_plan else 'None'} to {plan.name}"
            )

            return redirect('companies:billing')

        except SubscriptionPlan.DoesNotExist:
            messages.error(request, 'Invalid plan selected.')
            logger.error(f"Invalid plan selected: {plan_id}")

        except Company.DoesNotExist:
            messages.error(request, 'Company not found.')
            logger.error(f"Company not found for user {request.user.id}")

        except Exception as e:
            messages.error(request, 'An error occurred during the upgrade.')
            logger.error(f"Error upgrading plan: {e}", exc_info=True)

    return redirect('companies:billing')


@staff_member_required
@transaction.atomic
def admin_suspend_company(request, company_id):
    """Admin action to suspend a company"""
    if not getattr(request.user, 'is_saas_admin', False):
        return HttpResponseForbidden('Permission denied')

    if request.method == 'POST':
        # Get company with lock
        company = get_object_or_404(
            Company.objects.select_for_update(),
            company_id=company_id
        )

        reason = request.POST.get('reason', 'Suspended by administrator')

        # Suspend the company
        company.suspend_for_misbehavior(reason, suspended_by=request.user)

        # Clear all caches
        company._clear_all_caches()

        messages.success(request, f'Company {company.display_name} has been suspended.')
        logger.warning(
            f"Admin {request.user.username} suspended company {company_id}: {reason}"
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'success',
                'message': 'Company suspended',
                'company_id': company_id,
                'company_name': company.display_name
            })

        return redirect('companies:company_list')

    return HttpResponseForbidden()


@staff_member_required
@transaction.atomic
def admin_reactivate_company(request, company_id):
    """Admin action to reactivate a company"""
    if not getattr(request.user, 'is_saas_admin', False):
        return HttpResponseForbidden('Permission denied')

    if request.method == 'POST':
        # Get company with lock
        company = get_object_or_404(
            Company.objects.select_for_update(),
            company_id=company_id
        )

        reason = request.POST.get('reason', 'Reactivated by administrator')
        days = int(request.POST.get('days', 30))  # Default 30 days
        grace_days = int(request.POST.get('grace_days', 7))  # Default 7 days grace

        # Use the reallow_company method for full reactivation
        company.reallow_company(reason=reason, days=days, grace_days=grace_days)

        # Clear all caches
        company._clear_all_caches()

        # Force status refresh
        company.force_status_refresh()

        messages.success(
            request,
            f'Company {company.display_name} has been reactivated for {days} days.'
        )
        logger.info(
            f"Admin {request.user.username} reactivated company {company_id}: {reason}"
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'success',
                'message': 'Company reactivated',
                'company_id': company_id,
                'company_name': company.display_name,
                'subscription_ends_at': company.subscription_ends_at.isoformat() if company.subscription_ends_at else None
            })

        return redirect('companies:company_list')

    return HttpResponseForbidden()


@staff_member_required
def admin_extend_grace_period(request, company_id):
    """Admin action to extend grace period"""
    if not getattr(request.user, 'is_saas_admin', False):
        return HttpResponseForbidden('Permission denied')

    if request.method == 'POST':
        company = get_object_or_404(Company, company_id=company_id)
        days = int(request.POST.get('days', 7))

        company.extend_grace_period(days=days)

        messages.success(
            request,
            f'Extended grace period for {company.display_name} by {days} days.'
        )
        logger.info(
            f"Admin {request.user.username} extended grace period for "
            f"company {company_id} by {days} days"
        )

        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return JsonResponse({
                'status': 'success',
                'message': f'Grace period extended by {days} days',
                'grace_period_ends_at': company.grace_period_ends_at.isoformat() if company.grace_period_ends_at else None
            })

        return redirect('companies:company_list')

    return HttpResponseForbidden()


@staff_member_required
def company_analytics_view(request):
    """Analytics view for company status (SaaS admin only)"""
    if not getattr(request.user, 'is_saas_admin', False):
        return HttpResponseForbidden('Permission denied')

    # Get company statistics
    stats = Company.objects.aggregate(
        total=Count('company_id'),
        active=Count('company_id', filter=Q(status='ACTIVE')),
        trial=Count('company_id', filter=Q(status='TRIAL')),
        suspended=Count('company_id', filter=Q(status='SUSPENDED')),
        expired=Count('company_id', filter=Q(status='EXPIRED')),
        grace_period=Count('company_id', filter=Q(
            status='SUSPENDED',
            grace_period_ends_at__gte=timezone.now().date()
        ))
    )

    # Companies requiring attention
    today = timezone.now().date()

    expiring_soon = Company.objects.filter(
        is_active=True,
        status__in=['ACTIVE', 'TRIAL']
    ).filter(
        Q(trial_ends_at__lte=today + timedelta(days=7), is_trial=True) |
        Q(subscription_ends_at__lte=today + timedelta(days=7), is_trial=False)
    ).select_related('plan').order_by('trial_ends_at', 'subscription_ends_at')

    in_grace_period = Company.objects.filter(
        status='SUSPENDED',
        grace_period_ends_at__gte=today
    ).select_related('plan').order_by('grace_period_ends_at')

    recently_expired = Company.objects.filter(
        status='EXPIRED'
    ).select_related('plan').order_by('-subscription_ends_at', '-trial_ends_at')[:20]

    # Calculate additional metrics
    revenue_stats = {
        'total_companies': stats['total'],
        'paying_customers': stats['active'] + stats['suspended'],  # Companies with paid plans
        'trial_conversions': stats['active'],  # Companies that converted from trial
    }

    context = {
        'stats': stats,
        'revenue_stats': revenue_stats,
        'expiring_soon': expiring_soon[:10],
        'in_grace_period': in_grace_period,
        'recently_expired': recently_expired,
    }

    return render(request, 'admin/company_analytics.html', context)


@staff_member_required
def company_detail_admin(request, company_id):
    """Detailed view of a company for admin"""
    if not getattr(request.user, 'is_saas_admin', False):
        return HttpResponseForbidden('Permission denied')

    company = get_object_or_404(
        Company.objects.select_related('plan'),
        company_id=company_id
    )

    # Force refresh status
    company.force_status_refresh()

    # Get usage statistics
    usage_stats = {
        'users': {
            'current': company.active_users_count,
            'limit': company.plan.max_users if company.plan else 0,
            'percentage': (
                        company.active_users_count / company.plan.max_users * 100) if company.plan and company.plan.max_users > 0 else 0
        },
        'branches': {
            'current': company.branches_count,
            'limit': company.plan.max_branches if company.plan else 0,
            'percentage': (
                        company.branches_count / company.plan.max_branches * 100) if company.plan and company.plan.max_branches > 0 else 0
        },
        'storage': {
            'current': company.storage_used_mb,
            'limit': company.plan.max_storage_gb * 1024 if company.plan else 0,
            'percentage': company.storage_usage_percentage
        }
    }

    # Get restrictions
    restrictions = company.get_access_restrictions()

    context = {
        'company': company,
        'usage_stats': usage_stats,
        'restrictions': restrictions,
        'status_display': company.access_status_display,
    }

    return render(request, 'admin/company_detail.html', context)


# API endpoint for checking company status
@login_required
def api_company_status(request):
    """API endpoint to get current company status"""
    company = request.user.company

    # Update status
    status_changed = company.check_and_update_access_status()

    restrictions = company.get_access_restrictions()

    data = {
        'company_id': company.company_id,
        'status': company.status,
        'is_active': company.is_active,
        'has_active_access': company.has_active_access,
        'access_status_display': company.access_status_display,
        'days_until_expiry': company.days_until_expiry,
        'restrictions': restrictions,
        'status_changed': status_changed,
        'plan': {
            'name': company.plan.name if company.plan else None,
            'display_name': company.plan.display_name if company.plan else None,
        } if company.plan else None
    }

    return JsonResponse(data)
