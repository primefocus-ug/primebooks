"""
PrimeBooks — Universal Tracker API
====================================
Endpoint: GET /api/track/?type=<type>&id=<pk>

Wire up (urls.py):
    from accounts.tracking_api import TrackingAPIView
    path("api/track/", TrackingAPIView.as_view(), name="universal-track"),

To add a new model:
    1. Subclass BaseTracker
    2. Implement get_object / meta / stats / efris / sections
    3. Add one line to REGISTRY at the bottom

Field names are taken directly from your actual models.py files.
"""

import logging
from django.contrib.contenttypes.models import ContentType
from django.utils import timezone
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Sum

logger = logging.getLogger(__name__)


# ─── FORMATTING HELPERS ───────────────────────────────────────────────────────

def fmt_ugx(val, currency="UGX"):
    try:
        return f"{currency} {int(val):,}" if val is not None else "—"
    except Exception:
        return str(val) if val is not None else "—"

def fmt_qty(val, unit=""):
    if val is None:
        return "—"
    try:
        s = f"{float(val):,.3f}".rstrip("0").rstrip(".")
        return f"{s} {unit}".strip() if unit else s
    except Exception:
        return str(val)

def fmt_dt(dt):
    return dt.isoformat() if dt else None

def fmt_date(d):
    return d.strftime("%d %b %Y") if d else "—"

def fmt_datetime(dt):
    return dt.strftime("%d %b %Y, %H:%M") if dt else "—"


# ─── AUDIT LOG HELPERS ────────────────────────────────────────────────────────

def action_severity(action):
    errors = {
        "login_failed", "account_locked", "suspicious_activity", "sale_voided",
        "product_deleted", "efris_failed", "expense_rejected", "user_deactivated",
        "session_superseded", "token_superseded",
    }
    warnings = {
        "stock_adjusted", "password_changed", "account_unlocked", "permission_changed",
        "sharing_detected",
    }
    successes = {
        "login_success", "sale_completed", "invoice_paid", "efris_fiscalized",
        "expense_approved", "expense_paid", "user_activated", "2fa_enabled",
        "sale_created", "product_created", "user_created", "stock_added",
    }
    if action in errors:    return "error"
    if action in warnings:  return "warning"
    if action in successes: return "success"
    return "info"

def build_audit_items(audit_qs):
    """Convert AuditLog queryset → frontend audit section items."""
    items = []
    for log in audit_qs.order_by("-timestamp"):
        diff = None
        changes = log.changes or {}
        before  = changes.get("before", {})
        after   = changes.get("after",  {})
        if before and after:
            for key in before:
                if key in after and before[key] != after[key]:
                    bv, av = before[key], after[key]
                    if any(x in str(key) for x in ("price", "amount", "cost", "total", "rate")):
                        bv = fmt_ugx(bv)
                        av = fmt_ugx(av)
                    diff = {"from": str(bv), "to": str(av)}
                    break
        items.append({
            "id":          log.pk,
            "description": log.action_description,
            "user":        log.user.get_full_name() if log.user else "System",
            "date":        fmt_dt(log.timestamp),
            "severity":    action_severity(log.action),
            "diff":        diff,
        })
    return items

def get_audit_qs(obj):
    """Return AuditLog queryset for any model instance."""
    from accounts.models import AuditLog
    ct = ContentType.objects.get_for_model(obj)
    return AuditLog.objects.filter(content_type=ct, object_id=str(obj.pk))


# ─── BASE TRACKER ──────────────────────────────────────────────────────────────

class BaseTracker:
    """
    Subclass this for every model you want to support.

    Section 'type' values understood by tracker.js:
        "timeline"  — items: [{label, sub, tag, qty, running, note, user, date}]
        "audit"     — items: [{description, user, date, severity, diff:{from,to}}]
        "table"     — columns:[...], rows:[[...]]  (last col highlighted green)
        "lineitems" — same as table, styled for sale/invoice lines
        "keyvalue"  — pairs:[{label, value}]
    """
    def get_object(self, pk, user): raise NotImplementedError
    def meta(self, obj, user):      raise NotImplementedError
    def stats(self, obj, user):     return []
    def efris(self, obj, user):     return {"status": "not_applicable"}
    def sections(self, obj, user):  return []

    def build(self, pk, user):
        obj = self.get_object(pk, user)
        if obj is None:
            return None
        return {
            "meta":     self.meta(obj, user),
            "stats":    self.stats(obj, user),
            "efris":    self.efris(obj, user),
            "sections": self.sections(obj, user),
        }


# ─── PRODUCT TRACKER ──────────────────────────────────────────────────────────
#
# Model:   inventory.Product
# Stock:   inventory.Stock  (related_name on Product = 'store_inventory')
# Moves:   inventory.StockMovement  (related_name on Product = 'movements')
#
# Key field names confirmed from models.py:
#   Product.selling_price / cost_price / unit_of_measure (str code) / min_stock_level
#   Product.sku / barcode / category (FK) / supplier (FK)
#   Product.efris_is_uploaded / efris_upload_date / efris_item_code / efris_goods_id
#   Stock.quantity / low_stock_threshold / store (FK)
#   StockMovement.product / store / movement_type / quantity / reference / notes
#                .unit_price / total_value / created_by / created_at

class ProductTracker(BaseTracker):

    def get_object(self, pk, user):
        from inventory.models import Product
        try:
            return Product.objects.select_related(
                "category", "supplier"
            ).get(pk=pk)
        except Product.DoesNotExist:
            return None

    def _stock_data(self, obj, user):
        """
        Stock is stored in inventory.Stock.
        Related name from Product → store_inventory (NOT 'stocks').
        Returns (list_of_stock_records, total_qty, threshold, unit_label).
        """
        from inventory.models import Stock
        accessible_stores = user.get_accessible_stores()
        stock_qs = Stock.objects.filter(
            product=obj,
            store__in=accessible_stores
        ).select_related("store")
        stocks    = list(stock_qs)
        total_qty = sum(float(s.quantity) for s in stocks)
        threshold = max((float(s.low_stock_threshold) for s in stocks), default=float(obj.min_stock_level))
        # unit_of_measure on Product is a choice code string (e.g. "103"="Kg", "PCE"="Piece")
        # Get human label from UNIT_CHOICES dict if possible
        unit_code = obj.unit_of_measure or "103"
        unit_dict = dict(obj.UNIT_CHOICES)
        unit_label = unit_dict.get(unit_code, unit_code)
        # Shorten long labels — keep only the first word after any dash
        if "-" in unit_label:
            unit_label = unit_label.split("-", 1)[1].strip().split()[0]
        return stocks, total_qty, threshold, unit_label

    def _stock_badge(self, total_qty, threshold):
        if total_qty == 0:           return "Out of Stock", "red"
        if total_qty <= threshold:   return "Low Stock",    "yellow"
        return "Good Stock", "green"

    def meta(self, obj, user):
        _, total_qty, threshold, unit = self._stock_data(obj, user)
        badge, color = self._stock_badge(total_qty, threshold)
        cat_name = obj.category.name if obj.category else "—"
        return {
            "title":       obj.name,
            "subtitle":    f"{cat_name} · {obj.sku}",
            "badge":       badge,
            "badge_color": color,
            "id_label":    obj.sku or obj.barcode or f"ID {obj.pk}",
        }

    def stats(self, obj, user):
        _, total_qty, threshold, unit = self._stock_data(obj, user)
        badge, color = self._stock_badge(total_qty, threshold)
        efris_val   = "Registered" if obj.efris_is_uploaded else "Pending"
        efris_color = "purple"     if obj.efris_is_uploaded else "yellow"
        return [
            {"label": "Current Stock",  "value": fmt_qty(total_qty, unit),    "color": color},
            {"label": "Selling Price",  "value": fmt_ugx(obj.selling_price),  "color": "blue"},
            {"label": "Cost Price",     "value": fmt_ugx(obj.cost_price),     "color": "dim"},
            {"label": "EFRIS",          "value": efris_val,                    "color": efris_color},
        ]

    def efris(self, obj, user):
        if not obj.efris_is_uploaded:
            return {"status": "pending"}
        return {
            "status":    "fiscalized",
            "reference": obj.efris_item_code or obj.efris_goods_id or "",
            "synced_at": fmt_dt(obj.efris_upload_date),
        }

    def sections(self, obj, user):
        from inventory.models import StockMovement

        accessible_stores = user.get_accessible_stores()
        # StockMovement.movements is the related_name from Product
        movements = StockMovement.objects.filter(
            product=obj,
            store__in=accessible_stores
        ).select_related("created_by", "store").order_by("created_at")

        # Types that decrease stock
        DECREASE = {"SALE", "TRANSFER_OUT", "VOID", "REFUND"}

        running, tl_items = 0.0, []
        for m in movements:
            q = float(m.quantity)
            q = -abs(q) if m.movement_type in DECREASE else abs(q)
            running += q
            sign = "+" if q >= 0 else "−"
            tl_items.append({
                "id":      m.pk,
                "label":   m.get_movement_type_display(),
                "sub":     m.reference or "",
                "tag":     m.movement_type,
                "qty":     f"{sign}{abs(int(float(m.quantity)))}",
                "running": fmt_qty(running),
                "note":    m.notes or "",
                "user":    m.created_by.get_full_name() if m.created_by else "System",
                "date":    fmt_dt(m.created_at),
            })

        # Stock per store — keyvalue section
        stocks, _, _, unit = self._stock_data(obj, user)
        store_pairs = [
            {"label": s.store.name, "value": fmt_qty(s.quantity, unit)}
            for s in stocks
        ] or [{"label": "No stock records found", "value": "—"}]

        # Product details
        detail_pairs = [
            {"label": "SKU",          "value": obj.sku or "—"},
            {"label": "Barcode",      "value": obj.barcode or "—"},
            {"label": "Tax Rate",     "value": obj.get_tax_rate_display()},
            {"label": "Unit",         "value": obj.get_unit_of_measure_display() if hasattr(obj, 'get_unit_of_measure_display') else obj.unit_of_measure},
            {"label": "Min Stock",    "value": str(obj.min_stock_level)},
            {"label": "Supplier",     "value": obj.supplier.name if obj.supplier else "—"},
        ]
        if obj.discount_percentage:
            detail_pairs.append({"label": "Discount", "value": f"{obj.discount_percentage}%"})

        sections = [
            {
                "id": "movements", "title": "Stock Movements",
                "type": "timeline", "items": list(reversed(tl_items)),
            },
            {
                "id": "stock_by_store", "title": "Stock by Store",
                "type": "keyvalue", "pairs": store_pairs,
            },
            {
                "id": "details", "title": "Product Details",
                "type": "keyvalue", "pairs": detail_pairs,
            },
        ]

        audit_items = build_audit_items(get_audit_qs(obj))
        if audit_items:
            sections.append({
                "id": "audit", "title": "Change History",
                "type": "audit", "items": audit_items,
            })

        return sections


# ─── SALE TRACKER ─────────────────────────────────────────────────────────────
#
# Model:  sales.Sale
# Fields: document_number / document_type / status / total_amount
#         payment_method / is_fiscalized / efris_irn / fiscalized_at
# Related: .items (SaleItem) / .payments (Payment)
# SaleItem: product (FK) / quantity / unit_price / total_price
# Payment:  amount / payment_method / reference_number / is_voided / created_at

class SaleTracker(BaseTracker):

    def get_object(self, pk, user):
        from sales.models import Sale
        try:
            return Sale.objects.select_related(
                "customer", "store", "created_by", "customer"
            ).get(pk=pk, store__in=user.get_accessible_stores())
        except Sale.DoesNotExist:
            return None

    def meta(self, obj, user):
        is_fisc      = getattr(obj, "is_fiscalized", False)
        status_label = obj.get_status_display() if hasattr(obj, "get_status_display") else str(obj.status)
        badge        = "Fiscalized" if is_fisc else status_label
        color        = "purple"     if is_fisc else "green"
        customer_name = obj.customer.name if obj.customer else "Walk-in"
        return {
            "title":       obj.document_number or f"Sale #{obj.pk}",
            "subtitle":    f"{customer_name} · {obj.store.name}",
            "badge":       badge,
            "badge_color": color,
            "id_label":    fmt_datetime(obj.created_at),
        }

    def stats(self, obj, user):
        payment_str = str(getattr(obj, "payment_method", None) or "—")
        served_str  = obj.created_by.get_full_name() if getattr(obj, "created_by", None) else "—"
        doc_type    = obj.get_document_type_display() if hasattr(obj, "get_document_type_display") else getattr(obj, "document_type", "SALE")
        item_count  = obj.items.count() if hasattr(obj, "items") else 0
        return [
            {"label": "Total Amount",  "value": fmt_ugx(obj.total_amount),  "color": "green"},
            {"label": "Payment",       "value": payment_str,                "color": "blue"},
            {"label": "Served By",     "value": served_str,                 "color": "dim"},
            {"label": "Document Type", "value": doc_type,                   "color": "dim"},
        ]

    def efris(self, obj, user):
        is_fisc = getattr(obj, "is_fiscalized", False)
        if not is_fisc:
            return {"status": "pending"}
        return {
            "status":    "fiscalized",
            "reference": getattr(obj, "efris_irn", None) or getattr(obj, "efris_reference", None) or "",
            "synced_at": fmt_dt(getattr(obj, "fiscalized_at", None)),
        }

    def sections(self, obj, user):
        from sales.models import SaleItem
        from inventory.models import StockMovement

        # ── Line items ─────────────────────────────────────────────────────────
        rows = []
        for item in SaleItem.objects.filter(sale=obj).select_related("product"):
            rows.append([
                item.product.name if item.product else "—",
                item.product.sku  if item.product else "",
                fmt_qty(item.quantity),
                fmt_ugx(item.unit_price,  ""),
                fmt_ugx(item.total_price, ""),
            ])

        # ── Payments ──────────────────────────────────────────────────────────
        payment_rows = []
        if hasattr(obj, "payments"):
            for pmt in obj.payments.filter(is_voided=False).order_by("created_at"):
                payment_rows.append([
                    fmt_datetime(pmt.created_at),
                    str(pmt.payment_method or "—"),
                    pmt.reference_number or "—",
                    fmt_ugx(pmt.amount, ""),
                ])

        # ── Sale timeline ──────────────────────────────────────────────────────
        tl = [{
            "id": "t_created", "label": "Sale initiated",
            "sub": obj.document_number or f"#{obj.pk}",
            "tag": "created",
            "note": f"{obj.store.name} · {getattr(obj, 'document_type', 'SALE')}",
            "user": obj.created_by.get_full_name() if getattr(obj, "created_by", None) else "System",
            "date": fmt_dt(obj.created_at),
        }]

        if hasattr(obj, "payments"):
            for pmt in obj.payments.filter(is_voided=False).order_by("created_at"):
                tl.append({
                    "id": f"pmt_{pmt.pk}", "label": "Payment received",
                    "sub": str(pmt.payment_method or ""),
                    "tag": "paid",
                    "note": f"{fmt_ugx(pmt.amount)} · {pmt.reference_number or '—'}",
                    "user": obj.created_by.get_full_name() if getattr(obj, "created_by", None) else "System",
                    "date": fmt_dt(pmt.created_at),
                })

        if getattr(obj, "is_fiscalized", False):
            tl.append({
                "id": "t_efris", "label": "Fiscalized on EFRIS",
                "sub": getattr(obj, "efris_irn", "") or "",
                "tag": "efris",
                "note": "Receipt registered with URA",
                "user": "System",
                "date": fmt_dt(getattr(obj, "fiscalized_at", None)),
            })

        # Stock deductions via StockMovement (reference contains document number)
        doc_ref = obj.document_number or str(obj.pk)
        for sm in StockMovement.objects.filter(
            reference__icontains=doc_ref,
            movement_type="SALE"
        ).select_related("product").order_by("created_at"):
            tl.append({
                "id": f"sm_{sm.pk}", "label": "Stock deducted",
                "sub": f"{fmt_qty(sm.quantity)}× {sm.product.name if sm.product else '—'}",
                "tag": "SALE", "qty": f"−{int(float(sm.quantity))}",
                "note": sm.notes or "", "user": "System",
                "date": fmt_dt(sm.created_at),
            })

        tl.sort(key=lambda x: x.get("date") or "")

        sections = [
            {
                "id": "lineitems", "title": "Line Items",
                "type": "lineitems",
                "columns": ["Product", "SKU", "Qty", "Unit Price", "Total"],
                "rows": rows,
            },
        ]

        if payment_rows:
            sections.append({
                "id": "payments", "title": "Payments",
                "type": "table",
                "columns": ["Date", "Method", "Reference", "Amount"],
                "rows": payment_rows,
            })

        sections.append({
            "id": "timeline", "title": "Sale Timeline",
            "type": "timeline", "items": list(reversed(tl)),
        })

        audit_items = build_audit_items(get_audit_qs(obj))
        if audit_items:
            sections.append({
                "id": "audit", "title": "Change History",
                "type": "audit", "items": audit_items,
            })

        return sections


# ─── EXPENSE TRACKER ──────────────────────────────────────────────────────────
#
# Model:   expenses.Expense
# Fields:  user (FK) / amount / currency / exchange_rate / amount_base
#          description / vendor / payment_method / status / date
#          receipt / ocr_processed / ocr_vendor / ocr_amount / notes
#          is_recurring / recurrence_interval / next_recurrence_date
# Related: .approvals (ExpenseApproval)
# ExpenseApproval fields: actor / action / comment / previous_status
#                         new_status / created_at

class ExpenseTracker(BaseTracker):

    def get_object(self, pk, user):
        from expenses.models import Expense
        try:
            # Expense is linked to user, not store — scope by company via user
            return Expense.objects.select_related("user").get(
                pk=pk, user__company=user.company
            )
        except Expense.DoesNotExist:
            return None

    def meta(self, obj, user):
        STATUS_COLORS = {
            "draft":        "dim",
            "submitted":    "blue",
            "under_review": "yellow",
            "approved":     "green",
            "rejected":     "red",
            "resubmit":     "yellow",
        }
        color = STATUS_COLORS.get(obj.status, "dim")
        # Strip leading emoji from display value
        raw_badge = obj.get_status_display()
        badge = raw_badge.split(" ", 1)[-1] if raw_badge[0] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" else raw_badge
        return {
            "title":       obj.description,
            "subtitle":    f"{obj.vendor or 'No vendor'} · {fmt_date(obj.date)}",
            "badge":       badge,
            "badge_color": color,
            "id_label":    f"EXP-{obj.pk:05d}",
        }

    def stats(self, obj, user):
        submitted_by = obj.user.get_full_name() if obj.user else "—"

        from expenses.models import ExpenseApproval
        last_decision = ExpenseApproval.objects.filter(
            expense=obj, action__in=["approved", "rejected"]
        ).order_by("-created_at").first()
        approved_by = (
            last_decision.actor.get_full_name()
            if last_decision and last_decision.actor
            else "Pending"
        )

        # Strip emoji from payment method display
        raw_pmt = dict(obj.PAYMENT_METHODS).get(obj.payment_method, obj.payment_method or "—")
        payment_str = raw_pmt.split(" ", 1)[-1] if raw_pmt and raw_pmt[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else raw_pmt

        return [
            {"label": "Amount",       "value": fmt_ugx(obj.amount, obj.currency), "color": "green"},
            {"label": "Payment",      "value": payment_str,                        "color": "blue"},
            {"label": "Submitted By", "value": submitted_by,                       "color": "dim"},
            {"label": "Approved By",  "value": approved_by,                        "color": "dim" if approved_by == "Pending" else "green"},
        ]

    def sections(self, obj, user):
        from expenses.models import ExpenseApproval

        # ── Approval timeline ──────────────────────────────────────────────────
        ACTION_TAGS = {
            "submitted":    "created",
            "under_review": "updated",
            "approved":     "approved",
            "rejected":     "rejected",
            "resubmit":     "updated",
            "cancelled":    "cancelled",
            "comment":      "updated",
        }
        ACTION_SEV = {
            "submitted":    "info",
            "under_review": "info",
            "approved":     "success",
            "rejected":     "error",
            "resubmit":     "warning",
            "cancelled":    "warning",
            "comment":      "info",
        }

        tl_items = []
        for ap in obj.approvals.select_related("actor").order_by("created_at"):
            raw = ap.get_action_display()
            label = raw.split(" ", 1)[-1].strip() if raw[0] not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ" else raw
            note = ap.comment or ""
            if ap.previous_status and ap.new_status and ap.previous_status != ap.new_status:
                note = f"Status: {ap.previous_status} → {ap.new_status}" + (f" · {ap.comment}" if ap.comment else "")
            tl_items.append({
                "id":    ap.pk,
                "label": label,
                "sub":   "",
                "tag":   ACTION_TAGS.get(ap.action, "updated"),
                "note":  note,
                "user":  ap.actor.get_full_name() if ap.actor else "System",
                "date":  fmt_dt(ap.created_at),
            })

        # ── Details keyvalue ───────────────────────────────────────────────────
        pairs = [
            {"label": "Description",  "value": obj.description},
            {"label": "Vendor",       "value": obj.vendor or "—"},
            {"label": "Date",         "value": fmt_date(obj.date)},
            {"label": "Currency",     "value": obj.currency},
        ]
        if str(obj.currency) != "UGX":
            pairs.append({"label": "Exchange Rate", "value": str(obj.exchange_rate)})
            pairs.append({"label": "Base Amount",   "value": fmt_ugx(obj.amount_base)})
        if obj.is_recurring:
            raw_ri = obj.get_recurrence_interval_display() if obj.recurrence_interval else "—"
            pairs.append({"label": "Recurring",  "value": raw_ri})
            if obj.next_recurrence_date:
                pairs.append({"label": "Next Due", "value": fmt_date(obj.next_recurrence_date)})
        if obj.notes:
            pairs.append({"label": "Notes", "value": obj.notes})
        if obj.ocr_processed:
            pairs.append({"label": "OCR Vendor", "value": obj.ocr_vendor or "—"})
            if obj.ocr_amount:
                pairs.append({"label": "OCR Amount", "value": fmt_ugx(obj.ocr_amount)})

        return [
            {
                "id": "details", "title": "Expense Details",
                "type": "keyvalue", "pairs": pairs,
            },
            {
                "id": "timeline", "title": "Approval History",
                "type": "timeline", "items": tl_items,
            },
        ]


# ─── CUSTOMER TRACKER ─────────────────────────────────────────────────────────
#
# Model:   customers.Customer
# Fields:  name / customer_type / email / phone / tin / nin / brn
#          store (FK) / credit_limit / credit_balance / credit_available
#          allow_credit / credit_status / is_active
#          efris_status / efris_customer_id / efris_registered_at
#          efris_last_sync / efris_reference_no
# Related: .credit_statements (CustomerCreditStatement)
#          .efris_syncs (EFRISCustomerSync)

class CustomerTracker(BaseTracker):

    def get_object(self, pk, user):
        from customers.models import Customer
        try:
            return Customer.objects.select_related("store", "created_by").get(
                pk=pk, store__in=user.get_accessible_stores()
            )
        except Customer.DoesNotExist:
            return None

    def meta(self, obj, user):
        if not obj.is_active:
            badge, color = "Inactive", "dim"
        elif obj.credit_status == "BLOCKED":
            badge, color = "Blocked", "red"
        elif obj.credit_status == "SUSPENDED":
            badge, color = "Suspended", "red"
        elif obj.credit_status == "WARNING":
            badge, color = "Payment Warning", "yellow"
        else:
            badge, color = "Active", "green"

        return {
            "title":       obj.name or f"Customer #{obj.pk}",
            "subtitle":    f"{obj.get_customer_type_display()} · {obj.store.name}",
            "badge":       badge,
            "badge_color": color,
            "id_label":    str(obj.customer_id)[:8].upper(),
        }

    def stats(self, obj, user):
        efris_color = {
            "REGISTERED":    "purple",
            "PENDING":       "yellow",
            "FAILED":        "red",
            "NOT_REGISTERED":"dim",
            "UPDATED":       "blue",
        }.get(obj.efris_status, "dim")

        return [
            {"label": "Credit Balance",   "value": fmt_ugx(obj.credit_balance),          "color": "red" if obj.credit_balance > 0 else "green"},
            {"label": "Credit Limit",     "value": fmt_ugx(obj.credit_limit),             "color": "blue"},
            {"label": "Available Credit", "value": fmt_ugx(obj.credit_available),         "color": "green"},
            {"label": "EFRIS",            "value": obj.get_efris_status_display(),        "color": efris_color},
        ]

    def efris(self, obj, user):
        status_map = {
            "REGISTERED":    "fiscalized",
            "PENDING":       "pending",
            "FAILED":        "failed",
            "NOT_REGISTERED":"not_applicable",
            "UPDATED":       "fiscalized",
        }
        efris_status = status_map.get(obj.efris_status, "not_applicable")
        if efris_status == "not_applicable":
            return {"status": "not_applicable"}
        return {
            "status":    efris_status,
            "reference": obj.efris_customer_id or obj.efris_reference_no or "",
            "synced_at": fmt_dt(obj.efris_last_sync or obj.efris_registered_at),
        }

    def sections(self, obj, user):
        from customers.models import CustomerCreditStatement, EFRISCustomerSync

        # ── Credit statement (CustomerCreditStatement) ─────────────────────────
        # Fields: transaction_type / amount / balance_before / balance_after
        #         description / created_at
        credit_rows = []
        for stmt in obj.credit_statements.order_by("-created_at")[:20]:
            credit_rows.append([
                fmt_datetime(stmt.created_at),
                stmt.get_transaction_type_display(),
                (stmt.description or "—")[:40],
                fmt_ugx(stmt.amount, ""),
                fmt_ugx(stmt.balance_after, ""),
            ])

        # ── Recent sales via the total_outstanding property logic ──────────────
        sale_rows = []
        try:
            from sales.models import Sale
            for s in Sale.objects.filter(customer=obj).order_by("-created_at")[:10]:
                sale_rows.append([
                    s.document_number or f"#{s.pk}",
                    fmt_datetime(s.created_at) if s.created_at else "—",
                    getattr(s, "document_type", "SALE"),
                    fmt_ugx(s.total_amount, ""),
                    s.get_status_display() if hasattr(s, "get_status_display") else str(s.status),
                ])
        except Exception:
            pass

        # ── EFRIS sync history (EFRISCustomerSync) ─────────────────────────────
        # Fields: sync_type / status / error_message / efris_reference
        #         retry_count / created_at
        efris_tl = []
        for sync in obj.efris_syncs.order_by("-created_at")[:10]:
            sev  = "success" if sync.status == "SUCCESS" else "error" if sync.status == "FAILED" else "info"
            note = sync.error_message or sync.efris_reference or ""
            efris_tl.append({
                "id":    sync.pk,
                "label": f"EFRIS {sync.get_sync_type_display()}",
                "sub":   sync.efris_reference or "",
                "tag":   "efris" if sync.status == "SUCCESS" else "rejected",
                "note":  (note[:80] if note else ""),
                "user":  "System",
                "date":  fmt_dt(sync.created_at),
            })

        # ── Contact/ID details ─────────────────────────────────────────────────
        pairs = [
            {"label": "Phone",   "value": obj.phone or "—"},
            {"label": "Email",   "value": obj.email or "—"},
            {"label": "Type",    "value": obj.get_customer_type_display()},
            {"label": "Country", "value": obj.country or "Uganda"},
        ]
        if obj.tin:   pairs.append({"label": "TIN", "value": obj.tin})
        if obj.nin:   pairs.append({"label": "NIN", "value": obj.nin})
        if obj.brn:   pairs.append({"label": "BRN", "value": obj.brn})
        if obj.allow_credit:
            pairs.append({"label": "Credit Days",   "value": str(obj.credit_days)})
            pairs.append({"label": "Credit Status", "value": obj.get_credit_status_display()})

        sections = [
            {"id": "details", "title": "Customer Details", "type": "keyvalue", "pairs": pairs},
        ]
        if sale_rows:
            sections.append({
                "id": "sales", "title": "Recent Sales", "type": "table",
                "columns": ["Document", "Date", "Type", "Amount", "Status"],
                "rows": sale_rows,
            })
        if credit_rows:
            sections.append({
                "id": "credit", "title": "Credit Statement", "type": "table",
                "columns": ["Date", "Type", "Description", "Amount", "Balance"],
                "rows": credit_rows,
            })
        if efris_tl:
            sections.append({
                "id": "efris_history", "title": "EFRIS Sync History",
                "type": "timeline", "items": efris_tl,
            })
        audit_items = build_audit_items(get_audit_qs(obj))
        if audit_items:
            sections.append({"id": "audit", "title": "Change History", "type": "audit", "items": audit_items})
        return sections


# ─── EXPENSE BUDGET TRACKER ───────────────────────────────────────────────────
#
# Model:   expenses.Budget
# Fields:  user (FK) / name / amount / period / currency / alert_threshold
#          is_active / tags (TaggableManager)
# Methods: get_period_dates() / get_current_spending() / get_remaining()
#          get_percentage_used()

class BudgetTracker(BaseTracker):

    def get_object(self, pk, user):
        from expenses.models import Budget
        try:
            return Budget.objects.get(pk=pk, user__company=user.company)
        except Budget.DoesNotExist:
            return None

    def meta(self, obj, user):
        pct   = float(obj.get_percentage_used())
        thr   = float(obj.alert_threshold)
        if pct >= 100:      badge, color = "Over Budget",  "red"
        elif pct >= thr:    badge, color = "Near Limit",   "yellow"
        else:               badge, color = "On Track",     "green"

        start, end = obj.get_period_dates()
        raw_period = obj.get_period_display()
        period_str = raw_period.split(" ", 1)[-1] if raw_period[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else raw_period
        return {
            "title":       obj.name,
            "subtitle":    f"{period_str} · {fmt_date(start)} – {fmt_date(end)}",
            "badge":       badge,
            "badge_color": color,
            "id_label":    f"BDG-{obj.pk:04d}",
        }

    def stats(self, obj, user):
        from decimal import Decimal
        spending  = obj.get_current_spending()
        remaining = obj.get_remaining()
        pct       = float(obj.get_percentage_used())
        currency  = obj.currency or "UGX"
        pct_color = "red" if pct >= 100 else "yellow" if pct >= float(obj.alert_threshold) else "green"
        return [
            {"label": "Budget",    "value": fmt_ugx(obj.amount, currency),  "color": "blue"},
            {"label": "Spent",     "value": fmt_ugx(spending, currency),    "color": pct_color},
            {"label": "Remaining", "value": fmt_ugx(remaining, currency),   "color": "green" if remaining >= 0 else "red"},
            {"label": "Used",      "value": f"{pct:.1f}%",                  "color": pct_color},
        ]

    def sections(self, obj, user):
        from expenses.models import Expense
        start, end = obj.get_period_dates()

        # Same filter logic as Budget.get_current_spending()
        expenses_qs = Expense.objects.filter(
            user=obj.user, date__gte=start, date__lte=end
        )
        if obj.currency:
            expenses_qs = expenses_qs.filter(currency=obj.currency)
        if obj.tags.exists():
            tag_names = list(obj.tags.names())
            expenses_qs = expenses_qs.filter(tags__name__in=tag_names).distinct()

        expense_rows = []
        for exp in expenses_qs.order_by("-date")[:20]:
            raw_status = exp.get_status_display()
            status_str = raw_status.split(" ", 1)[-1] if raw_status[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else raw_status
            expense_rows.append([
                fmt_date(exp.date),
                exp.description[:40],
                exp.vendor or "—",
                fmt_ugx(exp.amount, exp.currency),
                status_str,
            ])

        raw_period = obj.get_period_display()
        period_str = raw_period.split(" ", 1)[-1] if raw_period[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else raw_period

        pairs = [
            {"label": "Period",          "value": period_str},
            {"label": "Alert Threshold", "value": f"{obj.alert_threshold}%"},
            {"label": "Currency Scope",  "value": obj.currency or "All currencies"},
            {"label": "Status",          "value": "Active" if obj.is_active else "Inactive"},
        ]

        return [
            {"id": "summary",  "title": "Budget Summary", "type": "keyvalue", "pairs": pairs},
            {
                "id": "expenses",
                "title": f"Expenses ({fmt_date(start)} – {fmt_date(end)})",
                "type": "table",
                "columns": ["Date", "Description", "Vendor", "Amount", "Status"],
                "rows": expense_rows,
            },
        ]


# ─── USER TRACKER ─────────────────────────────────────────────────────────────
#
# Model:   accounts.CustomUser
# Fields:  display_role / login_count / last_activity_at / two_factor_enabled
#          is_locked / is_active / company (FK)
# Related: LoginHistory (user FK) / RoleHistory (affected_user FK)
# LoginHistory fields: status / ip_address / browser / location
#                      timestamp / failure_reason
# RoleHistory fields:  role (FK→group) / action / affected_user / user
#                      timestamp / notes

class UserTracker(BaseTracker):

    def get_object(self, pk, user):
        from accounts.models import CustomUser
        try:
            subject = CustomUser.objects.select_related(
                "company", "primary_role__group"
            ).get(pk=pk, company=user.company)
            if user.pk != subject.pk and not user.can_manage_user(subject):
                return None
            return subject
        except Exception:
            return None

    def meta(self, obj, user):
        if getattr(obj, "is_locked", False):
            badge, color = "Locked",   "red"
        elif obj.is_active:
            badge, color = "Active",   "green"
        else:
            badge, color = "Inactive", "dim"
        return {
            "title":       obj.get_full_name() or obj.email,
            "subtitle":    f"{obj.display_role} · {obj.company.name}",
            "badge":       badge,
            "badge_color": color,
            "id_label":    f"usr_{obj.pk:05d}",
        }

    def stats(self, obj, user):
        last_active = (
            obj.last_activity_at.strftime("%d %b, %H:%M")
            if getattr(obj, "last_activity_at", None)
            else "Never"
        )
        return [
            {"label": "Role",         "value": obj.display_role,                                      "color": "blue"},
            {"label": "Total Logins", "value": str(getattr(obj, "login_count", 0)),                   "color": "dim"},
            {"label": "Last Active",  "value": last_active,                                           "color": "green"},
            {"label": "2FA",          "value": "Enabled" if obj.two_factor_enabled else "Disabled",   "color": "purple" if obj.two_factor_enabled else "red"},
        ]

    def sections(self, obj, user):
        from accounts.models import LoginHistory, RoleHistory, AuditLog

        logins = LoginHistory.objects.filter(user=obj).order_by("-timestamp")[:15]
        login_items = [{
            "id":    ln.pk,
            "label": f"Login {ln.get_status_display()}",
            "sub":   ln.ip_address or "",
            "tag":   "login_success" if ln.status == "success" else "login_failed",
            "note":  (
                f"{ln.browser or 'Browser'} · {ln.location or 'Unknown location'}"
                + (f" · ❌ {ln.failure_reason}" if getattr(ln, "failure_reason", None) else "")
            ),
            "user":  obj.get_full_name(),
            "date":  fmt_dt(ln.timestamp),
        } for ln in reversed(list(logins))]

        role_items = [{
            "id":          rh.pk,
            "description": rh.notes or f"Role '{rh.role.group.name}' {rh.get_action_display()}",
            "user":        rh.user.get_full_name() if rh.user else "System",
            "date":        fmt_dt(rh.timestamp),
            "severity":    "success" if rh.action == "assigned" else "warning" if rh.action == "removed" else "info",
        } for rh in RoleHistory.objects.filter(affected_user=obj).order_by("-timestamp")[:10]]

        audit_items = build_audit_items(get_audit_qs(obj))

        # ── Sharing / security events ──────────────────────────────────────────
        security_items = []
        try:
            security_qs = AuditLog.objects.filter(
                user=obj,
                action__in=[
                    'suspicious_activity',
                    'session_superseded',
                    'token_superseded',
                    'account_locked',
                    'account_unlocked',
                ]
            ).order_by("-timestamp")[:20]

            for log in security_qs:
                metadata = log.metadata or {}
                score = metadata.get("total_score")
                detectors = metadata.get("detectors", {})

                # Build a readable note from evidence
                notes = []
                for reason, evidence in detectors.items():
                    label = reason.replace("_", " ").title()
                    if "distance_km" in evidence:
                        notes.append(
                            f"{label}: {evidence['distance_km']} km in "
                            f"{evidence.get('elapsed_hours', '?')} hrs"
                        )
                    elif "distinct_fingerprints" in evidence:
                        notes.append(
                            f"{label}: {evidence['distinct_fingerprints']} devices "
                            f"in {evidence.get('window_hours', '?')} hrs"
                        )
                    elif "other_active_ips" in evidence:
                        other = ", ".join(evidence["other_active_ips"])
                        notes.append(f"{label}: simultaneous IPs — {other}")
                    else:
                        notes.append(label)

                note_str = " · ".join(notes) if notes else (log.action_description or "")
                if score is not None:
                    note_str = f"Score: {score}/100 · " + note_str

                severity = "error" if log.action in ("suspicious_activity", "account_locked") else "warning"

                security_items.append({
                    "id":          log.pk,
                    "description": log.action_description or log.action.replace("_", " ").title(),
                    "user":        log.user.get_full_name() if log.user else "System",
                    "date":        fmt_dt(log.timestamp),
                    "severity":    severity,
                    "diff":        {"from": log.ip_address or "—", "to": note_str} if note_str else None,
                })
        except Exception as e:
            logger.warning(f"[UserTracker] Failed to load security events: {e}")

        # ── Current lock status ────────────────────────────────────────────────
        security_pairs = [
            {"label": "Account Status",  "value": "🔒 Locked" if getattr(obj, "is_locked", False) else "✅ Active"},
            {"label": "Failed Logins",   "value": str(getattr(obj, "failed_login_attempts", 0))},
            {"label": "2FA",             "value": "Enabled" if obj.two_factor_enabled else "Disabled"},
            {"label": "Total Sessions",  "value": str(getattr(obj, "login_count", 0))},
        ]
        if getattr(obj, "locked_until", None):
            security_pairs.append({
                "label": "Locked Until",
                "value": obj.locked_until.strftime("%d %b %Y, %H:%M UTC"),
            })
        # Surface last known sharing lock reason from metadata if present
        sharing_lock = (obj.metadata or {}).get("sharing_lock")
        if sharing_lock:
            security_pairs.append({
                "label": "Lock Reason",
                "value": ", ".join(sharing_lock.get("reasons", [])) or "Sharing detected",
            })
            security_pairs.append({
                "label": "Lock Score",
                "value": f"{sharing_lock.get('score', '—')}/100",
            })

        sections = [
            {"id": "logins",  "title": "Login History",   "type": "timeline", "items": login_items},
            {"id": "roles",   "title": "Role Changes",    "type": "audit",    "items": role_items},
        ]

        if security_items or getattr(obj, "is_locked", False):
            sections.append({
                "id":    "security_status",
                "title": "Security Status",
                "type":  "keyvalue",
                "pairs": security_pairs,
            })
            sections.append({
                "id":    "security_events",
                "title": "Security Events",
                "type":  "audit",
                "items": security_items,
            })

        sections.append({"id": "profile", "title": "Account Changes", "type": "audit", "items": audit_items})
        return sections


# ─────────────────────────────────────────────────────────────────────────────
#  REGISTRY — add a new tracker by adding one line here only
# ─────────────────────────────────────────────────────────────────────────────

REGISTRY = {
    "product":  ProductTracker(),
    "sale":     SaleTracker(),
    "expense":  ExpenseTracker(),
    "customer": CustomerTracker(),
    "user":     UserTracker(),
    "budget":   BudgetTracker(),

    # Uncomment / add as you build them:
    # "transfer":       TransferTracker(),
    # "purchase_order": PurchaseOrderTracker(),
    # "stock_take":     StockTakeTracker(),
    # "supplier":       SupplierTracker(),
}


# ─── VIEW ─────────────────────────────────────────────────────────────────────

class TrackingAPIView(LoginRequiredMixin, View):
    """
    GET /api/track/?type=product&id=6
    Returns JSON payload that tracker.js renders in the slide-out drawer.
    """

    def get(self, request):
        rtype = request.GET.get("type", "").strip().lower()
        rid   = request.GET.get("id",   "").strip()

        if not rtype or not rid:
            return JsonResponse(
                {"error": "Both 'type' and 'id' parameters are required."},
                status=400,
            )

        tracker = REGISTRY.get(rtype)
        if not tracker:
            return JsonResponse(
                {"error": f"Unknown type '{rtype}'. Supported: {', '.join(REGISTRY)}"},
                status=400,
            )

        try:
            data = tracker.build(rid, request.user)
        except Exception:
            logger.exception("Tracker error  type=%s  id=%s", rtype, rid)
            return JsonResponse(
                {"error": "Internal error building tracking data."},
                status=500,
            )

        if data is None:
            return JsonResponse(
                {"error": f"{rtype.title()} #{rid} not found or you do not have access."},
                status=404,
            )

        return JsonResponse(data)