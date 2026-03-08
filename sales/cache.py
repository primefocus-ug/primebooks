"""
sales/cache.py
──────────────
Central cache key definitions and invalidation signals for the sales app.

Add to your app config (sales/apps.py):

    def ready(self):
        import sales.cache  # noqa — registers signals

Usage in settings.py:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": env("REDIS_URL", default="redis://127.0.0.1:6379/1"),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "PARSER_CLASS": "redis.connection.HiredisParser",   # pip install hiredis
                "CONNECTION_POOL_KWARGS": {
                    "max_connections": 50,
                },
                "COMPRESSOR": "django_redis.compressors.zlib.ZlibCompressor",
                "IGNORE_EXCEPTIONS": True,  # degrade gracefully, never crash
            },
            "KEY_PREFIX": "sales",
            "TIMEOUT": 300,
        }
    }
"""

from django.core.cache import cache
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

# ── Key builders ──────────────────────────────────────────────────────────────

def sale_stats_key(store_ids_str: str, date_str: str) -> str:
    """Per-store-set, per-day stats aggregate. Invalidated on every sale save."""
    return f"sale_stats:{store_ids_str}:{date_str}"


def sale_doc_type_key(store_ids_str: str, date_str: str) -> str:
    return f"sale_doc_type_stats:{store_ids_str}:{date_str}"


def sale_pay_stats_key(store_ids_str: str, date_str: str) -> str:
    return f"sale_pay_stats:{store_ids_str}:{date_str}"


def sale_store_perf_key(store_ids_str: str, date_str: str) -> str:
    return f"sale_store_perf:{store_ids_str}:{date_str}"


def sale_top_cust_key(store_ids_str: str, date_str: str) -> str:
    return f"sale_top_cust:{store_ids_str}:{date_str}"


def sale_efris_latest_key(store_ids_str: str) -> str:
    return f"sale_efris_latest:{store_ids_str}"


def product_catalogue_key(store_id: int) -> str:
    """Product catalogue per store. Invalidated when any product changes."""
    return f"product_catalogue:{store_id}"


def user_stores_key(user_id: int) -> str:
    """Store access list per user. Invalidated on permission change."""
    return f"user_stores:{user_id}"


# ── Invalidation helpers ──────────────────────────────────────────────────────

def _invalidate_sale_stats_for_store(store_id: int) -> None:
    """
    Delete all stats cache entries that include this store.
    We use a wildcard delete via django-redis's delete_pattern.
    Falls back to a targeted key delete if delete_pattern is unavailable.
    """
    date_str = timezone.now().strftime('%Y-%m-%d')
    prefixes = [
        f"sale_stats:*{store_id}*:{date_str}",
        f"sale_doc_type_stats:*{store_id}*:{date_str}",
        f"sale_pay_stats:*{store_id}*:{date_str}",
        f"sale_store_perf:*{store_id}*:{date_str}",
        f"sale_top_cust:*{store_id}*:{date_str}",
        f"sale_efris_latest:*{store_id}*",
    ]
    try:
        for pattern in prefixes:
            cache.delete_pattern(f":{pattern}")  # django-redis adds KEY_PREFIX
    except AttributeError:
        # delete_pattern not available (non-Redis backend) — skip silently
        pass


# ── Signal receivers ─────────────────────────────────────────────────────────

# Lazy import to avoid circular imports at module load time.
def _get_sale_model():
    from django.apps import apps
    return apps.get_model('sales', 'Sale')


def _register_signals():
    Sale = _get_sale_model()

    @receiver(post_save, sender=Sale, dispatch_uid='sales.cache.invalidate_on_save')
    @receiver(post_delete, sender=Sale, dispatch_uid='sales.cache.invalidate_on_delete')
    def invalidate_sale_stats(sender, instance, **kwargs):
        """Bust stats cache whenever a sale is created, updated, or deleted."""
        try:
            _invalidate_sale_stats_for_store(instance.store_id)
        except Exception as e:
            # Never let cache invalidation crash the main request
            logger.warning(f"Cache invalidation failed for sale {instance.pk}: {e}")


_register_signals()