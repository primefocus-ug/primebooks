from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from sales.models import Sale
from finance.models import Journal, JournalEntry, JournalEntryLine, ChartOfAccounts
from decimal import Decimal


@receiver(post_save, sender=Sale)
def create_journal_entry_for_sale(sender, instance, created, **kwargs):
    """
    Automatically create journal entry when sale is completed
    """
    # Only process completed sales that don't have a journal entry yet
    if not instance.is_completed or instance.is_voided:
        return

    # Check if journal entry already exists
    if JournalEntry.objects.filter(
            source_model='sales.Sale',
            source_id=str(instance.id)
    ).exists():
        return

    # Get sales journal
    journal = Journal.objects.filter(
        journal_type='SALES',
        is_active=True
    ).first()

    if not journal:
        return

    with transaction.atomic():
        # Create journal entry
        entry = JournalEntry.objects.create(
            journal=journal,
            entry_date=instance.created_at.date(),
            description=f"Sales Invoice: {instance.invoice_number}",
            reference=instance.invoice_number,
            created_by=instance.created_by,
            source_model='sales.Sale',
            source_id=str(instance.id)
        )

        # Get accounts
        try:
            # Debit: Accounts Receivable or Cash
            if instance.customer:
                ar_account = ChartOfAccounts.objects.get(
                    code='1200',  # Accounts Receivable
                    is_active=True
                )
            else:
                ar_account = ChartOfAccounts.objects.get(
                    code='1100',  # Cash
                    is_active=True
                )

            # Credit: Sales Revenue
            sales_account = ChartOfAccounts.objects.get(
                code='4000',  # Sales Revenue
                is_active=True
            )

            # Credit: Tax Payable (if applicable)
            if instance.tax_amount and instance.tax_amount > 0:
                tax_account = ChartOfAccounts.objects.get(
                    code='2300',  # Tax Payable
                    is_active=True
                )
        except ChartOfAccounts.DoesNotExist:
            # Rollback if accounts not found
            entry.delete()
            return

        # Debit line: AR/Cash for total amount
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=ar_account,
            debit_amount=instance.total_amount,
            description=f"Sale to {instance.customer.name if instance.customer else 'Cash Customer'}",
            cost_center=instance.store.cost_centers.first() if hasattr(instance.store, 'cost_centers') else None
        )

        # Credit line: Sales revenue (net of tax)
        net_sales = instance.subtotal - (instance.discount_amount or Decimal('0'))
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=sales_account,
            credit_amount=net_sales,
            description=f"Sales Revenue - Invoice {instance.invoice_number}",
            cost_center=instance.store.cost_centers.first() if hasattr(instance.store, 'cost_centers') else None
        )

        # Credit line: Tax payable (if applicable)
        if instance.tax_amount and instance.tax_amount > 0:
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=tax_account,
                credit_amount=instance.tax_amount,
                description=f"Sales Tax - Invoice {instance.invoice_number}"
            )

        # Auto-post if configured
        if journal.journal_type == 'SALES':
            try:
                entry.post(instance.created_by)
            except Exception as e:
                # Log error but don't fail the sale
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to auto-post sales journal entry: {e}")