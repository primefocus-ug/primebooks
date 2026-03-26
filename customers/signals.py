# customers/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Customer, CustomerGroup
from .tasks import register_customer_with_efris, enrich_customer_from_efris
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Customer)
def handle_customer_efris_sync(sender, instance, created, **kwargs):
    """Handle EFRIS sync when customer is created or updated"""

    company = getattr(instance, 'company', None)
    if not company and hasattr(instance, 'store'):
        company = getattr(instance.store, 'company', None)

    if not company or not getattr(company, 'efris_enabled', False):
        return

    if created:
        can_sync, errors = instance.validate_for_efris()
        if can_sync:
            auto_sync_groups = instance.groups.filter(auto_sync_to_efris=True)
            if auto_sync_groups.exists():
                logger.info(f"Scheduling EFRIS registration for new customer {instance.name}")
                register_customer_with_efris.delay(instance.id)
            elif getattr(instance, 'tin', None):
                logger.info(f"Scheduling EFRIS enrichment for customer with TIN {instance.tin}")
                enrich_customer_from_efris.delay(instance.id)
        else:
            logger.info(f"Customer {instance.name} not ready for EFRIS sync: {', '.join(errors)}")

    else:
        try:
            old_instance = Customer.objects.get(pk=instance.pk)

            if not getattr(old_instance, 'tin', None) and getattr(instance, 'tin', None):
                logger.info(f"TIN added for customer {instance.name}, scheduling enrichment")
                enrich_customer_from_efris.delay(instance.id)

            old_can_sync, _ = old_instance.validate_for_efris()
            new_can_sync, _ = instance.validate_for_efris()

            if not old_can_sync and new_can_sync and instance.efris_status == 'NOT_REGISTERED':
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

            if not old_instance.auto_sync_to_efris and instance.auto_sync_to_efris:
                logger.info(f"Auto-sync enabled for group {instance.name}, registering customers")

                eligible_customers = instance.customers.filter(efris_status='NOT_REGISTERED')

                for customer in eligible_customers:
                    can_sync, _ = customer.validate_for_efris()
                    if can_sync:
                        register_customer_with_efris.delay(customer.id)

        except CustomerGroup.DoesNotExist:
            pass