from django.db.models.signals import post_save, pre_save, post_delete, pre_delete
from django.dispatch import receiver
from django.db import transaction as db_transaction
from django.core.exceptions import ValidationError
from decimal import Decimal
import logging
import json

from .models import (
    JournalEntry, JournalEntryLine, Transaction, BankAccount,
    FixedAsset, FiscalPeriod, Budget, BudgetLine, Currency,
    ExchangeRate, ChartOfAccounts, AuditLog, FiscalYear
)

logger = logging.getLogger(__name__)


# ============================================
# JOURNAL ENTRY SIGNALS
# ============================================

@receiver(post_save, sender=JournalEntry)
def journal_entry_posted(sender, instance, created, **kwargs):
    """
    Handle journal entry status changes
    """
    if instance.status == 'POSTED' and not created:
        logger.info(f'Journal entry {instance.entry_number} posted')

        # Create audit log
        AuditLog.objects.create(
            model_name='JournalEntry',
            object_id=str(instance.pk),
            action='POST',
            user=instance.posted_by,
            changes_json={'status': 'POSTED', 'posted_at': str(instance.posted_at)}
        )

        # Send notification if notifications app exists
        try:
            from notifications.models import Notification

            # Notify creator
            if instance.created_by:
                Notification.objects.create(
                    user=instance.created_by,
                    title='Journal Entry Posted',
                    message=f'Journal entry {instance.entry_number} has been posted successfully.',
                    notification_type='JOURNAL_POSTED',
                    related_object_id=str(instance.pk)
                )

            # Notify approver if applicable
            if instance.approved_by and instance.approved_by != instance.posted_by:
                Notification.objects.create(
                    user=instance.approved_by,
                    title='Journal Entry Posted',
                    message=f'Journal entry {instance.entry_number} that you approved has been posted.',
                    notification_type='JOURNAL_POSTED',
                    related_object_id=str(instance.pk)
                )
        except ImportError:
            pass  # Notifications module doesn't exist


@receiver(post_save, sender=JournalEntryLine)
def journal_entry_line_saved(sender, instance, created, **kwargs):
    """
    Update entry totals when lines change
    """
    if not created:
        # Recalculate entry totals
        instance.journal_entry.calculate_totals()


@receiver(post_delete, sender=JournalEntryLine)
def journal_entry_line_deleted(sender, instance, **kwargs):
    """
    Update entry totals when lines are deleted
    """
    if instance.journal_entry:
        instance.journal_entry.calculate_totals()


# ============================================
# BUDGET MONITORING SIGNALS
# ============================================

@receiver(post_save, sender=JournalEntryLine)
def check_budget_utilization(sender, instance, created, **kwargs):
    """
    Check budget utilization when entry is posted
    Alert if budget is exceeded
    """
    if instance.journal_entry.status == 'POSTED':
        from .models import AccountType

        # Only check expense accounts
        if instance.account.account_type != AccountType.EXPENSE:
            return

        try:
            # Get dimension values for this line
            dimension_values = list(instance.dimension_values.all())

            # Find applicable budget line
            budget_lines = BudgetLine.objects.filter(
                account=instance.account,
                budget__status='ACTIVE',
                budget__start_date__lte=instance.journal_entry.entry_date,
                budget__end_date__gte=instance.journal_entry.entry_date
            )

            # Filter by dimensions if present
            for dim_value in dimension_values:
                budget_lines = budget_lines.filter(dimension_values=dim_value)

            for budget_line in budget_lines:
                utilization = budget_line.get_utilization_percentage()

                # Alert if over threshold
                if utilization >= budget_line.budget.alert_threshold:
                    logger.warning(
                        f'Budget alert: {instance.account.code} at {utilization:.1f}% utilization'
                    )

                    try:
                        from notifications.models import Notification

                        # Notify budget owner
                        if budget_line.budget.created_by:
                            Notification.objects.create(
                                user=budget_line.budget.created_by,
                                title='Budget Alert',
                                message=f'Budget for {instance.account.name} is at {utilization:.1f}% utilization.',
                                notification_type='BUDGET_ALERT',
                                priority='HIGH'
                            )

                        # Notify dimension managers
                        for dim_value in dimension_values:
                            if dim_value.manager:
                                Notification.objects.create(
                                    user=dim_value.manager,
                                    title='Budget Alert',
                                    message=f'Budget for {instance.account.name} in {dim_value.name} is at {utilization:.1f}% utilization.',
                                    notification_type='BUDGET_ALERT',
                                    priority='HIGH'
                                )
                    except ImportError:
                        pass

        except Exception as e:
            logger.error(f'Error checking budget utilization: {str(e)}')


@receiver(post_save, sender=Budget)
def budget_status_changed(sender, instance, created, **kwargs):
    """
    Handle budget status changes
    """
    if created:
        logger.info(f'Budget {instance.name} created')

        AuditLog.objects.create(
            model_name='Budget',
            object_id=str(instance.pk),
            action='CREATE',
            user=instance.created_by,
            changes_json={'name': instance.name, 'status': instance.status}
        )

    if instance.status == 'APPROVED' and not created:
        logger.info(f'Budget {instance.name} approved')

        try:
            from notifications.models import Notification

            # Notify creator
            if instance.created_by:
                Notification.objects.create(
                    user=instance.created_by,
                    title='Budget Approved',
                    message=f'Budget "{instance.name}" has been approved.',
                    notification_type='BUDGET_APPROVED'
                )
        except ImportError:
            pass


# ============================================
# TRANSACTION SIGNALS
# ============================================

@receiver(post_save, sender=Transaction)
def transaction_created(sender, instance, created, **kwargs):
    """
    Handle transaction creation
    Update bank account balance
    """
    if created:
        logger.info(f'Transaction {instance.transaction_id} created')

        # Update bank account balance
        instance.bank_account.update_balance()

        AuditLog.objects.create(
            model_name='Transaction',
            object_id=str(instance.pk),
            action='CREATE',
            user=instance.created_by,
            changes_json={
                'transaction_id': instance.transaction_id,
                'amount': str(instance.amount),
                'type': instance.transaction_type
            }
        )


@receiver(post_save, sender=BankAccount)
def bank_account_default_changed(sender, instance, **kwargs):
    """
    Ensure only one default bank account per currency
    """
    if instance.is_default:
        # Set all other accounts in same currency to non-default
        BankAccount.objects.filter(
            currency=instance.currency
        ).exclude(pk=instance.pk).update(is_default=False)


# ============================================
# FIXED ASSET SIGNALS
# ============================================

@receiver(post_save, sender=FixedAsset)
def fixed_asset_activated(sender, instance, created, **kwargs):
    """
    Handle fixed asset activation
    Create initial journal entry
    """
    if created and instance.status == 'ACTIVE':
        logger.info(f'Fixed asset {instance.asset_number} activated')

        try:
            from .models import Journal, JournalType

            # Get general journal
            journal = Journal.objects.filter(
                journal_type=JournalType.GENERAL,
                is_active=True
            ).first()

            if journal:
                with db_transaction.atomic():
                    # Create asset acquisition entry
                    entry = JournalEntry.objects.create(
                        journal=journal,
                        entry_number=journal.get_next_entry_number(),
                        entry_date=instance.purchase_date,
                        description=f'Acquisition of {instance.name}',
                        reference=instance.asset_number,
                        currency=instance.currency,
                        created_by=instance.created_by,
                        source_model='finance.FixedAsset',
                        source_id=str(instance.pk)
                    )

                    # Get fiscal period
                    fiscal_period = FiscalPeriod.objects.filter(
                        start_date__lte=instance.purchase_date,
                        end_date__gte=instance.purchase_date
                    ).first()

                    if fiscal_period:
                        entry.fiscal_period = fiscal_period
                        entry.fiscal_year = fiscal_period.fiscal_year
                        entry.save()

                        # Debit: Asset Account
                        JournalEntryLine.objects.create(
                            journal_entry=entry,
                            account=instance.category.asset_account,
                            debit_amount=instance.purchase_cost,
                            currency=instance.currency,
                            description=f'Asset acquisition - {instance.name}'
                        )

                        # Credit would typically be cash/AP - handled separately

                        logger.info(f'Asset acquisition entry created: {entry.entry_number}')

        except Exception as e:
            logger.error(f'Error creating asset acquisition entry: {str(e)}')


# ============================================
# FISCAL PERIOD SIGNALS
# ============================================

@receiver(pre_save, sender=FiscalPeriod)
def fiscal_period_closing(sender, instance, **kwargs):
    """
    Validate before closing period
    """
    if instance.pk:
        try:
            old_instance = FiscalPeriod.objects.get(pk=instance.pk)

            # Check if status changed to CLOSED
            if old_instance.status == 'OPEN' and instance.status == 'CLOSED':
                logger.info(f'Closing fiscal period {instance.name}')

                # Check for unposted entries
                unposted_count = JournalEntry.objects.filter(
                    fiscal_period=instance,
                    status__in=['DRAFT', 'PENDING']
                ).count()

                if unposted_count > 0:
                    raise ValidationError(
                        f'Cannot close period: {unposted_count} unposted entries exist'
                    )
        except FiscalPeriod.DoesNotExist:
            pass


@receiver(post_save, sender=FiscalPeriod)
def fiscal_period_closed(sender, instance, **kwargs):
    """
    After fiscal period is closed
    """
    if instance.status == 'CLOSED':
        logger.info(f'Fiscal period {instance.name} closed')

        AuditLog.objects.create(
            model_name='FiscalPeriod',
            object_id=str(instance.pk),
            action='CLOSE',
            user=instance.closed_by,
            changes_json={'status': 'CLOSED', 'closed_at': str(instance.closed_at)}
        )

        try:
            from notifications.models import Notification
            from django.contrib.auth import get_user_model
            User = get_user_model()

            # Notify finance team
            finance_users = User.objects.filter(
                groups__permissions__codename='change_fiscalperiod',
                is_active=True
            ).distinct()

            for user in finance_users:
                Notification.objects.create(
                    user=user,
                    title='Fiscal Period Closed',
                    message=f'Fiscal period {instance.name} has been closed.',
                    notification_type='PERIOD_CLOSED'
                )
        except ImportError:
            pass


# ============================================
# CURRENCY & EXCHANGE RATE SIGNALS
# ============================================

@receiver(post_save, sender=Currency)
def currency_base_changed(sender, instance, **kwargs):
    """
    Ensure only one base currency
    """
    if instance.is_base:
        Currency.objects.exclude(pk=instance.pk).update(is_base=False)
        logger.info(f'Base currency set to {instance.code}')


@receiver(post_save, sender=ExchangeRate)
def exchange_rate_updated(sender, instance, created, **kwargs):
    """
    Log exchange rate updates
    """
    if created:
        logger.info(
            f'Exchange rate created: {instance.from_currency.code}/{instance.to_currency.code} = {instance.rate}'
        )


# ============================================
# ACCOUNT BALANCE UPDATES
# ============================================

@receiver(post_save, sender=JournalEntry)
def update_account_balances_on_post(sender, instance, **kwargs):
    """
    Update account balances when entry is posted
    """
    if instance.status == 'POSTED':
        # Update all affected accounts
        for line in instance.lines.all():
            try:
                line.account.update_balance()
            except Exception as e:
                logger.error(f'Error updating balance for {line.account.code}: {str(e)}')


# ============================================
# AUDIT TRAIL (COMPREHENSIVE)
# ============================================

@receiver(pre_save)
def create_audit_trail(sender, instance, **kwargs):
    """
    Create comprehensive audit trail for important models
    """
    # Models to audit
    audited_models = [
        'JournalEntry', 'Transaction', 'FixedAsset',
        'Budget', 'FiscalPeriod', 'FiscalYear', 'BankAccount',
        'ChartOfAccounts'
    ]

    if sender.__name__ not in audited_models:
        return

    if instance.pk:
        try:
            old_instance = sender.objects.get(pk=instance.pk)

            # Track changes
            changes = {}
            for field in instance._meta.fields:
                if field.name in ['updated_at', 'created_at']:
                    continue

                old_value = getattr(old_instance, field.name, None)
                new_value = getattr(instance, field.name, None)

                if old_value != new_value:
                    changes[field.name] = {
                        'old': str(old_value) if old_value is not None else None,
                        'new': str(new_value) if new_value is not None else None
                    }

            if changes:
                # Get user from instance if available
                user = None
                for attr in ['updated_by', 'created_by', 'posted_by', 'approved_by']:
                    if hasattr(instance, attr):
                        user = getattr(instance, attr)
                        if user:
                            break

                AuditLog.objects.create(
                    model_name=sender.__name__,
                    object_id=str(instance.pk),
                    action='UPDATE',
                    user=user,
                    changes_json=changes
                )

                logger.debug(
                    f'Audit: {sender.__name__} {instance.pk} modified. Changes: {len(changes)} fields'
                )

        except sender.DoesNotExist:
            pass
        except Exception as e:
            logger.error(f'Error in audit trail: {str(e)}')


@receiver(post_delete)
def log_deletion(sender, instance, **kwargs):
    """
    Log deletions of important objects
    """
    audited_models = [
        'JournalEntry', 'Transaction', 'FixedAsset',
        'Budget', 'BankAccount', 'ChartOfAccounts'
    ]

    if sender.__name__ in audited_models:
        # Get user from current request if possible
        user = None
        if hasattr(instance, '_deletion_user'):
            user = instance._deletion_user

        AuditLog.objects.create(
            model_name=sender.__name__,
            object_id=str(instance.pk),
            action='DELETE',
            user=user,
            changes_json={'deleted_object': str(instance)}
        )

        logger.warning(f'{sender.__name__} {instance.pk} deleted')


# ============================================
# VALIDATION SIGNALS
# ============================================

@receiver(pre_save, sender=ChartOfAccounts)
def validate_account_hierarchy(sender, instance, **kwargs):
    """
    Prevent circular parent references
    """
    if instance.parent:
        parent = instance.parent
        depth = 0
        max_depth = 10

        while parent and depth < max_depth:
            if parent == instance:
                raise ValidationError('Circular parent reference detected')
            parent = parent.parent
            depth += 1

        if depth >= max_depth:
            raise ValidationError('Account hierarchy too deep')


@receiver(pre_save, sender=BudgetLine)
def validate_budget_line(sender, instance, **kwargs):
    """
    Validate budget line before saving
    """
    # Ensure amount is positive
    if instance.amount < 0:
        raise ValidationError('Budget amount cannot be negative')

    # Ensure account is of type that can be budgeted
    from .models import AccountType
    if instance.account.account_type not in [AccountType.EXPENSE, AccountType.REVENUE]:
        raise ValidationError('Can only budget for expense and revenue accounts')