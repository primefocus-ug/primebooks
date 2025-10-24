from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.db.models import Q, Sum, Count, Avg
from django.utils import timezone
from django.core.paginator import Paginator
from django.views.decorators.http import require_http_methods
from django.views.generic import ListView, DetailView, CreateView, UpdateView, DeleteView
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.urls import reverse_lazy
from decimal import Decimal
from datetime import timedelta, date

from .models import (
    Expense, ExpenseCategory, Vendor, Budget, RecurringExpense,
    PettyCash, PettyCashTransaction, EmployeeReimbursement,
    ReimbursementItem, ExpenseAttachment, ExpenseSplit
)
from .forms import (
    ExpenseForm, ExpenseCategoryForm, VendorForm, BudgetForm,
    RecurringExpenseForm, PettyCashForm, ReimbursementForm,
    ExpenseFilterForm, ExpenseApprovalForm
)
from .utils import (
    ExpenseAnalytics, ExpenseExporter, BudgetCalculator,
    TaxCalculator, get_expense_statistics
)


# ==================== Dashboard Views ====================

@login_required
def expense_dashboard(request):
    """Main expense dashboard"""
    store = request.user.stores.first() if hasattr(request.user, 'stores') else None

    # Date range
    today = timezone.now().date()
    start_of_month = today.replace(day=1)

    # Summary statistics
    expenses = Expense.objects.filter(
        store=store,
        expense_date__gte=start_of_month,
        status='PAID'
    )

    stats = {
        'total_expenses': expenses.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0'),
        'expense_count': expenses.count(),
        'pending_approvals': Expense.objects.filter(store=store, status='PENDING').count(),
        'overdue_count': Expense.objects.filter(
            store=store,
            due_date__lt=today,
            status__in=['APPROVED', 'PARTIALLY_PAID']
        ).count(),
    }

    # Recent expenses
    recent_expenses = Expense.objects.filter(store=store).order_by('-created_at')[:10]

    # Budget status
    active_budgets = Budget.objects.filter(
        store=store,
        start_date__lte=today,
        end_date__gte=today,
        is_active=True
    )

    # Category breakdown
    category_data = expenses.values('category__name').annotate(
        total=Sum('total_amount')
    ).order_by('-total')[:5]

    context = {
        'stats': stats,
        'recent_expenses': recent_expenses,
        'active_budgets': active_budgets,
        'category_data': list(category_data),
        'store': store,
    }

    return render(request, 'expenses/dashboard.html', context)


# ==================== Expense Views ====================

class ExpenseListView(LoginRequiredMixin, ListView):
    """List all expenses with filtering"""
    model = Expense
    template_name = 'expenses/expense_list.html'
    context_object_name = 'expenses'
    paginate_by = 25

    def get_queryset(self):
        queryset = Expense.objects.select_related(
            'category', 'vendor', 'store', 'created_by'
        ).order_by('-expense_date', '-created_at')

        # Filter by store
        if hasattr(self.request.user, 'stores'):
            store = self.request.user.stores.first()
            if store:
                queryset = queryset.filter(store=store)

        # Apply filters from GET parameters
        status = self.request.GET.get('status')
        if status:
            queryset = queryset.filter(status=status)

        category = self.request.GET.get('category')
        if category:
            queryset = queryset.filter(category_id=category)

        vendor = self.request.GET.get('vendor')
        if vendor:
            queryset = queryset.filter(vendor_id=vendor)

        start_date = self.request.GET.get('start_date')
        if start_date:
            queryset = queryset.filter(expense_date__gte=start_date)

        end_date = self.request.GET.get('end_date')
        if end_date:
            queryset = queryset.filter(expense_date__lte=end_date)

        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(expense_number__icontains=search) |
                Q(description__icontains=search) |
                Q(invoice_number__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['filter_form'] = ExpenseFilterForm(self.request.GET)
        context['categories'] = ExpenseCategory.objects.filter(is_active=True)
        context['vendors'] = Vendor.objects.filter(is_active=True)
        return context


class ExpenseDetailView(LoginRequiredMixin, DetailView):
    """View expense details"""
    model = Expense
    template_name = 'expenses/expense_detail.html'
    context_object_name = 'expense'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        expense = self.object

        # Get related data
        context['attachments'] = expense.attachments.all()
        context['splits'] = expense.splits.all() if expense.is_split else []
        context['approvals'] = expense.approvals.all().order_by('approval_level')
        context['audit_logs'] = expense.audit_logs.all().order_by('-timestamp')[:20]

        # Check if user can approve
        context['can_approve'] = self.request.user.has_perm('expenses.approve_expense')
        context['can_reject'] = self.request.user.has_perm('expenses.reject_expense')
        context['can_pay'] = self.request.user.has_perm('expenses.pay_expense')

        return context


@login_required
def create_expense(request):
    """Create new expense"""
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.created_by = request.user

            # Get store from user
            if hasattr(request.user, 'stores'):
                store = request.user.stores.first()
                if store:
                    expense.store = store

            expense.save()

            # Handle attachments
            attachments = request.FILES.getlist('attachments')
            for attachment in attachments:
                ExpenseAttachment.objects.create(
                    expense=expense,
                    file=attachment,
                    attachment_type=request.POST.get('attachment_type', 'RECEIPT'),
                    uploaded_by=request.user
                )

            messages.success(request, f'Expense {expense.expense_number} created successfully.')
            return redirect('expenses:expense_detail', pk=expense.pk)
    else:
        form = ExpenseForm()

    context = {
        'form': form,
        'categories': ExpenseCategory.objects.filter(is_active=True),
        'vendors': Vendor.objects.filter(is_active=True),
    }

    return render(request, 'expenses/expense_form.html', context)


@login_required
def update_expense(request, pk):
    """Update existing expense"""
    expense = get_object_or_404(Expense, pk=pk)

    # Check if user can edit
    if expense.status not in ['DRAFT', 'REJECTED']:
        messages.error(request, 'Only draft or rejected expenses can be edited.')
        return redirect('expenses:expense_detail', pk=pk)

    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, instance=expense)
        if form.is_valid():
            expense = form.save()

            # Track who modified
            expense._modified_by = request.user
            expense.save()

            messages.success(request, 'Expense updated successfully.')
            return redirect('expenses:expense_detail', pk=expense.pk)
    else:
        form = ExpenseForm(instance=expense)

    return render(request, 'expenses/expense_form.html', {
        'form': form,
        'expense': expense,
        'is_update': True
    })


@login_required
@permission_required('expenses.approve_expense', raise_exception=True)
def approve_expense(request, pk):
    """Approve an expense"""
    expense = get_object_or_404(Expense, pk=pk)

    if request.method == 'POST':
        form = ExpenseApprovalForm(request.POST)
        if form.is_valid():
            notes = form.cleaned_data.get('notes', '')

            try:
                expense.approve(approved_by=request.user, notes=notes)
                messages.success(request, f'Expense {expense.expense_number} approved successfully.')
            except Exception as e:
                messages.error(request, f'Error approving expense: {str(e)}')

            return redirect('expenses:expense_detail', pk=pk)
    else:
        form = ExpenseApprovalForm()

    return render(request, 'expenses/expense_approval.html', {
        'expense': expense,
        'form': form,
        'action': 'approve'
    })


@login_required
@permission_required('expenses.reject_expense', raise_exception=True)
def reject_expense(request, pk):
    """Reject an expense"""
    expense = get_object_or_404(Expense, pk=pk)

    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        if not reason:
            messages.error(request, 'Rejection reason is required.')
            return redirect('expenses:expense_detail', pk=pk)

        try:
            expense.reject(rejected_by=request.user, reason=reason)
            messages.success(request, f'Expense {expense.expense_number} rejected.')
        except Exception as e:
            messages.error(request, f'Error rejecting expense: {str(e)}')

        return redirect('expenses:expense_detail', pk=pk)

    return render(request, 'expenses/expense_approval.html', {
        'expense': expense,
        'action': 'reject'
    })


@login_required
@permission_required('expenses.pay_expense', raise_exception=True)
def mark_expense_paid(request, pk):
    """Mark expense as paid"""
    expense = get_object_or_404(Expense, pk=pk)

    if request.method == 'POST':
        payment_method = request.POST.get('payment_method')
        payment_reference = request.POST.get('payment_reference', '')
        payment_date = request.POST.get('payment_date')

        if not payment_method:
            messages.error(request, 'Payment method is required.')
            return redirect('expenses:expense_detail', pk=pk)

        try:
            expense.mark_as_paid(
                paid_by=request.user,
                payment_method=payment_method,
                payment_reference=payment_reference,
                payment_date=payment_date
            )
            messages.success(request, f'Expense {expense.expense_number} marked as paid.')
        except Exception as e:
            messages.error(request, f'Error marking expense as paid: {str(e)}')

        return redirect('expenses:expense_detail', pk=pk)

    return render(request, 'expenses/expense_payment.html', {
        'expense': expense
    })


@login_required
def cancel_expense(request, pk):
    """Cancel an expense"""
    expense = get_object_or_404(Expense, pk=pk)

    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        if not reason:
            messages.error(request, 'Cancellation reason is required.')
            return redirect('expenses:expense_detail', pk=pk)

        try:
            expense.cancel(cancelled_by=request.user, reason=reason)
            messages.success(request, f'Expense {expense.expense_number} cancelled.')
        except Exception as e:
            messages.error(request, f'Error cancelling expense: {str(e)}')

        return redirect('expenses:expense_detail', pk=pk)

    return render(request, 'expenses/expense_cancel.html', {
        'expense': expense
    })


# ==================== Vendor Views ====================

class VendorListView(LoginRequiredMixin, ListView):
    """List all vendors"""
    model = Vendor
    template_name = 'expenses/vendor_list.html'
    context_object_name = 'vendors'
    paginate_by = 25

    def get_queryset(self):
        queryset = Vendor.objects.all().order_by('name')

        # Apply filters
        vendor_type = self.request.GET.get('vendor_type')
        if vendor_type:
            queryset = queryset.filter(vendor_type=vendor_type)

        is_active = self.request.GET.get('is_active')
        if is_active:
            queryset = queryset.filter(is_active=is_active == 'true')

        search = self.request.GET.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(contact_person__icontains=search) |
                Q(email__icontains=search) |
                Q(tin__icontains=search)
            )

        return queryset


class VendorDetailView(LoginRequiredMixin, DetailView):
    """View vendor details"""
    model = Vendor
    template_name = 'expenses/vendor_detail.html'
    context_object_name = 'vendor'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        vendor = self.object

        # Get vendor expenses
        expenses = vendor.expenses.all().order_by('-expense_date')[:20]
        context['recent_expenses'] = expenses

        # Vendor statistics
        context['total_spent'] = vendor.total_spent
        context['outstanding_balance'] = vendor.outstanding_balance
        context['expense_count'] = vendor.expenses.count()

        # Performance metrics
        from .utils import ExpenseAnalytics
        context['performance'] = ExpenseAnalytics.get_vendor_performance(vendor.id)

        return context


@login_required
def create_vendor(request):
    """Create new vendor"""
    if request.method == 'POST':
        form = VendorForm(request.POST)
        if form.is_valid():
            vendor = form.save(commit=False)
            vendor.created_by = request.user
            vendor.save()

            messages.success(request, f'Vendor {vendor.name} created successfully.')
            return redirect('expenses:vendor_detail', pk=vendor.pk)
    else:
        form = VendorForm()

    return render(request, 'expenses/vendor_form.html', {'form': form})


@login_required
def update_vendor(request, pk):
    """Update existing vendor"""
    vendor = get_object_or_404(Vendor, pk=pk)

    if request.method == 'POST':
        form = VendorForm(request.POST, instance=vendor)
        if form.is_valid():
            vendor = form.save()
            messages.success(request, 'Vendor updated successfully.')
            return redirect('expenses:vendor_detail', pk=vendor.pk)
    else:
        form = VendorForm(instance=vendor)

    return render(request, 'expenses/vendor_form.html', {
        'form': form,
        'vendor': vendor,
        'is_update': True
    })


# ==================== Budget Views ====================

class BudgetListView(LoginRequiredMixin, ListView):
    """List all budgets"""
    model = Budget
    template_name = 'expenses/budget_list.html'
    context_object_name = 'budgets'
    paginate_by = 25

    def get_queryset(self):
        queryset = Budget.objects.select_related(
            'category', 'store'
        ).order_by('-start_date')

        # Filter by store
        if hasattr(self.request.user, 'stores'):
            store = self.request.user.stores.first()
            if store:
                queryset = queryset.filter(Q(store=store) | Q(store__isnull=True))

        return queryset


@login_required
def budget_dashboard(request):
    """Budget overview dashboard"""
    store = request.user.stores.first() if hasattr(request.user, 'stores') else None
    today = timezone.now().date()

    # Active budgets
    active_budgets = Budget.objects.filter(
        start_date__lte=today,
        end_date__gte=today,
        is_active=True
    )

    if store:
        active_budgets = active_budgets.filter(Q(store=store) | Q(store__isnull=True))

    # Budget performance
    from .utils import BudgetCalculator
    performance = BudgetCalculator().calculate_budget_forecast(
        category=None,
        store=store,
        months_ahead=3
    )

    context = {
        'active_budgets': active_budgets,
        'performance': performance,
        'store': store,
    }

    return render(request, 'expenses/budget_dashboard.html', context)


# ==================== Report Views ====================

@login_required
def expense_reports(request):
    """Expense reports page"""
    store = request.user.stores.first() if hasattr(request.user, 'stores') else None

    # Get date range from request or default to current month
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date or not end_date:
        today = timezone.now().date()
        start_date = today.replace(day=1)
        end_date = today

    # Get analytics
    analytics = ExpenseAnalytics.get_expense_summary(
        store=store,
        start_date=start_date,
        end_date=end_date
    )

    # Get trends
    trends = ExpenseAnalytics.get_expense_trends(store=store, months=6)

    # Overdue report
    overdue = ExpenseAnalytics.get_overdue_report(store=store)

    context = {
        'analytics': analytics,
        'trends': trends,
        'overdue': overdue,
        'start_date': start_date,
        'end_date': end_date,
        'store': store,
    }

    return render(request, 'expenses/reports.html', context)


@login_required
def export_expenses(request):
    """Export expenses to Excel/PDF/CSV"""
    format_type = request.GET.get('format', 'excel')

    # Get filtered expenses
    expenses = Expense.objects.filter(status='PAID')

    # Apply filters
    store_id = request.GET.get('store')
    if store_id:
        expenses = expenses.filter(store_id=store_id)

    start_date = request.GET.get('start_date')
    if start_date:
        expenses = expenses.filter(expense_date__gte=start_date)

    end_date = request.GET.get('end_date')
    if end_date:
        expenses = expenses.filter(expense_date__lte=end_date)

    # Export based on format
    if format_type == 'excel':
        output = ExpenseExporter.export_to_excel(expenses)
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename=expenses.xlsx'

    elif format_type == 'pdf':
        output = ExpenseExporter.export_to_pdf(expenses)
        response = HttpResponse(output.read(), content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename=expenses.pdf'

    elif format_type == 'csv':
        output = ExpenseExporter.export_to_csv(expenses)
        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=expenses.csv'

    else:
        messages.error(request, 'Invalid export format.')
        return redirect('expenses:reports')

    return response


# ==================== API/AJAX Views ====================

@login_required
@require_http_methods(["GET"])
def get_expense_stats_api(request):
    """API endpoint for expense statistics"""
    store_id = request.GET.get('store_id')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    store = None
    if store_id:
        from stores.models import Store
        store = Store.objects.filter(id=store_id).first()

    stats = get_expense_statistics(
        store=store,
        start_date=start_date,
        end_date=end_date
    )

    # Convert Decimal to float for JSON serialization
    import json
    from decimal import Decimal

    def decimal_to_float(obj):
        if isinstance(obj, Decimal):
            return float(obj)
        raise TypeError

    return JsonResponse(stats, safe=False, encoder=json.JSONEncoder, default=decimal_to_float)


@login_required
def check_budget_availability(request):
    """Check if budget is available for expense"""
    category_id = request.GET.get('category_id')
    amount = request.GET.get('amount', 0)
    store_id = request.GET.get('store_id')

    try:
        amount = Decimal(amount)
    except:
        return JsonResponse({'error': 'Invalid amount'}, status=400)

    # Find active budget
    today = timezone.now().date()
    budgets = Budget.objects.filter(
        category_id=category_id,
        start_date__lte=today,
        end_date__gte=today,
        is_active=True
    )

    if store_id:
        budgets = budgets.filter(Q(store_id=store_id) | Q(store__isnull=True))

    result = {
        'has_budget': False,
        'available': False,
        'message': 'No active budget found'
    }

    for budget in budgets:
        result['has_budget'] = True
        remaining = budget.remaining_amount

        if remaining >= amount:
            result['available'] = True
            result['message'] = f'Budget available. Remaining: {remaining}'
            break
        else:
            result['message'] = f'Insufficient budget. Remaining: {remaining}, Required: {amount}'

    return JsonResponse(result)