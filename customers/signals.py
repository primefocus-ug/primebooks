# customers/signals.py
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Customer, CustomerGroup
from .tasks import register_customer_with_efris, enrich_customer_from_efris
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Customer)
def handle_customer_efris_sync(sender, instance, created, **kwargs):
    """Handle EFRIS sync when customer is created or updated"""

    # Check if company has EFRIS enabled
    company = getattr(instance, 'company', None)
    if not company and hasattr(instance, 'store'):
        company = getattr(instance.store, 'company', None)

    if not company or not getattr(company, 'efris_enabled', False):
        return

    if created:
        # New customer - check if should auto-register
        can_sync, error = instance.can_sync_to_efris()
        if can_sync:
            # Check if customer is in a group with auto-sync enabled
            auto_sync_groups = instance.groups.filter(auto_sync_to_efris=True)
            if auto_sync_groups.exists():
                logger.info(f"Scheduling EFRIS registration for new customer {instance.name}")
                register_customer_with_efris.delay(instance.id)

            # Auto-enrich if customer has TIN
            elif getattr(instance, 'tin', None):
                logger.info(f"Scheduling EFRIS enrichment for customer with TIN {instance.tin}")
                enrich_customer_from_efris.delay(instance.id)
        else:
            logger.info(f"Customer {instance.name} not ready for EFRIS sync: {error}")

    else:
        # Existing customer updated
        try:
            old_instance = Customer.objects.get(pk=instance.pk)

            # Check if TIN was added
            if not getattr(old_instance, 'tin', None) and getattr(instance, 'tin', None):
                logger.info(f"TIN added for customer {instance.name}, scheduling enrichment")
                enrich_customer_from_efris.delay(instance.id)

            # Check if customer became ready for EFRIS sync
            old_can_sync, _ = old_instance.can_sync_to_efris()
            new_can_sync, _ = instance.can_sync_to_efris()

            if not old_can_sync and new_can_sync and instance.efris_status == 'NOT_REGISTERED':
                # Check if in auto-sync group
                auto_sync_groups = instance.groups.filter(auto_sync_to_efris=True)
                if auto_sync_groups.exists():
                    logger.info(f"Customer {instance.name} now ready for EFRIS registration")
                    register_customer_with_efris.delay(instance.id)

        except Customer.DoesNotExist:
            pass


@receiver(post_save, sender=CustomerGroup)
def handle_customer_group_efris_sync(sender, instance, created, **kwargs):
    """Handle EFRIS sync when customer group auto-sync settings change"""

    if not created:
        try:
            old_instance = CustomerGroup.objects.get(pk=instance.pk)

            # Check if auto-sync was enabled for this group
            if not old_instance.auto_sync_to_efris and instance.auto_sync_to_efris:
                logger.info(f"Auto-sync enabled for group {instance.name}, registering customers")

                # Register all eligible customers in this group
                eligible_customers = instance.customers.filter(
                    efris_status='NOT_REGISTERED'
                )

                for customer in eligible_customers:
                    can_sync, _ = customer.can_sync_to_efris()
                    if can_sync:
                        register_customer_with_efris.delay(customer.id)

        except CustomerGroup.DoesNotExist:
            pass

