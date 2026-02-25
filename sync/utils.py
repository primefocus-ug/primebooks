"""
sync/utils.py
=============
Shared helpers used by both pull and push views.

Key responsibility: sync_id normalisation.

Django models have id (int PK) + sync_id (UUID, nullable on old records).
Old records may have sync_id = NULL. We auto-generate a deterministic UUID
for them so the desktop can always use sync_id as a stable identifier.

Deterministic UUID formula:
  uuid5(NAMESPACE_URL, "{schema_name}:{table}:{pk}")

This is the SAME formula used in the desktop login_screen.py, so
records created on the server before sync_id existed will still match
records that were pulled to the desktop if the desktop ever received
their integer pk.
"""

import uuid
import time
import logging
from datetime import datetime, timezone as tz
from typing import Optional, Any

logger = logging.getLogger(__name__)

SYNC_ID_NAMESPACE = uuid.NAMESPACE_URL


# ─────────────────────────────────────────────────────────────────────────────
# sync_id helpers
# ─────────────────────────────────────────────────────────────────────────────

def ensure_sync_id(instance, table_name: str, schema_name: str = "") -> str:
    """
    Return the instance's sync_id, generating + saving one if it's NULL.

    Deterministic: same pk + table + schema always gives the same UUID.
    Safe to call repeatedly — only writes to DB if sync_id was NULL.
    """
    if instance.sync_id:
        return str(instance.sync_id)

    # Generate deterministic UUID from schema + table + integer pk
    seed = f"{schema_name}:{table_name}:{instance.pk}"
    new_id = str(uuid.uuid5(SYNC_ID_NAMESPACE, seed))

    # Persist immediately so future pulls are consistent
    type(instance).objects.filter(pk=instance.pk).update(sync_id=new_id)
    instance.sync_id = new_id
    logger.debug(f"Auto-generated sync_id for {table_name}#{instance.pk}: {new_id}")
    return new_id


def parse_sync_id(value: Any) -> Optional[str]:
    """
    Safely parse a sync_id value into a normalised UUID string.
    Returns None if invalid.
    """
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Timestamp helpers
# ─────────────────────────────────────────────────────────────────────────────

def unix_to_dt(ts: Optional[float]) -> Optional[datetime]:
    """Unix float → timezone-aware datetime."""
    if not ts:
        return None
    return datetime.fromtimestamp(float(ts), tz=tz.utc)


def dt_to_unix(dt_val) -> Optional[float]:
    """datetime (aware or naive) → Unix float."""
    if not dt_val:
        return None
    if hasattr(dt_val, "timestamp"):
        return dt_val.timestamp()
    return None


def now_unix() -> float:
    return time.time()


# ─────────────────────────────────────────────────────────────────────────────
# Value coercion
# ─────────────────────────────────────────────────────────────────────────────

def safe_decimal(value: Any) -> Optional[str]:
    """
    Convert a value to a Decimal-safe string for Django model assignment.
    Returns None if value is empty/None.
    """
    if value is None or value == "":
        return None
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return None


def safe_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def safe_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() not in ("false", "0", "no", "")
    return bool(value) if value is not None else default


# ─────────────────────────────────────────────────────────────────────────────
# IP extraction
# ─────────────────────────────────────────────────────────────────────────────

def get_client_ip(request) -> Optional[str]:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")