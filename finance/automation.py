from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from django.db import models

class FinanceAutomation:
    """
    Automated finance processes
    """

    @staticmethod
    def run_period_end_close(fiscal_period, user):
        """
        Run period-end closing procedures
        """
        from finance.models import FiscalPeriod, FixedAsset, RecurringJournalEntry

        results = {
            'depreciation': [],
            'recurring_entries': [],
            'errors': []
        }

        # 1. Calculate and record depreciation
        active_assets = FixedAsset.objects.filter(
            status='ACTIVE',
            depreciation_start_date__lte=fiscal_period.end_date
        )

        for asset in active_assets:
            try:
                # Check if depreciation already recorded
                if not asset.depreciation_records.filter(
                        fiscal_period=fiscal_period
                ).exists():
                    # Calculate depreciation
                    annual_depreciation = asset.depreciable_amount / asset.useful_life_years
                    monthly_depreciation = annual_depreciation / 12

                    # Record it
                    depreciation = asset.record_depreciation(
                        amount=monthly_depreciation,
                        for_period=fiscal_period,
                        user=user
                    )
                    results['depreciation'].append(depreciation)
            except Exception as e:
                results['errors'].append(f"Asset {asset.asset_number}: {str(e)}")

        # 2. Process recurring journal entries
        recurring_entries = RecurringJournalEntry.objects.filter(
            is_active=True,
            next_run_date__lte=fiscal_period.end_date
        )

        for recurring in recurring_entries:
            try:
                if recurring.next_run_date >= fiscal_period.start_date:
                    entry = recurring.generate_entry()
                    results['recurring_entries'].append(entry)
            except Exception as e:
                results['errors'].append(f"Recurring entry {recurring.name}: {str(e)}")

        # 3. Close the period
        fiscal_period.close_period(user)

        return results

    @staticmethod
    def reconcile_bank_accounts(as_of_date=None):
        """
        Automated bank reconciliation matching
        """
        from finance.models import BankAccount, BankTransaction, Transaction

        if not as_of_date:
            as_of_date = timezone.now().date()

        results = {
            'matched': [],
            'unmatched_bank': [],
            'unmatched_book': []
        }

        for bank_account in BankAccount.objects.filter(is_active=True):
            # Get unreconciled bank transactions
            bank_txns = BankTransaction.objects.filter(
                bank_account=bank_account,
                is_reconciled=False,
                transaction_date__lte=as_of_date
            )

            # Get uncleared book transactions
            book_txns = Transaction.objects.filter(
                bank_account=bank_account,
                is_cleared=False,
                transaction_date__lte=as_of_date
            )

            # Simple matching by amount and date (±2 days)
            for bank_txn in bank_txns:
                match = None
                for book_txn in book_txns:
                    # Check if amounts match
                    if abs(bank_txn.amount - book_txn.amount) < Decimal('0.01'):
                        # Check if dates are within 2 days
                        date_diff = abs((bank_txn.transaction_date - book_txn.transaction_date).days)
                        if date_diff <= 2:
                            match = book_txn
                            break

                if match:
                    # Match found
                    bank_txn.matched_transaction = match
                    bank_txn.is_reconciled = True
                    bank_txn.save()

                    match.is_cleared = True
                    match.cleared_date = as_of_date
                    match.save()

                    results['matched'].append({
                        'bank_txn': bank_txn,
                        'book_txn': match
                    })
                else:
                    results['unmatched_bank'].append(bank_txn)

            # Remaining unmatched book transactions
            results['unmatched_book'].extend(
                book_txns.filter(is_cleared=False)
            )

        return results

    @staticmethod
    def calculate_budget_variance():
        """
        Calculate budget vs actual variance for all active budgets
        """
        from finance.models import Budget, BudgetLine

        results = []

        active_budgets = Budget.objects.filter(
            status='ACTIVE'
        )

        for budget in active_budgets:
            budget_data = {
                'budget': budget,
                'lines': []
            }

            for line in budget.lines.all():
                actual = line.get_actual_spending()
                variance = line.get_variance()
                utilization = line.get_utilization_percentage()

                budget_data['lines'].append({
                    'line': line,
                    'budgeted': line.amount,
                    'actual': actual,
                    'variance': variance,
                    'utilization': utilization,
                    'over_budget': variance < 0
                })

            results.append(budget_data)

        return results

    @staticmethod
    def generate_ar_ageing_report():
        """
        Generate accounts receivable ageing report
        """
        from finance.models import CustomerAccount
        from datetime import timedelta

        today = timezone.now().date()
        report = {
            'as_of_date': today,
            'customers': []
        }

        for customer_account in CustomerAccount.objects.filter(
                current_balance__gt=0
        ):
            ageing = customer_account.get_ageing_analysis()

            report['customers'].append({
                'customer': customer_account.customer,
                'total_outstanding': customer_account.current_balance,
                'current': ageing['current'],
                '31_60': ageing['31_60'],
                '61_90': ageing['61_90'],
                '91_120': ageing['91_120'],
                'over_120': ageing['over_120'],
                'overdue': customer_account.overdue_balance
            })

        # Sort by total outstanding
        report['customers'].sort(
            key=lambda x: x['total_outstanding'],
            reverse=True
        )

        return report

    @staticmethod
    def process_tax_filing(fiscal_period):
        """
        Prepare tax filing data
        """
        from finance.models import TaxCode, JournalEntryLine

        filing_data = {
            'period': fiscal_period,
            'tax_collected': {},
            'tax_paid': {},
            'net_tax': Decimal('0')
        }

        for tax_code in TaxCode.objects.filter(is_active=True):
            # Tax collected (credit balance)
            collected = JournalEntryLine.objects.filter(
                account=tax_code.tax_collected_account,
                journal_entry__status='POSTED',
                journal_entry__fiscal_period=fiscal_period
            ).aggregate(
                total=models.Sum('credit_amount') - models.Sum('debit_amount')
            )['total'] or Decimal('0')

            # Tax paid (debit balance)
            paid = JournalEntryLine.objects.filter(
                account=tax_code.tax_paid_account,
                journal_entry__status='POSTED',
                journal_entry__fiscal_period=fiscal_period
            ).aggregate(
                total=models.Sum('debit_amount') - models.Sum('credit_amount')
            )['total'] or Decimal('0')

            filing_data['tax_collected'][tax_code.code] = collected
            filing_data['tax_paid'][tax_code.code] = paid

        # Calculate net tax payable/receivable
        total_collected = sum(filing_data['tax_collected'].values())
        total_paid = sum(filing_data['tax_paid'].values())
        filing_data['net_tax'] = total_collected - total_paid

        return filing_data