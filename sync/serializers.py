"""
sync/serializers.py
===================
Lightweight serializers for the sync protocol.

Rules:
  1. Every serialized record MUST have a sync_id — never null.
     Old records with sync_id=NULL get one auto-generated here.
  2. Decimal fields are serialized as strings to avoid float precision loss.
  3. ForeignKey fields are serialized as sync_id (not integer pk).
     This lets the desktop match relationships without knowing server PKs.
  4. Timestamps are Unix floats throughout.
"""

import logging
from typing import Optional
from .utils import ensure_sync_id, dt_to_unix, safe_decimal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Base helper
# ─────────────────────────────────────────────────────────────────────────────

def _fk_sync_id(related_instance, table_name: str, schema_name: str = "") -> Optional[str]:
    """Resolve a FK to its sync_id. Returns None if the FK is null."""
    if related_instance is None:
        return None
    return ensure_sync_id(related_instance, table_name, schema_name)


from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# Inventory
# ─────────────────────────────────────────────────────────────────────────────

def serialize_store(obj, schema_name="") -> dict:
    return {
        "sync_id":          ensure_sync_id(obj, "stores", schema_name),
        "name":             obj.name or "",
        "code":             getattr(obj, "code", "") or "",
        "address":          getattr(obj, "physical_address", "") or "",
        "phone":            getattr(obj, "phone", "") or "",
        "email":            getattr(obj, "email", "") or "",
        "is_active":        bool(obj.is_active),
        "is_default":       bool(getattr(obj, "is_main_branch", False)),
        "accessible_by_all": bool(getattr(obj, "accessible_by_all", False)),
        "efris_enabled":    bool(getattr(obj, "efris_enabled", False)),
        "efris_tin":        getattr(obj, "tin", None) or "",
        "created_at":       dt_to_unix(obj.created_at) if hasattr(obj, "created_at") else None,
        "updated_at":       dt_to_unix(obj.updated_at) if hasattr(obj, "updated_at") else None,
    }


def serialize_category(obj, schema_name="") -> dict:
    return {
        "sync_id":                        ensure_sync_id(obj, "categories", schema_name),
        "name":                           obj.name or "",
        "code":                           getattr(obj, "code", "") or "",
        "description":                    getattr(obj, "description", "") or "",
        "category_type":                  getattr(obj, "category_type", "product") or "product",
        "is_active":                      bool(obj.is_active),
        "efris_commodity_category_code":  getattr(obj, "efris_commodity_category_code", "") or "",
        "efris_auto_sync":                bool(getattr(obj, "efris_auto_sync", True)),
        "efris_is_uploaded":              bool(getattr(obj, "efris_is_uploaded", False)),
        "updated_at":                     dt_to_unix(getattr(obj, "updated_at", None)),
        "created_at":                     dt_to_unix(getattr(obj, "created_at", None)),
    }


def serialize_supplier(obj, schema_name="") -> dict:
    return {
        "sync_id":         ensure_sync_id(obj, "suppliers", schema_name),
        "name":            obj.name or "",
        "tin":             getattr(obj, "tin", "") or "",
        "contact_person":  getattr(obj, "contact_person", "") or "",
        "phone":           getattr(obj, "phone", "") or "",
        "email":           getattr(obj, "email", "") or "",
        "address":         getattr(obj, "address", "") or "",
        "country":         getattr(obj, "country", "Uganda") or "Uganda",
        "is_active":       bool(obj.is_active),
        "updated_at":      dt_to_unix(getattr(obj, "updated_at", None)),
        "created_at":      dt_to_unix(getattr(obj, "created_at", None)),
    }


def serialize_product(obj, schema_name="") -> dict:
    # Resolve FK sync_ids
    category_sync_id = None
    if obj.category_id:
        try:
            category_sync_id = ensure_sync_id(obj.category, "categories", schema_name)
        except Exception:
            pass

    supplier_sync_id = None
    if obj.supplier_id:
        try:
            supplier_sync_id = ensure_sync_id(obj.supplier, "suppliers", schema_name)
        except Exception:
            pass

    return {
        "sync_id":                  ensure_sync_id(obj, "products", schema_name),
        "category_id":              category_sync_id,
        "supplier_id":              supplier_sync_id,
        "name":                     obj.name or "",
        "sku":                      obj.sku or "",
        "barcode":                  getattr(obj, "barcode", "") or "",
        "description":              getattr(obj, "description", "") or "",
        "selling_price":            safe_decimal(obj.selling_price),
        "cost_price":               safe_decimal(obj.cost_price),
        "discount_percentage":      safe_decimal(getattr(obj, "discount_percentage", 0)),
        "tax_rate":                 getattr(obj, "tax_rate", "A") or "A",
        "excise_duty_rate":         safe_decimal(getattr(obj, "excise_duty_rate", 0)),
        "unit_of_measure":          getattr(obj, "unit_of_measure", "103") or "103",
        "min_stock_level":          int(getattr(obj, "min_stock_level", 5) or 5),
        "is_active":                bool(obj.is_active),
        "efris_is_uploaded":        bool(getattr(obj, "efris_is_uploaded", False)),
        "efris_auto_sync_enabled":  bool(getattr(obj, "efris_auto_sync_enabled", True)),
        "efris_goods_code_field":   getattr(obj, "efris_goods_code_field", "") or "",
        "efris_service_mark":       getattr(obj, "efris_service_mark", "102") or "102",
        "updated_at":               dt_to_unix(getattr(obj, "updated_at", None)),
        "created_at":               dt_to_unix(getattr(obj, "created_at", None)),
    }


import time

def serialize_stock(obj, schema_name="") -> dict:
    product_sync_id = None
    if obj.product_id:
        try:
            product_sync_id = ensure_sync_id(obj.product, "products", schema_name)
        except Exception:
            pass

    store_sync_id = None
    if obj.store_id:
        try:
            store_sync_id = ensure_sync_id(obj.store, "stores", schema_name)
        except Exception:
            pass

    return {
        "sync_id":             ensure_sync_id(obj, "stock", schema_name),
        "product_id":          product_sync_id,
        "store_id":            store_sync_id,
        "quantity":            safe_decimal(obj.quantity),
        "low_stock_threshold": safe_decimal(getattr(obj, "low_stock_threshold", 5)),
        "reorder_quantity":    safe_decimal(getattr(obj, "reorder_quantity", 10)),
        "updated_at":          (
            dt_to_unix(getattr(obj, "updated_at", None))
            or dt_to_unix(getattr(obj, "last_updated", None))
            or time.time()
        ),
    }

def serialize_stock_movement(obj, schema_name="") -> dict:
    product_sync_id = None
    if obj.product_id:
        try:
            product_sync_id = ensure_sync_id(obj.product, "products", schema_name)
        except Exception:
            pass

    store_sync_id = None
    if obj.store_id:
        try:
            store_sync_id = ensure_sync_id(obj.store, "stores", schema_name)
        except Exception:
            pass

    return {
        "sync_id":       ensure_sync_id(obj, "stock_movements", schema_name),
        "product_id":    product_sync_id,
        "store_id":      store_sync_id,
        "movement_type": obj.movement_type or "",
        "quantity":      safe_decimal(obj.quantity),
        "reference":     getattr(obj, "reference", "") or "",
        "notes":         getattr(obj, "notes", "") or "",
        "unit_price":    safe_decimal(getattr(obj, "unit_price", None)),
        "total_value":   safe_decimal(getattr(obj, "total_value", None)),
        "updated_at": (
            dt_to_unix(getattr(obj, "updated_at", None))
            or dt_to_unix(getattr(obj, "created_at", None))
            or time.time()
        ),
        "created_at": (
            dt_to_unix(getattr(obj, "created_at", None))
            or time.time()
        ),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Customers
# ─────────────────────────────────────────────────────────────────────────────

def serialize_customer(obj, schema_name="") -> dict:
    return {
        "sync_id":          ensure_sync_id(obj, "customers", schema_name),
        "name":             obj.name or "",
        "email":            getattr(obj, "email", "") or "",
        "phone":            getattr(obj, "phone", "") or "",
        # server field is physical_address, desktop expects address
        "address":          getattr(obj, "physical_address", "") or "",
        "tin":              getattr(obj, "tin", "") or "",
        "is_active":        bool(obj.is_active),
        "credit_limit":     safe_decimal(getattr(obj, "credit_limit", 0)),
        # server field is credit_balance, desktop expects current_balance
        "current_balance":  safe_decimal(getattr(obj, "credit_balance", 0)),
        # no loyalty_points on server — send 0
        "loyalty_points":   0,
        "updated_at":       dt_to_unix(getattr(obj, "updated_at", None)) or time.time(),
        "created_at":       dt_to_unix(getattr(obj, "created_at", None)) or time.time(),
    }

# ─────────────────────────────────────────────────────────────────────────────
# Sales
# ─────────────────────────────────────────────────────────────────────────────

def serialize_sale(obj, schema_name="") -> dict:
    store_sync_id = None
    if obj.store_id:
        try:
            store_sync_id = ensure_sync_id(obj.store, "stores", schema_name)
        except Exception:
            pass

    customer_sync_id = None
    if obj.customer_id:
        try:
            customer_sync_id = ensure_sync_id(obj.customer, "customers", schema_name)
        except Exception:
            pass

    return {
        "sync_id":               ensure_sync_id(obj, "sales", schema_name),
        "document_number":       obj.document_number or "",
        "store_id":              store_sync_id,
        "customer_id":           customer_sync_id,
        "subtotal":              safe_decimal(obj.subtotal),
        "tax_amount":            safe_decimal(obj.tax_amount),
        "discount_amount":       safe_decimal(obj.discount_amount),
        "total_amount":          safe_decimal(obj.total_amount),
        "amount_paid":           safe_decimal(obj.amount_paid),
        "change_amount":         safe_decimal(getattr(obj, "change_amount", 0)),
        "status":                (obj.status or "completed").lower(),
        "payment_method":        (obj.payment_method or "cash").lower(),
        "payment_status":        (getattr(obj, "payment_status", "paid") or "paid").lower(),
        "is_fiscalized":         bool(getattr(obj, "is_fiscalized", False)),
        "fiscal_document_number": getattr(obj, "efris_invoice_number", "") or "",
        "notes":                 getattr(obj, "notes", "") or "",
        "updated_at":            dt_to_unix(getattr(obj, "updated_at", None)),
        "created_at":            dt_to_unix(getattr(obj, "created_at", None)),
        "created_by_id":         str(getattr(obj.created_by, 'sync_id', '') or ""),
    }


import time

def serialize_sale_item(obj, schema_name="") -> dict:
    sale_sync_id = None
    if obj.sale_id:
        try:
            sale_sync_id = ensure_sync_id(obj.sale, "sales", schema_name)
        except Exception:
            pass

    product_sync_id = None
    if obj.product_id:
        try:
            product_sync_id = ensure_sync_id(obj.product, "products", schema_name)
        except Exception:
            pass

    # SaleItem has no updated_at — fall back to parent sale's updated_at, then now
    updated_at = (
        dt_to_unix(getattr(obj, "updated_at", None))
        or dt_to_unix(getattr(obj.sale, "updated_at", None))
        or time.time()
    )

    return {
        "sync_id":             ensure_sync_id(obj, "sale_items", schema_name),
        "sale_id":             sale_sync_id,
        "product_id":          product_sync_id,
        "quantity":            safe_decimal(obj.quantity),
        "unit_price":          safe_decimal(obj.unit_price),
        "discount_percentage": safe_decimal(getattr(obj, "discount", 0)),
        "tax_rate":            getattr(obj, "tax_rate", "A") or "A",
        "tax_amount":          safe_decimal(getattr(obj, "tax_amount", 0)),
        "subtotal":            safe_decimal(obj.total_price),
        "total":               safe_decimal(obj.line_total),
        "updated_at":          updated_at,
    }
# ─────────────────────────────────────────────────────────────────────────────
# Expenses
# ─────────────────────────────────────────────────────────────────────────────

def serialize_expense(obj, schema_name="") -> dict:
    return {
        "sync_id":        ensure_sync_id(obj, "expenses", schema_name),
        "title":          getattr(obj, "description", "") or "",   # no title field — use description
        "description":    getattr(obj, "notes", "") or "",         # map notes → description
        "amount":         safe_decimal(obj.amount),
        "expense_date":   dt_to_unix(getattr(obj, "date", None)),  # date → expense_date
        "category":       "",                                       # no category on server
        "payment_method": (getattr(obj, "payment_method", "cash") or "cash").lower(),
        "reference":      "",                                       # no reference on server
        "store_id":       None,                                     # no store FK on server
        "created_by_id":  str(getattr(obj.user, 'sync_id', '') or "") if obj.user else "",
        "status":         getattr(obj, "status", "pending") or "pending",
        "notes":          getattr(obj, "notes", "") or "",
        "updated_at":     dt_to_unix(getattr(obj, "updated_at", None)),
        "created_at":     dt_to_unix(getattr(obj, "created_at", None)),
    }