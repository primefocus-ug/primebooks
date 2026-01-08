from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db import transaction
from django.utils.dateparse import parse_datetime, parse_date
from sales.models import Sale, SaleItem, Payment
from customers.models import Customer
from decimal import Decimal
from sales.serializers import SaleSerializer
from customers.serializers import CustomerSerializer
import logging

logger = logging.getLogger(__name__)


class SaleViewSet(viewsets.ModelViewSet):
    """
    Sale CRUD operations with offline sync support
    """
    permission_classes = [IsAuthenticated]
    serializer_class = SaleSerializer

    def get_queryset(self):
        queryset = Sale.objects.select_related(
            'store', 'customer', 'created_by'
        ).prefetch_related('items')

        # Filter by store
        store_id = self.request.query_params.get('store_id')
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Filter by date range
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            start_dt = parse_date(start_date)
            queryset = queryset.filter(created_at__date__gte=start_dt)
        if end_date:
            end_dt = parse_date(end_date)
            queryset = queryset.filter(created_at__date__lte=end_dt)

        # Filter by document type
        document_type = self.request.query_params.get('document_type')
        if document_type:
            queryset = queryset.filter(document_type=document_type)

        # Filter by status
        sale_status = self.request.query_params.get('status')
        if sale_status:
            queryset = queryset.filter(status=sale_status)

        # Incremental sync
        updated_since = self.request.query_params.get('updated_since')
        if updated_since:
            try:
                updated_dt = parse_datetime(updated_since)
                queryset = queryset.filter(updated_at__gte=updated_dt)
            except (ValueError, TypeError):
                pass

        return queryset.order_by('-created_at')

    def list(self, request):
        queryset = self.get_queryset()[:100]  # Limit to recent 100

        data = []
        for sale in queryset:
            data.append(self._serialize_sale(sale))

        return Response({
            'results': data,
            'count': len(data)
        })

    def retrieve(self, request, pk=None):
        try:
            sale = Sale.objects.select_related(
                'store', 'customer', 'created_by'
            ).prefetch_related('items__product', 'items__service').get(pk=pk)

            return Response(self._serialize_sale(sale, include_items=True))

        except Sale.DoesNotExist:
            return Response(
                {'error': 'Sale not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @transaction.atomic
    def create(self, request):
        try:
            # Extract sale data
            sale_data = request.data.copy()
            items_data = sale_data.pop('items', [])

            # Check for client-generated ID (offline creation)
            client_id = sale_data.get('id')
            if client_id and isinstance(client_id, str) and client_id.startswith('offline_'):
                # This is an offline-created sale
                # Check if it already exists to prevent duplicates
                existing = Sale.objects.filter(
                    document_number=sale_data.get('document_number')
                ).first()

                if existing:
                    return Response(
                        {
                            'error': 'Sale with this document number already exists',
                            'existing_id': existing.id
                        },
                        status=status.HTTP_409_CONFLICT
                    )

            # Create sale
            sale = Sale.objects.create(
                store_id=sale_data['store_id'],
                customer_id=sale_data.get('customer_id'),
                created_by=request.user,
                document_type=sale_data.get('document_type', 'RECEIPT'),
                payment_method=sale_data.get('payment_method', 'CASH'),
                currency=sale_data.get('currency', 'UGX'),
                due_date=sale_data.get('due_date'),
                subtotal=Decimal(str(sale_data.get('subtotal', 0))),
                tax_amount=Decimal(str(sale_data.get('tax_amount', 0))),
                discount_amount=Decimal(str(sale_data.get('discount_amount', 0))),
                total_amount=Decimal(str(sale_data.get('total_amount', 0))),
                status=sale_data.get('status', 'COMPLETED'),
                payment_status=sale_data.get('payment_status', 'PAID'),
                transaction_type=sale_data.get('transaction_type', 'SALE'),
                notes=sale_data.get('notes', ''),
            )

            # Create sale items
            for item_data in items_data:
                SaleItem.objects.create(
                    sale=sale,
                    product_id=item_data.get('product_id'),
                    service_id=item_data.get('service_id'),
                    item_type=item_data.get('item_type', 'PRODUCT'),
                    quantity=item_data['quantity'],
                    unit_price=Decimal(str(item_data['unit_price'])),
                    total_price=Decimal(str(item_data['total_price'])),
                    tax_rate=item_data.get('tax_rate', 'A'),
                    tax_amount=Decimal(str(item_data.get('tax_amount', 0))),
                    discount=Decimal(str(item_data.get('discount', 0))),
                    discount_amount=Decimal(str(item_data.get('discount_amount', 0))),
                    description=item_data.get('description', ''),
                )

            # Update sale totals
            sale.update_totals()

            return Response(
                self._serialize_sale(sale, include_items=True),
                status=status.HTTP_201_CREATED
            )

        except Exception as e:
            logger.error(f"Sale creation error: {e}", exc_info=True)
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @transaction.atomic
    def update(self, request, pk=None):
        try:
            sale = Sale.objects.select_for_update().get(pk=pk)

            # Check if sale can be updated
            if sale.is_fiscalized:
                return Response(
                    {'error': 'Cannot update fiscalized sale'},
                    status=status.HTTP_403_FORBIDDEN
                )

            # Update allowed fields
            for field in ['notes', 'payment_status', 'status']:
                if field in request.data:
                    setattr(sale, field, request.data[field])

            sale.save()

            return Response(self._serialize_sale(sale))

        except Sale.DoesNotExist:
            return Response(
                {'error': 'Sale not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=True, methods=['post'])
    def void(self, request, pk=None):
        """Void a sale"""
        try:
            sale = Sale.objects.get(pk=pk)

            if sale.is_voided:
                return Response(
                    {'error': 'Sale is already voided'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            reason = request.data.get('reason', 'Voided by user')
            sale.void_sale(reason)

            return Response({
                'message': 'Sale voided successfully',
                'sale_id': sale.id
            })

        except Sale.DoesNotExist:
            return Response(
                {'error': 'Sale not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Sale void error: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    def _serialize_sale(self, sale, include_items=False):
        """Serialize sale object to dictionary"""
        data = {
            'id': sale.id,
            'transaction_id': str(sale.transaction_id),
            'document_number': sale.document_number,
            'document_type': sale.document_type,
            'store_id': sale.store_id,
            'customer_id': sale.customer_id,
            'created_by_id': sale.created_by_id,
            'payment_method': sale.payment_method,
            'currency': sale.currency,
            'due_date': sale.due_date.isoformat() if sale.due_date else None,
            'subtotal': str(sale.subtotal),
            'tax_amount': str(sale.tax_amount),
            'discount_amount': str(sale.discount_amount),
            'total_amount': str(sale.total_amount),
            'status': sale.status,
            'payment_status': sale.payment_status,
            'transaction_type': sale.transaction_type,
            'is_fiscalized': sale.is_fiscalized,
            'efris_invoice_number': sale.efris_invoice_number,
            'verification_code': sale.verification_code,
            'is_refunded': sale.is_refunded,
            'is_voided': sale.is_voided,
            'notes': sale.notes,
            'created_at': sale.created_at.isoformat(),
            'updated_at': sale.updated_at.isoformat(),
        }

        if include_items:
            items = []
            for item in sale.items.all():
                items.append({
                    'id': item.id,
                    'product_id': item.product_id,
                    'service_id': item.service_id,
                    'item_type': item.item_type,
                    'quantity': item.quantity,
                    'unit_price': str(item.unit_price),
                    'total_price': str(item.total_price),
                    'tax_rate': item.tax_rate,
                    'tax_amount': str(item.tax_amount),
                    'discount': str(item.discount),
                    'discount_amount': str(item.discount_amount),
                    'description': item.description,
                })
            data['items'] = items

        return data


class CustomerViewSet(viewsets.ModelViewSet):
    """
    Customer CRUD operations
    """
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerSerializer

    def get_queryset(self):
        queryset = Customer.objects.filter(is_active=True)

        # Filter by store
        store_id = self.request.query_params.get('store_id')
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Search
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(phone__icontains=search) |
                Q(email__icontains=search)
            )

        return queryset.order_by('name')

    def list(self, request):
        queryset = self.get_queryset()

        data = []
        for customer in queryset:
            data.append({
                'id': customer.id,
                'customer_id': customer.customer_id,
                'customer_type': customer.customer_type,
                'name': customer.name,
                'store_id': customer.store_id,
                'email': customer.email,
                'phone': customer.phone,
                'tin': customer.tin,
                'physical_address': customer.physical_address,
                'credit_limit': str(customer.credit_limit),
                'credit_balance': str(customer.credit_balance),
                'is_active': customer.is_active,
            })

        return Response({'results': data, 'count': len(data)})

    @transaction.atomic
    def create(self, request):
        try:
            # Validate business customer has TIN
            if request.data.get('customer_type') in ['BUSINESS', 'GOVERNMENT'] and \
                    not request.data.get('tin'):
                return Response(
                    {'error': 'TIN is required for business/government customers'},
                    status=status.HTTP_400_BAD_REQUEST
                )

            customer = Customer.objects.create(
                customer_type=request.data.get('customer_type', 'INDIVIDUAL'),
                name=request.data['name'],
                store_id=request.data['store_id'],
                email=request.data.get('email'),
                phone=request.data['phone'],
                tin=request.data.get('tin'),
                nin=request.data.get('nin'),
                physical_address=request.data.get('physical_address'),
                credit_limit=Decimal(str(request.data.get('credit_limit', 0))),
                allow_credit=request.data.get('allow_credit', False),
                created_by=request.user,
            )

            return Response({
                'id': customer.id,
                'customer_id': customer.customer_id,
                'name': customer.name,
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Customer creation error: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )