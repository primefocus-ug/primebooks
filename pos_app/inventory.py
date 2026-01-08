from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, F
from django.utils.dateparse import parse_datetime
from inventory.models import Product, Service, Category, Stock, StockMovement
from stores.models import Store
from inventory.serializers import ProductSerializer,ServiceSerializer,StockSerializer,StockMovementSerializer
import logging

logger = logging.getLogger(__name__)


class ProductViewSet(viewsets.ModelViewSet):
    """
    Product CRUD operations
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ProductSerializer

    def get_queryset(self):
        queryset = Product.objects.select_related('category', 'supplier').filter(is_active=True)

        # Filter by updated_since for incremental sync
        updated_since = self.request.query_params.get('updated_since')
        if updated_since:
            try:
                updated_dt = parse_datetime(updated_since)
                queryset = queryset.filter(updated_at__gte=updated_dt)
            except (ValueError, TypeError):
                pass

        # Filter by category
        category_id = self.request.query_params.get('category_id')
        if category_id:
            queryset = queryset.filter(category_id=category_id)

        # Search by name or SKU
        search = self.request.query_params.get('search')
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) |
                Q(sku__icontains=search) |
                Q(barcode__icontains=search)
            )

        return queryset.order_by('-updated_at')

    def list(self, request):
        queryset = self.get_queryset()

        # Simple serialization
        data = []
        for product in queryset:
            data.append({
                'id': product.id,
                'category_id': product.category_id,
                'supplier_id': product.supplier_id,
                'name': product.name,
                'sku': product.sku,
                'barcode': product.barcode,
                'description': product.description,
                'selling_price': str(product.selling_price),
                'cost_price': str(product.cost_price),
                'discount_percentage': str(product.discount_percentage),
                'tax_rate': product.tax_rate,
                'excise_duty_rate': str(product.excise_duty_rate),
                'unit_of_measure': product.unit_of_measure,
                'min_stock_level': product.min_stock_level,
                'is_active': product.is_active,
                'created_at': product.created_at.isoformat(),
                'updated_at': product.updated_at.isoformat(),
                'efris_is_uploaded': product.efris_is_uploaded,
                'efris_goods_code_field': product.efris_goods_code_field,
            })

        return Response({
            'results': data,
            'count': len(data)
        })

    def retrieve(self, request, pk=None):
        try:
            product = Product.objects.select_related('category', 'supplier').get(pk=pk)

            data = {
                'id': product.id,
                'category_id': product.category_id,
                'supplier_id': product.supplier_id,
                'name': product.name,
                'sku': product.sku,
                'barcode': product.barcode,
                'description': product.description,
                'selling_price': str(product.selling_price),
                'cost_price': str(product.cost_price),
                'discount_percentage': str(product.discount_percentage),
                'tax_rate': product.tax_rate,
                'excise_duty_rate': str(product.excise_duty_rate),
                'unit_of_measure': product.unit_of_measure,
                'min_stock_level': product.min_stock_level,
                'is_active': product.is_active,
                'created_at': product.created_at.isoformat(),
                'updated_at': product.updated_at.isoformat(),
                'efris_is_uploaded': product.efris_is_uploaded,
            }

            return Response(data)

        except Product.DoesNotExist:
            return Response(
                {'error': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND
            )

    def create(self, request):
        try:
            # Check for conflicts (version-based)
            existing = Product.objects.filter(sku=request.data.get('sku')).first()
            if existing:
                return Response(
                    {'error': 'Product with this SKU already exists'},
                    status=status.HTTP_409_CONFLICT
                )

            # Create product
            product = Product.objects.create(
                category_id=request.data.get('category_id'),
                supplier_id=request.data.get('supplier_id'),
                name=request.data['name'],
                sku=request.data['sku'],
                barcode=request.data.get('barcode'),
                description=request.data.get('description', ''),
                selling_price=request.data['selling_price'],
                cost_price=request.data['cost_price'],
                discount_percentage=request.data.get('discount_percentage', 0),
                tax_rate=request.data.get('tax_rate', 'A'),
                unit_of_measure=request.data.get('unit_of_measure', '103'),
                min_stock_level=request.data.get('min_stock_level', 5),
            )

            return Response({
                'id': product.id,
                'name': product.name,
                'sku': product.sku,
                'created_at': product.created_at.isoformat(),
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Product creation error: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    def update(self, request, pk=None):
        try:
            product = Product.objects.get(pk=pk)

            # Update fields
            for field in ['name', 'selling_price', 'cost_price', 'discount_percentage',
                          'tax_rate', 'description', 'min_stock_level']:
                if field in request.data:
                    setattr(product, field, request.data[field])

            product.save()

            return Response({
                'id': product.id,
                'updated_at': product.updated_at.isoformat(),
            })

        except Product.DoesNotExist:
            return Response(
                {'error': 'Product not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class ServiceViewSet(viewsets.ModelViewSet):
    """
    Service CRUD operations
    """
    permission_classes = [IsAuthenticated]
    serializer_class = ServiceSerializer

    def get_queryset(self):
        queryset = Service.objects.select_related('category').filter(is_active=True)

        # Filter by updated_since
        updated_since = self.request.query_params.get('updated_since')
        if updated_since:
            try:
                updated_dt = parse_datetime(updated_since)
                queryset = queryset.filter(updated_at__gte=updated_dt)
            except (ValueError, TypeError):
                pass

        return queryset.order_by('-updated_at')

    def list(self, request):
        queryset = self.get_queryset()

        data = []
        for service in queryset:
            data.append({
                'id': service.id,
                'category_id': service.category_id,
                'name': service.name,
                'code': service.code,
                'description': service.description,
                'unit_price': str(service.unit_price),
                'tax_rate': service.tax_rate,
                'unit_of_measure': service.unit_of_measure,
                'is_active': service.is_active,
                'created_at': service.created_at.isoformat(),
                'updated_at': service.updated_at.isoformat(),
            })

        return Response({'results': data, 'count': len(data)})


class CategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Category read operations
    """
    permission_classes = [IsAuthenticated]
    queryset = Category.objects.filter(is_active=True)

    def list(self, request):
        queryset = self.get_queryset()

        data = []
        for category in queryset:
            data.append({
                'id': category.id,
                'name': category.name,
                'code': category.code,
                'description': category.description,
                'category_type': category.category_type,
                'is_active': category.is_active,
            })

        return Response({'results': data, 'count': len(data)})


class StockViewSet(viewsets.ModelViewSet):
    """
    Stock management operations
    """
    permission_classes = [IsAuthenticated]
    serializer_class = StockSerializer

    def get_queryset(self):
        queryset = Stock.objects.select_related('product', 'store')

        # Filter by store
        store_id = self.request.query_params.get('store_id')
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        # Filter by product
        product_id = self.request.query_params.get('product_id')
        if product_id:
            queryset = queryset.filter(product_id=product_id)

        return queryset

    def list(self, request):
        queryset = self.get_queryset()

        data = []
        for stock in queryset:
            data.append({
                'id': stock.id,
                'product_id': stock.product_id,
                'store_id': stock.store_id,
                'quantity': str(stock.quantity),
                'low_stock_threshold': str(stock.low_stock_threshold),
                'reorder_quantity': str(stock.reorder_quantity),
                'last_updated': stock.last_updated.isoformat(),
            })

        return Response({'results': data, 'count': len(data)})

    def update(self, request, pk=None):
        try:
            stock = Stock.objects.select_for_update().get(pk=pk)

            # Merge changes for conflict resolution
            if 'quantity_change' in request.data:
                # Apply change instead of replacing
                stock.quantity = F('quantity') + request.data['quantity_change']
            elif 'quantity' in request.data:
                stock.quantity = request.data['quantity']

            stock.save()
            stock.refresh_from_db()

            return Response({
                'id': stock.id,
                'quantity': str(stock.quantity),
                'last_updated': stock.last_updated.isoformat(),
            })

        except Stock.DoesNotExist:
            return Response(
                {'error': 'Stock record not found'},
                status=status.HTTP_404_NOT_FOUND
            )


class StockMovementViewSet(viewsets.ModelViewSet):
    """
    Stock movement operations
    """
    permission_classes = [IsAuthenticated]
    serializer_class = StockMovementSerializer

    def get_queryset(self):
        queryset = StockMovement.objects.select_related('product', 'store')

        # Filter by store
        store_id = self.request.query_params.get('store_id')
        if store_id:
            queryset = queryset.filter(store_id=store_id)

        return queryset.order_by('-created_at')

    def list(self, request):
        queryset = self.get_queryset()[:100]  # Limit to recent 100

        data = []
        for movement in queryset:
            data.append({
                'id': movement.id,
                'product_id': movement.product_id,
                'store_id': movement.store_id,
                'movement_type': movement.movement_type,
                'quantity': str(movement.quantity),
                'reference': movement.reference,
                'notes': movement.notes,
                'created_at': movement.created_at.isoformat(),
                'created_by_id': movement.created_by_id,
            })

        return Response({'results': data, 'count': len(data)})

    def create(self, request):
        try:
            movement = StockMovement.objects.create(
                product_id=request.data['product_id'],
                store_id=request.data['store_id'],
                movement_type=request.data['movement_type'],
                quantity=request.data['quantity'],
                reference=request.data.get('reference', ''),
                notes=request.data.get('notes', ''),
                created_by=request.user,
            )

            return Response({
                'id': movement.id,
                'created_at': movement.created_at.isoformat(),
            }, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Stock movement creation error: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )