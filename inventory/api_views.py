"""
Inventory API Views
Comprehensive API endpoints for inventory management
"""

from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Sum, F, Count, Avg
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import (
    Category, Supplier, Product, Stock, StockMovement,
    ImportSession, ImportLog, ImportResult, Service
)
from .serializers import (
    CategorySerializer, CategoryDetailSerializer, CategoryBasicSerializer,
    SupplierSerializer, SupplierBasicSerializer,
    ProductSerializer, ProductListSerializer, ProductDetailSerializer,
    ProductBulkActionSerializer, EFRISProductSerializer,
    StockSerializer, StockMovementSerializer,
    ImportSessionSerializer, ImportLogSerializer, ImportResultSerializer,
    InventoryReportSerializer, StockMovementReportSerializer,
    LowStockReportSerializer, ValuationReportSerializer,
    ServiceSerializer, EFRISCommodityCategorySerializer
)
from company.models import EFRISCommodityCategory


class EFRISCommodityCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for EFRIS Commodity Categories (Read-only)
    Provides endpoints to browse and search EFRIS commodity categories
    """
    queryset = EFRISCommodityCategory.objects.all()
    serializer_class = EFRISCommodityCategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['commodity_category_code', 'commodity_category_name']
    filterset_fields = ['is_exempt', 'is_leaf_node', 'is_zero_rate']
    ordering_fields = ['commodity_category_code', 'commodity_category_name', 'last_synced']
    ordering = ['commodity_category_code']

    @action(detail=False, methods=['get'])
    def leaf_nodes(self, request):
        """Get only leaf node categories (selectable categories)"""
        categories = self.queryset.filter(is_leaf_node=True)
        serializer = self.get_serializer(categories, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def exempt_categories(self, request):
        """Get tax-exempt categories"""
        categories = self.queryset.filter(is_exempt=True)
        serializer = self.get_serializer(categories, many=True)
        return Response(serializer.data)


class CategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Product Categories
    Supports CRUD operations and EFRIS integration
    """
    queryset = Category.objects.filter(is_active=True)
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code', 'description']
    filterset_fields = ['is_active', 'efris_auto_sync', 'efris_is_uploaded']
    ordering_fields = ['name', 'code', 'created_at']
    ordering = ['name']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return CategoryDetailSerializer
        elif self.action == 'list':
            return CategoryBasicSerializer
        return CategorySerializer

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        """Get all products in this category"""
        category = self.get_object()
        products = category.products.filter(is_active=True)

        # Apply filters
        search = request.query_params.get('search', None)
        if search:
            products = products.filter(
                Q(name__icontains=search) | Q(sku__icontains=search)
            )

        serializer = ProductListSerializer(products, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def sync_to_efris(self, request, pk=None):
        """Sync category to EFRIS"""
        category = self.get_object()

        if not category.efris_commodity_category:
            return Response(
                {'error': 'EFRIS commodity category not set'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Add your EFRIS sync logic here
            category.efris_is_uploaded = True
            category.efris_upload_date = timezone.now()
            category.save()

            return Response({
                'status': 'success',
                'message': 'Category synced to EFRIS successfully',
                'upload_date': category.efris_upload_date
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get category statistics"""
        stats = {
            'total_categories': Category.objects.filter(is_active=True).count(),
            'efris_synced': Category.objects.filter(
                is_active=True, efris_is_uploaded=True
            ).count(),
            'auto_sync_enabled': Category.objects.filter(
                is_active=True, efris_auto_sync=True
            ).count(),
            'with_products': Category.objects.filter(
                is_active=True, products__isnull=False
            ).distinct().count()
        }
        return Response(stats)


class ServiceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Services
    Manages service catalog with EFRIS integration
    """
    queryset = Service.objects.filter(is_active=True)
    serializer_class = ServiceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'code', 'description']
    filterset_fields = ['is_active', 'category', 'tax_rate', 'efris_auto_sync_enabled']
    ordering_fields = ['name', 'code', 'unit_price', 'created_at']
    ordering = ['name']

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def sync_to_efris(self, request, pk=None):
        """Sync service to EFRIS"""
        service = self.get_object()

        if not service.efris_configuration_complete:
            return Response(
                {
                    'error': 'Service EFRIS configuration incomplete',
                    'missing_fields': service.get_efris_errors()
                },
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Add your EFRIS sync logic here
            service.efris_is_uploaded = True
            service.efris_upload_date = timezone.now()
            service.save()

            return Response({
                'status': 'success',
                'message': 'Service synced to EFRIS successfully',
                'efris_data': {
                    'commodity_category': service.efris_commodity_category_name,
                    'tax_rate': service.efris_tax_rate,
                    'final_price': str(service.final_price)
                }
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['post'])
    def bulk_sync(self, request):
        """Bulk sync services to EFRIS"""
        service_ids = request.data.get('service_ids', [])

        if not service_ids:
            return Response(
                {'error': 'No service IDs provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        services = Service.objects.filter(id__in=service_ids, is_active=True)
        results = {'success': [], 'failed': []}

        for service in services:
            if service.efris_configuration_complete:
                service.efris_is_uploaded = True
                service.efris_upload_date = timezone.now()
                service.save()
                results['success'].append(service.id)
            else:
                results['failed'].append({
                    'id': service.id,
                    'name': service.name,
                    'errors': service.get_efris_errors()
                })

        return Response(results)


class SupplierViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Suppliers
    Manages supplier information and relationships
    """
    queryset = Supplier.objects.filter(is_active=True)
    serializer_class = SupplierSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'tin', 'contact_person', 'email']
    filterset_fields = ['is_active', 'country']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

    @action(detail=True, methods=['get'])
    def products(self, request, pk=None):
        """Get all products from this supplier"""
        supplier = self.get_object()
        products = supplier.products.filter(is_active=True)
        serializer = ProductListSerializer(products, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def stats(self, request, pk=None):
        """Get supplier statistics"""
        supplier = self.get_object()
        products = supplier.products.filter(is_active=True)

        stats = {
            'total_products': products.count(),
            'total_stock_value': Stock.objects.filter(
                product__supplier=supplier
            ).aggregate(
                total=Sum(F('quantity') * F('product__cost_price'))
            )['total'] or 0,
            'active_products': products.filter(is_active=True).count(),
            'low_stock_products': Stock.objects.filter(
                product__supplier=supplier,
                quantity__lte=F('low_stock_threshold')
            ).count()
        }
        return Response(stats)


class ProductViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Products
    Comprehensive product management with EFRIS integration
    """
    queryset = Product.objects.select_related(
        'category', 'supplier'
    ).filter(is_active=True)
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'sku', 'barcode', 'description']
    filterset_fields = [
        'is_active', 'category', 'supplier', 'tax_rate',
        'efris_auto_sync_enabled', 'efris_is_uploaded'
    ]
    ordering_fields = ['name', 'sku', 'selling_price', 'created_at']
    ordering = ['name']

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return ProductDetailSerializer
        elif self.action == 'list':
            return ProductListSerializer
        elif self.action == 'efris_data':
            return EFRISProductSerializer
        return ProductSerializer

    @action(detail=False, methods=['post'])
    def bulk_action(self, request):
        """Perform bulk actions on products"""
        serializer = ProductBulkActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data
        product_ids = data['product_ids']
        action_type = data['action']

        products = Product.objects.filter(id__in=product_ids)

        if action_type == 'activate':
            products.update(is_active=True)
        elif action_type == 'deactivate':
            products.update(is_active=False)
        elif action_type == 'delete':
            products.delete()
        elif action_type == 'enable_efris_sync':
            products.update(efris_auto_sync_enabled=True)
        elif action_type == 'disable_efris_sync':
            products.update(efris_auto_sync_enabled=False)
        elif action_type == 'update_category':
            products.update(category_id=data['category_id'])
        elif action_type == 'update_supplier':
            products.update(supplier_id=data['supplier_id'])
        elif action_type == 'update_tax_rate':
            products.update(tax_rate=data['tax_rate'])

        return Response({
            'status': 'success',
            'affected_count': products.count(),
            'action': action_type
        })

    @action(detail=True, methods=['get'])
    def stock_levels(self, request, pk=None):
        """Get stock levels across all stores"""
        product = self.get_object()
        stocks = Stock.objects.filter(product=product).select_related('store')
        serializer = StockSerializer(stocks, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def movements(self, request, pk=None):
        """Get stock movement history"""
        product = self.get_object()
        days = int(request.query_params.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)

        movements = StockMovement.objects.filter(
            product=product,
            created_at__gte=start_date
        ).select_related('store', 'created_by').order_by('-created_at')

        serializer = StockMovementSerializer(movements, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def efris_data(self, request, pk=None):
        """Get EFRIS configuration data"""
        product = self.get_object()
        serializer = EFRISProductSerializer(product)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def sync_to_efris(self, request, pk=None):
        """Sync product to EFRIS"""
        product = self.get_object()

        errors = product.get_efris_errors()
        if errors:
            return Response(
                {'error': 'Product EFRIS configuration incomplete', 'errors': errors},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Add your EFRIS sync logic here
            product.efris_is_uploaded = True
            product.efris_upload_date = timezone.now()
            product.save()

            return Response({
                'status': 'success',
                'message': 'Product synced to EFRIS successfully',
                'efris_data': product.get_efris_data()
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        """Get products with low stock"""
        store_id = request.query_params.get('store', None)

        query = Stock.objects.filter(
            quantity__lte=F('low_stock_threshold')
        ).select_related('product', 'store')

        if store_id:
            query = query.filter(store_id=store_id)

        serializer = StockSerializer(query, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        """Get product analytics"""
        days = int(request.query_params.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)

        analytics = {
            'total_products': Product.objects.filter(is_active=True).count(),
            'low_stock_count': Stock.objects.filter(
                quantity__lte=F('low_stock_threshold')
            ).count(),
            'total_inventory_value': Stock.objects.aggregate(
                total=Sum(F('quantity') * F('product__cost_price'))
            )['total'] or 0,
            'efris_synced': Product.objects.filter(
                efris_is_uploaded=True
            ).count(),
            'recent_movements': StockMovement.objects.filter(
                created_at__gte=start_date
            ).count(),
            'top_selling': StockMovement.objects.filter(
                movement_type='SALE',
                created_at__gte=start_date
            ).values('product__name').annotate(
                total=Sum('quantity')
            ).order_by('-total')[:10]
        }

        return Response(analytics)


class StockViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Stock Management
    Handles stock levels across stores
    """
    queryset = Stock.objects.select_related('product', 'store')
    serializer_class = StockSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['store', 'product']
    ordering_fields = ['quantity', 'last_updated']
    ordering = ['-last_updated']

    @action(detail=True, methods=['post'])
    def adjust(self, request, pk=None):
        """Adjust stock quantity"""
        stock = self.get_object()
        adjustment = Decimal(request.data.get('adjustment', 0))
        reason = request.data.get('reason', '')

        if not adjustment:
            return Response(
                {'error': 'Adjustment value required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        old_quantity = stock.quantity
        stock.quantity += adjustment

        if stock.quantity < 0:
            return Response(
                {'error': 'Stock cannot be negative'},
                status=status.HTTP_400_BAD_REQUEST
            )

        stock.save()

        # Create movement record
        movement_type = 'ADJUSTMENT_IN' if adjustment > 0 else 'ADJUSTMENT_OUT'
        StockMovement.objects.create(
            product=stock.product,
            store=stock.store,
            movement_type=movement_type,
            quantity=abs(adjustment),
            notes=reason,
            created_by=request.user
        )

        return Response({
            'status': 'success',
            'old_quantity': old_quantity,
            'new_quantity': stock.quantity,
            'adjustment': adjustment
        })

    @action(detail=True, methods=['post'])
    def physical_count(self, request, pk=None):
        """Record physical stock count"""
        stock = self.get_object()
        counted_quantity = Decimal(request.data.get('quantity', 0))
        notes = request.data.get('notes', '')

        old_quantity = stock.quantity
        difference = counted_quantity - old_quantity

        stock.quantity = counted_quantity
        stock.last_physical_count = timezone.now()
        stock.last_physical_count_quantity = counted_quantity
        stock.save()

        # Create adjustment movement if there's a difference
        if difference != 0:
            movement_type = 'ADJUSTMENT_IN' if difference > 0 else 'ADJUSTMENT_OUT'
            StockMovement.objects.create(
                product=stock.product,
                store=stock.store,
                movement_type=movement_type,
                quantity=abs(difference),
                notes=f"Physical count adjustment: {notes}",
                created_by=request.user
            )

        return Response({
            'status': 'success',
            'old_quantity': old_quantity,
            'counted_quantity': counted_quantity,
            'difference': difference,
            'count_date': stock.last_physical_count
        })

    @action(detail=False, methods=['get'])
    def valuation(self, request):
        """Get total stock valuation"""
        store_id = request.query_params.get('store', None)

        query = Stock.objects.all()
        if store_id:
            query = query.filter(store_id=store_id)

        valuation = query.aggregate(
            total_cost=Sum(F('quantity') * F('product__cost_price')),
            total_selling=Sum(F('quantity') * F('product__selling_price')),
            total_items=Sum('quantity')
        )

        return Response(valuation)


class StockMovementViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Stock Movements
    Tracks all stock transactions
    """
    queryset = StockMovement.objects.select_related(
        'product', 'store', 'created_by'
    ).order_by('-created_at')
    serializer_class = StockMovementSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['movement_type', 'product', 'store', 'created_by']
    ordering_fields = ['created_at', 'quantity', 'total_value']
    ordering = ['-created_at']

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get movement summary"""
        days = int(request.query_params.get('days', 30))
        start_date = timezone.now() - timedelta(days=days)

        movements = StockMovement.objects.filter(created_at__gte=start_date)

        summary = {
            'total_movements': movements.count(),
            'by_type': movements.values('movement_type').annotate(
                count=Count('id'),
                total_quantity=Sum('quantity')
            ),
            'total_value': movements.aggregate(
                Sum('total_value')
            )['total_value__sum'] or 0
        }

        return Response(summary)


class ImportSessionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Import Sessions
    Manages bulk import operations
    """
    queryset = ImportSession.objects.order_by('-created_at')
    serializer_class = ImportSessionSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['status', 'import_mode']
    ordering_fields = ['created_at', 'completed_at']
    ordering = ['-created_at']

    @action(detail=True, methods=['get'])
    def logs(self, request, pk=None):
        """Get import logs for this session"""
        session = self.get_object()
        logs = ImportLog.objects.filter(session=session).order_by('timestamp')
        serializer = ImportLogSerializer(logs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def results(self, request, pk=None):
        """Get import results for this session"""
        session = self.get_object()
        results = ImportResult.objects.filter(session=session).order_by('row_number')
        serializer = ImportResultSerializer(results, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def retry(self, request, pk=None):
        """Retry failed import"""
        session = self.get_object()

        if session.status != 'FAILED':
            return Response(
                {'error': 'Only failed imports can be retried'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Add your retry logic here
        return Response({'status': 'Retry initiated'})


class ReportViewSet(viewsets.ViewSet):
    """
    ViewSet for Inventory Reports
    Generates various inventory reports
    """
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def inventory(self, request):
        """Generate inventory report"""
        store_id = request.query_params.get('store', None)
        category_id = request.query_params.get('category', None)

        stocks = Stock.objects.select_related(
            'product', 'product__category', 'store'
        )

        if store_id:
            stocks = stocks.filter(store_id=store_id)
        if category_id:
            stocks = stocks.filter(product__category_id=category_id)

        report_data = []
        for stock in stocks:
            product = stock.product
            report_data.append({
                'product_id': product.id,
                'product_name': product.name,
                'sku': product.sku,
                'category': product.category.name if product.category else None,
                'store': stock.store.name,
                'current_stock': stock.quantity,
                'reorder_level': stock.low_stock_threshold,
                'unit_of_measure': product.unit_of_measure,
                'cost_price': product.cost_price,
                'selling_price': product.selling_price,
                'final_price': product.final_price,
                'total_cost': stock.quantity * product.cost_price,
                'total_value': stock.quantity * product.final_price,
                'status': stock.status,
                'last_updated': stock.last_updated,
                'efris_sync_enabled': product.efris_auto_sync_enabled,
                'efris_uploaded': product.efris_is_uploaded
            })

        serializer = InventoryReportSerializer(report_data, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def movements(self, request):
        """Generate stock movement report"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        store_id = request.query_params.get('store')

        movements = StockMovement.objects.select_related(
            'product', 'store', 'created_by'
        ).order_by('-created_at')

        if start_date:
            movements = movements.filter(created_at__gte=start_date)
        if end_date:
            movements = movements.filter(created_at__lte=end_date)
        if store_id:
            movements = movements.filter(store_id=store_id)

        report_data = []
        for movement in movements:
            report_data.append({
                'date': movement.created_at.date(),
                'product_name': movement.product.name,
                'product_sku': movement.product.sku,
                'store_name': movement.store.name,
                'movement_type': movement.movement_type,
                'quantity': movement.quantity,
                'unit_price': movement.unit_price,
                'total_value': movement.total_value,
                'reference': movement.reference,
                'notes': movement.notes,
                'created_by': movement.created_by.get_full_name() if movement.created_by else None
            })

        serializer = StockMovementReportSerializer(report_data, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        """Generate low stock report"""
        store_id = request.query_params.get('store')

        stocks = Stock.objects.filter(
            quantity__lte=F('low_stock_threshold')
        ).select_related('product', 'product__category', 'store')

        if store_id:
            stocks = stocks.filter(store_id=store_id)

        report_data = []
        for stock in stocks:
            product = stock.product
            reorder_gap = stock.low_stock_threshold - stock.quantity

            report_data.append({
                'product_id': product.id,
                'product_name': product.name,
                'sku': product.sku,
                'category': product.category.name if product.category else None,
                'store': stock.store.name,
                'current_stock': stock.quantity,
                'reorder_level': stock.low_stock_threshold,
                'reorder_gap': reorder_gap,
                'stock_percentage': stock.stock_percentage,
                'total_cost': stock.quantity * product.cost_price,
                'recommended_order_qty': reorder_gap * Decimal('1.5'),
                'priority': 'HIGH' if stock.quantity < stock.low_stock_threshold * Decimal('0.5') else 'MEDIUM',
                'status': stock.status
            })

        serializer = LowStockReportSerializer(report_data, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def valuation(self, request):
        """Generate inventory valuation report"""
        store_id = request.query_params.get('store')
        category_id = request.query_params.get('category')

        stocks = Stock.objects.select_related(
            'product', 'product__category', 'store'
        )

        if store_id:
            stocks = stocks.filter(store_id=store_id)
        if category_id:
            stocks = stocks.filter(product__category_id=category_id)

        report_data = []
        for stock in stocks:
            product = stock.product
            total_cost = stock.quantity * product.cost_price
            total_selling = stock.quantity * product.selling_price
            total_final = stock.quantity * product.final_price
            potential_profit = total_final - total_cost
            profit_margin = (potential_profit / total_cost * 100) if total_cost > 0 else 0

            report_data.append({
                'product_id': product.id,
                'product_name': product.name,
                'sku': product.sku,
                'category': product.category.name if product.category else None,
                'store': stock.store.name,
                'quantity': stock.quantity,
                'cost_price': product.cost_price,
                'selling_price': product.selling_price,
                'final_price': product.final_price,
                'total_cost': total_cost,
                'total_selling': total_selling,
                'total_final': total_final,
                'potential_profit': potential_profit,
                'profit_margin': profit_margin,
                'unit_of_measure': product.unit_of_measure
            })

        serializer = ValuationReportSerializer(report_data, many=True)
        return Response(serializer.data)