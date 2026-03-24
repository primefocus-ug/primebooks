"""
Auto-reset sequences after record creation.
Prevents duplicate key errors after bulk inserts or tenant data migrations.

Key correctness rules for django-tenants:
  - SHARED_APPS tables live in the public schema only.
  - TENANT_APPS tables live in each tenant schema.
  - Trying pg_get_serial_sequence('rem.pesapal_integration_...') always fails
    because that relation does not exist in the tenant schema — it is only in
    public. The fix: classify every tracked model against settings.SHARED_APPS
    at reset time and route it to the correct schema.
"""
import logging
import threading

from django.conf import settings
from django.db import connection
from django.db.models.signals import post_save
from django.dispatch import receiver

logger = logging.getLogger(__name__)

# ── Thread-local tracking ─────────────────────────────────────────────────────
# The original code used a module-level set — shared across all threads.
# A model saved in one request (e.g. TenantPaymentTransaction during a Pesapal
# flow) would still be in the set when the *next* request called
# reset_tracked_sequences() under a different schema, causing the wrong-schema
# lookup and the "relation does not exist" warning.
#
# thread_local.models_needing_reset is a set that exists only for the lifetime
# of the current thread/request and is never visible to other threads.
_local = threading.local()


def _get_tracked() -> set:
    """Return the per-thread tracking set, creating it if needed."""
    if not hasattr(_local, 'models_needing_reset'):
        _local.models_needing_reset = set()
    return _local.models_needing_reset


# ── Shared-app label cache ────────────────────────────────────────────────────
# Built once at import time from settings — no DB queries.
# SHARED_APPS entries can be plain labels ('pesapal_integration') or dotted
# paths ('pesapal_integration.apps.PesapalConfig'). Normalise to app label.
def _extract_app_label(app_string: str) -> str:
    return app_string.split('.')[0]


_SHARED_APP_LABELS: frozenset = frozenset(
    _extract_app_label(a) for a in getattr(settings, 'SHARED_APPS', [])
)

# Apps that should never participate in sequence resets at all.
_ALWAYS_SKIP: frozenset = frozenset([
    'contenttypes', 'auth', 'sessions', 'admin', 'sites',
])


def _is_shared_model(app_label: str) -> bool:
    """True if this model's table lives in public, not the tenant schema."""
    return app_label in _SHARED_APP_LABELS


def should_track_model(sender) -> bool:
    """Return True if this model's sequences should be reset after inserts."""
    app_label = sender._meta.app_label

    if app_label in _ALWAYS_SKIP:
        return False

    pk = sender._meta.pk
    if pk is None:
        return False
    if pk.get_internal_type() not in ('AutoField', 'BigAutoField'):
        return False

    return True


@receiver(post_save)
def track_model_for_reset(sender, instance, created, **kwargs):
    """Track newly-created records so their sequences get reset at end of request."""
    if not created:
        return

    if not should_track_model(sender):
        return

    model_name = f"{sender._meta.app_label}.{sender._meta.model_name}"
    _get_tracked().add(model_name)
    logger.debug(f"📝 Tracked {model_name} for sequence reset")


def reset_tracked_sequences():
    """
    Reset PostgreSQL sequences for all models tracked in this request/thread.

    Routing:
      - SHARED_APPS models  → reset against public schema
      - TENANT_APPS models  → reset against the current tenant schema

    Call this at the end of every request (e.g. from middleware or a signal).
    The tracking set is cleared afterwards so the next request starts clean.
    """
    from django.apps import apps

    tracked = _get_tracked()
    if not tracked:
        return

    current_schema = getattr(connection, 'schema_name', 'public')

    public_models = []
    tenant_models = []

    for model_name in tracked:
        app_label = model_name.split('.')[0]
        if _is_shared_model(app_label):
            public_models.append(model_name)
        else:
            tenant_models.append(model_name)

    total = len(public_models) + len(tenant_models)
    logger.info(
        f"🔄 Resetting sequences for {total} models "
        f"({len(tenant_models)} tenant in '{current_schema}', "
        f"{len(public_models)} shared in 'public')"
    )

    if public_models:
        _reset_sequences_in_schema(apps, public_models, 'public')

    if tenant_models and current_schema != 'public':
        _reset_sequences_in_schema(apps, tenant_models, current_schema)
    elif tenant_models and current_schema == 'public':
        logger.debug(
            f"Skipping tenant sequence reset — current schema is public. "
            f"Models skipped: {tenant_models}"
        )

    tracked.clear()
    logger.info("✅ Sequences reset complete")


def _reset_sequences_in_schema(apps, model_names: list, schema: str):
    """Execute pg_get_serial_sequence + setval for each model in the given schema."""
    with connection.cursor() as cursor:
        for model_name in model_names:
            try:
                model = apps.get_model(model_name)
                table = model._meta.db_table
                pk_col = model._meta.pk.column

                # Fully-qualify the table name so PostgreSQL looks in the
                # right schema regardless of the current search_path.
                fq_table = f'"{schema}"."{table}"'

                cursor.execute(
                    "SELECT pg_get_serial_sequence(%s, %s)",
                    [fq_table, pk_col]
                )
                row = cursor.fetchone()
                seq = row[0] if row else None

                if not seq:
                    logger.debug(f"  — No sequence for {model_name} in {schema}")
                    continue

                cursor.execute(
                    f"""
                    SELECT setval(
                        %s,
                        COALESCE((SELECT MAX({pk_col}) FROM {fq_table}), 0) + 1,
                        false
                    )
                    """,
                    [seq]
                )

                logger.debug(f"  ✓ Reset sequence for {model_name} in {schema}")

            except Exception as e:
                # WARNING not DEBUG — real failures should be visible in logs
                logger.warning(f"  ⚠️ Skipped {model_name} in {schema}: {e}")