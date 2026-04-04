"""
sync/permissions.py
===================
Role-based access control for all sync endpoints (pull, push).

How your role system works (from accounts/models.py)
------------------------------------------------------
- CustomUser.primary_role  →  Role instance (FK, nullable)
- Role.group               →  Django Group (OneToOne)
- Role.priority            →  int (0 = no role, higher = more authority)
- Role.group.name          →  the human-readable name set by the company admin
                               (NOT a fixed string — varies per company)
- user.display_role        →  role.group.name or "No Role Assigned"
- user.highest_role_priority → role.priority or 0
- user.company_admin       →  bool — tenant owner with full control
- user.is_saas_admin       →  bool — cross-company superuser

Why we use priority thresholds, not role name strings
------------------------------------------------------
Role names like "Cashier" or "Store Manager" are created by each company
and can be renamed at any time.  Matching on strings would break silently.

Priority is a stable integer set when creating a role.  Your codebase
already uses it this way:
    primary.priority >= 70  # Manager level and above  (accounts/models.py:691)

We follow the same convention:

    PRIORITY_THRESHOLDS (adjustable below)
    ───────────────────────────────────────
    0          → no role / unknown  → deny everything
    1  – 29    → view-only / guest
    30 – 59    → cashier / staff    → pull: sales data; push: sales + expenses
    60 – 69    → senior staff       → pull + push: adds stock movements
    70 – 89    → store manager      → pull + push: full inventory catalogue
    90 – 99    → admin              → unrestricted
    100+       → company_admin / saas_admin → unrestricted

Store access
------------
Instead of reimplementing store-access logic, we delegate directly to
user.get_accessible_stores() and user.can_access_store(store), which are
already fully implemented on CustomUser and cover all four paths:
  - Store.accessible_by_all
  - Store.staff M2M
  - Store.store_managers M2M
  - StoreAccess model

Adjusting for your company
---------------------------
Change the PRIORITY_THRESHOLDS dicts below to match the priorities your
company admins actually assign to roles.  Nothing else needs to change.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Priority thresholds  ← edit these to match your role setup
# ─────────────────────────────────────────────────────────────────────────────

# Minimum priority to PULL each table.
# A user whose highest_role_priority is below the threshold cannot pull that table.
PULL_THRESHOLDS: dict[str, int] = {
    # Basic sales data — all staff
    "stores":     30,
    "categories": 30,
    "products":   30,
    "stock":      30,
    "customers":  30,
    "sales":      30,
    "sale_items": 30,
    "expenses":   30,
    # Supplier/movement data — store managers and above
    "suppliers":       70,
    "stock_movements": 70,
    # User list — managers and above
    "users": 70,
}

# Minimum priority to PUSH to each table.
PUSH_THRESHOLDS: dict[str, int] = {
    # Cashiers can record transactions
    "customers":  30,
    "sales":      30,
    "sale_items": 30,
    "expenses":   30,
    # Stock movements need senior staff or above
    "stock_movements": 60,
    # Catalogue management needs store manager level
    "categories": 70,
    "suppliers":  70,
    "products":   70,
    "stock":      70,
}

# Users at or above this priority bypass store scoping entirely.
# Below this threshold → only their assigned stores are visible.
STORE_SCOPE_BYPASS_PRIORITY = 90


# ─────────────────────────────────────────────────────────────────────────────
# Core role helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_user_priority(user) -> int:
    """
    Return the user's effective role priority.

    company_admin and is_saas_admin always return 100 so they bypass
    every threshold check without needing a Role record.
    """
    if getattr(user, "is_saas_admin", False):
        return 100
    if getattr(user, "company_admin", False):
        return 100
    if getattr(user, "is_superuser", False):
        return 100
    return getattr(user, "highest_role_priority", 0) or 0


def get_user_role(user) -> str:
    """Return the user's display role name for logging."""
    return getattr(user, "display_role", "Unknown Role")

def is_privileged(user) -> bool:
    """True if the user bypasses all table and store restrictions."""
    return get_user_priority(user) >= STORE_SCOPE_BYPASS_PRIORITY


def is_store_scoped(user) -> bool:
    """
    True if this user's data must be filtered to their assigned stores.
    Privileged users are never store-scoped.
    Users with no role (priority 0) are also not store-scoped — they get
    nothing at all because every table threshold is > 0.
    """
    return not is_privileged(user) and get_user_priority(user) >= 30


# ─────────────────────────────────────────────────────────────────────────────
# Layer 1 — Table allowlists via priority thresholds
# ─────────────────────────────────────────────────────────────────────────────

def allowed_pull_tables(user, requested_tables: list[str]) -> list[str]:
    """
    Return the subset of requested_tables this user may pull.
    """
    priority = get_user_priority(user)

    if priority == 0:
        logger.warning(
            f"sync RBAC: pull denied — user has no role. "
            f"user={getattr(user, 'email', user)}"
        )
        return []

    permitted = [t for t in requested_tables if priority >= PULL_THRESHOLDS.get(t, 9999)]
    denied    = set(requested_tables) - set(permitted)
    if denied:
        logger.info(
            f"sync RBAC: pull denied tables={sorted(denied)} "
            f"user={getattr(user, 'email', user)} priority={priority}"
        )
    return permitted


def allowed_push_tables(user, requested_tables: list[str]) -> list[str]:
    """
    Return the subset of requested_tables this user may push to.
    """
    priority = get_user_priority(user)

    if priority == 0:
        logger.warning(
            f"sync RBAC: push denied — user has no role. "
            f"user={getattr(user, 'email', user)}"
        )
        return []

    permitted = [t for t in requested_tables if priority >= PUSH_THRESHOLDS.get(t, 9999)]
    denied    = set(requested_tables) - set(permitted)
    if denied:
        logger.warning(
            f"sync RBAC: push denied tables={sorted(denied)} "
            f"user={getattr(user, 'email', user)} priority={priority}"
        )
    return permitted


# ─────────────────────────────────────────────────────────────────────────────
# Layer 2 — Store scoping  (delegates to CustomUser methods)
# ─────────────────────────────────────────────────────────────────────────────

def get_accessible_store_pks(user) -> Optional[list[int]]:
    """
    Return the list of Store PKs this user may access, or None (unrestricted).

    Delegates to user.get_accessible_stores() which already handles all four
    access paths (accessible_by_all, staff M2M, store_managers M2M,
    StoreAccess model).

    Returns None  → privileged user, caller must NOT filter.
    Returns []    → user has no stores, caller gets empty queryset (safe default).
    """
    if not is_store_scoped(user):
        return None

    try:
        pks = list(user.get_accessible_stores().values_list("pk", flat=True))
        if not pks:
            logger.info(
                f"sync RBAC: user {getattr(user, 'email', user)} "
                f"has no accessible stores — returning empty queryset"
            )
        return pks
    except Exception as e:
        logger.error(
            f"sync RBAC: get_accessible_store_pks failed for "
            f"user={getattr(user, 'email', user)}: {e}",
            exc_info=True,
        )
        return []   # fail safe — no data leaks on error


def store_is_accessible(user, store_obj) -> bool:
    """
    Check whether a specific store object is within the user's access.
    Delegates to user.can_access_store(store).

    If store_obj is None we cannot validate — allow through so that the
    FK-missing error surfaces naturally in the handler.
    Privileged users always return True.
    """
    if is_privileged(user):
        return True
    if store_obj is None:
        return True   # let FK-missing error surface naturally
    try:
        return user.can_access_store(store_obj)
    except Exception as e:
        logger.error(
            f"sync RBAC: store_is_accessible check failed "
            f"user={getattr(user, 'email', user)} store={store_obj}: {e}",
            exc_info=True,
        )
        return False   # fail safe


# ─────────────────────────────────────────────────────────────────────────────
# Layer 3 — Row ownership (for push updates / deletes)
# ─────────────────────────────────────────────────────────────────────────────

def can_modify_record(user, obj, owner_field: str = "created_by") -> bool:
    """
    Check whether the pushing user may overwrite an existing server record.

    Rules (in order):
      1. Privileged users (priority >= STORE_SCOPE_BYPASS_PRIORITY) → yes.
      2. Record's owner_field matches pushing user → yes.
      3. User is priority >= 70 (manager level) AND the record's store is
         in their accessible stores → yes.
      4. Otherwise → no.

    owner_field: the attribute name on obj holding the owner FK.
        "created_by" for Sale, SaleItem, Customer, StockMovement.
        "user"        for Expense (Expense.user FK).
    """
    if is_privileged(user):
        return True

    # Direct ownership
    owner = getattr(obj, owner_field, None)
    if owner is not None:
        owner_pk = getattr(owner, "pk", owner)
        if owner_pk == user.pk:
            return True

    # Manager-level users can modify any record in their assigned stores
    if get_user_priority(user) >= 70:
        store = getattr(obj, "store", None)
        if store is not None and store_is_accessible(user, store):
            return True

    return False


def can_delete_record(user, obj, owner_field: str = "created_by") -> bool:
    """
    Stricter than can_modify_record.

    Users below manager level (priority < 70) cannot delete records via sync
    even if they own them — deletes touch financial records.
    """
    if is_privileged(user):
        return True
    if get_user_priority(user) < 70:
        return False
    return can_modify_record(user, obj, owner_field)


# ─────────────────────────────────────────────────────────────────────────────
# Utility
# ─────────────────────────────────────────────────────────────────────────────

def permission_denied_error(table: str, action: str, user) -> dict:
    priority  = get_user_priority(user)
    role_name = getattr(user, "display_role", "Unknown Role")
    return {
        "sync_id": None,
        "error": (
            f"Permission denied: role '{role_name}' (priority {priority}) "
            f"cannot {action} '{table}' records."
        ),
    }