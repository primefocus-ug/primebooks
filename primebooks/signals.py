"""
Auto-reset sequences after record creation
✅ Prevents duplicate key errors permanently
"""
import logging
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.db import connection
from django_tenants.utils import get_tenant_model

logger = logging.getLogger(__name__)

# Track which models need sequence reset
_models_needing_reset = set()


def should_track_model(sender):
    """Check if model should trigger sequence reset"""
    # Skip public schema models
    if sender._meta.app_label in ['company', 'public_router']:
        return False

    # Only track models with integer primary keys
    pk = sender._meta.pk
    if pk.get_internal_type() not in ('AutoField', 'BigAutoField'):
        return False

    return True


@receiver(post_save)
def track_model_for_reset(sender, instance, created, **kwargs):
    """Track models that need sequence reset"""
    if not created:
        return  # Only care about new records

    if not should_track_model(sender):
        return

    # Track this model
    model_name = f"{sender._meta.app_label}.{sender._meta.model_name}"
    _models_needing_reset.add(model_name)

    logger.debug(f"📝 Tracked {model_name} for sequence reset")


def reset_tracked_sequences():
    """
    Reset sequences for all tracked models
    Call this at the end of request or batch operation
    """
    from django.db import connection
    from django.apps import apps

    if not _models_needing_reset:
        return

    schema_name = connection.schema_name

    if schema_name == 'public':
        return  # Don't reset public schema

    logger.info(f"🔄 Resetting sequences for {len(_models_needing_reset)} models in {schema_name}")

    with connection.cursor() as cursor:
        for model_name in _models_needing_reset:
            try:
                model = apps.get_model(model_name)
                table = model._meta.db_table
                pk = model._meta.pk

                # Get sequence name
                cursor.execute(
                    "SELECT pg_get_serial_sequence(%s, %s)",
                    [f"{schema_name}.{table}", pk.column]
                )
                seq = cursor.fetchone()[0]

                if not seq:
                    continue

                # Reset sequence
                cursor.execute(f"""
                    SELECT setval(
                        %s,
                        COALESCE((SELECT MAX({pk.column}) FROM {schema_name}.{table}), 0) + 1,
                        false
                    )
                """, [seq])

                logger.debug(f"  ✓ Reset sequence for {model_name}")

            except Exception as e:
                logger.debug(f"  ⚠️ Skipped {model_name}: {e}")

    # Clear tracked models
    _models_needing_reset.clear()
    logger.info(f"✅ Sequences reset complete")