"""
PrimeBooks — General Tracker API
=================================
Powers the tracker_report.html dashboard.

This file is SEPARATE from tracking_api.py.
tracking_api.py  → single-object drill-down  (GET /api/track/?type=x&id=pk)
general_tracker.py → date-range reports       (GET /api/report/?type=x&from=…&to=…)

Wire up (urls.py):
    from accounts.general_tracker import GeneralTrackerView
    path("api/report/", GeneralTrackerView.as_view(), name="general-report"),

Query parameters
----------------
    type        required  sale | product | customer | expense | budget | user
    date_from   required  YYYY-MM-DD
    date_to     required  YYYY-MM-DD
    store_id    optional  filter to a specific store
    sections    optional  comma-separated section ids to include (omit = all)

Response shape (mirrors what tracker_report.html expects)
---------------------------------------------------------
{
  "title":       str,
  "badge":       str,
  "badge_color": str,
  "date_from":   str,
  "date_to":     str,
  "stats":  [ {label, value, color}, … ],
  "charts": [
      {
        "id":     str,
        "title":  str,
        "type":   "bar3d" | "pie" | "line" | "doughnut" | "radar",
        "labels": [str, …],
        "data": [
            {"label": str, "data": [num, …], "color": str}   ← single series
          or
            {"label": str, "data": [num, …], "colors": [str,…]} ← multi-colour
        ]
      }, …
  ],
  "sections": [
      {
        "id":      str,
        "title":   str,
        "type":    "table" | "timeline" | "keyvalue" | "lineitems" | "audit",
        "columns": [str, …],          ← table / lineitems only
        "rows":    [[…], …],          ← table / lineitems only
        "pairs":   [{label,value},…], ← keyvalue only
        "items":   [{…}, …],          ← timeline / audit only
      }, …
  ]
}
"""

import logging
from datetime import timedelta, date
from collections import defaultdict

from django.db.models import Sum, Count, Avg, Q, F
from django.utils import timezone
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
#  SHARED FORMATTING HELPERS
#  (duplicated from tracking_api.py intentionally — keeps files independent)
# ═══════════════════════════════════════════════════════════════════════════════

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

def fmt_date(d):
    return d.strftime("%d %b %Y") if d else "—"

def fmt_datetime(dt):
    return dt.strftime("%d %b %Y, %H:%M") if dt else "—"

def fmt_dt(dt):
    return dt.isoformat() if dt else None


# ═══════════════════════════════════════════════════════════════════════════════
#  DATE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def parse_date(s):
    """Parse YYYY-MM-DD → date, or return None."""
    if not s:
        return None
    try:
        from datetime import date as _date
        y, m, d = s.split("-")
        return _date(int(y), int(m), int(d))
    except Exception:
        return None

def date_series(date_from, date_to, max_points=14):
    """
    Return a list of ISO date strings evenly spaced between date_from and date_to.
    Used as chart X-axis labels.
    """
    delta = (date_to - date_from).days
    if delta <= 0:
        return [date_from.isoformat()]
    step = max(1, delta // (max_points - 1))
    points = []
    current = date_from
    while current <= date_to:
        points.append(current.isoformat())
        current += timedelta(days=step)
    if points[-1] != date_to.isoformat():
        points.append(date_to.isoformat())
    return points[:max_points]

def bucket_by_date(qs, date_field, value_field, date_from, date_to, max_points=14):
    """
    Aggregate queryset into time-series buckets.
    Returns (labels: [str], values: [float]) aligned to date_series().

    Uses .values() so it never iterates model instances — avoids the Django
    FieldError that occurs when select_related() and .only() are both present.
    """
    labels     = date_series(date_from, date_to, max_points)
    buckets    = defaultdict(float)
    delta_days = (date_to - date_from).days
    step       = max(1, delta_days // max(1, max_points - 1))

    for row in qs.values(date_field, value_field):
        raw = row.get(date_field)
        if raw is None:
            continue
        d = raw.date() if hasattr(raw, "date") else raw
        offset = (d - date_from).days
        if offset < 0:
            continue
        idx = min(offset // step, len(labels) - 1)
        val = row.get(value_field)
        try:
            buckets[labels[idx]] += float(val or 0)
        except Exception:
            buckets[labels[idx]] += 1

    return labels, [round(buckets.get(l, 0), 2) for l in labels]


# ═══════════════════════════════════════════════════════════════════════════════
#  AUDIT HELPERS  (same logic as tracking_api.py — no import dependency)
# ═══════════════════════════════════════════════════════════════════════════════

def _action_severity(action):
    errors   = {"login_failed","account_locked","suspicious_activity","sale_voided",
                "product_deleted","efris_failed","expense_rejected","user_deactivated"}
    warnings = {"stock_adjusted","password_changed","account_unlocked","permission_changed"}
    successes= {"login_success","sale_completed","invoice_paid","efris_fiscalized",
                "expense_approved","expense_paid","user_activated","2fa_enabled",
                "sale_created","product_created","user_created","stock_added"}
    if action in errors:    return "error"
    if action in warnings:  return "warning"
    if action in successes: return "success"
    return "info"

def _build_audit_items(audit_qs, limit=30):
    items = []
    for log in audit_qs.order_by("-timestamp")[:limit]:
        diff    = None
        changes = log.changes or {}
        before  = changes.get("before", {})
        after   = changes.get("after",  {})
        if before and after:
            for key in before:
                if key in after and before[key] != after[key]:
                    bv, av = before[key], after[key]
                    if any(x in str(key) for x in ("price","amount","cost","total","rate")):
                        bv, av = fmt_ugx(bv), fmt_ugx(av)
                    diff = {"from": str(bv), "to": str(av)}
                    break
        items.append({
            "id":          log.pk,
            "description": log.action_description,
            "user":        log.user.get_full_name() if log.user else "System",
            "date":        fmt_dt(log.timestamp),
            "severity":    _action_severity(log.action),
            "diff":        diff,
        })
    return items


# ═══════════════════════════════════════════════════════════════════════════════
#  BASE REPORT BUILDER
# ═══════════════════════════════════════════════════════════════════════════════

class BaseReportBuilder:
    """
    Subclass this for each model type.

    build(user, date_from, date_to, store_id, sections) → dict
        title, badge, badge_color, date_from, date_to, stats, charts, sections
    """

    TYPE_LABEL   = "report"
    SECTION_KEYS = []   # ordered list of section IDs this builder can produce

    def build(self, user, date_from, date_to, store_id=None, section_filter=None):
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════════════════════
#  SALE REPORT
# ═══════════════════════════════════════════════════════════════════════════════

class SaleReportBuilder(BaseReportBuilder):
    """
    Models used:
        sales.Sale          — document_number, document_type, status, total_amount,
                              customer(FK), store(FK), created_by(FK),
                              payment_method, is_fiscalized, created_at
        sales.SaleItem      — sale(FK), product(FK), quantity, unit_price, total_price
        sales.Payment       — sale(FK), amount, payment_method, is_voided, created_at
    """
    TYPE_LABEL   = "Sales"
    SECTION_KEYS = ["summary","top_products","top_customers","payments","recent_sales","audit"]

    def build(self, user, date_from, date_to, store_id=None, section_filter=None):
        from sales.models import Sale, SaleItem

        accessible = user.get_accessible_stores()
        base_qs    = Sale.objects.filter(
            store__in   = accessible,
            created_at__date__gte = date_from,
            created_at__date__lte = date_to,
        ).select_related("customer", "store", "created_by")

        if store_id:
            base_qs = base_qs.filter(store_id=store_id)

        # ── Aggregates ────────────────────────────────────────────────────────
        agg = base_qs.aggregate(
            total_revenue = Sum("total_amount"),
            total_count   = Count("id"),
            avg_value     = Avg("total_amount"),
        )
        total_revenue = float(agg["total_revenue"] or 0)
        total_count   = int(agg["total_count"]   or 0)
        avg_value     = float(agg["avg_value"]   or 0)
        efris_count   = base_qs.filter(is_fiscalized=True).count()
        efris_pct     = round(efris_count / total_count * 100, 1) if total_count else 0

        # ── Stats cards ───────────────────────────────────────────────────────
        stats = [
            {"label": "Total Revenue",   "value": fmt_ugx(total_revenue), "color": "green"},
            {"label": "Transactions",    "value": str(total_count),        "color": "blue"},
            {"label": "Avg Sale Value",  "value": fmt_ugx(avg_value),      "color": "dim"},
            {"label": "EFRIS Filed",     "value": f"{efris_pct}%",         "color": "purple"},
        ]

        # ── Charts ────────────────────────────────────────────────────────────
        # 1. Revenue time-series (line)
        ts_labels, ts_values = bucket_by_date(
            base_qs,
            "created_at", "total_amount", date_from, date_to
        )

        # 2. Sales by payment method (pie)
        pmt_agg = (
            base_qs.values("payment_method")
            .annotate(total=Sum("total_amount"), cnt=Count("id"))
            .order_by("-total")[:8]
        )
        pmt_labels = [x["payment_method"] or "Unknown" for x in pmt_agg]
        pmt_values = [float(x["total"] or 0) for x in pmt_agg]

        # 3. Revenue by store (bar3d)
        store_agg = (
            base_qs.values("store__name")
            .annotate(total=Sum("total_amount"))
            .order_by("-total")[:8]
        )
        store_labels = [x["store__name"] or "—" for x in store_agg]
        store_values = [float(x["total"] or 0) for x in store_agg]

        # 4. Document type split (doughnut)
        dtype_agg = (
            base_qs.values("document_type")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")
        )
        dtype_labels = [x["document_type"] or "SALE" for x in dtype_agg]
        dtype_values = [int(x["cnt"]) for x in dtype_agg]

        charts = [
            {
                "id": "sale_revenue_ts", "title": "Revenue Over Time", "type": "line",
                "labels": ts_labels,
                "data": [{"label": "Revenue (UGX)", "data": ts_values, "color": "#c94f2a"}],
            },
            {
                "id": "sale_by_payment", "title": "Sales by Payment Method", "type": "pie",
                "labels": pmt_labels,
                "data": [{"label": "Revenue", "data": pmt_values,
                          "colors": ["#c94f2a","#2a7a6f","#d4943a","#5e4ba3","#2563c4","#3a4a5c","#c97c1a","#b83276"]}],
            },
            {
                "id": "sale_by_store", "title": "Revenue by Store (3D Bar)", "type": "bar3d",
                "labels": store_labels,
                "data": [{"label": "Revenue", "data": store_values, "color": "#2a7a6f"}],
            },
            {
                "id": "sale_by_doctype", "title": "Document Type Split", "type": "doughnut",
                "labels": dtype_labels,
                "data": [{"label": "Count", "data": dtype_values,
                          "colors": ["#c94f2a","#2a7a6f","#d4943a","#5e4ba3","#2563c4"]}],
            },
        ]

        # ── Sections ──────────────────────────────────────────────────────────
        sf = set(section_filter) if section_filter else set(self.SECTION_KEYS)
        sections = []

        # summary keyvalue
        if "summary" in sf:
            voided   = base_qs.filter(status="voided").count()
            completed= base_qs.filter(status="completed").count()
            sections.append({
                "id": "summary", "title": "Sales Summary", "type": "keyvalue",
                "pairs": [
                    {"label": "Period",        "value": f"{fmt_date(date_from)} – {fmt_date(date_to)}"},
                    {"label": "Total Revenue", "value": fmt_ugx(total_revenue)},
                    {"label": "Completed",     "value": str(completed)},
                    {"label": "Voided",        "value": str(voided)},
                    {"label": "EFRIS Filed",   "value": f"{efris_count} / {total_count}"},
                    {"label": "Avg Value",     "value": fmt_ugx(avg_value)},
                ],
            })

        # top products table
        if "top_products" in sf:
            top_items = (
                SaleItem.objects.filter(sale__in=base_qs)
                .values("product__name", "product__sku")
                .annotate(
                    qty_sold  = Sum("quantity"),
                    revenue   = Sum("total_price"),
                    sale_count= Count("sale", distinct=True),
                )
                .order_by("-revenue")[:15]
            )
            rows = [
                [
                    r["product__name"] or "—",
                    r["product__sku"]  or "—",
                    fmt_qty(r["qty_sold"]),
                    str(r["sale_count"]),
                    fmt_ugx(r["revenue"]),
                ]
                for r in top_items
            ]
            sections.append({
                "id": "top_products", "title": "Top Products by Revenue",
                "type": "table",
                "columns": ["Product", "SKU", "Qty Sold", "# Sales", "Revenue"],
                "rows": rows,
            })

        # top customers table
        if "top_customers" in sf:
            top_custs = (
                base_qs.filter(customer__isnull=False)
                .values("customer__name", "customer__customer_id")
                .annotate(
                    total = Sum("total_amount"),
                    cnt   = Count("id"),
                )
                .order_by("-total")[:10]
            )
            rows = [
                [
                    r["customer__name"] or "—",
                    str(r["customer__customer_id"] or "—")[:10].upper(),
                    str(r["cnt"]),
                    fmt_ugx(r["total"]),
                ]
                for r in top_custs
            ]
            rows.append(["Walk-in / No Customer", "—",
                         str(base_qs.filter(customer__isnull=True).count()),
                         fmt_ugx(base_qs.filter(customer__isnull=True).aggregate(t=Sum("total_amount"))["t"] or 0)])
            sections.append({
                "id": "top_customers", "title": "Top Customers",
                "type": "table",
                "columns": ["Customer", "ID", "# Sales", "Revenue"],
                "rows": rows,
            })

        # payments summary table
        if "payments" in sf:
            try:
                from sales.models import Payment
                pmt_rows_qs = (
                    Payment.objects.filter(sale__in=base_qs, is_voided=False)
                    .values("payment_method")
                    .annotate(total=Sum("amount"), cnt=Count("id"))
                    .order_by("-total")
                )
                pmt_rows = [
                    [r["payment_method"] or "Unknown", str(r["cnt"]), fmt_ugx(r["total"])]
                    for r in pmt_rows_qs
                ]
                sections.append({
                    "id": "payments", "title": "Payments by Method",
                    "type": "table",
                    "columns": ["Payment Method", "# Payments", "Total Amount"],
                    "rows": pmt_rows,
                })
            except Exception:
                pass

        # recent sales timeline
        if "recent_sales" in sf:
            recent = base_qs.order_by("-created_at")[:20]
            items  = []
            for s in recent:
                tag = "sale_voided" if s.status == "voided" else \
                      "efris"        if s.is_fiscalized      else \
                      "sale_completed" if s.status == "completed" else "sale_created"
                items.append({
                    "id":    s.pk,
                    "label": s.document_number or f"Sale #{s.pk}",
                    "sub":   s.store.name if s.store else "—",
                    "tag":   tag,
                    "note":  f"{s.customer.name if s.customer else 'Walk-in'} · "
                             f"{s.get_payment_method_display() if hasattr(s,'get_payment_method_display') else (s.payment_method or '—')}",
                    "user":  s.created_by.get_full_name() if s.created_by else "System",
                    "qty":   fmt_ugx(s.total_amount),
                    "date":  fmt_dt(s.created_at),
                })
            sections.append({
                "id": "recent_sales", "title": "Recent Sales", "type": "timeline",
                "items": items,
            })

        # audit log
        if "audit" in sf:
            try:
                from accounts.models import AuditLog
                audit_qs = AuditLog.objects.filter(
                    timestamp__date__gte = date_from,
                    timestamp__date__lte = date_to,
                    user__company        = user.company,
                    action__in           = [
                        "sale_created","sale_completed","sale_voided",
                        "invoice_paid","efris_fiscalized",
                    ],
                )
                audit_items = _build_audit_items(audit_qs, limit=25)
                if audit_items:
                    sections.append({
                        "id": "audit", "title": "Sales Audit Log",
                        "type": "audit", "items": audit_items,
                    })
            except Exception:
                pass

        return {
            "title":       "Sales Report",
            "badge":       "active",
            "badge_color": "green",
            "date_from":   date_from.isoformat(),
            "date_to":     date_to.isoformat(),
            "stats":       stats,
            "charts":      charts,
            "sections":    sections,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  PRODUCT REPORT
# ═══════════════════════════════════════════════════════════════════════════════

class ProductReportBuilder(BaseReportBuilder):
    """
    Models used:
        inventory.Product       — name, sku, category(FK), supplier(FK),
                                  selling_price, cost_price, min_stock_level,
                                  efris_is_uploaded
        inventory.Stock         — product(FK), store(FK), quantity, low_stock_threshold
        inventory.StockMovement — product(FK), store(FK), movement_type, quantity,
                                  unit_price, total_value, created_by, created_at, notes
    """
    TYPE_LABEL   = "Products"
    SECTION_KEYS = ["summary","inventory","low_stock","movements","stock_by_category","audit"]

    def build(self, user, date_from, date_to, store_id=None, section_filter=None):
        from inventory.models import Product, Stock, StockMovement

        accessible = user.get_accessible_stores()
        sf = set(section_filter) if section_filter else set(self.SECTION_KEYS)

        # all active products visible to user
        prod_qs = Product.objects.select_related("category", "supplier").filter(
            store_inventory__store__in=accessible
        ).distinct()

        # stock movements in the date window
        mov_qs = StockMovement.objects.filter(
            store__in         = accessible,
            created_at__date__gte = date_from,
            created_at__date__lte = date_to,
        ).select_related("product", "store", "created_by")

        if store_id:
            prod_qs = prod_qs.filter(store_inventory__store_id=store_id)
            mov_qs  = mov_qs.filter(store_id=store_id)

        # ── Aggregates ────────────────────────────────────────────────────────
        stock_qs   = Stock.objects.filter(store__in=accessible)
        if store_id:
            stock_qs = stock_qs.filter(store_id=store_id)

        total_products  = prod_qs.count()
        stock_value_agg = stock_qs.aggregate(
            val=Sum(F("quantity") * F("product__selling_price"))
        )
        total_stock_value = float(stock_value_agg["val"] or 0)
        low_stock_count   = stock_qs.filter(quantity__lte=F("low_stock_threshold")).count()
        efris_pct = (
            prod_qs.filter(efris_is_uploaded=True).count() / total_products * 100
            if total_products else 0
        )

        stats = [
            {"label": "Products",         "value": str(total_products),          "color": "blue"},
            {"label": "Total Stock Value", "value": fmt_ugx(total_stock_value),   "color": "green"},
            {"label": "Low Stock Items",   "value": str(low_stock_count),         "color": "yellow"},
            {"label": "EFRIS Registered",  "value": f"{efris_pct:.1f}%",          "color": "purple"},
        ]

        # ── Charts ────────────────────────────────────────────────────────────
        # 1. Movements in / out over time (line, dual series)
        DECREASE = {"SALE","TRANSFER_OUT","VOID","REFUND"}
        mov_in  = mov_qs.exclude(movement_type__in=DECREASE)
        mov_out = mov_qs.filter(movement_type__in=DECREASE)

        ts_labels,  in_vals  = bucket_by_date(mov_in,  "created_at","quantity", date_from, date_to)
        _,           out_vals = bucket_by_date(mov_out, "created_at","quantity", date_from, date_to, max_points=len(ts_labels))

        # 2. Stock qty by category (bar3d)
        cat_agg = (
            stock_qs.values("product__category__name")
            .annotate(total_qty=Sum("quantity"), total_val=Sum(F("quantity")*F("product__selling_price")))
            .order_by("-total_val")[:8]
        )
        cat_labels = [x["product__category__name"] or "Uncategorised" for x in cat_agg]
        cat_qty    = [float(x["total_qty"] or 0) for x in cat_agg]
        cat_val    = [float(x["total_val"] or 0) for x in cat_agg]

        # 3. Movement type split (pie)
        mtype_agg = (
            mov_qs.values("movement_type")
            .annotate(cnt=Count("id"), qty=Sum("quantity"))
            .order_by("-cnt")
        )
        mtype_labels = [x["movement_type"] for x in mtype_agg]
        mtype_values = [int(x["cnt"]) for x in mtype_agg]

        # 4. Top movers by qty sold (doughnut)
        top_movers = (
            mov_qs.filter(movement_type="SALE")
            .values("product__name")
            .annotate(qty=Sum("quantity"))
            .order_by("-qty")[:8]
        )
        mover_labels = [x["product__name"] or "—" for x in top_movers]
        mover_values = [float(x["qty"] or 0) for x in top_movers]

        charts = [
            {
                "id": "prod_movements_ts", "title": "Stock Movements Over Time", "type": "line",
                "labels": ts_labels,
                "data": [
                    {"label": "Stock In",  "data": in_vals,  "color": "#2a7a6f"},
                    {"label": "Stock Out", "data": out_vals, "color": "#c94f2a"},
                ],
            },
            {
                "id": "prod_by_category", "title": "Stock Value by Category (3D Bar)", "type": "bar3d",
                "labels": cat_labels,
                "data": [
                    {"label": "Value (UGX)", "data": cat_val, "color": "#2a7a6f"},
                    {"label": "Qty",         "data": cat_qty, "color": "#d4943a"},
                ],
            },
            {
                "id": "prod_movement_types", "title": "Movement Type Breakdown", "type": "pie",
                "labels": mtype_labels,
                "data": [{"label": "Count", "data": mtype_values,
                          "colors": ["#c94f2a","#2a7a6f","#d4943a","#5e4ba3","#2563c4","#3a4a5c"]}],
            },
            {
                "id": "prod_top_movers", "title": "Top Products by Qty Sold", "type": "doughnut",
                "labels": mover_labels,
                "data": [{"label": "Qty Sold", "data": mover_values,
                          "colors": ["#c94f2a","#2a7a6f","#d4943a","#5e4ba3","#2563c4","#3a4a5c","#c97c1a","#b83276"]}],
            },
        ]

        # ── Sections ──────────────────────────────────────────────────────────
        sections = []

        if "summary" in sf:
            total_moves = mov_qs.count()
            purchase_val = float(
                mov_qs.filter(movement_type="PURCHASE")
                .aggregate(v=Sum("total_value"))["v"] or 0
            )
            sections.append({
                "id": "summary", "title": "Inventory Summary", "type": "keyvalue",
                "pairs": [
                    {"label": "Period",            "value": f"{fmt_date(date_from)} – {fmt_date(date_to)}"},
                    {"label": "Total Products",    "value": str(total_products)},
                    {"label": "Stock Value",       "value": fmt_ugx(total_stock_value)},
                    {"label": "Low Stock Items",   "value": str(low_stock_count)},
                    {"label": "EFRIS Registered",  "value": f"{efris_pct:.1f}%"},
                    {"label": "Movements (period)","value": str(total_moves)},
                    {"label": "Purchases Value",   "value": fmt_ugx(purchase_val)},
                ],
            })

        if "inventory" in sf:
            rows = []
            for p in prod_qs.order_by("name")[:50]:
                total_qty = sum(
                    float(s.quantity)
                    for s in p.store_inventory.filter(store__in=accessible)
                )
                rows.append([
                    p.name,
                    p.sku or "—",
                    p.category.name if p.category else "—",
                    fmt_qty(total_qty, ""),
                    fmt_ugx(p.selling_price),
                    fmt_ugx(float(p.selling_price or 0) * total_qty),
                    "✅" if p.efris_is_uploaded else "⏳",
                ])
            sections.append({
                "id": "inventory", "title": "Product Inventory",
                "type": "table",
                "columns": ["Product","SKU","Category","In Stock","Sell Price","Stock Value","EFRIS"],
                "rows": rows,
            })

        if "low_stock" in sf:
            low_stocks = stock_qs.filter(
                quantity__lte=F("low_stock_threshold")
            ).select_related("product","store").order_by("quantity")[:30]
            rows = [
                [
                    ls.product.name if ls.product else "—",
                    ls.store.name   if ls.store   else "—",
                    fmt_qty(ls.quantity),
                    fmt_qty(ls.low_stock_threshold),
                    fmt_ugx(ls.product.selling_price if ls.product else 0),
                ]
                for ls in low_stocks
            ]
            sections.append({
                "id": "low_stock", "title": f"Low / Out-of-Stock ({len(rows)} items)",
                "type": "table",
                "columns": ["Product","Store","Current Qty","Min Level","Sell Price"],
                "rows": rows,
            })

        if "movements" in sf:
            recent_moves = mov_qs.order_by("-created_at")[:30]
            items = []
            for m in recent_moves:
                q   = float(m.quantity or 0)
                dec = m.movement_type in DECREASE
                items.append({
                    "id":    m.pk,
                    "label": m.get_movement_type_display() if hasattr(m,"get_movement_type_display") else m.movement_type,
                    "sub":   m.reference or "",
                    "tag":   m.movement_type,
                    "qty":   f"{'−' if dec else '+'}{int(q)}",
                    "note":  f"{m.product.name if m.product else '—'} · {m.store.name if m.store else '—'}" + (f" · {m.notes}" if m.notes else ""),
                    "user":  m.created_by.get_full_name() if m.created_by else "System",
                    "date":  fmt_dt(m.created_at),
                })
            sections.append({
                "id": "movements", "title": "Stock Movements (Period)",
                "type": "timeline", "items": items,
            })

        if "stock_by_category" in sf:
            sections.append({
                "id": "stock_by_category", "title": "Stock by Category", "type": "table",
                "columns": ["Category","Products","Total Qty","Stock Value"],
                "rows": [
                    [
                        x["product__category__name"] or "Uncategorised",
                        str(prod_qs.filter(category__name=x["product__category__name"]).count()),
                        fmt_qty(x["total_qty"]),
                        fmt_ugx(x["total_val"]),
                    ]
                    for x in cat_agg
                ],
            })

        if "audit" in sf:
            try:
                from accounts.models import AuditLog
                from django.contrib.contenttypes.models import ContentType
                from inventory.models import Product as _Product
                ct = ContentType.objects.get_for_model(_Product)
                audit_qs = AuditLog.objects.filter(
                    content_type = ct,
                    timestamp__date__gte = date_from,
                    timestamp__date__lte = date_to,
                )
                items = _build_audit_items(audit_qs, limit=20)
                if items:
                    sections.append({"id":"audit","title":"Product Change History","type":"audit","items":items})
            except Exception:
                pass

        return {
            "title":       "Products Report",
            "badge":       "in_stock",
            "badge_color": "green",
            "date_from":   date_from.isoformat(),
            "date_to":     date_to.isoformat(),
            "stats":       stats,
            "charts":      charts,
            "sections":    sections,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  CUSTOMER REPORT
# ═══════════════════════════════════════════════════════════════════════════════

class CustomerReportBuilder(BaseReportBuilder):
    """
    Models used:
        customers.Customer             — name, customer_type, email, phone,
                                         tin, store(FK), credit_limit, credit_balance,
                                         credit_available, allow_credit, credit_status,
                                         is_active, efris_status, created_at
        customers.CustomerCreditStatement — customer(FK), transaction_type, amount,
                                            balance_after, description, created_at
        sales.Sale                     — customer(FK), total_amount, created_at
    """
    TYPE_LABEL   = "Customers"
    SECTION_KEYS = ["summary","customer_list","new_customers","credit_summary","sales_by_customer","audit"]

    def build(self, user, date_from, date_to, store_id=None, section_filter=None):
        from customers.models import Customer

        accessible = user.get_accessible_stores()
        sf = set(section_filter) if section_filter else set(self.SECTION_KEYS)

        cust_qs = Customer.objects.filter(store__in=accessible)
        if store_id:
            cust_qs = cust_qs.filter(store_id=store_id)

        new_in_period = cust_qs.filter(
            created_at__date__gte=date_from,
            created_at__date__lte=date_to,
        )

        # ── Aggregates ────────────────────────────────────────────────────────
        total_customers = cust_qs.count()
        active_count    = cust_qs.filter(is_active=True).count()
        credit_accounts = cust_qs.filter(allow_credit=True).count()
        total_receivable= float(cust_qs.aggregate(t=Sum("credit_balance"))["t"] or 0)
        efris_reg       = cust_qs.filter(efris_status="REGISTERED").count()
        efris_pct       = round(efris_reg / total_customers * 100, 1) if total_customers else 0

        stats = [
            {"label": "Total Customers",  "value": str(total_customers), "color": "blue"},
            {"label": "Active",           "value": str(active_count),    "color": "green"},
            {"label": "Total Receivables","value": fmt_ugx(total_receivable), "color": "red"},
            {"label": "EFRIS Registered", "value": f"{efris_pct}%",      "color": "purple"},
        ]

        # ── Charts ────────────────────────────────────────────────────────────
        # 1. New customers over time (line)
        ts_labels, ts_new = bucket_by_date(
            new_in_period, "created_at", "id", date_from, date_to
        )
        ts_new = [1 for _ in ts_new]   # each record = 1 new customer

        # 2. Customer type split (pie)
        type_agg = (
            cust_qs.values("customer_type")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")
        )
        type_labels = [x["customer_type"] or "Individual" for x in type_agg]
        type_values = [int(x["cnt"]) for x in type_agg]

        # 3. Credit status (doughnut)
        cr_agg = (
            cust_qs.filter(allow_credit=True)
            .values("credit_status")
            .annotate(cnt=Count("id"))
        )
        cr_labels = [x["credit_status"] or "NONE" for x in cr_agg]
        cr_values = [int(x["cnt"]) for x in cr_agg]

        # 4. Top customers by revenue — join via Sale
        try:
            from sales.models import Sale
            top_custs_agg = (
                Sale.objects.filter(
                    store__in=accessible,
                    customer__isnull=False,
                    created_at__date__gte=date_from,
                    created_at__date__lte=date_to,
                )
                .values("customer__name")
                .annotate(revenue=Sum("total_amount"))
                .order_by("-revenue")[:8]
            )
            top_c_labels = [x["customer__name"] or "—" for x in top_custs_agg]
            top_c_values = [float(x["revenue"] or 0) for x in top_custs_agg]
        except Exception:
            top_c_labels, top_c_values = [], []

        charts = [
            {
                "id": "cust_new_ts", "title": "New Customers Over Time", "type": "line",
                "labels": ts_labels,
                "data": [{"label": "New Customers", "data": ts_new, "color": "#2a7a6f"}],
            },
            {
                "id": "cust_types", "title": "Customer Types", "type": "pie",
                "labels": type_labels,
                "data": [{"label":"Count","data":type_values,
                          "colors":["#c94f2a","#2a7a6f","#d4943a","#5e4ba3"]}],
            },
            {
                "id": "cust_credit_status", "title": "Credit Status Split", "type": "doughnut",
                "labels": cr_labels,
                "data": [{"label":"Count","data":cr_values,
                          "colors":["#2a7a6f","#c97c1a","#c94f2a","#b83232"]}],
            },
            {
                "id": "cust_top_revenue", "title": "Top Customers by Revenue (3D Bar)", "type": "bar3d",
                "labels": top_c_labels,
                "data": [{"label":"Revenue","data":top_c_values,"color":"#d4943a"}],
            },
        ]

        # ── Sections ──────────────────────────────────────────────────────────
        sections = []

        if "summary" in sf:
            blocked   = cust_qs.filter(credit_status="BLOCKED").count()
            suspended = cust_qs.filter(credit_status="SUSPENDED").count()
            sections.append({
                "id": "summary", "title": "Customer Summary", "type": "keyvalue",
                "pairs": [
                    {"label": "Period",          "value": f"{fmt_date(date_from)} – {fmt_date(date_to)}"},
                    {"label": "Total Customers", "value": str(total_customers)},
                    {"label": "Active",          "value": str(active_count)},
                    {"label": "New This Period", "value": str(new_in_period.count())},
                    {"label": "Credit Accounts", "value": str(credit_accounts)},
                    {"label": "Total Receivable","value": fmt_ugx(total_receivable)},
                    {"label": "Blocked",         "value": str(blocked)},
                    {"label": "Suspended",       "value": str(suspended)},
                    {"label": "EFRIS Registered","value": f"{efris_reg} ({efris_pct}%)"},
                ],
            })

        if "customer_list" in sf:
            rows = []
            for c in cust_qs.order_by("-created_at")[:50]:
                rows.append([
                    c.name or "—",
                    c.get_customer_type_display() if hasattr(c,"get_customer_type_display") else c.customer_type,
                    c.phone or "—",
                    fmt_ugx(c.credit_balance),
                    fmt_ugx(c.credit_limit),
                    c.get_credit_status_display() if hasattr(c,"get_credit_status_display") else (c.credit_status or "—"),
                    c.get_efris_status_display() if hasattr(c,"get_efris_status_display") else c.efris_status,
                ])
            sections.append({
                "id": "customer_list", "title": "Customer List",
                "type": "table",
                "columns": ["Name","Type","Phone","Credit Balance","Credit Limit","Credit Status","EFRIS"],
                "rows": rows,
            })

        if "new_customers" in sf:
            items = []
            for c in new_in_period.order_by("-created_at")[:20]:
                items.append({
                    "id":    c.pk,
                    "label": c.name or f"Customer #{c.pk}",
                    "sub":   c.store.name if c.store else "—",
                    "tag":   "user_created",
                    "note":  f"{c.phone or ''} · {c.get_customer_type_display() if hasattr(c,'get_customer_type_display') else c.customer_type}",
                    "user":  "System",
                    "date":  fmt_dt(c.created_at),
                })
            sections.append({
                "id": "new_customers", "title": "New Customers This Period",
                "type": "timeline", "items": items,
            })

        if "credit_summary" in sf:
            try:
                from customers.models import CustomerCreditStatement
                stmt_qs = CustomerCreditStatement.objects.filter(
                    customer__store__in=accessible,
                    created_at__date__gte=date_from,
                    created_at__date__lte=date_to,
                ).select_related("customer").order_by("-created_at")[:30]
                rows = [
                    [
                        fmt_datetime(s.created_at),
                        s.customer.name[:30] if s.customer else "—",
                        s.get_transaction_type_display() if hasattr(s,"get_transaction_type_display") else s.transaction_type,
                        (s.description or "—")[:40],
                        fmt_ugx(s.amount, ""),
                        fmt_ugx(s.balance_after, ""),
                    ]
                    for s in stmt_qs
                ]
                sections.append({
                    "id": "credit_summary", "title": "Credit Transactions",
                    "type": "table",
                    "columns": ["Date","Customer","Type","Description","Amount","Balance After"],
                    "rows": rows,
                })
            except Exception:
                pass

        if "sales_by_customer" in sf:
            try:
                from sales.models import Sale
                sale_rows = (
                    Sale.objects.filter(
                        store__in=accessible,
                        customer__isnull=False,
                        created_at__date__gte=date_from,
                        created_at__date__lte=date_to,
                    )
                    .values("customer__name")
                    .annotate(cnt=Count("id"), total=Sum("total_amount"))
                    .order_by("-total")[:20]
                )
                sections.append({
                    "id": "sales_by_customer", "title": "Sales by Customer",
                    "type": "table",
                    "columns": ["Customer","# Sales","Total Revenue"],
                    "rows": [[r["customer__name"] or "—", str(r["cnt"]), fmt_ugx(r["total"])] for r in sale_rows],
                })
            except Exception:
                pass

        if "audit" in sf:
            try:
                from accounts.models import AuditLog
                from customers.models import Customer as _C
                ct = ContentType.objects.get_for_model(_C)
                audit_qs = AuditLog.objects.filter(
                    content_type=ct,
                    timestamp__date__gte=date_from,
                    timestamp__date__lte=date_to,
                )
                items = _build_audit_items(audit_qs, limit=20)
                if items:
                    sections.append({"id":"audit","title":"Customer Change History","type":"audit","items":items})
            except Exception:
                pass

        return {
            "title": "Customers Report", "badge": "active", "badge_color": "green",
            "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "stats": stats, "charts": charts, "sections": sections,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  EXPENSE REPORT
# ═══════════════════════════════════════════════════════════════════════════════

class ExpenseReportBuilder(BaseReportBuilder):
    """
    Models used:
        expenses.Expense         — user(FK), amount, currency, exchange_rate,
                                   amount_base, description, vendor, payment_method,
                                   status, date, is_recurring, tags
        expenses.ExpenseApproval — expense(FK), actor(FK), action, comment,
                                   previous_status, new_status, created_at
    """
    TYPE_LABEL   = "Expenses"
    SECTION_KEYS = ["summary","expense_list","by_vendor","by_category","approvals","audit"]

    def build(self, user, date_from, date_to, store_id=None, section_filter=None):
        from expenses.models import Expense, ExpenseApproval

        sf = set(section_filter) if section_filter else set(self.SECTION_KEYS)

        exp_qs = Expense.objects.filter(
            user__company = user.company,
            date__gte     = date_from,
            date__lte     = date_to,
        ).select_related("user")

        # ── Aggregates ────────────────────────────────────────────────────────
        agg = exp_qs.aggregate(
            total_amount = Sum("amount_base"),
            count        = Count("id"),
            avg_amount   = Avg("amount_base"),
        )
        total   = float(agg["total_amount"] or 0)
        count   = int(agg["count"]   or 0)
        avg_val = float(agg["avg_amount"] or 0)
        pending = exp_qs.filter(status__in=["submitted","under_review"]).count()

        stats = [
            {"label": "Total Expenses",    "value": fmt_ugx(total),    "color": "red"},
            {"label": "# Expenses",        "value": str(count),        "color": "blue"},
            {"label": "Pending Approval",  "value": str(pending),      "color": "yellow"},
            {"label": "Avg Expense",       "value": fmt_ugx(avg_val),  "color": "dim"},
        ]

        # ── Charts ────────────────────────────────────────────────────────────
        # 1. Spending over time (line) — use date field directly
        ts_labels, ts_vals = bucket_by_date(
            exp_qs, "date", "amount_base", date_from, date_to
        )

        # 2. By vendor (bar3d, top 8)
        vend_agg = (
            exp_qs.exclude(vendor__isnull=True).exclude(vendor="")
            .values("vendor")
            .annotate(total=Sum("amount_base"))
            .order_by("-total")[:8]
        )
        vend_labels = [x["vendor"][:20] for x in vend_agg]
        vend_values = [float(x["total"] or 0) for x in vend_agg]

        # 3. By payment method (pie)
        pmt_agg = (
            exp_qs.values("payment_method")
            .annotate(total=Sum("amount_base"))
            .order_by("-total")
        )
        pmt_labels = [x["payment_method"] or "Unknown" for x in pmt_agg]
        pmt_values = [float(x["total"] or 0) for x in pmt_agg]

        # 4. Status distribution (doughnut)
        stat_agg = exp_qs.values("status").annotate(cnt=Count("id")).order_by("-cnt")
        stat_labels = [x["status"] for x in stat_agg]
        stat_values = [int(x["cnt"]) for x in stat_agg]

        charts = [
            {
                "id": "exp_ts", "title": "Spending Over Time", "type": "line",
                "labels": ts_labels,
                "data": [{"label": "Amount (UGX)", "data": ts_vals, "color": "#b83232"}],
            },
            {
                "id": "exp_by_vendor", "title": "Top Vendors by Spend (3D Bar)", "type": "bar3d",
                "labels": vend_labels,
                "data": [{"label": "Spent", "data": vend_values, "color": "#3a4a5c"}],
            },
            {
                "id": "exp_by_payment", "title": "Expenses by Payment Method", "type": "pie",
                "labels": pmt_labels,
                "data": [{"label": "Amount","data": pmt_values,
                          "colors":["#c94f2a","#2a7a6f","#d4943a","#5e4ba3","#2563c4"]}],
            },
            {
                "id": "exp_by_status", "title": "Expense Status Distribution", "type": "doughnut",
                "labels": stat_labels,
                "data": [{"label": "Count","data": stat_values,
                          "colors":["#2a7a6f","#2563c4","#d4943a","#b83232","#c97c1a"]}],
            },
        ]

        # ── Sections ──────────────────────────────────────────────────────────
        sections = []

        if "summary" in sf:
            approved = exp_qs.filter(status="approved").count()
            rejected = exp_qs.filter(status="rejected").count()
            total_approved_val = float(
                exp_qs.filter(status="approved").aggregate(v=Sum("amount_base"))["v"] or 0
            )
            sections.append({
                "id": "summary", "title": "Expense Summary", "type": "keyvalue",
                "pairs": [
                    {"label": "Period",          "value": f"{fmt_date(date_from)} – {fmt_date(date_to)}"},
                    {"label": "Total Spend",     "value": fmt_ugx(total)},
                    {"label": "# Expenses",      "value": str(count)},
                    {"label": "Avg Expense",     "value": fmt_ugx(avg_val)},
                    {"label": "Approved",        "value": f"{approved} · {fmt_ugx(total_approved_val)}"},
                    {"label": "Pending",         "value": str(pending)},
                    {"label": "Rejected",        "value": str(rejected)},
                ],
            })

        if "expense_list" in sf:
            rows = []
            for e in exp_qs.order_by("-date")[:50]:
                raw_pmt = dict(getattr(e,"PAYMENT_METHODS",{})).get(e.payment_method, e.payment_method or "—")
                pmt_str = raw_pmt.split(" ",1)[-1] if raw_pmt and raw_pmt[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" else raw_pmt
                raw_st  = e.get_status_display() if hasattr(e,"get_status_display") else e.status
                st_str  = raw_st.split(" ",1)[-1] if raw_st and raw_st[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" else raw_st
                rows.append([
                    fmt_date(e.date),
                    (e.description or "—")[:40],
                    (e.vendor or "—")[:25],
                    fmt_ugx(e.amount, e.currency),
                    pmt_str,
                    st_str,
                    e.user.get_full_name() if e.user else "—",
                ])
            sections.append({
                "id": "expense_list", "title": "Expense Details",
                "type": "table",
                "columns": ["Date","Description","Vendor","Amount","Payment","Status","Submitted By"],
                "rows": rows,
            })

        if "by_vendor" in sf:
            sections.append({
                "id": "by_vendor", "title": "Spend by Vendor", "type": "table",
                "columns": ["Vendor","# Expenses","Total Spend","Avg Expense"],
                "rows": [
                    [
                        x["vendor"][:30],
                        str(exp_qs.filter(vendor=x["vendor"]).count()),
                        fmt_ugx(x["total"]),
                        fmt_ugx(float(x["total"] or 0) / max(exp_qs.filter(vendor=x["vendor"]).count(),1)),
                    ]
                    for x in vend_agg
                ],
            })

        if "approvals" in sf:
            ap_qs = (
                ExpenseApproval.objects.filter(
                    expense__in  = exp_qs,
                    created_at__date__gte = date_from,
                    created_at__date__lte = date_to,
                )
                .select_related("actor","expense")
                .order_by("-created_at")[:30]
            )
            ACTION_SEV = {
                "approved": "success", "rejected": "error",
                "submitted": "info",   "under_review": "info",
                "resubmit": "warning", "cancelled": "warning",
            }
            items = []
            for ap in ap_qs:
                raw = ap.get_action_display() if hasattr(ap,"get_action_display") else ap.action
                label = raw.split(" ",1)[-1].strip() if raw and raw[0] not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" else raw
                note = ap.comment or ""
                if ap.previous_status and ap.new_status and ap.previous_status != ap.new_status:
                    note = f"Status: {ap.previous_status} → {ap.new_status}" + (f" · {ap.comment}" if ap.comment else "")
                items.append({
                    "id":    ap.pk,
                    "label": label,
                    "sub":   ap.expense.description[:30] if ap.expense else "",
                    "tag":   ACTION_SEV.get(ap.action,"info"),
                    "note":  note,
                    "user":  ap.actor.get_full_name() if ap.actor else "System",
                    "date":  fmt_dt(ap.created_at),
                    "severity": ACTION_SEV.get(ap.action,"info"),
                })
            sections.append({
                "id": "approvals", "title": "Approval History",
                "type": "timeline", "items": items,
            })

        if "audit" in sf:
            try:
                from accounts.models import AuditLog
                from expenses.models import Expense as _E
                ct = ContentType.objects.get_for_model(_E)
                audit_qs = AuditLog.objects.filter(
                    content_type=ct,
                    timestamp__date__gte=date_from,
                    timestamp__date__lte=date_to,
                )
                items = _build_audit_items(audit_qs, limit=20)
                if items:
                    sections.append({"id":"audit","title":"Expense Audit Log","type":"audit","items":items})
            except Exception:
                pass

        return {
            "title": "Expenses Report", "badge": "submitted", "badge_color": "blue",
            "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "stats": stats, "charts": charts, "sections": sections,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  BUDGET REPORT
# ═══════════════════════════════════════════════════════════════════════════════

class BudgetReportBuilder(BaseReportBuilder):
    """
    Models used:
        expenses.Budget   — user(FK), name, amount, period, currency,
                            alert_threshold, is_active, tags
                            Methods: get_period_dates(), get_current_spending(),
                                     get_remaining(), get_percentage_used()
        expenses.Expense  — (scoped through budget's period logic)
    """
    TYPE_LABEL   = "Budgets"
    SECTION_KEYS = ["summary","budget_list","budget_vs_actual","expense_breakdown"]

    def build(self, user, date_from, date_to, store_id=None, section_filter=None):
        from expenses.models import Budget, Expense

        sf = set(section_filter) if section_filter else set(self.SECTION_KEYS)

        budget_qs = Budget.objects.filter(user__company=user.company)
        active_budgets = budget_qs.filter(is_active=True)

        # compute spend for each budget using its own methods
        budget_data = []
        for b in budget_qs:
            try:
                spent     = float(b.get_current_spending() or 0)
                remaining = float(b.get_remaining() or 0)
                pct       = float(b.get_percentage_used() or 0)
                alloc     = float(b.amount or 0)
                start, end = b.get_period_dates()
                currency   = b.currency or "UGX"
                budget_data.append({
                    "obj": b, "spent": spent, "remaining": remaining,
                    "pct": pct, "alloc": alloc, "start": start,
                    "end": end, "currency": currency,
                })
            except Exception:
                pass

        total_allocated = sum(d["alloc"]  for d in budget_data)
        total_spent     = sum(d["spent"]  for d in budget_data)
        over_budget     = sum(1 for d in budget_data if d["pct"] >= 100)
        near_limit      = sum(1 for d in budget_data if float(d["obj"].alert_threshold) <= d["pct"] < 100)

        stats = [
            {"label": "Active Budgets",   "value": str(active_budgets.count()), "color": "blue"},
            {"label": "Total Allocated",  "value": fmt_ugx(total_allocated),    "color": "green"},
            {"label": "Total Spent",      "value": fmt_ugx(total_spent),        "color": "red"},
            {"label": "Over Budget",      "value": str(over_budget),            "color": "yellow"},
        ]

        # ── Charts ────────────────────────────────────────────────────────────
        b_names  = [d["obj"].name[:16] for d in budget_data]
        b_alloc  = [d["alloc"] for d in budget_data]
        b_spent  = [d["spent"] for d in budget_data]
        b_pct    = [round(d["pct"],1) for d in budget_data]

        charts = [
            {
                "id": "bud_vs_actual", "title": "Budget vs Actual Spend (3D Bar)", "type": "bar3d",
                "labels": b_names,
                "data": [
                    {"label": "Allocated", "data": b_alloc, "color": "#2a7a6f"},
                    {"label": "Spent",     "data": b_spent, "color": "#c94f2a"},
                ],
            },
            {
                "id": "bud_pct_used", "title": "% Budget Used per Budget", "type": "bar3d",
                "labels": b_names,
                "data": [{"label": "% Used", "data": b_pct, "color": "#d4943a"}],
            },
            {
                "id": "bud_status", "title": "Budget Health Status", "type": "doughnut",
                "labels": ["On Track", "Near Limit", "Over Budget"],
                "data": [{"label": "Count",
                          "data": [len(budget_data)-over_budget-near_limit, near_limit, over_budget],
                          "colors": ["#2a7a6f","#c97c1a","#b83232"]}],
            },
            {
                "id": "bud_share", "title": "Allocation Share", "type": "pie",
                "labels": b_names,
                "data": [{"label": "Allocated", "data": b_alloc,
                          "colors": ["#c94f2a","#2a7a6f","#d4943a","#5e4ba3","#2563c4","#3a4a5c","#c97c1a","#b83276"]}],
            },
        ]

        # ── Sections ──────────────────────────────────────────────────────────
        sections = []

        if "summary" in sf:
            sections.append({
                "id": "summary", "title": "Budget Summary", "type": "keyvalue",
                "pairs": [
                    {"label": "Period",         "value": f"{fmt_date(date_from)} – {fmt_date(date_to)}"},
                    {"label": "Total Budgets",  "value": str(len(budget_data))},
                    {"label": "Active",         "value": str(active_budgets.count())},
                    {"label": "Total Allocated","value": fmt_ugx(total_allocated)},
                    {"label": "Total Spent",    "value": fmt_ugx(total_spent)},
                    {"label": "Total Remaining","value": fmt_ugx(total_allocated - total_spent)},
                    {"label": "Over Budget",    "value": str(over_budget)},
                    {"label": "Near Limit",     "value": str(near_limit)},
                ],
            })

        if "budget_list" in sf:
            rows = []
            for d in budget_data:
                b = d["obj"]
                color_hint = "🔴" if d["pct"] >= 100 else "🟡" if d["pct"] >= float(b.alert_threshold) else "🟢"
                raw_period = b.get_period_display() if hasattr(b,"get_period_display") else b.period
                rows.append([
                    b.name,
                    raw_period,
                    fmt_ugx(d["alloc"], d["currency"]),
                    fmt_ugx(d["spent"],     d["currency"]),
                    fmt_ugx(d["remaining"], d["currency"]),
                    f"{color_hint} {d['pct']:.1f}%",
                    "Active" if b.is_active else "Inactive",
                ])
            sections.append({
                "id": "budget_list", "title": "Budget Details",
                "type": "table",
                "columns": ["Budget","Period","Allocated","Spent","Remaining","Used %","Status"],
                "rows": rows,
            })

        if "budget_vs_actual" in sf:
            # per-budget keyvalue deep-dives
            for d in budget_data:
                b = d["obj"]
                sections.append({
                    "id": f"bud_detail_{b.pk}", "title": f"Budget: {b.name}", "type": "keyvalue",
                    "pairs": [
                        {"label": "Allocated",       "value": fmt_ugx(d["alloc"], d["currency"])},
                        {"label": "Spent",           "value": fmt_ugx(d["spent"],     d["currency"])},
                        {"label": "Remaining",       "value": fmt_ugx(d["remaining"], d["currency"])},
                        {"label": "Used",            "value": f"{d['pct']:.1f}%"},
                        {"label": "Alert Threshold", "value": f"{b.alert_threshold}%"},
                        {"label": "Period Start",    "value": fmt_date(d["start"])},
                        {"label": "Period End",      "value": fmt_date(d["end"])},
                        {"label": "Currency",        "value": d["currency"]},
                        {"label": "Status",          "value": "Active" if b.is_active else "Inactive"},
                    ],
                })

        if "expense_breakdown" in sf:
            # All expenses that fall under any budget's scope in the date window
            exp_qs = Expense.objects.filter(
                user__company        = user.company,
                date__gte            = date_from,
                date__lte            = date_to,
            ).order_by("-date")[:50]
            rows = []
            for e in exp_qs:
                rows.append([
                    fmt_date(e.date),
                    (e.description or "—")[:35],
                    (e.vendor or "—")[:20],
                    fmt_ugx(e.amount, e.currency),
                    e.get_status_display() if hasattr(e,"get_status_display") else e.status,
                ])
            sections.append({
                "id": "expense_breakdown", "title": "Expense Transactions in Period",
                "type": "table",
                "columns": ["Date","Description","Vendor","Amount","Status"],
                "rows": rows,
            })

        return {
            "title": "Budgets Report", "badge": "on_track", "badge_color": "green",
            "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "stats": stats, "charts": charts, "sections": sections,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  USER / ACCESS REPORT
# ═══════════════════════════════════════════════════════════════════════════════

class UserReportBuilder(BaseReportBuilder):
    """
    Models used:
        accounts.CustomUser    — display_role, login_count, last_activity_at,
                                  two_factor_enabled, is_locked, is_active, company(FK)
        accounts.LoginHistory  — user(FK), status, ip_address, browser, location,
                                  timestamp, failure_reason
        accounts.RoleHistory   — role(FK), action, affected_user(FK), user(FK),
                                  timestamp, notes
        accounts.AuditLog      — (all company events)
    """
    TYPE_LABEL   = "Users"
    SECTION_KEYS = ["summary","user_list","login_activity","login_failures","role_changes","audit"]

    def build(self, user, date_from, date_to, store_id=None, section_filter=None):
        from accounts.models import CustomUser, LoginHistory, RoleHistory

        sf = set(section_filter) if section_filter else set(self.SECTION_KEYS)

        # only users of the same company — management permission enforced
        user_qs = CustomUser.objects.filter(company=user.company).select_related("company")

        login_qs = LoginHistory.objects.filter(
            user__company     = user.company,
            timestamp__date__gte = date_from,
            timestamp__date__lte = date_to,
        ).select_related("user")

        role_qs = RoleHistory.objects.filter(
            affected_user__company = user.company,
            timestamp__date__gte  = date_from,
            timestamp__date__lte  = date_to,
        ).select_related("affected_user","user","role__group")

        # ── Aggregates ────────────────────────────────────────────────────────
        total_users    = user_qs.count()
        active_users   = user_qs.filter(is_active=True, locked_until__isnull=True).count()
        locked_users   = user_qs.filter(locked_until__isnull=False).count()
        tfa_enabled    = user_qs.filter(two_factor_enabled=True).count()
        tfa_pct        = round(tfa_enabled / total_users * 100, 1) if total_users else 0
        total_logins   = login_qs.filter(status="success").count()
        failed_logins  = login_qs.filter(status="failed").count()

        stats = [
            {"label": "Total Users",    "value": str(total_users),    "color": "blue"},
            {"label": "Active",         "value": str(active_users),   "color": "green"},
            {"label": "Total Logins",   "value": str(total_logins),   "color": "dim"},
            {"label": "Failed Logins",  "value": str(failed_logins),  "color": "red"},
        ]

        # ── Charts ────────────────────────────────────────────────────────────
        # 1. Login activity over time (line)
        ts_labels, ts_success = bucket_by_date(
            login_qs.filter(status="success"),
            "timestamp", "id", date_from, date_to
        )
        _, ts_failed = bucket_by_date(
            login_qs.filter(status="failed"),
            "timestamp", "id", date_from, date_to, max_points=len(ts_labels)
        )

        # 2. Logins by user (bar3d, top 10)
        user_login_agg = (
            login_qs.filter(status="success")
            .values("user__first_name","user__last_name")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")[:10]
        )
        ul_labels = [f"{x['user__first_name']} {x['user__last_name']}".strip() or "Unknown" for x in user_login_agg]
        ul_values = [int(x["cnt"]) for x in user_login_agg]

        # 3. Role distribution (pie)
        role_agg = (
            user_qs.values("primary_role__group__name")
            .annotate(cnt=Count("id"))
            .order_by("-cnt")
        )
        role_labels = [x["primary_role__group__name"] or "No Role" for x in role_agg]
        role_values = [int(x["cnt"]) for x in role_agg]

        # 4. Security events (doughnut)
        sec_agg = login_qs.values("status").annotate(cnt=Count("id"))
        sec_labels = [x["status"] for x in sec_agg]
        sec_values = [int(x["cnt"]) for x in sec_agg]

        charts = [
            {
                "id": "usr_logins_ts", "title": "Login Activity Over Time", "type": "line",
                "labels": ts_labels,
                "data": [
                    {"label": "Successful", "data": ts_success, "color": "#2a7a6f"},
                    {"label": "Failed",     "data": ts_failed,  "color": "#b83232"},
                ],
            },
            {
                "id": "usr_by_user", "title": "Logins per User (3D Bar)", "type": "bar3d",
                "labels": ul_labels,
                "data": [{"label": "Logins", "data": ul_values, "color": "#5e4ba3"}],
            },
            {
                "id": "usr_roles", "title": "Users by Role", "type": "pie",
                "labels": role_labels,
                "data": [{"label": "Count", "data": role_values,
                          "colors": ["#c94f2a","#2a7a6f","#d4943a","#5e4ba3","#2563c4","#3a4a5c"]}],
            },
            {
                "id": "usr_security", "title": "Login Status Breakdown", "type": "doughnut",
                "labels": sec_labels,
                "data": [{"label": "Count", "data": sec_values,
                          "colors": ["#2a7a6f","#b83232","#c97c1a"]}],
            },
        ]

        # ── Sections ──────────────────────────────────────────────────────────
        sections = []

        if "summary" in sf:
            sections.append({
                "id": "summary", "title": "User & Access Summary", "type": "keyvalue",
                "pairs": [
                    {"label": "Period",          "value": f"{fmt_date(date_from)} – {fmt_date(date_to)}"},
                    {"label": "Total Users",     "value": str(total_users)},
                    {"label": "Active",          "value": str(active_users)},
                    {"label": "Locked",          "value": str(locked_users)},
                    {"label": "2FA Enabled",     "value": f"{tfa_enabled} ({tfa_pct}%)"},
                    {"label": "Successful Logins","value": str(total_logins)},
                    {"label": "Failed Logins",   "value": str(failed_logins)},
                    {"label": "Role Changes",    "value": str(role_qs.count())},
                ],
            })

        if "user_list" in sf:
            rows = []
            for u in user_qs.order_by("first_name"):
                last_active = (
                    u.last_activity_at.strftime("%d %b, %H:%M")
                    if getattr(u,"last_activity_at",None) else "Never"
                )
                rows.append([
                    u.get_full_name() or u.email,
                    u.display_role or "—",
                    str(getattr(u,"login_count",0)),
                    last_active,
                    "✅" if u.two_factor_enabled else "❌",
                    "Locked" if getattr(u,"locked_until",None) else ("Active" if u.is_active else "Inactive"),
                ])
            sections.append({
                "id": "user_list", "title": "User List",
                "type": "table",
                "columns": ["Name","Role","Total Logins","Last Active","2FA","Status"],
                "rows": rows,
            })

        if "login_activity" in sf:
            items = []
            for ln in login_qs.order_by("-timestamp")[:30]:
                sev = "success" if ln.status == "success" else "error"
                items.append({
                    "id":    ln.pk,
                    "label": f"Login {ln.get_status_display() if hasattr(ln,'get_status_display') else ln.status}",
                    "sub":   ln.user.get_full_name() if ln.user else "—",
                    "tag":   "login_success" if ln.status == "success" else "login_failed",
                    "note":  f"{ln.browser or 'Browser'} · {ln.location or 'Unknown'} · {ln.ip_address or '—'}"
                             + (f" · ❌ {ln.failure_reason}" if getattr(ln,"failure_reason",None) else ""),
                    "user":  ln.user.get_full_name() if ln.user else "—",
                    "date":  fmt_dt(ln.timestamp),
                    "severity": sev,
                })
            sections.append({
                "id": "login_activity", "title": "Login History",
                "type": "timeline", "items": items,
            })

        if "login_failures" in sf:
            fail_rows = (
                login_qs.filter(status="failed")
                .values("user__first_name","user__last_name","ip_address","failure_reason","browser")
                .annotate(cnt=Count("id"))
                .order_by("-cnt")[:20]
            )
            rows = [
                [
                    f"{r['user__first_name']} {r['user__last_name']}".strip() or "—",
                    r["ip_address"] or "—",
                    r["browser"] or "—",
                    r["failure_reason"] or "—",
                    str(r["cnt"]),
                ]
                for r in fail_rows
            ]
            sections.append({
                "id": "login_failures", "title": "Failed Login Summary",
                "type": "table",
                "columns": ["User","IP Address","Browser","Failure Reason","# Failures"],
                "rows": rows,
            })

        if "role_changes" in sf:
            items = []
            for rh in role_qs.order_by("-timestamp")[:30]:
                sev = "success" if rh.action=="assigned" else "warning" if rh.action=="removed" else "info"
                items.append({
                    "id":          rh.pk,
                    "description": rh.notes or f"Role '{rh.role.group.name if rh.role and rh.role.group else '?'}' {rh.get_action_display() if hasattr(rh,'get_action_display') else rh.action}",
                    "user":        rh.user.get_full_name() if rh.user else "System",
                    "date":        fmt_dt(rh.timestamp),
                    "severity":    sev,
                })
            sections.append({
                "id": "role_changes", "title": "Role Changes",
                "type": "audit", "items": items,
            })

        if "audit" in sf:
            try:
                from accounts.models import AuditLog
                audit_qs = AuditLog.objects.filter(
                    user__company        = user.company,
                    timestamp__date__gte = date_from,
                    timestamp__date__lte = date_to,
                ).order_by("-timestamp")
                items = _build_audit_items(audit_qs, limit=30)
                if items:
                    sections.append({"id":"audit","title":"Full Audit Log","type":"audit","items":items})
            except Exception:
                pass

        return {
            "title": "Users & Access Report", "badge": "active", "badge_color": "green",
            "date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
            "stats": stats, "charts": charts, "sections": sections,
        }


# ═══════════════════════════════════════════════════════════════════════════════
#  REGISTRY  — add one line per new report type
# ═══════════════════════════════════════════════════════════════════════════════

REPORT_REGISTRY = {
    "sale":     SaleReportBuilder(),
    "product":  ProductReportBuilder(),
    "customer": CustomerReportBuilder(),
    "expense":  ExpenseReportBuilder(),
    "budget":   BudgetReportBuilder(),
    "user":     UserReportBuilder(),

    # Uncomment when builders are ready:
    # "supplier":       SupplierReportBuilder(),
    # "purchase_order": PurchaseOrderReportBuilder(),
    # "transfer":       TransferReportBuilder(),
    # "stock_take":     StockTakeReportBuilder(),
}


# ═══════════════════════════════════════════════════════════════════════════════
#  VIEW
# ═══════════════════════════════════════════════════════════════════════════════

class GeneralTrackerView(LoginRequiredMixin, View):
    """
    GET /api/report/
        ?type=sale
        &date_from=2025-01-01
        &date_to=2025-03-31
        [&store_id=3]
        [&sections=summary,top_products,payments]

    Returns the full report JSON consumed by tracker_report.html.
    """

    def get(self, request):
        rtype     = request.GET.get("type",      "").strip().lower()
        date_from = request.GET.get("date_from", "").strip()
        date_to   = request.GET.get("date_to",   "").strip()
        store_id  = request.GET.get("store_id",  "").strip() or None
        sections  = request.GET.get("sections",  "").strip() or None

        # ── Validate ──────────────────────────────────────────────────────────
        if not rtype:
            return JsonResponse(
                {"error": f"'type' is required. Supported: {', '.join(REPORT_REGISTRY)}"},
                status=400,
            )
        if rtype not in REPORT_REGISTRY:
            return JsonResponse(
                {"error": f"Unknown type '{rtype}'. Supported: {', '.join(REPORT_REGISTRY)}"},
                status=400,
            )

        d_from = parse_date(date_from)
        d_to   = parse_date(date_to)
        if not d_from or not d_to:
            return JsonResponse(
                {"error": "Both 'date_from' and 'date_to' are required (YYYY-MM-DD)."},
                status=400,
            )
        if d_from > d_to:
            return JsonResponse({"error": "'date_from' must be before 'date_to'."}, status=400)

        # Cap range at 2 years to avoid runaway queries
        if (d_to - d_from).days > 730:
            return JsonResponse({"error": "Date range cannot exceed 2 years."}, status=400)

        section_filter = [s.strip() for s in sections.split(",")] if sections else None
        store_id_int   = int(store_id) if store_id and store_id.isdigit() else None

        # ── Build ─────────────────────────────────────────────────────────────
        builder = REPORT_REGISTRY[rtype]
        try:
            data = builder.build(
                user           = request.user,
                date_from      = d_from,
                date_to        = d_to,
                store_id       = store_id_int,
                section_filter = section_filter,
            )
        except Exception:
            logger.exception(
                "GeneralTracker error  type=%s  from=%s  to=%s",
                rtype, date_from, date_to
            )
            return JsonResponse({"error": "Internal error building report."}, status=500)

        return JsonResponse(data)