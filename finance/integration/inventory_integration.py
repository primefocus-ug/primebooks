from inventory.models import StockMovement
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
from sales.models import Sale
from finance.models import Journal, JournalEntry, JournalEntryLine, ChartOfAccounts
from decimal import Decimal

@receiver(post_save, sender=StockMovement)
def create_journal_entry_for_inventory(sender, instance, created, **kwargs):
    """
    Create journal entry for inventory movements (COGS)
    """
    if not created:
        return

    # Only for sales movements
    if instance.movement_type != 'SALE':
        return

    journal = Journal.objects.filter(
        journal_type='GENERAL',
        is_active=True
    ).first()

    if not journal:
        return

    with transaction.atomic():
        entry = JournalEntry.objects.create(
            journal=journal,
            entry_date=instance.created_at.date(),
            description=f"COGS for {instance.product.name}",
            reference=instance.reference,
            created_by=instance.created_by,
            source_model='inventory.StockMovement',
            source_id=str(instance.id)
        )

        try:
            # Debit: Cost of Goods Sold
            cogs_account = ChartOfAccounts.objects.get(
                code='5000',
                is_active=True
            )

            # Credit: Inventory
            inventory_account = ChartOfAccounts.objects.get(
                code='1300',
                is_active=True
            )
        except ChartOfAccounts.DoesNotExist:
            entry.delete()
            return

        # Calculate cost
        cost = instance.unit_price * instance.quantity if instance.unit_price else Decimal('0')

        if cost > 0:
            # Debit: COGS
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=cogs_account,
                debit_amount=cost,
                description=f"Cost of {instance.product.name} sold",
                cost_center=instance.store.cost_centers.first() if hasattr(instance.store, 'cost_centers') else None
            )

            # Credit: Inventory
            JournalEntryLine.objects.create(
                journal_entry=entry,
                account=inventory_account,
                credit_amount=cost,
                description=f"Inventory reduction - {instance.product.name}"
            )

            # Auto-post
            try:
                entry.post(instance.created_by)
            except Exception:
                pass