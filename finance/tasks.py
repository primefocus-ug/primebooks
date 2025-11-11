from celery import shared_task
from django.utils import timezone
from django.db.models import Sum, Q
from django.db import transaction as db_transaction
from django_tenants.utils import schema_context, get_tenant_model
from decimal import Decimal
import logging
from django.core.files.base import ContentFile
import csv
import json
from io import StringIO
from datetime import datetime


logger = logging.getLogger(__name__)



@shared_task
def generate_financial_report_task(report_type, user_id, **filters):
    """
    Generate financial report asynchronously
    """
    from django.contrib.auth import get_user_model
    from .models import FinancialReport, ChartOfAccounts, JournalEntryLine
    from django.utils import timezone
    from decimal import Decimal

    User = get_user_model()

    try:
        user = User.objects.get(pk=user_id)
        report_data = {}

        if report_type == 'BALANCE_SHEET':
            report_data = _generate_balance_sheet_data(filters)
        elif report_type == 'INCOME_STATEMENT':
            report_data = _generate_income_statement_data(filters)
        elif report_type == 'TRIAL_BALANCE':
            report_data = _generate_trial_balance_data(filters)
        elif report_type == 'CASH_FLOW':
            report_data = _generate_cash_flow_data(filters)

        # Create financial report record
        financial_report = FinancialReport.objects.create(
            name=f"{report_type} - {timezone.now().strftime('%Y-%m-%d')}",
            report_type=report_type,
            report_data=report_data,
            filters_applied=filters,
            generated_by=user
        )

        return f"Report generated successfully: {financial_report.id}"

    except Exception as e:
        return f"Error generating report: {str(e)}"


def _generate_balance_sheet_data(filters):
    """Generate balance sheet data"""
    from .models import ChartOfAccounts
    from decimal import Decimal

    as_of_date = filters.get('as_of_date')
    if not as_of_date:
        from django.utils import timezone
        as_of_date = timezone.now().date()

    # Assets
    assets = ChartOfAccounts.objects.filter(
        account_type='ASSET',
        is_active=True,
        is_header=False
    ).order_by('code')

    asset_data = []
    total_assets = Decimal('0.00')

    for asset in assets:
        balance = asset.get_balance(as_of_date=as_of_date)
        if balance != 0:
            asset_data.append({
                'code': asset.code,
                'name': asset.name,
                'balance': float(balance)
            })
            total_assets += balance

    # Liabilities
    liabilities = ChartOfAccounts.objects.filter(
        account_type='LIABILITY',
        is_active=True,
        is_header=False
    ).order_by('code')

    liability_data = []
    total_liabilities = Decimal('0.00')

    for liability in liabilities:
        balance = liability.get_balance(as_of_date=as_of_date)
        if balance != 0:
            liability_data.append({
                'code': liability.code,
                'name': liability.name,
                'balance': float(balance)
            })
            total_liabilities += balance

    # Equity
    equity = ChartOfAccounts.objects.filter(
        account_type='EQUITY',
        is_active=True,
        is_header=False
    ).order_by('code')

    equity_data = []
    total_equity = Decimal('0.00')

    for eq in equity:
        balance = eq.get_balance(as_of_date=as_of_date)
        if balance != 0:
            equity_data.append({
                'code': eq.code,
                'name': eq.name,
                'balance': float(balance)
            })
            total_equity += balance

    return {
        'as_of_date': as_of_date.isoformat(),
        'assets': asset_data,
        'liabilities': liability_data,
        'equity': equity_data,
        'totals': {
            'assets': float(total_assets),
            'liabilities': float(total_liabilities),
            'equity': float(total_equity)
        }
    }


def _generate_income_statement_data(filters):
    """Generate income statement data"""
    from .models import ChartOfAccounts, JournalEntryLine
    from decimal import Decimal

    start_date = filters.get('start_date')
    end_date = filters.get('end_date')

    if not start_date or not end_date:
        from django.utils import timezone
        today = timezone.now().date()
        start_date = today.replace(day=1)
        end_date = today

    def get_account_activity(account, start, end):
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

        if account.is_credit_account:
            return credit - debit
        else:
            return debit - credit

    # Revenue
    revenue_accounts = ChartOfAccounts.objects.filter(
        account_type='REVENUE',
        is_active=True,
        is_header=False
    )

    revenue_data = []
    total_revenue = Decimal('0.00')

    for account in revenue_accounts:
        amount = get_account_activity(account, start_date, end_date)
        if amount != 0:
            revenue_data.append({
                'code': account.code,
                'name': account.name,
                'amount': float(amount)
            })
            total_revenue += amount

    # Expenses
    expense_accounts = ChartOfAccounts.objects.filter(
        account_type='EXPENSE',
        is_active=True,
        is_header=False
    )

    expense_data = []
    total_expenses = Decimal('0.00')

    for account in expense_accounts:
        amount = get_account_activity(account, start_date, end_date)
        if amount != 0:
            expense_data.append({
                'code': account.code,
                'name': account.name,
                'amount': float(amount)
            })
            total_expenses += amount

    net_income = total_revenue - total_expenses

    return {
        'period': {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        },
        'revenue': revenue_data,
        'expenses': expense_data,
        'totals': {
            'revenue': float(total_revenue),
            'expenses': float(total_expenses),
            'net_income': float(net_income)
        }
    }


def _generate_trial_balance_data(filters):
    """Generate trial balance data"""
    from .models import ChartOfAccounts
    from decimal import Decimal

    as_of_date = filters.get('as_of_date')
    if not as_of_date:
        from django.utils import timezone
        as_of_date = timezone.now().date()

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
                'code': account.code,
                'name': account.name,
                'type': account.get_account_type_display(),
                'debit': float(debit),
                'credit': float(credit)
            })

            total_debit += debit
            total_credit += credit

    return {
        'as_of_date': as_of_date.isoformat(),
        'accounts': trial_balance_data,
        'totals': {
            'debit': float(total_debit),
            'credit': float(total_credit),
            'difference': float(total_debit - total_credit)
        }
    }


def _generate_cash_flow_data(filters):
    """Generate cash flow statement data"""
    from .models import JournalEntryLine
    from decimal import Decimal

    start_date = filters.get('start_date')
    end_date = filters.get('end_date')

    if not start_date or not end_date:
        from django.utils import timezone
        today = timezone.now().date()
        start_date = today.replace(day=1)
        end_date = today

    # Operating Activities (simplified)
    operating = JournalEntryLine.objects.filter(
        account__account_type__in=['REVENUE', 'EXPENSE'],
        journal_entry__status='POSTED',
        journal_entry__posting_date__range=[start_date, end_date]
    ).aggregate(
        net=Sum('credit_amount_base') - Sum('debit_amount_base')
    )['net'] or Decimal('0.00')

    # Investing Activities (simplified)
    investing = JournalEntryLine.objects.filter(
        account__name__icontains='asset',
        journal_entry__status='POSTED',
        journal_entry__posting_date__range=[start_date, end_date]
    ).aggregate(
        net=Sum('debit_amount_base') - Sum('credit_amount_base')
    )['net'] or Decimal('0.00')

    # Financing Activities (simplified)
    financing = JournalEntryLine.objects.filter(
        account__account_type__in=['LIABILITY', 'EQUITY'],
        journal_entry__status='POSTED',
        journal_entry__posting_date__range=[start_date, end_date]
    ).aggregate(
        net=Sum('credit_amount_base') - Sum('debit_amount_base')
    )['net'] or Decimal('0.00')

    net_cash_flow = operating + investing + financing

    return {
        'period': {
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat()
        },
        'operating_activities': float(operating),
        'investing_activities': float(investing),
        'financing_activities': float(financing),
        'net_cash_flow': float(net_cash_flow)
    }


@shared_task
def export_general_ledger_task(account_id, start_date, end_date, user_id, format='csv'):
    """
    Export general ledger for specific account
    """
    from django.contrib.auth import get_user_model
    from .models import ChartOfAccounts, JournalEntryLine
    from django.http import HttpResponse
    import csv
    from io import StringIO
    from decimal import Decimal

    User = get_user_model()

    try:
        user = User.objects.get(pk=user_id)
        account = ChartOfAccounts.objects.get(pk=account_id)

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

        if format == 'csv':
            output = StringIO()
            writer = csv.writer(output)

            # Write header
            writer.writerow(['Date', 'Entry Number', 'Description', 'Reference', 'Debit', 'Credit', 'Balance'])

            # Write opening balance
            writer.writerow(['', 'OPENING BALANCE', '', '', '', '', str(opening_balance)])

            # Write entries
            for line in entries:
                if account.is_debit_account:
                    running_balance += line.debit_amount - line.credit_amount
                else:
                    running_balance += line.credit_amount - line.debit_amount

                writer.writerow([
                    line.journal_entry.posting_date.isoformat(),
                    line.journal_entry.entry_number,
                    line.description or '',
                    line.journal_entry.reference or '',
                    str(line.debit_amount),
                    str(line.credit_amount),
                    str(running_balance)
                ])

            csv_content = output.getvalue()
            output.close()

            return {
                'success': True,
                'format': 'csv',
                'content': csv_content,
                'filename': f"general_ledger_{account.code}_{start_date}_to_{end_date}.csv"
            }

        elif format == 'json':
            ledger_data = {
                'account': {
                    'code': account.code,
                    'name': account.name,
                    'type': account.get_account_type_display()
                },
                'period': {
                    'start_date': start_date.isoformat() if start_date else '',
                    'end_date': end_date.isoformat() if end_date else ''
                },
                'opening_balance': float(opening_balance),
                'entries': []
            }

            for line in entries:
                if account.is_debit_account:
                    running_balance += line.debit_amount - line.credit_amount
                else:
                    running_balance += line.credit_amount - line.debit_amount

                ledger_data['entries'].append({
                    'date': line.journal_entry.posting_date.isoformat(),
                    'entry_number': line.journal_entry.entry_number,
                    'description': line.description,
                    'reference': line.journal_entry.reference,
                    'debit': float(line.debit_amount),
                    'credit': float(line.credit_amount),
                    'balance': float(running_balance)
                })

            ledger_data['closing_balance'] = float(running_balance)

            return {
                'success': True,
                'format': 'json',
                'content': json.dumps(ledger_data, indent=2),
                'filename': f"general_ledger_{account.code}_{start_date}_to_{end_date}.json"
            }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def export_trial_balance_task(as_of_date, user_id, format='csv'):
    """
    Export trial balance
    """
    from django.contrib.auth import get_user_model
    from .models import ChartOfAccounts
    import csv
    from io import StringIO
    from decimal import Decimal

    User = get_user_model()

    try:
        user = User.objects.get(pk=user_id)

        accounts = ChartOfAccounts.objects.filter(
            is_active=True,
            is_header=False
        ).order_by('code')

        if format == 'csv':
            output = StringIO()
            writer = csv.writer(output)

            writer.writerow(['Account Code', 'Account Name', 'Account Type', 'Debit', 'Credit'])

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
                        str(debit),
                        str(credit)
                    ])

                    total_debit += debit
                    total_credit += credit

            # Add totals
            writer.writerow([])
            writer.writerow(['TOTAL', '', '', str(total_debit), str(total_credit)])
            writer.writerow(['DIFFERENCE', '', '', '', str(total_debit - total_credit)])

            csv_content = output.getvalue()
            output.close()

            return {
                'success': True,
                'format': 'csv',
                'content': csv_content,
                'filename': f"trial_balance_{as_of_date}.csv"
            }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def generate_recurring_entries_task():
    """
    Generate recurring journal entries automatically
    """
    from .models import RecurringJournalEntry
    from django.utils import timezone

    try:
        today = timezone.now().date()
        recurring_entries = RecurringJournalEntry.objects.filter(
            is_active=True,
            next_run_date__lte=today
        )

        generated_count = 0
        errors = []

        for recurring in recurring_entries:
            try:
                with db_transaction.atomic():
                    entry = recurring.generate_entry()
                    generated_count += 1
            except Exception as e:
                errors.append(f"{recurring.code}: {str(e)}")

        return {
            'success': True,
            'generated_count': generated_count,
            'errors': errors
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }


@shared_task
def calculate_depreciation_task():
    """
    Calculate depreciation for all active fixed assets
    """
    from .models import FixedAsset, FiscalPeriod
    from django.utils import timezone

    try:
        today = timezone.now().date()
        current_period = FiscalPeriod.objects.filter(
            start_date__lte=today,
            end_date__gte=today,
            status='OPEN'
        ).first()

        if not current_period:
            return {
                'success': False,
                'error': 'No open fiscal period found'
            }

        assets = FixedAsset.objects.filter(
            status='ACTIVE',
            depreciation_start_date__lte=today
        )

        processed_count = 0
        errors = []

        for asset in assets:
            try:
                # Check if already depreciated for this period
                if asset.depreciation_records.filter(fiscal_period=current_period).exists():
                    continue

                # Calculate depreciation
                amount = asset.calculate_depreciation(current_period.end_date)

                if amount > 0:
                    # Record depreciation (you'll need to pass a user - using system user or first admin)
                    from django.contrib.auth import get_user_model
                    User = get_user_model()
                    system_user = User.objects.filter(is_superuser=True).first()

                    if system_user:
                        asset.record_depreciation(
                            amount=amount,
                            for_period=current_period,
                            user=system_user
                        )
                        processed_count += 1

            except Exception as e:
                errors.append(f"{asset.asset_number}: {str(e)}")

        return {
            'success': True,
            'processed_count': processed_count,
            'errors': errors
        }

    except Exception as e:
        return {
            'success': False,
            'error': str(e)
        }

# ============================================
# EXCHANGE RATE TASKS
# ============================================

@shared_task(bind=True, max_retries=3)
def fetch_exchange_rates_task(self, tenant_schema=None):
    """
    Fetch exchange rates from API for all tenants or specific tenant
    """
    try:
        Tenant = get_tenant_model()

        if tenant_schema:
            tenants = Tenant.objects.filter(schema_name=tenant_schema)
        else:
            # Fetch for all tenants
            tenants = Tenant.objects.exclude(schema_name='public')

        results = {}

        for tenant in tenants:
            with schema_context(tenant.schema_name):
                from .models import ExchangeRate

                try:
                    success = ExchangeRate.fetch_rates_from_api()
                    results[tenant.schema_name] = 'success' if success else 'failed'
                    logger.info(f"Exchange rates fetched for {tenant.schema_name}: {success}")
                except Exception as e:
                    logger.error(f"Error fetching rates for {tenant.schema_name}: {str(e)}")
                    results[tenant.schema_name] = f'error: {str(e)}'

        return {'status': 'completed', 'results': results}

    except Exception as e:
        logger.error(f"Error in fetch_exchange_rates_task: {str(e)}")
        raise self.retry(exc=e, countdown=300)  # Retry after 5 minutes


@shared_task
def fetch_exchange_rates_for_tenant(tenant_schema):
    """Fetch exchange rates for specific tenant"""
    with schema_context(tenant_schema):
        from .models import ExchangeRate

        try:
            success = ExchangeRate.fetch_rates_from_api()
            return {'status': 'success' if success else 'failed'}
        except Exception as e:
            logger.error(f"Error fetching rates: {str(e)}")
            return {'status': 'error', 'message': str(e)}


# ============================================
# FINANCIAL REPORTS
# ============================================

@shared_task(bind=True)
def generate_financial_report_task(self, tenant_schema, report_type, user_id, **kwargs):
    """
    Generate financial reports asynchronously
    """
    with schema_context(tenant_schema):
        from .models import (
            ChartOfAccounts, AccountType, JournalEntryLine,
            FinancialReport, Currency
        )
        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            user = User.objects.get(id=user_id)

            if report_type == 'BALANCE_SHEET':
                as_of_date = kwargs.get('as_of_date', timezone.now().date())
                data = _generate_balance_sheet_data(as_of_date)

            elif report_type == 'INCOME_STATEMENT':
                start_date = kwargs.get('start_date')
                end_date = kwargs.get('end_date')
                data = _generate_income_statement_data(start_date, end_date)

            elif report_type == 'TRIAL_BALANCE':
                as_of_date = kwargs.get('as_of_date', timezone.now().date())
                data = _generate_trial_balance_data(as_of_date)

            elif report_type == 'CASH_FLOW':
                start_date = kwargs.get('start_date')
                end_date = kwargs.get('end_date')
                data = _generate_cash_flow_data(start_date, end_date)

            # Save report
            report = FinancialReport.objects.create(
                name=f"{report_type} - {timezone.now().date()}",
                report_type=report_type,
                report_data=data,
                generated_by=user,
                **kwargs
            )

            # Create notification
            try:
                from notifications.models import Notification
                Notification.objects.create(
                    user=user,
                    title=f'{report_type.replace("_", " ").title()} Ready',
                    message=f'Your report has been generated successfully.',
                    notification_type='REPORT_READY',
                    data={'report_id': report.id}
                )
            except:
                pass  # Notifications module may not exist

            logger.info(f'Report {report_type} generated for user {user_id}')
            return {'status': 'success', 'report_id': report.id}

        except Exception as e:
            logger.error(f'Error generating report {report_type}: {str(e)}')
            return {'status': 'error', 'message': str(e)}


def _generate_balance_sheet_data(as_of_date):
    """Generate balance sheet data"""
    from .models import ChartOfAccounts, AccountType, Currency

    base_currency = Currency.objects.filter(is_base=True).first()

    data = {
        'as_of_date': str(as_of_date),
        'currency': base_currency.code if base_currency else 'USD',
        'assets': [],
        'liabilities': [],
        'equity': [],
        'totals': {}
    }

    # Assets
    assets = ChartOfAccounts.objects.filter(
        account_type=AccountType.ASSET,
        is_active=True,
        is_header=False
    ).order_by('code')

    total_assets = Decimal('0')
    for account in assets:
        balance = account.get_balance(as_of_date=as_of_date, currency=base_currency)
        if balance != 0:
            data['assets'].append({
                'code': account.code,
                'name': account.name,
                'balance': str(balance),
                'currency': account.currency.code
            })
            total_assets += balance

    # Liabilities
    liabilities = ChartOfAccounts.objects.filter(
        account_type=AccountType.LIABILITY,
        is_active=True,
        is_header=False
    ).order_by('code')

    total_liabilities = Decimal('0')
    for account in liabilities:
        balance = account.get_balance(as_of_date=as_of_date, currency=base_currency)
        if balance != 0:
            data['liabilities'].append({
                'code': account.code,
                'name': account.name,
                'balance': str(balance)
            })
            total_liabilities += balance

    # Equity
    equity = ChartOfAccounts.objects.filter(
        account_type=AccountType.EQUITY,
        is_active=True,
        is_header=False
    ).order_by('code')

    total_equity = Decimal('0')
    for account in equity:
        balance = account.get_balance(as_of_date=as_of_date, currency=base_currency)
        if balance != 0:
            data['equity'].append({
                'code': account.code,
                'name': account.name,
                'balance': str(balance)
            })
            total_equity += balance

    data['totals'] = {
        'assets': str(total_assets),
        'liabilities': str(total_liabilities),
        'equity': str(total_equity),
        'total_liabilities_equity': str(total_liabilities + total_equity)
    }

    return data


def _generate_income_statement_data(start_date, end_date):
    """Generate income statement data"""
    from .models import ChartOfAccounts, AccountType, JournalEntryLine, Currency

    base_currency = Currency.objects.filter(is_base=True).first()

    data = {
        'period': {
            'start': str(start_date),
            'end': str(end_date)
        },
        'currency': base_currency.code if base_currency else 'USD',
        'revenue': [],
        'cogs': [],
        'expenses': [],
        'totals': {}
    }

    def get_period_activity(account, start, end):
        lines = JournalEntryLine.objects.filter(
            account=account,
            journal_entry__status='POSTED',
            journal_entry__posting_date__range=[start, end]
        )

        total = lines.aggregate(
            debit=Sum('debit_amount_base'),
            credit=Sum('credit_amount_base')
        )

        debit = total['debit'] or Decimal('0')
        credit = total['credit'] or Decimal('0')

        if account.is_credit_account:
            return credit - debit
        else:
            return debit - credit

    # Revenue
    revenue_accounts = ChartOfAccounts.objects.filter(
        account_type=AccountType.REVENUE,
        is_active=True,
        is_header=False
    )

    total_revenue = Decimal('0')
    for account in revenue_accounts:
        amount = get_period_activity(account, start_date, end_date)
        if amount != 0:
            data['revenue'].append({
                'code': account.code,
                'name': account.name,
                'amount': str(amount)
            })
            total_revenue += amount

    # COGS
    cogs_accounts = ChartOfAccounts.objects.filter(
        account_type=AccountType.COST_OF_SALES,
        is_active=True,
        is_header=False
    )

    total_cogs = Decimal('0')
    for account in cogs_accounts:
        amount = get_period_activity(account, start_date, end_date)
        if amount != 0:
            data['cogs'].append({
                'code': account.code,
                'name': account.name,
                'amount': str(amount)
            })
            total_cogs += amount

    # Expenses
    expense_accounts = ChartOfAccounts.objects.filter(
        account_type=AccountType.EXPENSE,
        is_active=True,
        is_header=False
    )

    total_expenses = Decimal('0')
    for account in expense_accounts:
        amount = get_period_activity(account, start_date, end_date)
        if amount != 0:
            data['expenses'].append({
                'code': account.code,
                'name': account.name,
                'amount': str(amount)
            })
            total_expenses += amount

    gross_profit = total_revenue - total_cogs
    net_income = gross_profit - total_expenses

    data['totals'] = {
        'revenue': str(total_revenue),
        'cogs': str(total_cogs),
        'gross_profit': str(gross_profit),
        'gross_margin': str((gross_profit / total_revenue * 100) if total_revenue else 0),
        'expenses': str(total_expenses),
        'net_income': str(net_income),
        'net_margin': str((net_income / total_revenue * 100) if total_revenue else 0)
    }

    return data


def _generate_trial_balance_data(as_of_date):
    """Generate trial balance data"""
    from .models import ChartOfAccounts, Currency

    base_currency = Currency.objects.filter(is_base=True).first()

    data = {
        'as_of_date': str(as_of_date),
        'currency': base_currency.code if base_currency else 'USD',
        'accounts': [],
        'totals': {}
    }

    accounts = ChartOfAccounts.objects.filter(
        is_active=True,
        is_header=False
    ).order_by('code')

    total_debit = Decimal('0')
    total_credit = Decimal('0')

    for account in accounts:
        balance = account.get_balance(as_of_date=as_of_date, currency=base_currency)

        if balance != 0:
            if account.is_debit_account:
                debit = balance if balance > 0 else Decimal('0')
                credit = abs(balance) if balance < 0 else Decimal('0')
            else:
                credit = balance if balance > 0 else Decimal('0')
                debit = abs(balance) if balance < 0 else Decimal('0')

            data['accounts'].append({
                'code': account.code,
                'name': account.name,
                'type': account.account_type,
                'debit': str(debit),
                'credit': str(credit)
            })

            total_debit += debit
            total_credit += credit

    data['totals'] = {
        'debit': str(total_debit),
        'credit': str(total_credit),
        'difference': str(abs(total_debit - total_credit)),
        'is_balanced': abs(total_debit - total_credit) < Decimal('0.01')
    }

    return data


def _generate_cash_flow_data(start_date, end_date):
    """Generate cash flow statement data"""
    from .models import ChartOfAccounts, JournalEntryLine, Currency

    base_currency = Currency.objects.filter(is_base=True).first()

    data = {
        'period': {
            'start': str(start_date),
            'end': str(end_date)
        },
        'currency': base_currency.code if base_currency else 'USD',
        'operating': [],
        'investing': [],
        'financing': [],
        'totals': {}
    }

    # This would require more complex logic to categorize cash flows
    # Simplified version shown here

    return data


# ============================================
# DEPRECIATION TASKS
# ============================================

@shared_task(bind=True)
def calculate_depreciation_task(self, tenant_schema):
    """
    Calculate and record depreciation for all active assets
    """
    with schema_context(tenant_schema):
        from .models import FixedAsset, FiscalPeriod
        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            # Get current period
            current_period = FiscalPeriod.objects.filter(
                status='OPEN',
                start_date__lte=timezone.now().date(),
                end_date__gte=timezone.now().date()
            ).first()

            if not current_period:
                logger.warning('No open fiscal period found for depreciation')
                return {'status': 'skipped', 'message': 'No open period'}

            # Get all active assets
            assets = FixedAsset.objects.filter(
                status='ACTIVE',
                depreciation_start_date__lte=current_period.end_date
            ).exclude(
                depreciation_records__fiscal_period=current_period
            )

            # Get system user
            system_user = User.objects.filter(is_superuser=True).first()

            success_count = 0
            error_count = 0
            errors = []

            for asset in assets:
                try:
                    with db_transaction.atomic():
                        amount = asset.calculate_depreciation(current_period.end_date)

                        if amount > 0:
                            asset.record_depreciation(
                                amount=amount,
                                for_period=current_period,
                                user=system_user
                            )
                            success_count += 1

                except Exception as e:
                    logger.error(f'Error depreciating asset {asset.asset_number}: {str(e)}')
                    error_count += 1
                    errors.append({
                        'asset': asset.asset_number,
                        'error': str(e)
                    })

            return {
                'status': 'completed',
                'period': current_period.name,
                'processed': success_count,
                'errors': error_count,
                'error_details': errors
            }

        except Exception as e:
            logger.error(f'Error in depreciation task: {str(e)}')
            return {'status': 'error', 'message': str(e)}


# ============================================
# RECURRING ENTRIES
# ============================================

@shared_task
def generate_recurring_entries_task(tenant_schema):
    """
    Generate recurring journal entries for tenant
    """
    with schema_context(tenant_schema):
        from .models import RecurringJournalEntry

        try:
            today = timezone.now().date()

            recurring_entries = RecurringJournalEntry.objects.filter(
                is_active=True,
                next_run_date__lte=today
            )

            generated_count = 0
            errors = []

            for recurring in recurring_entries:
                try:
                    with db_transaction.atomic():
                        entry = recurring.generate_entry()
                        generated_count += 1
                        logger.info(f'Generated recurring entry: {entry.entry_number}')
                except Exception as e:
                    logger.error(f'Error generating recurring entry {recurring.code}: {str(e)}')
                    errors.append({
                        'code': recurring.code,
                        'error': str(e)
                    })

            return {
                'status': 'completed',
                'generated': generated_count,
                'errors': len(errors),
                'error_details': errors
            }

        except Exception as e:
            logger.error(f'Error in recurring entries task: {str(e)}')
            return {'status': 'error', 'message': str(e)}


@shared_task
def generate_recurring_entries_all_tenants():
    """Generate recurring entries for all tenants"""
    Tenant = get_tenant_model()
    tenants = Tenant.objects.exclude(schema_name='public')

    results = {}
    for tenant in tenants:
        result = generate_recurring_entries_task(tenant.schema_name)
        results[tenant.schema_name] = result

    return results


# ============================================
# BANK STATEMENT PROCESSING
# ============================================

@shared_task(bind=True)
def process_bank_statement_task(self, tenant_schema, bank_statement_id):
    """
    Process uploaded bank statement and create transactions
    """
    with schema_context(tenant_schema):
        from .models import BankStatement, BankTransaction
        import csv

        try:
            statement = BankStatement.objects.get(id=bank_statement_id)

            # Parse based on format
            if statement.file_format == 'CSV':
                transactions_created = _process_csv_statement(statement)
            elif statement.file_format == 'OFX':
                transactions_created = _process_ofx_statement(statement)
            # Add other formats as needed

            statement.is_processed = True
            statement.processed_at = timezone.now()
            statement.transactions_imported = transactions_created
            statement.save()

            return {
                'status': 'success',
                'imported': transactions_created
            }

        except Exception as e:
            logger.error(f'Error processing bank statement: {str(e)}')
            return {'status': 'error', 'message': str(e)}


def _process_csv_statement(statement):
    """Process CSV bank statement"""
    # Implementation would depend on your bank's CSV format
    # This is a placeholder
    return 0


def _process_ofx_statement(statement):
    """Process OFX bank statement"""
    # Implementation for OFX format
    return 0


# ============================================
# PERIOD CLOSE TASKS
# ============================================

@shared_task
def close_fiscal_period_task(tenant_schema, period_id, user_id):
    """
    Close fiscal period with all checks
    """
    with schema_context(tenant_schema):
        from .models import FiscalPeriod, JournalEntry
        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            period = FiscalPeriod.objects.get(id=period_id)
            user = User.objects.get(id=user_id)

            # Check for unposted entries
            unposted = JournalEntry.objects.filter(
                fiscal_period=period,
                status__in=['DRAFT', 'PENDING']
            ).count()

            if unposted > 0:
                return {
                    'status': 'error',
                    'message': f'{unposted} unposted journal entries found'
                }

            # Close the period
            with db_transaction.atomic():
                period.close_period(user)

            return {'status': 'success'}

        except Exception as e:
            logger.error(f'Error closing period: {str(e)}')
            return {'status': 'error', 'message': str(e)}


# ============================================
# MAINTENANCE TASKS
# ============================================

@shared_task
def update_account_balances_task(tenant_schema):
    """
    Update cached account balances
    """
    with schema_context(tenant_schema):
        from .models import ChartOfAccounts

        try:
            accounts = ChartOfAccounts.objects.filter(is_active=True)

            updated_count = 0
            for account in accounts:
                try:
                    account.update_balance()
                    updated_count += 1
                except Exception as e:
                    logger.error(f'Error updating balance for {account.code}: {str(e)}')

            return {
                'status': 'success',
                'updated': updated_count
            }

        except Exception as e:
            logger.error(f'Error updating account balances: {str(e)}')
            return {'status': 'error', 'message': str(e)}


@shared_task
def update_budget_actuals_task(tenant_schema):
    """
    Update cached budget actuals
    """
    with schema_context(tenant_schema):
        from .models import Budget, BudgetLine

        try:
            active_budgets = Budget.objects.filter(status='ACTIVE')

            updated_lines = 0
            for budget in active_budgets:
                for line in budget.lines.all():
                    line.update_actual()
                    updated_lines += 1

                budget.calculate_totals()

            return {
                'status': 'success',
                'budgets': active_budgets.count(),
                'lines_updated': updated_lines
            }

        except Exception as e:
            logger.error(f'Error updating budget actuals: {str(e)}')
            return {'status': 'error', 'message': str(e)}


# ============================================
# SCHEDULED TASKS (Run via celery beat)
# ============================================

@shared_task
def daily_finance_tasks():
    """
    Daily finance tasks for all tenants
    """
    Tenant = get_tenant_model()
    tenants = Tenant.objects.exclude(schema_name='public')

    results = {}

    for tenant in tenants:
        tenant_results = {}

        # Fetch exchange rates
        tenant_results['exchange_rates'] = fetch_exchange_rates_for_tenant(tenant.schema_name)

        # Generate recurring entries
        tenant_results['recurring_entries'] = generate_recurring_entries_task(tenant.schema_name)

        # Update account balances
        tenant_results['account_balances'] = update_account_balances_task(tenant.schema_name)

        # Update budget actuals
        tenant_results['budget_actuals'] = update_budget_actuals_task(tenant.schema_name)

        results[tenant.schema_name] = tenant_results

    return results


@shared_task
def monthly_finance_tasks():
    """
    Monthly finance tasks for all tenants
    """
    Tenant = get_tenant_model()
    tenants = Tenant.objects.exclude(schema_name='public')

    results = {}

    for tenant in tenants:
        tenant_results = {}

        # Calculate depreciation
        tenant_results['depreciation'] = calculate_depreciation_task(tenant.schema_name)

        results[tenant.schema_name] = tenant_results

    return results