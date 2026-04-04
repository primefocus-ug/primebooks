"""
sync/push_view.py
=================
POST /api/v1/sync/push/

RBAC enforcement (sync/permissions.py)
---------------------------------------
Layer 1 — Table allowlist:
  allowed_push_tables() rejects entire tables the user's role cannot write.
  Rejected records are returned in the 'rejected' dict with a clear error
  so the desktop can surface it to the user without crashing.

Layer 2 — Store scoping (write side):
  For store-scoped users, each record's store_id is validated against the
  stores they are assigned to.  A cashier at Store A cannot push records
  tagged with Store B's sync_id.

Layer 3 — Row ownership:
  On UPDATE (record already exists on server), can_modify_record() checks
  whether the pushing user is the original creator or a manager of the
  store.  Prevents a cashier from overwriting another user's sale or
  expense.

Layer 3b — Delete gate:
  can_delete_record() is stricter — cashiers cannot delete records via sync
  even if they own them.

All other behaviour (conflict strategy, FK resolution, field mapping,
savepoint-per-record transaction isolation) is unchanged from the original.
See original docstring for full field mapping notes.
"""

import time
import logging
from decimal import Decimal, InvalidOperation
from datetime import datetime, timezone as tz
from .e2e_middleware import e2e_sync_view
from django.db import transaction, IntegrityError
from django.utils import timezone as dj_timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .utils import (
    parse_sync_id, safe_decimal, safe_int, safe_bool,
    unix_to_dt, now_unix, get_client_ip, bulk_resolve_fk,
)
from .permissions import (
    allowed_push_tables,
    is_store_scoped,
    get_accessible_store_pks,
    can_modify_record,
    can_delete_record,
    get_user_role,
    permission_denied_error,
)

logger = logging.getLogger(__name__)

MAX_RECORDS_PER_TABLE = 5_000


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@e2e_sync_view
def sync_push(request):
    """
    Accept dirty records from desktop, apply to server DB.
    Role-based access control applied before any handler runs.
    """
    data        = request.data
    changes     = data.get("changes", {})
    schema_name = _get_schema_name(request)

    logger.info(
        f"Push request: user={request.user.email}, "
        f"role={get_user_role(request.user)}, "
        f"schema={schema_name}, "
        f"tables={list(changes.keys())}"
    )

    accepted  = {}
    rejected  = {}
    conflicts = {}

    # ── LAYER 1: Table allowlist ─────────────────────────────────────────────
    permitted_push = set(allowed_push_tables(request.user, list(changes.keys())))

    for table_name in list(changes.keys()):
        if table_name not in permitted_push:
            # Collect all sync_ids from this table and reject them all
            table_changes = changes[table_name]
            all_ids = (
                [r.get("sync_id") for r in table_changes.get("created", [])]
                + [r.get("sync_id") for r in table_changes.get("updated", [])]
                + table_changes.get("deleted", [])
            )
            rejected[table_name] = [
                {
                    "sync_id": sid,
                    "error": (
                        f"Permission denied: role '{get_user_role(request.user)}' "
                        f"cannot push to '{table_name}'."
                    ),
                }
                for sid in all_ids if sid
            ]
            logger.warning(
                f"Push RBAC: table '{table_name}' denied to "
                f"user={request.user.email} role={get_user_role(request.user)}"
            )
            changes.pop(table_name)

    # ── LAYER 2: Resolve store PKs once for the whole request ────────────────
    # None = user is privileged (unrestricted).
    # list = PKs of stores the user may write to.
    accessible_store_pks: list | None = (
        get_accessible_store_pks(request.user)
        if is_store_scoped(request.user)
        else None
    )

    # ── Dispatch to per-table handlers ───────────────────────────────────────
    for table_name, table_changes in changes.items():
        handler = PUSH_HANDLERS.get(table_name)
        if not handler:
            logger.warning(f"Push: unknown table '{table_name}' — skipping")
            continue

        try:
            table_accepted, table_rejected, table_conflicts = handler(
                table_changes, request.user, schema_name, accessible_store_pks
            )
            if table_accepted:
                accepted[table_name] = table_accepted
            if table_rejected:
                rejected.setdefault(table_name, []).extend(table_rejected)
            if table_conflicts:
                conflicts[table_name] = table_conflicts
        except Exception as e:
            logger.error(f"Push handler error for '{table_name}': {e}", exc_info=True)
            all_sync_ids = (
                [r.get("sync_id") for r in table_changes.get("created", [])]
                + [r.get("sync_id") for r in table_changes.get("updated", [])]
                + table_changes.get("deleted", [])
            )
            rejected.setdefault(table_name, []).extend(
                {"sync_id": sid, "error": str(e)} for sid in all_sync_ids if sid
            )

    total_accepted = sum(len(v) for v in accepted.values())
    total_rejected = sum(len(v) for v in rejected.values())
    logger.info(
        f"Push complete: user={request.user.email} "
        f"accepted={total_accepted}, rejected={total_rejected}"
    )

    return Response({
        "accepted":  accepted,
        "rejected":  rejected,
        "conflicts": conflicts,
    })


# ─────────────────────────────────────────────────────────────────────────────
# Store-scope guard helper
# ─────────────────────────────────────────────────────────────────────────────

def _store_allowed(store_obj, accessible_store_pks) -> bool:
    """
    Return True if the given store is within the user's accessible stores.
    If accessible_store_pks is None the user is unrestricted.
    If store_obj is None we cannot validate — allow through (FK validation
    will catch missing stores separately).
    """
    if accessible_store_pks is None:
        return True
    if store_obj is None:
        return True   # let FK-missing error surface naturally
    return store_obj.pk in accessible_store_pks


# ─────────────────────────────────────────────────────────────────────────────
# Per-table push handlers
# All handlers now accept accessible_store_pks (list | None).
# ─────────────────────────────────────────────────────────────────────────────

def _push_customers(changes, user, schema_name, accessible_store_pks):
    """
    Customers are tenant-wide — no store FK.
    Layer 3 ownership check applied on update.
    """
    from customers.models import Customer

    accepted, rejected, conflicts = [], [], []
    records = (changes.get("created", []) + changes.get("updated", []))[:MAX_RECORDS_PER_TABLE]

    with transaction.atomic():
        for record in records:
            sync_id = parse_sync_id(record.get("sync_id"))
            if not sync_id:
                rejected.append({"sync_id": None, "error": "Missing sync_id"})
                continue
            sid = transaction.savepoint()
            try:
                obj, created = Customer.objects.get_or_create(
                    sync_id=sync_id,
                    defaults=_customer_defaults(record),
                )
                if not created:
                    # Layer 3: ownership check
                    if not can_modify_record(user, obj, owner_field="created_by"):
                        transaction.savepoint_rollback(sid)
                        rejected.append({
                            "sync_id": sync_id,
                            "error": "Permission denied: cannot modify another user's customer record.",
                        })
                        continue
                    _apply_customer(obj, record)
                    obj.save()
                transaction.savepoint_commit(sid)
                accepted.append(sync_id)
            except Exception as e:
                transaction.savepoint_rollback(sid)
                logger.warning(f"Customer push error {sync_id}: {e}")
                rejected.append({"sync_id": sync_id, "error": str(e)[:200]})

    for sync_id in changes.get("deleted", []):
        sid = parse_sync_id(sync_id)
        if not sid:
            continue
        try:
            obj = Customer.objects.filter(sync_id=sid).first()
            if obj and not can_delete_record(user, obj, owner_field="created_by"):
                rejected.append({
                    "sync_id": sid,
                    "error": "Permission denied: your role cannot delete customer records.",
                })
                continue
            Customer.objects.filter(sync_id=sid).update(is_active=False)
            accepted.append(sid)
        except Exception as e:
            rejected.append({"sync_id": sid, "error": str(e)[:200]})

    return accepted, rejected, conflicts


def _push_sales(changes, user, schema_name, accessible_store_pks):
    from sales.models import Sale
    from stores.models import Store
    from customers.models import Customer

    accepted, rejected, conflicts = [], [], []
    records = (changes.get("created", []) + changes.get("updated", []))[:MAX_RECORDS_PER_TABLE]

    store_map    = bulk_resolve_fk(Store,    [r.get("store_id")    for r in records])
    customer_map = bulk_resolve_fk(Customer, [r.get("customer_id") for r in records])

    with transaction.atomic():
        for record in records:
            sync_id = parse_sync_id(record.get("sync_id"))
            if not sync_id:
                rejected.append({"sync_id": None, "error": "Missing sync_id"})
                continue
            sid = transaction.savepoint()
            try:
                store    = store_map.get(str(record.get("store_id", "")))
                customer = customer_map.get(str(record.get("customer_id", "")))

                # Layer 2: store scope check
                if not _store_allowed(store, accessible_store_pks):
                    transaction.savepoint_rollback(sid)
                    rejected.append({
                        "sync_id": sync_id,
                        "error": "Permission denied: you are not assigned to that store.",
                    })
                    continue

                obj, created = Sale.objects.get_or_create(
                    sync_id=sync_id,
                    defaults=_sale_defaults(record, store, customer, user),
                )
                if not created:
                    # Layer 3: ownership check
                    if not can_modify_record(user, obj, owner_field="created_by"):
                        transaction.savepoint_rollback(sid)
                        rejected.append({
                            "sync_id": sync_id,
                            "error": "Permission denied: cannot modify another user's sale.",
                        })
                        continue
                    _apply_sale(obj, record, store, customer)
                    obj.save()
                transaction.savepoint_commit(sid)
                accepted.append(sync_id)
            except IntegrityError as e:
                transaction.savepoint_rollback(sid)
                logger.warning(f"Sale push IntegrityError {sync_id}: {e}")
                rejected.append({"sync_id": sync_id, "error": "Duplicate document number"})
            except Exception as e:
                transaction.savepoint_rollback(sid)
                logger.warning(f"Sale push error {sync_id}: {e}")
                rejected.append({"sync_id": sync_id, "error": str(e)[:200]})

    for sync_id in changes.get("deleted", []):
        sid = parse_sync_id(sync_id)
        if not sid:
            continue
        try:
            obj = Sale.objects.filter(sync_id=sid).first()
            if obj and not can_delete_record(user, obj, owner_field="created_by"):
                rejected.append({
                    "sync_id": sid,
                    "error": "Permission denied: your role cannot cancel sales via sync.",
                })
                continue
            Sale.objects.filter(sync_id=sid).update(status="CANCELLED")
            accepted.append(sid)
        except Exception as e:
            rejected.append({"sync_id": sid, "error": str(e)[:200]})

    return accepted, rejected, conflicts


def _push_sale_items(changes, user, schema_name, accessible_store_pks):
    """
    SaleItems are child records — pushed alongside sales.
    Store scope is enforced through the parent sale's store.
    """
    try:
        from sales.models import SaleItem, Sale
        from inventory.models import Product
    except ImportError:
        return [], [], []

    accepted, rejected, conflicts = [], [], []
    records = (changes.get("created", []) + changes.get("updated", []))[:MAX_RECORDS_PER_TABLE]

    sale_map    = bulk_resolve_fk(Sale,    [r.get("sale_id")    for r in records])
    product_map = bulk_resolve_fk(Product, [r.get("product_id") for r in records])

    with transaction.atomic():
        for record in records:
            sync_id = parse_sync_id(record.get("sync_id"))
            if not sync_id:
                rejected.append({"sync_id": None, "error": "Missing sync_id"})
                continue

            sale    = sale_map.get(str(record.get("sale_id", "")))
            product = product_map.get(str(record.get("product_id", "")))

            if not sale:
                rejected.append({"sync_id": sync_id, "error": "Parent sale not found"})
                continue

            # Layer 2: store scope through parent sale
            if not _store_allowed(getattr(sale, "store", None), accessible_store_pks):
                rejected.append({
                    "sync_id": sync_id,
                    "error": "Permission denied: parent sale belongs to a store you are not assigned to.",
                })
                continue

            sid = transaction.savepoint()
            try:
                defaults = {
                    "sale":        sale,
                    "product":     product,
                    "quantity":    int(_d(record.get("quantity", 1))),
                    "unit_price":  _d(record.get("unit_price", 0)),
                    "discount":    _d(record.get("discount_percentage", 0)),
                    "tax_rate":    record.get("tax_rate", "A") or "A",
                    "tax_amount":  _d(record.get("tax_amount", 0)),
                    "total_price": _d(record.get("subtotal", 0)),
                }
                obj, created = SaleItem.objects.get_or_create(
                    sync_id=sync_id, defaults=defaults
                )
                if not created:
                    for k, v in defaults.items():
                        setattr(obj, k, v)
                    obj._skip_deduction   = True
                    obj._skip_sale_update = True
                    obj.save()
                transaction.savepoint_commit(sid)
                accepted.append(sync_id)
            except Exception as e:
                transaction.savepoint_rollback(sid)
                logger.warning(f"SaleItem push error {sync_id}: {e}")
                rejected.append({"sync_id": sync_id, "error": str(e)[:200]})

    return accepted, rejected, conflicts


def _push_expenses(changes, user, schema_name, accessible_store_pks):
    """
    Expense has no store FK on server — store scoping is done via ownership:
    scoped users may only update their own expenses.
    """
    try:
        from expenses.models import Expense
    except ImportError:
        return [], [], []

    accepted, rejected, conflicts = [], [], []
    records = (changes.get("created", []) + changes.get("updated", []))[:MAX_RECORDS_PER_TABLE]

    _VALID_PMS = {"CASH", "CREDIT_CARD", "DEBIT_CARD", "BANK_TRANSFER", "DIGITAL_WALLET", "OTHER"}
    _PM_MAP    = {"MOBILE_MONEY": "DIGITAL_WALLET", "CARD": "CREDIT_CARD"}

    with transaction.atomic():
        for record in records:
            sync_id = parse_sync_id(record.get("sync_id"))
            if not sync_id:
                rejected.append({"sync_id": None, "error": "Missing sync_id"})
                continue
            sid = transaction.savepoint()
            try:
                expense_dt   = unix_to_dt(record.get("expense_date"))
                expense_date = expense_dt.date() if expense_dt else dj_timezone.now().date()

                raw_pm         = (record.get("payment_method", "cash") or "cash").upper()
                payment_method = _PM_MAP.get(raw_pm, raw_pm)
                if payment_method not in _VALID_PMS:
                    payment_method = "OTHER"

                defaults = {
                    "description":    record.get("title", "") or record.get("description", ""),
                    "notes":          record.get("notes", "") or record.get("description", ""),
                    "amount":         _d(record.get("amount", 0)),
                    "date":           expense_date,
                    "payment_method": payment_method,
                    "user":           user,
                }
                obj, created = Expense.objects.get_or_create(
                    sync_id=sync_id, defaults=defaults
                )
                if not created:
                    # Layer 3: scoped users can only update their own expenses
                    # (Expense uses 'user' FK not 'created_by')
                    if not can_modify_record(user, obj, owner_field="user"):
                        transaction.savepoint_rollback(sid)
                        rejected.append({
                            "sync_id": sync_id,
                            "error": "Permission denied: cannot modify another user's expense.",
                        })
                        continue
                    for k, v in defaults.items():
                        setattr(obj, k, v)
                    obj.save()
                transaction.savepoint_commit(sid)
                accepted.append(sync_id)
            except Exception as e:
                transaction.savepoint_rollback(sid)
                logger.warning(f"Expense push error {sync_id}: {e}")
                rejected.append({"sync_id": sync_id, "error": str(e)[:200]})

    for sync_id in changes.get("deleted", []):
        sid = parse_sync_id(sync_id)
        if not sid:
            continue
        # Expense has no status field — only allow delete for privileged users.
        obj = None
        try:
            from expenses.models import Expense
            obj = Expense.objects.filter(sync_id=sid).first()
        except Exception:
            pass
        if obj and not can_delete_record(user, obj, owner_field="user"):
            rejected.append({
                "sync_id": sid,
                "error": "Permission denied: your role cannot delete expense records.",
            })
            continue
        accepted.append(sid)   # soft-delete not supported; accept silently

    return accepted, rejected, conflicts


def _push_categories(changes, user, schema_name, accessible_store_pks):
    """
    Categories are tenant-wide inventory data.
    Server wins on conflict (server is authoritative for catalogue).
    No store scoping — already blocked at table allowlist for cashiers.
    """
    from inventory.models import Category

    accepted, rejected, conflicts = [], [], []
    records       = (changes.get("created", []) + changes.get("updated", []))[:MAX_RECORDS_PER_TABLE]
    conflict_objs = []

    with transaction.atomic():
        for record in records:
            sync_id = parse_sync_id(record.get("sync_id"))
            if not sync_id:
                rejected.append({"sync_id": None, "error": "Missing sync_id"})
                continue
            sid = transaction.savepoint()
            try:
                obj, created = Category.objects.get_or_create(
                    sync_id=sync_id,
                    defaults={
                        "name":          record.get("name", ""),
                        "code":          record.get("code", "") or None,
                        "description":   record.get("description", ""),
                        "category_type": record.get("category_type", "product"),
                        "is_active":     safe_bool(record.get("is_active", True)),
                    }
                )
                transaction.savepoint_commit(sid)
                if not created:
                    conflict_objs.append(obj)
                else:
                    accepted.append(sync_id)
            except Exception as e:
                transaction.savepoint_rollback(sid)
                rejected.append({"sync_id": sync_id, "error": str(e)[:200]})

    from .serializers import serialize_category
    for obj in conflict_objs:
        conflicts.append(serialize_category(obj, schema_name))

    return accepted, rejected, conflicts


def _push_suppliers(changes, user, schema_name, accessible_store_pks):
    from inventory.models import Supplier

    accepted, rejected, conflicts = [], [], []
    records       = (changes.get("created", []) + changes.get("updated", []))[:MAX_RECORDS_PER_TABLE]
    conflict_objs = []

    with transaction.atomic():
        for record in records:
            sync_id = parse_sync_id(record.get("sync_id"))
            if not sync_id:
                rejected.append({"sync_id": None, "error": "Missing sync_id"})
                continue
            sid = transaction.savepoint()
            try:
                obj, created = Supplier.objects.get_or_create(
                    sync_id=sync_id,
                    defaults={
                        "name":           record.get("name", ""),
                        "tin":            record.get("tin", "") or None,
                        "contact_person": record.get("contact_person", ""),
                        "phone":          record.get("phone", ""),
                        "email":          record.get("email", ""),
                        "address":        record.get("address", ""),
                        "country":        record.get("country", "Uganda"),
                        "is_active":      safe_bool(record.get("is_active", True)),
                    }
                )
                transaction.savepoint_commit(sid)
                if not created:
                    conflict_objs.append(obj)
                else:
                    accepted.append(sync_id)
            except Exception as e:
                transaction.savepoint_rollback(sid)
                rejected.append({"sync_id": sync_id, "error": str(e)[:200]})

    from .serializers import serialize_supplier
    for obj in conflict_objs:
        conflicts.append(serialize_supplier(obj, schema_name))

    return accepted, rejected, conflicts


def _push_products(changes, user, schema_name, accessible_store_pks):
    """
    Products are tenant-wide catalogue data.
    Server wins on conflict.
    Already blocked for cashiers at the table allowlist layer.
    """
    from inventory.models import Product, Category, Supplier

    accepted, rejected, conflicts = [], [], []
    records       = (changes.get("created", []) + changes.get("updated", []))[:MAX_RECORDS_PER_TABLE]
    conflict_objs = []

    category_map = bulk_resolve_fk(Category, [r.get("category_id") for r in records])
    supplier_map = bulk_resolve_fk(Supplier, [r.get("supplier_id") for r in records])

    with transaction.atomic():
        for record in records:
            sync_id = parse_sync_id(record.get("sync_id"))
            if not sync_id:
                rejected.append({"sync_id": None, "error": "Missing sync_id"})
                continue
            sid = transaction.savepoint()
            try:
                category = category_map.get(str(record.get("category_id", "")))
                supplier = supplier_map.get(str(record.get("supplier_id", "")))

                obj, created = Product.objects.get_or_create(
                    sync_id=sync_id,
                    defaults={
                        "name":                record.get("name", ""),
                        "sku":                 record.get("sku", ""),
                        "barcode":             record.get("barcode") or None,
                        "description":         record.get("description", ""),
                        "selling_price":       _d(record.get("selling_price", 0)),
                        "cost_price":          _d(record.get("cost_price", 0)),
                        "discount_percentage": _d(record.get("discount_percentage", 0)),
                        "tax_rate":            record.get("tax_rate", "A") or "A",
                        "unit_of_measure":     record.get("unit_of_measure", "103") or "103",
                        "min_stock_level":     safe_int(record.get("min_stock_level"), 5),
                        "is_active":           safe_bool(record.get("is_active", True)),
                        "category":            category,
                        "supplier":            supplier,
                    }
                )
                transaction.savepoint_commit(sid)
                if not created:
                    conflict_objs.append(obj)
                else:
                    accepted.append(sync_id)
            except IntegrityError:
                transaction.savepoint_rollback(sid)
                rejected.append({"sync_id": sync_id, "error": "SKU already exists"})
            except Exception as e:
                transaction.savepoint_rollback(sid)
                rejected.append({"sync_id": sync_id, "error": str(e)[:200]})

    from .serializers import serialize_product
    for obj in conflict_objs:
        conflicts.append(serialize_product(obj, schema_name))

    return accepted, rejected, conflicts


def _push_stock(changes, user, schema_name, accessible_store_pks):
    """
    Stock adjustments from desktop.
    Desktop wins — it's the physical point of truth.
    Layer 2: store scoping applied.
    """
    from inventory.models import Stock, Product
    from stores.models import Store

    accepted, rejected, conflicts = [], [], []
    records = (changes.get("created", []) + changes.get("updated", []))[:MAX_RECORDS_PER_TABLE]

    product_map = bulk_resolve_fk(Product, [r.get("product_id") for r in records])
    store_map   = bulk_resolve_fk(Store,   [r.get("store_id")   for r in records])

    with transaction.atomic():
        for record in records:
            sync_id = parse_sync_id(record.get("sync_id"))
            if not sync_id:
                rejected.append({"sync_id": None, "error": "Missing sync_id"})
                continue

            store   = store_map.get(str(record.get("store_id", "")))
            product = product_map.get(str(record.get("product_id", "")))

            # Layer 2: store scope
            if not _store_allowed(store, accessible_store_pks):
                rejected.append({
                    "sync_id": sync_id,
                    "error": "Permission denied: you are not assigned to that store.",
                })
                continue

            sid = transaction.savepoint()
            try:
                defaults = {
                    "product":             product,
                    "store":               store,
                    "quantity":            _d(record.get("quantity", 0)),
                    "low_stock_threshold": _d(record.get("low_stock_threshold", 5)),
                    "reorder_quantity":    _d(record.get("reorder_quantity", 10)),
                }
                obj, created = Stock.objects.get_or_create(
                    sync_id=sync_id, defaults=defaults
                )
                if not created:
                    for k, v in defaults.items():
                        setattr(obj, k, v)
                    obj.save()
                transaction.savepoint_commit(sid)
                accepted.append(sync_id)
            except Exception as e:
                transaction.savepoint_rollback(sid)
                rejected.append({"sync_id": sync_id, "error": str(e)[:200]})

    return accepted, rejected, conflicts


def _push_stock_movements(changes, user, schema_name, accessible_store_pks):
    from inventory.models import StockMovement, Product
    from stores.models import Store

    accepted, rejected, conflicts = [], [], []
    records       = (changes.get("created", []) + changes.get("updated", []))[:MAX_RECORDS_PER_TABLE]
    conflict_objs = []

    product_map = bulk_resolve_fk(Product, [r.get("product_id") for r in records])
    store_map   = bulk_resolve_fk(Store,   [r.get("store_id")   for r in records])

    with transaction.atomic():
        for record in records:
            sync_id = parse_sync_id(record.get("sync_id"))
            if not sync_id:
                rejected.append({"sync_id": None, "error": "Missing sync_id"})
                continue

            store   = store_map.get(str(record.get("store_id", "")))
            product = product_map.get(str(record.get("product_id", "")))

            # Layer 2: store scope
            if not _store_allowed(store, accessible_store_pks):
                rejected.append({
                    "sync_id": sync_id,
                    "error": "Permission denied: you are not assigned to that store.",
                })
                continue

            sid = transaction.savepoint()
            try:
                defaults = {
                    "product":       product,
                    "store":         store,
                    "movement_type": record.get("movement_type", "adjustment"),
                    "quantity":      _d(record.get("quantity", 0)),
                    "reference":     record.get("reference", "") or None,
                    "notes":         record.get("notes", "") or None,
                    "unit_price":    _d(record.get("unit_price")) if record.get("unit_price") else None,
                    "total_value":   _d(record.get("total_value")) if record.get("total_value") else None,
                    "created_by":    user,
                }
                obj, created = StockMovement.objects.get_or_create(
                    sync_id=sync_id, defaults=defaults
                )
                transaction.savepoint_commit(sid)
                if not created:
                    # Movements are append-only — send conflict back
                    conflict_objs.append(obj)
                else:
                    accepted.append(sync_id)
            except Exception as e:
                transaction.savepoint_rollback(sid)
                rejected.append({"sync_id": sync_id, "error": str(e)[:200]})

    from .serializers import serialize_stock_movement
    for obj in conflict_objs:
        conflicts.append(serialize_stock_movement(obj, schema_name))

    return accepted, rejected, conflicts


PUSH_HANDLERS = {
    "customers":       _push_customers,
    "sales":           _push_sales,
    "sale_items":      _push_sale_items,
    "expenses":        _push_expenses,
    "categories":      _push_categories,
    "suppliers":       _push_suppliers,
    "products":        _push_products,
    "stock":           _push_stock,
    "stock_movements": _push_stock_movements,
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers (unchanged from original)
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_fk(model_class, sync_id_value):
    if not sync_id_value:
        return None
    sid = parse_sync_id(sync_id_value)
    if not sid:
        return None
    try:
        return model_class.objects.get(sync_id=sid)
    except model_class.DoesNotExist:
        logger.debug(f"FK not found: {model_class.__name__} sync_id={sid}")
        return None


def _d(value) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def _customer_defaults(record: dict) -> dict:
    return {
        "name":             record.get("name", ""),
        "email":            record.get("email", "") or "",
        "phone":            record.get("phone", "") or "",
        "physical_address": record.get("address", "") or "",
        "tin":              record.get("tin", "") or None,
        "is_active":        safe_bool(record.get("is_active", True)),
        "credit_limit":     _d(record.get("credit_limit", 0)),
        "credit_balance":   _d(record.get("current_balance", 0)),
    }


def _apply_customer(obj, record: dict):
    obj.name             = record.get("name", obj.name)
    obj.email            = record.get("email", obj.email) or ""
    obj.phone            = record.get("phone", obj.phone) or ""
    obj.physical_address = record.get("address", obj.physical_address) or ""
    obj.tin              = record.get("tin") or obj.tin
    obj.is_active        = safe_bool(record.get("is_active", obj.is_active))
    obj.credit_limit     = _d(record.get("credit_limit", obj.credit_limit))
    obj.credit_balance   = _d(record.get("current_balance", obj.credit_balance))


def _sale_defaults(record: dict, store, customer, user) -> dict:
    return {
        "document_number": record.get("document_number") or f"DESK-{str(record.get('sync_id', ''))[:8]}",
        "store":           store,
        "customer":        customer,
        "created_by":      user,
        "subtotal":        _d(record.get("subtotal", 0)),
        "tax_amount":      _d(record.get("tax_amount", 0)),
        "discount_amount": _d(record.get("discount_amount", 0)),
        "total_amount":    _d(record.get("total_amount", 0)),
        "status":          (record.get("status", "completed") or "completed").upper(),
        "payment_method":  (record.get("payment_method", "cash") or "cash").upper(),
        "payment_status":  (record.get("payment_status", "paid") or "paid").upper(),
        "notes":           record.get("notes", "") or "",
    }


def _apply_sale(obj, record: dict, store, customer):
    if store:
        obj.store = store
    if customer is not None:
        obj.customer = customer
    obj.subtotal        = _d(record.get("subtotal", obj.subtotal))
    obj.tax_amount      = _d(record.get("tax_amount", obj.tax_amount))
    obj.discount_amount = _d(record.get("discount_amount", obj.discount_amount))
    obj.total_amount    = _d(record.get("total_amount", obj.total_amount))
    obj.status          = (record.get("status", obj.status) or obj.status).upper()
    obj.payment_method  = (record.get("payment_method", obj.payment_method) or obj.payment_method).upper()
    obj.payment_status  = (record.get("payment_status", getattr(obj, "payment_status", "PAID")) or "PAID").upper()
    obj.notes           = record.get("notes", obj.notes) or ""


def _get_schema_name(request) -> str:
    if hasattr(request, "tenant"):
        return request.tenant.schema_name
    return getattr(request, "schema_name", "")