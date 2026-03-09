"""
transfer_hub.py  –  Single Class-Based View for all Stock Transfer functionality.

Handles tabs: list | create | detail | stats
URL pattern: path('transfers/hub/', TransferHubView.as_view(), name='transfer_hub')
Query-param navigation: ?tab=list | ?tab=create | ?tab=detail&id=<pk> | ?tab=stats
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.shortcuts import render
from datetime import datetime
import logging

from stores.models import Store
from .models import Product, Stock, StockMovement, StockTransfer
from .forms import StockTransferForm

logger = logging.getLogger(__name__)

VALID_TABS = {"list", "create", "detail", "stats"}


class TransferHubView(LoginRequiredMixin, PermissionRequiredMixin, View):
    """
    Unified Transfer Hub – one URL, four tabs, zero full-page reloads.

    GET  ?tab=list            → transfer list with filters & pagination
    GET  ?tab=create          → inline creation form
    GET  ?tab=detail&id=<pk>  → single-transfer detail panel
    GET  ?tab=stats           → summary cards + KPIs
    POST ?tab=create          → save new transfer (AJAX-friendly)
    POST ?tab=approve&id=<pk> → approve  (AJAX)
    POST ?tab=complete&id=<pk>→ complete (AJAX)
    POST ?tab=cancel&id=<pk>  → cancel   (AJAX)
    """

    template_name = "inventory/transfer_hub.html"
    permission_required = "inventory.view_stocktransfer"

    # ──────────────────────────────────────────────
    # Dispatch
    # ──────────────────────────────────────────────

    def get(self, request, *args, **kwargs):
        tab = request.GET.get("tab", "list")
        if tab not in VALID_TABS:
            tab = "list"
        context = self._base_context(request, tab)

        if tab == "list":
            context.update(self._list_context(request))
        elif tab == "create":
            context.update(self._create_context(request))
        elif tab == "detail":
            context.update(self._detail_context(request))
        elif tab == "stats":
            context.update(self._stats_context(request))

        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        tab = request.GET.get("tab", "create")
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"

        if tab == "create":
            return self._handle_create(request, is_ajax)
        elif tab == "approve":
            return self._handle_approve(request, is_ajax)
        elif tab == "complete":
            return self._handle_complete(request, is_ajax)
        elif tab == "cancel":
            return self._handle_cancel(request, is_ajax)

        return redirect(f"{request.path}?tab=list")

    # ──────────────────────────────────────────────
    # Base context (shared across all tabs)
    # ──────────────────────────────────────────────

    def _base_context(self, request, active_tab):
        # Summary counts – always shown in header cards
        qs = StockTransfer.objects.all()
        return {
            "active_tab": active_tab,
            "stores": Store.objects.filter(is_active=True).order_by("name"),
            "status_choices": StockTransfer.STATUS_CHOICES,
            "summary": {
                "pending_count": qs.filter(status="pending").count(),
                "in_transit_count": qs.filter(status="in_transit").count(),
                "completed_count": qs.filter(status="completed").count(),
                "cancelled_count": qs.filter(status="cancelled").count(),
            },
        }

    # ──────────────────────────────────────────────
    # Tab: LIST
    # ──────────────────────────────────────────────

    def _list_context(self, request):
        qs = StockTransfer.objects.select_related(
            "product", "from_store", "to_store",
            "requested_by", "approved_by", "completed_by"
        ).order_by("-created_at")

        # Filters
        status = request.GET.get("status", "")
        from_store = request.GET.get("from_store", "")
        to_store = request.GET.get("to_store", "")
        date_from = request.GET.get("date_from", "")
        date_to = request.GET.get("date_to", "")
        search = request.GET.get("search", "")

        if status:
            qs = qs.filter(status=status)
        if from_store:
            qs = qs.filter(from_store_id=from_store)
        if to_store:
            qs = qs.filter(to_store_id=to_store)
        if date_from:
            try:
                qs = qs.filter(created_at__date__gte=datetime.strptime(date_from, "%Y-%m-%d").date())
            except ValueError:
                pass
        if date_to:
            try:
                qs = qs.filter(created_at__date__lte=datetime.strptime(date_to, "%Y-%m-%d").date())
            except ValueError:
                pass
        if search:
            qs = qs.filter(
                Q(transfer_number__icontains=search) |
                Q(product__name__icontains=search) |
                Q(product__sku__icontains=search)
            )

        paginator = Paginator(qs, 25)
        page_obj = paginator.get_page(request.GET.get("page", 1))

        return {
            "transfers": page_obj,
            "page_obj": page_obj,
            "current_filters": {
                "status": status,
                "from_store": from_store,
                "to_store": to_store,
                "date_from": date_from,
                "date_to": date_to,
                "search": search,
            },
        }

    # ──────────────────────────────────────────────
    # Tab: CREATE
    # ──────────────────────────────────────────────

    def _create_context(self, request):
        initial = {}
        for field in ("product", "from_store", "to_store", "quantity"):
            val = request.GET.get(field)
            if val:
                initial[field] = val

        form = StockTransferForm(user=request.user, initial=initial)
        return {
            "form": form,
            "products": Product.objects.filter(is_active=True).order_by("name"),
        }

    # ──────────────────────────────────────────────
    # Tab: DETAIL
    # ──────────────────────────────────────────────

    def _detail_context(self, request):
        transfer_id = request.GET.get("id")
        if not transfer_id:
            return {"transfer": None, "detail_error": "No transfer ID provided."}

        try:
            transfer = StockTransfer.objects.select_related(
                "product", "from_store", "to_store",
                "requested_by", "approved_by", "completed_by"
            ).get(pk=transfer_id)
        except StockTransfer.DoesNotExist:
            return {"transfer": None, "detail_error": "Transfer not found."}

        related_movements = StockMovement.objects.filter(
            reference=transfer.transfer_number
        ).select_related("store", "created_by").order_by("created_at")

        source_stock = dest_stock = source_stock_after = dest_stock_after = None
        try:
            source_stock = Stock.objects.get(product=transfer.product, store=transfer.from_store)
            source_stock_after = (
                source_stock.quantity
                if transfer.status in ("completed", "in_transit")
                else source_stock.quantity - transfer.quantity
            )
        except Stock.DoesNotExist:
            pass

        try:
            dest_stock = Stock.objects.get(product=transfer.product, store=transfer.to_store)
            dest_stock_after = (
                dest_stock.quantity
                if transfer.status == "completed"
                else dest_stock.quantity + transfer.quantity
            )
        except Stock.DoesNotExist:
            pass

        return {
            "transfer": transfer,
            "related_movements": related_movements,
            "source_stock": source_stock,
            "source_stock_after": source_stock_after,
            "dest_stock": dest_stock,
            "dest_stock_after": dest_stock_after,
        }

    # ──────────────────────────────────────────────
    # Tab: STATS
    # ──────────────────────────────────────────────

    def _stats_context(self, request):
        qs = StockTransfer.objects.all()
        today = timezone.now().date()
        from datetime import timedelta
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        recent_completed = (
            StockTransfer.objects
            .filter(status="completed")
            .select_related("product", "from_store", "to_store")
            .order_by("-completed_at")[:10]
        )

        top_products = (
            StockTransfer.objects
            .values("product__name", "product__id")
            .annotate(transfer_count=Count("id"))
            .order_by("-transfer_count")[:5]
        )

        top_routes = (
            StockTransfer.objects
            .values("from_store__name", "to_store__name")
            .annotate(route_count=Count("id"))
            .order_by("-route_count")[:5]
        )

        return {
            "stats": {
                "total_all_time": qs.count(),
                "this_week": qs.filter(created_at__date__gte=week_ago).count(),
                "this_month": qs.filter(created_at__date__gte=month_ago).count(),
                "avg_completion_rate": self._completion_rate(qs),
            },
            "recent_completed": recent_completed,
            "top_products": top_products,
            "top_routes": top_routes,
        }

    def _completion_rate(self, qs):
        total = qs.count()
        if not total:
            return 0
        completed = qs.filter(status="completed").count()
        return round((completed / total) * 100, 1)

    # ──────────────────────────────────────────────
    # POST handlers
    # ──────────────────────────────────────────────

    def _handle_create(self, request, is_ajax):
        if not request.user.has_perm("inventory.add_stocktransfer"):
            if is_ajax:
                return JsonResponse({"success": False, "error": "Permission denied."}, status=403)
            messages.error(request, "Permission denied.")
            return redirect(f"{request.path}?tab=create")

        # Route to bulk handler
        if request.POST.get("transfer_mode") == "bulk":
            return self._handle_bulk_create(request, is_ajax)

        form = StockTransferForm(request.POST, user=request.user)
        if form.is_valid():
            try:
                with transaction.atomic():
                    transfer = form.save(commit=False)
                    transfer.requested_by = request.user
                    transfer.status = "pending"
                    transfer.save()

                if is_ajax:
                    return JsonResponse({
                        "success": True,
                        "message": f"Transfer {transfer.transfer_number} created successfully!",
                        "transfer_number": transfer.transfer_number,
                        "redirect_url": f"{request.path}?tab=list",
                    })

                messages.success(request, f"Transfer {transfer.transfer_number} created!")
                return redirect(f"{request.path}?tab=detail&id={transfer.pk}")

            except Exception as e:
                logger.error(f"Error creating transfer: {e}", exc_info=True)
                if is_ajax:
                    return JsonResponse({"success": False, "error": str(e)}, status=500)
                messages.error(request, f"Error: {e}")

        if is_ajax:
            return JsonResponse({"success": False, "errors": form.errors}, status=400)

        context = self._base_context(request, "create")
        context.update({"form": form, "products": Product.objects.filter(is_active=True).order_by("name")})
        return render(request, self.template_name, context)

    def _handle_bulk_create(self, request, is_ajax):
        """
        Bulk transfer: one from_store + one to_store, N product rows.
        POST fields:
          from_store, to_store, notes
          products[]   — product PKs  (parallel arrays)
          quantities[] — quantities
        """
        from decimal import Decimal, InvalidOperation

        from_store_id = request.POST.get("from_store")
        to_store_id   = request.POST.get("to_store")
        notes         = request.POST.get("notes", "")
        product_ids   = request.POST.getlist("products[]")
        quantities    = request.POST.getlist("quantities[]")

        errors = []
        if not from_store_id:
            errors.append("Source store is required.")
        if not to_store_id:
            errors.append("Destination store is required.")
        if from_store_id and to_store_id and from_store_id == to_store_id:
            errors.append("Source and destination stores must be different.")
        if not product_ids:
            errors.append("Add at least one product row.")

        if errors:
            if is_ajax:
                return JsonResponse({"success": False, "error": " ".join(errors)}, status=400)
            for e in errors:
                messages.error(request, e)
            return redirect(f"{request.path}?tab=create")

        try:
            from_store = Store.objects.get(pk=from_store_id)
            to_store   = Store.objects.get(pk=to_store_id)
        except Store.DoesNotExist as exc:
            msg = f"Store not found: {exc}"
            if is_ajax:
                return JsonResponse({"success": False, "error": msg}, status=400)
            messages.error(request, msg)
            return redirect(f"{request.path}?tab=create")

        created_transfers = []
        row_errors = []

        try:
            with transaction.atomic():
                for idx, (pid, qty_str) in enumerate(zip(product_ids, quantities), start=1):
                    if not pid or not qty_str:
                        row_errors.append(f"Row {idx}: empty product or quantity — skipped.")
                        continue
                    try:
                        product = Product.objects.get(pk=pid, is_active=True)
                        try:
                            quantity = Decimal(qty_str)
                        except InvalidOperation:
                            row_errors.append(f"Row {idx}: invalid quantity '{qty_str}'.")
                            continue
                        if quantity <= 0:
                            row_errors.append(f"Row {idx}: quantity must be > 0.")
                            continue

                        transfer = StockTransfer(
                            product=product,
                            from_store=from_store,
                            to_store=to_store,
                            quantity=quantity,
                            notes=notes,
                            requested_by=request.user,
                            status="pending",
                        )
                        transfer.save()
                        created_transfers.append(transfer)

                    except Product.DoesNotExist:
                        row_errors.append(f"Row {idx}: product id={pid} not found.")
                    except Exception as row_exc:
                        row_errors.append(f"Row {idx}: {row_exc}")

                if not created_transfers:
                    raise Exception("No valid transfers could be created. " + " ".join(row_errors))

        except Exception as exc:
            logger.error(f"Bulk transfer error: {exc}", exc_info=True)
            if is_ajax:
                return JsonResponse({"success": False, "error": str(exc)}, status=500)
            messages.error(request, str(exc))
            return redirect(f"{request.path}?tab=create")

        n   = len(created_transfers)
        msg = f"{n} transfer request{'s' if n != 1 else ''} created successfully!"
        if row_errors:
            msg += f" ({len(row_errors)} rows skipped)"

        if is_ajax:
            return JsonResponse({
                "success": True,
                "message": msg,
                "created_count": n,
                "skipped": row_errors,
                "redirect_url": f"{request.path}?tab=list",
            })

        messages.success(request, msg)
        for err in row_errors:
            messages.warning(request, err)
        return redirect(f"{request.path}?tab=list")

    def _handle_approve(self, request, is_ajax):
        pk = request.GET.get("id")
        transfer = get_object_or_404(StockTransfer, pk=pk)
        if not transfer.can_be_approved:
            err = "This transfer cannot be approved."
            return JsonResponse({"success": False, "error": err}, status=400) if is_ajax else self._redirect_detail(request, pk, err)
        try:
            with transaction.atomic():
                transfer.approve(request.user)
            if is_ajax:
                return JsonResponse({"success": True, "message": f"Transfer {transfer.transfer_number} approved!", "status": transfer.status})
            messages.success(request, f"✅ Transfer {transfer.transfer_number} approved!")
        except (ValidationError, Exception) as e:
            if is_ajax:
                return JsonResponse({"success": False, "error": str(e)}, status=400)
            messages.error(request, str(e))
        return redirect(f"{request.path}?tab=detail&id={pk}")

    def _handle_complete(self, request, is_ajax):
        pk = request.GET.get("id")
        transfer = get_object_or_404(StockTransfer, pk=pk)
        if not transfer.can_be_completed:
            err = "This transfer cannot be completed."
            return JsonResponse({"success": False, "error": err}, status=400) if is_ajax else self._redirect_detail(request, pk, err)
        try:
            with transaction.atomic():
                transfer.complete(request.user)
            if is_ajax:
                return JsonResponse({"success": True, "message": f"Transfer {transfer.transfer_number} completed!", "status": transfer.status})
            messages.success(request, f"✅ Transfer {transfer.transfer_number} completed!")
        except (ValidationError, Exception) as e:
            if is_ajax:
                return JsonResponse({"success": False, "error": str(e)}, status=400)
            messages.error(request, str(e))
        return redirect(f"{request.path}?tab=detail&id={pk}")

    def _handle_cancel(self, request, is_ajax):
        pk = request.GET.get("id")
        transfer = get_object_or_404(StockTransfer, pk=pk)
        if not transfer.can_be_cancelled:
            err = "This transfer cannot be cancelled."
            return JsonResponse({"success": False, "error": err}, status=400) if is_ajax else self._redirect_detail(request, pk, err)
        reason = request.POST.get("reason", "No reason provided")
        try:
            with transaction.atomic():
                transfer.cancel(request.user, reason)
            if is_ajax:
                return JsonResponse({"success": True, "message": f"Transfer {transfer.transfer_number} cancelled!", "status": transfer.status})
            messages.success(request, f"✅ Transfer {transfer.transfer_number} cancelled!")
        except (ValidationError, Exception) as e:
            if is_ajax:
                return JsonResponse({"success": False, "error": str(e)}, status=400)
            messages.error(request, str(e))
        return redirect(f"{request.path}?tab=list")

    def _redirect_detail(self, request, pk, error_msg):
        messages.error(request, error_msg)
        return redirect(f"{request.path}?tab=detail&id={pk}")