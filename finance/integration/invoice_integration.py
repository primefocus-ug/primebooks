from invoices.models import Invoice, InvoicePayment
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from sales.models import Sale
from finance.models import Journal, JournalEntry, JournalEntryLine, ChartOfAccounts

@receiver(post_save, sender=Invoice)
def create_journal_entry_for_invoice(sender, instance, created, **kwargs):
    """
    Create journal entry when invoice is fiscalized
    """
    if not instance.is_fiscalized:
        return

    # Check if journal entry already exists
    if JournalEntry.objects.filter(
            source_model='invoices.Invoice',
            source_id=str(instance.id)
    ).exists():
        return

    # Similar to sales integration...
    pass


@receiver(post_save, sender=InvoicePayment)
def create_journal_entry_for_payment(sender, instance, created, **kwargs):
    """
    Create journal entry for invoice payment
    """
    if not created:
        return

    journal = Journal.objects.filter(
        journal_type='CASH_RECEIPTS',
        is_active=True
    ).first()

    if not journal:
        return

    with transaction.atomic():
        entry = JournalEntry.objects.create(
            journal=journal,
            entry_date=instance.payment_date,
            description=f"Payment for Invoice {instance.invoice.invoice_number}",
            reference=instance.transaction_reference,
            created_by=instance.processed_by or instance.invoice.created_by,
            source_model='invoices.InvoicePayment',
            source_id=str(instance.id)
        )

        try:
            # Debit: Cash/Bank
            cash_account = ChartOfAccounts.objects.get(
                code='1100',
                is_active=True
            )

            # Credit: Accounts Receivable
            ar_account = ChartOfAccounts.objects.get(
                code='1200',
                is_active=True
            )
        except ChartOfAccounts.DoesNotExist:
            entry.delete()
            return

        # Debit: Cash
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=cash_account,
            debit_amount=instance.amount,
            description=f"Payment received for {instance.invoice.invoice_number}"
        )

        # Credit: Accounts Receivable
        JournalEntryLine.objects.create(
            journal_entry=entry,
            account=ar_account,
            credit_amount=instance.amount,
            description=f"Payment applied to {instance.invoice.invoice_number}"
        )

        # Auto-post
        try:
            entry.post(instance.processed_by or instance.invoice.created_by)
        except Exception as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to auto-post payment journal entry: {e}")