from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .services import EncryptionService
from accounts.models import CustomUser

User = get_user_model()

@receiver(post_save, sender=User)
def create_user_encryption_keys(sender, instance, created, **kwargs):
    """
    Automatically generate encryption keys when a CustomUser is created.
    Skip PublicUser or other user types.
    """
    if created and isinstance(instance, CustomUser):
        EncryptionService.generate_user_keys(instance)
