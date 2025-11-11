from django.views.decorators.http import require_http_methods
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.utils.translation import gettext_lazy as _
from django.db.models import Q, Sum
from decimal import Decimal
from django.utils import timezone
from datetime import datetime
import csv
import json

from .models import (
    FinancialReport, BankReconciliation, BankTransaction,
    ChartOfAccounts, AccountType, FiscalYear, FiscalPeriod,Transaction,
    JournalEntry, JournalEntryLine, FixedAsset, TaxCode,
)
from .tasks import (
    generate_financial_report_task,
    _generate_trial_balance_data,
    export_general_ledger_task
)
from .forms import BankReconciliationForm


# ============================================
# FINANCIAL REPORTS - MISSING VIEWS
# ============================================

@login_required
@permission_required('finance.view_financialreport', raise_exception=True)
def financial_reports_dashboard(request):
    """Financial reports dashboard with all report options"""
    current_year = FiscalYear.objects.filter(is_current=True).first()

    # Get recent reports
    recent_reports = FinancialReport.objects.filter(
        generated_by=request.user
    ).order_by('-generated_at')[:10]

    context = {
        'report_types': FinancialReport.REPORT_TYPES,
        'fiscal_years': FiscalYear.objects.all().order_by('-start_date'),
        'current_year': current_year,
        'recent_reports': recent_reports,
    }
    return render(request, 'finance/reports/dashboard.html', context)


@login_required
@permission_required('finance.view_financialreport', raise_exception=True)
def generate_balance_sheet(request):
    """Generate balance sheet report"""
    as_of_date = request.GET.get('as_of_date', timezone.now().date())
    fiscal_period_id = request.GET.get('fiscal_period')

    if request.method == 'POST':
        as_of_date = request.POST.get('as_of_date')
        fiscal_period_id = request.POST.get('fiscal_period')

        # Generate the report
        try:
            if fiscal_period_id:
                fiscal_period = get_object_or_404(FiscalPeriod, pk=fiscal_period_id)
                as_of_date = fiscal_period.end_date

            # Get all asset accounts with balances
            assets = ChartOfAccounts.objects.filter(
                account_type=AccountType.ASSET,
                is_active=True,
                is_header=False
            ).order_by('code')

            # Get all liability accounts with balances
            liabilities = ChartOfAccounts.objects.filter(
                account_type=AccountType.LIABILITY,
                is_active=True,
                is_header=False
            ).order_by('code')

            # Get all equity accounts with balances
            equity = ChartOfAccounts.objects.filter(
                account_type=AccountType.EQUITY,
                is_active=True,
                is_header=False
            ).order_by('code')

            # Calculate totals
            total_assets = Decimal('0.00')
            asset_details = []

            for asset in assets:
                balance = asset.get_balance(as_of_date=as_of_date)
                if balance != 0:
                    asset_details.append({
                        'account': asset,
                        'balance': balance
                    })
                    total_assets += balance

            total_liabilities = Decimal('0.00')
            liability_details = []

            for liability in liabilities:
                balance = liability.get_balance(as_of_date=as_of_date)
                if balance != 0:
                    liability_details.append({
                        'account': liability,
                        'balance': balance
                    })
                    total_liabilities += balance

            total_equity = Decimal('0.00')
            equity_details = []

            for eq in equity:
                balance = eq.get_balance(as_of_date=as_of_date)
                if balance != 0:
                    equity_details.append({
                        'account': eq,
                        'balance': balance
                    })
                    total_equity += balance

            # Calculate retained earnings (simplified)
            current_year = FiscalYear.objects.filter(is_current=True).first()
            retained_earnings = Decimal('0.00')

            if current_year:
                # Get net income for the year
                revenue_total = JournalEntryLine.objects.filter(
                    account__account_type=AccountType.REVENUE,
                    journal_entry__status='POSTED',
                    journal_entry__fiscal_year=current_year,
                    journal_entry__posting_date__lte=as_of_date
                ).aggregate(
                    total=Sum('credit_amount_base') - Sum('debit_amount_base')
                )['total'] or Decimal('0.00')

                expense_total = JournalEntryLine.objects.filter(
                    account__account_type=AccountType.EXPENSE,
                    journal_entry__status='POSTED',
                    journal_entry__fiscal_year=current_year,
                    journal_entry__posting_date__lte=as_of_date
                ).aggregate(
                    total=Sum('debit_amount_base') - Sum('credit_amount_base')
                )['total'] or Decimal('0.00')

                retained_earnings = revenue_total - expense_total

            total_equity += retained_earnings

            context = {
                'as_of_date': as_of_date,
                'asset_details': asset_details,
                'liability_details': liability_details,
                'equity_details': equity_details,
                'total_assets': total_assets,
                'total_liabilities': total_liabilities,
                'total_equity': total_equity,
                'retained_earnings': retained_earnings,
                'is_balanced': abs(total_assets - (total_liabilities + total_equity)) < Decimal('0.01'),
            }

            return render(request, 'finance/reports/balance_sheet.html', context)

        except Exception as e:
            messages.error(request, f'Error generating balance sheet: {str(e)}')

    # GET request - show form
    fiscal_periods = FiscalPeriod.objects.filter(
        status='OPEN'
    ).select_related('fiscal_year').order_by('-start_date')

    context = {
        'as_of_date': as_of_date,
        'fiscal_periods': fiscal_periods,
    }
    return render(request, 'finance/reports/balance_sheet_form.html', context)


@login_required
@permission_required('finance.view_financialreport', raise_exception=True)
def generate_income_statement(request):
    """Generate income statement (Profit & Loss) report"""
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    fiscal_period_id = request.GET.get('fiscal_period')

    if request.method == 'POST':
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        fiscal_period_id = request.POST.get('fiscal_period')

        try:
            if fiscal_period_id:
                fiscal_period = get_object_or_404(FiscalPeriod, pk=fiscal_period_id)
                start_date = fiscal_period.start_date
                end_date = fiscal_period.end_date

            # Revenue accounts
            revenue_accounts = ChartOfAccounts.objects.filter(
                account_type=AccountType.REVENUE,
                is_active=True,
                is_header=False
            ).order_by('code')

            # Cost of Goods Sold accounts
            cogs_accounts = ChartOfAccounts.objects.filter(
                account_type=AccountType.COST_OF_SALES,
                is_active=True,
                is_header=False
            ).order_by('code')

            # Expense accounts
            expense_accounts = ChartOfAccounts.objects.filter(
                account_type=AccountType.EXPENSE,
                is_active=True,
                is_header=False
            ).order_by('code')

            def get_period_activity(account, start, end):
                """Get account activity for period"""
                lines = JournalEntryLine.objects.filter(
                    account=account,
                    journal_entry__status='POSTED',
                    journal_entry__posting_date__range=[start, end]
                ).aggregate(
                    debit=Sum('debit_amount_base'),
                    credit=Sum('credit_amount_base')
                )

                debit = lines['debit'] or Decimal('0.00')
                credit = lines['credit'] or Decimal('0.00')

                if account.is_credit_account:  # Revenue accounts
                    return credit - debit
                else:  # Expense accounts
                    return debit - credit

            # Calculate totals
            revenue_details = []
            total_revenue = Decimal('0.00')

            for account in revenue_accounts:
                amount = get_period_activity(account, start_date, end_date)
                if amount != 0:
                    revenue_details.append({
                        'account': account,
                        'amount': amount
                    })
                    total_revenue += amount

            cogs_details = []
            total_cogs = Decimal('0.00')

            for account in cogs_accounts:
                amount = get_period_activity(account, start_date, end_date)
                if amount != 0:
                    cogs_details.append({
                        'account': account,
                        'amount': amount
                    })
                    total_cogs += amount

            expense_details = []
            total_expenses = Decimal('0.00')

            for account in expense_accounts:
                amount = get_period_activity(account, start_date, end_date)
                if amount != 0:
                    expense_details.append({
                        'account': account,
                        'amount': amount
                    })
                    total_expenses += amount

            # Calculate profits
            gross_profit = total_revenue - total_cogs
            operating_profit = gross_profit - total_expenses
            net_profit = operating_profit  # Simplified - no taxes/other income

            context = {
                'start_date': start_date,
                'end_date': end_date,
                'revenue_details': revenue_details,
                'cogs_details': cogs_details,
                'expense_details': expense_details,
                'total_revenue': total_revenue,
                'total_cogs': total_cogs,
                'total_expenses': total_expenses,
                'gross_profit': gross_profit,
                'operating_profit': operating_profit,
                'net_profit': net_profit,
            }

            return render(request, 'finance/reports/income_statement.html', context)

        except Exception as e:
            messages.error(request, f'Error generating income statement: {str(e)}')

    # GET request - show form
    fiscal_periods = FiscalPeriod.objects.filter(
        status='OPEN'
    ).select_related('fiscal_year').order_by('-start_date')

    # Default to current month
    today = timezone.now().date()
    if not start_date:
        start_date = today.replace(day=1)
    if not end_date:
        end_date = today

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'fiscal_periods': fiscal_periods,
    }
    return render(request, 'finance/reports/income_statement_form.html', context)


@login_required
@permission_required('finance.view_financialreport', raise_exception=True)
def generate_trial_balance(request):
    """Generate trial balance report"""
    as_of_date = request.GET.get('as_of_date', timezone.now().date())
    fiscal_period_id = request.GET.get('fiscal_period')

    if request.method == 'POST':
        as_of_date = request.POST.get('as_of_date')
        fiscal_period_id = request.POST.get('fiscal_period')

        try:
            if fiscal_period_id:
                fiscal_period = get_object_or_404(FiscalPeriod, pk=fiscal_period_id)
                as_of_date = fiscal_period.end_date

            # Get all active non-header accounts
            accounts = ChartOfAccounts.objects.filter(
                is_active=True,
                is_header=False
            ).order_by('code')

            trial_balance_data = []
            total_debit = Decimal('0.00')
            total_credit = Decimal('0.00')

            for account in accounts:
                balance = account.get_balance(as_of_date=as_of_date)

                if balance != 0:
                    if account.is_debit_account:
                        debit = balance if balance > 0 else Decimal('0.00')
                        credit = abs(balance) if balance < 0 else Decimal('0.00')
                    else:
                        credit = balance if balance > 0 else Decimal('0.00')
                        debit = abs(balance) if balance < 0 else Decimal('0.00')

                    trial_balance_data.append({
                        'account': account,
                        'debit': debit,
                        'credit': credit,
                    })

                    total_debit += debit
                    total_credit += credit

            context = {
                'as_of_date': as_of_date,
                'trial_balance_data': trial_balance_data,
                'total_debit': total_debit,
                'total_credit': total_credit,
                'is_balanced': abs(total_debit - total_credit) < Decimal('0.01'),
                'difference': total_debit - total_credit,
            }

            return render(request, 'finance/reports/trial_balance.html', context)

        except Exception as e:
            messages.error(request, f'Error generating trial balance: {str(e)}')

    # GET request - show form
    fiscal_periods = FiscalPeriod.objects.filter(
        status='OPEN'
    ).select_related('fiscal_year').order_by('-start_date')

    context = {
        'as_of_date': as_of_date,
        'fiscal_periods': fiscal_periods,
    }
    return render(request, 'finance/reports/trial_balance_form.html', context)


@login_required
@permission_required('finance.view_financialreport', raise_exception=True)
def general_ledger(request):
    """Generate general ledger report for specific account"""
    account_id = request.GET.get('account')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    accounts = ChartOfAccounts.objects.filter(
        is_active=True,
        is_header=False
    ).order_by('code')

    ledger_entries = []
    opening_balance = Decimal('0.00')
    closing_balance = Decimal('0.00')

    if account_id:
        account = get_object_or_404(ChartOfAccounts, pk=account_id)

        # Calculate opening balance
        if start_date:
            opening_balance = account.get_balance(as_of_date=start_date)

        running_balance = opening_balance

        # Get journal entry lines for this account
        entries = JournalEntryLine.objects.filter(
            account=account,
            journal_entry__status='POSTED'
        ).select_related(
            'journal_entry',
            'journal_entry__journal',
            'currency'
        ).prefetch_related('dimension_values')

        if start_date:
            entries = entries.filter(journal_entry__posting_date__gte=start_date)
        if end_date:
            entries = entries.filter(journal_entry__posting_date__lte=end_date)

        entries = entries.order_by('journal_entry__posting_date', 'id')

        for line in entries:
            # Calculate running balance
            if account.is_debit_account:
                running_balance += line.debit_amount - line.credit_amount
            else:
                running_balance += line.credit_amount - line.debit_amount

            ledger_entries.append({
                'line': line,
                'running_balance': running_balance,
            })

        closing_balance = running_balance

        context = {
            'account': account,
            'accounts': accounts,
            'start_date': start_date,
            'end_date': end_date,
            'ledger_entries': ledger_entries,
            'opening_balance': opening_balance,
            'closing_balance': closing_balance,
        }
    else:
        context = {
            'accounts': accounts,
        }

    return render(request, 'finance/reports/general_ledger.html', context)


@login_required
@permission_required('finance.view_financialreport', raise_exception=True)
def generate_cash_flow(request):
    """Generate cash flow statement"""
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    fiscal_period_id = request.GET.get('fiscal_period')

    if request.method == 'POST':
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        fiscal_period_id = request.POST.get('fiscal_period')

        try:
            if fiscal_period_id:
                fiscal_period = get_object_or_404(FiscalPeriod, pk=fiscal_period_id)
                start_date = fiscal_period.start_date
                end_date = fiscal_period.end_date

            # Get cash accounts
            cash_accounts = ChartOfAccounts.objects.filter(
                account_type=AccountType.ASSET,
                name__icontains='cash',
                is_active=True
            )

            # Operating Activities (simplified - using net income approach)
            net_income = Decimal('0.00')

            # Revenue and expense activities
            operating_activities = JournalEntryLine.objects.filter(
                account__account_type__in=[AccountType.REVENUE, AccountType.EXPENSE],
                journal_entry__status='POSTED',
                journal_entry__posting_date__range=[start_date, end_date]
            ).aggregate(
                net=Sum('credit_amount_base') - Sum('debit_amount_base')
            )['net'] or Decimal('0.00')

            # Investing Activities (fixed asset purchases/sales)
            investing_activities = JournalEntryLine.objects.filter(
                account__name__icontains='asset',
                journal_entry__status='POSTED',
                journal_entry__posting_date__range=[start_date, end_date]
            ).aggregate(
                net=Sum('debit_amount_base') - Sum('credit_amount_base')
            )['net'] or Decimal('0.00')

            # Financing Activities (loans, equity)
            financing_activities = JournalEntryLine.objects.filter(
                account__account_type__in=[AccountType.LIABILITY, AccountType.EQUITY],
                journal_entry__status='POSTED',
                journal_entry__posting_date__range=[start_date, end_date]
            ).aggregate(
                net=Sum('credit_amount_base') - Sum('debit_amount_base')
            )['net'] or Decimal('0.00')

            net_cash_flow = operating_activities + investing_activities + financing_activities

            context = {
                'start_date': start_date,
                'end_date': end_date,
                'operating_activities': operating_activities,
                'investing_activities': investing_activities,
                'financing_activities': financing_activities,
                'net_cash_flow': net_cash_flow,
            }

            return render(request, 'finance/reports/cash_flow.html', context)

        except Exception as e:
            messages.error(request, f'Error generating cash flow statement: {str(e)}')

    # GET request - show form
    fiscal_periods = FiscalPeriod.objects.filter(
        status='OPEN'
    ).select_related('fiscal_year').order_by('-start_date')

    # Default to current month
    today = timezone.now().date()
    if not start_date:
        start_date = today.replace(day=1)
    if not end_date:
        end_date = today

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'fiscal_periods': fiscal_periods,
    }
    return render(request, 'finance/reports/cash_flow_form.html', context)


# ============================================
# TAX MANAGEMENT - MISSING VIEWS
# ============================================

@login_required
@permission_required('finance.view_taxcode', raise_exception=True)
def tax_code_list(request):
    """List all tax codes"""
    tax_codes = TaxCode.objects.filter(is_active=True).order_by('code')

    context = {
        'tax_codes': tax_codes,
    }
    return render(request, 'finance/tax/code_list.html', context)


@login_required
@permission_required('finance.view_taxcode', raise_exception=True)
def tax_report(request):
    """Generate tax report"""
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    tax_code_id = request.GET.get('tax_code')

    if not start_date or not end_date:
        # Default to current quarter
        today = timezone.now().date()
        start_date = today.replace(day=1)
        end_date = today

    tax_codes = TaxCode.objects.filter(is_active=True)
    selected_tax_code = None

    if tax_code_id:
        selected_tax_code = get_object_or_404(TaxCode, pk=tax_code_id)
        tax_codes = tax_codes.filter(pk=tax_code_id)

    tax_summary = []

    for tax_code in tax_codes:
        # Calculate tax collected (sales tax/VAT collected)
        tax_collected = JournalEntryLine.objects.filter(
            account=tax_code.tax_collected_account,
            journal_entry__status='POSTED',
            journal_entry__posting_date__range=[start_date, end_date]
        ).aggregate(
            total=Sum('credit_amount_base') - Sum('debit_amount_base')
        )['total'] or Decimal('0.00')

        # Calculate tax paid (input tax/VAT paid)
        tax_paid = JournalEntryLine.objects.filter(
            account=tax_code.tax_paid_account,
            journal_entry__status='POSTED',
            journal_entry__posting_date__range=[start_date, end_date]
        ).aggregate(
            total=Sum('debit_amount_base') - Sum('credit_amount_base')
        )['total'] or Decimal('0.00')

        net_tax = tax_collected - tax_paid

        tax_summary.append({
            'tax_code': tax_code,
            'collected': tax_collected,
            'paid': tax_paid,
            'net': net_tax,
        })

    context = {
        'start_date': start_date,
        'end_date': end_date,
        'tax_summary': tax_summary,
        'selected_tax_code': selected_tax_code,
        'all_tax_codes': TaxCode.objects.filter(is_active=True),
    }

    return render(request, 'finance/tax/report.html', context)


# ============================================
# EXPORT FUNCTIONS - MISSING VIEWS
# ============================================

@login_required
@permission_required('finance.view_financialreport', raise_exception=True)
def export_trial_balance_csv(request):
    """Export trial balance to CSV"""
    as_of_date = request.GET.get('as_of_date', timezone.now().date())

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="trial_balance_{as_of_date}.csv"'

    writer = csv.writer(response)
    writer.writerow(['Account Code', 'Account Name', 'Account Type', 'Debit', 'Credit'])

    accounts = ChartOfAccounts.objects.filter(
        is_active=True,
        is_header=False
    ).order_by('code')

    total_debit = Decimal('0.00')
    total_credit = Decimal('0.00')

    for account in accounts:
        balance = account.get_balance(as_of_date=as_of_date)

        if balance != 0:
            if account.is_debit_account:
                debit = balance if balance > 0 else Decimal('0.00')
                credit = abs(balance) if balance < 0 else Decimal('0.00')
            else:
                credit = balance if balance > 0 else Decimal('0.00')
                debit = abs(balance) if balance < 0 else Decimal('0.00')

            writer.writerow([
                account.code,
                account.name,
                account.get_account_type_display(),
                debit,
                credit
            ])

            total_debit += debit
            total_credit += credit

    # Add totals row
    writer.writerow([])
    writer.writerow(['TOTAL', '', '', total_debit, total_credit])
    writer.writerow(['DIFFERENCE', '', '', '', total_debit - total_credit])

    return response


@login_required
@permission_required('finance.view_financialreport', raise_exception=True)
def export_general_ledger_csv(request):
    """Export general ledger to CSV - ADD THIS TO URLS"""
    account_id = request.GET.get('account')
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')

    if not account_id:
        return HttpResponse('Account ID is required', status=400)

    account = get_object_or_404(ChartOfAccounts, pk=account_id)

    response = HttpResponse(content_type='text/csv')
    filename = f"general_ledger_{account.code}_{start_date}_to_{end_date}.csv"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    writer = csv.writer(response)
    writer.writerow(['Date', 'Entry Number', 'Description', 'Reference', 'Debit', 'Credit', 'Balance'])

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

    # Calculate opening balance
    opening_balance = Decimal('0.00')
    if start_date:
        opening_balance = account.get_balance(as_of_date=start_date)

    running_balance = opening_balance

    # Write opening balance
    writer.writerow(['', 'OPENING BALANCE', '', '', '', '', opening_balance])

    for line in entries:
        if account.is_debit_account:
            running_balance += line.debit_amount - line.credit_amount
        else:
            running_balance += line.credit_amount - line.debit_amount

        writer.writerow([
            line.journal_entry.posting_date,
            line.journal_entry.entry_number,
            line.description,
            line.journal_entry.reference,
            line.debit_amount,
            line.credit_amount,
            running_balance
        ])

    return response