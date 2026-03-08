from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination, CursorPagination
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Sum, Count, Avg, F
from django.utils import timezone
from django.shortcuts import get_object_or_404
from decimal import Decimal
from datetime import datetime, timedelta
import logging
from .models import Sale, SaleItem, Payment, Cart, CartItem, Receipt
from .serializers import (
    SaleSerializer, SaleItemSerializer, PaymentSerializer,
    CartSerializer, CartItemSerializer, ReceiptSerializer,
    CartConfirmSerializer, DocumentTypeSelectionSerializer,
    ProformaConvertSerializer, SalesReportSerializer, ZReportSerializer
)
from stores.models import Store
from stores.utils import validate_store_access, get_user_accessible_stores
from inventory.models import Product, Service, Stock

from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from company.models import EFRISHsCode
from tenancy.utils import tenant_context_safe, get_current_tenant

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["GET"])
def search_hs_codes(request):
    """
    Search HS codes with autocomplete functionality

    Query params:
        - q: search query (searches code and description)
        - limit: number of results (default: 20, max: 50)
        - leaf_only: if 'true', only return leaf nodes (default: false to include all)
    """
    query = request.GET.get('q', '').strip()
    limit = min(int(request.GET.get('limit', 20)), 50)
    # Default to False so all codes are returned unless explicitly set
    leaf_only = request.GET.get('leaf_only', 'false').lower() == 'true'

    company = get_current_tenant()
    if not company:
        return JsonResponse({'success': False, 'error': 'No company context found'}, status=400)

    try:
        with tenant_context_safe(company):
            qs = EFRISHsCode.objects.all()

            # Only filter if leaf_only is True
            if leaf_only:
                qs = qs.filter(is_leaf=True)

            # Apply search
            if query:
                qs = qs.filter(Q(hs_code__icontains=query) | Q(description__icontains=query))
                qs = qs.order_by('hs_code')

                # Prioritize exact matches
                exact_matches = list(qs.filter(hs_code__iexact=query))
                starts_with = list(qs.filter(hs_code__istartswith=query).exclude(hs_code__iexact=query))
                contains = list(qs.exclude(Q(hs_code__iexact=query) | Q(hs_code__istartswith=query)))

                hs_codes = (exact_matches + starts_with + contains)[:limit]
            else:
                hs_codes = list(qs.order_by('hs_code')[:limit])

            results = [
                {
                    'hs_code': code.hs_code,
                    'description': code.description,
                    'is_leaf': code.is_leaf,
                    'parent_code': code.parent_code,
                    'display': f"{code.hs_code} - {code.description[:60]}{'...' if len(code.description) > 60 else ''}"
                }
                for code in hs_codes
            ]

            return JsonResponse({'success': True, 'results': results, 'total': len(results), 'query': query})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)



@login_required
@require_http_methods(["GET"])
def get_hs_code_details(request, hs_code):
    """
    Get detailed information about a specific HS code
    """
    # FIXED: get_current_tenant() doesn't take arguments
    company = get_current_tenant()

    if not company:
        return JsonResponse({
            'success': False,
            'error': 'No company context found'
        }, status=400)

    try:
        with tenant_context_safe(company):
            try:
                code = EFRISHsCode.objects.get(hs_code=hs_code)

                # Get parent information if exists
                parent_info = None
                if code.parent_code:
                    try:
                        parent = EFRISHsCode.objects.get(hs_code=code.parent_code)
                        parent_info = {
                            'hs_code': parent.hs_code,
                            'description': parent.description
                        }
                    except EFRISHsCode.DoesNotExist:
                        pass

                # Get children if not a leaf
                children = []
                if not code.is_leaf:
                    children = list(
                        EFRISHsCode.objects.filter(parent_code=code.hs_code)
                        .values('hs_code', 'description', 'is_leaf')[:10]
                    )

                return JsonResponse({
                    'success': True,
                    'hs_code': {
                        'hs_code': code.hs_code,
                        'description': code.description,
                        'is_leaf': code.is_leaf,
                        'parent_code': code.parent_code,
                        'parent_info': parent_info,
                        'children': children,
                        'last_synced': code.last_synced.isoformat() if code.last_synced else None
                    }
                })

            except EFRISHsCode.DoesNotExist:
                return JsonResponse({
                    'success': False,
                    'error': f'HS code {hs_code} not found'
                }, status=404)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def browse_hs_codes(request):
    """
    Browse HS codes by parent code (hierarchical browsing)
    """
    parent_code = request.GET.get('parent_code', None)
    limit = min(int(request.GET.get('limit', 50)), 100)

    # FIXED: get_current_tenant() doesn't take arguments
    company = get_current_tenant()

    if not company:
        return JsonResponse({
            'success': False,
            'error': 'No company context found'
        }, status=400)

    try:
        with tenant_context_safe(company):
            if parent_code:
                # Get children of specific parent
                qs = EFRISHsCode.objects.filter(parent_code=parent_code)

                # Get parent info
                try:
                    parent = EFRISHsCode.objects.get(hs_code=parent_code)
                    parent_info = {
                        'hs_code': parent.hs_code,
                        'description': parent.description,
                        'parent_code': parent.parent_code
                    }
                except EFRISHsCode.DoesNotExist:
                    parent_info = None
            else:
                # Get top-level codes (no parent)
                qs = EFRISHsCode.objects.filter(
                    Q(parent_code__isnull=True) | Q(parent_code='')
                )
                parent_info = None

            hs_codes = list(qs.order_by('hs_code')[:limit])

            results = [
                {
                    'hs_code': code.hs_code,
                    'description': code.description,
                    'is_leaf': code.is_leaf,
                    'parent_code': code.parent_code,
                    'has_children': not code.is_leaf,
                    'display': f"{code.hs_code} - {code.description}"
                }
                for code in hs_codes
            ]

            return JsonResponse({
                'success': True,
                'results': results,
                'total': len(results),
                'parent_code': parent_code,
                'parent_info': parent_info
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ==================== CUSTOM PAGINATION ====================
class StandardResultsSetPagination(PageNumberPagination):
    """Standard pagination for list views"""
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 100


class LargeResultsSetPagination(PageNumberPagination):
    """Pagination for larger datasets"""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 500


class SaleCursorPagination(CursorPagination):
    """
    Keyset (cursor) pagination for Sale list endpoint.
    O(1) regardless of page depth — required for millions of rows.
    """
    page_size = 50
    page_size_query_param = 'page_size'
    max_page_size = 200
    ordering = '-created_at'
    cursor_query_param = 'cursor'


# ==================== CUSTOM PERMISSIONS ====================
class IsStoreAccessible(IsAuthenticated):
    """
    Custom permission to check if user has access to the store
    """

    def has_object_permission(self, request, view, obj):
        # Get store from object
        store = getattr(obj, 'store', None)
        if not store:
            return False

        try:
            validate_store_access(request.user, store, action='view', raise_exception=True)
            return True
        except (PermissionDenied, Exception) as e:
            # Log unexpected errors so they don't silently masquerade as 403s
            from django.core.exceptions import PermissionDenied as DjangoPermDenied
            if not isinstance(e, DjangoPermDenied):
                logger.warning(f"Unexpected error in IsStoreAccessible for store {store.id}: {e}")
            return False


# ==================== SALE VIEWSET ====================
class SaleViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing sales (Receipts, Invoices, Proformas, Estimates)

    Provides:
    - list: Get all sales with filtering
    - retrieve: Get specific sale details
    - create: Create new sale
    - update/partial_update: Modify existing sale
    - destroy: Delete sale
    - fiscalize: Send sale to EFRIS for fiscalization
    - void: Void a sale
    - refund: Process refund for a sale
    - duplicate: Create duplicate of a sale
    - analytics: Get sales analytics
    """
    serializer_class = SaleSerializer
    permission_classes = [IsStoreAccessible]
    pagination_class = SaleCursorPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['document_type', 'payment_method', 'payment_status', 'status', 'is_fiscalized', 'store']
    search_fields = ['document_number', 'transaction_id', 'efris_invoice_number', 'customer__name', 'customer__phone']
    ordering_fields = ['created_at', 'total_amount', 'document_number']
    ordering = ['-created_at']

    # Columns needed for the list view — reduces per-row data transfer by ~70%
    LIST_ONLY_FIELDS = [
        'id', 'document_number', 'document_type', 'status', 'payment_status',
        'payment_method', 'total_amount', 'currency', 'created_at', 'updated_at',
        'is_fiscalized', 'efris_invoice_number', 'transaction_type', 'is_voided',
        'store_id', 'customer_id', 'created_by_id',
    ]

    def get_queryset(self):
        """
        Filter sales by user's accessible stores.
        Uses only() for list actions to avoid fetching all 40+ columns.
        """
        user = self.request.user
        accessible_stores = get_user_accessible_stores(user)

        base_qs = Sale.objects.filter(store__in=accessible_stores)

        # Narrow columns for list; full object for detail/update/fiscalize
        if getattr(self, 'action', None) == 'list':
            queryset = base_qs.only(
                *self.LIST_ONLY_FIELDS
            ).select_related('store', 'customer', 'created_by')
        else:
            queryset = base_qs.select_related(
                'store', 'customer', 'created_by'
            ).prefetch_related(
                'items__product', 'items__service', 'payments'
            )

        # Additional filters from query params
        document_type = self.request.query_params.get('document_type')
        if document_type:
            queryset = queryset.filter(document_type=document_type)

        payment_method = self.request.query_params.get('payment_method')
        if payment_method:
            queryset = queryset.filter(payment_method=payment_method)

        payment_status = self.request.query_params.get('payment_status')
        if payment_status:
            queryset = queryset.filter(payment_status=payment_status)

        # Date range filtering
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')

        if date_from:
            try:
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__date__gte=date_from)
            except ValueError:
                pass

        if date_to:
            try:
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                queryset = queryset.filter(created_at__date__lte=date_to)
            except ValueError:
                pass

        # Amount range filtering
        min_amount = self.request.query_params.get('min_amount')
        if min_amount:
            try:
                queryset = queryset.filter(total_amount__gte=Decimal(min_amount))
            except:
                pass

        max_amount = self.request.query_params.get('max_amount')
        if max_amount:
            try:
                queryset = queryset.filter(total_amount__lte=Decimal(max_amount))
            except:
                pass

        return queryset

    def perform_create(self, serializer):
        """Set created_by to current user"""
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def fiscalize(self, request, pk=None):
        """
        Fiscalize a sale (send to EFRIS)

        POST /api/sales/{id}/fiscalize/
        """
        sale = self.get_object()

        # Check if sale can be fiscalized
        if hasattr(sale, 'can_fiscalize'):
            can_fiscalize, reason = sale.can_fiscalize(request.user)
            if not can_fiscalize:
                return Response({
                    'success': False,
                    'error': reason
                }, status=status.HTTP_400_BAD_REQUEST)

        # Check if already fiscalized
        if sale.is_fiscalized:
            return Response({
                'success': False,
                'error': f'{sale.get_document_type_display()} is already fiscalized'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            # Queue fiscalization task
            from .tasks import fiscalize_invoice_async
            task_result = fiscalize_invoice_async.delay(
                sale.pk, request.user.pk, schema_name=connection.schema_name)

            return Response({
                'success': True,
                'message': f'Fiscalization queued for {sale.get_document_type_display()} {sale.document_number}',
                'task_id': task_result.id
            }, status=status.HTTP_202_ACCEPTED)

        except Exception as e:
            logger.error(f"Error queueing fiscalization for sale {pk}: {e}")
            return Response({
                'success': False,
                'error': 'Failed to queue fiscalization'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def void(self, request, pk=None):
        """
        Void a sale

        POST /api/sales/{id}/void/
        Body: {
            "void_reason": "CUSTOMER_REQUEST",
            "void_notes": "Optional notes"
        }
        """
        sale = self.get_object()

        # Validate void request
        if sale.is_voided:
            return Response({
                'success': False,
                'error': 'Sale is already voided'
            }, status=status.HTTP_400_BAD_REQUEST)

        if sale.transaction_type != 'SALE':
            return Response({
                'success': False,
                'error': 'Only regular sales can be voided'
            }, status=status.HTTP_400_BAD_REQUEST)

        void_reason = request.data.get('void_reason', '').strip()
        void_notes = request.data.get('void_notes', '').strip()

        if not void_reason:
            return Response({
                'success': False,
                'error': 'Void reason is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            from django.db import transaction, connection

            with transaction.atomic():
                # Restore stock for products
                for item in sale.items.all():
                    if item.item_type == 'PRODUCT' and item.product:
                        stock = Stock.objects.select_for_update().get(
                            product=item.product,
                            store=sale.store
                        )
                        stock.quantity += item.quantity
                        stock.save()

                # Mark payments as voided
                sale.payments.filter(is_confirmed=True).update(
                    is_voided=True,
                    voided_at=timezone.now(),
                    voided_by=request.user,
                    void_reason=void_reason
                )

                # Mark sale as voided
                sale.is_voided = True
                sale.void_reason = void_reason
                sale.void_notes = void_notes
                sale.voided_at = timezone.now()
                sale.voided_by = request.user
                sale.status = 'VOIDED'
                sale.save()

            return Response({
                'success': True,
                'message': f'Sale #{sale.document_number} voided successfully'
            })

        except Exception as e:
            logger.error(f"Error voiding sale {pk}: {e}")
            return Response({
                'success': False,
                'error': 'Failed to void sale'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def refund(self, request, pk=None):
        """
        Process refund for a sale

        POST /api/sales/{id}/refund/
        Body: {
            "items": [{"item_id": 1, "quantity": 2}],
            "refund_reason": "DEFECTIVE_PRODUCT",
            "refund_notes": "Optional notes",
            "refund_method": "CASH"
        }
        """
        sale = self.get_object()

        # Validate refund request
        if sale.transaction_type != 'SALE':
            return Response({
                'success': False,
                'error': 'Only regular sales can be refunded'
            }, status=status.HTTP_400_BAD_REQUEST)

        if sale.is_voided:
            return Response({
                'success': False,
                'error': 'Voided sales cannot be refunded'
            }, status=status.HTTP_400_BAD_REQUEST)

        items_data = request.data.get('items', [])
        refund_reason = request.data.get('refund_reason', '').strip()
        refund_notes = request.data.get('refund_notes', '').strip()
        refund_method = request.data.get('refund_method', 'CASH')

        if not items_data:
            return Response({
                'success': False,
                'error': 'At least one item is required for refund'
            }, status=status.HTTP_400_BAD_REQUEST)

        if not refund_reason:
            return Response({
                'success': False,
                'error': 'Refund reason is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            from django.db import transaction

            with transaction.atomic():
                # Create refund sale
                refund_sale = Sale.objects.create(
                    store=sale.store,
                    customer=sale.customer,
                    transaction_type='REFUND',
                    related_sale=sale,
                    payment_method=refund_method,
                    payment_status='PAID',
                    status='COMPLETED',
                    document_type=sale.document_type,
                    created_by=request.user,
                    notes=f"Refund for sale #{sale.document_number}. Reason: {refund_reason}. {refund_notes}"
                )

                refund_total = Decimal('0')

                # Process refund items
                for item_data in items_data:
                    original_item = sale.items.get(id=item_data['item_id'])
                    qty = Decimal(str(item_data['quantity']))

                    # Create refund item
                    SaleItem.objects.create(
                        sale=refund_sale,
                        item_type=original_item.item_type,
                        product=original_item.product if original_item.item_type == 'PRODUCT' else None,
                        service=original_item.service if original_item.item_type == 'SERVICE' else None,
                        quantity=-qty,
                        unit_price=original_item.unit_price,
                        discount=original_item.discount,
                        tax_rate=original_item.tax_rate
                    )

                    # Restore stock for products
                    if original_item.item_type == 'PRODUCT' and original_item.product:
                        stock = Stock.objects.select_for_update().get(
                            product=original_item.product,
                            store=sale.store
                        )
                        stock.quantity += qty
                        stock.save()

                # Update refund sale totals
                refund_sale.update_totals()

                # Check if sale is fully refunded
                total_refunded = Sale.objects.filter(
                    related_sale=sale,
                    transaction_type='REFUND'
                ).aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')

                if abs(total_refunded) >= sale.total_amount:
                    sale.is_refunded = True
                    sale.status = 'REFUNDED'
                    sale.save()

            return Response({
                'success': True,
                'message': f'Refund processed successfully',
                'refund_sale_id': refund_sale.id,
                'refund_document_number': refund_sale.document_number,
                'refund_amount': refund_sale.total_amount
            })

        except Exception as e:
            logger.error(f"Error processing refund for sale {pk}: {e}")
            return Response({
                'success': False,
                'error': 'Failed to process refund'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def duplicate(self, request, pk=None):
        """
        Create duplicate of a sale

        POST /api/sales/{id}/duplicate/
        """
        original = self.get_object()

        try:
            from django.db import transaction

            with transaction.atomic():
                # Create new sale
                new_sale = Sale.objects.create(
                    store=original.store,
                    customer=original.customer,
                    created_by=request.user,
                    document_type=original.document_type,
                    payment_method=original.payment_method,
                    duplicated_from=original,
                    notes=f"Duplicated from {original.get_document_type_display().lower()} {original.document_number}"
                )

                # Copy items
                for item in original.items.all():
                    SaleItem.objects.create(
                        sale=new_sale,
                        product=item.product,
                        service=item.service,
                        item_type=item.item_type,
                        quantity=item.quantity,
                        unit_price=item.unit_price,
                        tax_rate=item.tax_rate,
                    )

                # Update totals
                new_sale.update_totals()

            serializer = self.get_serializer(new_sale)
            return Response({
                'success': True,
                'message': f'{original.get_document_type_display()} {original.document_number} duplicated successfully',
                'sale': serializer.data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error duplicating sale {pk}: {e}")
            return Response({
                'success': False,
                'error': 'Failed to duplicate sale'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['get'], permission_classes=[IsAuthenticated])
    def analytics(self, request):
        """
        Get sales analytics

        GET /api/sales/analytics/?date_from=2024-01-01&date_to=2024-01-31&store_id=1
        """
        try:
            # Get date range
            date_from = request.query_params.get('date_from')
            date_to = request.query_params.get('date_to')
            store_id = request.query_params.get('store_id')

            if not date_from:
                date_from = timezone.now().date() - timedelta(days=30)
            else:
                date_from = datetime.strptime(date_from, '%Y-%m-%d').date()

            if not date_to:
                date_to = timezone.now().date()
            else:
                date_to = datetime.strptime(date_to, '%Y-%m-%d').date()

            # Base queryset
            queryset = self.get_queryset().filter(
                created_at__date__gte=date_from,
                created_at__date__lte=date_to,
                transaction_type='SALE',
                is_voided=False
            )

            if store_id:
                queryset = queryset.filter(store_id=store_id)

            # Calculate metrics
            total_sales = queryset.count()
            total_revenue = queryset.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')
            avg_sale_value = queryset.aggregate(Avg('total_amount'))['total_amount__avg'] or Decimal('0')

            # Sales by payment method
            payment_methods = queryset.values('payment_method').annotate(
                count=Count('id'),
                total=Sum('total_amount')
            ).order_by('-total')

            # Daily sales trend — use TruncDate (safe, DB-portable, index-friendly)
            from django.db.models.functions import TruncDate
            daily_sales = queryset.annotate(
                day=TruncDate('created_at')
            ).values('day').annotate(
                count=Count('id'),
                total=Sum('total_amount')
            ).order_by('day')

            # Document type breakdown
            document_types = queryset.values('document_type').annotate(
                count=Count('id'),
                total=Sum('total_amount')
            )

            return Response({
                'success': True,
                'period': {
                    'from': date_from,
                    'to': date_to,
                    'days': (date_to - date_from).days + 1
                },
                'metrics': {
                    'total_sales': total_sales,
                    'total_revenue': total_revenue,
                    'avg_sale_value': avg_sale_value
                },
                'payment_methods': list(payment_methods),
                'daily_sales': list(daily_sales),
                'document_types': list(document_types)
            })

        except Exception as e:
            logger.error(f"Error generating analytics: {e}")
            return Response({
                'success': False,
                'error': 'Failed to generate analytics'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def convert_to_invoice(self, request, pk=None):
        """
        Convert proforma/estimate to invoice

        POST /api/sales/{id}/convert_to_invoice/
        Body: {
            "due_date": "2024-12-31",
            "terms": "Payment terms..."
        }
        """
        sale = self.get_object()

        if sale.document_type not in ['PROFORMA', 'ESTIMATE']:
            return Response({
                'success': False,
                'error': 'Only proforma invoices and estimates can be converted to invoices'
            }, status=status.HTTP_400_BAD_REQUEST)

        serializer = ProformaConvertSerializer(data=request.data)
        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            from django.db import transaction

            with transaction.atomic():
                # Update sale to invoice
                sale.document_type = 'INVOICE'
                sale.due_date = serializer.validated_data['due_date']
                sale.payment_status = 'PENDING'
                sale.status = 'PENDING_PAYMENT'

                if 'terms' in serializer.validated_data:
                    sale.notes = f"{sale.notes}\n\nTerms: {serializer.validated_data['terms']}"

                sale.save()

                # Create stock movements for products
                from inventory.models import StockMovement
                for item in sale.items.all():
                    if item.item_type == 'PRODUCT' and item.product:
                        StockMovement.objects.create(
                            product=item.product,
                            store=sale.store,
                            movement_type='SALE',
                            quantity=item.quantity,
                            reference=sale.document_number or f"SALE-{sale.id}",
                            unit_price=item.unit_price,
                            total_value=item.total_price,
                            created_by=request.user,
                            notes=f"Converted from {sale.get_document_type_display()}"
                        )

            return Response({
                'success': True,
                'message': f'{sale.get_document_type_display()} converted to invoice successfully',
                'sale': SaleSerializer(sale).data
            })

        except Exception as e:
            logger.error(f"Error converting sale {pk} to invoice: {e}")
            return Response({
                'success': False,
                'error': 'Failed to convert to invoice'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==================== PAYMENT VIEWSET ====================
class PaymentViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing payments
    """
    serializer_class = PaymentSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['sale', 'payment_method', 'is_confirmed', 'is_voided']
    ordering_fields = ['created_at', 'amount']
    ordering = ['-created_at']

    def get_queryset(self):
        user = self.request.user
        accessible_stores = get_user_accessible_stores(user)

        return Payment.objects.filter(
            store__in=accessible_stores
        ).select_related('sale', 'store')

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def confirm(self, request, pk=None):
        """Confirm a payment"""
        payment = self.get_object()

        if payment.is_confirmed:
            return Response({
                'success': False,
                'error': 'Payment is already confirmed'
            }, status=status.HTTP_400_BAD_REQUEST)

        payment.is_confirmed = True
        payment.confirmed_at = timezone.now()
        payment.save()

        # Update sale payment status
        payment.sale.update_payment_status()

        return Response({
            'success': True,
            'message': 'Payment confirmed successfully'
        })

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def void(self, request, pk=None):
        """Void a payment"""
        payment = self.get_object()

        if payment.is_voided:
            return Response({
                'success': False,
                'error': 'Payment is already voided'
            }, status=status.HTTP_400_BAD_REQUEST)

        void_reason = request.data.get('void_reason', '').strip()

        payment.is_voided = True
        payment.voided_at = timezone.now()
        payment.voided_by = request.user
        payment.void_reason = void_reason
        payment.save()

        # Update sale payment status
        payment.sale.update_payment_status()

        return Response({
            'success': True,
            'message': 'Payment voided successfully'
        })


# ==================== CART VIEWSET ====================
class CartViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing shopping carts
    """
    serializer_class = CartSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        accessible_stores = get_user_accessible_stores(user)

        return Cart.objects.filter(
            Q(user=user) | Q(store__in=accessible_stores),
            status='OPEN'
        ).select_related('store', 'customer').prefetch_related('items__product')

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def add_item(self, request, pk=None):
        """
        Add item to cart

        POST /api/carts/{id}/add_item/
        Body: {
            "product_id": 1,
            "quantity": 2,
            "unit_price": 5000  # optional
        }
        """
        cart = self.get_object()

        product_id = request.data.get('product_id')
        quantity = request.data.get('quantity', 1)

        if not product_id:
            return Response({
                'success': False,
                'error': 'Product ID is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            quantity = Decimal(str(quantity))
            if quantity <= 0:
                raise ValueError("Quantity must be positive")
        except (ValueError, TypeError):
            return Response({
                'success': False,
                'error': 'Invalid quantity'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            product = Product.objects.get(id=product_id)

            cart_item, created = CartItem.objects.get_or_create(
                cart=cart,
                product=product,
                defaults={
                    'quantity': quantity,
                    'unit_price': request.data.get('unit_price', product.selling_price),
                }
            )

            if not created:
                cart_item.quantity += quantity
                cart_item.save()

            cart.update_totals()

            return Response({
                'success': True,
                'message': 'Item added to cart',
                'cart': CartSerializer(cart).data
            })

        except Product.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Product not found'
            }, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error adding item to cart: {e}")
            return Response({
                'success': False,
                'error': 'Failed to add item to cart'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def remove_item(self, request, pk=None):
        """
        Remove item from cart

        POST /api/carts/{id}/remove_item/
        Body: {"item_id": 1}
        """
        cart = self.get_object()
        item_id = request.data.get('item_id')

        if not item_id:
            return Response({
                'success': False,
                'error': 'Item ID is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            item = CartItem.objects.get(id=item_id, cart=cart)
            item.delete()
            cart.update_totals()

            return Response({
                'success': True,
                'message': 'Item removed from cart',
                'cart': CartSerializer(cart).data
            })

        except CartItem.DoesNotExist:
            return Response({
                'success': False,
                'error': 'Item not found in cart'
            }, status=status.HTTP_404_NOT_FOUND)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def confirm(self, request, pk=None):
        """
        Confirm cart and create sale

        POST /api/carts/{id}/confirm/
        Body: {
            "payment_method": "CASH",
            "terms": "Optional terms",
            "purchase_order": "Optional PO"
        }
        """
        cart = self.get_object()

        serializer = CartConfirmSerializer(data=request.data, instance=cart, context={'request': request})
        if not serializer.is_valid():
            return Response({
                'success': False,
                'errors': serializer.errors
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            sale = serializer.save()

            return Response({
                'success': True,
                'message': 'Cart confirmed successfully',
                'sale': SaleSerializer(sale).data
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error confirming cart {pk}: {e}")
            return Response({
                'success': False,
                'error': 'Failed to confirm cart'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ==================== RECEIPT VIEWSET ====================
class ReceiptViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint for viewing receipts
    """
    serializer_class = ReceiptSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        user = self.request.user
        accessible_stores = get_user_accessible_stores(user)

        return Receipt.objects.filter(
            sale__store__in=accessible_stores
        ).select_related('sale', 'printed_by')

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def reprint(self, request, pk=None):
        """Mark receipt as reprinted"""
        receipt = self.get_object()

        receipt.print_count += 1
        receipt.is_duplicate = True
        receipt.last_printed_by = request.user
        receipt.save()
        return Response({
            'success': True,
            'message': 'Receipt marked for reprint',
            'receipt': ReceiptSerializer(receipt).data
        })


class ReportViewSet(viewsets.ViewSet):
    """
    API endpoint for sales reports
    """


    permission_classes = [IsAuthenticated]


    @action(detail=False, methods=['get'])
    def z_report(self, request):
        """
        Generate Z Report (end of day report)

        GET /api/reports/z_report/?store_id=1&date=2024-01-20
        """
        try:
            store_id = request.query_params.get('store_id')
            report_date = request.query_params.get('date')

            if not store_id:
                return Response({
                    'success': False,
                    'error': 'Store ID is required'
                }, status=status.HTTP_400_BAD_REQUEST)

            if not report_date:
                report_date = timezone.now().date()
            else:
                report_date = datetime.strptime(report_date, '%Y-%m-%d').date()

            # Get store
            store = get_object_or_404(Store, id=store_id)
            validate_store_access(request.user, store, action='view', raise_exception=True)

            # Get sales for the day
            start_time = datetime.combine(report_date, datetime.min.time())
            end_time = datetime.combine(report_date, datetime.max.time())

            sales = Sale.objects.filter(
                store=store,
                created_at__range=(start_time, end_time),
                transaction_type='SALE',
                is_voided=False
            )

            refunds = Sale.objects.filter(
                store=store,
                created_at__range=(start_time, end_time),
                transaction_type='REFUND'
            )

            # Calculate totals
            total_sales = sales.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')
            total_tax = sales.aggregate(Sum('tax_amount'))['tax_amount__sum'] or Decimal('0')
            total_discount = sales.aggregate(Sum('discount_amount'))['discount_amount__sum'] or Decimal('0')
            total_refunds = refunds.aggregate(Sum('total_amount'))['total_amount__sum'] or Decimal('0')

            transaction_count = sales.count()
            items_sold = SaleItem.objects.filter(sale__in=sales).aggregate(Sum('quantity'))['quantity__sum'] or 0

            # Document type breakdown
            doc_breakdown = sales.values('document_type').annotate(count=Count('id'))
            document_type_breakdown = {item['document_type']: item['count'] for item in doc_breakdown}

            # Payment method breakdown
            payment_breakdown = sales.values('payment_method').annotate(total=Sum('total_amount'))
            payment_method_breakdown = {item['payment_method']: item['total'] for item in payment_breakdown}

            report_data = {
                'store_id': store.id,
                'store_name': store.name,
                'report_date': report_date,
                'start_time': start_time,
                'end_time': end_time,
                'total_sales': total_sales,
                'total_tax': total_tax,
                'total_discount': total_discount,
                'total_refunds': abs(total_refunds),
                'transaction_count': transaction_count,
                'items_sold': items_sold,
                'document_type_breakdown': document_type_breakdown,
                'payment_method_breakdown': {k: str(v) for k, v in payment_method_breakdown.items()}
            }

            return Response({
                'success': True,
                'report': report_data
            })

        except Exception as e:
            logger.error(f"Error generating Z report: {e}")
            return Response({
                'success': False,
                'error': 'Failed to generate report'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)