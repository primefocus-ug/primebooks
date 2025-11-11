from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.db.models import Q, Sum, Count, F, Case, When, Value
from django.http import JsonResponse, HttpResponse
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.core.paginator import Paginator
from django.views.decorators.http import require_http_methods
from django.db import transaction as db_transaction
from django_tenants.utils import schema_context, get_tenant_model
from decimal import Decimal
from accounts.models import CustomUser
from django.core.exceptions import ValidationError,PermissionDenied
from datetime import datetime, timedelta
import json
import csv

from .models import (
    Currency, ExchangeRate, Dimension, DimensionValue,
    ChartOfAccounts, AccountType, Journal, JournalEntry, JournalEntryLine,
    FiscalYear, FiscalPeriod, BankAccount, Transaction,
    BankReconciliation, BankReconciliationItem, BankStatement, BankTransaction,
    Budget, BudgetLine, TaxCode, AssetCategory, FixedAsset, DepreciationRecord,
    RecurringJournalEntry, FinancialReport, AuditLog,JournalType,Expense,ExpenseCategory,Receipt
)
from .forms import (
    ChartOfAccountsForm, JournalEntryForm, JournalEntryLineFormSet,
    BankAccountForm, TransactionForm, BudgetForm, TaxCodeForm,DimensionValueForm,CurrencyForm,
    BankReconciliationForm, FixedAssetForm, RecurringJournalEntryForm,DimensionForm,ExchangeRateForm,QuickExpenseForm,ExpenseForm,ExpenseCategoryForm
)
from .tasks import (
    generate_financial_report_task, process_bank_statement_task,
    calculate_depreciation_task, fetch_exchange_rates_task,
    generate_recurring_entries_task
)


# ============================================
# HELPER FUNCTIONS
# ============================================

def get_base_currency():
    """Get base currency for current tenant"""
    return Currency.objects.filter(is_base=True).first()


def convert_to_base_currency(amount, from_currency, date=None):
    """Convert amount to base currency"""
    base_currency = get_base_currency()
    if not base_currency or from_currency == base_currency:
        return amount

    return ExchangeRate.convert_amount(
        amount,
        from_currency,
        base_currency,
        date or timezone.now().date()
    )


# ============================================
# DASHBOARD
# ============================================

@login_required
def expense_dashboard(request):
    """Cashier expense dashboard"""
    # Recent expenses
    recent_expenses = Expense.objects.filter(
        submitted_by=request.user
    ).select_related('category', 'currency').order_by('-date')[:10]

    # Monthly totals
    current_month = timezone.now().replace(day=1)
    monthly_total = Expense.objects.filter(
        submitted_by=request.user,
        date__gte=current_month,
        status__in=['APPROVED', 'PAID']
    ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

    # Pending approvals
    pending_count = Expense.objects.filter(
        submitted_by=request.user,
        status='SUBMITTED'
    ).count()

    context = {
        'recent_expenses': recent_expenses,
        'monthly_total': monthly_total,
        'pending_count': pending_count,
    }
    return render(request, 'finance/expenses/dashboard.html', context)


@login_required
@permission_required('finance.view_expensecategory', raise_exception=True)
def expense_category_list(request):
    """List expense categories"""
    categories = ExpenseCategory.objects.filter(is_active=True).select_related('parent', 'gl_account')

    # Build tree structure for display
    def build_category_tree(categories, parent=None, level=0):
        tree = []
        for category in categories:
            if category.parent == parent:
                category.level = level
                tree.append(category)
                tree.extend(build_category_tree(categories, category, level + 1))
        return tree

    category_tree = build_category_tree(categories)

    context = {
        'categories': category_tree,
    }
    return render(request, 'finance/expenses/category_list.html', context)

@login_required
def expense_create(request):
    """Create new expense - for cashiers"""
    if request.method == 'POST':
        form = ExpenseForm(request.POST, request.FILES, request=request)
        if form.is_valid():
            try:
                with db_transaction.atomic():
                    expense = form.save(commit=False)
                    expense.submitted_by = request.user
                    expense.status = 'SUBMITTED'
                    expense.submitted_at = timezone.now()
                    expense.save()
                    form.save_m2m()  # Save many-to-many

                    # Handle receipt upload
                    if 'receipt_image' in request.FILES:
                        Receipt.objects.create(
                            expense=expense,
                            image=request.FILES['receipt_image'],
                            uploaded_by=request.user
                        )

                    messages.success(request, 'Expense submitted for approval.')
                    return redirect('finance:expense_detail', pk=expense.pk)

            except Exception as e:
                messages.error(request, f'Error creating expense: {str(e)}')
    else:
        form = ExpenseForm(request=request)

    context = {
        'form': form,
        'categories': ExpenseCategory.objects.filter(is_active=True),
        'bank_accounts': BankAccount.objects.filter(is_active=True),
    }
    return render(request, 'finance/expenses/form.html', context)


@login_required
def quick_expense_create(request):
    """Quick expense entry for cashiers"""
    if request.method == 'POST':
        form = QuickExpenseForm(request.POST)
        if form.is_valid():
            try:
                expense = form.save(commit=False)
                expense.submitted_by = request.user
                expense.date = timezone.now().date()
                expense.currency = get_base_currency()
                expense.payment_method = 'CASH'
                expense.status = 'SUBMITTED'
                expense.submitted_at = timezone.now()
                expense.save()

                messages.success(request, 'Quick expense recorded.')
                return redirect('finance:expense_dashboard')

            except Exception as e:
                messages.error(request, f'Error: {str(e)}')
    else:
        form = QuickExpenseForm()

    return render(request, 'finance/expenses/quick_form.html', {'form': form})


@login_required
def expense_list(request):
    """List expenses with filters"""
    status = request.GET.get('status')
    category = request.GET.get('category')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    expenses = Expense.objects.select_related(
        'category', 'currency', 'submitted_by'
    )

    # Filter by user role
    if not request.user.has_perm('finance.approve_expense'):
        expenses = expenses.filter(submitted_by=request.user)

    if status:
        expenses = expenses.filter(status=status)
    if category:
        expenses = expenses.filter(category_id=category)
    if date_from:
        expenses = expenses.filter(date__gte=date_from)
    if date_to:
        expenses = expenses.filter(date__lte=date_to)

    expenses = expenses.order_by('-date', '-created_at')

    paginator = Paginator(expenses, 25)
    page = request.GET.get('page')
    expenses = paginator.get_page(page)

    context = {
        'expenses': expenses,
        'categories': ExpenseCategory.objects.filter(is_active=True),
    }
    return render(request, 'finance/expenses/list.html', context)


@login_required
def expense_detail(request, pk):
    """Expense detail view"""
    expense = get_object_or_404(
        Expense.objects.select_related(
            'category', 'currency', 'submitted_by',
            'approved_by', 'journal_entry'
        ).prefetch_related('receipts', 'dimension_values'),
        pk=pk
    )

    # Check permission
    if expense.submitted_by != request.user and not request.user.has_perm('finance.approve_expense'):
        raise PermissionDenied

    context = {
        'expense': expense,
        'can_approve': request.user.has_perm('finance.approve_expense'),
    }
    return render(request, 'finance/expenses/detail.html', context)


@login_required
@permission_required('finance.approve_expense', raise_exception=True)
def expense_approve(request, pk):
    """Approve expense"""
    expense = get_object_or_404(Expense, pk=pk)

    if request.method == 'POST':
        try:
            with db_transaction.atomic():
                expense.status = 'APPROVED'
                expense.approved_by = request.user
                expense.approved_at = timezone.now()
                expense.save()

                # Create journal entry
                expense.create_journal_entry()

                messages.success(request, 'Expense approved and posted to accounting.')

        except Exception as e:
            messages.error(request, f'Error approving expense: {str(e)}')

    return redirect('finance:expense_detail', pk=expense.pk)


@login_required
@permission_required('finance.approve_expense', raise_exception=True)
def expense_reject(request, pk):
    """Reject expense"""
    expense = get_object_or_404(Expense, pk=pk)

    if request.method == 'POST':
        reason = request.POST.get('reason', '')
        expense.status = 'REJECTED'
        expense.save()

        messages.success(request, f'Expense rejected. Reason: {reason}')

    return redirect('finance:expense_detail', pk=expense.pk)


@login_required
@permission_required('finance.add_expensecategory', raise_exception=True)
def expense_category_create(request):
    """Create new expense category"""
    if request.method == 'POST':
        form = ExpenseCategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            messages.success(request, 'Expense category created successfully.')
            return redirect('finance:expense_category_list')
    else:
        form = ExpenseCategoryForm()

    context = {'form': form}
    return render(request, 'finance/expenses/category_form.html', context)


@login_required
@permission_required('finance.change_expensecategory', raise_exception=True)
def expense_category_update(request, pk):
    """Update expense category"""
    category = get_object_or_404(ExpenseCategory, pk=pk)

    if request.method == 'POST':
        form = ExpenseCategoryForm(request.POST, instance=category)
        if form.is_valid():
            form.save()
            messages.success(request, 'Expense category updated successfully.')
            return redirect('finance:expense_category_list')
    else:
        form = ExpenseCategoryForm(instance=category)

    context = {'form': form, 'category': category}
    return render(request, 'finance/expenses/category_form.html', context)


@login_required
@permission_required('finance.delete_expensecategory', raise_exception=True)
def expense_category_delete(request, pk):
    """Delete expense category (soft delete)"""
    category = get_object_or_404(ExpenseCategory, pk=pk)

    if request.method == 'POST':
        # Check if category has expenses
        if category.expense_set.exists():
            messages.error(request, 'Cannot delete category with existing expenses.')
        else:
            category.is_active = False
            category.save()
            messages.success(request, 'Expense category deleted successfully.')

        return redirect('finance:expense_category_list')

    context = {'category': category}
    return render(request, 'finance/expenses/category_confirm_delete.html', context)


# ============================================
# EXPENSE REPORTING VIEWS
# ============================================

@login_required
@permission_required('finance.view_expense', raise_exception=True)
def expense_report(request):
    """Generate expense reports"""
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    category_id = request.GET.get('category')
    submitted_by = request.GET.get('submitted_by')

    # Default to current month
    if not start_date or not end_date:
        today = timezone.now().date()
        start_date = today.replace(day=1)
        end_date = today

    # Build base queryset
    expenses = Expense.objects.filter(
        date__range=[start_date, end_date],
        status__in=['APPROVED', 'PAID']
    ).select_related('category', 'currency', 'submitted_by')

    # Apply filters
    if category_id:
        expenses = expenses.filter(category_id=category_id)
    if submitted_by:
        expenses = expenses.filter(submitted_by_id=submitted_by)

    # Group by category for summary
    category_summary = expenses.values(
        'category__code', 'category__name'
    ).annotate(
        total_amount=Sum('amount'),
        expense_count=Count('id')
    ).order_by('-total_amount')

    # Monthly trend (last 6 months)
    monthly_trend = []
    for i in range(6):
        month_date = timezone.now().date().replace(day=1) - timedelta(days=30 * i)
        month_start = month_date.replace(day=1)
        if i == 0:
            month_end = timezone.now().date()
        else:
            next_month = month_start + timedelta(days=32)
            month_end = next_month.replace(day=1) - timedelta(days=1)

        month_total = Expense.objects.filter(
            date__range=[month_start, month_end],
            status__in=['APPROVED', 'PAID']
        ).aggregate(total=Sum('amount'))['total'] or Decimal('0')

        monthly_trend.append({
            'month': month_start.strftime('%b %Y'),
            'total': month_total
        })

    monthly_trend.reverse()

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'expenses': expenses.order_by('-date'),
        'category_summary': category_summary,
        'monthly_trend': monthly_trend,
        'categories': ExpenseCategory.objects.filter(is_active=True),
        'users': CustomUser.objects.filter(is_active=True),  # For submitted_by filter
    }

    return render(request, 'finance/expenses/report.html', context)


@login_required
@permission_required('finance.view_expense', raise_exception=True)
def export_expense_report(request):
    """Export expense report to CSV"""
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    category_id = request.GET.get('category')

    if not start_date or not end_date:
        today = timezone.now().date()
        start_date = today.replace(day=1)
        end_date = today

    expenses = Expense.objects.filter(
        date__range=[start_date, end_date],
        status__in=['APPROVED', 'PAID']
    ).select_related('category', 'currency', 'submitted_by')

    if category_id:
        expenses = expenses.filter(category_id=category_id)

    response = HttpResponse(content_type='text/csv')
    filename = f"expense_report_{start_date}_to_{end_date}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(
        ['Date', 'Expense Number', 'Category', 'Description', 'Amount', 'Currency', 'Submitted By', 'Status'])

    for expense in expenses:
        writer.writerow([
            expense.date,
            expense.expense_number,
            expense.category.name,
            expense.description,
            expense.amount,
            expense.currency.code,
            expense.submitted_by.get_full_name(),
            expense.get_status_display()
        ])

    return response

@login_required
@permission_required('finance.view_pettycash', raise_exception=True)
def petty_cash_list(request):
    """List petty cash funds"""
    petty_cash_funds = PettyCash.objects.filter(is_active=True).select_related('custodian', 'gl_account')

    context = {
        'petty_cash_funds': petty_cash_funds,
    }
    return render(request, 'finance/expenses/petty_cash_list.html', context)


@login_required
@permission_required('finance.add_pettycash', raise_exception=True)
def petty_cash_create(request):
    """Create new petty cash fund"""
    if request.method == 'POST':
        # Using model directly since we don't have a form
        name = request.POST.get('name')
        custodian_id = request.POST.get('custodian')
        gl_account_id = request.POST.get('gl_account')
        max_amount = request.POST.get('max_amount')

        try:
            petty_cash = PettyCash.objects.create(
                name=name,
                custodian_id=custodian_id,
                gl_account_id=gl_account_id,
                max_amount=max_amount
            )
            messages.success(request, 'Petty cash fund created successfully.')
            return redirect('finance:petty_cash_list')
        except Exception as e:
            messages.error(request, f'Error creating petty cash fund: {str(e)}')

    context = {
        'users': User.objects.filter(is_active=True),
        'accounts': ChartOfAccounts.objects.filter(
            account_type=AccountType.ASSET,
            is_active=True
        ),
    }
    return render(request, 'finance/expenses/petty_cash_form.html', context)


@login_required
@permission_required('finance.change_pettycash', raise_exception=True)
def petty_cash_replenish(request, pk):
    """Replenish petty cash fund"""
    petty_cash = get_object_or_404(PettyCash, pk=pk)

    if request.method == 'POST':
        amount = Decimal(request.POST.get('amount', 0))

        try:
            with db_transaction.atomic():
                # Create journal entry for replenishment
                journal = Journal.objects.filter(journal_type=JournalType.CASH_PAYMENTS, is_active=True).first()
                if not journal:
                    journal = Journal.objects.filter(journal_type=JournalType.GENERAL, is_active=True).first()

                entry = JournalEntry.objects.create(
                    journal=journal,
                    entry_number=journal.get_next_entry_number(),
                    entry_date=timezone.now().date(),
                    description=f"Replenish petty cash: {petty_cash.name}",
                    currency=get_base_currency(),
                    created_by=request.user
                )

                # Debit: Petty Cash account
                JournalEntryLine.objects.create(
                    journal_entry=entry,
                    account=petty_cash.gl_account,
                    debit_amount=amount,
                    description=f"Replenish {petty_cash.name}",
                    currency=get_base_currency()
                )

                # Credit: Bank account (you might want to make this configurable)
                bank_account = BankAccount.objects.filter(is_default=True).first()
                if bank_account:
                    JournalEntryLine.objects.create(
                        journal_entry=entry,
                        account=bank_account.gl_account,
                        credit_amount=amount,
                        description=f"Replenish {petty_cash.name}",
                        currency=get_base_currency()
                    )

                entry.calculate_totals()
                entry.post(request.user)

                # Update petty cash balance
                petty_cash.current_balance += amount
                petty_cash.save()

                messages.success(request, f'Petty cash replenished by {amount}.')

        except Exception as e:
            messages.error(request, f'Error replenishing petty cash: {str(e)}')

    return redirect('finance:petty_cash_list')

# ============================================
# URL PATTERNS TO ADD
# ============================================

@login_required
@permission_required('finance.view_chartofaccounts', raise_exception=True)
def finance_dashboard(request):
    """Enhanced finance dashboard with KPIs"""

    # Get current fiscal year
    current_year = FiscalYear.objects.filter(is_current=True).first()
    base_currency = get_base_currency()

    if current_year:
        # Assets
        total_assets = ChartOfAccounts.objects.filter(
            account_type=AccountType.ASSET,
            is_active=True
        ).aggregate(total=Sum('current_balance_base'))['total'] or Decimal('0')

        # Liabilities
        total_liabilities = ChartOfAccounts.objects.filter(
            account_type=AccountType.LIABILITY,
            is_active=True
        ).aggregate(total=Sum('current_balance_base'))['total'] or Decimal('0')

        # Equity
        total_equity = ChartOfAccounts.objects.filter(
            account_type=AccountType.EQUITY,
            is_active=True
        ).aggregate(total=Sum('current_balance_base'))['total'] or Decimal('0')

        # Revenue (YTD)
        total_revenue = JournalEntryLine.objects.filter(
            account__account_type=AccountType.REVENUE,
            journal_entry__status='POSTED',
            journal_entry__fiscal_year=current_year
        ).aggregate(
            total=Sum('credit_amount_base') - Sum('debit_amount_base')
        )['total'] or Decimal('0')

        # Expenses (YTD)
        total_expenses = JournalEntryLine.objects.filter(
            account__account_type=AccountType.EXPENSE,
            journal_entry__status='POSTED',
            journal_entry__fiscal_year=current_year
        ).aggregate(
            total=Sum('debit_amount_base') - Sum('credit_amount_base')
        )['total'] or Decimal('0')

        net_income = total_revenue - total_expenses
    else:
        total_assets = total_liabilities = total_equity = Decimal('0')
        total_revenue = total_expenses = net_income = Decimal('0')

    # Pending approvals
    pending_entries = JournalEntry.objects.filter(
        status__in=['DRAFT', 'PENDING']
    ).count()

    # Recent transactions
    recent_transactions = Transaction.objects.select_related(
        'bank_account', 'created_by', 'currency'
    ).order_by('-transaction_date')[:10]

    # Bank accounts
    bank_accounts = BankAccount.objects.filter(
        is_active=True
    ).select_related('currency', 'gl_account').order_by('-is_default')

    # Budget utilization alerts
    budget_alerts = []
    if current_year:
        active_budgets = Budget.objects.filter(
            fiscal_year=current_year,
            status='ACTIVE'
        )

        for budget in active_budgets:
            utilization = budget.get_utilization()
            if utilization >= budget.alert_threshold:
                budget_alerts.append({
                    'budget': budget,
                    'utilization': utilization
                })

    context = {
        'current_fiscal_year': current_year,
        'base_currency': base_currency,
        'total_assets': total_assets,
        'total_liabilities': total_liabilities,
        'total_equity': total_equity,
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'net_income': net_income,
        'pending_entries': pending_entries,
        'recent_transactions': recent_transactions,
        'bank_accounts': bank_accounts,
        'budget_alerts': budget_alerts,
    }

    return render(request, 'finance/dashboard.html', context)


# ============================================
# CURRENCY MANAGEMENT
# ============================================

@login_required
@permission_required('finance.view_currency', raise_exception=True)
def currency_list(request):
    """List currencies"""
    currencies = Currency.objects.filter(is_active=True).order_by('code')

    context = {'currencies': currencies}
    return render(request, 'finance/currency/list.html', context)


@login_required
@permission_required('finance.view_exchangerate', raise_exception=True)
def exchange_rate_list(request):
    """List exchange rates"""
    from_currency = request.GET.get('from_currency')
    to_currency = request.GET.get('to_currency')
    date_from = request.GET.get('date_from')

    rates = ExchangeRate.objects.select_related(
        'from_currency', 'to_currency'
    ).filter(is_active=True)

    if from_currency:
        rates = rates.filter(from_currency_id=from_currency)
    if to_currency:
        rates = rates.filter(to_currency_id=to_currency)
    if date_from:
        rates = rates.filter(rate_date__gte=date_from)

    rates = rates.order_by('-rate_date', 'from_currency__code')[:100]

    currencies = Currency.objects.filter(is_active=True)

    context = {
        'rates': rates,
        'currencies': currencies,
    }
    return render(request, 'finance/currency/exchange_rates.html', context)


@login_required
@permission_required('finance.add_exchangerate', raise_exception=True)
@require_http_methods(['POST'])
def fetch_exchange_rates(request):
    """Fetch latest exchange rates from API"""
    try:
        success = ExchangeRate.fetch_rates_from_api()
        if success:
            messages.success(request, _('Exchange rates updated successfully.'))
        else:
            messages.warning(request, _('Could not fetch exchange rates. Please try again later.'))
    except Exception as e:
        messages.error(request, f'Error fetching rates: {str(e)}')

    return redirect('finance:exchange_rate_list')


# ============================================
# DIMENSIONS
# ============================================

@login_required
@permission_required('finance.view_dimension', raise_exception=True)
def dimension_list(request):
    """List dimensions"""
    dimensions = Dimension.objects.filter(
        is_active=True
    ).prefetch_related('values').order_by('dimension_type', 'code')

    context = {'dimensions': dimensions}
    return render(request, 'finance/dimensions/list.html', context)


@login_required
@permission_required('finance.view_dimension', raise_exception=True)
def dimension_detail(request, pk):
    """Dimension detail with values"""
    dimension = get_object_or_404(Dimension, pk=pk)

    values = dimension.values.filter(is_active=True).select_related('manager')

    context = {
        'dimension': dimension,
        'values': values,
    }
    return render(request, 'finance/dimensions/detail.html', context)


# ============================================
# CHART OF ACCOUNTS
# ============================================

@login_required
@permission_required('finance.view_chartofaccounts', raise_exception=True)
def chart_of_accounts_list(request):
    """Enhanced chart of accounts with multi-currency"""
    account_type = request.GET.get('account_type')
    currency = request.GET.get('currency')
    search = request.GET.get('search')
    show_inactive = request.GET.get('show_inactive', False)

    accounts = ChartOfAccounts.objects.select_related('currency', 'parent')

    if not show_inactive:
        accounts = accounts.filter(is_active=True)

    if account_type:
        accounts = accounts.filter(account_type=account_type)

    if currency:
        accounts = accounts.filter(currency_id=currency)

    if search:
        accounts = accounts.filter(
            Q(code__icontains=search) |
            Q(name__icontains=search) |
            Q(description__icontains=search)
        )

    # Get root accounts
    root_accounts = accounts.filter(parent__isnull=True).order_by('code')

    currencies = Currency.objects.filter(is_active=True)

    context = {
        'root_accounts': root_accounts,
        'account_types': AccountType.choices,
        'currencies': currencies,
        'selected_type': account_type,
        'selected_currency': currency,
        'search': search,
        'show_inactive': show_inactive,
    }

    return render(request, 'finance/chart_of_accounts/list.html', context)


@login_required
@permission_required('finance.add_chartofaccounts', raise_exception=True)
def chart_of_accounts_create(request):
    """Create new account"""
    if request.method == 'POST':
        form = ChartOfAccountsForm(request.POST)
        if form.is_valid():
            account = form.save(commit=False)
            account.created_by = request.user
            account.save()
            form.save_m2m()  # Save many-to-many relationships
            messages.success(request, _('Account created successfully.'))
            return redirect('finance:chart_of_accounts_detail', pk=account.pk)
    else:
        form = ChartOfAccountsForm()

    context = {'form': form}
    return render(request, 'finance/chart_of_accounts/form.html', context)


@login_required
@permission_required('finance.view_chartofaccounts', raise_exception=True)
def chart_of_accounts_detail(request, pk):
    """Enhanced account detail with multi-dimensional analysis"""
    account = get_object_or_404(
        ChartOfAccounts.objects.select_related('currency', 'parent'),
        pk=pk
    )

    # Date range filter
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    dimension_filter = request.GET.get('dimension')

    # Recent transactions
    recent_lines = JournalEntryLine.objects.filter(
        account=account,
        journal_entry__status='POSTED'
    ).select_related(
        'journal_entry__journal',
        'journal_entry__fiscal_period',
        'currency'
    ).prefetch_related('dimension_values')

    if date_from:
        recent_lines = recent_lines.filter(journal_entry__posting_date__gte=date_from)
    if date_to:
        recent_lines = recent_lines.filter(journal_entry__posting_date__lte=date_to)

    recent_lines = recent_lines.order_by('-journal_entry__posting_date')[:50]

    # Balance by dimension
    dimension_balances = []
    if dimension_filter:
        dimension = get_object_or_404(Dimension, pk=dimension_filter)
        for dim_value in dimension.values.filter(is_active=True):
            balance = account.get_balance(dimensions=[dim_value])
            if balance != 0:
                dimension_balances.append({
                    'dimension_value': dim_value,
                    'balance': balance
                })

    # Monthly balance trend (last 12 months)
    balance_history = []
    current_date = timezone.now().date()
    for i in range(12):
        date = current_date - timedelta(days=30 * i)
        balance = account.get_balance(as_of_date=date)
        balance_history.append({
            'date': date,
            'balance': balance
        })

    dimensions = Dimension.objects.filter(is_active=True)

    context = {
        'account': account,
        'recent_lines': recent_lines,
        'balance_history': reversed(balance_history),
        'current_balance': account.current_balance,
        'current_balance_base': account.current_balance_base,
        'dimensions': dimensions,
        'dimension_balances': dimension_balances,
        'date_from': date_from,
        'date_to': date_to,
    }

    return render(request, 'finance/chart_of_accounts/detail.html', context)


@login_required
@permission_required('finance.change_chartofaccounts', raise_exception=True)
def chart_of_accounts_update(request, pk):
    """Update account"""
    account = get_object_or_404(ChartOfAccounts, pk=pk)

    if account.is_system:
        messages.error(request, _('Cannot modify system account.'))
        return redirect('finance:chart_of_accounts_detail', pk=account.pk)

    if request.method == 'POST':
        form = ChartOfAccountsForm(request.POST, instance=account)
        if form.is_valid():
            form.save()
            messages.success(request, _('Account updated successfully.'))
            return redirect('finance:chart_of_accounts_detail', pk=account.pk)
    else:
        form = ChartOfAccountsForm(instance=account)

    context = {
        'form': form,
        'account': account,
    }
    return render(request, 'finance/chart_of_accounts/form.html', context)


# ============================================
# FISCAL YEAR & PERIODS
# ============================================

@login_required
@permission_required('finance.view_fiscalyear', raise_exception=True)
def fiscal_year_list(request):
    """List fiscal years"""
    fiscal_years = FiscalYear.objects.all().order_by('-start_date')

    context = {'fiscal_years': fiscal_years}
    return render(request, 'finance/fiscal_year/list.html', context)


@login_required
@permission_required('finance.view_fiscalyear', raise_exception=True)
def fiscal_year_detail(request, pk):
    """Fiscal year detail with periods"""
    fiscal_year = get_object_or_404(FiscalYear, pk=pk)

    periods = fiscal_year.periods.all().order_by('period_number')

    context = {
        'fiscal_year': fiscal_year,
        'periods': periods,
    }
    return render(request, 'finance/fiscal_year/detail.html', context)


@login_required
@permission_required('finance.add_fiscalyear', raise_exception=True)
@require_http_methods(['POST'])
def fiscal_year_generate_periods(request, pk):
    """Generate periods for fiscal year"""
    fiscal_year = get_object_or_404(FiscalYear, pk=pk)

    try:
        fiscal_year.generate_periods()
        messages.success(request, _('Periods generated successfully.'))
    except Exception as e:
        messages.error(request, str(e))

    return redirect('finance:fiscal_year_detail', pk=pk)


@login_required
@permission_required('finance.change_fiscalperiod', raise_exception=True)
@require_http_methods(['POST'])
def fiscal_period_close(request, pk):
    """Close fiscal period"""
    period = get_object_or_404(FiscalPeriod, pk=pk)

    try:
        with db_transaction.atomic():
            period.close_period(request.user)
        messages.success(request, _(f'Period {period.name} closed successfully.'))
    except Exception as e:
        messages.error(request, str(e))

    return redirect('finance:fiscal_year_detail', pk=period.fiscal_year_id)


# ============================================
# JOURNAL ENTRIES
# ============================================

@login_required
@permission_required('finance.view_journalentry', raise_exception=True)
def journal_entry_list(request):
    """List journal entries with filters"""
    status = request.GET.get('status')
    journal_type = request.GET.get('journal')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    search = request.GET.get('search')

    entries = JournalEntry.objects.select_related(
        'journal', 'created_by', 'fiscal_year', 'fiscal_period', 'currency'
    ).prefetch_related('lines')

    if status:
        entries = entries.filter(status=status)
    if journal_type:
        entries = entries.filter(journal_id=journal_type)
    if date_from:
        entries = entries.filter(entry_date__gte=date_from)
    if date_to:
        entries = entries.filter(entry_date__lte=date_to)
    if search:
        entries = entries.filter(
            Q(entry_number__icontains=search) |
            Q(description__icontains=search) |
            Q(reference__icontains=search)
        )

    entries = entries.order_by('-entry_date', '-created_at')

    paginator = Paginator(entries, 25)
    page = request.GET.get('page')
    entries = paginator.get_page(page)

    journals = Journal.objects.filter(is_active=True)

    context = {
        'entries': entries,
        'journals': journals,
        'status_choices': JournalEntry.STATUS_CHOICES,
    }

    return render(request, 'finance/journal_entry/list.html', context)


@login_required
@permission_required('finance.add_journalentry', raise_exception=True)
def journal_entry_create(request):
    """Create new journal entry with multi-currency support"""
    if request.method == 'POST':
        form = JournalEntryForm(request.POST)
        formset = JournalEntryLineFormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            try:
                with db_transaction.atomic():
                    entry = form.save(commit=False)
                    entry.created_by = request.user

                    # Generate entry number
                    entry.entry_number = entry.journal.get_next_entry_number()

                    # Get fiscal period
                    fiscal_period = FiscalPeriod.objects.filter(
                        start_date__lte=entry.entry_date,
                        end_date__gte=entry.entry_date,
                        status='OPEN'
                    ).first()

                    if not fiscal_period:
                        raise ValidationError('No open fiscal period for this date')

                    entry.fiscal_period = fiscal_period
                    entry.fiscal_year = fiscal_period.fiscal_year

                    # Check if requires approval
                    if entry.journal.require_approval:
                        if entry.journal.approval_limit:
                            entry.requires_approval = True
                        if entry.journal.auto_approval_limit:
                            # Auto-approve if below limit
                            pass

                    entry.save()

                    # Save lines
                    formset.instance = entry
                    formset.save()

                    # Calculate totals
                    entry.calculate_totals()

                    # Check balance
                    if entry.is_balanced():
                        messages.success(request, _('Journal entry created successfully.'))

                        # Auto-post if configured
                        if not entry.requires_approval and request.POST.get('auto_post'):
                            entry.post(request.user)
                            messages.info(request, _('Entry posted automatically.'))

                        return redirect('finance:journal_entry_detail', pk=entry.pk)
                    else:
                        messages.warning(request, _('Entry is not balanced. Please review.'))
                        return redirect('finance:journal_entry_update', pk=entry.pk)

            except Exception as e:
                messages.error(request, str(e))
    else:
        # Initialize with defaults
        initial = {
            'entry_date': timezone.now().date(),
            'currency': get_base_currency(),
        }
        form = JournalEntryForm(initial=initial)
        formset = JournalEntryLineFormSet()

    journals = Journal.objects.filter(is_active=True)
    currencies = Currency.objects.filter(is_active=True)
    accounts = ChartOfAccounts.objects.filter(
        is_active=True,
        allow_direct_posting=True
    ).select_related('currency')
    dimensions = Dimension.objects.filter(is_active=True).prefetch_related('values')

    context = {
        'form': form,
        'formset': formset,
        'journals': journals,
        'currencies': currencies,
        'accounts': accounts,
        'dimensions': dimensions,
    }
    return render(request, 'finance/journal_entry/form.html', context)


@login_required
@permission_required('finance.view_journalentry', raise_exception=True)
def journal_entry_detail(request, pk):
    """Journal entry detail with audit trail"""
    entry = get_object_or_404(
        JournalEntry.objects.select_related(
            'journal', 'created_by', 'fiscal_year', 'fiscal_period',
            'currency', 'approved_by', 'posted_by'
        ).prefetch_related(
            'lines__account',
            'lines__dimension_values__dimension',
            'lines__currency'
        ),
        pk=pk
    )

    # Get audit logs
    audit_logs = AuditLog.objects.filter(
        model_name='JournalEntry',
        object_id=str(entry.pk)
    ).select_related('user').order_by('-timestamp')[:20]

    context = {
        'entry': entry,
        'audit_logs': audit_logs,
    }
    return render(request, 'finance/journal_entry/detail.html', context)


@login_required
@permission_required('finance.change_journalentry', raise_exception=True)
def journal_entry_update(request, pk):
    """Update journal entry"""
    entry = get_object_or_404(JournalEntry, pk=pk)

    if entry.status not in ['DRAFT', 'PENDING']:
        messages.error(request, _('Only draft/pending entries can be edited.'))
        return redirect('finance:journal_entry_detail', pk=pk)

    if request.method == 'POST':
        form = JournalEntryForm(request.POST, instance=entry)
        formset = JournalEntryLineFormSet(request.POST, instance=entry)

        if form.is_valid() and formset.is_valid():
            try:
                with db_transaction.atomic():
                    form.save()
                    formset.save()
                    entry.calculate_totals()

                    if entry.is_balanced():
                        messages.success(request, _('Entry updated successfully.'))
                        return redirect('finance:journal_entry_detail', pk=entry.pk)
                    else:
                        messages.warning(request, _('Entry is not balanced.'))
            except Exception as e:
                messages.error(request, str(e))
    else:
        form = JournalEntryForm(instance=entry)
        formset = JournalEntryLineFormSet(instance=entry)

    accounts = ChartOfAccounts.objects.filter(
        is_active=True,
        allow_direct_posting=True
    )
    dimensions = Dimension.objects.filter(is_active=True).prefetch_related('values')

    context = {
        'form': form,
        'formset': formset,
        'entry': entry,
        'accounts': accounts,
        'dimensions': dimensions,
    }
    return render(request, 'finance/journal_entry/form.html', context)


@login_required
@permission_required('finance.change_journalentry', raise_exception=True)
@require_http_methods(['POST'])
def journal_entry_post(request, pk):
    """Post journal entry"""
    entry = get_object_or_404(JournalEntry, pk=pk)

    try:
        with db_transaction.atomic():
            entry.post(request.user)

            # Create audit log
            AuditLog.objects.create(
                model_name='JournalEntry',
                object_id=str(entry.pk),
                action='POST',
                user=request.user,
                changes_json={'status': 'POSTED'}
            )

        messages.success(request, _('Journal entry posted successfully.'))
    except Exception as e:
        messages.error(request, str(e))

    return redirect('finance:journal_entry_detail', pk=entry.pk)


@login_required
@permission_required('finance.change_journalentry', raise_exception=True)
@require_http_methods(['POST'])
def journal_entry_approve(request, pk):
    """Approve journal entry"""
    entry = get_object_or_404(JournalEntry, pk=pk)

    try:
        with db_transaction.atomic():
            entry.approve(request.user)

            # Auto-post if configured
            if request.POST.get('auto_post') == 'true':
                entry.post(request.user)

        messages.success(request, _('Entry approved successfully.'))
    except Exception as e:
        messages.error(request, str(e))

    return redirect('finance:journal_entry_detail', pk=entry.pk)


@login_required
@permission_required('finance.delete_journalentry', raise_exception=True)
@require_http_methods(['POST'])
def journal_entry_reverse(request, pk):
    """Reverse journal entry"""
    entry = get_object_or_404(JournalEntry, pk=pk)

    reversal_date = request.POST.get('reversal_date')
    description = request.POST.get('description')

    try:
        with db_transaction.atomic():
            reversal = entry.reverse(
                request.user,
                reversal_date=reversal_date,
                description=description
            )

        messages.success(request, _('Entry reversed successfully.'))
        return redirect('finance:journal_entry_detail', pk=reversal.pk)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('finance:journal_entry_detail', pk=entry.pk)


# ============================================
# RECURRING JOURNAL ENTRIES
# ============================================

@login_required
@permission_required('finance.view_recurringjournalentry', raise_exception=True)
def recurring_entry_list(request):
    """List recurring entries"""
    entries = RecurringJournalEntry.objects.select_related(
        'journal', 'currency', 'created_by'
    ).filter(is_active=True).order_by('next_run_date')

    context = {'entries': entries}
    return render(request, 'finance/recurring_entry/list.html', context)


@login_required
@permission_required('finance.add_recurringjournalentry', raise_exception=True)
@require_http_methods(['POST'])
def recurring_entry_generate(request, pk):
    """Generate entry from recurring template"""
    recurring = get_object_or_404(RecurringJournalEntry, pk=pk)

    try:
        with db_transaction.atomic():
            entry = recurring.generate_entry()

        messages.success(request, _('Entry generated successfully.'))
        return redirect('finance:journal_entry_detail', pk=entry.pk)
    except Exception as e:
        messages.error(request, str(e))
        return redirect('finance:recurring_entry_list')


# ============================================
# BANK ACCOUNTS & TRANSACTIONS
# ============================================

@login_required
@permission_required('finance.view_bankaccount', raise_exception=True)
def bank_account_list(request):
    """List bank accounts with balances"""
    accounts = BankAccount.objects.select_related(
        'gl_account', 'currency'
    ).filter(is_active=True).order_by('-is_default', 'bank_name')

    context = {'accounts': accounts}
    return render(request, 'finance/bank_account/list.html', context)


@login_required
@permission_required('finance.view_bankaccount', raise_exception=True)
def bank_account_detail(request, pk):
    """Bank account detail with transactions"""
    account = get_object_or_404(
        BankAccount.objects.select_related('gl_account', 'currency'),
        pk=pk
    )

    # Filter transactions
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')
    status = request.GET.get('status')

    transactions = Transaction.objects.filter(
        bank_account=account
    ).select_related('currency', 'created_by', 'journal_entry')

    if date_from:
        transactions = transactions.filter(transaction_date__gte=date_from)
    if date_to:
        transactions = transactions.filter(transaction_date__lte=date_to)
    if status:
        transactions = transactions.filter(status=status)

    transactions = transactions.order_by('-transaction_date')[:100]

    # Calculate totals
    totals = transactions.aggregate(
        deposits=Sum('amount', filter=Q(transaction_type='DEPOSIT')),
        withdrawals=Sum('amount', filter=Q(transaction_type='WITHDRAWAL'))
    )

    context = {
        'account': account,
        'transactions': transactions,
        'totals': totals,
    }
    return render(request, 'finance/bank_account/detail.html', context)


@login_required
@permission_required('finance.add_transaction', raise_exception=True)
def transaction_create(request):
    """Create transaction"""
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            try:
                with db_transaction.atomic():
                    transaction = form.save(commit=False)
                    transaction.created_by = request.user

                    # Generate transaction ID
                    transaction.transaction_id = f"TXN-{timezone.now().strftime('%Y%m%d%H%M%S')}"
                    transaction.save()

                    # Update bank balance
                    transaction.bank_account.update_balance()

                    # Create journal entry if requested
                    if request.POST.get('create_journal_entry'):
                        transaction.create_journal_entry(request.user)

                messages.success(request, _('Transaction created successfully.'))
                return redirect('finance:transaction_detail', pk=transaction.pk)
            except Exception as e:
                messages.error(request, str(e))
    else:
        form = TransactionForm()

    bank_accounts = BankAccount.objects.filter(is_active=True)
    currencies = Currency.objects.filter(is_active=True)

    context = {
        'form': form,
        'bank_accounts': bank_accounts,
        'currencies': currencies,
    }
    return render(request, 'finance/transaction/form.html', context)


# ============================================
# BANK RECONCILIATION
# ============================================

@login_required
@permission_required('finance.view_bankreconciliation', raise_exception=True)
def bank_reconciliation_list(request):
    """List bank reconciliations"""
    reconciliations = BankReconciliation.objects.select_related(
        'bank_account', 'reconciled_by'
    ).order_by('-reconciliation_date')

    context = {'reconciliations': reconciliations}
    return render(request, 'finance/reconciliation/list.html', context)


@login_required
@permission_required('finance.add_bankreconciliation', raise_exception=True)
def bank_reconciliation_create(request):
    """Create bank reconciliation"""
    if request.method == 'POST':
        form = BankReconciliationForm(request.POST)
        if form.is_valid():
            try:
                with db_transaction.atomic():
                    reconciliation = form.save(commit=False)
                    reconciliation.reconciled_by = request.user

                    # Generate reconciliation number
                    reconciliation.reconciliation_number = f"REC-{timezone.now().strftime('%Y%m%d%H%M%S')}"

                    # Set opening balance from previous reconciliation or account opening
                    prev_rec = BankReconciliation.objects.filter(
                        bank_account=reconciliation.bank_account,
                        status='COMPLETED'
                    ).order_by('-reconciliation_date').first()

                    if prev_rec:
                        reconciliation.opening_balance = prev_rec.closing_balance_bank
                    else:
                        reconciliation.opening_balance = reconciliation.bank_account.opening_balance

                    reconciliation.save()

                messages.success(request, _('Reconciliation started.'))
                return redirect('finance:bank_reconciliation_detail', pk=reconciliation.pk)
            except Exception as e:
                messages.error(request, str(e))
    else:
        form = BankReconciliationForm()

    bank_accounts = BankAccount.objects.filter(is_active=True)

    context = {
        'form': form,
        'bank_accounts': bank_accounts,
    }
    return render(request, 'finance/reconciliation/form.html', context)


@login_required
@permission_required('finance.view_bankreconciliation', raise_exception=True)
def bank_reconciliation_detail(request, pk):
    """Bank reconciliation with matching interface"""
    reconciliation = get_object_or_404(
        BankReconciliation.objects.select_related('bank_account'),
        pk=pk
    )

    # Get unmatched bank transactions
    bank_transactions = BankTransaction.objects.filter(
        bank_account=reconciliation.bank_account,
        is_reconciled=False,
        transaction_date__range=[
            reconciliation.start_date,
            reconciliation.end_date
        ]
    ).order_by('transaction_date')

    # Get uncleared book transactions
    book_transactions = Transaction.objects.filter(
        bank_account=reconciliation.bank_account,
        is_cleared=False,
        transaction_date__range=[
            reconciliation.start_date,
            reconciliation.end_date
        ]
    ).select_related('currency', 'journal_entry').order_by('transaction_date')

    # Get reconciliation items
    rec_items = reconciliation.items.select_related('book_transaction')

    context = {
        'reconciliation': reconciliation,
        'bank_transactions': bank_transactions,
        'book_transactions': book_transactions,
        'rec_items': rec_items,
    }

    return render(request, 'finance/reconciliation/detail.html', context)


@login_required
@permission_required('finance.change_bankreconciliation', raise_exception=True)
@require_http_methods(['POST'])
def bank_reconciliation_match(request, pk):
    """Match bank and book transactions"""
    reconciliation = get_object_or_404(BankReconciliation, pk=pk)

    bank_transaction_id = request.POST.get('bank_transaction_id')
    book_transaction_id = request.POST.get('book_transaction_id')

    if bank_transaction_id and book_transaction_id:
        try:
            with db_transaction.atomic():
                bank_trans = BankTransaction.objects.get(pk=bank_transaction_id)
                book_trans = Transaction.objects.get(pk=book_transaction_id)

                # Match them
                bank_trans.matched_transaction = book_trans
                bank_trans.is_reconciled = True
                bank_trans.reconciliation = reconciliation
                bank_trans.save()

                book_trans.is_cleared = True
                book_trans.cleared_date = reconciliation.reconciliation_date
                book_trans.status = 'RECONCILED'
                book_trans.save()

                # Create reconciliation item
                BankReconciliationItem.objects.create(
                    reconciliation=reconciliation,
                    item_type='DEPOSIT_IN_TRANSIT' if bank_trans.transaction_type == 'DEPOSIT' else 'OUTSTANDING_CHECK',
                    transaction_date=bank_trans.transaction_date,
                    description=bank_trans.description,
                    amount=bank_trans.amount,
                    book_transaction=book_trans,
                    is_matched=True
                )

            messages.success(request, _('Transactions matched successfully.'))
        except Exception as e:
            messages.error(request, str(e))

    return redirect('finance:bank_reconciliation_detail', pk=pk)


@login_required
@permission_required('finance.change_bankreconciliation', raise_exception=True)
@require_http_methods(['POST'])
def bank_reconciliation_complete(request, pk):
    """Complete bank reconciliation"""
    reconciliation = get_object_or_404(BankReconciliation, pk=pk)

    try:
        with db_transaction.atomic():
            reconciliation.calculate_balance()
            reconciliation.complete()

        messages.success(request, _('Reconciliation completed successfully.'))
    except Exception as e:
        messages.error(request, str(e))

    return redirect('finance:bank_reconciliation_detail', pk=pk)


# ============================================
# BUDGETING
# ============================================

@login_required
@permission_required('finance.view_budget', raise_exception=True)
def budget_list(request):
    """List budgets"""
    fiscal_year = request.GET.get('fiscal_year')
    status = request.GET.get('status')

    budgets = Budget.objects.select_related(
        'fiscal_year', 'created_by'
    )

    if fiscal_year:
        budgets = budgets.filter(fiscal_year_id=fiscal_year)
    if status:
        budgets = budgets.filter(status=status)

    budgets = budgets.order_by('-fiscal_year', 'name')

    fiscal_years = FiscalYear.objects.all()

    context = {
        'budgets': budgets,
        'fiscal_years': fiscal_years,
    }
    return render(request, 'finance/budget/list.html', context)


@login_required
@permission_required('finance.view_budget', raise_exception=True)
def budget_detail(request, pk):
    """Budget detail with variance analysis"""
    budget = get_object_or_404(
        Budget.objects.select_related('fiscal_year'),
        pk=pk
    )

    # Dimension filter
    dimension_filter = request.GET.get('dimension')

    lines = budget.lines.select_related(
        'account', 'currency'
    ).prefetch_related('dimension_values__dimension')

    if dimension_filter:
        lines = lines.filter(dimension_values__id=dimension_filter)

    lines = lines.order_by('account__code')

    # Calculate actuals and variances
    for line in lines:
        line.actual = line.get_actual_spending()
        line.variance = line.get_variance()
        line.utilization = line.get_utilization_percentage()
        line.is_over_budget = line.variance < 0

    # Summary
    total_budget = sum(line.amount for line in lines)
    total_actual = sum(line.actual for line in lines)
    total_variance = total_budget - total_actual

    dimensions = Dimension.objects.filter(is_active=True)

    context = {
        'budget': budget,
        'lines': lines,
        'total_budget': total_budget,
        'total_actual': total_actual,
        'total_variance': total_variance,
        'total_utilization': budget.get_utilization(),
        'dimensions': dimensions,
    }
    return render(request, 'finance/budget/detail.html', context)


@login_required
@permission_required('finance.change_budget', raise_exception=True)
@require_http_methods(['POST'])
def budget_approve(request, pk):
    """Approve budget"""
    budget = get_object_or_404(Budget, pk=pk)

    try:
        budget.approve(request.user)
        messages.success(request, _('Budget approved successfully.'))
    except Exception as e:
        messages.error(request, str(e))

    return redirect('finance:budget_detail', pk=pk)


@login_required
@permission_required('finance.change_budget', raise_exception=True)
@require_http_methods(['POST'])
def budget_activate(request, pk):
    """Activate budget"""
    budget = get_object_or_404(Budget, pk=pk)

    try:
        budget.activate(request.user)
        messages.success(request, _('Budget activated successfully.'))
    except Exception as e:
        messages.error(request, str(e))

    return redirect('finance:budget_detail', pk=pk)


# ============================================
# FIXED ASSETS
# ============================================

@login_required
@permission_required('finance.view_fixedasset', raise_exception=True)
def fixed_asset_list(request):
    """List fixed assets"""
    status = request.GET.get('status')
    category = request.GET.get('category')

    assets = FixedAsset.objects.select_related(
        'category', 'currency', 'assigned_to'
    )

    if status:
        assets = assets.filter(status=status)
    if category:
        assets = assets.filter(category_id=category)

    assets = assets.order_by('asset_number')

    categories = AssetCategory.objects.filter(is_active=True)

    context = {
        'assets': assets,
        'categories': categories,
        'status_choices': FixedAsset.STATUS_CHOICES,
    }
    return render(request, 'finance/fixed_asset/list.html', context)


@login_required
@permission_required('finance.view_fixedasset', raise_exception=True)
def fixed_asset_detail(request, pk):
    """Fixed asset detail with depreciation schedule"""
    asset = get_object_or_404(
        FixedAsset.objects.select_related('category', 'currency'),
        pk=pk
    )

    # Get depreciation records
    depreciation_records = asset.depreciation_records.select_related(
        'fiscal_period', 'journal_entry'
    ).order_by('-fiscal_period__start_date')

    context = {
        'asset': asset,
        'depreciation_records': depreciation_records,
    }
    return render(request, 'finance/fixed_asset/detail.html', context)


@login_required
@permission_required('finance.change_fixedasset', raise_exception=True)
@require_http_methods(['POST'])
def fixed_asset_depreciate(request, pk):
    """Calculate and record depreciation"""
    asset = get_object_or_404(FixedAsset, pk=pk)
    fiscal_period_id = request.POST.get('fiscal_period_id')

    if not fiscal_period_id:
        messages.error(request, _('Please select a fiscal period.'))
        return redirect('finance:fixed_asset_detail', pk=pk)

    fiscal_period = get_object_or_404(FiscalPeriod, pk=fiscal_period_id)

    try:
        with db_transaction.atomic():
            amount = asset.calculate_depreciation(fiscal_period.end_date)
            depreciation = asset.record_depreciation(
                amount=amount,
                for_period=fiscal_period,
                user=request.user
            )

        messages.success(request, _(f'Depreciation of {amount} recorded successfully.'))
    except Exception as e:
        messages.error(request, str(e))

    return redirect('finance:fixed_asset_detail', pk=pk)


# ============================================
# MISSING VIEWS - CURRENCY MANAGEMENT
# ============================================

@login_required
@permission_required('finance.add_currency', raise_exception=True)
def currency_create(request):
    """Create new currency"""
    if request.method == 'POST':
        form = CurrencyForm(request.POST)
        if form.is_valid():
            currency = form.save()
            messages.success(request, _('Currency created successfully.'))
            return redirect('finance:currency_list')
    else:
        form = CurrencyForm()

    context = {'form': form}
    return render(request, 'finance/currency/form.html', context)


@login_required
@permission_required('finance.change_currency', raise_exception=True)
def currency_update(request, pk):
    """Update currency"""
    currency = get_object_or_404(Currency, pk=pk)

    if request.method == 'POST':
        form = CurrencyForm(request.POST, instance=currency)
        if form.is_valid():
            form.save()
            messages.success(request, _('Currency updated successfully.'))
            return redirect('finance:currency_list')
    else:
        form = CurrencyForm(instance=currency)

    context = {'form': form, 'currency': currency}
    return render(request, 'finance/currency/form.html', context)


@login_required
@permission_required('finance.add_exchangerate', raise_exception=True)
def exchange_rate_create(request):
    """Create new exchange rate"""
    if request.method == 'POST':
        form = ExchangeRateForm(request.POST)
        if form.is_valid():
            exchange_rate = form.save(commit=False)
            exchange_rate.created_by = request.user
            exchange_rate.save()
            messages.success(request, _('Exchange rate created successfully.'))
            return redirect('finance:exchange_rate_list')
    else:
        form = ExchangeRateForm()

    context = {'form': form}
    return render(request, 'finance/currency/exchange_rate_form.html', context)


# ============================================
# MISSING VIEWS - DIMENSIONS
# ============================================

@login_required
@permission_required('finance.add_dimension', raise_exception=True)
def dimension_create(request):
    """Create new dimension"""
    if request.method == 'POST':
        form = DimensionForm(request.POST)
        if form.is_valid():
            dimension = form.save(commit=False)
            dimension.created_by = request.user
            dimension.save()
            messages.success(request, _('Dimension created successfully.'))
            return redirect('finance:dimension_detail', pk=dimension.pk)
    else:
        form = DimensionForm()

    context = {'form': form}
    return render(request, 'finance/dimensions/form.html', context)


@login_required
@permission_required('finance.change_dimension', raise_exception=True)
def dimension_update(request, pk):
    """Update dimension"""
    dimension = get_object_or_404(Dimension, pk=pk)

    if request.method == 'POST':
        form = DimensionForm(request.POST, instance=dimension)
        if form.is_valid():
            form.save()
            messages.success(request, _('Dimension updated successfully.'))
            return redirect('finance:dimension_detail', pk=dimension.pk)
    else:
        form = DimensionForm(instance=dimension)

    context = {'form': form, 'dimension': dimension}
    return render(request, 'finance/dimensions/form.html', context)


@login_required
@permission_required('finance.add_dimensionvalue', raise_exception=True)
def dimension_value_create(request, dimension_pk):
    """Create new dimension value"""
    dimension = get_object_or_404(Dimension, pk=dimension_pk)

    if request.method == 'POST':
        form = DimensionValueForm(request.POST)
        if form.is_valid():
            dimension_value = form.save(commit=False)
            dimension_value.dimension = dimension
            dimension_value.save()
            messages.success(request, _('Dimension value created successfully.'))
            return redirect('finance:dimension_detail', pk=dimension.pk)
    else:
        form = DimensionValueForm(initial={'dimension': dimension})

    context = {'form': form, 'dimension': dimension}
    return render(request, 'finance/dimensions/value_form.html', context)


# ============================================
# MISSING VIEWS - FISCAL YEAR
# ============================================

@login_required
@permission_required('finance.add_fiscalyear', raise_exception=True)
def fiscal_year_create(request):
    """Create new fiscal year"""
    if request.method == 'POST':
        # Using FiscalYear model directly since we don't have a form
        name = request.POST.get('name')
        code = request.POST.get('code')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        period_type = request.POST.get('period_type', 'MONTHLY')

        try:
            fiscal_year = FiscalYear.objects.create(
                name=name,
                code=code,
                start_date=start_date,
                end_date=end_date,
                period_type=period_type,
                created_by=request.user
            )
            messages.success(request, _('Fiscal year created successfully.'))
            return redirect('finance:fiscal_year_detail', pk=fiscal_year.pk)
        except Exception as e:
            messages.error(request, str(e))
    else:
        # Set default dates (current year)
        today = timezone.now().date()
        start_date = today.replace(month=1, day=1)
        end_date = today.replace(month=12, day=31)

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'period_types': FiscalYear._meta.get_field('period_type').choices,
    }
    return render(request, 'finance/fiscal_year/form.html', context)


@login_required
@permission_required('finance.change_fiscalyear', raise_exception=True)
@require_http_methods(['POST'])
def fiscal_year_close(request, pk):
    """Close fiscal year"""
    fiscal_year = get_object_or_404(FiscalYear, pk=pk)

    try:
        with db_transaction.atomic():
            fiscal_year.close_year(request.user)
        messages.success(request, _('Fiscal year closed successfully.'))
    except Exception as e:
        messages.error(request, str(e))

    return redirect('finance:fiscal_year_detail', pk=pk)


# ============================================
# MISSING VIEWS - JOURNALS
# ============================================

@login_required
@permission_required('finance.view_journal', raise_exception=True)
def journal_list(request):
    """List journals"""
    journals = Journal.objects.filter(is_active=True).order_by('code')
    context = {'journals': journals}
    return render(request, 'finance/journal/list.html', context)


@login_required
@permission_required('finance.add_journal', raise_exception=True)
def journal_create(request):
    """Create new journal"""
    if request.method == 'POST':
        # Using Journal model directly
        code = request.POST.get('code')
        name = request.POST.get('name')
        journal_type = request.POST.get('journal_type')
        prefix = request.POST.get('prefix', '')

        try:
            journal = Journal.objects.create(
                code=code,
                name=name,
                journal_type=journal_type,
                prefix=prefix,
                created_by=request.user
            )
            messages.success(request, _('Journal created successfully.'))
            return redirect('finance:journal_list')
        except Exception as e:
            messages.error(request, str(e))

    context = {
        'journal_types': JournalType.choices,
    }
    return render(request, 'finance/journal/form.html', context)


# ============================================
# MISSING VIEWS - RECURRING JOURNAL ENTRIES
# ============================================

@login_required
@permission_required('finance.add_recurringjournalentry', raise_exception=True)
def recurring_entry_create(request):
    """Create new recurring journal entry"""
    if request.method == 'POST':
        form = RecurringJournalEntryForm(request.POST)
        if form.is_valid():
            recurring = form.save(commit=False)
            recurring.created_by = request.user

            # Set next run date to start date if not provided
            if not recurring.next_run_date:
                recurring.next_run_date = recurring.start_date

            recurring.save()
            messages.success(request, _('Recurring entry created successfully.'))
            return redirect('finance:recurring_entry_list')
    else:
        form = RecurringJournalEntryForm()

    context = {'form': form}
    return render(request, 'finance/recurring_entry/form.html', context)


@login_required
@permission_required('finance.change_recurringjournalentry', raise_exception=True)
def recurring_entry_update(request, pk):
    """Update recurring journal entry"""
    recurring = get_object_or_404(RecurringJournalEntry, pk=pk)

    if request.method == 'POST':
        form = RecurringJournalEntryForm(request.POST, instance=recurring)
        if form.is_valid():
            form.save()
            messages.success(request, _('Recurring entry updated successfully.'))
            return redirect('finance:recurring_entry_list')
    else:
        form = RecurringJournalEntryForm(instance=recurring)

    context = {'form': form, 'recurring': recurring}
    return render(request, 'finance/recurring_entry/form.html', context)


# ============================================
# MISSING VIEWS - BANK ACCOUNTS
# ============================================

@login_required
@permission_required('finance.add_bankaccount', raise_exception=True)
def bank_account_create(request):
    """Create new bank account"""
    if request.method == 'POST':
        form = BankAccountForm(request.POST)
        if form.is_valid():
            bank_account = form.save()
            messages.success(request, _('Bank account created successfully.'))
            return redirect('finance:bank_account_detail', pk=bank_account.pk)
    else:
        form = BankAccountForm()

    context = {'form': form}
    return render(request, 'finance/bank_account/form.html', context)


@login_required
@permission_required('finance.change_bankaccount', raise_exception=True)
def bank_account_update(request, pk):
    """Update bank account"""
    bank_account = get_object_or_404(BankAccount, pk=pk)

    if request.method == 'POST':
        form = BankAccountForm(request.POST, instance=bank_account)
        if form.is_valid():
            form.save()
            messages.success(request, _('Bank account updated successfully.'))
            return redirect('finance:bank_account_detail', pk=bank_account.pk)
    else:
        form = BankAccountForm(instance=bank_account)

    context = {'form': form, 'bank_account': bank_account}
    return render(request, 'finance/bank_account/form.html', context)


# ============================================
# MISSING VIEWS - TRANSACTIONS
# ============================================

@login_required
@permission_required('finance.view_transaction', raise_exception=True)
def transaction_list(request):
    """List transactions"""
    bank_account = request.GET.get('bank_account')
    transaction_type = request.GET.get('transaction_type')
    status = request.GET.get('status')
    date_from = request.GET.get('date_from')
    date_to = request.GET.get('date_to')

    transactions = Transaction.objects.select_related(
        'bank_account', 'currency', 'created_by'
    )

    if bank_account:
        transactions = transactions.filter(bank_account_id=bank_account)
    if transaction_type:
        transactions = transactions.filter(transaction_type=transaction_type)
    if status:
        transactions = transactions.filter(status=status)
    if date_from:
        transactions = transactions.filter(transaction_date__gte=date_from)
    if date_to:
        transactions = transactions.filter(transaction_date__lte=date_to)

    transactions = transactions.order_by('-transaction_date')[:100]

    bank_accounts = BankAccount.objects.filter(is_active=True)

    context = {
        'transactions': transactions,
        'bank_accounts': bank_accounts,
        'transaction_types': Transaction.TRANSACTION_TYPES,
        'status_choices': Transaction.STATUS_CHOICES,
    }
    return render(request, 'finance/transaction/list.html', context)


@login_required
@permission_required('finance.view_transaction', raise_exception=True)
def transaction_detail(request, pk):
    """Transaction detail"""
    transaction = get_object_or_404(
        Transaction.objects.select_related(
            'bank_account', 'currency', 'created_by', 'journal_entry'
        ),
        pk=pk
    )

    context = {'transaction': transaction}
    return render(request, 'finance/transaction/detail.html', context)


@login_required
@permission_required('finance.change_transaction', raise_exception=True)
def transaction_update(request, pk):
    """Update transaction"""
    transaction = get_object_or_404(Transaction, pk=pk)

    if request.method == 'POST':
        form = TransactionForm(request.POST, instance=transaction)
        if form.is_valid():
            form.save()

            # Update bank balance
            transaction.bank_account.update_balance()

            messages.success(request, _('Transaction updated successfully.'))
            return redirect('finance:transaction_detail', pk=transaction.pk)
    else:
        form = TransactionForm(instance=transaction)

    context = {'form': form, 'transaction': transaction}
    return render(request, 'finance/transaction/form.html', context)


@login_required
@permission_required('finance.change_transaction', raise_exception=True)
@require_http_methods(['POST'])
def transaction_clear(request, pk):
    """Clear transaction"""
    transaction = get_object_or_404(Transaction, pk=pk)

    try:
        transaction.is_cleared = True
        transaction.cleared_date = timezone.now().date()
        transaction.status = 'CLEARED'
        transaction.save()

        messages.success(request, _('Transaction cleared successfully.'))
    except Exception as e:
        messages.error(request, str(e))

    return redirect('finance:transaction_detail', pk=pk)


# ============================================
# MISSING VIEWS - BUDGETS
# ============================================

@login_required
@permission_required('finance.add_budget', raise_exception=True)
def budget_create(request):
    """Create new budget"""
    if request.method == 'POST':
        form = BudgetForm(request.POST)
        if form.is_valid():
            budget = form.save(commit=False)
            budget.created_by = request.user
            budget.save()
            messages.success(request, _('Budget created successfully.'))
            return redirect('finance:budget_detail', pk=budget.pk)
    else:
        form = BudgetForm()

    context = {'form': form}
    return render(request, 'finance/budget/form.html', context)


@login_required
@permission_required('finance.change_budget', raise_exception=True)
def budget_update(request, pk):
    """Update budget"""
    budget = get_object_or_404(Budget, pk=pk)

    if request.method == 'POST':
        form = BudgetForm(request.POST, instance=budget)
        if form.is_valid():
            form.save()
            messages.success(request, _('Budget updated successfully.'))
            return redirect('finance:budget_detail', pk=budget.pk)
    else:
        form = BudgetForm(instance=budget)

    context = {'form': form, 'budget': budget}
    return render(request, 'finance/budget/form.html', context)


# ============================================
# MISSING VIEWS - FIXED ASSETS
# ============================================

@login_required
@permission_required('finance.add_fixedasset', raise_exception=True)
def fixed_asset_create(request):
    """Create new fixed asset"""
    if request.method == 'POST':
        form = FixedAssetForm(request.POST)
        if form.is_valid():
            asset = form.save(commit=False)
            asset.created_by = request.user
            asset.save()
            form.save_m2m()  # Save many-to-many relationships
            messages.success(request, _('Fixed asset created successfully.'))
            return redirect('finance:fixed_asset_detail', pk=asset.pk)
    else:
        form = FixedAssetForm()

    context = {'form': form}
    return render(request, 'finance/fixed_asset/form.html', context)


@login_required
@permission_required('finance.change_fixedasset', raise_exception=True)
def fixed_asset_update(request, pk):
    """Update fixed asset"""
    asset = get_object_or_404(FixedAsset, pk=pk)

    if request.method == 'POST':
        form = FixedAssetForm(request.POST, instance=asset)
        if form.is_valid():
            form.save()
            messages.success(request, _('Fixed asset updated successfully.'))
            return redirect('finance:fixed_asset_detail', pk=asset.pk)
    else:
        form = FixedAssetForm(instance=asset)

    context = {'form': form, 'asset': asset}
    return render(request, 'finance/fixed_asset/form.html', context)


# ============================================
# MISSING VIEWS - TAX CODES
# ============================================

@login_required
@permission_required('finance.add_taxcode', raise_exception=True)
def tax_code_create(request):
    """Create new tax code"""
    if request.method == 'POST':
        form = TaxCodeForm(request.POST)
        if form.is_valid():
            tax_code = form.save()
            messages.success(request, _('Tax code created successfully.'))
            return redirect('finance:tax_code_list')
    else:
        form = TaxCodeForm()

    context = {'form': form}
    return render(request, 'finance/tax/form.html', context)


@login_required
@permission_required('finance.change_taxcode', raise_exception=True)
def tax_code_update(request, pk):
    """Update tax code"""
    tax_code = get_object_or_404(TaxCode, pk=pk)

    if request.method == 'POST':
        form = TaxCodeForm(request.POST, instance=tax_code)
        if form.is_valid():
            form.save()
            messages.success(request, _('Tax code updated successfully.'))
            return redirect('finance:tax_code_list')
    else:
        form = TaxCodeForm(instance=tax_code)

    context = {'form': form, 'tax_code': tax_code}
    return render(request, 'finance/tax/form.html', context)


# ============================================
# MISSING VIEWS - FINANCIAL REPORTS
# ============================================

@login_required
@permission_required('finance.view_financialreport', raise_exception=True)
def generate_cash_flow(request):
    """Generate cash flow statement"""
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not start_date or not end_date:
        today = timezone.now().date()
        start_date = today.replace(day=1)
        end_date = today

    if request.method == 'POST':
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')

        task = generate_financial_report_task.delay(
            report_type='CASH_FLOW',
            start_date=start_date,
            end_date=end_date,
            user_id=request.user.id
        )

        messages.success(request, _('Cash flow statement is being generated.'))
        return redirect('finance:financial_reports_dashboard')

    # Simplified cash flow calculation
    # Operating Activities
    operating_cash = JournalEntryLine.objects.filter(
        account__account_type__in=[AccountType.REVENUE, AccountType.EXPENSE],
        journal_entry__status='POSTED',
        journal_entry__posting_date__range=[start_date, end_date]
    ).aggregate(
        total=Sum('debit_amount_base') - Sum('credit_amount_base')
    )['total'] or Decimal('0')

    # Investing Activities (fixed assets)
    investing_cash = JournalEntryLine.objects.filter(
        account__account_type=AccountType.ASSET,
        journal_entry__status='POSTED',
        journal_entry__posting_date__range=[start_date, end_date],
        account__name__icontains='asset'  # Simplified
    ).aggregate(
        total=Sum('debit_amount_base') - Sum('credit_amount_base')
    )['total'] or Decimal('0')

    # Financing Activities (loans, equity)
    financing_cash = JournalEntryLine.objects.filter(
        account__account_type__in=[AccountType.LIABILITY, AccountType.EQUITY],
        journal_entry__status='POSTED',
        journal_entry__posting_date__range=[start_date, end_date]
    ).aggregate(
        total=Sum('credit_amount_base') - Sum('debit_amount_base')
    )['total'] or Decimal('0')

    net_cash_flow = operating_cash + investing_cash + financing_cash

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'operating_cash': operating_cash,
        'investing_cash': investing_cash,
        'financing_cash': financing_cash,
        'net_cash_flow': net_cash_flow,
    }

    return render(request, 'finance/reports/cash_flow.html', context)


# ============================================
# MISSING VIEWS - EXPORTS
# ============================================

@login_required
@permission_required('finance.view_financialreport', raise_exception=True)
def export_general_ledger(request):
    """Export general ledger to CSV"""
    account_id = request.GET.get('account')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not account_id:
        messages.error(request, _('Please select an account.'))
        return redirect('finance:general_ledger')

    account = get_object_or_404(ChartOfAccounts, pk=account_id)

    response = HttpResponse(content_type='text/csv')
    response[
        'Content-Disposition'] = f'attachment; filename="general_ledger_{account.code}_{start_date}_to_{end_date}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Date', 'Entry Number', 'Description', 'Debit', 'Credit', 'Balance'])

    # Get ledger entries
    entries = JournalEntryLine.objects.filter(
        account=account,
        journal_entry__status='POSTED'
    ).select_related('journal_entry')

    if start_date:
        entries = entries.filter(journal_entry__posting_date__gte=start_date)
    if end_date:
        entries = entries.filter(journal_entry__posting_date__lte=end_date)

    entries = entries.order_by('journal_entry__posting_date', 'id')

    running_balance = Decimal('0')

    # Opening balance
    if start_date:
        opening_balance = account.get_balance(start_date)
        running_balance = opening_balance
        writer.writerow(['', 'OPENING BALANCE', '', '', '', opening_balance])

    for line in entries:
        if account.is_debit_account:
            running_balance += line.debit_amount - line.credit_amount
        else:
            running_balance += line.credit_amount - line.debit_amount

        writer.writerow([
            line.journal_entry.posting_date,
            line.journal_entry.entry_number,
            line.description,
            line.debit_amount,
            line.credit_amount,
            running_balance
        ])

    return response


# ============================================
# MISSING VIEWS - AJAX/API ENDPOINTS
# ============================================

@login_required
@require_http_methods(['GET'])
def ajax_get_account_balance(request, account_id):
    """Get account balance for AJAX requests"""
    account = get_object_or_404(ChartOfAccounts, pk=account_id)
    as_of_date = request.GET.get('as_of_date')

    balance = account.get_balance(as_of_date=as_of_date)

    return JsonResponse({
        'account_code': account.code,
        'account_name': account.name,
        'balance': float(balance),
        'currency': account.currency.code
    })


@login_required
@require_http_methods(['GET'])
def ajax_get_exchange_rate(request):
    """Get exchange rate for AJAX requests"""
    from_currency_id = request.GET.get('from_currency')
    to_currency_id = request.GET.get('to_currency')
    rate_date = request.GET.get('rate_date', timezone.now().date())

    from_currency = get_object_or_404(Currency, pk=from_currency_id)
    to_currency = get_object_or_404(Currency, pk=to_currency_id)

    try:
        rate = ExchangeRate.get_rate(from_currency, to_currency, rate_date)
        return JsonResponse({'rate': float(rate)})
    except ValidationError as e:
        return JsonResponse({'error': str(e)}, status=400)


@login_required
@require_http_methods(['GET'])
def ajax_get_fiscal_periods(request, fiscal_year_id):
    """Get fiscal periods for AJAX requests"""
    fiscal_year = get_object_or_404(FiscalYear, pk=fiscal_year_id)
    periods = fiscal_year.periods.filter(status='OPEN').values('id', 'name', 'code')

    return JsonResponse(list(periods), safe=False)


# ============================================
# MISSING VIEWS - BULK OPERATIONS
# ============================================

@login_required
@permission_required('finance.add_journalentry', raise_exception=True)
def journal_entry_bulk_create(request):
    """Bulk create journal entries from CSV"""
    if request.method == 'POST' and request.FILES.get('csv_file'):
        csv_file = request.FILES['csv_file']
        journal_id = request.POST.get('journal')

        try:
            journal = Journal.objects.get(pk=journal_id)
            decoded_file = csv_file.read().decode('utf-8').splitlines()
            reader = csv.DictReader(decoded_file)

            created_count = 0
            errors = []

            for row_num, row in enumerate(reader, 2):  # Start from 2 (header is row 1)
                try:
                    with db_transaction.atomic():
                        # Create journal entry
                        entry = JournalEntry.objects.create(
                            journal=journal,
                            entry_number=journal.get_next_entry_number(),
                            entry_date=row.get('entry_date', timezone.now().date()),
                            description=row.get('description', ''),
                            currency=get_base_currency(),
                            created_by=request.user
                        )

                        # Create lines (simplified - you might want more complex parsing)
                        # This is a basic implementation
                        JournalEntryLine.objects.create(
                            journal_entry=entry,
                            account_id=row.get('account_id'),
                            description=row.get('line_description', ''),
                            debit_amount=Decimal(row.get('debit', 0)),
                            credit_amount=Decimal(row.get('credit', 0)),
                            currency=get_base_currency()
                        )

                        entry.calculate_totals()
                        created_count += 1

                except Exception as e:
                    errors.append(f"Row {row_num}: {str(e)}")

            if errors:
                messages.warning(request, _('Created %(count)d entries with %(error_count)d errors.') % {
                    'count': created_count, 'error_count': len(errors)
                })
                # You might want to show errors in a better way
            else:
                messages.success(request, _(f'Successfully created {created_count} journal entries.'))

        except Exception as e:
            messages.error(request, str(e))

    journals = Journal.objects.filter(is_active=True)
    context = {'journals': journals}
    return render(request, 'finance/journal_entry/bulk_create.html', context)

