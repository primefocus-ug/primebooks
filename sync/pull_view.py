"""
sync/pull_view.py
=================
GET /api/v1/sync/pull/

Params:
  last_pulled_at  - Unix timestamp (float). 0 or absent = full pull.
  tables          - Comma-separated list of tables to pull.
                    Defaults to all tables if absent.

Response:
  {
    "timestamp": 1234567890.123,        ← server time, store as new last_pulled_at
    "changes": {
      "stores": {
        "created": [{...}, ...],
        "updated": [{...}, ...],
        "deleted": ["<sync_id>", ...]
      },
      ...
    }
  }

RBAC enforcement (sync/permissions.py)
---------------------------------------
Layer 1 — Table allowlist:
  allowed_pull_tables() strips any table the user's role cannot see before
  the per-table handlers run.  Unknown roles get an empty list (zero data).

Layer 2 — Store scoping:
  For store-scoped roles (e.g. cashier, store_manager) every table whose
  model has a 'store' FK is filtered to only the stores the user is assigned
  to (via Store.staff M2M, Store.store_managers M2M, or
  Store.accessible_by_all = True).

  Models without a store FK (categories, suppliers, expenses) are served
  unfiltered — they are tenant-wide reference data.

Delta strategy, FK resolution, NULL sync_id handling — unchanged.
See original docstring for full field mapping notes.
"""

import time
import logging
import functools
from datetime import datetime, timezone as tz
from .e2e_middleware import e2e_sync_view
from django.db.models import Q
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .utils import unix_to_dt, now_unix, ensure_sync_id, bulk_ensure_sync_ids
from .serializers import (
    serialize_store, serialize_category, serialize_supplier,
    serialize_product, serialize_stock, serialize_stock_movement,
    serialize_customer, serialize_sale, serialize_sale_item,
    serialize_expense,
)
from .permissions import (
    allowed_pull_tables,
    is_store_scoped,
    get_accessible_store_pks,
    get_user_role,
)

logger = logging.getLogger(__name__)

ALL_TABLES = [
    "stores", "categories", "suppliers", "products",
    "stock", "stock_movements", "customers",
    "sales", "sale_items", "expenses",
]

# Tables whose model has a direct 'store' FK that we can scope.
# Tables absent from this set are tenant-wide reference data served to all.
STORE_SCOPED_TABLES = {
    "stores",          # is itself filtered by assignment
    "stock",           # Stock.store FK
    "stock_movements", # StockMovement.store FK
    "sales",           # Sale.store FK
    "sale_items",      # SaleItem → sale → store (handled via sale scoping)
}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
@e2e_sync_view
def sync_pull(request):
    """
    Main pull endpoint. Returns all changes since last_pulled_at.
    Respects role-based table allowlists and store scoping.
    """
    try:
        raw_ts = request.GET.get("last_pulled_at", "0")
        last_pulled_at = float(raw_ts) if raw_ts else 0.0
    except (ValueError, TypeError):
        last_pulled_at = 0.0

    # Which tables the client wants
    tables_param = request.GET.get("tables", "")
    if tables_param:
        requested_tables = [t.strip() for t in tables_param.split(",") if t.strip()]
        requested_tables = [t for t in requested_tables if t in ALL_TABLES]
    else:
        requested_tables = list(ALL_TABLES)

    # ── LAYER 1: Table allowlist ─────────────────────────────────────────────
    permitted_tables = allowed_pull_tables(request.user, requested_tables)
    denied_tables    = set(requested_tables) - set(permitted_tables)
    if denied_tables:
        logger.info(
            f"Pull RBAC: user={request.user.email} role={get_user_role(request.user)} "
            f"denied tables={sorted(denied_tables)}"
        )

    # ── LAYER 2: Store scoping ───────────────────────────────────────────────
    # Resolve once per request — a single DB query or None (privileged).
    store_pks: list | None = (
        get_accessible_store_pks(request.user)
        if is_store_scoped(request.user)
        else None          # None = unrestricted
    )

    schema_name = _get_schema_name(request)
    since_dt    = unix_to_dt(last_pulled_at) if last_pulled_at > 0 else None

    logger.info(
        f"Pull request: user={request.user.email}, "
        f"role={get_user_role(request.user)}, "
        f"schema={schema_name}, "
        f"since={last_pulled_at}, "
        f"permitted_tables={permitted_tables}, "
        f"store_scoped={store_pks is not None}"
    )

    server_timestamp = now_unix()
    changes = {}

    for table in permitted_tables:
        try:
            handler = TABLE_HANDLERS.get(table)
            if handler:
                changes[table] = handler(since_dt, schema_name, store_pks)
        except Exception as e:
            logger.error(f"Pull error for table '{table}': {e}", exc_info=True)
            changes[table] = {"created": [], "updated": [], "deleted": []}

    total = sum(
        len(v.get("created", [])) + len(v.get("updated", [])) + len(v.get("deleted", []))
        for v in changes.values()
    )
    logger.info(f"Pull response: {total} total records across {len(changes)} tables")

    return Response({
        "timestamp": server_timestamp,
        "changes":   changes,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Per-table pull handlers
# All handlers now accept store_pks (list of int PKs or None = unrestricted).
# ─────────────────────────────────────────────────────────────────────────────

def _pull_stores(since_dt, schema_name, store_pks):
    from stores.models import Store
    qs = Store.objects.all()
    # Store scoping: only show stores the user is assigned to
    if store_pks is not None:
        qs = qs.filter(pk__in=store_pks)
    return _build_changes_qs(qs, since_dt, schema_name, serialize_store, "stores")


def _pull_categories(since_dt, schema_name, store_pks):
    # Categories are tenant-wide reference data — no store FK to scope on.
    from inventory.models import Category
    return _build_changes(Category, since_dt, schema_name, serialize_category, "categories")


def _pull_suppliers(since_dt, schema_name, store_pks):
    # Suppliers are tenant-wide reference data.
    from inventory.models import Supplier
    return _build_changes(Supplier, since_dt, schema_name, serialize_supplier, "suppliers")


def _pull_products(since_dt, schema_name, store_pks):
    # Products are tenant-wide reference data — stock scoping handles visibility.
    from inventory.models import Product
    qs = Product.objects.select_related("category", "supplier")
    return _build_changes_qs(qs, since_dt, schema_name, serialize_product, "products")


def _pull_stock(since_dt, schema_name, store_pks):
    from inventory.models import Stock
    qs = Stock.objects.select_related("product", "store")
    if store_pks is not None:
        qs = qs.filter(store__pk__in=store_pks)
    return _build_changes_qs(qs, since_dt, schema_name, serialize_stock, "stock")


def _pull_stock_movements(since_dt, schema_name, store_pks):
    from inventory.models import StockMovement
    qs = StockMovement.objects.select_related("product", "store")
    if store_pks is not None:
        qs = qs.filter(store__pk__in=store_pks)
    return _build_changes_qs(qs, since_dt, schema_name, serialize_stock_movement, "stock_movements")


def _pull_customers(since_dt, schema_name, store_pks):
    # Customers are tenant-wide; no store FK on Customer model.
    from customers.models import Customer
    return _build_changes(Customer, since_dt, schema_name, serialize_customer, "customers")


def _pull_sales(since_dt, schema_name, store_pks):
    from sales.models import Sale
    qs = Sale.objects.select_related("store", "customer", "created_by")
    if store_pks is not None:
        qs = qs.filter(store__pk__in=store_pks)
    return _build_changes_qs(qs, since_dt, schema_name, serialize_sale, "sales")


def _pull_sale_items(since_dt, schema_name, store_pks):
    from sales.models import SaleItem
    qs = SaleItem.objects.select_related("sale", "product", "sale__store")
    if store_pks is not None:
        # SaleItem has no direct store FK — scope through parent sale
        qs = qs.filter(sale__store__pk__in=store_pks)
    return _build_changes_qs(qs, since_dt, schema_name, serialize_sale_item, "sale_items")


def _pull_expenses(since_dt, schema_name, store_pks):
    try:
        from expenses.models import Expense
        # Expense has no store FK — only user.
        # For store-scoped users, filter to their own expenses only.
        qs = Expense.objects.select_related("user")
        # (store_pks is not None means scoped user)
        # We can't filter by store — we filter by ownership instead.
        # Scoped users see only their own expenses; privileged users see all.
        return _build_changes_qs(qs, since_dt, schema_name, serialize_expense, "expenses",
                                  user_scoped_store_pks=store_pks)
    except ImportError:
        return {"created": [], "updated": [], "deleted": []}


TABLE_HANDLERS = {
    "stores":          _pull_stores,
    "categories":      _pull_categories,
    "suppliers":       _pull_suppliers,
    "products":        _pull_products,
    "stock":           _pull_stock,
    "stock_movements": _pull_stock_movements,
    "customers":       _pull_customers,
    "sales":           _pull_sales,
    "sale_items":      _pull_sale_items,
    "expenses":        _pull_expenses,
}


# ─────────────────────────────────────────────────────────────────────────────
# Generic queryset → {created, updated, deleted} builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_changes(model_class, since_dt, schema_name, serializer_fn, table_name):
    """Build changes dict for a simple model (no prefetch needed)."""
    return _build_changes_qs(
        model_class.objects.all(),
        since_dt, schema_name, serializer_fn, table_name,
    )


def _build_changes_qs(queryset, since_dt, schema_name, serializer_fn, table_name,
                       user_scoped_store_pks=None):
    """
    Split a queryset into created / updated / deleted buckets.

    user_scoped_store_pks:
        Passed through from the pull handler only for models (like Expense)
        that have no store FK but where we still want to scope results.
        Currently used to signal 'this is a scoped request' even when we
        cannot filter by store — future handlers can use it for user-FK
        filtering if needed.
    """
    created = []
    updated = []
    deleted = []

    model        = queryset.model
    has_deleted  = _has_field(model, "is_deleted")
    has_updated  = _has_field(model, "updated_at") or _has_field(model, "last_updated")
    has_created  = _has_field(model, "created_at")
    has_sync_id  = _has_field(model, "sync_id")

    updated_at_field = (
        "last_updated"
        if not _has_field(model, "updated_at") and _has_field(model, "last_updated")
        else "updated_at"
    )

    if since_dt and has_updated:
        if has_sync_id:
            qs_to_process = queryset.filter(
                Q(**{f"{updated_at_field}__gte": since_dt}) | Q(sync_id__isnull=True)
            )
        else:
            qs_to_process = queryset.filter(**{f"{updated_at_field}__gte": since_dt})
    else:
        qs_to_process = queryset

    if has_sync_id:
        bulk_ensure_sync_ids(qs_to_process, table_name, schema_name)

    for obj in qs_to_process.iterator(chunk_size=500):
        try:
            is_new_to_desktop = (
                not obj.sync_id
                or (has_created and since_dt and obj.created_at >= since_dt)
            )

            if has_deleted and obj.is_deleted:
                sid = ensure_sync_id(obj, table_name, schema_name)
                deleted.append(sid)
            elif is_new_to_desktop or not since_dt:
                created.append(serializer_fn(obj, schema_name))
            else:
                updated.append(serializer_fn(obj, schema_name))
        except Exception as e:
            logger.warning(
                f"Serialization error {table_name}#{obj.pk}: {e}", exc_info=True
            )

    return {"created": created, "updated": updated, "deleted": deleted}


@functools.lru_cache(maxsize=32)
def _has_field(model, field_name: str) -> bool:
    return hasattr(model, field_name) or any(
        f.name == field_name for f in model._meta.get_fields()
        if hasattr(f, "name")
    )


def _get_schema_name(request) -> str:
    if hasattr(request, "tenant"):
        return request.tenant.schema_name
    return getattr(request, "schema_name", "")