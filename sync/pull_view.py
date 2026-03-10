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
      "categories": { ... },
      "suppliers":  { ... },
      "products":   { ... },
      "stock":      { ... },
      "stock_movements": { ... },
      "customers":  { ... },
      "sales":      { ... },
      "sale_items": { ... },
      "expenses":   { ... }
    }
  }

Delta strategy:
  - created: updated_at >= last_pulled_at AND created_at >= last_pulled_at
             (or sync_id was NULL and we just assigned one → always re-send)
  - updated: updated_at >= last_pulled_at AND created_at < last_pulled_at
  - deleted: is_deleted=True AND updated_at >= last_pulled_at

FK resolution:
  All FK fields are serialized as sync_id strings so the desktop never
  needs to know Django integer PKs.

NULL sync_id handling:
  Records with sync_id=NULL get a deterministic UUID auto-assigned.
  On first pull these always appear in "created" (their synced_at is null).

Field mapping notes (server → desktop):
  Store:    physical_address → address, is_main_branch → is_default, tin → efris_tin
  Sale:     status/payment_method/payment_status lowercased, efris_invoice_number → fiscal_document_number
            created_by.sync_id → created_by_id
  SaleItem: total_price → subtotal, line_total → total, discount → discount_percentage
            updated_at falls back to sale.updated_at then time.time()
  Stock:    last_updated → updated_at (no updated_at field on server model)
  Expense:  description → title, notes → description, date → expense_date,
            payment_method lowercased, user.sync_id → created_by_id, no store FK
"""

import time
import logging
import functools
from datetime import datetime, timezone as tz

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

logger = logging.getLogger(__name__)

ALL_TABLES = [
    "stores", "categories", "suppliers", "products",
    "stock", "stock_movements", "customers",
    "sales", "sale_items", "expenses",
]


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def sync_pull(request):
    """
    Main pull endpoint. Returns all changes since last_pulled_at.
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
        # Validate — only allow known tables
        requested_tables = [t for t in requested_tables if t in ALL_TABLES]
    else:
        requested_tables = ALL_TABLES

    # Grab tenant schema name from the request (django-tenants sets this)
    schema_name = _get_schema_name(request)
    since_dt = unix_to_dt(last_pulled_at) if last_pulled_at > 0 else None

    logger.info(
        f"Pull request: user={request.user.email}, "
        f"schema={schema_name}, "
        f"since={last_pulled_at}, "
        f"tables={requested_tables}"
    )

    server_timestamp = now_unix()
    changes = {}

    for table in requested_tables:
        try:
            handler = TABLE_HANDLERS.get(table)
            if handler:
                changes[table] = handler(since_dt, schema_name)
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
        "changes": changes,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Per-table pull handlers
# ─────────────────────────────────────────────────────────────────────────────

def _pull_stores(since_dt, schema_name):
    from stores.models import Store
    return _build_changes(Store, since_dt, schema_name, serialize_store, "stores")


def _pull_categories(since_dt, schema_name):
    from inventory.models import Category
    return _build_changes(Category, since_dt, schema_name, serialize_category, "categories")


def _pull_suppliers(since_dt, schema_name):
    from inventory.models import Supplier
    return _build_changes(Supplier, since_dt, schema_name, serialize_supplier, "suppliers")


def _pull_products(since_dt, schema_name):
    from inventory.models import Product
    qs = Product.objects.select_related("category", "supplier")
    return _build_changes_qs(qs, since_dt, schema_name, serialize_product, "products")


def _pull_stock(since_dt, schema_name):
    from inventory.models import Stock
    qs = Stock.objects.select_related("product", "store")
    return _build_changes_qs(qs, since_dt, schema_name, serialize_stock, "stock")


def _pull_stock_movements(since_dt, schema_name):
    from inventory.models import StockMovement
    qs = StockMovement.objects.select_related("product", "store")
    return _build_changes_qs(qs, since_dt, schema_name, serialize_stock_movement, "stock_movements")


def _pull_customers(since_dt, schema_name):
    from customers.models import Customer
    return _build_changes(Customer, since_dt, schema_name, serialize_customer, "customers")


def _pull_sales(since_dt, schema_name):
    from sales.models import Sale
    qs = Sale.objects.select_related("store", "customer", "created_by")
    return _build_changes_qs(qs, since_dt, schema_name, serialize_sale, "sales")


def _pull_sale_items(since_dt, schema_name):
    from sales.models import SaleItem
    # select_related on sale so we can fall back to sale.updated_at for updated_at
    qs = SaleItem.objects.select_related("sale", "product")
    return _build_changes_qs(qs, since_dt, schema_name, serialize_sale_item, "sale_items")


def _pull_expenses(since_dt, schema_name):
    try:
        from expenses.models import Expense
        # Expense has no store FK — only user
        qs = Expense.objects.select_related("user")
        return _build_changes_qs(qs, since_dt, schema_name, serialize_expense, "expenses")
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


def _build_changes_qs(queryset, since_dt, schema_name, serializer_fn, table_name):
    """
    Split a queryset into created / updated / deleted buckets.

    Performance improvements:
      - Single Q-filter query replaces three separate queries (changed_pks,
        null_pks, pk__in) that were used to combine changed + NULL-sync_id rows.
      - bulk_ensure_sync_ids() pre-assigns sync_ids to all NULL records in ONE
        bulk_update() before the serialization loop starts — eliminates one
        UPDATE per NULL record that ensure_sync_id() would fire inline.
      - _has_field() is lru_cache'd so _meta scans run once per model, not
        once per pull request.

    Stock special case: Stock.last_updated is used instead of updated_at
    because the server model has no updated_at field.
    """
    created = []
    updated = []
    deleted = []

    model        = queryset.model
    has_deleted  = _has_field(model, "is_deleted")
    has_updated  = _has_field(model, "updated_at") or _has_field(model, "last_updated")
    has_created  = _has_field(model, "created_at")
    has_sync_id  = _has_field(model, "sync_id")

    # Stock uses last_updated instead of updated_at
    updated_at_field = (
        "last_updated"
        if not _has_field(model, "updated_at") and _has_field(model, "last_updated")
        else "updated_at"
    )

    if since_dt and has_updated:
        if has_sync_id:
            # One query replaces three: changed OR never-synced (NULL sync_id)
            qs_to_process = queryset.filter(
                Q(**{f"{updated_at_field}__gte": since_dt}) | Q(sync_id__isnull=True)
            )
        else:
            qs_to_process = queryset.filter(**{f"{updated_at_field}__gte": since_dt})
    else:
        # Full pull: everything
        qs_to_process = queryset

    # Pre-assign sync_ids to all NULL records in ONE bulk_update() before the
    # loop. Without this, ensure_sync_id() inside serializers fires one UPDATE
    # per NULL record — at 10 000 products that's 10 000 individual UPDATEs.
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
    """
    Check whether a model has a given field.
    lru_cache'd per (model, field_name) — _meta scans run once per process,
    not once per pull request.
    """
    return hasattr(model, field_name) or any(
        f.name == field_name for f in model._meta.get_fields()
        if hasattr(f, "name")
    )


def _get_schema_name(request) -> str:
    """Extract tenant schema name from request (django-tenants)."""
    if hasattr(request, "tenant"):
        return request.tenant.schema_name
    return getattr(request, "schema_name", "")