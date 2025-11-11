from django.utils import timezone
from django.db.models import Sum, Q, F, Avg
from django.db import transaction as db_transaction
from decimal import Decimal
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)


class IntelligentReconciliationEngine:
    """
    Intelligent bank reconciliation with machine learning-like matching
    """

    @staticmethod
    def match_transactions(bank_account, confidence_threshold=0.85):
        """
        Match bank and book transactions using intelligent scoring
        """
        from finance.models import BankTransaction, Transaction

        unmatched_bank = BankTransaction.objects.filter(
            bank_account=bank_account,
            is_reconciled=False
        )

        unmatched_book = Transaction.objects.filter(
            bank_account=bank_account,
            is_cleared=False
        )

        matches = []

        for bank_txn in unmatched_bank:
            best_match = None
            best_score = 0

            for book_txn in unmatched_book:
                score = IntelligentReconciliationEngine._calculate_match_score(
                    bank_txn, book_txn
                )

                if score > best_score and score >= confidence_threshold:
                    best_score = score
                    best_match = book_txn

            if best_match:
                matches.append({
                    'bank_txn': bank_txn,
                    'book_txn': best_match,
                    'confidence': best_score
                })

        return matches

    @staticmethod
    def _calculate_match_score(bank_txn, book_txn):
        """
        Calculate match score (0-1) based on multiple factors
        """
        score = 0.0

        # Amount matching (40% weight)
        amount_diff = abs(bank_txn.amount - book_txn.amount)
        if amount_diff == 0:
            score += 0.4
        elif amount_diff <= bank_txn.amount * Decimal('0.01'):  # 1% tolerance
            score += 0.35
        elif amount_diff <= bank_txn.amount * Decimal('0.05'):  # 5% tolerance
            score += 0.25

        # Date matching (30% weight)
        date_diff = abs((bank_txn.transaction_date - book_txn.transaction_date).days)
        if date_diff == 0:
            score += 0.3
        elif date_diff <= 1:
            score += 0.25
        elif date_diff <= 2:
            score += 0.2
        elif date_diff <= 5:
            score += 0.15

        # Description matching (20% weight)
        desc_score = IntelligentReconciliationEngine._compare_descriptions(
            bank_txn.description,
            book_txn.description
        )
        score += desc_score * 0.2

        # Transaction type matching (10% weight)
        if bank_txn.transaction_type == book_txn.transaction_type:
            score += 0.1

        return score

    @staticmethod
    def _compare_descriptions(desc1, desc2):
        """
        Compare descriptions and return similarity score (0-1)
        """
        if not desc1 or not desc2:
            return 0

        desc1 = desc1.lower().split()
        desc2 = desc2.lower().split()

        common_words = set(desc1) & set(desc2)
        total_words = len(set(desc1) | set(desc2))

        if total_words == 0:
            return 0

        return len(common_words) / total_words


class SmartBudgetAnalyzer:
    """
    Intelligent budget analysis and forecasting
    """

    @staticmethod
    def analyze_spending_trends(budget_line, periods=6):
        """
        Analyze spending trends and predict future utilization
        """
        from finance.models import JournalEntryLine

        # Get historical spending per period
        spending_history = []
        current_date = timezone.now().date()

        for i in range(periods):
            period_start = current_date - timedelta(days=30 * (i + 1))
            period_end = current_date - timedelta(days=30 * i)

            spending = JournalEntryLine.objects.filter(
                account=budget_line.account,
                cost_center=budget_line.cost_center,
                journal_entry__status='POSTED',
                journal_entry__posting_date__range=[period_start, period_end]
            ).aggregate(
                total=Sum('debit_amount') - Sum('credit_amount')
            )['total'] or Decimal('0')

            spending_history.append(float(spending))

        # Calculate trend
        if len(spending_history) >= 2:
            avg_spending = sum(spending_history) / len(spending_history)
            trend = (spending_history[0] - spending_history[-1]) / len(spending_history)

            # Predict next period
            predicted_spending = spending_history[0] + trend

            return {
                'average': avg_spending,
                'trend': 'increasing' if trend > 0 else 'decreasing',
                'predicted_next_period': predicted_spending,
                'history': list(reversed(spending_history))
            }

        return None

    @staticmethod
    def get_budget_alerts(priority_threshold='MEDIUM'):
        """
        Get all budget alerts with intelligent prioritization
        """
        from finance.models import Budget, BudgetLine

        alerts = []
        active_budgets = Budget.objects.filter(status='ACTIVE')

        for budget in active_budgets:
            for line in budget.lines.select_related('account', 'cost_center'):
                utilization = line.get_utilization_percentage()

                alert = SmartBudgetAnalyzer._create_alert(line, utilization)

                if alert and alert['priority_score'] >= SmartBudgetAnalyzer._priority_threshold(priority_threshold):
                    alerts.append(alert)

        # Sort by priority
        alerts.sort(key=lambda x: x['priority_score'], reverse=True)

        return alerts

    @staticmethod
    def _create_alert(budget_line, utilization):
        """
        Create intelligent alert with priority scoring
        """
        if utilization < 75:
            return None

        alert = {
            'budget_line': budget_line,
            'utilization': utilization,
            'priority_score': 0,
            'recommendations': []
        }

        # Calculate priority score
        if utilization >= 110:
            alert['priority_score'] = 100
            alert['level'] = 'CRITICAL'
            alert['recommendations'].append('Immediate action required - Budget exceeded')
        elif utilization >= 100:
            alert['priority_score'] = 90
            alert['level'] = 'HIGH'
            alert['recommendations'].append('Stop new spending immediately')
        elif utilization >= 95:
            alert['priority_score'] = 75
            alert['level'] = 'HIGH'
            alert['recommendations'].append('Review and approve all new expenses')
        elif utilization >= 90:
            alert['priority_score'] = 60
            alert['level'] = 'MEDIUM'
            alert['recommendations'].append('Monitor closely - Consider budget adjustment')
        elif utilization >= 75:
            alert['priority_score'] = 40
            alert['level'] = 'LOW'
            alert['recommendations'].append('Plan for period-end budget review')

        # Add trend-based recommendations
        trend = SmartBudgetAnalyzer.analyze_spending_trends(budget_line)
        if trend and trend['trend'] == 'increasing':
            alert['priority_score'] += 10
            alert['recommendations'].append('Spending trend is increasing')

        return alert

    @staticmethod
    def _priority_threshold(level):
        thresholds = {
            'LOW': 40,
            'MEDIUM': 60,
            'HIGH': 75,
            'CRITICAL': 90
        }
        return thresholds.get(level, 60)


class AutomatedJournalEntryEngine:
    """
    Intelligent journal entry creation engine
    """

    @staticmethod
    def create_standard_entry(entry_type, **kwargs):
        """
        Create standard journal entries based on type
        """
        entry_types = {
            'depreciation': AutomatedJournalEntryEngine._create_depreciation_entry,
            'accrual': AutomatedJournalEntryEngine._create_accrual_entry,
            'prepayment': AutomatedJournalEntryEngine._create_prepayment_entry,
            'payroll': AutomatedJournalEntryEngine._create_payroll_entry,
        }

        creator = entry_types.get(entry_type)
        if creator:
            return creator(**kwargs)

        raise ValueError(f"Unknown entry type: {entry_type}")

    @staticmethod
    def _create_depreciation_entry(asset, period, user):
        """
        Create depreciation entry for an asset
        """
        from finance.models import Journal, JournalType, JournalEntry, JournalEntryLine

        journal = Journal.objects.filter(
            journal_type=JournalType.GENERAL,
            is_active=True
        ).first()

        if not journal:
            raise ValueError("No general journal found")

        # Calculate depreciation
        annual_dep = asset.depreciable_amount / asset.useful_life_years
        monthly_dep = annual_dep / 12

        with db_transaction.atomic():
            entry = JournalEntry.objects.create(
                journal=journal,
                entry_date=period.end_date,
                description=f'Depreciation - {asset.name}',
                reference=f'DEP-{asset.asset_number}-{period.name}',
                created_by=user,
                fiscal_period=period
            )

            # Debit: Depreciation Expense
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=asset.category.depreciation_expense_account,
                debit_amount=monthly_dep,
                description=f'Depreciation expense for {asset.name}',
                cost_center=asset.cost_center
            )

            # Credit: Accumulated Depreciation
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=asset.category.accumulated_depreciation_account,
                credit_amount=monthly_dep,
                description=f'Accumulated depreciation for {asset.name}'
            )

            return entry

    @staticmethod
    def _create_accrual_entry(account, amount, description, date, user):
        """
        Create accrual entry
        """
        from finance.models import Journal, JournalType, JournalEntry, JournalEntryLine

        journal = Journal.objects.filter(
            journal_type=JournalType.GENERAL,
            is_active=True
        ).first()

        with db_transaction.atomic():
            entry = JournalEntry.objects.create(
                journal=journal,
                entry_date=date,
                description=f'Accrual - {description}',
                created_by=user
            )

            # Implementation depends on accrual type
            # This is a template

            return entry


class FinancialHealthMonitor:
    """
    Monitor financial health and provide insights
    """

    @staticmethod
    def calculate_key_ratios(as_of_date=None):
        """
        Calculate key financial ratios
        """
        from finance.models import ChartOfAccounts, AccountType

        if not as_of_date:
            as_of_date = timezone.now().date()

        # Current Assets
        current_assets = ChartOfAccounts.objects.filter(
            account_type=AccountType.ASSET,
            is_active=True,
            is_current=True
        ).aggregate(total=Sum('current_balance'))['total'] or Decimal('0')

        # Current Liabilities
        current_liabilities = ChartOfAccounts.objects.filter(
            account_type=AccountType.LIABILITY,
            is_active=True,
            is_current=True
        ).aggregate(total=Sum('current_balance'))['total'] or Decimal('0')

        # Total Assets
        total_assets = ChartOfAccounts.objects.filter(
            account_type=AccountType.ASSET,
            is_active=True
        ).aggregate(total=Sum('current_balance'))['total'] or Decimal('0')

        # Total Liabilities
        total_liabilities = ChartOfAccounts.objects.filter(
            account_type=AccountType.LIABILITY,
            is_active=True
        ).aggregate(total=Sum('current_balance'))['total'] or Decimal('0')

        # Total Equity
        total_equity = ChartOfAccounts.objects.filter(
            account_type=AccountType.EQUITY,
            is_active=True
        ).aggregate(total=Sum('current_balance'))['total'] or Decimal('0')

        ratios = {}

        # Current Ratio
        if current_liabilities > 0:
            ratios['current_ratio'] = float(current_assets / current_liabilities)

        # Debt to Equity Ratio
        if total_equity > 0:
            ratios['debt_to_equity'] = float(total_liabilities / total_equity)

        # Equity Ratio
        if total_assets > 0:
            ratios['equity_ratio'] = float(total_equity / total_assets)

        return ratios

    @staticmethod
    def get_health_score():
        """
        Calculate overall financial health score (0-100)
        """
        ratios = FinancialHealthMonitor.calculate_key_ratios()

        score = 0

        # Current Ratio (30 points)
        current_ratio = ratios.get('current_ratio', 0)
        if current_ratio >= 2:
            score += 30
        elif current_ratio >= 1.5:
            score += 25
        elif current_ratio >= 1:
            score += 15

        # Debt to Equity (30 points)
        debt_to_equity = ratios.get('debt_to_equity', 999)
        if debt_to_equity <= 0.5:
            score += 30
        elif debt_to_equity <= 1:
            score += 25
        elif debt_to_equity <= 2:
            score += 15

        # Equity Ratio (20 points)
        equity_ratio = ratios.get('equity_ratio', 0)
        if equity_ratio >= 0.5:
            score += 20
        elif equity_ratio >= 0.3:
            score += 15
        elif equity_ratio >= 0.2:
            score += 10

        # Budget Compliance (20 points)
        budget_compliance = SmartBudgetAnalyzer.get_budget_alerts('LOW')
        if len(budget_compliance) == 0:
            score += 20
        elif len(budget_compliance) <= 3:
            score += 15
        elif len(budget_compliance) <= 6:
            score += 10

        return min(score, 100)


class CashFlowPredictor:
    """
    Predict cash flow based on historical data
    """

    @staticmethod
    def predict_next_period(bank_account, periods_ahead=1):
        """
        Predict cash flow for the next period(s)
        """
        from finance.models import Transaction

        # Get historical transactions
        lookback_days = 90
        historical_txns = Transaction.objects.filter(
            bank_account=bank_account,
            transaction_date__gte=timezone.now().date() - timedelta(days=lookback_days)
        )

        # Calculate averages
        avg_inflow = historical_txns.filter(
            transaction_type='DEPOSIT'
        ).aggregate(avg=Avg('amount'))['avg'] or Decimal('0')

        avg_outflow = historical_txns.filter(
            transaction_type='WITHDRAWAL'
        ).aggregate(avg=Avg('amount'))['avg'] or Decimal('0')

        # Count transactions
        inflow_count = historical_txns.filter(transaction_type='DEPOSIT').count()
        outflow_count = historical_txns.filter(transaction_type='WITHDRAWAL').count()

        # Predict
        predicted_inflow = avg_inflow * (inflow_count / 90) * 30 * periods_ahead
        predicted_outflow = avg_outflow * (outflow_count / 90) * 30 * periods_ahead

        current_balance = bank_account.current_balance
        predicted_balance = current_balance + predicted_inflow - predicted_outflow

        return {
            'current_balance': float(current_balance),
            'predicted_inflow': float(predicted_inflow),
            'predicted_outflow': float(predicted_outflow),
            'predicted_balance': float(predicted_balance),
            'confidence': 'medium'  # Would be calculated based on variance
        }


class AutomationScheduler:
    """
    Schedule and manage automated finance tasks
    """

    @staticmethod
    def get_scheduled_tasks():
        """
        Get all scheduled automation tasks
        """
        return {
            'daily': [
                'Bank reconciliation',
                'Budget monitoring',
                'AR aging update'
            ],
            'weekly': [
                'Cash flow analysis',
                'Budget variance reports',
                'Expense review'
            ],
            'monthly': [
                'Depreciation calculation',
                'Period-end closing',
                'Financial statements'
            ]
        }

    @staticmethod
    def execute_daily_tasks():
        """
        Execute all daily automation tasks
        """
        from finance.tasks import (
            auto_reconcile_transactions_task,
            monitor_budget_alerts_task,
            smart_ar_reminder_task
        )

        tasks = []

        # Queue tasks
        tasks.append(auto_reconcile_transactions_task.delay())
        tasks.append(monitor_budget_alerts_task.delay())
        tasks.append(smart_ar_reminder_task.delay())

        return tasks