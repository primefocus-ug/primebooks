from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import connection
from django.utils.functional import SimpleLazyObject
from .services import EncryptionService
from accounts.models import CustomUser
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender=CustomUser)
def create_user_encryption_keys(sender, instance, created, **kwargs):
    """
    Automatically generate encryption keys when a CustomUser is created.

    TENANT-AWARE: Only generates keys for CustomUser in tenant schemas.
    This signal is explicitly bound to CustomUser, so it won't fire for PublicUser.
    """
    # Skip if not a new user
    if not created:
        return

    # Skip if in public schema (shouldn't happen, but extra safety)
    if connection.schema_name == 'public':
        logger.warning(f"CustomUser created in public schema - this shouldn't happen: {instance}")
        return

    # Generate encryption keys
    try:
        EncryptionService.generate_user_keys(instance)
        logger.info(f"Generated encryption keys for CustomUser {instance.id} in schema {connection.schema_name}")
    except Exception as e:
        logger.error(f"Failed to generate encryption keys for user {instance.id}: {e}")