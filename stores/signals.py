from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import Store,DeviceOperatorLog


@receiver(post_save, sender=Store)
def store_efris_setup(sender, instance, created, **kwargs):
    """Handle EFRIS setup when store is created or updated"""
    if created and instance.efris_enabled:
        # Log store creation for EFRIS
        if hasattr(instance, '_current_user'):
            DeviceOperatorLog.objects.create(
                user=instance._current_user,
                action='OTHER',
                store=instance,
                details={'message': 'EFRIS-enabled store created'},
                is_efris_related=True
            )

